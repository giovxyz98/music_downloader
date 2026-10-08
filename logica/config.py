import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Radice del progetto: logica/config.py -> logica/ -> root
ROOT_DIR = Path(__file__).resolve().parent.parent

# Dove vivono log e cache (DATA_DIR) e config.json (CONFIG_DIR): da sorgente log e
# cache in dati/ e config.json accanto al codice; da exe (PyInstaller) tutto in
# %APPDATA%, perche' la cartella dell'exe one-file e' temporanea e a ogni
# chiusura verrebbe cancellata.
if getattr(sys, "frozen", False):
    DATA_DIR = CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "MusicDownloader"
else:
    DATA_DIR, CONFIG_DIR = ROOT_DIR / "dati", ROOT_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ffmpeg/ffprobe inclusi nel bundle exe (vedi crea_programma.bat); da sorgente si usa il PATH.
FFMPEG_DIR = str(Path(sys._MEIPASS) / "ffmpeg") if getattr(sys, "frozen", False) else None

# ─────────────────────────────────────────────────────────────
# Palette
# ─────────────────────────────────────────────────────────────
BG      = "#111827"
PANEL   = "#1f2937"
CARD    = "#374151"
ACCENT  = "#6366f1"
ACCENT2 = "#4f46e5"
TEXT    = "#f9fafb"
SUBTEXT = "#9ca3af"
ERROR   = "#ef4444"
SUCCESS = "#4ade80"
BORDER  = "#4b5563"

# ─────────────────────────────────────────────────────────────
# Logger  (setup una sola volta, idempotente)
# ─────────────────────────────────────────────────────────────
logger = logging.getLogger("music_downloader")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    _log_file = DATA_DIR / "music_downloader.log"
    # Un solo file: la rotazione scatta solo oltre 1 GB (e tiene 1 copia precedente).
    _fh = RotatingFileHandler(_log_file, maxBytes=1_000_000_000, backupCount=1, encoding="utf-8")
    _fh.setLevel(logging.DEBUG)  # abbassato dopo il load di config.json (LOG_LEVEL)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_fh)
    if sys.stderr is not None:  # exe senza console: stderr e' None
        _ch = logging.StreamHandler()
        _ch.setLevel(logging.WARNING)
        _ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(_ch)

