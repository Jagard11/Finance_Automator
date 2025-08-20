import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from datetime import date, timedelta, datetime
from typing import Dict, List, Optional

import pandas as pd

import storage
from models import Portfolio, Holding
from values_cache import read_values_cache


def _normalize_date(s: str) -> str:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s


def _holding_start(holding: Holding) -> Optional[str]:
    dates = [_normalize_date(e.date) for e in holding.events if e.date]
    if not dates:
        return None
    return min(dates)


def _build_values_dataframe_from_cache(portfolio: Portfolio) -> pd.DataFrame:
    symbols: List[str] = [h.symbol for h in portfolio.holdings]
    frames: List[pd.DataFrame] = []
    for sym in symbols:
        df = read_values_cache(sym)
        if df is None or df.empty:
            continue
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df.set_index("date", inplace=True)
        df.rename(columns={"value": sym}, inplace=True)
        frames.append(df[[sym]])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=1).sort_index()
    return out


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

    def on_configure(_evt=None):  # noqa: ANN001
        canvas.configure(scrollregion=canvas.bbox("all"))

    grid_frame.bind("<Configure>", on_configure)

    def refresh_grid() -> None:
        nonlocal portfolio, highlight_font
        # Clear existing children
        for w in grid_frame.winfo_children():
            w.destroy()
        values = _build_values_dataframe_from_cache(portfolio)
        if values is None or values.empty:
            ttk.Label(grid_frame, text="No cached values yet").grid(row=0, column=0, padx=8, pady=8)
            on_configure()
            return
        symbols = list(values.columns)
        # Header row
        ttk.Label(grid_frame, text="Date").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        for j, sym in enumerate(symbols, start=1):
            ttk.Label(grid_frame, text=sym).grid(row=0, column=j, padx=6, pady=4, sticky="w")
        # Determine per-column maxima row index
        max_idx: Dict[str, int] = {}
        for sym in symbols:
            col = values[sym]
            try:
                max_val = col.max(skipna=True)
                if pd.isna(max_val):
                    continue
                # First occurrence index
                row_pos = int(col.index.get_indexer_for([col.idxmax()])[0])
                max_idx[sym] = row_pos
            except Exception:  # noqa: BLE001
                continue
        # Body
        for i, ts in enumerate(values.index, start=1):
            date_str = pd.Timestamp(ts).isoformat()
            ttk.Label(grid_frame, text=date_str).grid(row=i, column=0, padx=6, pady=2, sticky="w")
            for j, sym in enumerate(symbols, start=1):
                val = values.at[ts, sym]
                txt = "" if pd.isna(val) else f"{val:.2f}"
                if sym in max_idx and max_idx[sym] == (i - 1):
                    tk.Label(grid_frame, text=txt, font=highlight_font).grid(row=i, column=j, padx=6, pady=2, sticky="w")
                else:
                    ttk.Label(grid_frame, text=txt).grid(row=i, column=j, padx=6, pady=2, sticky="w")
        on_configure()

    def reload_and_refresh() -> None:
        nonlocal portfolio, highlight_font
        portfolio = storage.load_portfolio()
        # Update highlight font if default changed (e.g., zoom)
        try:
            df = tkfont.nametofont("TkDefaultFont")
            highlight_font.configure(family=df.cget("family"), size=df.cget("size"))
        except Exception:
            pass
        refresh_grid()

    parent.bind("<<FontScaleChanged>>", lambda _e: reload_and_refresh())

    # Do not auto-load at startup to avoid blocking UI; load on tab open
    ttk.Label(grid_frame, text="Open the Journal tab to load cached values").grid(row=0, column=0, padx=8, pady=8)

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
