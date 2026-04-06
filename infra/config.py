import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

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
    _log_file = Path(__file__).parent.parent / "music_downloader.log"
    _fh = RotatingFileHandler(_log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _ch = logging.StreamHandler()
    _ch.setLevel(logging.WARNING)
    _ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(_fh)
    logger.addHandler(_ch)

# ─────────────────────────────────────────────────────────────
# Configurazione  (default + override da config.json)
# ─────────────────────────────────────────────────────────────
_CFG_DEFAULTS: dict = {
    "MAX_WORKERS":                3,
    "PREFERRED_QUALITY":          "320",
    "SOCKET_TIMEOUT":             30,
    "RETRIES":                    3,
    "YOUTUBE_RESULTS":            5,
    "FILENAME_MAX_LENGTH":        180,
    "MAX_SEARCHES":               50,
    "MAX_HISTORY":                500,
    "HISTORY_MENU_MAX":           40,
    "RECENT_SEARCHES_SHOWN":      10,
    "DEEZER_ARTIST_LIMIT":        100,
    "DEEZER_TRACK_LIMIT":         50,
    "CACHE_MAXSIZE":              200,
    "DOWNLOAD_TIMEOUT":           300,
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
}

_cfg_file = Path(__file__).parent.parent / "config.json"
try:
    with open(_cfg_file, "r", encoding="utf-8") as _f:
        _cfg = {**_CFG_DEFAULTS, **json.load(_f)}
except FileNotFoundError:
    _cfg = dict(_CFG_DEFAULTS)
    with open(_cfg_file, "w", encoding="utf-8") as _f:
        json.dump(_CFG_DEFAULTS, _f, indent=2)
except Exception as _e:
    logger.warning(f"config.json non leggibile, uso default: {_e}")
    _cfg = dict(_CFG_DEFAULTS)

MAX_WORKERS                = _cfg["MAX_WORKERS"]
PREFERRED_QUALITY          = _cfg["PREFERRED_QUALITY"]
SOCKET_TIMEOUT             = _cfg["SOCKET_TIMEOUT"]
RETRIES                    = _cfg["RETRIES"]
YOUTUBE_RESULTS            = _cfg["YOUTUBE_RESULTS"]
FILENAME_MAX_LENGTH        = _cfg["FILENAME_MAX_LENGTH"]
MAX_SEARCHES               = _cfg["MAX_SEARCHES"]
MAX_HISTORY                = _cfg["MAX_HISTORY"]
HISTORY_MENU_MAX           = _cfg["HISTORY_MENU_MAX"]
RECENT_SEARCHES_SHOWN      = _cfg["RECENT_SEARCHES_SHOWN"]
DEEZER_ARTIST_LIMIT        = _cfg["DEEZER_ARTIST_LIMIT"]
DEEZER_TRACK_LIMIT         = _cfg["DEEZER_TRACK_LIMIT"]
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