# ─────────────────────────────────────────────────────────────
# Configurazione  (default + override da config.json)
# ─────────────────────────────────────────────────────────────
_CFG_DEFAULTS: dict = {
    "MAX_WORKERS":                3,
    "PREFERRED_QUALITY":          "320",
    "SOCKET_TIMEOUT":             30,
    "RETRIES":                    3,
    # HTTP 403 di YouTube su un download: di solito temporaneo, si riprova lo
    # stesso link prima di passare al candidato successivo.
    "HTTP_403_RETRIES":           2,
    "HTTP_403_RETRY_PAUSE":       4,
    "YOUTUBE_RESULTS":            5,
    "FILENAME_MAX_LENGTH":        180,
    "MAX_SEARCHES":               50,
    "MAX_HISTORY":                500,
    "HISTORY_MENU_MAX":           40,
    "RECENT_SEARCHES_SHOWN":      10,
    "DEEZER_ARTIST_LIMIT":        100,
    "DEEZER_TRACK_LIMIT":         50,
    "SPOTIFY_ARTIST_LIMIT":       10,
    "SPOTIFY_TRACK_LIMIT":        10,
    "CACHE_MAXSIZE":              200,
    "DOWNLOAD_TIMEOUT":           300,
    # Livello del log su file: INFO per l'uso normale, DEBUG per diagnosticare lo scoring
    "LOG_LEVEL":                  "INFO",
    # Pesi scoring YouTube — configurabili senza toccare il codice
    "SCORE_ARTIST_IN_TITLE":      25,
    "SCORE_TITLE_IN_TITLE":       30,
    "SCORE_ARTIST_IN_CHANNEL":    15,
    "SCORE_TOPIC_CHANNEL":        25,
    "SCORE_OFFICIAL_KEYWORD":     10,
    "SCORE_BAD_KEYWORD_PENALTY":  25,
    "SCORE_DURATION_EXACT":       20,
    "SCORE_DURATION_CLOSE":       10,
    "SCORE_DURATION_FAR_PENALTY": 20,
    "SCORE_FUZZY_MULTIPLIER":     0.3,
    "SCORE_FIRST_RESULT_BONUS":              15,
    # Il bonus primo risultato vale solo se il titolo del video somiglia almeno
    # cosi' (0-100, rapidfuzz token_set_ratio) al titolo cercato.
    "SCORE_FIRST_RESULT_MIN_TITLE_MATCH":    65,
    "SCORE_EXTRA_WORD_PENALTY":              10,
    "SCORE_ORIGINAL_ARTIST_MISSING_PENALTY": 35,
    "SCORE_MIN_DOWNLOAD":                    50,
    # Caso limite: sotto SCORE_MIN_DOWNLOAD ma non oltre LIMIT_MARGIN punti, si
    # accetta il miglior candidato solo se e' sul canale dell'artista stesso
    # (vedi YouTubeSearcher._limit_case) e la durata non si discosta oltre
    # LIMIT_MAX_DURATION_DIFF secondi.
    "SCORE_LIMIT_MARGIN":                    10,
    "LIMIT_MAX_DURATION_DIFF":               90,
    "SEARCH_WORKERS":             2,
    # Penalità "canale sospetto": se un candidato ha views drasticamente più
    # basse di un altro candidato che cita lo stesso artista nella stessa
    # ricerca, è probabile un canale omonimo/impostore — vedi problemi_scoring.txt #5
    "SCORE_VIEWS_GAP_RATIO":      20,
    "SCORE_VIEWS_GAP_PENALTY":    50,
}

_cfg_file = CONFIG_DIR / "config.json"
try:
    with open(_cfg_file, "r", encoding="utf-8") as _f:
        _cfg = {**_CFG_DEFAULTS, **json.load(_f)}
except FileNotFoundError:
    _cfg = dict(_CFG_DEFAULTS)
    with open(_cfg_file, "w", encoding="utf-8") as _f:
        json.dump(_CFG_DEFAULTS, _f, indent=2)
except Exception as _e:
    logger.warning(f"config.json non leggibile, lo rigenero con i default: {_e}")
    _cfg = dict(_CFG_DEFAULTS)
    with open(_cfg_file, "w", encoding="utf-8") as _f:
        json.dump(_CFG_DEFAULTS, _f, indent=2)

_log_level = getattr(logging, str(_cfg["LOG_LEVEL"]).upper(), logging.INFO)
for _h in logger.handlers:
    if isinstance(_h, RotatingFileHandler):
        _h.setLevel(_log_level)

