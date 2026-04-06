import time
from typing import Dict, List, Optional

import requests

from config import (
    logger, RETRIES, SOCKET_TIMEOUT,
    DEEZER_ARTIST_LIMIT, DEEZER_TRACK_LIMIT, CACHE_MAXSIZE,
)
from models import Artist, Album, Track


class MusicSearcher:
    BASE = "https://api.deezer.com"

    def __init__(self):
        self._session       = requests.Session()
        self._artist_cache: Dict[str, List[Artist]] = {}
        self._album_cache:  Dict[str, List[Album]]  = {}
        self._track_cache:  Dict[str, List[Track]]  = {}
        self._search_cache: Dict[str, List[Track]]  = {}

    def _cache_set(self, cache: dict, key: str, value) -> None:
        """Inserisce nella cache con limite CACHE_MAXSIZE (eviction FIFO)."""
        if len(cache) >= CACHE_MAXSIZE:
            del cache[next(iter(cache))]
        cache[key] = value

    def _get(self, url: str, params: Optional[Dict] = None) -> Dict:
        time.sleep(0.1)
        logger.debug(f"[Deezer] GET {url} params={params}")
        for attempt in range(RETRIES):
            try:
                r = self._session.get(url, params=params, timeout=SOCKET_TIMEOUT)
                if r.status_code == 429:
                    retry_after = int(r.headers.get("Retry-After", 5))
                    logger.warning(f"[Deezer] Rate limited, attendo {retry_after}s")
                    time.sleep(retry_after)
                    continue
                if not r.ok:
                    logger.warning(f"[Deezer] HTTP {r.status_code} per {url}: {r.text[:300]}")
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    raise RuntimeError(
                        f"Deezer error {data['error'].get('code')}: {data['error'].get('message')}"
                    )
                return data
            except requests.RequestException as e:
                logger.warning(f"[Deezer] Tentativo {attempt+1}/{RETRIES} fallito: {e}")
                if attempt == RETRIES - 1:
                    raise RuntimeError(f"Richiesta fallita dopo {RETRIES} tentativi: {e}")
                time.sleep(1 * (2 ** attempt))

    def search_artist(self, name: str) -> List[Artist]:
        if name in self._artist_cache:
            logger.debug(f"[Deezer] Cache hit artista: {name}")
            return self._artist_cache[name]
        data = self._get(f"{self.BASE}/search/artist", {"q": name, "limit": DEEZER_ARTIST_LIMIT})
        result = [
            Artist(
                id=a["id"],
                nome=a["name"],
                followers=a.get("nb_fan", 0),
                nb_album=a.get("nb_album", 0),
            )
            for a in data.get("data", []) if a.get("id")
        ]
        self._cache_set(self._artist_cache, name, result)
        return result

    def search_track(self, query: str) -> List[Track]:
        if query in self._search_cache:
            logger.debug(f"[Deezer] Cache hit canzone: {query}")
            return self._search_cache[query]
        data = self._get(f"{self.BASE}/search/track", {"q": query, "limit": DEEZER_TRACK_LIMIT})
        result = [
            Track(
                id=t["id"],
                nome=t["title"],
                artisti=[t["artist"]["name"]] if t.get("artist") else [],
                artist_id=t["artist"]["id"] if t.get("artist") else None,
                album=t["album"]["title"] if t.get("album") else "",
                album_id=t["album"]["id"] if t.get("album") else None,
                duration=t.get("duration", 0),
            )
            for t in data.get("data", []) if t.get("id")
        ]
        self._cache_set(self._search_cache, query, result)
        return result

    def get_artist_albums(self, artist_id: int) -> List[Album]:
        key = str(artist_id)
        if key in self._album_cache:
            logger.debug(f"[Deezer] Cache hit album artista: {artist_id}")
            return self._album_cache[key]
        url = f"{self.BASE}/artist/{artist_id}/albums"
        albums, seen = [], set()
        while url:
            data = self._get(url, {"limit": 50} if not albums else None)
            for a in data.get("data", []):
                if a["id"] not in seen:
                    seen.add(a["id"])
                    albums.append(Album(
                        id=a["id"],
                        nome=a["title"],
                        anno=a.get("release_date", "")[:4] or "N/A",
                        artisti=[a["artist"]["name"]] if a.get("artist") else [],
                        artist_id=a["artist"]["id"] if a.get("artist") else artist_id,
                    ))
            url = data.get("next")
        self._cache_set(self._album_cache, key, albums)
        return albums

    def get_album_tracks(self, album_id: int) -> List[Track]:
        key = str(album_id)
        if key in self._track_cache:
            logger.debug(f"[Deezer] Cache hit tracce album: {album_id}")
            return self._track_cache[key]
        data = self._get(f"{self.BASE}/album/{album_id}/tracks")
        result = [
            Track(
                id=t["id"],
                nome=t["title"],
                artisti=[t["artist"]["name"]] if t.get("artist") else [],
                numero=t.get("track_position", 0),
                duration=t.get("duration", 0),
            )
            for t in data.get("data", [])
        ]
        self._cache_set(self._track_cache, key, result)
        return result

    def get_album_details(self, album_id: int) -> Dict:
        data = self._get(f"{self.BASE}/album/{album_id}")
        genres = [g["name"] for g in data.get("genres", {}).get("data", [])]
        return {
            "genre":        ", ".join(genres),
            "album_artist": data["artist"]["name"] if data.get("artist") else "",
            "nb_tracks":    data.get("nb_tracks", 0),
            "label":        data.get("label", ""),
            "anno":         data.get("release_date", "")[:4] or "",
            "cover_xl":     data.get("cover_xl", ""),
        }
