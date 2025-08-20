import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, timedelta, datetime
from typing import Optional, List, Tuple, Dict
import os

import matplotlib
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import pandas as pd

from models import Portfolio, Holding
import storage
from market_data import fetch_price_history


matplotlib.use("TkAgg")


def build_charts_ui(parent: tk.Widget) -> None:
    portfolio: Portfolio = storage.load_portfolio()

    # cache for ROI computations per symbol to keep UI snappy
    roi_cache: Dict[str, Optional[float]] = {}

    # Figure font scaling factor; updated via virtual event
    font_scale = 1.0

    # Left panel: sort + symbols list; Right panel: chart
    main_pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
    main_pane.pack(fill="both", expand=True)

    left = ttk.Frame(main_pane)
    right = ttk.Frame(main_pane)
    main_pane.add(left, weight=1)
    main_pane.add(right, weight=4)

    sort_row = ttk.Frame(left)
    sort_row.pack(fill="x", padx=8, pady=(8, 4))

    ttk.Label(sort_row, text="Sort:").pack(side="left")
    sort_var = tk.StringVar(value="Symbol A-Z")
    sort_combo = ttk.Combobox(
        sort_row,
        textvariable=sort_var,
        state="readonly",
        width=18,
        values=[
            "Symbol A-Z",
            "Symbol Z-A",
            "Oldest first",
            "Newest first",
            "Highest return",
            "Lowest return",
        ],
    )
    sort_combo.pack(side="left", padx=8)

    ttk.Label(left, text="Symbols").pack(anchor="w", padx=8)
    symbols_list = tk.Listbox(left, height=12)
    symbols_list.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # Figure area with dark style
    def apply_matplotlib_style(scale: float) -> None:
        base = 10 * scale
        matplotlib.rcParams.update({
            "axes.facecolor": "#1e1e1e",
            "figure.facecolor": "#121212",
            "savefig.facecolor": "#121212",
            "text.color": "#ffffff",
            "axes.labelcolor": "#ffffff",
            "axes.edgecolor": "#cccccc",
            "xtick.color": "#cccccc",
            "ytick.color": "#cccccc",
            "grid.color": "#333333",
            "font.size": base,
            "axes.titlesize": base + 2,
            "axes.labelsize": base,
            "xtick.labelsize": base - 1,
            "ytick.labelsize": base - 1,
            "legend.fontsize": base - 1,
        })

    def update_axes_fonts(ax, scale: float) -> None:
        base = 10 * scale
        try:
            ax.title.set_fontsize(base + 2)
            ax.xaxis.label.set_size(base)
            ax.yaxis.label.set_size(base)
            for lbl in ax.get_xticklabels() + ax.get_yticklabels():
                lbl.set_fontsize(base - 1)
            leg = ax.get_legend()
            if leg is not None:
                for txt in leg.get_texts():
                    txt.set_fontsize(base - 1)
        except Exception:
            pass

    apply_matplotlib_style(font_scale)

    fig = Figure(figsize=(8, 5), dpi=100, facecolor="#121212", constrained_layout=True)
    ax = fig.add_subplot(111, facecolor="#1e1e1e")
    ax.set_title("Price History", color="#ffffff")
    ax.set_xlabel("Date", color="#ffffff")
    ax.set_ylabel("Adj Close", color="#ffffff")

    canvas = FigureCanvasTkAgg(fig, master=right)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(fill="both", expand=True)

    def on_font_scale_changed(_evt=None):  # noqa: ANN001
        # Derive scale from Tk default font size relative to base 10
        try:
            from tkinter import font as tkfont  # lazy import
            f = tkfont.nametofont("TkDefaultFont")
            current = f.cget("size")
            nonlocal font_scale
            font_scale = max(0.6, min(3.0, current / 10.0))
        except Exception:
            pass
        apply_matplotlib_style(font_scale)
        update_axes_fonts(ax, font_scale)
        canvas.draw_idle()

    parent.bind("<<FontScaleChanged>>", on_font_scale_changed)

    def normalize_date(date_str: str) -> str:
        s = (date_str or "").strip()
        if not s:
            return s
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                continue
        return s

    def holding_start_date(holding: Holding) -> str:
        if not holding.events:
            return date.max.isoformat()
        try:
            return min(normalize_date(e.date) for e in holding.events if e.date)
        except ValueError:
            return date.max.isoformat()

    def reload_portfolio() -> None:
        nonlocal portfolio, roi_cache
        portfolio = storage.load_portfolio()
        roi_cache = {}
        refresh_symbols()

    def compute_date_range(holding: Holding) -> tuple[str, str]:
        if not holding.events:
            today_str = date.today().isoformat()
            return today_str, today_str
        # Start at first event date
        start = min(normalize_date(e.date) for e in holding.events)
        # End at last event date when position goes flat; else today
        shares = 0.0
        last_flat: Optional[str] = None
        for ev in sorted(holding.events, key=lambda e: normalize_date(e.date)):
            if ev.type.value == "purchase":
                shares += ev.shares
            elif ev.type.value == "sale":
                shares -= ev.shares
            if abs(shares) < 1e-9:
                last_flat = normalize_date(ev.date)
        end = last_flat or date.today().isoformat()
        return start, end

    def load_cached_close_series(symbol: str) -> Optional[pd.Series]:
        cache_path = os.path.join(storage.default_data_dir(), "cache", f"{symbol.upper()}_prices.csv")
        if not os.path.exists(cache_path):
            return None
        try:
            df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            if df is None or df.empty:
                return None
            if "Close" in df.columns:
                return df["Close"]
            return df.iloc[:, 0]
        except Exception:
            return None

    def compute_holding_return(holding: Holding) -> Optional[float]:
        # simple ROI: (last_close / first_close) - 1 over the holding date range
        sym = holding.symbol.upper()
        if sym in roi_cache:
            return roi_cache[sym]
        start, end = compute_date_range(holding)
        end_plus = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        # Prefer cached data to avoid fetch lag
        series = load_cached_close_series(sym)
        if series is None:
            df = fetch_price_history(sym, start, end_plus)
            if df is None or df.empty:
                roi_cache[sym] = None
                return None
            series = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
        # Filter to range and compute
        try:
            s = series.dropna()
            if isinstance(s.index, pd.DatetimeIndex):
                s = s.loc[pd.to_datetime(start) : pd.to_datetime(end)]
            vals = s.to_numpy()
            if vals.size == 0:
                roi_cache[sym] = None
                return None
            first_price = float(vals[0])
            last_price = float(vals[-1])
        except Exception:
            roi_cache[sym] = None
            return None
        if first_price <= 0:
            roi_cache[sym] = None
            return None
        roi = (last_price / first_price) - 1.0
        roi_cache[sym] = roi
        return roi

    def sorted_symbols() -> List[str]:
        syms = [h.symbol for h in portfolio.holdings]
        mode = sort_var.get()
        if mode == "Symbol A-Z":
            return sorted(syms)
        if mode == "Symbol Z-A":
            return sorted(syms, reverse=True)
        if mode in ("Oldest first", "Newest first"):
            pairs: List[Tuple[str, str]] = [(holding_start_date(h), h.symbol) for h in portfolio.holdings]
            pairs.sort(key=lambda p: (p[0], p[1]))
            if mode == "Newest first":
                pairs.reverse()
            return [sym for _, sym in pairs]
        if mode in ("Highest return", "Lowest return"):
            # compute ROI and sort accordingly; None values go to the end
            roi_pairs: List[Tuple[float, str]] = []
            missing: List[str] = []
            for h in portfolio.holdings:
                roi = compute_holding_return(h)
                if roi is None:
                    missing.append(h.symbol)
                else:
                    roi_pairs.append((roi, h.symbol))
            roi_pairs.sort(key=lambda p: (p[0], p[1]))
            if mode == "Highest return":
                roi_pairs.reverse()
            ordered = [sym for _, sym in roi_pairs]
            ordered.extend(sorted(missing))
            return ordered
        return sorted(syms)

    def refresh_symbols() -> None:
        symbols_list.delete(0, tk.END)
        for sym in sorted_symbols():
            symbols_list.insert(tk.END, sym)
        # select first and plot
        if symbols_list.size() > 0:
            symbols_list.selection_clear(0, tk.END)
            symbols_list.selection_set(0)
            symbols_list.activate(0)
            plot_selected()
        else:
            clear_chart()

    def clear_chart() -> None:
        ax.clear()
        ax.set_facecolor("#1e1e1e")
        ax.set_title("Price History", color="#ffffff")
        ax.set_xlabel("Date", color="#ffffff")
        ax.set_ylabel("Adj Close", color="#ffffff")
        ax.text(0.5, 0.5, "No symbols", transform=ax.transAxes, ha="center", va="center", color="#cccccc")
        ax.grid(True, color="#333333", linestyle="--", linewidth=0.5)
        for spine in ax.spines.values():
            spine.set_color("#666666")
        canvas.draw()

    def find_holding(symbol: str) -> Optional[Holding]:
        for h in portfolio.holdings:
            if h.symbol.upper() == symbol.upper():
                return h
        return None

    def plot_selected() -> None:
        try:
            idx = symbols_list.curselection()[0]
        except IndexError:
            clear_chart()
            return
        symbol = symbols_list.get(idx)
        holding = find_holding(symbol)
        if holding is None:
            clear_chart()
            return
        start, end = compute_date_range(holding)
        # yfinance end date is exclusive, add one day
        end_plus = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        df = fetch_price_history(symbol, start, end_plus)
        ax.clear()
        ax.set_facecolor("#1e1e1e")
        ax.set_title(f"{symbol} Price History", color="#ffffff")
        ax.set_xlabel("Date", color="#ffffff")
        ax.set_ylabel("Adj Close", color="#ffffff")
        if df is not None and not df.empty:
            series = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
            ax.plot(series.index, series.values, label=symbol, color="#0a84ff")
            ax.legend(facecolor="#1e1e1e", edgecolor="#333333", labelcolor="#ffffff")
        else:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center", color="#cccccc")
        ax.grid(True, color="#333333", linestyle="--", linewidth=0.5)
        for spine in ax.spines.values():
            spine.set_color("#666666")
        update_axes_fonts(ax, font_scale)
        canvas.draw()

    symbols_list.bind("<<ListboxSelect>>", lambda _e: plot_selected())
    sort_combo.bind("<<ComboboxSelected>>", lambda _e: refresh_symbols())

    # Initial load
    apply_matplotlib_style(font_scale)
    reload_portfolio()

    # Expose a hook on the parent so external code can trigger a refresh/plot
    setattr(parent, "_charts_refresh_and_plot", lambda: (reload_portfolio(),))


def register_charts_tab_handlers(notebook: ttk.Notebook, charts_frame: tk.Widget) -> None:
    def on_tab_changed(_evt=None):  # noqa: ANN001
        try:
            current = notebook.select()
            if current == str(charts_frame):
                # Call the refresh hook if present
                fn = getattr(charts_frame, "_charts_refresh_and_plot", None)
                if callable(fn):
                    fn()
        except Exception:
            pass
    notebook.bind("<<NotebookTabChanged>>", on_tab_changed)
