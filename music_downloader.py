import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import requests
import yt_dlp
import sys
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

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
BORDER  = "#4b5563"

# ─────────────────────────────────────────────────────────────
# MusicSearcher  –  Deezer metadata client
# ─────────────────────────────────────────────────────────────
class MusicSearcher:
    BASE = "https://api.deezer.com"

    def _get(self, url: str, params: Optional[Dict] = None) -> Dict:
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, timeout=10)
                if not r.ok:
                    print(f"[MusicSearcher] HTTP {r.status_code} per {url}: {r.text[:300]}",
                          file=sys.stderr)
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    raise RuntimeError(
                        f"Deezer error {data['error'].get('code')}: {data['error'].get('message')}"
                    )
                return data
            except requests.RequestException as e:
                print(f"[MusicSearcher] Tentativo {attempt+1}/3 fallito: {e}", file=sys.stderr)
                if attempt == 2:
                    raise RuntimeError(f"Richiesta fallita dopo 3 tentativi: {e}")
                time.sleep(1 * (2 ** attempt))

    def search_artist(self, name: str) -> List[Dict]:
        data = self._get(f"{self.BASE}/search/artist", {"q": name, "limit": 5})
        return [
            {"id": a["id"], "nome": a["name"], "followers": a.get("nb_fan", 0), "generi": []}
            for a in data.get("data", []) if a.get("id")
        ]

    def search_track(self, query: str) -> List[Dict]:
        data = self._get(f"{self.BASE}/search/track", {"q": query, "limit": 50})
        return [
            {
                "id": t["id"],
                "nome": t["title"],
                "artisti": [t["artist"]["name"]] if t.get("artist") else [],
                "album": t["album"]["title"] if t.get("album") else "",
            }
            for t in data.get("data", []) if t.get("id")
        ]

    def get_artist_albums(self, artist_id: str) -> List[Dict]:
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
                    })
            url = data.get("next")
        return albums

    def get_album_tracks(self, album_id: str) -> List[Dict]:
        data = self._get(f"{self.BASE}/album/{album_id}/tracks")
        return [
            {
                "id": track["id"],
                "nome": track["title"],
                "artisti": [track["artist"]["name"]] if track.get("artist") else [],
                "numero": track.get("track_position", 0),
            }
            for track in data.get("data", [])
        ]


