import re
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Callable, List, Optional

from .cache import CacheManager
from .config import logger
from .downloader import AudioDownloader, tag_file, check_mp3, mp3_bitrate_kbps
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
        self._yt_info_cache:   dict = {}   # query -> {url: {"title", "channel"}}, accanto a _yt_url_cache

        self.cancel_event = threading.Event()

    # ── Metadati album (genere, numero tracce) ──────────────────

    def get_genre(self, album_id: str) -> tuple:
        if not album_id:
            logger.debug("[Genre] get_genre chiamato senza album_id, ritorno ('', 0)")
            return "", 0
        if album_id in self._genre_cache:
            logger.debug(f"[Genre] cache hit per album_id={album_id}: genre={self._genre_cache[album_id]!r}")
            return self._genre_cache[album_id], self._nb_tracks_cache.get(album_id, 0)
        try:
            details   = self._searcher.get_album_details(album_id)
            genre     = details.get("genre", "")
            nb_tracks = details.get("nb_tracks", 0)
            logger.debug(f"[Genre] cache miss per album_id={album_id}, richiesto a Deezer: genre={genre!r} nb_tracks={nb_tracks}")
            self.prime_genre_cache(album_id, genre, nb_tracks)
            return genre, nb_tracks
        except Exception as e:
            logger.warning(f"[Genre] errore recupero dettagli album_id={album_id}: {e}")
            return "", 0

    def prime_genre_cache(self, album_id: str, genre: str, nb_tracks: int) -> None:
        """Permette di riusare dettagli album gia' scaricati altrove (es. dalla
        UI durante la navigazione) evitando una chiamata API ridondante."""
        logger.debug(f"[Genre] prime_genre_cache album_id={album_id} genre={genre!r} nb_tracks={nb_tracks}")
        self._genre_cache[album_id]     = genre
        self._nb_tracks_cache[album_id] = nb_tracks

    # ── Risoluzione URL / metadati traccia ──────────────────────

    def resolve_url(self, item: QueueItem, tag: str = "") -> List[str]:
        cached = self._yt_url_cache.get(item.query)
        if cached:
            logger.debug(f"[Cache]{tag} YouTube hit: '{item.query}' → {cached[0]}")
            item.result_cached, item.result_winner = True, cached[0]
            item.result_info = dict(self._yt_info_cache.get(item.query, {}))
            return cached
        meta = item.meta or {}
        diag: dict = {}
        urls = YouTubeSearcher.search(
            item.query,
            artist          = meta.get("artist", ""),
            title           = meta.get("title", ""),
            duration        = meta.get("duration", 0),
            original_artist = meta.get("albumartist", ""),
            tag             = tag,
            diagnostics     = diag,
        )
        item.result_note = diag.get("note", "")
        item.result_ranking = diag.get("ranking", [])
        item.result_winner = urls[0] if urls else ""
        item.result_info = {c["url"]: {"title": c["title"], "channel": c["channel"]}
                            for c in item.result_ranking}
        if urls:
            self._yt_url_cache[item.query] = urls
            self._yt_info_cache[item.query] = dict(item.result_info)
        else:
            item.result_error = diag.get("reason", "")
        return urls

    def prepare_meta(self, item: QueueItem, genre_info: tuple = None) -> dict:
        meta_before      = dict(item.meta or {})
        meta             = dict(meta_before)
        genre, nb_tracks = genre_info if genre_info is not None \
                           else self.get_genre(meta.get("album_id", ""))
        if genre:
            meta["genre"] = genre
        if meta.get("tracknumber") and nb_tracks:
            meta["tracknumber"] = f"{meta['tracknumber']}/{nb_tracks}"
        if meta != meta_before:
            logger.debug(f"[Meta] prepare_meta per '{item.label}': {meta_before} → {meta}")
        return meta

    # ── Download singola traccia ────────────────────────────────

    @staticmethod
    def _filename(item: QueueItem, meta: dict) -> str:
        title    = meta.get("title") or item.label
        artist   = meta.get("artist") or ""
        raw_name = f"{artist} - {title}" if artist else title
        return sanitize_filename(raw_name)

    @staticmethod
    def _check_label(filepath) -> str:
        problem = check_mp3(str(filepath))
        return f"SOSPETTO: {problem}" if problem else "valido"

    def already_downloaded(self, item: QueueItem, destination: str) -> bool:
        """True se il file di destinazione esiste gia' (titolo e artista non
        dipendono dal genere, quindi bastano i metadati grezzi)."""
        dest = item.destination or destination
        return Path(dest, f"{self._filename(item, item.meta or {})}.mp3").exists()

    BLOCK_SEP = "═" * 70

    @staticmethod
    def _short_views(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.0f}k"
        return str(n)

    @staticmethod
    def _short_error(msg: str) -> str:
        msg = msg.replace("ERROR: ", "").strip()
        m = re.search(r"HTTP Error \d+", msg)
        return m.group(0) if m else msg[:60]

    @staticmethod
    def _label(item: QueueItem, url: str) -> str:
        """'titolo  [canale]  link' (as-is da YouTube) se noto, altrimenti solo il link."""
        info = (item.result_info or {}).get(url)
        if not info:
            return url
        return f"{info['title']}  [{info['channel']}]  {url}"

    def _log_block(self, item: QueueItem, tag: str, meta: dict, outcome: str,
                   failed: dict = None, extra: List[str] = None) -> None:
        """Un solo blocco di log per canzone, scritto con UNA chiamata cosi' le righe
        di worker diversi non si mescolano. `failed` = {url: errore breve}."""
        failed = failed or {}
        title = meta.get("title") or item.label
        artist = meta.get("artist") or ""
        album = meta.get("album") or "Singoli"
        lines = [self.BLOCK_SEP, f"{tag} {artist} - {title}   ({album})"]
        if item.result_ranking:
            # titolo e canale COMPLETI (mai troncati): le colonne si allineano sul piu' lungo del blocco
            wc = max(len(c["channel"]) for c in item.result_ranking)
            wt = max(len(c["title"]) for c in item.result_ranking)
            for n, c in enumerate(item.result_ranking, start=1):
                mark = f"   ✗ {failed[c['url']]}" if c["url"] in failed else ""
                lines.append(f"  {n}. {c['score']:>4}  {self._short_views(c['views']):>6}  "
                             f"{c['channel']:<{wc}}  {c['title']:<{wt}}  {c['id']}{mark}")
        elif item.result_cached:
            lines.append("  (classifica non disponibile: link da cache)")
        if item.result_winner:
            lines.append(f"  scoring:  {self._label(item, item.result_winner)}")
        lines.extend(extra or [])
        lines.append(f"  {outcome}")
        logger.info("\n".join(lines))

    def download_single(self, item: QueueItem, destination: str,
                        progress_cb=None, genre_info: tuple = None,
                        urls: List[str] = None, tag: str = "") -> tuple:
        dest     = item.destination or destination
        meta     = self.prepare_meta(item, genre_info)
        title    = meta.get("title") or item.label
        artist   = meta.get("artist") or ""
        filename = self._filename(item, meta)

        logger.debug(f"[Download]{tag} Inizio: '{item.label}' → query='{item.query}' "
                     f"(artist={artist!r}, title={title!r}, meta={meta})")

        if Path(dest, f"{filename}.mp3").exists():
            item.result_status = "esistente"
            item.result_check = self._check_label(Path(dest, f"{filename}.mp3"))
            self._log_block(item, tag, meta, "già presente  " + (
                self._label(item, item.result_url) if item.result_url
                else "(link originale non noto)"))
            return True, None

        if urls is None:
            urls = self.resolve_url(item, tag=tag)
        if not urls:
            item.result_status = "nessun url"
            item.result_error = item.result_error or f"nessun risultato YouTube valido per '{item.query}'"
            self._log_block(item, tag, meta, f"NON SCARICATA: {item.result_error}")
            return False, item.label

        logger.debug(f"[Download]{tag} {len(urls)} URL candidati in ordine di score: {urls}")
        errors: List[str] = []
        failed: dict = {}
        for i, url in enumerate(urls):
            try:
                logger.debug(f"[Download]{tag} Tentativo {i+1}/{len(urls)}: {url}")
                filepath = AudioDownloader.download(url, dest, filename=filename,
                                                    progress_callback=progress_cb, tag=tag)
                logger.debug(f"[Download]{tag} File scaricato: {filepath}, applico i tag ID3")
                tag_file(filepath, meta, tag=tag)
                item.result_url, item.result_status = url, "ok"
                info = (item.result_info or {}).get(url, {})
                item.result_title, item.result_channel = info.get("title", ""), info.get("channel", "")
                item.result_check = self._check_label(filepath)
                kbps = mp3_bitrate_kbps(filepath)
                ok_mark = "OK" if i == 0 else f"OK* (candidato {i + 1})"
                extra = [f"  !!! {item.result_note}"] if item.result_note else []
                self._log_block(item, tag, meta,
                                f"download: {ok_mark} {kbps}k {item.result_check}  {self._label(item, url)}",
                                failed, extra)
                return True, None
            except Exception as e:
                logger.debug(f"[Download]{tag} URL {i+1} fallito per '{item.label}': {e}")
                failed[url] = self._short_error(str(e))
                errors.append(f"{url} → {str(e).strip()[:200]}")
                continue

        item.result_url, item.result_status = urls[0], "errore"
        info = (item.result_info or {}).get(urls[0], {})
        item.result_title, item.result_channel = info.get("title", ""), info.get("channel", "")
        item.result_error = " || ".join(errors)
        self._log_block(item, tag, meta, f"FALLITA: tutti i {len(urls)} link hanno dato errore", failed)
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
        width      = len(str(total)) if total else 1
        lock       = threading.Lock()
        state      = {"successi": 0, "falliti": [], "completed": 0}
        search_q:   Queue = Queue()
        download_q: Queue = Queue()

        started = time.monotonic()
        logger.info("\n".join(["█" * 70, f"INIZIO ESECUZIONE  {total} tracce → {destination}", "█" * 70]))
        for idx, item in enumerate(queue):
            logger.debug(f"[Batch] Coda #{idx + 1:0{width}d}/{total}: '{item.label}' query='{item.query}'")

        def resolver():
            seen: set = set()
            for item in queue:
                if genre_info is None:
                    aid = item.meta.get("album_id", "")
                    if aid and aid not in seen:
                        seen.add(aid)
                        self.get_genre(aid)
            for idx, item in enumerate(queue):
                if self.cancel_event.is_set():
                    break
                search_q.put((idx, item))
            for _ in range(self._search_workers):
                search_q.put(None)

        def search_worker():
            while True:
                entry = search_q.get()
                if entry is None:
                    break
                idx, item = entry
                item_tag = f"[#{idx + 1:0{width}d}/{total}]"
                if self.cancel_event.is_set():
                    download_q.put((item, [], item_tag))
                    continue
                # File gia' presente: niente ricerca su YouTube, download_single
                # lo segnalera' come "esistente" prima di toccare gli URL.
                urls = [] if self.already_downloaded(item, destination) \
                       else self.resolve_url(item, tag=item_tag)
                download_q.put((item, urls, item_tag))

        def download_worker():
            while True:
                entry = download_q.get()
                if entry is None:
                    break
                item, urls, item_tag = entry
                item_id = id(item)

                if self.cancel_event.is_set():
                    with lock:
                        state["completed"] += 1
                        state["falliti"].append(f"{item.label} (annullato)")
                        c = state["completed"]
                    logger.info(f"[Download]{item_tag} Annullato: '{item.label}'")
                    item.result_status = "annullato"
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
                                                   genre_info, urls=urls, tag=item_tag)
                except Exception as e:
                    logger.error(
                        f"[Worker]{item_tag} Eccezione non gestita per '{item.label}': {e}", exc_info=True)
                    ok, err = False, f"{item.label} ({str(e)[:40]})"
                    item.result_status, item.result_error = "errore", f"eccezione: {e}"

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

        elapsed = int(time.monotonic() - started)
        end = ["█" * 70,
               f"FINE ESECUZIONE  {state['successi']}/{total} successi, {len(state['falliti'])} falliti"
               f"  ({elapsed // 60}m {elapsed % 60:02d}s)"]
        end += [f"  fallita: {f}" for f in state["falliti"]]
        end.append("█" * 70)
        logger.info("\n".join(end))

        self._cache.add_download(
            self._history_entry(queue, destination, artist_name, state["successi"])
        )

        if on_batch_done:
            on_batch_done(state["successi"], state["falliti"], queue, destination, artist_name)
