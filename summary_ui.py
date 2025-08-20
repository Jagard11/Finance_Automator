import tkinter as tk
from tkinter import ttk
from datetime import date, timedelta, datetime
from typing import Dict, List, Optional, Tuple

import os
from models import Portfolio, Holding, EventType
import storage
from market_data import fetch_price_history


def _normalize_date(date_str: str) -> str:
    s = (date_str or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s


def _shares_held(holding: Holding) -> float:
    shares = 0.0
    for ev in holding.events:
        if ev.type == EventType.PURCHASE:
            shares += float(ev.shares or 0)
        elif ev.type == EventType.SALE:
            shares -= float(ev.shares or 0)
    return shares


def _cost_basis(holding: Holding) -> float:
    # Simple net cash flow into position: buys - sells
    cost = 0.0
    for ev in holding.events:
        if ev.type == EventType.PURCHASE:
            cost += float(ev.shares or 0) * float(ev.price or 0)
        elif ev.type == EventType.SALE:
            cost -= float(ev.shares or 0) * float(ev.price or 0)
    return cost


def _date_range(holding: Holding) -> Tuple[str, str]:
    dates = [_normalize_date(e.date) for e in holding.events if e.date]
    if not dates:
        today = date.today().isoformat()
        return today, today
    return min(dates), max(dates)


def build_summary_ui(parent: tk.Widget) -> None:
    portfolio: Portfolio = storage.load_portfolio()
    portfolio_path = storage.default_portfolio_path()
    try:
        last_mtime = os.path.getmtime(portfolio_path) if os.path.exists(portfolio_path) else 0.0
    except Exception:
        last_mtime = 0.0

    # Price cache per symbol
    last_price_cache: Dict[str, Optional[float]] = {}

    # Top metrics
    top = ttk.Frame(parent)
    top.pack(fill="x", padx=8, pady=8)

    ttk.Button(top, text="Refresh", command=lambda: reload_and_refresh()).pack(side="right")

    metrics = ttk.Frame(parent)
    metrics.pack(fill="x", padx=8, pady=(0, 8))

    lbl_total_value = tk.StringVar(value="Total Value: -")
    lbl_total_cost = tk.StringVar(value="Total Cost: -")
    lbl_dividends = tk.StringVar(value="Dividends: -")
    lbl_roi = tk.StringVar(value="ROI: -")

    ttk.Label(metrics, textvariable=lbl_total_value).pack(side="left", padx=(0, 16))
    ttk.Label(metrics, textvariable=lbl_total_cost).pack(side="left", padx=(0, 16))
    ttk.Label(metrics, textvariable=lbl_dividends).pack(side="left", padx=(0, 16))
    ttk.Label(metrics, textvariable=lbl_roi).pack(side="left", padx=(0, 16))

    # Symbols table
    columns = ("symbol", "shares", "last_price", "value", "cost", "roi", "start", "last")
    tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
    tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    tree.heading("symbol", text="Symbol")
    tree.heading("shares", text="Shares")
    tree.heading("last_price", text="Last Price")
    tree.heading("value", text="Value")
    tree.heading("cost", text="Cost Basis")
    tree.heading("roi", text="ROI")
    tree.heading("start", text="First Event")
    tree.heading("last", text="Last Event")

    # Initial widths (auto-adjust on font scale change)
    tree.column("symbol", width=100, anchor="w")
    tree.column("shares", width=100, anchor="e")
    tree.column("last_price", width=100, anchor="e")
    tree.column("value", width=120, anchor="e")
    tree.column("cost", width=120, anchor="e")
    tree.column("roi", width=90, anchor="e")
    tree.column("start", width=120, anchor="w")
    tree.column("last", width=120, anchor="w")

    def auto_size_columns() -> None:
        try:
            from tkinter import font as tkfont
            f = tkfont.nametofont("TkDefaultFont")
            def ch(n: int) -> int:
                return int(n * max(6, f.measure("0")) / 1.6)
            tree.column("symbol", width=ch(10))
            tree.column("shares", width=ch(10))
            tree.column("last_price", width=ch(10))
            tree.column("value", width=ch(12))
            tree.column("cost", width=ch(12))
            tree.column("roi", width=ch(8))
            tree.column("start", width=ch(12))
            tree.column("last", width=ch(12))
        except Exception:
            pass

    parent.bind("<<FontScaleChanged>>", lambda _e: auto_size_columns())

    # Sorting state
    sort_col = "symbol"
    sort_reverse = False

    def last_price(symbol: str) -> Optional[float]:
        if symbol in last_price_cache:
            return last_price_cache[symbol]
        # Fetch last close over recent window
        end = date.today()
        start = end - timedelta(days=14)
        # Use cache-only to keep UI snappy; background worker will update cache
        df = fetch_price_history(symbol, start.isoformat(), (end + timedelta(days=1)).isoformat(), avoid_network=True)
        price = None
        if df is not None and not df.empty:
            series = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
            try:
                price = float(series.dropna().iloc[-1])
            except Exception:  # noqa: BLE001
                price = None
        last_price_cache[symbol] = price
        return price

    def recompute_and_fill() -> None:
        # Clear rows
        for iid in tree.get_children():
            tree.delete(iid)
        total_value = 0.0
        total_cost = 0.0
        total_div = 0.0

        rows: List[Tuple] = []
        for holding in portfolio.holdings:
            sym = holding.symbol
            shares = _shares_held(holding)
            cost = _cost_basis(holding)
            start_dt, last_dt = _date_range(holding)
            lp = last_price(sym)
            value = (lp or 0.0) * shares
            roi = None
            if cost and cost != 0:
                roi = (value - cost) / cost
            rows.append((sym, shares, lp, value, cost, roi, start_dt, last_dt))
            total_value += value
            total_cost += max(0.0, cost)
        # Dividends total
        for ev in portfolio.cash_events:
            if ev.type == EventType.DIVIDEND:
                total_div += float(ev.amount or 0)

        # Sort rows
        def sort_key(row: Tuple) -> Tuple:
            mapping = {
                "symbol": row[0],
                "shares": row[1] if row[1] is not None else -1e18,
                "last_price": row[2] if row[2] is not None else -1e18,
                "value": row[3],
                "cost": row[4],
                "roi": row[5] if row[5] is not None else -1e18,
                "start": row[6],
                "last": row[7],
            }
            return (mapping.get(sort_col), row[0])

        rows.sort(key=sort_key, reverse=sort_reverse)

        for sym, shares, lp, value, cost, roi, start_dt, last_dt in rows:
            tree.insert("", "end", iid=sym, values=(
                sym,
                f"{shares:g}",
                ("-" if lp is None else f"{lp:.2f}"),
                f"{value:.2f}",
                f"{cost:.2f}",
                ("-" if roi is None else f"{roi*100:.2f}%"),
                start_dt,
                last_dt,
            ))

        overall_roi = None
        if total_cost > 0:
            overall_roi = (total_value + total_div - total_cost) / total_cost
        lbl_total_value.set(f"Total Value: {total_value:.2f}")
        lbl_total_cost.set(f"Total Cost: {total_cost:.2f}")
        lbl_dividends.set(f"Dividends: {total_div:.2f}")
        lbl_roi.set("ROI: -" if overall_roi is None else f"ROI: {overall_roi*100:.2f}%")

        auto_size_columns()

    def on_sort(col: str) -> None:
        nonlocal sort_col, sort_reverse
        if sort_col == col:
            sort_reverse = not sort_reverse
        else:
            sort_col = col
            sort_reverse = False
        recompute_and_fill()

    for col in columns:
        tree.heading(col, text=tree.heading(col, option="text"), command=lambda c=col: on_sort(c))

    def reload_and_refresh() -> None:
        nonlocal portfolio, last_price_cache, last_mtime
        # Only reload from disk if file changed to avoid thrashing caches
        try:
            m = os.path.getmtime(portfolio_path) if os.path.exists(portfolio_path) else 0.0
        except Exception:
            m = last_mtime
        if m > last_mtime:
            last_mtime = m
            portfolio = storage.load_portfolio()
        # Preserve last_price_cache across refreshes so we don't re-read CSVs unnecessarily
        recompute_and_fill()

    # Initial load
    reload_and_refresh()

    # Expose refresh hook for tab change
    setattr(parent, "_summary_refresh", reload_and_refresh)


def register_summary_tab_handlers(notebook: ttk.Notebook, summary_frame: tk.Widget) -> None:
    def on_tab_changed(_evt=None):  # noqa: ANN001
        try:
            current = notebook.select()
            if current == str(summary_frame):
                fn = getattr(summary_frame, "_summary_refresh", None)
                if callable(fn):
                    fn()
        except Exception:
            pass
    notebook.bind("<<NotebookTabChanged>>", on_tab_changed)
