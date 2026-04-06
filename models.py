from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Artist:
    id: int
    nome: str
    followers: int = 0
    nb_album: int = 0


@dataclass
class Album:
    id: int
    nome: str
    anno: str = "N/A"
    artisti: List[str] = field(default_factory=list)
    artist_id: Optional[int] = None


@dataclass
class Track:
    id: int
    nome: str
    artisti: List[str] = field(default_factory=list)
    numero: int = 0
    duration: int = 0
    album: str = ""
    album_id: Optional[int] = None
    artist_id: Optional[int] = None


@dataclass
class QueueItem:
    query: str
    label: str
    meta: dict = field(default_factory=dict)
    destination: str = ""