MAX_WORKERS                = _cfg["MAX_WORKERS"]
PREFERRED_QUALITY          = _cfg["PREFERRED_QUALITY"]
SOCKET_TIMEOUT             = _cfg["SOCKET_TIMEOUT"]
RETRIES                    = _cfg["RETRIES"]
HTTP_403_RETRIES           = _cfg["HTTP_403_RETRIES"]
HTTP_403_RETRY_PAUSE       = _cfg["HTTP_403_RETRY_PAUSE"]
YOUTUBE_RESULTS            = _cfg["YOUTUBE_RESULTS"]
FILENAME_MAX_LENGTH        = _cfg["FILENAME_MAX_LENGTH"]
MAX_SEARCHES               = _cfg["MAX_SEARCHES"]
MAX_HISTORY                = _cfg["MAX_HISTORY"]
HISTORY_MENU_MAX           = _cfg["HISTORY_MENU_MAX"]
RECENT_SEARCHES_SHOWN      = _cfg["RECENT_SEARCHES_SHOWN"]
DEEZER_ARTIST_LIMIT        = _cfg["DEEZER_ARTIST_LIMIT"]
DEEZER_TRACK_LIMIT         = _cfg["DEEZER_TRACK_LIMIT"]
SPOTIFY_ARTIST_LIMIT       = _cfg["SPOTIFY_ARTIST_LIMIT"]
SPOTIFY_TRACK_LIMIT        = _cfg["SPOTIFY_TRACK_LIMIT"]
CACHE_MAXSIZE              = _cfg["CACHE_MAXSIZE"]
DOWNLOAD_TIMEOUT           = _cfg["DOWNLOAD_TIMEOUT"]
SCORE_ARTIST_IN_TITLE      = _cfg["SCORE_ARTIST_IN_TITLE"]
SCORE_TITLE_IN_TITLE       = _cfg["SCORE_TITLE_IN_TITLE"]
SCORE_ARTIST_IN_CHANNEL    = _cfg["SCORE_ARTIST_IN_CHANNEL"]
SCORE_TOPIC_CHANNEL        = _cfg["SCORE_TOPIC_CHANNEL"]
SCORE_OFFICIAL_KEYWORD     = _cfg["SCORE_OFFICIAL_KEYWORD"]
SCORE_BAD_KEYWORD_PENALTY  = _cfg["SCORE_BAD_KEYWORD_PENALTY"]
SCORE_DURATION_EXACT       = _cfg["SCORE_DURATION_EXACT"]
SCORE_DURATION_CLOSE       = _cfg["SCORE_DURATION_CLOSE"]
SCORE_DURATION_FAR_PENALTY = _cfg["SCORE_DURATION_FAR_PENALTY"]
SCORE_FUZZY_MULTIPLIER     = _cfg["SCORE_FUZZY_MULTIPLIER"]
SCORE_FIRST_RESULT_BONUS              = _cfg["SCORE_FIRST_RESULT_BONUS"]
SCORE_FIRST_RESULT_MIN_TITLE_MATCH    = _cfg["SCORE_FIRST_RESULT_MIN_TITLE_MATCH"]
SCORE_EXTRA_WORD_PENALTY              = _cfg["SCORE_EXTRA_WORD_PENALTY"]
SCORE_ORIGINAL_ARTIST_MISSING_PENALTY = _cfg["SCORE_ORIGINAL_ARTIST_MISSING_PENALTY"]
SCORE_MIN_DOWNLOAD                    = _cfg["SCORE_MIN_DOWNLOAD"]
SCORE_LIMIT_MARGIN                    = _cfg["SCORE_LIMIT_MARGIN"]
LIMIT_MAX_DURATION_DIFF               = _cfg["LIMIT_MAX_DURATION_DIFF"]
SEARCH_WORKERS             = _cfg["SEARCH_WORKERS"]
SCORE_VIEWS_GAP_RATIO      = _cfg["SCORE_VIEWS_GAP_RATIO"]
SCORE_VIEWS_GAP_PENALTY    = _cfg["SCORE_VIEWS_GAP_PENALTY"]

_START_BANNER = "█" * 100
logger.debug(f"\n\n{_START_BANNER}\n{'NUOVA ESECUZIONE':^100}\n{_START_BANNER}")
logger.debug(f"[Config] Configurazione attiva: {_cfg}")


class YtDlpLogAdapter:
    """Inoltra i messaggi interni di yt-dlp (normalmente silenziati da quiet=True)
    nel nostro logger, così restano nel file invece di sparire nel nulla."""

    def __init__(self, tag: str = ""):
        self.tag = tag

    def debug(self, msg):
        logger.debug(f"[yt-dlp-internal]{self.tag} {msg}")

    def info(self, msg):
        logger.debug(f"[yt-dlp-internal]{self.tag} {msg}")

    # warning/error di yt-dlp (avvisi JS, traceback dei 403...) restano nel file ma solo
    # a DEBUG: l'esito vero lo scrive il blocco della canzone (download_manager).
    def warning(self, msg):
        logger.debug(f"[yt-dlp-internal][WARNING]{self.tag} {msg}")

    def error(self, msg):
        logger.debug(f"[yt-dlp-internal][ERROR]{self.tag} {msg}")
