"""Blocco di avanzamento condiviso dall'app principale e dal download da txt:
titolo, contatore, barra generale, ETA/spazio e lista canzoni."""
import time
from tkinter import ttk
from typing import List

import customtkinter as ctk

from logica.config import (ACCENT, BG, CARD, ERROR, PANEL, PREFERRED_QUALITY, SUBTEXT,
                           SUCCESS, TEXT, logger)
from logica.models import QueueItem
from logica.progress_tracker import ProgressTracker, format_bytes, format_duration
from logica.txt_download import item_file_size


class ProgressView:
    """Un solo Treeview per tutte le canzoni: migliaia di righe si creano e si
    aggiornano in un attimo (a differenza di una riga di widget ciascuna).
    I callback di yt-dlp arrivano molto spesso: on_progress memorizza e basta,
    il disegno lo fa _tick 3 volte al secondo.

    Gli on_* vanno chiamati dal thread grafico (via root.after). `compact`
    stringe colonne e font per il pannello laterale dell'app principale."""

    def __init__(self, root, parent, queue: List[QueueItem], destination: str = "",
                 *, bg: str = BG, compact: bool = False):
        self.root = root
        self.total = len(queue)
        self._destination = destination
        self._ok = 0
        self._running = False
        self._last_log = 0.0
        self._bar_cells = 5 if compact else 10

        existing = {id(i) for i in queue if item_file_size(i, destination)}
        self.tracker = ProgressTracker(queue, int(PREFERRED_QUALITY), existing)

        self.frame = ctk.CTkFrame(parent, fg_color=bg)
        big, small = (11, 9) if compact else (14, 11)
        self.title_label = ctk.CTkLabel(self.frame, text="Download in corso",
                                        font=("Segoe UI", big, "bold"), text_color=TEXT)
        self.title_label.pack()
        self.count_label = ctk.CTkLabel(self.frame, text=f"0 / {self.total}",
                                        text_color=SUBTEXT, font=("Segoe UI", small))
        self.count_label.pack()
        self.general_bar = ctk.CTkProgressBar(self.frame, progress_color=ACCENT, fg_color=CARD)
        self.general_bar.set(0)
        self.general_bar.pack(fill="x", pady=(6, 4))
        self.eta_label = ctk.CTkLabel(self.frame, text="Tempo rimanente: calcolo…",
                                      text_color=SUBTEXT, font=("Segoe UI", small))
        self.eta_label.pack()
        self.size_label = ctk.CTkLabel(self.frame, text="", text_color=SUBTEXT,
                                       font=("Segoe UI", small))
        self.size_label.pack(pady=(0, 6))
        self._build_list(queue, compact)

    def _build_list(self, queue: List[QueueItem], compact: bool):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Progress.Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=TEXT, borderwidth=0, rowheight=22, font=("Segoe UI", 10))
        style.configure("Progress.Treeview.Heading", background=CARD, foreground=SUBTEXT,
                        borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("Progress.Treeview", background=[("selected", CARD)],
                  foreground=[("selected", TEXT)])

        frame = ctk.CTkFrame(self.frame, fg_color=PANEL)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, style="Progress.Treeview", show="headings",
                                 columns=("stato", "canzone", "avanz"), selectmode="browse")
        cols = (("stato", "", 24 if compact else 30, "center"),
                ("canzone", "Canzone", 120 if compact else 330, "w"),
                ("avanz", "Avanzamento", 100 if compact else 150, "w"))
        for col, text, width, anchor in cols:
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "canzone"))
        self.tree.tag_configure("active", foreground=ACCENT)
        self.tree.tag_configure("ok", foreground=SUCCESS)
        self.tree.tag_configure("fail", foreground=ERROR)
        self.tree.tag_configure("wait", foreground=SUBTEXT)
        sb = ctk.CTkScrollbar(frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.rows = set()
        self._pct = {}        # ultimo % ricevuto per canzone
        self._dirty = set()   # canzoni da ridisegnare al prossimo giro
        for item in queue:
            iid = str(id(item))
            self.rows.add(iid)
            self.tree.insert("", "end", iid=iid, values=("○", item.label, ""), tags=("wait",))

    def start(self):
        self.tracker.start()
        self._running = True
        self._tick()

    def _text_bar(self, pct):
        n = int(pct * self._bar_cells // 100)
        return f"{'▓' * n}{'░' * (self._bar_cells - n)} {int(pct):3d}%"

    # ── Eventi dal download ──────────────────────────────────

    def on_started(self, iid):
        iid = str(iid)
        if iid in self.rows:
            self.tree.item(iid, tags=("active",))
            self.tree.set(iid, "stato", "▶")
            self.tree.set(iid, "avanz", self._text_bar(0))
            self.tree.see(iid)

    def on_progress(self, iid, pct):
        iid = str(iid)
        if iid in self.rows:
            self._pct[iid] = pct
            self._dirty.add(iid)
            self.tracker.update(int(iid), pct)

    def on_completed(self, iid, item: QueueItem, ok: bool):
        self._ok += ok
        self.tracker.complete(int(iid), item, item_file_size(item, self._destination) if ok else 0)
        iid = str(iid)
        self._dirty.discard(iid)
        if iid in self.rows:
            self.tree.item(iid, tags=("ok" if ok else "fail",))
            self.tree.set(iid, "stato", "✓" if ok else "✗")
            self.tree.set(iid, "avanz", "completata" if ok else (item.result_status or "fallita"))
        self.count_label.configure(text=f"{self.tracker.finished} / {self.total}")
        self._refresh_stats()

    def stop(self):
        """Ferma il ridisegno periodico (da chiamare prima di distruggere la UI)."""
        self._running = False

    def finish(self, cancelled: bool):
        self.stop()
        self.eta_label.configure(text="")
        self.title_label.configure(
            text=f"{'Annullato' if cancelled else 'Completato'}: {self._ok}/{self.total}",
            text_color=SUCCESS if self._ok == self.total else ERROR)

    # ── Ridisegno periodico ──────────────────────────────────

    def _tick(self):
        """Ridisegna le barre cambiate e aggiorna ETA/spazio, 3 volte al secondo."""
        if not self._running:
            return
        for iid in self._dirty:
            self.tree.set(iid, "avanz", self._text_bar(self._pct[iid]))
        self._dirty.clear()
        self._refresh_stats()
        self._log_progress()
        self.root.after(300, self._tick)

    def _log_progress(self, every: float = 30.0):
        """Riga nel log ogni 30s: serve a confrontare l'ETA mostrata con la durata reale."""
        now = time.monotonic()
        if now - self._last_log < every:
            return
        self._last_log = now
        t = self.tracker
        remaining = t.remaining_seconds()
        logger.info(f"[Progress] {t.finished}/{t.total} concluse | ETA "
                    f"{'n/d' if remaining is None else format_duration(remaining)} | "
                    f"{format_bytes(t.downloaded_bytes)} / ~{format_bytes(t.estimated_bytes)} stimati")

    def _refresh_stats(self):
        t = self.tracker
        remaining = t.remaining_seconds()
        self.eta_label.configure(text="Tempo rimanente: " + (
            "calcolo…" if remaining is None else f"~{format_duration(remaining)}"))
        self.general_bar.set(t.bar_fraction)
        self.size_label.configure(
            text=f"Scaricato: {format_bytes(t.downloaded_bytes)}  /  "
                 f"~{format_bytes(t.estimated_bytes)} stimati")
