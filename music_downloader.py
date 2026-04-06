import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
import threading
from queue import Queue
import logging
from logging.handlers import RotatingFileHandler
import requests
import yt_dlp
import sys
import os
import re
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, ID3NoHeaderError
from rapidfuzz import fuzz

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

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
# Logger
# ─────────────────────────────────────────────────────────────
logger = logging.getLogger("music_downloader")
logger.setLevel(logging.DEBUG)
_log_file = Path(__file__).parent / "music_downloader.log"
_fh = RotatingFileHandler(_log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_ch = logging.StreamHandler()
_ch.setLevel(logging.WARNING)
_ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(_fh)
logger.addHandler(_ch)

# ─────────────────────────────────────────────────────────────
# Configurazione  (valori default + override da config.json)
# ─────────────────────────────────────────────────────────────
_CFG_DEFAULTS = {
    "MAX_WORKERS":           3,
    "PREFERRED_QUALITY":     "320",
    "SOCKET_TIMEOUT":        30,
    "RETRIES":               3,
    "YOUTUBE_RESULTS":       5,
    "FILENAME_MAX_LENGTH":   180,
    "MAX_SEARCHES":          50,
    "MAX_HISTORY":           500,
    "HISTORY_MENU_MAX":      40,
    "RECENT_SEARCHES_SHOWN": 10,
    "DEEZER_ARTIST_LIMIT":   100,
    "DEEZER_TRACK_LIMIT":    50,
}
_cfg_file = Path(__file__).parent / "config.json"
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

MAX_WORKERS           = _cfg["MAX_WORKERS"]
PREFERRED_QUALITY     = _cfg["PREFERRED_QUALITY"]
SOCKET_TIMEOUT        = _cfg["SOCKET_TIMEOUT"]
RETRIES               = _cfg["RETRIES"]
YOUTUBE_RESULTS       = _cfg["YOUTUBE_RESULTS"]
FILENAME_MAX_LENGTH   = _cfg["FILENAME_MAX_LENGTH"]
MAX_SEARCHES          = _cfg["MAX_SEARCHES"]
MAX_HISTORY           = _cfg["MAX_HISTORY"]
HISTORY_MENU_MAX      = _cfg["HISTORY_MENU_MAX"]
RECENT_SEARCHES_SHOWN = _cfg["RECENT_SEARCHES_SHOWN"]
DEEZER_ARTIST_LIMIT   = _cfg["DEEZER_ARTIST_LIMIT"]
DEEZER_TRACK_LIMIT    = _cfg["DEEZER_TRACK_LIMIT"]

# ─────────────────────────────────────────────────────────────
# MusicSearcher  –  Deezer metadata client
# ─────────────────────────────────────────────────────────────
class MusicSearcher:
    BASE = "https://api.deezer.com"

    def __init__(self):
        self._session      = requests.Session()
        self._artist_cache: Dict[str, List[Dict]] = {}
        self._album_cache:  Dict[str, List[Dict]] = {}
        self._track_cache:  Dict[str, List[Dict]] = {}
        self._search_cache: Dict[str, List[Dict]] = {}

    def _get(self, url: str, params: Optional[Dict] = None) -> Dict:
        time.sleep(0.1)
        logger.debug(f"[Deezer] GET {url} params={params}")
        for attempt in range(RETRIES):
            try:
                r = self._session.get(url, params=params, timeout=10)
                if not r.ok:
                    logger.warning(f"[Deezer] HTTP {r.status_code} per {url}: {r.text[:300]}")
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    raise RuntimeError(
                        f"Deezer error {data['error'].get('code')}: {data['error'].get('message')}"
                    )
                return data
            except requests.RequestException as e:
                logger.warning(f"[Deezer] Tentativo {attempt+1}/{RETRIES} fallito: {e}")
                if attempt == RETRIES - 1:
                    raise RuntimeError(f"Richiesta fallita dopo {RETRIES} tentativi: {e}")
                time.sleep(1 * (2 ** attempt))

    def search_artist(self, name: str) -> List[Dict]:
        if name in self._artist_cache:
            logger.debug(f"[Deezer] Cache hit artista: {name}")
            return self._artist_cache[name]
        data = self._get(f"{self.BASE}/search/artist", {"q": name, "limit": DEEZER_ARTIST_LIMIT})
        result = [
            {
                "id": a["id"],
                "nome": a["name"],
                "followers": a.get("nb_fan", 0),
                "nb_album": a.get("nb_album", 0),
                "generi": [],
            }
            for a in data.get("data", []) if a.get("id")
        ]
        self._artist_cache[name] = result
        return result

    def search_track(self, query: str) -> List[Dict]:
        if query in self._search_cache:
            logger.debug(f"[Deezer] Cache hit canzone: {query}")
            return self._search_cache[query]
        data = self._get(f"{self.BASE}/search/track", {"q": query, "limit": DEEZER_TRACK_LIMIT})
        result = [
            {
                "id":        t["id"],
                "nome":      t["title"],
                "artisti":   [t["artist"]["name"]] if t.get("artist") else [],
                "artist_id": t["artist"]["id"] if t.get("artist") else None,
                "album":     t["album"]["title"] if t.get("album") else "",
                "album_id":  t["album"]["id"] if t.get("album") else None,
                "duration":  t.get("duration", 0),
            }
            for t in data.get("data", []) if t.get("id")
        ]
        self._search_cache[query] = result
        return result

    def get_artist_albums(self, artist_id: str) -> List[Dict]:
        key = str(artist_id)
        if key in self._album_cache:
            logger.debug(f"[Deezer] Cache hit album artista: {artist_id}")
            return self._album_cache[key]
        url = f"{self.BASE}/artist/{artist_id}/albums"
        albums, seen = [], set()
        while url:
            data = self._get(url, {"limit": 50} if not albums else None)
            for album in data.get("data", []):
                if album["id"] not in seen:
                    seen.add(album["id"])
                    albums.append({
                        "id": album["id"],
                        "nome": album["title"],
                        "anno": album.get("release_date", "")[:4] or "N/A",
                        "artisti": [album["artist"]["name"]] if album.get("artist") else [],
                        "artist_id": album["artist"]["id"] if album.get("artist") else artist_id,
                    })
            url = data.get("next")
        self._album_cache[key] = albums
        return albums

    def get_album_tracks(self, album_id: str) -> List[Dict]:
        key = str(album_id)
        if key in self._track_cache:
            logger.debug(f"[Deezer] Cache hit tracce album: {album_id}")
            return self._track_cache[key]
        data = self._get(f"{self.BASE}/album/{album_id}/tracks")
        result = [
            {
                "id":       track["id"],
                "nome":     track["title"],
                "artisti":  [track["artist"]["name"]] if track.get("artist") else [],
                "numero":   track.get("track_position", 0),
                "duration": track.get("duration", 0),
            }
            for track in data.get("data", [])
        ]
        self._track_cache[key] = result
        return result

    def get_album_details(self, album_id: str) -> Dict:
        data = self._get(f"{self.BASE}/album/{album_id}")
        genres = [g["name"] for g in data.get("genres", {}).get("data", [])]
        return {
            "genre":        ", ".join(genres),
            "album_artist": data["artist"]["name"] if data.get("artist") else "",
            "nb_tracks":    data.get("nb_tracks", 0),
            "label":        data.get("label", ""),
            "anno":         data.get("release_date", "")[:4] or "",
            "cover_xl":     data.get("cover_xl", ""),
        }


# ─────────────────────────────────────────────────────────────
# AudioDownloader  –  YouTube search + download via yt-dlp
# ─────────────────────────────────────────────────────────────
class AudioDownloader:

    _BAD_KEYWORDS      = {"live", "karaoke", "instrumental", "remix", "cover",
                          "sped up", "slowed", "8d", "nightcore"}
    _OFFICIAL_KEYWORDS = {"official video", "official audio"}

    @staticmethod
    def _normalize(s: str) -> str:
        import unicodedata
        s = unicodedata.normalize("NFKD", s)
        s = s.encode("ascii", "ignore").decode()
        s = s.lower()
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @staticmethod
    def _score(entry: dict, artist: str, title: str, duration: int) -> int:
        v     = AudioDownloader._normalize(entry.get("title", ""))
        ch    = AudioDownloader._normalize(entry.get("uploader", "") or entry.get("channel", ""))
        dur   = entry.get("duration") or 0
        art_n = AudioDownloader._normalize(artist)
        tit_n = AudioDownloader._normalize(title)

        score = 0
        if art_n and art_n in v:  score += 25
        if tit_n and tit_n in v:  score += 30
        if art_n and art_n in ch: score += 15
        if "topic" in ch:         score += 25
        for k in AudioDownloader._OFFICIAL_KEYWORDS:
            if k in v: score += 10
        for k in AudioDownloader._BAD_KEYWORDS:
            if k in v: score -= 25
        if dur and duration:
            diff = abs(dur - duration)
            if   diff <  5: score += 20
            elif diff < 15: score += 10
            elif diff > 60: score -= 20
        if tit_n:
            score += int(fuzz.partial_ratio(tit_n, v) * 0.3)
        return score

    @staticmethod
    def search_youtube(query: str, artist: str = "", title: str = "",
                       duration: int = 0) -> List[str]:
        logger.debug(f"[YouTube] Ricerca: '{query}' (artista='{artist}', titolo='{title}', durata={duration}s)")
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
                results = ydl.extract_info(f"ytsearch{YOUTUBE_RESULTS}:{query}", download=False)
            entries = [e for e in (results.get("entries") or []) if e]
            if not entries:
                logger.warning(f"[YouTube] Nessun risultato per: '{query}'")
                return []
            scored = sorted(
                entries,
                key=lambda e: AudioDownloader._score(e, artist, title, duration),
                reverse=True,
            )
            for e in scored:
                score = AudioDownloader._score(e, artist, title, duration)
                logger.debug(f"[YouTube] Score={score:3d}  canale='{e.get('uploader', '?')}'  titolo='{e.get('title', '?')[:60]}'")
            urls = [e["url"] for e in scored]
            logger.debug(f"[YouTube] {len(urls)} risultati, primo URL: {urls[0] if urls else 'nessuno'}")
            return urls
        except Exception as e:
            logger.error(f"[YouTube] Errore ricerca '{query}': {e}")
        return []

    @staticmethod
    def download(url: str, destination: str, filename: str = None,
                 progress_callback=None) -> Optional[str]:
        if filename:
            safe = re.sub(r'[<>:"/\\|?*\n\r\t]', '_', filename).strip()
            outtmpl    = str(Path(destination) / f"{safe}.%(ext)s")
            final_path = str(Path(destination) / f"{safe}.mp3")
        else:
            outtmpl    = str(Path(destination) / "%(title)s.%(ext)s")
            final_path = None

        def _hook(d):
            if progress_callback and d["status"] == "downloading":
                total      = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                if total:
                    progress_callback(min(downloaded / total * 100, 100))

        opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": PREFERRED_QUALITY,
            }],
            "noplaylist":                    True,
            "quiet":                         True,
            "progress_hooks":                [_hook],
            "socket_timeout":                SOCKET_TIMEOUT,
            "retries":                       RETRIES,
            "concurrent_fragment_downloads": 3,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        return final_path


