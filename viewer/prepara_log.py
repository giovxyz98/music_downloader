"""Prepara il log per il viewer: legge music_downloader.log (+ i file ruotati) e scrive
viewer/log_data.js, che viewer.html carica con <script src> (una pagina aperta da file://
non puo' leggere altri file).

Uso:
    python viewer/prepara_log.py              # log standard, poi apre il viewer
    python viewer/prepara_log.py altro.log    # un log specifico
    python viewer/prepara_log.py --no-open    # solo genera log_data.js
"""
import json
import re
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

LINE_RE = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d),\d{3} \[(\w+)\] (.*)$")
MAX_RECORDS = 30000   # si tengono le piu' recenti
MAX_TEXT = 4000       # caratteri per record (difesa da traceback enormi)


def read_records(paths):
    """[data, ora, livello, testo] per record; le righe senza timestamp (blocchi,
    traceback) appartengono al record precedente."""
    records = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = LINE_RE.match(line)
            if m:
                records.append(list(m.groups()))
            elif records:
                records[-1][3] += "\n" + line
    return records


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        base = Path(args[0])
        paths = [base]
    else:
        from logica.config import DATA_DIR
        base = DATA_DIR / "music_downloader.log"
        paths = [base.with_name(base.name + ".2"), base.with_name(base.name + ".1"), base]
    records = read_records(paths)
    cut = max(0, len(records) - MAX_RECORDS)
    records = [[d, t, lv, x[:MAX_TEXT]] for d, t, lv, x in records[cut:]]
    data = {"source": str(base), "cut": cut, "records": records}
    # json.dumps esce virgolette e backslash; "</" viene spezzato per non chiudere mai uno <script>
    payload = json.dumps(data, ensure_ascii=True).replace("</", "<\\/")
    out = HERE / "log_data.js"
    out.write_text("window.LOG_DATA = " + payload + ";\n", encoding="utf-8")
    print(f"{len(records)} righe di log -> {out}")
    if "--no-open" not in sys.argv:
        webbrowser.open((HERE / "viewer.html").as_uri())


if __name__ == "__main__":
    main()
