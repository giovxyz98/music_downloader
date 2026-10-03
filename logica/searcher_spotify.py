import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import requests

from .config import (
    logger, RETRIES, SOCKET_TIMEOUT,
    SPOTIFY_ARTIST_LIMIT, SPOTIFY_TRACK_LIMIT, CACHE_MAXSIZE,
)
from .models import Artist, Album, Track
from .spotify_auth import SpotifyAuth

# Se Spotify chiede di aspettare più di questo (es. un blocco temporaneo
# dell'app per troppe chiamate, non un normale rate limit), meglio fallire
# subito con un errore chiaro piuttosto che bloccare il thread per ore.
MAX_RETRY_AFTER_WAIT = 60


class MusicSearcherSpotify:
    BASE = "https://api.spotify.com/v1"

    def __init__(self):
        self._session       = requests.Session()
        self._auth          = SpotifyAuth()
        self._artist_cache: Dict[str, List[Artist]] = {}
        self._album_cache:  Dict[str, List[Album]]  = {}
        self._track_cache:  Dict[str, List[Track]]  = {}
        self._search_cache: Dict[str, List[Track]]  = {}
        self._genre_cache:  Dict[str, str]           = {}
        self._features_cache: Dict[str, List[Album]] = {}

    def _cache_set(self, cache: dict, key: str, value) -> None:
        """Inserisce nella cache con limite CACHE_MAXSIZE (eviction FIFO)."""
        if len(cache) >= CACHE_MAXSIZE:
            evicted_key = next(iter(cache))
            del cache[evicted_key]
            logger.debug(f"[Spotify][Cache] limite {CACHE_MAXSIZE} raggiunto, evict FIFO di {evicted_key!r}")
        cache[key] = value
        logger.debug(f"[Spotify][Cache] set {key!r} ({len(cache)}/{CACHE_MAXSIZE} entry in questa cache)")

    def _get(self, url: str, params: Optional[Dict] = None) -> Dict:
        time.sleep(0.1)
        logger.debug(f"[Spotify] GET {url} params={params}")
        for attempt in range(RETRIES):
            t0 = time.perf_counter()
            try:
                headers = {"Authorization": f"Bearer {self._auth.get_token()}"}
                r = self._session.get(url, params=params, headers=headers, timeout=SOCKET_TIMEOUT)
                elapsed = time.perf_counter() - t0
                logger.debug(f"[Spotify] risposta status={r.status_code} bytes={len(r.content)} tempo={elapsed:.3f}s per {url}")
                if r.status_code == 401:
                    logger.warning("[Spotify] Token rifiutato (401), forzo il rinnovo e riprovo")
                    self._auth.force_refresh()
                    continue
                if r.status_code == 429:
                    retry_after = int(r.headers.get("Retry-After", 5))
                    if retry_after > MAX_RETRY_AFTER_WAIT:
                        raise RuntimeError(
                            f"Spotify rate limit troppo lungo per aspettare (Retry-After={retry_after}s, "
                            f"~{retry_after / 3600:.1f}h) su {url}"
                        )
                    logger.warning(f"[Spotify] Rate limited, attendo {retry_after}s")
                    time.sleep(retry_after)
                    continue
                if not r.ok:
                    logger.warning(f"[Spotify] HTTP {r.status_code} per {url}: {r.text[:300]}")
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    raise RuntimeError(
                        f"Spotify error {data['error'].get('status')}: {data['error'].get('message')}"
                    )
                logger.debug(f"[Spotify] body: chiavi={list(data.keys())}")
                return data
            except requests.RequestException as e:
                logger.warning(f"[Spotify] Tentativo {attempt+1}/{RETRIES} fallito: {e}")
                if attempt == RETRIES - 1:
                    raise RuntimeError(f"Richiesta fallita dopo {RETRIES} tentativi: {e}")
                time.sleep(1 * (2 ** attempt))

    def search_artist(self, name: str) -> List[Artist]:
        name = name.lower().strip()
        if name in self._artist_cache:
            logger.debug(f"[Spotify] Cache hit artista: {name}")
            return self._artist_cache[name]
        data = self._get(f"{self.BASE}/search", {"q": name, "type": "artist", "limit": SPOTIFY_ARTIST_LIMIT})
        raw = data.get("artists", {}).get("items", [])
        result = [
            Artist(
                id=a["id"],
                nome=a["name"],
                followers=a.get("followers", {}).get("total", 0),
                nb_album=0,  # Spotify non fornisce il conteggio album nella ricerca artista
            )
            for a in raw if a.get("id")
        ]
        logger.debug(f"[Spotify] search_artist('{name}') → {len(result)} artisti: {[(a.id, a.nome) for a in result[:10]]}")
        self._cache_set(self._artist_cache, name, result)
        return result

    def search_track(self, query: str) -> List[Track]:
        query = query.lower().strip()
        if query in self._search_cache:
            logger.debug(f"[Spotify] Cache hit canzone: {query}")
            return self._search_cache[query]
        data = self._get(f"{self.BASE}/search", {"q": query, "type": "track", "limit": SPOTIFY_TRACK_LIMIT})
        raw = data.get("tracks", {}).get("items", [])
        result = [
            Track(
                id=t["id"],
                nome=t["name"],
                artisti=[t["artists"][0]["name"]] if t.get("artists") else [],
                artist_id=t["artists"][0]["id"] if t.get("artists") else None,
                album=t["album"]["name"] if t.get("album") else "",
                album_id=t["album"]["id"] if t.get("album") else None,
                duration=t.get("duration_ms", 0) // 1000,
            )
            for t in raw if t.get("id")
        ]
        logger.debug(f"[Spotify] search_track('{query}') → {len(result)} tracce")
        self._cache_set(self._search_cache, query, result)
        return result

    def get_artist_albums(self, artist_id: str) -> List[Album]:
        key = str(artist_id)
        if key in self._album_cache:
            logger.debug(f"[Spotify] Cache hit album artista: {artist_id}")
            return self._album_cache[key]
        url = f"{self.BASE}/artists/{artist_id}/albums"
        params = {"limit": 10, "include_groups": "album,single"}
        albums, seen = [], set()
        page = 0
        while url:
            page += 1
            data = self._get(url, params if not albums else None)
            dupes = 0
            for a in data.get("items", []):
                if a["id"] not in seen:
                    seen.add(a["id"])
                    albums.append(Album(
                        id=a["id"],
                        nome=a["name"],
                        anno=a.get("release_date", "")[:4] or "N/A",
                        artisti=[a["artists"][0]["name"]] if a.get("artists") else [],
                        artist_id=a["artists"][0]["id"] if a.get("artists") else artist_id,
                    ))
                else:
                    dupes += 1
            logger.debug(f"[Spotify] get_artist_albums({artist_id}) pagina {page}: +{len(data.get('items', [])) - dupes} nuovi, {dupes} duplicati, next={data.get('next')}")
            url = data.get("next")
        logger.debug(f"[Spotify] get_artist_albums({artist_id}) → {len(albums)} album totali in {page} pagine")
        self._cache_set(self._album_cache, key, albums)
        return albums

    def _get_appears_on_albums(self, artist_id: str) -> List[Dict]:
        """Album/singoli di ALTRI artisti in cui l'artista cercato compare
        (include_groups=appears_on), come JSON grezzo: serve solo da
        intermedio per get_artist_features, non è esposto all'esterno."""
        url = f"{self.BASE}/artists/{artist_id}/albums"
        params = {"limit": 10, "include_groups": "appears_on"}
        raw_albums, seen = [], set()
        page = 0
        while url:
            page += 1
            data = self._get(url, params if not raw_albums else None)
            dupes = 0
            for a in data.get("items", []):
                if a["id"] not in seen:
                    seen.add(a["id"])
                    raw_albums.append(a)
                else:
                    dupes += 1
            logger.debug(f"[Spotify] _get_appears_on_albums({artist_id}) pagina {page}: +{len(data.get('items', [])) - dupes} nuovi, {dupes} duplicati, next={data.get('next')}")
            url = data.get("next")
        logger.debug(f"[Spotify] _get_appears_on_albums({artist_id}) → {len(raw_albums)} album totali in {page} pagine")
        return raw_albums

    def get_artist_features(self, artist_id: str) -> List[Track]:
        """Canzoni (non album) in cui l'artista cercato compare come
        featuring su un rilascio di un altro artista. Scandisce ogni album
        "appears_on" e tiene solo le tracce dove l'artista cercato è
        davvero tra gli artisti — così anche un album fatto interamente
        insieme a un altro viene mostrato spacchettato in singole canzoni,
        non come un blocco unico da aprire a mano."""
        key = str(artist_id)
        if key in self._features_cache:
            logger.debug(f"[Spotify] Cache hit featuring artista: {artist_id}")
            return self._features_cache[key]

        albums = self._get_appears_on_albums(artist_id)

        def fetch_from_album(a: Dict) -> List[Track]:
            album_id   = a["id"]
            album_name = a["name"]
            album_anno = a.get("release_date", "")[:4] or "N/A"
            found: List[Track] = []
            url = f"{self.BASE}/albums/{album_id}/tracks"
            first_page = True
            while url:
                data = self._get(url, {"limit": 10} if first_page else None)
                first_page = False
                for t in data.get("items", []):
                    artist_ids = [art.get("id") for art in t.get("artists", [])]
                    if artist_id not in artist_ids:
                        continue
                    found.append(Track(
                        id=t["id"],
                        nome=t["name"],
                        artisti=[art["name"] for art in t.get("artists", [])],
                        artist_id=artist_id,
                        numero=t.get("track_number", 0),
                        duration=t.get("duration_ms", 0) // 1000,
                        album=album_name,
                        album_id=album_id,
                        anno=album_anno,
                    ))
                url = data.get("next")
            return found

        # Un album alla volta sarebbe troppo lento (un artista può comparire
        # come featuring su centinaia di rilasci): le chiamate per-album sono
        # indipendenti, quindi le paralleliziamo con un pool ridotto per non
        # saturare il rate limit Spotify.
        tracks: List[Track] = []
        seen_tracks = set()
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="spotify-features") as pool:
            for found in pool.map(fetch_from_album, albums):
                for track in found:
                    if track.id not in seen_tracks:
                        seen_tracks.add(track.id)
                        tracks.append(track)

        logger.debug(f"[Spotify] get_artist_features({artist_id}) → {len(tracks)} canzoni in featuring su {len(albums)} album")
        self._cache_set(self._features_cache, key, tracks)
        return tracks

    def get_album_tracks(self, album_id: str) -> List[Track]:
        key = str(album_id)
        if key in self._track_cache:
            logger.debug(f"[Spotify] Cache hit tracce album: {album_id}")
            return self._track_cache[key]
        url = f"{self.BASE}/albums/{album_id}/tracks"
        result = []
        page = 0
        while url:
            page += 1
            data = self._get(url, {"limit": 10} if not result else None)
            for t in data.get("items", []):
                result.append(Track(
                    id=t["id"],
                    nome=t["name"],
                    artisti=[t["artists"][0]["name"]] if t.get("artists") else [],
                    numero=t.get("track_number", 0),
                    duration=t.get("duration_ms", 0) // 1000,
                ))
            url = data.get("next")
        logger.debug(f"[Spotify] get_album_tracks({album_id}) → {len(result)} tracce: {[(t.numero, t.nome, t.duration) for t in result]}")
        self._cache_set(self._track_cache, key, result)
        return result

    def _get_artist_genres(self, artist_id: str) -> str:
        """Spotify non espone il genere sull'album: unica fonte residua sono
        i generi dell'artista (spesso generici o assenti, ma è l'unico dato
        disponibile senza tornare a un'API terza)."""
        if not artist_id:
            return ""
        if artist_id in self._genre_cache:
            return self._genre_cache[artist_id]
        try:
            data = self._get(f"{self.BASE}/artists/{artist_id}")
            genre = ", ".join(data.get("genres", []))
        except Exception as e:
            logger.warning(f"[Spotify] errore recupero generi artista {artist_id}: {e}")
            genre = ""
        self._cache_set(self._genre_cache, artist_id, genre)
        return genre

    def get_album_details(self, album_id: str) -> Dict:
        data = self._get(f"{self.BASE}/albums/{album_id}")
        artists  = data.get("artists", [])
        images   = data.get("images", [])
        artist_id = artists[0]["id"] if artists else None
        details = {
            "genre":        self._get_artist_genres(artist_id),
            "album_artist": artists[0]["name"] if artists else "",
            "nb_tracks":    data.get("total_tracks", 0),
            "label":        data.get("label", ""),
            "anno":         data.get("release_date", "")[:4] or "",
            "cover_xl":     images[0]["url"] if images else "",
        }
        logger.debug(f"[Spotify] get_album_details({album_id}) → {details}")
        return details
