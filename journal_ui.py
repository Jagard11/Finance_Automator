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
    render_seq = 0
    journal_active = False

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
        nonlocal highlight_font, last_refresh, render_seq
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
            show_status("Building journal...", spinning=True)
            ttk.Label(grid_frame, text="Journal not built yet...").grid(row=0, column=0, padx=8, pady=8)
            on_configure()
            # Kick off build if missing
            rebuild_journal_in_background()
            return
        show_status("Rendering journal...", spinning=True)
        # Drop all-empty columns (symbols with no values)
        df = df.dropna(axis=1, how="all")
        if df.shape[1] == 0:
            show_status("No journal data available yet.", spinning=False)
            ttk.Label(grid_frame, text="No journal data available yet.").grid(row=0, column=0, padx=8, pady=8)
            on_configure()
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
        # Body rendered in chunks to avoid stalls
        rows = list(df.index)
        chunk = 100
        render_seq += 1
        my_seq = render_seq

        def render_chunk(start: int) -> None:
            # Abort if a new refresh started or tab not active
            if my_seq != render_seq or not journal_active:
                return
            end = min(start + chunk, len(rows))
            for i in range(start, end):
                d = rows[i]
                grid_row = i + 1
                ttk.Label(grid_frame, text=d.isoformat()).grid(row=grid_row, column=0, padx=6, pady=2, sticky="w")
                for j, sym in enumerate(symbols, start=1):
                    s = df.at[d, sym]
                    s = "" if pd.isna(s) else str(s)
                    if sym in max_idx and max_idx[sym] == i:
                        tk.Label(grid_frame, text=s, font=highlight_font).grid(row=grid_row, column=j, padx=6, pady=2, sticky="w")
                    else:
                        ttk.Label(grid_frame, text=s).grid(row=grid_row, column=j, padx=6, pady=2, sticky="w")
            on_configure()
            if end < len(rows):
                try:
                    show_status(f"Rendering journal... {end}/{len(rows)}", spinning=True)
                except Exception:
                    pass
                parent.after(1, render_chunk, end)
            else:
                # Restore scroll after full render
                canvas.xview_moveto(x[0])
                canvas.yview_moveto(y[0])
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
    ttk.Label(grid_frame, text="Open the Journal tab to load cached values").grid(row=0, column=0, padx=8, pady=8)
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
