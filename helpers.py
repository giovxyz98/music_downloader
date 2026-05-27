import re
import tkinter as tk
from tkinter import ttk

from config import BG, PANEL, TEXT, ACCENT, SUBTEXT, FILENAME_MAX_LENGTH


def sanitize_filename(name: str, max_length: int = FILENAME_MAX_LENGTH) -> str:
    return re.sub(r'[<>:"/\\|?*\n\r\t]', '_', name).strip()[:max_length]


def scrolled_tree(parent, columns, headings, col_widths):
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
