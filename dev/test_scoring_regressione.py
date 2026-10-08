"""
Regressione dello scoring su risultati YouTube SALVATI (nessuna rete).

    python dev/test_scoring_regressione.py             # confronta con i vincitori attesi
    python dev/test_scoring_regressione.py --aggiorna  # accetta i vincitori attuali come nuovi attesi

dev/fixture_scoring.json: ~144 ricerche reali (query "Artista - Titolo", primi 5
risultati di yt-dlp, presi il 2026-10-08) con artista, titolo e durata attesa.
dev/fixture_scoring_attesi.json: per ogni ricerca, id e punteggio del vincitore
accettato. Dopo ogni ritocco allo scoring si lancia: elenca le ricerche in cui
cambia il vincitore o il passaggio della soglia, da guardare a mano. Se i
cambiamenti sono voluti, --aggiorna.
"""
import json
import logging
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parent
sys.path.insert(0, str(DEV.parent))
sys.stdout.reconfigure(encoding="utf-8")
from logica.config import SCORE_MIN_DOWNLOAD
from logica.youtube import YouTubeSearcher as Y

logging.disable(logging.CRITICAL)
FIXTURE = DEV / "fixture_scoring.json"
ATTESI = DEV / "fixture_scoring_attesi.json"


def vincitore(case: dict) -> dict:
    art_n, tit_n = Y._normalize(case["artist"]), Y._normalize(case["title"])
    score, e = Y._rank(case["entries"], art_n, tit_n, case["duration"], art_n)[0]
    return {"id": e["id"], "score": score, "canale": e.get("uploader") or e.get("channel"),
            "titolo": e.get("title")}


def main() -> int:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    attuali = {f"{c['artist']} - {c['title']}": vincitore(c) for c in cases}
    if "--aggiorna" in sys.argv or not ATTESI.exists():
        ATTESI.write_text(json.dumps(attuali, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Attesi salvati: {len(attuali)} ricerche")
        return 0
    attesi = json.loads(ATTESI.read_text(encoding="utf-8"))
    diversi = 0
    for k, a in attuali.items():
        o = attesi.get(k)
        if o is None:
            continue
        sopra_prima, sopra_dopo = o["score"] >= SCORE_MIN_DOWNLOAD, a["score"] >= SCORE_MIN_DOWNLOAD
        if o["id"] != a["id"] or sopra_prima != sopra_dopo:
            diversi += 1
            print(f"\n{k}\n   atteso {o['score']:4d} [{o['canale']}] {o['titolo']}\n"
                  f"   ora    {a['score']:4d} [{a['canale']}] {a['titolo']}")
    print(f"\n{len(attuali)} ricerche, {diversi} con vincitore o soglia diversi")
    return 1 if diversi else 0


if __name__ == "__main__":
    sys.exit(main())
