import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from datetime import datetime
from typing import Dict, List, Optional

import os
import time
import pandas as pd

import storage
from models import Portfolio
from journal_builder import journal_csv_path, rebuild_journal_in_background


def build_journal_ui(parent: tk.Widget) -> None:
    portfolio = storage.load_portfolio()

    # Status row (shows when journal is building/loading)
    status_row = ttk.Frame(parent)
    status_row.pack(fill="x", padx=8, pady=(6, 0))
    status_var = tk.StringVar(value="")
    status_label = ttk.Label(status_row, textvariable=status_var)
    status_label.pack(side="left")
    status_bar = ttk.Progressbar(status_row, mode="indeterminate", length=120)
    # status_bar is started/stopped dynamically; keep it packed when active only

    def show_status(text: str, spinning: bool = False) -> None:
        status_var.set(text)
        # Update tab label suffix if handler is attached
        try:
            setter = getattr(parent, "_journal_set_tab_suffix", None)
            if callable(setter):
                suffix = ""
                if spinning and text:
                    suffix = " (" + text.replace("...", "").strip() + "...)"
                elif text:
                    suffix = " (" + text + ")"
                setter(suffix)
        except Exception:
            pass
        if spinning:
            try:
                status_bar.pack(side="left", padx=(8, 0))
                status_bar.start(50)
            except Exception:
                pass
        else:
            try:
                status_bar.stop()
                status_bar.pack_forget()
            except Exception:
                pass

    # Fonts
    default_font = tkfont.nametofont("TkDefaultFont")
    highlight_font = tkfont.Font(family=default_font.cget("family"), size=default_font.cget("size"), weight="bold", underline=1)

    # Treeview-based table (more efficient than per-cell Labels)
    container = ttk.Frame(parent)
    container.pack(fill="both", expand=True)

    tree = ttk.Treeview(container, show="headings")
    yscroll_tree = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
    xscroll_tree = ttk.Scrollbar(container, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=yscroll_tree.set, xscrollcommand=xscroll_tree.set)

    # Use grid to ensure scrollbars are always visible and properly laid out
    container.grid_rowconfigure(0, weight=1)
    container.grid_columnconfigure(0, weight=1)
    tree.grid(row=0, column=0, sticky="nsew")
    yscroll_tree.grid(row=0, column=1, sticky="ns")
    xscroll_tree.grid(row=1, column=0, sticky="ew")

    journal_path = journal_csv_path()
    last_mtime = os.path.getmtime(journal_path) if os.path.exists(journal_path) else 0.0
    last_refresh = 0.0
    render_seq = 0
    journal_active = False

    def on_configure(_evt=None):  # noqa: ANN001
        pass

    def read_journal() -> pd.DataFrame:
        if not os.path.exists(journal_path):
            return pd.DataFrame()
        try:
            df = pd.read_csv(journal_path)
            if df.empty or df.shape[1] <= 1:
                return pd.DataFrame()
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df.set_index("date", inplace=True)
            return df
        except Exception:
            return pd.DataFrame()

    def refresh_grid() -> None:
        nonlocal highlight_font, last_refresh, render_seq
        now = time.time()
        if now - last_refresh < 1.0:
            return
        last_refresh = now
        # Clear tree
        for iid in tree.get_children():
            tree.delete(iid)
        df = read_journal()
        if df is None or df.empty:
            show_status("Building journal...", spinning=True)
            # Keep table empty and kick off build
            # Kick off build if missing
            rebuild_journal_in_background()
            return
        show_status("Rendering journal...", spinning=True)
        # Drop all-empty columns (symbols with no values)
        df = df.dropna(axis=1, how="all")
        if df.shape[1] == 0:
            show_status("No journal data available yet.", spinning=False)
            return
        symbols = list(df.columns)
        # Configure tree columns: date + symbols (centered)
        columns = ["date"] + symbols
        tree["columns"] = columns
        # Headings
        for col in columns:
            tree.heading(col, text=col, anchor="center")
            tree.column(col, width=100, anchor="center")

        # Body rendered in chunks to avoid stalls
        rows = list(df.index)
        chunk = 200
        render_seq += 1
        my_seq = render_seq

        def render_chunk(start: int) -> None:
            # Abort if a new refresh started or tab not active
            if my_seq != render_seq or not journal_active:
                return
            end = min(start + chunk, len(rows))
            for i in range(start, end):
                d = rows[i]
                values: List[str] = [getattr(d, "isoformat", lambda: str(d))()]
                for sym in symbols:
                    val = df.at[d, sym]
                    values.append("" if pd.isna(val) else f"{val}")
                tree.insert("", "end", values=values)
            if end < len(rows):
                try:
                    show_status(f"Rendering journal... {end}/{len(rows)}", spinning=True)
                except Exception:
                    pass
                parent.after(1, render_chunk, end)
            else:
                # Done
                try:
                    show_status("Journal ready", spinning=False)
                    parent.after(1500, lambda: show_status("", spinning=False))
                except Exception:
                    pass

        parent.after(0, render_chunk, 0)

    def poll_for_updates() -> None:
        nonlocal last_mtime
        try:
            m = os.path.getmtime(journal_path) if os.path.exists(journal_path) else 0.0
        except Exception:
            m = last_mtime
        if m > last_mtime:
            last_mtime = m
            refresh_grid()
        # Poll occasionally; actual UI drawing is throttled inside refresh_grid
        parent.after(1000, poll_for_updates)

    def reload_and_refresh() -> None:
        # Update highlight font if default changed (e.g., zoom)
        try:
            dfnt = tkfont.nametofont("TkDefaultFont")
            highlight_font.configure(family=dfnt.cget("family"), size=dfnt.cget("size"))
        except Exception:
            pass
        refresh_grid()

    parent.bind("<<FontScaleChanged>>", lambda _e: reload_and_refresh())

    # Initial content and polling (polling is idle unless tab becomes active)
    show_status("Waiting to build journal...", spinning=False)
    parent.after(1000, poll_for_updates)

    # Expose refresh hook for tab change
    setattr(parent, "_journal_refresh", reload_and_refresh)
    def set_active(active: bool) -> None:
        nonlocal journal_active
        journal_active = active
        if active:
            # Trigger a refresh when becoming visible
            refresh_grid()
    setattr(parent, "_journal_set_active", set_active)


def register_journal_tab_handlers(notebook: ttk.Notebook, journal_frame: tk.Widget) -> None:
    def on_tab_changed(_evt=None):  # noqa: ANN001
        try:
            current = notebook.select()
            if current == str(journal_frame):
                setter = getattr(journal_frame, "_journal_set_active", None)
                if callable(setter):
                    setter(True)
                fn = getattr(journal_frame, "_journal_refresh", None)
                if callable(fn):
                    fn()
            else:
                setter = getattr(journal_frame, "_journal_set_active", None)
                if callable(setter):
                    setter(False)
        except Exception:
            pass
    notebook.bind("<<NotebookTabChanged>>", on_tab_changed)
