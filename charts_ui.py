import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, timedelta, datetime
from typing import Optional

import matplotlib
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from models import Portfolio, Holding
import storage
from market_data import fetch_price_history


matplotlib.use("TkAgg")


def build_charts_ui(parent: tk.Widget) -> None:
    portfolio: Portfolio = storage.load_portfolio()

    top = ttk.Frame(parent)
    top.pack(fill="x", padx=8, pady=8)

    ttk.Label(top, text="Symbol:").pack(side="left")
    symbol_var = tk.StringVar()
    symbol_combo = ttk.Combobox(top, textvariable=symbol_var, state="readonly", width=16)
    symbol_combo.pack(side="left", padx=8)

    def reload_portfolio() -> None:
        nonlocal portfolio
        portfolio = storage.load_portfolio()
        symbols = [h.symbol for h in portfolio.holdings]
        symbol_combo["values"] = symbols
        if symbols:
            symbol_combo.current(0)

    ttk.Button(top, text="Refresh", command=reload_portfolio).pack(side="left")
    ttk.Button(top, text="Plot", command=lambda: plot_selected()).pack(side="left", padx=(8, 0))

    # Figure area with dark style
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
    })

    fig = Figure(figsize=(8, 5), dpi=100, facecolor="#121212")
    ax = fig.add_subplot(111, facecolor="#1e1e1e")
    ax.set_title("Price History", color="#ffffff")
    ax.set_xlabel("Date", color="#ffffff")
    ax.set_ylabel("Adj Close", color="#ffffff")

    canvas = FigureCanvasTkAgg(fig, master=parent)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(fill="both", expand=True)

    def find_holding(symbol: str) -> Optional[Holding]:
        for h in portfolio.holdings:
            if h.symbol.upper() == symbol.upper():
                return h
        return None

    def normalize_date(date_str: str) -> str:
        s = (date_str or "").strip()
        if not s:
            return s
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                continue
        return s  # leave as-is; fetch may still work or show no data

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

    def plot_selected() -> None:
        symbol = symbol_var.get()
        if not symbol:
            messagebox.showwarning("No symbol", "Select a symbol to plot.")
            return
        holding = find_holding(symbol)
        if holding is None:
            messagebox.showwarning("Not found", f"No holding found for {symbol}.")
            return
        start, end = compute_date_range(holding)
        # yfinance end date is exclusive, add one day
        end_plus = (date.fromisoformat(normalize_date(end)) + timedelta(days=1)).isoformat()
        df = fetch_price_history(symbol, normalize_date(start), end_plus)
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
        canvas.draw()

    reload_portfolio()
