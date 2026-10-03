"""Mini-UI per il download da txt: scegli txt + cartella, vedi l'anteprima
ad albero e il numero di canzoni, conferma, segui l'avanzamento."""
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Optional

import customtkinter as ctk

from logica.config import ACCENT, ACCENT2, BG, CARD, ERROR, PANEL, SUBTEXT, SUCCESS, TEXT
from logica.txt_download import make_manager, run_plans
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
                    summary = f"Saranno scaricate {n} {'canzone' if n == 1 else 'canzoni'}"
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
        self._done = 0
        self._ok = 0
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
        self.general_bar.pack(fill="x", pady=(6, 8))

        scroll = ctk.CTkScrollableFrame(body, fg_color=PANEL)
        scroll.pack(fill="both", expand=True)
        self.rows = {}
        for item in queue:
            row = ctk.CTkFrame(scroll, fg_color=PANEL)
            row.pack(fill="x", pady=1)
            status = tk.StringVar(value="○")
            tk.Label(row, textvariable=status, bg=PANEL, fg=SUBTEXT, width=2).pack(side="left")
            ctk.CTkLabel(row, text=item.label, text_color=TEXT, anchor="w",
                         font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, padx=4)
            bar = ctk.CTkProgressBar(row, progress_color=ACCENT, fg_color=CARD, width=120, height=6)
            bar.set(0)
            bar.pack(side="right", padx=4)
            self.rows[id(item)] = (bar, status)

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
            on_track_completed=lambda item, iid, ok, c, t: after(0, self._on_completed, iid, ok, total),
        )
        after(0, self._on_finished, failed, total)

    def _on_started(self, iid):
        if iid in self.rows:
            self.rows[iid][1].set("▶")

    def _on_progress(self, iid, pct):
        if iid in self.rows:
            self.rows[iid][0].set(pct / 100)

    def _on_completed(self, iid, ok, total):
        self._done += 1
        self._ok += ok
        bar, status = self.rows[iid]
        bar.set(1.0 if ok else 0.0)
        status.set("✓" if ok else "✗")
        self.count_label.configure(text=f"{self._done} / {total}")
        self.general_bar.set(self._done / total)

    def _on_finished(self, failed, total):
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
