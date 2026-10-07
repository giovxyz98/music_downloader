import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, List

from .cache import CacheManager
from .config import MAX_WORKERS, SEARCH_WORKERS
from .download_manager import DownloadManager
from .downloader import AudioDownloader
from .txt_importer import ArtistPlan


def make_manager() -> DownloadManager:
    # Nessun searcher: senza album_id nei metadati il genere non viene mai richiesto.
    return DownloadManager(AudioDownloader(), None, CacheManager(),
                           MAX_WORKERS, SEARCH_WORKERS)


REPORT_NAME = "report_download.txt"


class ReportWriter:
    """Report dell'artista, riscritto dopo ogni canzone completata (cosi' resta
    valido anche se il programma viene chiuso a meta'). La sezione di questo
    lancio viene sostituita ogni volta; il testo dei lanci precedenti resta
    com'e'."""

    def __init__(self, plan: ArtistPlan):
        self.plan = plan
        self.path = plan.folder / REPORT_NAME
        self._lock = threading.Lock()
        self._stamp = f"{datetime.now():%Y-%m-%d %H:%M}"
        prefix = ""
        if self.path.exists():
            prefix = self.path.read_text(encoding="utf-8")
            if prefix.strip():
                prefix = prefix.rstrip("\n") + "\n\n" + "=" * 60 + "\n"
        self._prefix = prefix
        self._restore_links(prefix)

    def _restore_links(self, old_report: str) -> None:
        """Le canzoni gia' su disco vengono saltate al ripristino: il loro link
        non e' piu' nel QueueItem, ma e' nelle sezioni dei lanci precedenti."""
        known = {}
        key = None
        for line in old_report.splitlines():
            if line.startswith("      http"):
                if key:
                    known[key] = line.strip()
            elif " | " in line and not line.startswith(" "):
                key = line.split(" | ")[0] + " | " + line.split(" | ")[1]
            else:
                key = None
        for item in self.plan.queue:
            if not item.result_url and item_file_size(item):
                url = known.get(_item_key(item))
                if url:
                    item.result_url = url

    def update(self) -> Path:
        with self._lock:
            text = self._prefix + _report_section(self.plan, self._stamp)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, self.path)
        return self.path


def write_report(plan: ArtistPlan) -> Path:
    return ReportWriter(plan).update()


def _item_key(item) -> str:
    num = item.meta.get("tracknumber", "").split("/")[0]
    return f"{num + '. ' if num else ''}{item.meta['title']} | {item.meta['artist']}"


def _report_section(plan: ArtistPlan, stamp: str) -> str:
    """Report simile al txt di partenza: per ogni canzone album/numero, esito
    e link YouTube da cui e' stata scaricata."""
    lines = [f"# {plan.artist_name}   ({stamp})", ""]
    if plan.ignored:
        lines += ["!!! RIGHE DEL TXT IGNORATE:"] + [f"    {m}" for m in plan.ignored] + [""]
    base = len(lines)
    current = object()
    for item in plan.queue:
        album = item.meta.get("album", "")
        if album != current:
            current = album
            if len(lines) > base:
                lines.append("")
            year = item.meta.get("year", "")
            lines.append(f"[Album] {album}" + (f" ({year})" if year else "") if album
                         else "[Singoli]")
        num = item.meta.get("tracknumber", "").split("/")[0]
        head = f"{num}. " if num else ""
        status = item.result_status or "non scaricato"  # anche: in attesa / interrotto
        check = f" | {item.result_check}" if item.result_check else ""
        lines.append(f"{head}{item.meta['title']} | {item.meta['artist']} | {status.upper()}{check}")
        if item.result_url:
            lines.append(f"      {item.result_url}")
        if item.result_note:
            lines.append(f"      !!! {item.result_note}")
        if item.result_error:
            lines.append(f"      motivo: {item.result_error}")
    return "\n".join(lines) + "\n"


def item_file_size(item) -> int:
    """Dimensione dell'mp3 scaricato per questa canzone (0 se non c'e')."""
    try:
        name = DownloadManager._filename(item, item.meta or {})
        return Path(item.destination, f"{name}.mp3").stat().st_size
    except OSError:
        return 0


def describe_failure(item) -> str:
    """'Artista - Titolo (album): motivo' per il riepilogo finale."""
    reason = item.result_error or item.result_status or "non scaricato"
    return f"{item.meta['artist']} - {item.label}: {reason}"


def run_plans(manager: DownloadManager, plans: List[ArtistPlan], *,
              on_track_started: Callable = None,
              on_progress: Callable = None,
              on_track_completed: Callable = None) -> List[str]:
    """Scarica i piani artista uno dopo l'altro (un run_batch ciascuno, cosi'
    ogni artista ha la sua voce in cronologia). Bloccante; gli hook on_* sono
    quelli di DownloadManager.run_batch e arrivano da thread worker.
    Ritorna l'elenco dei download falliti."""
    manager.cancel_event.clear()
    failed: List[str] = []
    for plan in plans:
        if not plan.queue:
            if plan.ignored:
                write_report(plan)
            continue
        for dest in {item.destination for item in plan.queue}:
            Path(dest).mkdir(parents=True, exist_ok=True)
        report = ReportWriter(plan)
        report.update()

        def completed(item, item_id, ok, c, t, _report=report):
            _report.update()  # esito su disco subito, prima di avvisare la UI
            if on_track_completed:
                on_track_completed(item, item_id, ok, c, t)

        manager.run_batch(
            plan.queue, str(plan.folder), artist_name=plan.artist_name,
            on_track_started=on_track_started,
            on_progress=on_progress,
            on_track_completed=completed,
        )
        failed.extend(describe_failure(i) for i in plan.queue
                      if i.result_status not in ("ok", "esistente"))
        report.update()
        if manager.cancel_event.is_set():
            # gli artisti rimasti non sono mai partiti: vanno segnalati
            for rest in plans[plans.index(plan) + 1:]:
                for i in rest.queue:
                    i.result_status = "annullato"
                    failed.append(describe_failure(i))
            break
    return failed