# ─────────────────────────────────────────────────────────────
# CacheManager  –  ricerche recenti e cronologia download
# ─────────────────────────────────────────────────────────────
class CacheManager:
    CACHE_FILE = Path(__file__).parent / "music_cache.json"

    def __init__(self):
        self._save_lock = threading.Lock()
        self.data = {"recent_searches": [], "download_history": [], "youtube_cache": {}}
        self._load()

    def _load(self):
        if self.CACHE_FILE.exists():
            try:
                with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data["recent_searches"]  = loaded.get("recent_searches", [])
                self.data["download_history"] = loaded.get("download_history", [])
                self.data["youtube_cache"]    = loaded.get("youtube_cache", {})
            except Exception as e:
                logger.error(f"[Cache] Errore lettura: {e}")

    def save(self):
        with self._save_lock:
            try:
                with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"[Cache] Errore salvataggio: {e}")

    def add_search(self, type_: str, query: str):
        self.data["recent_searches"] = [
            s for s in self.data["recent_searches"]
            if not (s["type"] == type_ and s["query"].lower() == query.lower())
        ]
        self.data["recent_searches"].insert(0, {
            "type": type_,
            "query": query,
            "date": datetime.now().isoformat(timespec="seconds"),
        })
        self.data["recent_searches"] = self.data["recent_searches"][:MAX_SEARCHES]
        self.save()

    def add_download(self, entry: dict):
        self.data["download_history"].insert(0, {
            **entry,
            "date": datetime.now().isoformat(timespec="seconds"),
        })
        self.data["download_history"] = self.data["download_history"][:MAX_HISTORY]
        self.save()

    def get_recent_searches(self, limit: int = RECENT_SEARCHES_SHOWN) -> List[Dict]:
        return self.data["recent_searches"][:limit]

    def get_download_history(self) -> List[Dict]:
        return self.data["download_history"]

    def clear_history(self):
        self.data["download_history"] = []
        self.save()

    def get_youtube_urls(self, query: str) -> List[str]:
        cached = self.data["youtube_cache"].get(query, [])
        if cached:
            logger.debug(f"[Cache] YouTube hit: '{query}'")
        else:
            logger.debug(f"[Cache] YouTube miss: '{query}'")
        return cached

    def set_youtube_urls(self, query: str, urls: List[str]):
        self.data["youtube_cache"][query] = urls
        if len(self.data["youtube_cache"]) > MAX_SEARCHES:
            keys = list(self.data["youtube_cache"].keys())
            for k in keys[:-MAX_SEARCHES]:
                del self.data["youtube_cache"][k]
        self.save()


# ─────────────────────────────────────────────────────────────
# UI helper
# ─────────────────────────────────────────────────────────────
def _scrolled_tree(parent, columns, headings, col_widths):
    frame = tk.Frame(parent, bg=BG)
    sb = ttk.Scrollbar(frame, orient="vertical")
    sb.pack(side="right", fill="y")
    tree = ttk.Treeview(
        frame, columns=columns, show="headings",
        yscrollcommand=sb.set, style="Music.Treeview"
    )
    last = columns[-1]
    for col, heading, width in zip(columns, headings, col_widths):
        tree.heading(col, text=heading)
        tree.column(col, width=width, minwidth=40, stretch=(col == last))
    tree.pack(side="left", fill="both", expand=True)
    sb.config(command=tree.yview)
    return frame, tree


