import tkinter as tk
from tkinter import ttk

from infra.config import BG, PANEL, TEXT, ACCENT, SUBTEXT


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
