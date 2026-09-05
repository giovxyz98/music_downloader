import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk
from typing import List, Optional

import customtkinter as ctk
import requests
import yt_dlp

from config import (
    logger,
    BG, PANEL, CARD, ACCENT, ACCENT2, TEXT, SUBTEXT, ERROR, BORDER,
    HISTORY_MENU_MAX, RECENT_SEARCHES_SHOWN,
)
from cache import CacheManager
from download_manager import DownloadManager
from models import Artist, Album, Track, QueueItem
from queue_manager import QueueManager
from search_controller import SearchController
from helpers import scrolled_tree, sanitize_filename


class MusicDownloaderApp:

    SORT_OPTIONS = ["Nome A→Z", "Nome Z→A", "Anno ↑", "Anno ↓"]

    def __init__(self, root: ctk.CTk, search_controller: SearchController,
                 queue_manager: QueueManager, download_manager: DownloadManager,
                 cache: CacheManager):
        self.root = root
        self.root.title("Music Downloader")
        self.root.geometry("1020x660")
        self.root.resizable(True, True)
        self.root.configure(fg_color=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._setup_style()

        self.search_controller = search_controller
        self.queue_manager     = queue_manager
        self.download_manager  = download_manager
        self.cache              = cache

        # ThreadPoolExecutor per operazioni UI/Deezer: max 2 thread concorrenti
        self._ui_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ui")

        self.current_artist:   Optional[Artist] = None
        self.current_albums:   List[Album] = []
        self.filtered_albums:  List[Album] = []
        self.current_tracks:   List[Track] = []

        self._dl_general_bar:   Optional[ctk.CTkProgressBar] = None
        self._dl_general_label: Optional[ctk.CTkLabel]       = None
        self._dl_total:         int                           = 0
        self._track_widgets:    dict                          = {}

        self._setup_menubar()
        self._build_layout()
        self._show_search()

        logger.info(
            f"[App] Avvio — yt-dlp={yt_dlp.version.__version__}, "
            f"requests={requests.__version__}"
        )

    def _on_close(self):
        self._ui_executor.shutdown(wait=False)
        self.root.destroy()

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

    def _show_download_panel(self, queue: List[QueueItem]):
        total = len(queue)
        self._dl_total = total
        for w in self.queue_panel.winfo_children():
            w.destroy()

        ctk.CTkLabel(self.queue_panel, text="Download in corso",
                     font=("Segoe UI", 11, "bold"),
                     fg_color="transparent", text_color=TEXT).pack(pady=(12, 2))

        self._dl_general_label = ctk.CTkLabel(
            self.queue_panel, text=f"0 / {total}",
            font=("Segoe UI", 8), fg_color="transparent", text_color=SUBTEXT
        )
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

            short = item.label[:24] + "…" if len(item.label) > 24 else item.label
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
            bottom, orientation="horizontal", progress_color=ACCENT, fg_color=CARD
        )
        self._dl_general_bar.set(0)
        self._dl_general_bar.pack(fill="x", pady=2)

        ctk.CTkButton(self.queue_panel, text="Annulla download",
                      command=self.download_manager.cancel_event.set,
                      fg_color=PANEL, hover_color=CARD, text_color=SUBTEXT,
                      font=("Segoe UI", 9), corner_radius=6).pack(fill="x", padx=8, pady=(2, 8))

    def _track_started(self, item: QueueItem, item_id: int):
        w = self._track_widgets.get(item_id)
        if w:
            w[1].set("▶")

    def _update_track_progress(self, item_id: int, percent: float):
        w = self._track_widgets.get(item_id)
        if w:
            w[0].set(percent / 100)

    def _track_completed(self, item: QueueItem, item_id: int, ok: bool,
                         completed: int, total: int):
        w = self._track_widgets.get(item_id)
        if w:
            w[0].set(1.0 if ok else 0.0)
            w[1].set("✓" if ok else "✗")
        if self._dl_general_label is not None:
            self._dl_general_label.configure(text=f"{completed} / {total}")
        if self._dl_general_bar is not None and total > 0:
            self._dl_general_bar.set(completed / total)

    def _restore_queue_panel(self):
        for w in self.queue_panel.winfo_children():
            w.destroy()
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
                artists = self.search_controller.search_artist(query)
            except Exception as e:
                self.root.after(0, lambda: self.search_status.configure(
                    text=f"Errore: {e}", text_color=ERROR))
                return
            if not artists:
                self.root.after(0, lambda: self.search_status.configure(
                    text="Nessun artista trovato.", text_color=ERROR))
                return
            if len(artists) == 1:
                self.current_artist = artists[0]
                self.root.after(0, self._show_albums)
            else:
                self.root.after(0, self._show_artist_selection, artists)
        self._ui_executor.submit(_work)

    def _do_track_search(self, query: str):
        def _work():
            try:
                tracks = self.search_controller.search_track(query)
            except Exception as e:
                self.root.after(0, lambda: self.search_status.configure(
                    text=f"Errore: {e}", text_color=ERROR))
                return
            if not tracks:
                self.root.after(0, lambda: self.search_status.configure(
                    text="Nessuna canzone trovata.", text_color=ERROR))
                return
            self.root.after(0, self._show_track_results, tracks)
        self._ui_executor.submit(_work)

    # ── Schermata: Selezione artista ─────────────────────────

    def _show_artist_selection(self, artists: List[Artist]):
        self._clear_nav()
        self._nav_title("Seleziona artista", "Doppio click per selezionare")
        artists = sorted(artists, key=lambda a: a.nome.lower())

        f, tree = scrolled_tree(self.nav_frame,
                                columns=("nome", "album", "follower"),
                                headings=("Artista", "Album", "Follower"),
                                col_widths=(280, 80, 140))
        tree.column("album",    anchor="center", stretch=False)
        tree.column("follower", anchor="e",      stretch=False)
        f.pack(fill="both", expand=True)

        for i, a in enumerate(artists):
            follower = f"{a.followers:,}" if a.followers else "—"
            nb_album = str(a.nb_album) if a.nb_album else "—"
            tree.insert("", tk.END, iid=str(i), values=(a.nome, nb_album, follower))

        def on_dclick(event):
            item = tree.identify_row(event.y)
            if item:
                self.current_artist = artists[int(item)]
                self._show_albums()

        tree.bind("<Double-Button-1>", on_dclick)
        self._back_btn("← Nuova ricerca", self._show_search)

    # ── Schermata: Risultati ricerca canzone ─────────────────

    def _show_track_results(self, tracks: List[Track]):
        self._clear_nav()
        self._nav_title("Risultati ricerca",
                        f"{len(tracks)} canzoni trovate  —  doppio click per aggiungere alla coda")

        f, tree = scrolled_tree(self.nav_frame,
                                columns=("titolo", "artista"),
                                headings=("Titolo", "Artista"),
                                col_widths=(340, 220))
        f.pack(fill="both", expand=True)

        for i, t in enumerate(tracks):
            artist = t.artisti[0] if t.artisti else "—"
            tree.insert("", tk.END, iid=str(i), values=(t.nome, artist))

        def on_dclick(event):
            item = tree.identify_row(event.y)
            if not item:
                return
            t = tracks[int(item)]
            artist = t.artisti[0] if t.artisti else ""
            query  = f"{artist} - {t.nome}" if artist else t.nome
            label  = f"{t.nome}  ({artist})" if artist else t.nome
            meta = {
                "title":       t.nome,
                "artist":      artist,
                "albumartist": artist,
                "album":       t.album,
                "year":        "",
                "tracknumber": "",
                "album_id":    str(t.album_id) if t.album_id else "",
                "duration":    t.duration,
            }
            self._add_to_queue(query, label, meta)

        tree.bind("<Double-Button-1>", on_dclick)

        def show_track_menu(event):
            item = tree.identify_row(event.y)
            if not item:
                return
            tree.selection_set(item)
            t = tracks[int(item)]
            artist_name = t.artisti[0] if t.artisti else ""
            menu = tk.Menu(self.root, tearoff=0, bg=CARD, fg=TEXT,
                           activebackground=ACCENT, activeforeground=TEXT, borderwidth=0)
            if t.artist_id and artist_name:
                menu.add_command(
                    label="Vai all'artista",
                    command=lambda: self._goto_artist(t.artist_id, artist_name))
            if t.album_id and t.album and t.artist_id:
                menu.add_command(
                    label="Vai all'album",
                    command=lambda: self._goto_album(
                        t.artist_id, artist_name, t.album_id, t.album))
            if menu.index("end") is not None:
                menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", show_track_menu)
        self._back_btn("← Nuova ricerca", self._show_search)

    # ── Schermata: Album ─────────────────────────────────────

    def _build_filter_sort_controls(self, parent) -> tuple:
        controls = ctk.CTkFrame(parent, fg_color=BG)
        controls.pack(fill="x", pady=(0, 6))

        filter_var = tk.StringVar()
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
            artist_name = album.artisti[0] if album.artisti else ""

            menu = tk.Menu(self.root, tearoff=0, bg=CARD, fg=TEXT,
                           activebackground=ACCENT, activeforeground=TEXT, borderwidth=0)
            if len(selected_albums) == 1:
                if album.artist_id and artist_name:
                    menu.add_command(
                        label="Vai all'artista",
                        command=lambda: self._goto_artist(album.artist_id, artist_name))
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
        self._nav_title(f"Album di {self.current_artist.nome}")

        status = ctk.CTkLabel(self.nav_frame, text="Caricamento album...",
                              fg_color="transparent",
                              text_color=SUBTEXT, font=("Segoe UI", 10))
        status.pack()

        def _fetch():
            try:
                albums = self.search_controller.get_artist_albums(self.current_artist.id)
            except Exception as e:
                self.root.after(0, lambda: status.configure(
                    text=f"Errore: {e}", text_color=ERROR))
                return
            self.root.after(0, lambda: self._finish_show_albums(albums, status))

        self._ui_executor.submit(_fetch)

    def _finish_show_albums(self, albums: List[Album], status_label):
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

        def sorted_albums(al: List[Album]) -> List[Album]:
            def year_key(a: Album):
                try:    return int(a.anno)
                except: return 0
            mode = sort_var.get()
            if mode == "Nome A→Z": return sorted(al, key=lambda a: a.nome.lower())
            if mode == "Nome Z→A": return sorted(al, key=lambda a: a.nome.lower(), reverse=True)
            if mode == "Anno ↑":   return sorted(al, key=year_key)
            if mode == "Anno ↓":   return sorted(al, key=year_key, reverse=True)
            return al

        def refresh_list(*_):
            text = filter_var.get().lower()
            if text == "filtra album...":
                text = ""
            self.filtered_albums = sorted_albums(
                [a for a in self.current_albums if text in a.nome.lower()])
            self.albums_lb.delete(0, tk.END)
            for album in self.filtered_albums:
                self.albums_lb.insert(tk.END, f"  {album.nome}  ({album.anno})")

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

    def _show_tracks(self, album: Album):
        self._clear_nav()
        self._nav_title(album.nome, f"{self.current_artist.nome}  •  {album.anno}")

        status = ctk.CTkLabel(self.nav_frame, text="Caricamento tracce...",
                              fg_color="transparent",
                              text_color=SUBTEXT, font=("Segoe UI", 10))
        status.pack(pady=4)

        def _fetch():
            try:
                tracks = self.search_controller.get_album_tracks(album.id)
            except Exception as e:
                self.root.after(0, lambda: status.configure(
                    text=f"Errore: {e}", text_color=ERROR))
                return
            self.root.after(0, lambda: self._finish_show_tracks(tracks, album, status))

        self._ui_executor.submit(_fetch)

    def _finish_show_tracks(self, tracks: List[Track], album: Album, status_label):
        status_label.destroy()
        self.current_tracks = tracks

        ctk.CTkLabel(self.nav_frame, text="Doppio click per aggiungere alla coda",
                     fg_color="transparent",
                     text_color=SUBTEXT, font=("Segoe UI", 9)).pack(pady=(0, 6))

        f, tree = scrolled_tree(self.nav_frame,
                                columns=("num", "titolo", "artista"),
                                headings=("#", "Titolo", "Artista"),
                                col_widths=(46, 320, 200))
        tree.column("num", anchor="center", stretch=False)
        f.pack(fill="both", expand=True)

        for i, track in enumerate(self.current_tracks):
            tree.insert("", tk.END, iid=str(i),
                        values=(f"{track.numero:02d}", track.nome, ", ".join(track.artisti)))

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
                    self.current_artist.id, self.current_artist.nome))
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

    def _make_query(self, track: Track) -> str:
        artist = track.artisti[0] if track.artisti else self.current_artist.nome
        return f"{artist} - {track.nome}"

    def _make_label(self, track: Track, album: Album) -> str:
        return f"{track.nome}  ({album.nome})"

    def _make_meta(self, track: Track, album: Album) -> dict:
        artist = ", ".join(track.artisti) if track.artisti else self.current_artist.nome
        return {
            "title":       track.nome,
            "artist":      artist,
            "albumartist": self.current_artist.nome if self.current_artist else artist,
            "album":       album.nome,
            "year":        album.anno,
            "tracknumber": str(track.numero) if track.numero else "",
            "album_id":    str(album.id),
            "duration":    track.duration,
        }

    def _add_all_tracks(self, album: Album):
        for track in self.current_tracks:
            self._add_to_queue(
                self._make_query(track),
                self._make_label(track, album),
                self._make_meta(track, album),
            )

    def _add_to_queue(self, query: str, label: str, meta: dict = None):
        item = self.queue_manager.add(query, label, meta)
        if item is None:
            return
        self.queue_listbox.insert(tk.END, f"  {item.label}")
        self._refresh_queue_ui()

    def _remove_on_dclick(self, event):
        idx = self.queue_listbox.nearest(event.y)
        if idx >= 0:
            self.queue_listbox.delete(idx)
            self.queue_manager.remove_at(idx)
            self._refresh_queue_ui()

    def _remove_from_queue(self):
        indices = list(self.queue_listbox.curselection())
        for idx in reversed(indices):
            self.queue_listbox.delete(idx)
        self.queue_manager.remove_indices(indices)
        self._refresh_queue_ui()

    def _clear_queue(self):
        self.queue_listbox.delete(0, tk.END)
        self.queue_manager.clear()
        self._refresh_queue_ui()

    def _refresh_queue_ui(self):
        n = len(self.queue_manager)
        self.queue_count_label.configure(text=f"{n} {'canzone' if n == 1 else 'canzoni'}")
        self.btn_download.configure(state="normal" if n > 0 else "disabled")

    # ── Download ─────────────────────────────────────────────

    def _start_download(self):
        destination = filedialog.askdirectory(title="Seleziona cartella di destinazione")
        if not destination:
            return
        queue = self.queue_manager.items
        self.download_manager.cancel_event.clear()
        self.btn_download.configure(state="disabled")
        self._show_download_panel(queue)
        threading.Thread(
            target=self._run_download,
            args=(queue, destination),
            kwargs={"clear_queue": True},
            daemon=True,
        ).start()

    def _run_download(self, queue: List[QueueItem], destination: str,
                      genre_info: tuple = None, artist_name: str = None,
                      clear_queue: bool = False):
        """Thin wrapper UI: delega la pipeline a DownloadManager e marshalizza
        i suoi hook di avanzamento sul thread principale via root.after."""
        self.download_manager.run_batch(
            queue, destination,
            genre_info=genre_info, artist_name=artist_name,
            on_track_started=lambda item, item_id:
                self.root.after(0, self._track_started, item, item_id),
            on_progress=lambda item_id, percent:
                self.root.after(0, self._update_track_progress, item_id, percent),
            on_track_completed=lambda item, item_id, ok, c, total:
                self.root.after(0, self._track_completed, item, item_id, ok, c, total),
            on_batch_done=lambda successi, falliti, q, dest, an:
                self.root.after(0, self._download_all_done, successi, falliti, q, dest, an, clear_queue),
        )

    def _download_all_done(self, successi: int, falliti: list, queue: List[QueueItem],
                           destination: str, artist_name: str, clear_queue: bool):
        self._restore_queue_panel()
        totale = len(queue)
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
                import subprocess; subprocess.run(["open", str(path)])
            else:
                import subprocess; subprocess.run(["xdg-open", str(path)])
        except Exception:
            pass

    # ── Navigazione contestuale ──────────────────────────────

    def _goto_artist(self, artist_id: int, artist_name: str):
        self.current_artist = Artist(id=artist_id, nome=artist_name)
        self._show_albums()

    def _goto_album(self, artist_id: int, artist_name: str,
                    album_id: int, album_name: str):
        self.current_artist = Artist(id=artist_id, nome=artist_name)
        try:
            details = self.search_controller.get_album_details(album_id)
            anno = details.get("anno", "")
            self.download_manager.prime_genre_cache(
                str(album_id), details.get("genre", ""), details.get("nb_tracks", 0))
        except Exception:
            anno = ""
        self._show_tracks(Album(id=album_id, nome=album_name, anno=anno))

    # ── Download diretto album ───────────────────────────────

    def _download_albums_batch(self, albums: List[Album]):
        destination = filedialog.askdirectory(title="Seleziona cartella di destinazione")
        if not destination:
            return

        queue: List[QueueItem] = []
        for album in albums:
            try:
                tracks = self.search_controller.get_album_tracks(album.id)
            except Exception as e:
                messagebox.showerror("Errore", f"Impossibile caricare '{album.nome}': {e}")
                return
            album_folder = str(Path(destination) / sanitize_filename(album.nome))
            Path(album_folder).mkdir(parents=True, exist_ok=True)
            for track in tracks:
                queue.append(QueueItem(
                    query=self._make_query(track),
                    label=track.nome,
                    meta=self._make_meta(track, album),
                    destination=album_folder,
                ))

        if not queue:
            return

        artist_name = self.current_artist.nome if self.current_artist else ""
        self.download_manager.cancel_event.clear()
        self._show_download_panel(queue)
        threading.Thread(
            target=self._run_download,
            args=(queue, destination),
            kwargs={"artist_name": artist_name, "clear_queue": False},
            daemon=True,
        ).start()

    def _download_album_direct(self, album: Album):
        destination = filedialog.askdirectory(title="Seleziona cartella di destinazione")
        if not destination:
            return
        try:
            tracks = self.search_controller.get_album_tracks(album.id)
        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile caricare le tracce: {e}")
            return

        album_folder = Path(destination) / sanitize_filename(album.nome)
        album_folder.mkdir(parents=True, exist_ok=True)

        queue = [
            QueueItem(
                query=self._make_query(track),
                label=track.nome,
                meta=self._make_meta(track, album),
            )
            for track in tracks
        ]

        artist_name = self.current_artist.nome if self.current_artist else ""
        genre_info  = self.download_manager.get_genre(str(album.id))

        self.download_manager.cancel_event.clear()
        self._show_download_panel(queue)
        threading.Thread(
            target=self._run_download,
            args=(queue, str(album_folder)),
            kwargs={"genre_info": genre_info, "artist_name": artist_name, "clear_queue": False},
            daemon=True,
        ).start()
