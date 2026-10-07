"""Prepara il log per il viewer: legge music_downloader.log (+ i file ruotati),
lo trasforma in dati strutturati e scrive viewer/log_data.js, che viewer.html
carica con <script src> (una pagina aperta da file:// non puo' leggere altri file).

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

LINE_RE   = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d),\d{3} \[(\w+)\] (.*)$")
HEAD_RE   = re.compile(r"^\[#(\d+)/(\d+)\] (.*?)   \((.*)\)$")
CAND_RE   = re.compile(r"^\s+(\d+)\.\s+(-?\d+)\s+(\S+)\s+(.{16})  (.{42})  (\S{11})(?:\s+✗ (.*))?$")
YT_RE     = re.compile(r"^https://www\.youtube\.com/watch\?v=[\w-]{11}$")
BLOCK_SEP = "═" * 70
MAX_BLOCK_LINES = 40  # un blocco piu' lungo viene tagliato (difesa da log corrotti)


def read_records(paths):
    """Lista di (data, ora, livello, testo multi-riga), dal file piu' vecchio al nuovo."""
    records = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = LINE_RE.match(line)
            if m:
                records.append([m.group(1), m.group(2), m.group(3), m.group(4)])
            elif records:
                records[-1][3] += "\n" + line
    return records


def clean_url(url: str) -> str:
    """Solo link YouTube di forma nota diventano cliccabili; il resto resta testo."""
    url = url.strip()
    return url if YT_RE.match(url) else ""


def parse_song(date, time, text):
    lines = text.split("\n")[:MAX_BLOCK_LINES]
    m = HEAD_RE.match(lines[1]) if len(lines) > 1 else None
    song = {"date": date, "time": time, "n": 0, "of": 0, "name": lines[1] if len(lines) > 1 else "?",
            "album": "", "status": "?", "candidates": [], "scoring": "", "download": "",
            "kbps": 0, "check": "", "detail": "", "notes": [], "cached": False}
    if m:
        song.update(n=int(m.group(1)), of=int(m.group(2)), name=m.group(3), album=m.group(4))
    for line in lines[2:]:
        c = CAND_RE.match(line)
        s = line.strip()
        if c:
            song["candidates"].append({"rank": int(c.group(1)), "score": int(c.group(2)),
                                       "views": c.group(3), "channel": c.group(4).strip(),
                                       "title": c.group(5).strip(), "id": c.group(6),
                                       "error": c.group(7) or ""})
        elif s.startswith("scoring:"):
            song["scoring"] = s[8:].strip()
        elif s.startswith("(classifica non disponibile"):
            song["cached"] = True
        elif s.startswith("!!!"):
            song["notes"].append(s[3:].strip())
        elif s.startswith("download:"):
            rest = s[9:].strip()
            m2 = re.match(r"(OK\*?)(?: \(candidato (\d+)\))? (\d+)k (\S+.*?)  (\S+)$", rest)
            if m2:
                song["status"] = m2.group(1)
                song["kbps"] = int(m2.group(3))
                song["check"] = m2.group(4)
                song["download"] = m2.group(5)
                if m2.group(2):
                    song["detail"] = f"candidato {m2.group(2)}"
            else:
                song["status"], song["detail"] = "OK", rest
        elif s.startswith("già presente"):
            song["status"] = "PRESENTE"
            song["download"] = s[len("già presente"):].strip()
        elif s.startswith("NON SCARICATA"):
            song["status"], song["detail"] = "NON SCARICATA", s.partition(":")[2].strip()
        elif s.startswith("FALLITA"):
            song["status"], song["detail"] = "FALLITA", s.partition(":")[2].strip()
        elif s:
            song["notes"].append(s)
    for key in ("scoring", "download"):
        song[key + "_ok"] = bool(clean_url(song[key]))
    return song


def build(records):
    runs, cur = [], None

    def new_run(date, time, text):
        m = re.search(r"Inizio download: (\d+) tracce → (.*)", text)
        return {"date": date, "start": time, "end": "", "total": int(m.group(1)) if m else 0,
                "dest": m.group(2).strip() if m else "", "summary": "", "songs": [], "events": []}

    for date, time, level, text in records:
        if text.startswith("[Batch] Inizio download"):
            cur = new_run(date, time, text)
            runs.append(cur)
        elif cur is None:
            continue
        elif text.startswith(BLOCK_SEP):
            cur["songs"].append(parse_song(date, time, text))
        elif text.startswith("[Batch] Fine:"):
            cur["end"], cur["summary"] = time, text[len("[Batch] Fine:"):].strip()
        elif level in ("WARNING", "ERROR") and not text.startswith("[Batch] #"):
            cur["events"].append({"time": time, "level": level, "text": text[:500]})
    return runs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        base = Path(args[0])
        paths = [base]
    else:
        from logica.config import DATA_DIR
        base = DATA_DIR / "music_downloader.log"
        paths = [base.with_name(base.name + ".2"), base.with_name(base.name + ".1"), base]
    runs = build(read_records(paths))
    data = {"source": str(base), "runs": runs}
    # json.dumps esce virgolette e backslash; "</" viene spezzato per non chiudere mai uno <script>
    payload = json.dumps(data, ensure_ascii=True).replace("</", "<\\/")
    out = HERE / "log_data.js"
    out.write_text("window.LOG_DATA = " + payload + ";\n", encoding="utf-8")
    songs = sum(len(r["songs"]) for r in runs)
    print(f"{len(runs)} lanci, {songs} canzoni -> {out}")
    if "--no-open" not in sys.argv:
        webbrowser.open((HERE / "viewer.html").as_uri())


if __name__ == "__main__":
    main()
