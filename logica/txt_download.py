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


def write_report(plan: ArtistPlan) -> Path:
    """Scrive nella cartella dell'artista un report simile al txt di partenza:
    per ogni canzone album/numero, esito e link YouTube da cui e' stata scaricata."""
    path = plan.folder / REPORT_NAME
    # Il report si accoda: un rilancio (o un altro txt per lo stesso artista)
    # non cancella i link e gli esiti dei lanci precedenti.
    lines = []
    if path.exists():
        lines += ["", "=" * 60]
    lines += [f"# {plan.artist_name}   ({datetime.now():%Y-%m-%d %H:%M})", ""]
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
        status = item.result_status or "non scaricato"
        lines.append(f"{head}{item.meta['title']} | {item.meta['artist']} | {status.upper()}")
        if item.result_url:
            lines.append(f"      {item.result_url}")
        if item.result_note:
            lines.append(f"      !!! {item.result_note}")
        if item.result_error:
            lines.append(f"      motivo: {item.result_error}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


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
        manager.run_batch(
            plan.queue, str(plan.folder), artist_name=plan.artist_name,
            on_track_started=on_track_started,
            on_progress=on_progress,
            on_track_completed=on_track_completed,
        )
        failed.extend(describe_failure(i) for i in plan.queue
                      if i.result_status not in ("ok", "esistente"))
        write_report(plan)
        if manager.cancel_event.is_set():
            # gli artisti rimasti non sono mai partiti: vanno segnalati
            for rest in plans[plans.index(plan) + 1:]:
                for i in rest.queue:
                    i.result_status = "annullato"
                    failed.append(describe_failure(i))
            break
    return failed
