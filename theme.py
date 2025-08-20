from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def apply_dark_theme(root: tk.Tk) -> None:
    bg = "#121212"
    surface = "#1e1e1e"
    text = "#ffffff"
    text_muted = "#cccccc"
    accent = "#0a84ff"
    select_bg = "#264F78"

    root.configure(bg=bg)

    # Tk option database for classic widgets (e.g., Listbox)
    root.option_add("*background", surface)
    root.option_add("*foreground", text)
    root.option_add("*Listbox.background", surface)
    root.option_add("*Listbox.foreground", text)
    root.option_add("*Listbox.selectBackground", select_bg)
    root.option_add("*Listbox.selectForeground", text)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # Base surfaces
    style.configure("TFrame", background=bg)
    style.configure("TLabelframe", background=bg)
    style.configure("TLabelframe.Label", background=bg, foreground=text)
    style.configure("TLabel", background=bg, foreground=text)
    style.configure("TCheckbutton", background=bg, foreground=text)

    # Notebook and tabs
    style.configure("TNotebook", background=bg, borderwidth=0)
    style.configure("TNotebook.Tab", background=surface, foreground=text_muted)
    style.map(
        "TNotebook.Tab",
        background=[("selected", surface)],
        foreground=[("selected", text)],
    )

    # Buttons
    style.configure("TButton", background=surface, foreground=text)
    style.map(
        "TButton",
        background=[("active", "#2a2a2a"), ("pressed", "#333333")],
        foreground=[("disabled", "#777777")],
    )

    # Entries and combos
    style.configure("TEntry", fieldbackground=surface, background=surface, foreground=text)
    style.configure("TCombobox", fieldbackground=surface, background=surface, foreground=text)
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", surface)],
    )

    # Paned window
    style.configure("TPanedwindow", background=bg)

    # Treeview
    style.configure(
        "Treeview",
        background=surface,
        fieldbackground=surface,
        foreground=text,
        bordercolor=surface,
        lightcolor=surface,
        darkcolor=surface,
        rowheight=22,
    )
    style.map(
        "Treeview",
        background=[("selected", select_bg)],
        foreground=[("selected", text)],
    )
    style.configure("Treeview.Heading", background=surface, foreground=text_muted)
    style.map(
        "Treeview.Heading",
        background=[("active", surface)],
        foreground=[("!disabled", text)],
    )
