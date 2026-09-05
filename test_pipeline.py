"""
Dry-run della pipeline Deezer → YouTube senza scaricare nulla.
Uso:
    python test_pipeline.py "nome artista"
    python test_pipeline.py "nome artista" "nome album"   # filtra su un album specifico
"""
import sys
import logging
sys.stdout.reconfigure(encoding="utf-8")
from logica.config import logger
logger.handlers[1].setLevel(logging.DEBUG)  # handlers[1] = StreamHandler (console)

from logica.searcher import MusicSearcher
from logica.youtube import YouTubeSearcher


def run(artist_query: str, album_filter: str = ""):
    searcher = MusicSearcher()

    # ── 1. Cerca artista su Deezer ───────────────────────────
    print(f"\n[Deezer] Ricerca artista: '{artist_query}'")
    artists = searcher.search_artist(artist_query)
    if not artists:
        print("Nessun artista trovato.")
        return

    artist = artists[0]
    print(f"  → {artist.nome}  (id={artist.id}, fan={artist.followers:,})\n")

    # ── 2. Album dell'artista ────────────────────────────────
    print(f"[Deezer] Carico album di {artist.nome}...")
    albums = searcher.get_artist_albums(artist.id)
    print(f"  → {len(albums)} album trovati")

    if album_filter:
        albums = [a for a in albums if album_filter.lower() in a.nome.lower()]
        if not albums:
            print(f"  Nessun album corrisponde a '{album_filter}'.")
            return
        print(f"  → filtrati a {len(albums)} con '{album_filter}'")

    # ── 3. Per ogni album: tracce + YouTube scoring ──────────
    for album in albums:
        print(f"\n{'─'*60}")
        print(f"[Album] '{album.nome}' ({album.anno})")

        tracks = searcher.get_album_tracks(album.id)
        print(f"  → {len(tracks)} tracce\n")

        for track in tracks:
            art = track.artisti[0] if track.artisti else artist.nome
            query = f"{art} - {track.nome}"
            print(f"  [{track.numero:02d}] {track.nome}  ({track.duration}s)  → '{query}'")
            # I punteggi escono dai logger.debug già presenti in YouTubeSearcher.search
            urls = YouTubeSearcher.search(query, artist=art, title=track.nome,
                                          duration=track.duration,
                                          original_artist=artist.nome)
            if not urls:
                print("       ✗ nessun risultato\n")
            else:
                print(f"       ✓ {len(urls)} risultati, scelto: {urls[0]}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python test_pipeline.py <artista> [album]")
        sys.exit(1)
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
