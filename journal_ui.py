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

    # Fonts
    default_font = tkfont.nametofont("TkDefaultFont")
    highlight_font = tkfont.Font(family=default_font.cget("family"), size=default_font.cget("size"), weight="bold", underline=1)

    # Container with scrollbars
    container = ttk.Frame(parent)
    container.pack(fill="both", expand=True)

    xscroll = ttk.Scrollbar(container, orient="horizontal")
    yscroll = ttk.Scrollbar(container, orient="vertical")

    canvas = tk.Canvas(container, highlightthickness=0)
    grid_frame = ttk.Frame(canvas)

    xscroll.config(command=canvas.xview)
    yscroll.config(command=canvas.yview)
    canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)

    xscroll.pack(side="bottom", fill="x")
    yscroll.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    canvas_window = canvas.create_window((0, 0), window=grid_frame, anchor="nw")

    journal_path = journal_csv_path()
    last_mtime = os.path.getmtime(journal_path) if os.path.exists(journal_path) else 0.0
    last_refresh = 0.0

    def on_configure(_evt=None):  # noqa: ANN001
        canvas.configure(scrollregion=canvas.bbox("all"))

    grid_frame.bind("<Configure>", on_configure)

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
        nonlocal highlight_font, last_refresh
        now = time.time()
        if now - last_refresh < 1.0:
            return
        last_refresh = now
        # Preserve scroll
        x = canvas.xview()
        y = canvas.yview()
        # Clear
        for w in grid_frame.winfo_children():
            w.destroy()
        df = read_journal()
        if df is None or df.empty:
            ttk.Label(grid_frame, text="Journal not built yet...").grid(row=0, column=0, padx=8, pady=8)
            on_configure()
            # Kick off build if missing
            rebuild_journal_in_background()
            return
        symbols = list(df.columns)
        # Header
        ttk.Label(grid_frame, text="Date").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        for j, sym in enumerate(symbols, start=1):
            ttk.Label(grid_frame, text=sym).grid(row=0, column=j, padx=6, pady=4, sticky="w")
        # Max per symbol
        max_idx: Dict[str, int] = {}
        for sym in symbols:
            col = pd.to_numeric(df[sym], errors="coerce")
            try:
                max_val = col.max(skipna=True)
                if pd.isna(max_val):
                    continue
                row_pos = int(col.index.get_indexer_for([col.idxmax()])[0])
                max_idx[sym] = row_pos
            except Exception:
                continue
        # Body
        for i, d in enumerate(df.index, start=1):
            ttk.Label(grid_frame, text=d.isoformat()).grid(row=i, column=0, padx=6, pady=2, sticky="w")
            for j, sym in enumerate(symbols, start=1):
                s = df.at[d, sym]
                s = "" if pd.isna(s) else str(s)
                if sym in max_idx and max_idx[sym] == (i - 1):
                    tk.Label(grid_frame, text=s, font=highlight_font).grid(row=i, column=j, padx=6, pady=2, sticky="w")
                else:
                    ttk.Label(grid_frame, text=s).grid(row=i, column=j, padx=6, pady=2, sticky="w")
        on_configure()
        # Restore scroll
        canvas.xview_moveto(x[0])
        canvas.yview_moveto(y[0])

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

    # Initial content and polling
    ttk.Label(grid_frame, text="Open the Journal tab to load cached values").grid(row=0, column=0, padx=8, pady=8)
    parent.after(1000, refresh_grid)
    parent.after(1000, poll_for_updates)

    # Expose refresh hook for tab change
    setattr(parent, "_journal_refresh", reload_and_refresh)


def register_journal_tab_handlers(notebook: ttk.Notebook, journal_frame: tk.Widget) -> None:
    def on_tab_changed(_evt=None):  # noqa: ANN001
        try:
            current = notebook.select()
            if current == str(journal_frame):
                fn = getattr(journal_frame, "_journal_refresh", None)
                if callable(fn):
                    fn()
        except Exception:
            pass
    notebook.bind("<<NotebookTabChanged>>", on_tab_changed)