# ─────────────────────────────────────────────────────────────
# AudioDownloader  –  YouTube search + download via yt-dlp
# ─────────────────────────────────────────────────────────────
class AudioDownloader:

    @staticmethod
    def search_youtube(query: str) -> Optional[str]:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
                results = ydl.extract_info(f"ytsearch1:{query}", download=False)
                if results.get("entries"):
                    return results["entries"][0]["url"]
        except Exception as e:
            print(f"[AudioDownloader] Errore ricerca '{query}': {e}", file=sys.stderr)
        return None

    @staticmethod
    def download(url: str, destination: str, progress_callback=None) -> None:
        outtmpl = str(Path(destination) / "%(title)s.%(ext)s")

        def _hook(d):
            if progress_callback and d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                if total:
                    progress_callback(downloaded / total * 100)

        opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }],
            "noplaylist": True,
            "quiet": True,
            "progress_hooks": [_hook],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])


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

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Music Downloader")
        self.root.geometry("1020x660")
        self.root.resizable(True, True)
        self.root.configure(bg=BG)

        self._setup_style()

        self.searcher   = MusicSearcher()
        self.downloader = AudioDownloader()

        self.download_queue:   list = []
        self.current_artist:   dict = None
        self.current_albums:   list = []
        self.filtered_albums:  list = []
        self.current_tracks:   list = []

        self._build_layout()
        self._show_search()

    # ── Stile ────────────────────────────────────────────────

    def _setup_style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")

        s.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        s.configure("TFrame",  background=BG)
        s.configure("TLabel",  background=BG, foreground=TEXT)

        s.configure("Accent.TButton", background=ACCENT, foreground=TEXT,
                    font=("Segoe UI", 10, "bold"), borderwidth=0,
                    focusthickness=0, padding=(14, 7))
        s.map("Accent.TButton",
              background=[("active", ACCENT2), ("disabled", CARD)],
              foreground=[("disabled", SUBTEXT)])

        s.configure("Ghost.TButton", background=PANEL, foreground=SUBTEXT,
                    font=("Segoe UI", 9), borderwidth=0, focusthickness=0, padding=(10, 5))
        s.map("Ghost.TButton",
              background=[("active", CARD)],
              foreground=[("active", TEXT)])

        s.configure("TEntry", fieldbackground=PANEL, foreground=TEXT,
                    insertcolor=TEXT, borderwidth=0, padding=(8, 6))

        s.configure("Music.Treeview", background=PANEL, foreground=TEXT,
                    fieldbackground=PANEL, borderwidth=0, rowheight=30,
                    font=("Segoe UI", 10))
        s.configure("Music.Treeview.Heading", background=CARD, foreground=SUBTEXT,
                    font=("Segoe UI", 9, "bold"), borderwidth=0,
                    relief="flat", padding=(8, 6))
        s.map("Music.Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", TEXT)])

        s.configure("Music.Horizontal.TProgressbar", background=ACCENT,
                    troughcolor=CARD, borderwidth=0, thickness=6)

        s.configure("TRadiobutton", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        s.map("TRadiobutton", background=[("active", BG)], foreground=[("active", TEXT)])

        s.configure("TCombobox", fieldbackground=PANEL, background=PANEL,
                    foreground=TEXT, arrowcolor=SUBTEXT, borderwidth=0)
        s.map("TCombobox",
              fieldbackground=[("readonly", PANEL)],
              foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", PANEL)],
              selectforeground=[("readonly", TEXT)])

        s.configure("TScrollbar", background=CARD, troughcolor=PANEL,
                    borderwidth=0, arrowsize=12, arrowcolor=SUBTEXT)
        s.map("TScrollbar", background=[("active", BORDER)])

    # ── Layout principale ────────────────────────────────────

    def _build_layout(self):
        self.nav_frame = tk.Frame(self.root, bg=BG)
        self.nav_frame.pack(side="left", fill="both", expand=True, padx=(16, 8), pady=16)

        tk.Frame(self.root, width=1, bg=BORDER).pack(side="left", fill="y", pady=8)

        self.queue_panel = tk.Frame(self.root, bg=PANEL, width=285)
        self.queue_panel.pack(side="right", fill="y", padx=(8, 16), pady=16)
        self.queue_panel.pack_propagate(False)
        self._build_queue_panel()

    def _build_queue_panel(self):
        tk.Label(self.queue_panel, text="Coda download",
                 font=("Segoe UI", 13, "bold"), bg=PANEL, fg=TEXT).pack(pady=(14, 2))

        self.queue_count_var = tk.StringVar(value="0 canzoni")
        tk.Label(self.queue_panel, textvariable=self.queue_count_var,
                 fg=SUBTEXT, font=("Segoe UI", 9), bg=PANEL).pack()
        tk.Label(self.queue_panel, text="Doppio click per rimuovere",
                 fg=SUBTEXT, font=("Segoe UI", 8), bg=PANEL).pack(pady=(0, 6))

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

        btn_frame = tk.Frame(self.queue_panel, bg=PANEL)
        btn_frame.pack(fill="x", padx=10, pady=4)
        ttk.Button(btn_frame, text="Rimuovi selezionati",
                   command=self._remove_from_queue, style="Ghost.TButton").pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="Svuota coda",
                   command=self._clear_queue, style="Ghost.TButton").pack(fill="x", pady=2)

        self.btn_download = ttk.Button(
            self.queue_panel, text="Scarica tutto",
            command=self._start_download, style="Accent.TButton", state="disabled"
        )
        self.btn_download.pack(fill="x", padx=10, pady=(6, 12))

        self.progress_outer = tk.Frame(self.queue_panel, bg=PANEL)
        self.progress_label = tk.Label(self.progress_outer, text="",
                                       font=("Segoe UI", 8), wraplength=240,
                                       bg=PANEL, fg=SUBTEXT)
        self.progress_label.pack()
        self.progress_bar = ttk.Progressbar(
            self.progress_outer, orient="horizontal", length=240,
            mode="determinate", style="Music.Horizontal.TProgressbar"
        )
        self.progress_bar.pack(pady=4)

    # ── Utilità navigazione ──────────────────────────────────

    def _clear_nav(self):
        for w in self.nav_frame.winfo_children():
            w.destroy()

    def _nav_title(self, text, sub=None):
        tk.Label(self.nav_frame, text=text, font=("Segoe UI", 16, "bold"),
                 bg=BG, fg=TEXT).pack(pady=(16, 2))
        if sub:
            tk.Label(self.nav_frame, text=sub, font=("Segoe UI", 10),
                     bg=BG, fg=SUBTEXT).pack(pady=(0, 10))

    def _back_btn(self, text, cmd):
        ttk.Button(self.nav_frame, text=text, command=cmd,
                   style="Ghost.TButton").pack(pady=(8, 0))

    # ── Schermata: Ricerca ───────────────────────────────────

    def _show_search(self):
        self._clear_nav()
        self._nav_title("Music Downloader")

        self.search_mode = tk.StringVar(value="artista")
        mode_row = tk.Frame(self.nav_frame, bg=BG)
        mode_row.pack(pady=(0, 10))
        ttk.Radiobutton(mode_row, text="Artista", variable=self.search_mode,
                        value="artista").pack(side="left", padx=14)
        ttk.Radiobutton(mode_row, text="Canzone", variable=self.search_mode,
                        value="canzone").pack(side="left", padx=14)

        search_row = tk.Frame(self.nav_frame, bg=BG)
        search_row.pack()
        self.search_var = tk.StringVar()
        entry = ttk.Entry(search_row, textvariable=self.search_var,
                          width=34, font=("Segoe UI", 12))
        entry.pack(side="left", padx=(0, 8))
        entry.bind("<Return>", lambda _: self._do_search())
        entry.focus()
        ttk.Button(search_row, text="Cerca", command=self._do_search,
                   style="Accent.TButton").pack(side="left")

        self.search_status = tk.Label(self.nav_frame, text="",
                                      fg=SUBTEXT, font=("Segoe UI", 10), bg=BG)
        self.search_status.pack(pady=6)

    def _do_search(self):
        query = self.search_var.get().strip()
        if not query:
            return
        self.search_status.config(text="Ricerca in corso...", fg=SUBTEXT)
        self.root.update()
        if self.search_mode.get() == "canzone":
            self._do_track_search(query)
        else:
            self._do_artist_search(query)

    def _do_artist_search(self, query: str):
        try:
            artists = self.searcher.search_artist(query)
        except Exception as e:
            print(f"[Errore ricerca artista] {e}", file=sys.stderr)
            self.search_status.config(text=f"Errore: {e}", fg=ERROR)
            return
        if not artists:
            self.search_status.config(text="Nessun artista trovato.", fg=ERROR)
            return
        if len(artists) == 1:
            self.current_artist = artists[0]
            self._show_albums()
        else:
            self._show_artist_selection(artists)

    def _do_track_search(self, query: str):
        try:
            tracks = self.searcher.search_track(query)
        except Exception as e:
            print(f"[Errore ricerca canzone] {e}", file=sys.stderr)
            self.search_status.config(text=f"Errore: {e}", fg=ERROR)
            return
        if not tracks:
            self.search_status.config(text="Nessuna canzone trovata.", fg=ERROR)
            return
        self._show_track_results(tracks)

    # ── Schermata: Selezione artista ─────────────────────────

    def _show_artist_selection(self, artists: list):
        self._clear_nav()
        self._nav_title("Seleziona artista", "Doppio click per selezionare")

        f, tree = _scrolled_tree(self.nav_frame,
                                  columns=("nome", "fans"),
                                  headings=("Artista", "Fan"),
                                  col_widths=(320, 120))
        f.pack(fill="both", expand=True)

        for i, a in enumerate(artists):
            fans = f"{a['followers']:,}" if a["followers"] else "—"
            tree.insert("", tk.END, iid=str(i), values=(a["nome"], fans))

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
            query = f"{artist} - {t['nome']}" if artist else t["nome"]
            label = f"{t['nome']}  ({artist})" if artist else t["nome"]
            self._add_to_queue(query, label)

        tree.bind("<Double-Button-1>", on_dclick)
        self._back_btn("← Nuova ricerca", self._show_search)

    # ── Schermata: Album ─────────────────────────────────────

    def _show_albums(self):
        self._clear_nav()
        self._nav_title(f"Album di {self.current_artist['nome']}")

        status = tk.Label(self.nav_frame, text="Caricamento album...",
                          fg=SUBTEXT, font=("Segoe UI", 10), bg=BG)
        status.pack()
        self.root.update()

        try:
            self.current_albums = self.searcher.get_artist_albums(self.current_artist["id"])
        except Exception as e:
            print(f"[Errore album] {e}", file=sys.stderr)
            status.config(text=f"Errore: {e}", fg=ERROR)
            return

        status.destroy()

        tk.Label(self.nav_frame,
                 text=f"{len(self.current_albums)} album trovati  —  doppio click per vedere le tracce",
                 fg=SUBTEXT, font=("Segoe UI", 9), bg=BG).pack(pady=(0, 6))

        # Riga filtro + ordinamento
        controls = tk.Frame(self.nav_frame, bg=BG)
        controls.pack(fill="x", pady=(0, 6))

        filter_var = tk.StringVar()
        filter_entry = ttk.Entry(controls, textvariable=filter_var,
                                 font=("Segoe UI", 10), width=26)
        filter_entry.pack(side="left", padx=(0, 10))
        filter_entry.insert(0, "Filtra album...")

        def on_focus_in(e):
            if filter_entry.get() == "Filtra album...":
                filter_entry.delete(0, tk.END)

        def on_focus_out(e):
            if not filter_entry.get():
                filter_entry.insert(0, "Filtra album...")

        filter_entry.bind("<FocusIn>", on_focus_in)
        filter_entry.bind("<FocusOut>", on_focus_out)

        tk.Label(controls, text="Ordina:", fg=SUBTEXT,
                 font=("Segoe UI", 9), bg=BG).pack(side="left")

        sort_var = tk.StringVar(value=self.SORT_OPTIONS[0])
        sort_cb = ttk.Combobox(controls, textvariable=sort_var,
                               values=self.SORT_OPTIONS, state="readonly",
                               width=11, font=("Segoe UI", 9))
        sort_cb.pack(side="left", padx=(4, 0))

        # Lista album
        list_frame = tk.Frame(self.nav_frame, bg=BG)
        list_frame.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")

        self.albums_lb = tk.Listbox(
            list_frame, font=("Segoe UI", 11),
            bg=PANEL, fg=TEXT, selectbackground=ACCENT, selectforeground=TEXT,
            activestyle="none", bd=0, highlightthickness=0, yscrollcommand=sb.set
        )
        self.albums_lb.pack(side="left", fill="both", expand=True)
        sb.config(command=self.albums_lb.yview)

        def sorted_albums(albums):
            mode = sort_var.get()
            if mode == "Nome A→Z":
                return sorted(albums, key=lambda a: a["nome"].lower())
            if mode == "Nome Z→A":
                return sorted(albums, key=lambda a: a["nome"].lower(), reverse=True)
            if mode == "Anno ↑":
                return sorted(albums, key=lambda a: a["anno"])
            if mode == "Anno ↓":
                return sorted(albums, key=lambda a: a["anno"], reverse=True)
            return albums

        def refresh_list(*_):
            text = filter_var.get().lower()
            if text == "filtra album...":
                text = ""
            filtered = [a for a in self.current_albums if text in a["nome"].lower()]
            self.filtered_albums = sorted_albums(filtered)
            self.albums_lb.delete(0, tk.END)
            for album in self.filtered_albums:
                self.albums_lb.insert(tk.END, f"  {album['nome']}  ({album['anno']})")

        refresh_list()
        filter_var.trace_add("write", refresh_list)
        sort_var.trace_add("write", refresh_list)

        self.albums_lb.bind("<Double-Button-1>", self._on_album_dclick)
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

        status = tk.Label(self.nav_frame, text="Caricamento tracce...",
                          fg=SUBTEXT, font=("Segoe UI", 10), bg=BG)
        status.pack(pady=4)
        self.root.update()

        try:
            self.current_tracks = self.searcher.get_album_tracks(album["id"])
        except Exception as e:
            print(f"[Errore tracce] {e}", file=sys.stderr)
            status.config(text=f"Errore: {e}", fg=ERROR)
            return

        status.destroy()

        tk.Label(self.nav_frame, text="Doppio click per aggiungere alla coda",
                 fg=SUBTEXT, font=("Segoe UI", 9), bg=BG).pack(pady=(0, 6))

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
                self._add_to_queue(self._make_query(track), self._make_label(track, album))

        tree.bind("<Double-Button-1>", on_dclick)

        btn_row = tk.Frame(self.nav_frame, bg=BG)
        btn_row.pack(pady=10)
        ttk.Button(btn_row, text="+ Aggiungi tutto l'album",
                   command=lambda: self._add_all_tracks(album),
                   style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(btn_row, text="← Torna agli album",
                   command=self._show_albums,
                   style="Ghost.TButton").pack(side="left", padx=4)
        ttk.Button(btn_row, text="Nuova ricerca",
                   command=self._show_search,
                   style="Ghost.TButton").pack(side="left", padx=4)

    # ── Gestione coda ────────────────────────────────────────

    def _make_query(self, track: dict) -> str:
        artist = track["artisti"][0] if track["artisti"] else self.current_artist["nome"]
        return f"{artist} - {track['nome']}"

    def _make_label(self, track: dict, album: dict) -> str:
        return f"{track['nome']}  ({album['nome']})"

    def _add_all_tracks(self, album: dict):
        for track in self.current_tracks:
            self._add_to_queue(self._make_query(track), self._make_label(track, album))

    def _add_to_queue(self, query: str, label: str):
        if any(item["query"] == query for item in self.download_queue):
            return
        self.download_queue.append({"query": query, "label": label})
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
        self.queue_count_var.set(f"{n} {'canzone' if n == 1 else 'canzoni'}")
        self.btn_download.config(state="normal" if n > 0 else "disabled")

    # ── Download ─────────────────────────────────────────────

    def _start_download(self):
        destination = filedialog.askdirectory(title="Seleziona cartella di destinazione")
        if not destination:
            return
        self.btn_download.config(state="disabled")
        self.progress_bar["maximum"] = 100
        self.progress_bar["value"] = 0
        self.progress_outer.pack(fill="x", padx=10, pady=4)
        threading.Thread(
            target=self._run_download,
            args=(list(self.download_queue), destination),
            daemon=True
        ).start()

    def _run_download(self, queue: list, destination: str):
        successi, falliti = 0, []

        for i, item in enumerate(queue):
            self.root.after(0, self.progress_label.config,
                            {"text": f"({i+1}/{len(queue)}) {item['label'][:34]}..."})
            self.root.after(0, self._set_progress, 0)

            def callback(percent):
                self.root.after(0, self._set_progress, percent)

            try:
                url = self.downloader.search_youtube(item["query"])
                if not url:
                    falliti.append(item["label"])
                else:
                    self.downloader.download(url, destination, progress_callback=callback)
                    successi += 1
            except Exception as e:
                falliti.append(f"{item['label']} ({str(e)[:40]})")

            self.root.after(0, self._set_progress, 100)

        self.root.after(0, self._download_done, successi, falliti, len(queue), destination)

    def _set_progress(self, value):
        self.progress_bar["value"] = value

    def _download_done(self, successi: int, falliti: list, totale: int, destination: str):
        self.progress_outer.pack_forget()
        self._clear_queue()

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


# ─────────────────────────────────────────────────────────────
# Avvio
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    MusicDownloaderApp(root)
    root.mainloop()
