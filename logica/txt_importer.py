import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .config import logger
from .models import QueueItem
from .text_utils import sanitize_filename


@dataclass
class TrackRequest:
    title: str
    artists: str = ""     # opzionale: il primo e' l'artista principale
    duration: int = 0     # secondi, opzionale (aiuta a scegliere il video giusto)


@dataclass
class AlbumRequest:
    title: str
    year: str = ""
    tracks: List[TrackRequest] = field(default_factory=list)


@dataclass
class ArtistRequest:
    name: str
    albums:  List[AlbumRequest] = field(default_factory=list)
    singles: List[TrackRequest] = field(default_factory=list)
    ignored: List[str] = field(default_factory=list)   # righe del txt non interpretabili


@dataclass
class ArtistPlan:
    """Cosa scaricare per un artista: ogni QueueItem ha gia' la sua cartella
    di destinazione."""
    artist_name: str
    folder: Path
    queue: List[QueueItem] = field(default_factory=list)
    ignored: List[str] = field(default_factory=list)


_ALBUM_RE   = re.compile(r"\[album\]\s*(.+?)\s*(?:\((\d{4})\))?\s*$", re.IGNORECASE)
_SINGLE_RE  = re.compile(r"\[singol[oi]\]\s*(.*)", re.IGNORECASE)
_TRACKNO_RE = re.compile(r"^\d+\s*[.)]\s+")


def _parse_track(text: str) -> TrackRequest:
    """'Titolo | Artisti | m:ss' (artisti e durata opzionali)."""
    parts = [p.strip() for p in text.split(" | ")]
    duration = 0
    if len(parts) > 2 and re.fullmatch(r"\d+:\d{2}", parts[2]):
        m, sec = parts[2].split(":")
        duration = int(m) * 60 + int(sec)
    return TrackRequest(title=parts[0], artists=parts[1] if len(parts) > 1 else "",
                        duration=duration)


def parse_txt(path: Path, orphans: Optional[List[str]] = None) -> List[ArtistRequest]:
    """Formato:
        # Nome Artista
        [Album] Titolo album (2001)      <- anno opzionale
        1. Prima traccia | Artisti | 3:05  <- numero, artisti e durata opzionali
        2. Seconda traccia
        [Singoli]                        <- oppure "[Singolo] Titolo" su una riga
        Titolo canzone | Artista, Ospite | 2:41
    Le righe sotto [Album] sono tracce di quell'album, quelle sotto [Singoli]
    sono singoli. Righe vuote e righe che iniziano con // sono ignorate.
    Le righe non interpretabili finiscono in ArtistRequest.ignored (o in
    `orphans` se compaiono prima del primo artista)."""
    artists: List[ArtistRequest] = []
    artist: Optional[ArtistRequest] = None
    album: Optional[AlbumRequest] = None
    in_singles = False

    for n, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue

        if line.startswith("#"):
            artist = ArtistRequest(name=line.lstrip("#").strip())
            artists.append(artist)
            album, in_singles = None, False
            continue
        if artist is None:
            msg = f"riga {n} ignorata (nessun artista '# ...' prima): {raw!r}"
            logger.warning(f"[Txt] {msg}")
            if orphans is not None:
                orphans.append(msg)
            continue

        m = _ALBUM_RE.match(line)
        if m:
            album = AlbumRequest(title=m.group(1), year=m.group(2) or "")
            artist.albums.append(album)
            in_singles = False
            continue

        m = _SINGLE_RE.match(line)
        if m:
            album, in_singles = None, True
            if m.group(1).strip():
                artist.singles.append(_parse_track(m.group(1)))
            continue

        track = _parse_track(_TRACKNO_RE.sub("", line))
        if album is not None:
            album.tracks.append(track)
        elif in_singles:
            artist.singles.append(track)
        else:
            msg = f"riga {n} ignorata (sotto nessun [Album]/[Singoli]): {raw!r}"
            logger.warning(f"[Txt] {msg}")
            artist.ignored.append(msg)
    return artists


def _make_item(artist: str, albumartist: str, track: TrackRequest, album: str,
               year: str, number: str, destination: Path) -> QueueItem:
    return QueueItem(
        query=f"{artist} - {track.title}",
        label=f"{track.title}  ({album})" if album else f"{track.title}  (singolo)",
        meta={
            "title":       track.title,
            "artist":      artist,
            "albumartist": albumartist,
            "album":       album,
            "year":        year,
            "tracknumber": number,
            "album_id":    "",   # nessuna API: il genere resta vuoto
            "duration":    track.duration,
        },
        destination=str(destination),
    )


def _primary_artist(track: TrackRequest, default: str) -> str:
    """L'artista principale e' il primo dell'elenco: e' quello usato per la
    ricerca su YouTube e per il tag (gli ospiti sono gia' nel titolo)."""
    return track.artists.split(", ")[0].strip() if track.artists else default


def build_plan(req: ArtistRequest, root: Path) -> ArtistPlan:
    """Trasforma le richieste del txt in un piano di download. Nessuna rete,
    nessuna dipendenza da tkinter: i metadati sono quelli scritti nel txt."""
    folder = root / sanitize_filename(req.name)
    plan = ArtistPlan(artist_name=req.name, folder=folder, ignored=req.ignored)

    for album in req.albums:
        album_folder = folder / sanitize_filename(album.title)
        total = len(album.tracks)
        for i, track in enumerate(album.tracks, 1):
            plan.queue.append(_make_item(
                _primary_artist(track, req.name), req.name, track, album.title,
                album.year, f"{i}/{total}", album_folder))
    for track in req.singles:
        artist = _primary_artist(track, req.name)
        plan.queue.append(_make_item(artist, artist, track, "", "", "", folder))
    return plan


def count_tracks(plans: List[ArtistPlan]) -> int:
    return sum(len(p.queue) for p in plans)


def format_tree(plans: List[ArtistPlan], root: Path) -> str:
    """Anteprima ad albero (cartelle + file .mp3) di cio' che verra' creato
    dentro `root`. I nomi file sono gli stessi che usera' il download."""
    tree: dict = {}
    for plan in plans:
        for item in plan.queue:
            node = tree
            for part in (*Path(item.destination).relative_to(root).parts,
                         sanitize_filename(f"{item.meta['artist']} - {item.meta['title']}") + ".mp3"):
                node = node.setdefault(part, {})

    lines = [f"{root.name or root}/"]

    def render(node: dict, prefix: str) -> None:
        for i, (name, children) in enumerate(node.items()):
            last = i == len(node) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{name}{'/' if children else ''}")
            render(children, prefix + ("    " if last else "│   "))

    render(tree, "")
    return "\n".join(lines)
