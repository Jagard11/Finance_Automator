import tkinter as tk
from tkinter import ttk
from datetime import date, timedelta, datetime
from typing import Dict, List, Optional, Tuple

import os
import math
from models import Portfolio, Holding, EventType
import storage
from market_data import fetch_price_history
from values_cache import read_values_cache
import pandas as pd
import settings


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
    day_prices_cache: Dict[str, Tuple[Optional[float], Optional[float]]] = {}

    # Top metrics
    top = ttk.Frame(parent)
    top.pack(fill="x", padx=8, pady=8)

    ttk.Button(top, text="Refresh", command=lambda: reload_and_refresh()).pack(side="right")
    # Show active portfolio file
    active_file_var = tk.StringVar(value=os.path.basename(portfolio_path))
    ttk.Label(top, textvariable=active_file_var).pack(side="right", padx=(0, 12))

    metrics = ttk.Frame(parent)
    metrics.pack(fill="x", padx=8, pady=(0, 8))

    lbl_total_cost = tk.StringVar(value="Cost: -")
    lbl_dividends = tk.StringVar(value="Dividends: -")

    # Big total value with ROI subtext
    from tkinter import font as tkfont
    base_font = tkfont.nametofont("TkDefaultFont")
    big_font = base_font.copy()
    big_font.configure(size=int(base_font.cget("size")) + 10, weight="bold")

    leftcol = ttk.Frame(metrics)
    leftcol.pack(side="left", padx=(0, 16))
    total_value_label = tk.Label(leftcol, text="Profit: $-", font=big_font, fg="#2ecc71", padx=8)
    total_value_label.pack(anchor="w")
    day_profit_big = tk.Label(leftcol, text="Day Profit: $-", font=big_font, fg="#cccccc", padx=8)
    day_profit_big.pack(anchor="w")

    roi_subtext = tk.Label(metrics, text="ROI: -", padx=4)
    roi_subtext.pack(side="left", padx=(0, 8))
    day_gain_pct_header = tk.Label(metrics, text="Day %: -", padx=4)
    day_gain_pct_header.pack(side="left", padx=(0, 8))
    total_value_subtext = tk.Label(metrics, text="Total: -", padx=4)
    total_value_subtext.pack(side="left", padx=(0, 16))

    ttk.Label(metrics, textvariable=lbl_total_cost).pack(side="left", padx=(0, 16))
    ttk.Label(metrics, textvariable=lbl_dividends).pack(side="left", padx=(0, 16))

    # Symbols table
    columns = ("symbol", "shares", "last_price", "value", "cost", "avg_cost", "day_gain", "day_gain_pct", "roi", "start", "last")
    tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
    tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    tree.heading("symbol", text="Symbol", anchor="center")
    tree.heading("shares", text="Shares", anchor="center")
    tree.heading("last_price", text="Price", anchor="center")
    tree.heading("value", text="Value", anchor="center")
    tree.heading("cost", text="Cost", anchor="center")
    tree.heading("avg_cost", text="Avg/Sh", anchor="center")
    tree.heading("day_gain", text="Day $", anchor="center")
    tree.heading("day_gain_pct", text="Day %", anchor="center")
    tree.heading("roi", text="ROI", anchor="center")
    tree.heading("start", text="First", anchor="center")
    tree.heading("last", text="Last", anchor="center")

    # Initial widths (auto-adjust on font scale change)
    tree.column("symbol", width=80, anchor="center")
    tree.column("shares", width=70, anchor="center")
    tree.column("last_price", width=90, anchor="center")
    tree.column("value", width=110, anchor="center")
    tree.column("cost", width=110, anchor="center")
    tree.column("avg_cost", width=110, anchor="center")
    tree.column("day_gain", width=110, anchor="center")
    tree.column("day_gain_pct", width=90, anchor="center")
    tree.column("roi", width=90, anchor="center")
    tree.column("start", width=110, anchor="center")
    tree.column("last", width=110, anchor="center")

    def auto_size_columns() -> None:
        try:
            from tkinter import font as tkfont
            f = tkfont.nametofont("TkDefaultFont")
            def ch(n: int) -> int:
                return int(n * max(6, f.measure("0")) / 1.6)
            tree.column("symbol", width=ch(8))
            tree.column("shares", width=ch(6))
            tree.column("last_price", width=ch(8))
            tree.column("value", width=ch(10))
            tree.column("cost", width=ch(10))
            tree.column("avg_cost", width=ch(10))
            tree.column("day_gain", width=ch(10))
            tree.column("day_gain_pct", width=ch(8))
            tree.column("roi", width=ch(8))
            tree.column("start", width=ch(10))
            tree.column("last", width=ch(10))
        except Exception:
            pass

    parent.bind("<<FontScaleChanged>>", lambda _e: auto_size_columns())

    # Restore saved column widths
    def apply_saved_layout() -> None:
        try:
            s = settings.load_settings()
            tab = s.get("summary", {})
            saved_cols = tab.get("columns", {})
            if isinstance(saved_cols, dict):
                for col_id in columns:
                    try:
                        w = int(saved_cols.get(col_id, 0))
                        if w > 0:
                            tree.column(col_id, width=w)
                    except Exception:
                        continue
        except Exception:
            pass

    # Persist column widths when requested
    def save_state() -> None:
        try:
            s = settings.load_settings()
            tab = dict(s.get("summary", {}))
            col_widths = {}
            for col_id in columns:
                try:
                    col_widths[col_id] = int(tree.column(col_id, "width"))
                except Exception:
                    continue
            tab["columns"] = col_widths
            s["summary"] = tab
            settings.save_settings(s)
        except Exception:
            pass

    try:
        parent.bind_all("<<PersistUIState>>", lambda _e: save_state())
    except Exception:
        pass

    # Note: Per-cell coloring isn't supported natively by ttk.Treeview.
    # We avoid row-level coloring to keep the table uncluttered.

    # Sorting state
    sort_col = "symbol"
    sort_reverse = False

    def last_price(symbol: str) -> Optional[float]:
        if symbol in last_price_cache:
            return last_price_cache[symbol]
        # Prefer values cache derived price (robust and warmed by worker)
        price: Optional[float] = None
        try:
            vdf = read_values_cache(symbol)
            if vdf is not None and not vdf.empty:
                # Last non-null value with shares > 0
                vdf = vdf.copy()
                vdf.sort_values("date", inplace=True)
                vdf["shares"] = pd.to_numeric(vdf.get("shares"), errors="coerce")
                vdf["value"] = pd.to_numeric(vdf.get("value"), errors="coerce")
                vdf = vdf[(vdf["shares"] > 0) & (~vdf["value"].isna())]
                if not vdf.empty:
                    last_row = vdf.iloc[-1]
                    price = float(last_row["value"]) / float(last_row["shares"]) if float(last_row["shares"]) > 0 else None
        except Exception:
            price = None
        # Fallback to price cache if needed
        if price is None:
            end = date.today()
            start = end - timedelta(days=14)
            df = fetch_price_history(symbol, start.isoformat(), (end + timedelta(days=1)).isoformat(), avoid_network=True)
            if df is not None and not df.empty:
                series = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
                try:
                    price = float(series.dropna().iloc[-1])
                except Exception:
                    price = None
        last_price_cache[symbol] = price
        return price

    def day_prices(symbol: str) -> Tuple[Optional[float], Optional[float]]:
        # Returns (previous_close, last_close)
        if symbol in day_prices_cache:
            return day_prices_cache[symbol]
        prev: Optional[float] = None
        last: Optional[float] = None
        # Prefer values cache derived prices (same as last_price logic)
        try:
            vdf = read_values_cache(symbol)
            if vdf is not None and not vdf.empty:
                vdf = vdf.copy()
                vdf.sort_values("date", inplace=True)
                vdf["shares"] = pd.to_numeric(vdf.get("shares"), errors="coerce")
                vdf["value"] = pd.to_numeric(vdf.get("value"), errors="coerce")
                vdf = vdf[(vdf["shares"] > 0) & (~vdf["value"].isna())]
                if len(vdf) >= 1:
                    last_row = vdf.iloc[-1]
                    s_last = float(last_row["shares"]) if float(last_row["shares"]) > 0 else None
                    if s_last is not None:
                        last = float(last_row["value"]) / s_last
                if len(vdf) >= 2:
                    prev_row = vdf.iloc[-2]
                    s_prev = float(prev_row["shares"]) if float(prev_row["shares"]) > 0 else None
                    if s_prev is not None:
                        prev = float(prev_row["value"]) / s_prev
        except Exception:
            prev = prev
            last = last
        # Fallback to local price history cache if needed
        if prev is None or last is None:
            try:
                end = date.today()
                start = end - timedelta(days=14)
                df = fetch_price_history(symbol, start.isoformat(), (end + timedelta(days=1)).isoformat(), avoid_network=True)
                if df is not None and not df.empty:
                    series = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
                    s = series.dropna()
                    if last is None and len(s) >= 1:
                        last = float(s.iloc[-1])
                    if prev is None and len(s) >= 2:
                        prev = float(s.iloc[-2])
            except Exception:
                pass
        day_prices_cache[symbol] = (prev, last)
        return prev, last

    def recompute_and_fill() -> None:
        # Clear rows
        for iid in tree.get_children():
            tree.delete(iid)
        total_value = 0.0
        total_cost = 0.0
        total_div = 0.0

        rows: List[Tuple] = []
        portfolio_day_gain_total = 0.0
        portfolio_prev_value_total = 0.0
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
            avg_cost = None
            if shares and shares > 0:
                try:
                    avg_cost = max(0.0, cost) / shares
                except Exception:
                    avg_cost = None
            prev_close, last_close = day_prices(sym)
            day_gain_val: Optional[float] = None
            day_gain_pct: Optional[float] = None
            try:
                if prev_close is not None and last_close is not None and shares is not None and shares > 0:
                    day_gain_val = (last_close - prev_close) * shares
                if prev_close is not None and prev_close != 0 and last_close is not None:
                    day_gain_pct = (last_close - prev_close) / prev_close
            except Exception:
                day_gain_val = None
                day_gain_pct = None
            rows.append((sym, shares, lp, value, cost, avg_cost, day_gain_val, day_gain_pct, roi, start_dt, last_dt))
            total_value += value
            total_cost += max(0.0, cost)
            if day_gain_val is not None:
                portfolio_day_gain_total += day_gain_val
            if prev_close is not None and shares is not None and shares > 0:
                portfolio_prev_value_total += prev_close * shares
        # Dividends total: include cash events and reinvested (holding-level) dividends
        for ev in portfolio.cash_events:
            if ev.type == EventType.DIVIDEND:
                total_div += float(ev.amount or 0)
        for h in portfolio.holdings:
            for ev in h.events:
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
                "avg_cost": row[5] if row[5] is not None else -1e18,
                "day_gain": row[6] if row[6] is not None else -1e18,
                "day_gain_pct": row[7] if row[7] is not None else -1e18,
                "roi": row[8] if row[8] is not None else -1e18,
                "start": row[9],
                "last": row[10],
            }
            return (mapping.get(sort_col), row[0])

        rows.sort(key=sort_key, reverse=sort_reverse)

        for sym, shares, lp, value, cost, avg_cost, day_gain_val, day_gain_pct, roi, start_dt, last_dt in rows:
            tree.insert("", "end", iid=sym, values=(
                sym,
                f"{shares:g}",
                ("-" if lp is None else f"${math.ceil(lp):,}"),
                f"${math.ceil(value):,}",
                f"${math.ceil(cost):,}",
                ("-" if (avg_cost is None or shares <= 0) else f"${math.ceil(avg_cost):,}"),
                ("-" if day_gain_val is None else f"${math.ceil(day_gain_val):,}"),
                ("-" if day_gain_pct is None else f"{day_gain_pct*100:.2f}%"),
                ("-" if roi is None else f"{roi*100:.2f}%"),
                start_dt,
                last_dt,
            ))

        overall_roi = None
        if total_cost > 0:
            overall_roi = (total_value + total_div - total_cost) / total_cost
        # Profit (includes dividends)
        profit_total = total_value + total_div - total_cost
        color = "#2ecc71" if profit_total >= 0 else "#e74c3c"
        total_value_label.config(text=f"Profit: ${math.ceil(profit_total):,}", fg=color)
        roi_subtext.config(text=("ROI: -" if overall_roi is None else f"ROI: {overall_roi*100:.2f}%"))
        total_value_subtext.config(text=f"Total: ${math.ceil(total_value):,}")
        lbl_total_cost.set(f"Cost: ${math.ceil(total_cost):,}")
        lbl_dividends.set(f"Dividends: ${math.ceil(total_div):,}")

        # Daily portfolio gain in header
        day_color = "#cccccc"
        if portfolio_prev_value_total > 0:
            day_color = "#2ecc71" if portfolio_day_gain_total >= 0 else "#e74c3c"
            day_gain_pct_port = portfolio_day_gain_total / portfolio_prev_value_total
            day_profit_big.config(text=f"Day Profit: ${math.ceil(portfolio_day_gain_total):,}", fg=day_color)
            day_gain_pct_header.config(text=f"Day %: {day_gain_pct_port*100:.2f}%", fg=day_color)
        else:
            day_profit_big.config(text="Day Profit: -", fg=day_color)
            day_gain_pct_header.config(text="Day %: -", fg=day_color)

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
        nonlocal portfolio, last_price_cache, day_prices_cache, last_mtime, portfolio_path
        # Always resolve current default path in case it was swapped
        portfolio_path = storage.default_portfolio_path()
        # Only reload from disk if file changed to avoid thrashing caches
        try:
            m = os.path.getmtime(portfolio_path) if os.path.exists(portfolio_path) else 0.0
        except Exception:
            m = last_mtime
        if m > last_mtime:
            last_mtime = m
            portfolio = storage.load_portfolio()
        # Invalidate caches so newly downloaded data is reflected immediately
        last_price_cache = {}
        day_prices_cache = {}
        recompute_and_fill()
        try:
            active_file_var.set(os.path.basename(portfolio_path))
        except Exception:
            pass

    # Initial load
    reload_and_refresh()
    apply_saved_layout()

    # Expose refresh hook for tab change
    setattr(parent, "_summary_refresh", reload_and_refresh)

    # Also refresh when portfolio changes from other tabs
    try:
        parent.bind_all("<<PortfolioChanged>>", lambda _e: reload_and_refresh())
    except Exception:
        pass


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
