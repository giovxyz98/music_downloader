import time
from typing import Dict, Iterable, List, Optional

from .models import QueueItem

DEFAULT_TRACK_SECONDS = 210   # usata quando nessuna canzone del txt ha la durata
SIZE_OVERHEAD = 1.10          # misurato su 50 mp3 veri: ~10% oltre durata * bitrate


def estimate_total_bytes(queue: List[QueueItem], bitrate_kbps: int) -> int:
    """Spazio stimato degli mp3 (CBR): durata * bitrate. Le canzoni senza durata
    nel txt valgono la media di quelle che ce l'hanno."""
    durations = [i.meta.get("duration", 0) for i in queue]
    known = [d for d in durations if d]
    fallback = sum(known) / len(known) if known else DEFAULT_TRACK_SECONDS
    seconds = sum(d or fallback for d in durations)
    return int(seconds * bitrate_kbps * 1000 / 8 * SIZE_OVERHEAD)


def format_bytes(n: float) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    return f"{n / 1024 ** 2:.0f} MB"


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


class ProgressTracker:
    """Avanzamento complessivo e tempo rimanente di una coda. Nessuna
    dipendenza da tkinter; chiamare i metodi sempre dallo stesso thread.

    L'ETA e' reale: misura quanto lavoro (canzoni scaricate davvero, in frazioni)
    e' stato fatto dal via e ne ricava la velocita' effettiva, parallelismo
    incluso. Le canzoni gia' presenti su disco (note in anticipo, `existing_ids`)
    sono escluse da ETA e spazio stimato. Quelle che falliscono subito non contano
    come lavoro, e la loro quota osservata finora viene applicata a quelle ancora
    da fare."""

    MIN_WORK = 0.5       # canzoni-equivalenti scaricate prima di fidarsi dell'ETA
    MIN_ELAPSED = 5.0    # secondi
    MIN_SAMPLE = 5       # canzoni concluse prima di stimare quante saranno saltate

    def __init__(self, queue: List[QueueItem], bitrate_kbps: int,
                 existing_ids: Iterable[int] = ()):
        self.total = len(queue)
        self._existing = set(existing_ids)      # id() delle canzoni gia' scaricate prima
        self.existing_count = len(self._existing)
        self.estimated_bytes = estimate_total_bytes(
            [i for i in queue if id(i) not in self._existing], bitrate_kbps)
        self._existing_done = 0   # di quelle gia' presenti, quante sono state saltate
        self.downloaded_bytes = 0
        self._partial: Dict[int, float] = {}
        self._finished = 0        # tutte le canzoni concluse, comunque
        self._work_done = 0       # solo quelle scaricate davvero
        self._t0: Optional[float] = None

    def start(self) -> None:
        self._t0 = time.monotonic()

    def update(self, item_id: int, percent: float) -> None:
        self._partial[item_id] = percent / 100

    def complete(self, item_id: int, item: QueueItem, size_bytes: int = 0) -> None:
        self._partial.pop(item_id, None)
        self._finished += 1
        if item_id in self._existing:
            self._existing.discard(item_id)
            self._existing_done += 1
        if item.result_status == "ok":
            self._work_done += 1
            self.downloaded_bytes += size_bytes

    @property
    def finished(self) -> int:
        return self._finished

    @property
    def bar_fraction(self) -> float:
        if not self.total:
            return 0.0
        return min((self._finished + sum(self._partial.values())) / self.total, 1.0)

    def remaining_seconds(self) -> Optional[float]:
        """None finche' non ci sono abbastanza dati per una stima sensata."""
        if self._t0 is None:
            return None
        elapsed = time.monotonic() - self._t0
        work = self._work_done + sum(self._partial.values())
        if work < self.MIN_WORK or elapsed < self.MIN_ELAPSED:
            return None
        # Quante delle canzoni non ancora iniziate saranno download veri (le altre
        # sono gia' presenti o falliscono subito): la quota osservata finora.
        considered = self._finished - self._existing_done
        real_share = self._work_done / considered if considered >= self.MIN_SAMPLE else 1.0
        in_progress = sum(1 - p for p in self._partial.values())
        unstarted = self.total - self._finished - len(self._partial) - len(self._existing)
        to_do = in_progress + max(unstarted, 0) * real_share
        return to_do * elapsed / work
