"""Download da file txt (artista → album → tracce, e singoli).

Senza argomenti apre la mini-UI (ui/txt_app.py).
Da codice / terminale, senza nessuna UI:
    python scarica_da_txt.py lista.txt "D:/Musica"
Se la cartella di destinazione e' omessa si apre solo il selettore cartella.
Da Python:
    from scarica_da_txt import scarica
    scarica("lista.txt", "D:/Musica")

Per ogni artista viene creata <destinazione>/<Artista>/ con una sottocartella
per ogni album e i singoli direttamente nella cartella dell'artista. Nessuna
API: titoli, album, anno e numeri traccia sono quelli scritti nel txt (vedi
lista_esempio.txt per il formato)."""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import List, Optional, Union

from logica.txt_download import make_manager, run_plans
from logica.txt_importer import build_plan, count_tracks, format_tree, parse_txt


def scarica(txt: Union[str, Path], destination: Union[str, Path]) -> List[str]:
    """Scarica tutto cio' che e' scritto nel txt dentro `destination`,
    stampando l'avanzamento nel terminale. Ritorna i download falliti."""
    # Il terminale Windows (cp1252) non stampa i caratteri dell'albero.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    destination = Path(destination)
    orphans: List[str] = []
    plans = [build_plan(req, destination) for req in parse_txt(Path(txt), orphans)]
    ignored = orphans + [m for p in plans for m in p.ignored]
    if ignored:
        print("ATTENZIONE, righe del txt ignorate:")
        for m in ignored:
            print(f"  ! {m}")
        print()
    total = count_tracks(plans)
    if not total:
        print("Nessuna canzone trovata nel file.")
        return []

    print(format_tree(plans, destination))
    print(f"\n{total} canzoni da scaricare in {destination}\n")

    done = [0]  # c/t di run_batch sono per-artista: contiamo noi sul totale
    def on_completed(item, _id, ok, _c, _t):
        done[0] += 1
        print(f"  [{done[0]}/{total}] {'OK ' if ok else 'ERR'} {item.label}")

    failed = run_plans(make_manager(), plans, on_track_completed=on_completed)

    print("\n" + "=" * 60)
    if failed:
        print("Download falliti:")
        for f in failed:
            print(f"  - {f}")
    else:
        print("Tutto completato senza errori.")
    return failed


def choose_destination() -> Optional[Path]:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="Seleziona cartella di destinazione")
    root.destroy()
    return Path(folder) if folder else None


def main():
    if len(sys.argv) == 1:
        from ui.txt_app import run
        run()
        return
    if len(sys.argv) > 3:
        print(__doc__)
        return
    destination = Path(sys.argv[2]) if len(sys.argv) == 3 else choose_destination()
    if destination is None:
        print("Nessuna cartella scelta, annullato.")
        return
    scarica(sys.argv[1], destination)


if __name__ == "__main__":
    main()