# ─────────────────────────────────────────────────────────────
# MusicDownloaderApp  –  UI principale
# ─────────────────────────────────────────────────────────────
class MusicDownloaderApp:

    SORT_OPTIONS = ["Nome A→Z", "Nome Z→A", "Anno ↑", "Anno ↓"]

    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("Music Downloader")
        self.root.geometry("1020x660")
        self.root.resizable(True, True)
        self.root.configure(fg_color=BG)

        self._setup_style()

        self.searcher   = MusicSearcher()
        self.downloader = AudioDownloader()
        self.cache      = CacheManager()

        self.download_queue:   list = []
        self.current_artist:   dict = None
        self.current_albums:   list = []
        self.filtered_albums:  list = []
        self.current_tracks:   list = []
        self._genre_cache:     dict = {}
        self._nb_tracks_cache: dict = {}
        self._cover_cache:     dict = {}

        self._dl_active_frame:  ctk.CTkFrame       = None
        self._dl_done_listbox:  tk.Listbox          = None
        self._dl_general_bar:   ctk.CTkProgressBar  = None
        self._dl_general_label: ctk.CTkLabel        = None
        self._dl_total:         int                 = 0
        self._track_widgets:    dict                = {}
        self._cancel_event:     threading.Event     = threading.Event()

        self._setup_menubar()
        self._build_layout()
        self._show_search()

        logger.info(f"[App] Avvio — yt-dlp={yt_dlp.version.__version__}, requests={requests.__version__}")

    # ── Stile ────────────────────────────────────────────────

    def _setup_style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")

        s.configure("Music.Treeview", background=PANEL, foreground=TEXT,
                    fieldbackground=PANEL, borderwidth=0, rowheight=30,
                    font=("Segoe UI", 10))
        s.configure("Music.Treeview.Heading", background=CARD, foreground=SUBTEXT,
                    font=("Segoe UI", 9, "bold"), borderwidth=0,
                    relief="flat", padding=(8, 6))
        s.map("Music.Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", TEXT)])

        s.configure("TScrollbar", background=CARD, troughcolor=PANEL,
                    borderwidth=0, arrowsize=12, arrowcolor=SUBTEXT)
        s.map("TScrollbar", background=[("active", BORDER)])

    # ── Menubar ──────────────────────────────────────────────

    def _setup_menubar(self):
        menubar = tk.Menu(self.root, tearoff=0)
        self.root.config(menu=menubar)

        self.history_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Cronologia", menu=self.history_menu)
        self._refresh_history_menu()

    def _refresh_history_menu(self):
        self.history_menu.delete(0, tk.END)
        history = self.cache.get_download_history()
        if not history:
            self.history_menu.add_command(label="Nessun download ancora", state="disabled")
        else:
            for entry in history[:HISTORY_MENU_MAX]:
                date    = entry.get("date", "")[:10]
                nome    = entry.get("nome", "?")
                artista = entry.get("artista", "")
                tipo    = "[A]" if entry.get("type") == "album" else "[T]"
                ok      = entry.get("successi", "?")
                tot     = entry.get("totale", "?")
                label   = f"{tipo} {nome}"
                if artista:
                    label += f"  —  {artista}"
                label += f"  ({ok}/{tot})  [{date}]"
                dest = entry.get("destination", "")
                self.history_menu.add_command(
                    label=label,
                    command=(lambda d=dest: self._open_folder(d)) if dest else None,
                    state="normal" if dest else "disabled",
                )
            self.history_menu.add_separator()
            self.history_menu.add_command(label="Cancella cronologia",
                                           command=self._clear_history)

    def _open_folder(self, path: str):
        try:
            p = Path(path).resolve()
            if not p.exists():
                p = p.parent
            if sys.platform == "win32":
                os.startfile(p)
            elif sys.platform == "darwin":
                import subprocess; subprocess.run(["open", str(p)])
            else:
                import subprocess; subprocess.run(["xdg-open", str(p)])
        except Exception:
            pass

    def _clear_history(self):
        if messagebox.askyesno("Conferma", "Cancellare tutta la cronologia download?"):
            self.cache.clear_history()
            self._refresh_history_menu()

    # ── Layout principale ────────────────────────────────────

    def _build_layout(self):
        self.nav_frame = ctk.CTkFrame(self.root, fg_color=BG)
        self.nav_frame.pack(side="left", fill="both", expand=True, padx=(16, 8), pady=16)

        tk.Frame(self.root, width=1, bg=BORDER).pack(side="left", fill="y", pady=8)

        self.queue_panel = ctk.CTkFrame(self.root, fg_color=PANEL, width=285)
        self.queue_panel.pack(side="right", fill="y", padx=(8, 16), pady=16)
        self.queue_panel.pack_propagate(False)
        self._build_queue_panel()

    def _build_queue_panel(self):
        ctk.CTkLabel(self.queue_panel, text="Coda download",
                     font=("Segoe UI", 13, "bold"),
                     fg_color="transparent", text_color=TEXT).pack(pady=(14, 2))

        self.queue_count_label = ctk.CTkLabel(self.queue_panel, text="0 canzoni",
                                              fg_color="transparent",
                                              text_color=SUBTEXT, font=("Segoe UI", 9))
        self.queue_count_label.pack()
        ctk.CTkLabel(self.queue_panel, text="Doppio click per rimuovere",
                     fg_color="transparent",
                     text_color=SUBTEXT, font=("Segoe UI", 8)).pack(pady=(0, 6))

        list_frame = tk.Frame(self.queue_panel, bg=PANEL)
        list_frame.pack(fill="both", expand=True, padx=10)

        sb = ttk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")

        self.queue_listbox = tk.Listbox(
            list_frame, font=("Segoe UI", 9),
            bg=CARD, fg=TEXT, selectbackground=ACCENT, selectforeground=TEXT,
            activestyle="none", bd=0, highlightthickness=0, yscrollcommand=sb.set
        )
        self.queue_listbox.pack(side="left", fill="both", expand=True)
        sb.config(command=self.queue_listbox.yview)
        self.queue_listbox.bind("<Double-Button-1>", self._remove_on_dclick)

        btn_frame = ctk.CTkFrame(self.queue_panel, fg_color=PANEL)
        btn_frame.pack(fill="x", padx=10, pady=4)
        ctk.CTkButton(btn_frame, text="Rimuovi selezionati",
                      command=self._remove_from_queue,
                      fg_color=PANEL, hover_color=CARD, text_color=SUBTEXT,
                      font=("Segoe UI", 9), corner_radius=6).pack(fill="x", pady=2)
        ctk.CTkButton(btn_frame, text="Svuota coda",
                      command=self._clear_queue,
                      fg_color=PANEL, hover_color=CARD, text_color=SUBTEXT,
                      font=("Segoe UI", 9), corner_radius=6).pack(fill="x", pady=2)

        self.btn_download = ctk.CTkButton(
            self.queue_panel, text="Scarica tutto",
            command=self._start_download,
            fg_color=ACCENT, hover_color=ACCENT2, text_color=TEXT,
            font=("Segoe UI", 10, "bold"), corner_radius=6, state="disabled"
        )
        self.btn_download.pack(fill="x", padx=10, pady=(6, 12))

    # ── Pannello download ────────────────────────────────────

    def _show_download_panel(self, queue: list):
        total = len(queue)
        self._dl_total = total
        for w in self.queue_panel.winfo_children():
            w.destroy()

        ctk.CTkLabel(self.queue_panel, text="Download in corso",
                     font=("Segoe UI", 11, "bold"),
                     fg_color="transparent", text_color=TEXT).pack(pady=(12, 2))

        self._dl_general_label = ctk.CTkLabel(self.queue_panel, text=f"0 / {total}",
                                               font=("Segoe UI", 8),
                                               fg_color="transparent", text_color=SUBTEXT)
        self._dl_general_label.pack()

        list_frame = ctk.CTkFrame(self.queue_panel, fg_color=PANEL)
        list_frame.pack(fill="both", expand=True, padx=6, pady=(6, 4))

        scroll_frame = ctk.CTkScrollableFrame(list_frame, fg_color=PANEL)
        scroll_frame.pack(fill="both", expand=True)

        self._track_widgets = {}
        for item in queue:
            item_id = id(item)
            row = ctk.CTkFrame(scroll_frame, fg_color=PANEL)
            row.pack(fill="x", pady=1, padx=2)

            status_var = tk.StringVar(value="○")
            tk.Label(row, textvariable=status_var, font=("Segoe UI", 9),
                     bg=PANEL, fg=SUBTEXT, width=2, anchor="center").pack(side="left")

            lbl = item["label"]
            short = lbl[:24] + "…" if len(lbl) > 24 else lbl
            ctk.CTkLabel(row, text=short, font=("Segoe UI", 8),
                         fg_color="transparent", text_color=TEXT,
                         anchor="w").pack(side="left", fill="x", expand=True, padx=(2, 4))

            bar = ctk.CTkProgressBar(row, orientation="horizontal",
                                     progress_color=ACCENT, fg_color=CARD,
                                     width=55, height=6)
            bar.set(0)
            bar.pack(side="right")

            self._track_widgets[item_id] = (bar, status_var)

        bottom = ctk.CTkFrame(self.queue_panel, fg_color=PANEL)
        bottom.pack(fill="x", padx=8, pady=(4, 4))
        self._dl_general_bar = ctk.CTkProgressBar(
            bottom, orientation="horizontal",
            progress_color=ACCENT, fg_color=CARD
        )
        self._dl_general_bar.set(0)
        self._dl_general_bar.pack(fill="x", pady=2)

        ctk.CTkButton(self.queue_panel, text="Annulla download",
                      command=self._cancel_event.set,
                      fg_color=PANEL, hover_color=CARD, text_color=SUBTEXT,
                      font=("Segoe UI", 9), corner_radius=6).pack(fill="x", padx=8, pady=(2, 8))

        self._dl_active_frame = None
        self._dl_done_listbox = None

    def _track_started(self, item: dict, item_id: int):
        widgets = self._track_widgets.get(item_id)
        if widgets:
            widgets[1].set("▶")

    def _update_track_progress(self, item_id: int, percent: float):
        widgets = self._track_widgets.get(item_id)
        if widgets:
            widgets[0].set(percent / 100)

    def _track_completed(self, item: dict, item_id: int, ok: bool,
                         completed: int, total: int):
        widgets = self._track_widgets.get(item_id)
        if widgets:
            bar, status_var = widgets
            bar.set(1.0 if ok else 0.0)
            status_var.set("✓" if ok else "✗")

        if self._dl_general_label is not None:
            self._dl_general_label.configure(text=f"{completed} / {total}")
        if self._dl_general_bar is not None and total > 0:
            self._dl_general_bar.set(completed / total)

    def _restore_queue_panel(self):
        for w in self.queue_panel.winfo_children():
            w.destroy()
        self._dl_active_frame  = None
        self._dl_done_listbox  = None
        self._dl_general_bar   = None
        self._dl_general_label = None
        self._dl_total         = 0
        self._track_widgets    = {}
        self._build_queue_panel()

    # ── Utilità navigazione ──────────────────────────────────

    def _clear_nav(self):
        for w in self.nav_frame.winfo_children():
            w.destroy()

    def _nav_title(self, text, sub=None):
        ctk.CTkLabel(self.nav_frame, text=text, font=("Segoe UI", 16, "bold"),
                     fg_color="transparent", text_color=TEXT).pack(pady=(16, 2))
        if sub:
            ctk.CTkLabel(self.nav_frame, text=sub, font=("Segoe UI", 10),
                         fg_color="transparent", text_color=SUBTEXT).pack(pady=(0, 10))

    def _back_btn(self, text, cmd):
        ctk.CTkButton(self.nav_frame, text=text, command=cmd,
                      fg_color=PANEL, hover_color=CARD, text_color=SUBTEXT,
                      font=("Segoe UI", 9), corner_radius=6).pack(pady=(8, 0))

    # ── Schermata: Ricerca ───────────────────────────────────

    def _show_search(self):
        self._clear_nav()
        self._nav_title("Music Downloader")

        self.search_mode = tk.StringVar(value="artista")
        mode_row = ctk.CTkFrame(self.nav_frame, fg_color=BG)
        mode_row.pack(pady=(0, 10))
        ctk.CTkRadioButton(mode_row, text="Artista", variable=self.search_mode,
                           value="artista", text_color=TEXT, fg_color=ACCENT,
                           hover_color=ACCENT2).pack(side="left", padx=14)
        ctk.CTkRadioButton(mode_row, text="Canzone", variable=self.search_mode,
                           value="canzone", text_color=TEXT, fg_color=ACCENT,
                           hover_color=ACCENT2).pack(side="left", padx=14)

        search_row = ctk.CTkFrame(self.nav_frame, fg_color=BG)
        search_row.pack()
        self.search_var = tk.StringVar()
        entry = ctk.CTkEntry(search_row, textvariable=self.search_var,
                             width=280, font=("Segoe UI", 12),
                             fg_color=PANEL, text_color=TEXT,
                             border_color=BORDER, border_width=1)
        entry.pack(side="left", padx=(0, 8))
        entry.bind("<Return>", lambda _: self._do_search())
        entry.focus()
        ctk.CTkButton(search_row, text="Cerca", command=self._do_search,
                      fg_color=ACCENT, hover_color=ACCENT2, text_color=TEXT,
                      font=("Segoe UI", 10, "bold"), corner_radius=6).pack(side="left")

        self.search_status = ctk.CTkLabel(self.nav_frame, text="",
                                          fg_color="transparent",
                                          text_color=SUBTEXT, font=("Segoe UI", 10))
        self.search_status.pack(pady=6)

        recenti = self.cache.get_recent_searches(RECENT_SEARCHES_SHOWN)
        if recenti:
            ctk.CTkLabel(self.nav_frame, text="Ricerche recenti",
                         font=("Segoe UI", 9, "bold"),
                         fg_color="transparent", text_color=SUBTEXT).pack(pady=(8, 2))
            rec_frame = ctk.CTkFrame(self.nav_frame, fg_color=BG)
            rec_frame.pack()
            for s in recenti:
                tipo_label = "[A]" if s["type"] == "artista" else "[C]"
                ctk.CTkButton(
                    rec_frame,
                    text=f"{tipo_label} {s['query']}",
                    fg_color=PANEL, hover_color=CARD, text_color=SUBTEXT,
                    font=("Segoe UI", 9), corner_radius=6,
                    command=lambda q=s["query"], t=s["type"]: self._run_recent(q, t),
                ).pack(fill="x", pady=1)

    def _run_recent(self, query: str, tipo: str):
        self.search_mode.set(tipo)
        self.search_var.set(query)
        self._do_search()

    def _do_search(self):
        query = self.search_var.get().strip()
        if not query:
            return
        self.search_status.configure(text="Ricerca in corso...", text_color=SUBTEXT)
        self.root.update()
        if self.search_mode.get() == "canzone":
            self._do_track_search(query)
        else:
            self._do_artist_search(query)

    def _do_artist_search(self, query: str):
        def _work():
            try:
                artists = self.searcher.search_artist(query)
            except Exception as e:
                self.root.after(0, lambda: self.search_status.configure(text=f"Errore: {e}", text_color=ERROR))
                return
            if not artists:
                self.root.after(0, lambda: self.search_status.configure(text="Nessun artista trovato.", text_color=ERROR))
                return
            self.cache.add_search("artista", query)
            if len(artists) == 1:
                self.current_artist = artists[0]
                self.root.after(0, self._show_albums)
            else:
                self.root.after(0, self._show_artist_selection, artists)
        threading.Thread(target=_work, daemon=True).start()

    def _do_track_search(self, query: str):
        def _work():
            try:
                tracks = self.searcher.search_track(query)
            except Exception as e:
                self.root.after(0, lambda: self.search_status.configure(text=f"Errore: {e}", text_color=ERROR))
                return
            if not tracks:
                self.root.after(0, lambda: self.search_status.configure(text="Nessuna canzone trovata.", text_color=ERROR))
                return
            self.cache.add_search("canzone", query)
            self.root.after(0, self._show_track_results, tracks)
        threading.Thread(target=_work, daemon=True).start()

    # ── Schermata: Selezione artista ─────────────────────────

    def _show_artist_selection(self, artists: list):
        self._clear_nav()
        self._nav_title("Seleziona artista", "Doppio click per selezionare")

        artists = sorted(artists, key=lambda a: a["nome"].lower())

        f, tree = _scrolled_tree(self.nav_frame,
                                  columns=("nome", "album", "follower"),
                                  headings=("Artista", "Album", "Follower"),
                                  col_widths=(280, 80, 140))
        tree.column("album",    anchor="center", stretch=False)
        tree.column("follower", anchor="e",      stretch=False)
        f.pack(fill="both", expand=True)

        for i, a in enumerate(artists):
            follower = f"{a['followers']:,}" if a.get("followers") else "—"
            nb_album = str(a["nb_album"]) if a.get("nb_album") else "—"
            tree.insert("", tk.END, iid=str(i), values=(a["nome"], nb_album, follower))

        def on_dclick(event):
            item = tree.identify_row(event.y)
            if item:
                self.current_artist = artists[int(item)]
                self._show_albums()

        tree.bind("<Double-Button-1>", on_dclick)
        self._back_btn("← Nuova ricerca", self._show_search)

    # ── Schermata: Risultati ricerca canzone ─────────────────

    def _show_track_results(self, tracks: list):
        self._clear_nav()
        self._nav_title("Risultati ricerca",
                        f"{len(tracks)} canzoni trovate  —  doppio click per aggiungere alla coda")

        f, tree = _scrolled_tree(self.nav_frame,
                                  columns=("titolo", "artista"),
                                  headings=("Titolo", "Artista"),
                                  col_widths=(340, 220))
        f.pack(fill="both", expand=True)

        for i, t in enumerate(tracks):
            artist = t["artisti"][0] if t["artisti"] else "—"
            tree.insert("", tk.END, iid=str(i), values=(t["nome"], artist))

        def on_dclick(event):
            item = tree.identify_row(event.y)
            if not item:
                return
            t = tracks[int(item)]
            artist = t["artisti"][0] if t["artisti"] else ""
            query  = f"{artist} - {t['nome']}" if artist else t["nome"]
            label  = f"{t['nome']}  ({artist})" if artist else t["nome"]
            meta = {
                "title":       t["nome"],
                "artist":      artist,
                "albumartist": artist,
                "album":       t.get("album", ""),
                "year":        "",
                "tracknumber": "",
                "album_id":    str(t["album_id"]) if t.get("album_id") else "",
                "duration":    t.get("duration", 0),
            }
            self._add_to_queue(query, label, meta)

        tree.bind("<Double-Button-1>", on_dclick)

        def show_track_menu(event):
            item = tree.identify_row(event.y)
            if not item:
                return
            tree.selection_set(item)
            t = tracks[int(item)]
            artist_name = t["artisti"][0] if t["artisti"] else ""
            menu = tk.Menu(self.root, tearoff=0, bg=CARD, fg=TEXT,
                           activebackground=ACCENT, activeforeground=TEXT, borderwidth=0)
            if t.get("artist_id") and artist_name:
                menu.add_command(
                    label="Vai all'artista",
                    command=lambda: self._goto_artist(t["artist_id"], artist_name))
            if t.get("album_id") and t.get("album"):
                menu.add_command(
                    label="Vai all'album",
                    command=lambda: self._goto_album(
                        t["artist_id"], artist_name, t["album_id"], t["album"]))
            if menu.index("end") is not None:
                menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", show_track_menu)
        self._back_btn("← Nuova ricerca", self._show_search)

    # ── Schermata: Album ─────────────────────────────────────

    def _build_filter_sort_controls(self, parent) -> tuple:
        controls = ctk.CTkFrame(parent, fg_color=BG)
        controls.pack(fill="x", pady=(0, 6))

        filter_var   = tk.StringVar()
        filter_entry = ctk.CTkEntry(controls, textvariable=filter_var,
                                    font=("Segoe UI", 10), width=210,
                                    fg_color=PANEL, text_color=TEXT,
                                    border_color=BORDER, border_width=1)
        filter_entry.pack(side="left", padx=(0, 10))
        filter_entry.insert(0, "Filtra album...")

        def on_focus_in(e):
            if filter_entry.get() == "Filtra album...":
                filter_entry.delete(0, tk.END)
        def on_focus_out(e):
            if not filter_entry.get():
                filter_entry.insert(0, "Filtra album...")

        filter_entry.bind("<FocusIn>",  on_focus_in)
        filter_entry.bind("<FocusOut>", on_focus_out)

        ctk.CTkLabel(controls, text="Ordina:", fg_color="transparent",
                     text_color=SUBTEXT, font=("Segoe UI", 9)).pack(side="left")

        sort_var = tk.StringVar(value=self.SORT_OPTIONS[0])
        ctk.CTkComboBox(controls, variable=sort_var, values=self.SORT_OPTIONS,
                        state="readonly", width=130, font=("Segoe UI", 9),
                        fg_color=PANEL, text_color=TEXT,
                        button_color=PANEL, button_hover_color=CARD,
                        dropdown_fg_color=PANEL, dropdown_text_color=TEXT,
                        border_color=BORDER, border_width=1).pack(side="left", padx=(4, 0))

        return filter_var, sort_var

    def _bind_album_context_menu(self):
        def show_menu(event):
            idx = self.albums_lb.nearest(event.y)
            if idx < 0 or idx >= len(self.filtered_albums):
                return
            if idx not in self.albums_lb.curselection():
                self.albums_lb.selection_clear(0, tk.END)
                self.albums_lb.selection_set(idx)

            selected_indices = list(self.albums_lb.curselection())
            selected_albums  = [self.filtered_albums[i] for i in selected_indices
                                 if i < len(self.filtered_albums)]
            album       = self.filtered_albums[idx]
            artist_name = album["artisti"][0] if album.get("artisti") else ""

            menu = tk.Menu(self.root, tearoff=0, bg=CARD, fg=TEXT,
                           activebackground=ACCENT, activeforeground=TEXT, borderwidth=0)
            if len(selected_albums) == 1:
                if album.get("artist_id") and artist_name:
                    menu.add_command(
                        label="Vai all'artista",
                        command=lambda: self._goto_artist(album["artist_id"], artist_name))
                menu.add_command(
                    label="Scarica album",
                    command=lambda: self._download_album_direct(album))
            else:
                menu.add_command(
                    label=f"Scarica {len(selected_albums)} album selezionati",
                    command=lambda a=selected_albums: self._download_albums_batch(a))
            menu.tk_popup(event.x_root, event.y_root)

        self.albums_lb.bind("<Button-3>", show_menu)

    def _show_albums(self):
        self._clear_nav()
        self._nav_title(f"Album di {self.current_artist['nome']}")

        status = ctk.CTkLabel(self.nav_frame, text="Caricamento album...",
                              fg_color="transparent",
                              text_color=SUBTEXT, font=("Segoe UI", 10))
        status.pack()

        def _fetch():
            try:
                albums = self.searcher.get_artist_albums(self.current_artist["id"])
            except Exception as e:
                self.root.after(0, lambda: status.configure(text=f"Errore: {e}", text_color=ERROR))
                return
            self.root.after(0, lambda: self._finish_show_albums(albums, status))

        threading.Thread(target=_fetch, daemon=True).start()

    def _finish_show_albums(self, albums: list, status_label: ctk.CTkLabel):
        status_label.destroy()
        self.current_albums = albums

        ctk.CTkLabel(self.nav_frame,
                     text=f"{len(self.current_albums)} album trovati  —  doppio click per vedere le tracce",
                     fg_color="transparent",
                     text_color=SUBTEXT, font=("Segoe UI", 9)).pack(pady=(0, 6))

        list_frame = tk.Frame(self.nav_frame, bg=BG)
        list_frame.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")
        self.albums_lb = tk.Listbox(
            list_frame, font=("Segoe UI", 11),
            bg=PANEL, fg=TEXT, selectbackground=ACCENT, selectforeground=TEXT,
            activestyle="none", bd=0, highlightthickness=0, yscrollcommand=sb.set,
            selectmode=tk.EXTENDED
        )
        self.albums_lb.pack(side="left", fill="both", expand=True)
        sb.config(command=self.albums_lb.yview)

        filter_var, sort_var = self._build_filter_sort_controls(self.nav_frame)

        def sorted_albums(albums):
            def year_key(a):
                try:
                    return int(a["anno"])
                except (ValueError, TypeError):
                    return 0
            mode = sort_var.get()
            if mode == "Nome A→Z": return sorted(albums, key=lambda a: a["nome"].lower())
            if mode == "Nome Z→A": return sorted(albums, key=lambda a: a["nome"].lower(), reverse=True)
            if mode == "Anno ↑":   return sorted(albums, key=year_key)
            if mode == "Anno ↓":   return sorted(albums, key=year_key, reverse=True)
            return albums

        def refresh_list(*_):
            text = filter_var.get().lower()
            if text == "filtra album...":
                text = ""
            self.filtered_albums = sorted_albums(
                [a for a in self.current_albums if text in a["nome"].lower()])
            self.albums_lb.delete(0, tk.END)
            for album in self.filtered_albums:
                self.albums_lb.insert(tk.END, f"  {album['nome']}  ({album['anno']})")

        filter_var.trace_add("write", refresh_list)
        sort_var.trace_add("write",   refresh_list)
        refresh_list()

        self.albums_lb.bind("<Double-Button-1>", self._on_album_dclick)
        self._bind_album_context_menu()
        self._back_btn("← Nuova ricerca", self._show_search)

    def _on_album_dclick(self, event):
        idx = self.albums_lb.nearest(event.y)
        if 0 <= idx < len(self.filtered_albums):
            self._show_tracks(self.filtered_albums[idx])

    # ── Schermata: Tracce ────────────────────────────────────

    def _show_tracks(self, album: dict):
        self._clear_nav()
        self._nav_title(album["nome"],
                        f"{self.current_artist['nome']}  •  {album['anno']}")

        status = ctk.CTkLabel(self.nav_frame, text="Caricamento tracce...",
                              fg_color="transparent",
                              text_color=SUBTEXT, font=("Segoe UI", 10))
        status.pack(pady=4)

        def _fetch():
            try:
                tracks = self.searcher.get_album_tracks(album["id"])
            except Exception as e:
                self.root.after(0, lambda: status.configure(text=f"Errore: {e}", text_color=ERROR))
                return
            self.root.after(0, lambda: self._finish_show_tracks(tracks, album, status))

        threading.Thread(target=_fetch, daemon=True).start()

    def _finish_show_tracks(self, tracks: list, album: dict, status_label: ctk.CTkLabel):
        status_label.destroy()
        self.current_tracks = tracks

        ctk.CTkLabel(self.nav_frame, text="Doppio click per aggiungere alla coda",
                     fg_color="transparent",
                     text_color=SUBTEXT, font=("Segoe UI", 9)).pack(pady=(0, 6))

        f, tree = _scrolled_tree(self.nav_frame,
                                  columns=("num", "titolo", "artista"),
                                  headings=("#", "Titolo", "Artista"),
                                  col_widths=(46, 320, 200))
        tree.column("num", anchor="center", stretch=False)
        f.pack(fill="both", expand=True)

        for i, track in enumerate(self.current_tracks):
            tree.insert("", tk.END, iid=str(i),
                        values=(f"{track['numero']:02d}",
                                track["nome"],
                                ", ".join(track["artisti"])))

        def on_dclick(event):
            item = tree.identify_row(event.y)
            if item:
                track = self.current_tracks[int(item)]
                self._add_to_queue(
                    self._make_query(track),
                    self._make_label(track, album),
                    self._make_meta(track, album),
                )

        tree.bind("<Double-Button-1>", on_dclick)

        def show_track_menu(event):
            item = tree.identify_row(event.y)
            if not item:
                return
            tree.selection_set(item)
            menu = tk.Menu(self.root, tearoff=0, bg=CARD, fg=TEXT,
                           activebackground=ACCENT, activeforeground=TEXT, borderwidth=0)
            menu.add_command(
                label="Vai all'artista",
                command=lambda: self._goto_artist(
                    self.current_artist["id"], self.current_artist["nome"]))
            menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", show_track_menu)

        btn_row = ctk.CTkFrame(self.nav_frame, fg_color=BG)
        btn_row.pack(pady=10)
        ctk.CTkButton(btn_row, text="+ Aggiungi tutto l'album",
                      command=lambda: self._add_all_tracks(album),
                      fg_color=ACCENT, hover_color=ACCENT2, text_color=TEXT,
                      font=("Segoe UI", 10, "bold"), corner_radius=6).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="← Torna agli album",
                      command=self._show_albums,
                      fg_color=PANEL, hover_color=CARD, text_color=SUBTEXT,
                      font=("Segoe UI", 9), corner_radius=6).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Nuova ricerca",
                      command=self._show_search,
                      fg_color=PANEL, hover_color=CARD, text_color=SUBTEXT,
                      font=("Segoe UI", 9), corner_radius=6).pack(side="left", padx=4)

    # ── Gestione coda ────────────────────────────────────────

    def _make_query(self, track: dict) -> str:
        artist = track["artisti"][0] if track["artisti"] else self.current_artist["nome"]
        return f"{artist} - {track['nome']}"

    def _make_label(self, track: dict, album: dict) -> str:
        return f"{track['nome']}  ({album['nome']})"

    def _make_meta(self, track: dict, album: dict) -> dict:
        artist = ", ".join(track["artisti"]) if track["artisti"] else self.current_artist["nome"]
        return {
            "title":       track["nome"],
            "artist":      artist,
            "albumartist": self.current_artist["nome"] if self.current_artist else artist,
            "album":       album.get("nome", ""),
            "year":        album.get("anno", ""),
            "tracknumber": str(track["numero"]) if track.get("numero") else "",
            "album_id":    str(album.get("id", "")),
            "duration":    track.get("duration", 0),
        }

    def _add_all_tracks(self, album: dict):
        for track in self.current_tracks:
            self._add_to_queue(
                self._make_query(track),
                self._make_label(track, album),
                self._make_meta(track, album),
            )

    def _add_to_queue(self, query: str, label: str, meta: dict = None):
        if any(item["query"] == query for item in self.download_queue):
            return
        self.download_queue.append({"query": query, "label": label, "meta": meta or {}})
        self.queue_listbox.insert(tk.END, f"  {label}")
        self._refresh_queue_ui()

    def _remove_on_dclick(self, event):
        idx = self.queue_listbox.nearest(event.y)
        if idx >= 0:
            self.queue_listbox.delete(idx)
            self.download_queue.pop(idx)
            self._refresh_queue_ui()

    def _remove_from_queue(self):
        for idx in reversed(self.queue_listbox.curselection()):
            self.queue_listbox.delete(idx)
            self.download_queue.pop(idx)
        self._refresh_queue_ui()

    def _clear_queue(self):
        self.queue_listbox.delete(0, tk.END)
        self.download_queue.clear()
        self._refresh_queue_ui()

    def _refresh_queue_ui(self):
        n = len(self.download_queue)
        self.queue_count_label.configure(text=f"{n} {'canzone' if n == 1 else 'canzoni'}")
        self.btn_download.configure(state="normal" if n > 0 else "disabled")

    # ── Download ─────────────────────────────────────────────

    def _start_download(self):
        destination = filedialog.askdirectory(title="Seleziona cartella di destinazione")
        if not destination:
            return
        queue = list(self.download_queue)
        self._cancel_event.clear()
        self.btn_download.configure(state="disabled")
        self._show_download_panel(queue)
        threading.Thread(
            target=self._run_download,
            args=(queue, destination),
            kwargs={"clear_queue": True},
            daemon=True,
        ).start()

    def _get_genre(self, album_id: str) -> tuple:
        if not album_id:
            return "", 0
        if album_id in self._genre_cache:
            return self._genre_cache[album_id], self._nb_tracks_cache.get(album_id, 0)
        try:
            details = self.searcher.get_album_details(album_id)
            genre     = details.get("genre", "")
            nb_tracks = details.get("nb_tracks", 0)
            cover_url = details.get("cover_xl", "")
            self._genre_cache[album_id]     = genre
            self._nb_tracks_cache[album_id] = nb_tracks
            self._cover_cache[album_id]     = cover_url
            return genre, nb_tracks
        except Exception:
            return "", 0

    @staticmethod
    def _tag_file(filepath: str, meta: dict) -> None:
        if not filepath or not Path(filepath).exists():
            return
        try:
            try:
                tags = EasyID3(filepath)
            except ID3NoHeaderError:
                tags = EasyID3()
                tags.save(filepath)
                tags = EasyID3(filepath)
            mapping = {
                "title":       meta.get("title"),
                "artist":      meta.get("artist"),
                "albumartist": meta.get("albumartist"),
                "album":       meta.get("album"),
                "date":        meta.get("year"),
                "tracknumber": meta.get("tracknumber"),
                "genre":       meta.get("genre"),
            }
            for key, val in mapping.items():
                if val:
                    tags[key] = [str(val)]
                    logger.debug(f"[Tags] {key}={val!r} → {Path(filepath).name}")
            tags.save()
        except Exception as e:
            logger.error(f"[Tags] Errore su {filepath}: {e}")
        cover_url = meta.get("cover_url", "")
        if cover_url:
            try:
                tags2 = ID3(filepath)
                tags2.delall("APIC")
                with urllib.request.urlopen(cover_url, timeout=10) as resp:
                    img_data = resp.read()
                tags2.add(APIC(encoding=3, mime="image/jpeg", type=3,
                               desc="Cover", data=img_data))
                tags2.save()
                logger.debug(f"[Tags] Copertina incorporata: {Path(filepath).name}")
            except Exception as e:
                logger.error(f"[Tags] Errore artwork {filepath}: {e}")

    def _prepare_meta(self, item: dict, genre_info: tuple = None) -> dict:
        meta             = dict(item.get("meta") or {})
        genre, nb_tracks = genre_info if genre_info is not None \
                           else self._get_genre(meta.get("album_id", ""))
        if genre:
            meta["genre"] = genre
        if meta.get("tracknumber") and nb_tracks:
            meta["tracknumber"] = f"{meta['tracknumber']}/{nb_tracks}"
        album_id = meta.get("album_id", "")
        if album_id and album_id in self._cover_cache:
            meta["cover_url"] = self._cover_cache[album_id]
        return meta

    def _resolve_url(self, item: dict) -> List[str]:
        query = item["query"]
        cached = self.cache.get_youtube_urls(query)
        if cached:
            return cached
        meta = item.get("meta") or {}
        urls = self.downloader.search_youtube(
            query,
            artist   = meta.get("artist", ""),
            title    = meta.get("title", ""),
            duration = meta.get("duration", 0),
        )
        if urls:
            self.cache.set_youtube_urls(query, urls)
        return urls

    def _download_single(self, item: dict, destination: str,
                         progress_cb=None, genre_info: tuple = None,
                         urls: List[str] = None) -> tuple:
        dest     = item.get("destination") or destination
        meta     = self._prepare_meta(item, genre_info)
        title    = meta.get("title") or item["label"]
        artist   = meta.get("artist") or ""
        raw_name = f"{artist} - {title}" if artist else title
        filename = re.sub(r'[<>:"/\\|?*\n\r\t]', '_', raw_name).strip()[:FILENAME_MAX_LENGTH]

        logger.info(f"[Download] Inizio: '{item['label']}' → query='{item['query']}'")

        if Path(dest, f"{filename}.mp3").exists():
            logger.info(f"[Download] Saltato (già esiste): {filename}.mp3")
            return True, None

        if urls is None:
            urls = self._resolve_url(item)
        if not urls:
            logger.warning(f"[Download] Nessun URL trovato per: '{item['label']}'")
            return False, item["label"]

        for i, url in enumerate(urls):
            try:
                logger.debug(f"[Download] Tentativo {i+1}/{len(urls)}: {url}")
                filepath = self.downloader.download(url, dest, filename=filename,
                                                    progress_callback=progress_cb)
                self._tag_file(filepath, meta)
                logger.info(f"[Download] Completato: {filepath}")
                return True, None
            except Exception as e:
                logger.warning(f"[Download] URL {i+1} fallito per '{item['label']}': {e}")
                continue

        logger.error(f"[Download] Tutti gli URL esauriti per: '{item['label']}'")
        return False, item["label"]

    def _run_download(self, queue: list, destination: str,
                      genre_info: tuple = None, artist_name: str = None,
                      clear_queue: bool = False):
        total = len(queue)
        lock  = threading.Lock()
        state = {"successi": 0, "falliti": [], "completed": 0}
        ready: Queue = Queue()

        logger.info(f"[Batch] Inizio download: {total} tracce → {destination}")

        def resolver():
            seen: set = set()
            for item in queue:
                if genre_info is None:
                    aid = (item.get("meta") or {}).get("album_id", "")
                    if aid and aid not in seen:
                        seen.add(aid)
                        self._get_genre(aid)
            for item in queue:
                if self._cancel_event.is_set():
                    break
                ready.put(item)
            for _ in range(MAX_WORKERS):
                ready.put(None)

        def worker():
            while True:
                item = ready.get()
                if item is None:
                    break
                item_id = id(item)

                if self._cancel_event.is_set():
                    with lock:
                        state["completed"] += 1
                        state["falliti"].append(f"{item['label']} (annullato)")
                        c = state["completed"]
                    logger.info(f"[Download] Annullato: '{item['label']}'")
                    self.root.after(0, self._track_completed, item, item_id, False, c, total)
                    continue

                self.root.after(0, self._track_started, item, item_id)

                def progress_cb(percent, _id=item_id):
                    self.root.after(0, self._update_track_progress, _id, percent)

                try:
                    ok, err = self._download_single(item, destination, progress_cb, genre_info)
                except Exception as e:
                    logger.error(f"[Worker] Eccezione non gestita per '{item['label']}': {e}", exc_info=True)
                    ok, err = False, f"{item['label']} ({str(e)[:40]})"

                with lock:
                    state["completed"] += 1
                    if ok:
                        state["successi"] += 1
                    else:
                        state["falliti"].append(err)
                    c = state["completed"]

                self.root.after(0, self._track_completed, item, item_id, ok, c, total)

        resolver_t = threading.Thread(target=resolver, daemon=True)
        resolver_t.start()

        workers = [threading.Thread(target=worker, daemon=True) for _ in range(MAX_WORKERS)]
        for t in workers:
            t.start()

        resolver_t.join()
        for t in workers:
            t.join()

        logger.info(f"[Batch] Fine: {state['successi']}/{total} successi, {len(state['falliti'])} falliti")

        self.root.after(0, self._download_all_done,
                        state["successi"], state["falliti"],
                        queue, destination, artist_name, clear_queue)

    def _download_all_done(self, successi: int, falliti: list, queue: list,
                           destination: str, artist_name: str, clear_queue: bool):
        self._restore_queue_panel()
        totale = len(queue)

        if len(queue) == 1:
            entry_type = "track"
            nome    = queue[0].get("label", queue[0].get("query", ""))
            artista = queue[0].get("meta", {}).get("artist", "") or artist_name or ""
        else:
            entry_type = "album"
            nome    = queue[0].get("meta", {}).get("album", "") or "Album"
            artista = artist_name or queue[0].get("meta", {}).get("albumartist", "")

        self.cache.add_download({
            "type":        entry_type,
            "nome":        nome,
            "artista":     artista,
            "destination": destination,
            "successi":    successi,
            "totale":      totale,
        })
        self._refresh_history_menu()

        if clear_queue:
            self._clear_queue()
        else:
            self._refresh_queue_ui()

        msg = f"Download completato!\n\nTotali: {totale}\nSuccessi: {successi}"
        if falliti:
            msg += f"\nFalliti: {len(falliti)}\n" + "\n".join(f"  - {f}" for f in falliti[:10])
        messagebox.showinfo("Download completato", msg)

        try:
            path = Path(destination).resolve()
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.run(["open", str(path)])
            else:
                import subprocess
                subprocess.run(["xdg-open", str(path)])
        except Exception:
            pass

    # ── Navigazione contestuale ──────────────────────────────

    def _goto_artist(self, artist_id, artist_name: str):
        self.current_artist = {"id": artist_id, "nome": artist_name}
        self._show_albums()

    def _goto_album(self, artist_id, artist_name: str, album_id, album_name: str):
        self.current_artist = {"id": artist_id, "nome": artist_name}
        try:
            details = self.searcher.get_album_details(str(album_id))
            anno = details.get("anno", "")
            aid = str(album_id)
            self._genre_cache[aid]     = details.get("genre", "")
            self._nb_tracks_cache[aid] = details.get("nb_tracks", 0)
            self._cover_cache[aid]     = details.get("cover_xl", "")
        except Exception:
            anno = ""
        self._show_tracks({"id": album_id, "nome": album_name, "anno": anno})

    # ── Download diretto album ───────────────────────────────

    @staticmethod
    def _safe_name(name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()[:FILENAME_MAX_LENGTH]

    def _download_albums_batch(self, albums: list):
        destination = filedialog.askdirectory(title="Seleziona cartella di destinazione")
        if not destination:
            return

        queue = []
        for album in albums:
            try:
                tracks = self.searcher.get_album_tracks(album["id"])
            except Exception as e:
                messagebox.showerror("Errore", f"Impossibile caricare '{album['nome']}': {e}")
                return
            album_folder = str(Path(destination) / self._safe_name(album["nome"]))
            Path(album_folder).mkdir(parents=True, exist_ok=True)
            for track in tracks:
                queue.append({
                    "query":       self._make_query(track),
                    "label":       track["nome"],
                    "meta":        self._make_meta(track, album),
                    "destination": album_folder,
                })

        if not queue:
            return

        artist_name = self.current_artist["nome"] if self.current_artist else ""
        self._cancel_event.clear()
        self._show_download_panel(queue)
        threading.Thread(
            target=self._run_download,
            args=(queue, destination),
            kwargs={"artist_name": artist_name, "clear_queue": False},
            daemon=True,
        ).start()

    def _download_album_direct(self, album: dict):
        destination = filedialog.askdirectory(title="Seleziona cartella di destinazione")
        if not destination:
            return
        try:
            tracks = self.searcher.get_album_tracks(album["id"])
        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile caricare le tracce: {e}")
            return

        album_folder = Path(destination) / self._safe_name(album["nome"])
        album_folder.mkdir(parents=True, exist_ok=True)

        queue = [
            {
                "query": self._make_query(track),
                "label": track["nome"],
                "meta":  self._make_meta(track, album),
            }
            for track in tracks
        ]

        artist_name = self.current_artist["nome"] if self.current_artist else ""
        genre_info  = self._get_genre(str(album.get("id", "")))

        self._cancel_event.clear()
        self._show_download_panel(queue)
        threading.Thread(
            target=self._run_download,
            args=(queue, str(album_folder)),
            kwargs={"genre_info": genre_info, "artist_name": artist_name, "clear_queue": False},
            daemon=True,
        ).start()


# ─────────────────────────────────────────────────────────────
# Avvio
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = ctk.CTk()
    MusicDownloaderApp(root)
    root.mainloop()
