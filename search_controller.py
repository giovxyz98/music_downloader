from typing import Dict, List

from cache import CacheManager
from models import Album, Artist, Track
from searcher import MusicSearcher


class SearchController:
    """Punto unico da cui la UI accede alla ricerca Deezer, registrando
    automaticamente le ricerche riuscite nella cronologia."""

    def __init__(self, searcher: MusicSearcher, cache: CacheManager):
        self._searcher = searcher
        self._cache = cache

    def search_artist(self, query: str) -> List[Artist]:
        artists = self._searcher.search_artist(query)
        if artists:
            self._cache.add_search("artista", query)
        return artists

    def search_track(self, query: str) -> List[Track]:
        tracks = self._searcher.search_track(query)
        if tracks:
            self._cache.add_search("canzone", query)
        return tracks

    def get_artist_albums(self, artist_id: int) -> List[Album]:
        return self._searcher.get_artist_albums(artist_id)

    def get_album_tracks(self, album_id: int) -> List[Track]:
        return self._searcher.get_album_tracks(album_id)

    def get_album_details(self, album_id: int) -> Dict:
        return self._searcher.get_album_details(album_id)
