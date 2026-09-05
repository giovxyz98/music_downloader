import threading
from pathlib import Path
from queue import Queue
from typing import Callable, List, Optional

from .cache import CacheManager
from .config import logger
from .downloader import AudioDownloader, tag_file
from .text_utils import sanitize_filename
from .models import QueueItem
from .searcher import MusicSearcher
from .youtube import YouTubeSearcher


class DownloadManager:
    """Orchestrazione della pipeline di download: risoluzione URL YouTube,
    preparazione metadati, download effettivo, tagging e registrazione in
    cronologia. Nessuna dipendenza da tkinter: comunica lo stato di
    avanzamento tramite callback semplici, che il chiamante (la UI) e'
    libero di inoltrare al thread grafico come preferisce."""

    def __init__(self, downloader: AudioDownloader, searcher: MusicSearcher,
                 cache: CacheManager, max_workers: int, search_workers: int):
        self._downloader     = downloader
        self._searcher       = searcher
        self._cache          = cache
        self._max_workers    = max_workers
        self._search_workers = search_workers

        self._genre_cache:     dict = {}
        self._nb_tracks_cache: dict = {}
        self._yt_url_cache:    dict = {}

        self.cancel_event = threading.Event()

    # ── Metadati album (genere, numero tracce) ──────────────────

    def get_genre(self, album_id: str) -> tuple:
        if not album_id:
            return "", 0
        if album_id in self._genre_cache:
            return self._genre_cache[album_id], self._nb_tracks_cache.get(album_id, 0)
        try:
            details   = self._searcher.get_album_details(int(album_id))
            genre     = details.get("genre", "")
            nb_tracks = details.get("nb_tracks", 0)
            self.prime_genre_cache(album_id, genre, nb_tracks)
            return genre, nb_tracks
        except Exception:
            return "", 0

    def prime_genre_cache(self, album_id: str, genre: str, nb_tracks: int) -> None:
        """Permette di riusare dettagli album gia' scaricati altrove (es. dalla
        UI durante la navigazione) evitando una chiamata API ridondante."""
        self._genre_cache[album_id]     = genre
        self._nb_tracks_cache[album_id] = nb_tracks

    # ── Risoluzione URL / metadati traccia ──────────────────────

    def resolve_url(self, item: QueueItem) -> List[str]:
        cached = self._yt_url_cache.get(item.query)
        if cached:
            logger.debug(f"[Cache] YouTube hit: '{item.query}'")
            return cached
        meta = item.meta or {}
        urls = YouTubeSearcher.search(
            item.query,
            artist          = meta.get("artist", ""),
            title           = meta.get("title", ""),
            duration        = meta.get("duration", 0),
            original_artist = meta.get("albumartist", ""),
        )
        if urls:
            self._yt_url_cache[item.query] = urls
        return urls

    def prepare_meta(self, item: QueueItem, genre_info: tuple = None) -> dict:
        meta             = dict(item.meta or {})
        genre, nb_tracks = genre_info if genre_info is not None \
                           else self.get_genre(meta.get("album_id", ""))
        if genre:
            meta["genre"] = genre
        if meta.get("tracknumber") and nb_tracks:
            meta["tracknumber"] = f"{meta['tracknumber']}/{nb_tracks}"
        return meta

    # ── Download singola traccia ────────────────────────────────

    def download_single(self, item: QueueItem, destination: str,
                        progress_cb=None, genre_info: tuple = None,
                        urls: List[str] = None) -> tuple:
        dest     = item.destination or destination
        meta     = self.prepare_meta(item, genre_info)
        title    = meta.get("title") or item.label
        artist   = meta.get("artist") or ""
        raw_name = f"{artist} - {title}" if artist else title
        filename = sanitize_filename(raw_name)

        logger.info(f"[Download] Inizio: '{item.label}' → query='{item.query}'")

        if Path(dest, f"{filename}.mp3").exists():
            logger.info(f"[Download] Saltato (già esiste): {filename}.mp3")
            return True, None

        if urls is None:
            urls = self.resolve_url(item)
        if not urls:
            logger.warning(f"[Download] Nessun URL trovato per: '{item.label}'")
            return False, item.label

        for i, url in enumerate(urls):
            try:
                logger.debug(f"[Download] Tentativo {i+1}/{len(urls)}: {url}")
                filepath = AudioDownloader.download(url, dest, filename=filename,
                                                    progress_callback=progress_cb)
                tag_file(filepath, meta)
                logger.info(f"[Download] Completato: {filepath}")
                return True, None
            except Exception as e:
                logger.warning(f"[Download] URL {i+1} fallito per '{item.label}': {e}")
                continue

        logger.error(f"[Download] Tutti gli URL esauriti per: '{item.label}'")
        return False, item.label

    # ── Batch (coda intera) ──────────────────────────────────────

    def _history_entry(self, queue: List[QueueItem], destination: str,
                       artist_name: Optional[str], successi: int) -> dict:
        totale = len(queue)
        if totale == 1:
            entry_type = "track"
            nome    = queue[0].label
            artista = queue[0].meta.get("artist", "") or artist_name or ""
        else:
            entry_type = "album"
            nome    = queue[0].meta.get("album", "") or "Album"
            artista = artist_name or queue[0].meta.get("albumartist", "")
        return {
            "type":        entry_type,
            "nome":        nome,
            "artista":     artista,
            "destination": destination,
            "successi":    successi,
            "totale":      totale,
        }

    def run_batch(self, queue: List[QueueItem], destination: str, *,
                 genre_info: tuple = None, artist_name: str = None,
                 on_track_started: Callable = None,
                 on_progress: Callable = None,
                 on_track_completed: Callable = None,
                 on_batch_done: Callable = None) -> None:
        """Esegue il download dell'intera coda con pipeline a tre stadi
        (resolver → ricerca URL → download), bloccando il thread chiamante
        finche' non e' tutto completo. Gli hook on_* vengono invocati dal
        thread worker che li genera: se il chiamante deve aggiornare una UI,
        e' suo compito marshalizzarli sul thread principale."""
        total      = len(queue)
        lock       = threading.Lock()
        state      = {"successi": 0, "falliti": [], "completed": 0}
        search_q:   Queue = Queue()
        download_q: Queue = Queue()

        logger.info(f"[Batch] Inizio download: {total} tracce → {destination}")

        def resolver():
            seen: set = set()
            for item in queue:
                if genre_info is None:
                    aid = item.meta.get("album_id", "")
                    if aid and aid not in seen:
                        seen.add(aid)
                        self.get_genre(aid)
            for item in queue:
                if self.cancel_event.is_set():
                    break
                search_q.put(item)
            for _ in range(self._search_workers):
                search_q.put(None)

        def search_worker():
            while True:
                item = search_q.get()
                if item is None:
                    break
                if self.cancel_event.is_set():
                    download_q.put((item, []))
                    continue
                urls = self.resolve_url(item)
                download_q.put((item, urls))

        def download_worker():
            while True:
                entry = download_q.get()
                if entry is None:
                    break
                item, urls = entry
                item_id = id(item)

                if self.cancel_event.is_set():
                    with lock:
                        state["completed"] += 1
                        state["falliti"].append(f"{item.label} (annullato)")
                        c = state["completed"]
                    logger.info(f"[Download] Annullato: '{item.label}'")
                    if on_track_completed:
                        on_track_completed(item, item_id, False, c, total)
                    continue

                if on_track_started:
                    on_track_started(item, item_id)

                def progress_cb(percent, _id=item_id):
                    if on_progress:
                        on_progress(_id, percent)

                try:
                    ok, err = self.download_single(item, destination, progress_cb,
                                                   genre_info, urls=urls)
                except Exception as e:
                    logger.error(
                        f"[Worker] Eccezione non gestita per '{item.label}': {e}", exc_info=True)
                    ok, err = False, f"{item.label} ({str(e)[:40]})"

                with lock:
                    state["completed"] += 1
                    if ok:
                        state["successi"] += 1
                    else:
                        state["falliti"].append(err)
                    c = state["completed"]

                if on_track_completed:
                    on_track_completed(item, item_id, ok, c, total)

        resolver_t        = threading.Thread(target=resolver,         daemon=True)
        search_threads    = [threading.Thread(target=search_worker,   daemon=True)
                             for _ in range(self._search_workers)]
        download_threads  = [threading.Thread(target=download_worker, daemon=True)
                             for _ in range(self._max_workers)]

        resolver_t.start()
        for t in search_threads + download_threads:
            t.start()
        resolver_t.join()
        for t in search_threads:
            t.join()
        for _ in range(self._max_workers):
            download_q.put(None)
        for t in download_threads:
            t.join()

        logger.info(
            f"[Batch] Fine: {state['successi']}/{total} successi, "
            f"{len(state['falliti'])} falliti"
        )

        self._cache.add_download(
            self._history_entry(queue, destination, artist_name, state["successi"])
        )

        if on_batch_done:
            on_batch_done(state["successi"], state["falliti"], queue, destination, artist_name)
