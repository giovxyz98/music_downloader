"""Mini-UI per il download da txt: scegli txt + cartella, vedi l'anteprima
ad albero e il numero di canzoni, conferma, segui l'avanzamento."""
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

import customtkinter as ctk

from logica.config import (ACCENT, ACCENT2, BG, CARD, ERROR, PANEL, PREFERRED_QUALITY,
                           SUBTEXT, SUCCESS, TEXT, logger)
from logica.progress_tracker import (ProgressTracker, estimate_total_bytes, format_bytes,
                                     format_duration)
from logica.txt_download import item_file_size, make_manager, run_plans
from logica.txt_importer import ArtistPlan, build_plan, count_tracks, format_tree, parse_txt


class TxtDownloaderApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        root.title("Download da txt")
        root.geometry("640x680")
        root.configure(fg_color=BG)

        self.txt_path: Optional[Path] = None
        self.destination: Optional[Path] = None
        self.plans: List[ArtistPlan] = []
        self.manager = make_manager()

        self._build_picker()

    def _clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    # ── Schermata 1: scelta file + anteprima ─────────────────

    def _build_picker(self):
        self._clear()
        body = ctk.CTkFrame(self.root, fg_color=BG)
        body.pack(fill="both", expand=True, padx=16, pady=16)

        self.txt_label  = self._picker_row(body, "File txt", self._choose_txt)
        self.dest_label = self._picker_row(body, "Cartella di destinazione", self._choose_dest)

        self.summary = ctk.CTkLabel(body, text="", font=("Segoe UI", 12, "bold"),
                                    text_color=TEXT, anchor="w")
        self.summary.pack(fill="x", pady=(14, 4))

        self.preview = ctk.CTkTextbox(body, font=("Consolas", 11), fg_color=PANEL,
                                      text_color=TEXT, wrap="none")
        self.preview.pack(fill="both", expand=True)
        self.preview.configure(state="disabled")

        self.btn_confirm = ctk.CTkButton(
            body, text="Conferma e scarica", command=self._confirm, state="disabled",
            fg_color=ACCENT, hover_color=ACCENT2, text_color=TEXT,
            font=("Segoe UI", 12, "bold"), height=40)
        self.btn_confirm.pack(fill="x", pady=(12, 0))

    def _picker_row(self, parent, text, command) -> ctk.CTkLabel:
        row = ctk.CTkFrame(parent, fg_color=BG)
        row.pack(fill="x", pady=3)
        ctk.CTkButton(row, text=text, command=command, width=200,
                      fg_color=CARD, hover_color=ACCENT2, text_color=TEXT).pack(side="left")
        label = ctk.CTkLabel(row, text="—", text_color=SUBTEXT, anchor="w")
        label.pack(side="left", fill="x", expand=True, padx=10)
        return label

    def _choose_txt(self):
        path = filedialog.askopenfilename(title="Seleziona il file txt",
                                          filetypes=[("Testo", "*.txt"), ("Tutti", "*.*")])
        if path:
            self.txt_path = Path(path)
            self.txt_label.configure(text=self.txt_path.name, text_color=TEXT)
            self._refresh_preview()

    def _choose_dest(self):
        path = filedialog.askdirectory(title="Seleziona cartella di destinazione")
        if path:
            self.destination = Path(path)
            self.dest_label.configure(text=str(self.destination), text_color=TEXT)
            self._refresh_preview()

    def _refresh_preview(self):
        self.plans = []
        text, summary = "", ""
        if self.txt_path and self.destination:
            try:
                orphans: List[str] = []
                self.plans = [build_plan(r, self.destination)
                              for r in parse_txt(self.txt_path, orphans)]
                n_ign = len(orphans) + sum(len(p.ignored) for p in self.plans)
            except Exception as e:
                summary = f"Impossibile leggere il file: {e}"
            else:
                n = count_tracks(self.plans)
                if n:
                    size = estimate_total_bytes([i for p in self.plans for i in p.queue],
                                                int(PREFERRED_QUALITY))
                    summary = (f"Saranno scaricate {n} {'canzone' if n == 1 else 'canzoni'}"
                               f"  —  spazio stimato ~{format_bytes(size)}")
                    if n_ign:
                        summary += f"  —  ATTENZIONE: {n_ign} righe del txt ignorate (vedi log)"
                    text = format_tree(self.plans, self.destination)
                else:
                    summary = "Nessuna canzone trovata nel file"
        elif self.txt_path or self.destination:
            summary = "Scegli anche " + ("la cartella" if self.txt_path else "il file txt")

        self.summary.configure(text=summary)
        self.preview.configure(state="normal")
        self.preview.delete("1.0", tk.END)
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")
        self.btn_confirm.configure(state="normal" if count_tracks(self.plans) else "disabled")

    # ── Schermata 2: avanzamento ─────────────────────────────

    def _confirm(self):
        plans = self.plans
        queue = [item for p in plans for item in p.queue]
        self._build_progress(queue)
        self._ok = 0
        self.tracker = ProgressTracker(queue, int(PREFERRED_QUALITY))
        self.tracker.start()
        self._running = True
        self._last_log = 0.0
        self._tick()
        threading.Thread(target=self._worker, args=(plans, len(queue)), daemon=True).start()

    def _build_progress(self, queue):
        self._clear()
        total = len(queue)
        body = ctk.CTkFrame(self.root, fg_color=BG)
        body.pack(fill="both", expand=True, padx=16, pady=16)

        self.title_label = ctk.CTkLabel(body, text="Download in corso",
                                        font=("Segoe UI", 14, "bold"), text_color=TEXT)
        self.title_label.pack()
        self.count_label = ctk.CTkLabel(body, text=f"0 / {total}", text_color=SUBTEXT)
        self.count_label.pack()
        self.general_bar = ctk.CTkProgressBar(body, progress_color=ACCENT, fg_color=CARD)
        self.general_bar.set(0)
        self.general_bar.pack(fill="x", pady=(6, 4))
        self.eta_label = ctk.CTkLabel(body, text="Tempo rimanente: calcolo…",
                                      text_color=SUBTEXT, font=("Segoe UI", 11))
        self.eta_label.pack()
        self.size_label = ctk.CTkLabel(body, text="", text_color=SUBTEXT, font=("Segoe UI", 11))
        self.size_label.pack(pady=(0, 6))

        self._build_list(body, queue)

        self.btn_bottom = ctk.CTkButton(
            body, text="Annulla download", command=self.manager.cancel_event.set,
            fg_color=PANEL, hover_color=CARD, text_color=SUBTEXT)
        self.btn_bottom.pack(fill="x", pady=(10, 0))

    def _worker(self, plans, total):
        after = self.root.after
        failed = run_plans(
            self.manager, plans,
            on_track_started=lambda item, iid: after(0, self._on_started, iid),
            on_progress=lambda iid, pct: after(0, self._on_progress, iid, pct),
            on_track_completed=lambda item, iid, ok, c, t: after(0, self._on_completed, iid, item, ok, total),
        )
        after(0, self._on_finished, failed, total)

    def _build_list(self, body, queue):
        """Un solo Treeview per tutte le canzoni: migliaia di righe si creano
        e si aggiornano in un attimo (a differenza di una riga di widget ciascuna)."""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Txt.Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=TEXT, borderwidth=0, rowheight=22, font=("Segoe UI", 10))
        style.configure("Txt.Treeview.Heading", background=CARD, foreground=SUBTEXT,
                        borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("Txt.Treeview", background=[("selected", CARD)],
                  foreground=[("selected", TEXT)])

        frame = ctk.CTkFrame(body, fg_color=PANEL)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, style="Txt.Treeview", show="headings",
                                 columns=("stato", "canzone", "avanz"), selectmode="browse")
        for col, text, width, anchor in (("stato", "", 30, "center"),
                                         ("canzone", "Canzone", 330, "w"),
                                         ("avanz", "Avanzamento", 150, "w")):
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

    @staticmethod
    def _text_bar(pct):
        n = int(pct // 10)
        return f"{'▓' * n}{'░' * (10 - n)} {int(pct):3d}%"

    def _on_started(self, iid):
        iid = str(iid)
        if iid in self.rows:
            self.tree.item(iid, tags=("active",))
            self.tree.set(iid, "stato", "▶")
            self.tree.set(iid, "avanz", self._text_bar(0))
            self.tree.see(iid)

    def _on_progress(self, iid, pct):
        # yt-dlp chiama molto spesso: qui si memorizza e basta, il disegno lo fa _tick
        iid = str(iid)
        if iid in self.rows:
            self._pct[iid] = pct
            self._dirty.add(iid)
            self.tracker.update(int(iid), pct)

    def _on_completed(self, iid, item, ok, total):
        self._ok += ok
        self.tracker.complete(int(iid), item, item_file_size(item) if ok else 0)
        iid = str(iid)
        self._dirty.discard(iid)
        self.tree.item(iid, tags=("ok" if ok else "fail",))
        self.tree.set(iid, "stato", "✓" if ok else "✗")
        self.tree.set(iid, "avanz", "completata" if ok else (item.result_status or "fallita"))
        self.count_label.configure(text=f"{self.tracker.finished} / {total}")
        self._refresh_stats()

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

    def _on_finished(self, failed, total):
        self._running = False
        self.eta_label.configure(text="")
        cancelled = self.manager.cancel_event.is_set()
        self.title_label.configure(
            text=f"{'Annullato' if cancelled else 'Completato'}: {self._ok}/{total}",
            text_color=SUCCESS if self._ok == total else ERROR)
        if failed:
            messagebox.showinfo("Download completato", f"Falliti: {len(failed)}\n" +
                                "\n".join(f"  - {f}" for f in failed[:15]))
        self.btn_bottom.configure(text="Apri cartella e nuova lista", command=self._finish)

    def _finish(self):
        try:
            os.startfile(self.destination)
        except Exception:
            pass
        self.txt_path = self.destination = None
        self.plans = []
        self._build_picker()


def run():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    TxtDownloaderApp(root)
    root.mainloop()
