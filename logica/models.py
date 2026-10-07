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
    anno: str = ""


@dataclass
class QueueItem:
    query: str
    label: str
    meta: dict = field(default_factory=dict)
    destination: str = ""
    result_url: str = ""      # URL YouTube da cui e' stato scaricato (compilato da download_single)
    result_status: str = ""   # "ok" | "esistente" | "errore" | "nessun url" | "annullato"
    result_note: str = ""     # avvisi su un download riuscito (es. caso limite)
    result_error: str = ""    # motivo del fallimento (ultima eccezione per URL)
    result_check: str = ""    # "valido" | "SOSPETTO: motivo" (controllo header mp3)
    result_ranking: list = field(default_factory=list)  # candidati YouTube con score (per il blocco di log)
    result_winner: str = ""   # link primo in classifica (scoring), anche se poi ha vinto un altro
    result_cached: bool = False  # link preso dalla cache interna: classifica non disponibile
