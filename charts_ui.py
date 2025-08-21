import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
from datetime import date, timedelta, datetime
from typing import Optional, List, Tuple, Dict

def _lazy_import_matplotlib():
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # type: ignore[F401]
    from matplotlib.figure import Figure  # type: ignore[F401]
    return matplotlib, FigureCanvasTkAgg, Figure

from models import Portfolio, Holding
import storage
from market_data import fetch_price_history
from values_cache import read_values_cache
from settings import vprint, load_settings, save_settings
import pandas as pd


matplotlib, FigureCanvasTkAgg, Figure = _lazy_import_matplotlib()


def build_charts_ui(parent: tk.Widget) -> None:
    portfolio: Portfolio = storage.load_portfolio()

    # cache for ROI computations per symbol to keep UI snappy
    roi_cache: Dict[str, float] = {}

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
    # Keep selection when focus moves away (so returning to tab retains selection)
    symbols_list = tk.Listbox(left, height=12, exportselection=False)
    symbols_list.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # Reference data controls
    ref_row = ttk.Frame(left)
    ref_row.pack(fill="x", padx=8, pady=(0, 8))
    ttk.Label(ref_row, text="Reference:").pack(side="left")
    ref_var = tk.StringVar(value="")
    ref_entry = ttk.Entry(ref_row, textvariable=ref_var, width=12)
    ref_entry.pack(side="left", padx=(4, 4))
    ref_enable_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(ref_row, text="Show", variable=ref_enable_var, command=lambda: plot_selected()).pack(side="left")

    # Plot mode state (UI is created beside the chart below)
    mode_var = tk.StringVar(value="price")
    try:
        chs = load_settings().get("charts", {})
        if isinstance(chs, dict) and chs.get("mode") in {"price", "perf"}:
            mode_var.set(str(chs.get("mode")))
    except Exception:
        pass
    def _on_mode_changed() -> None:
        try:
            s = load_settings()
            ch = dict(s.get("charts", {}))
            ch["mode"] = mode_var.get()
            s["charts"] = ch
            save_settings(s)
        except Exception:
            pass
        plot_selected()

    # Header above chart with company name, price, change, status, and link (mirrors Portfolio tab)
    header = ttk.Frame(right)
    header.pack(fill="x", padx=8, pady=(0, 8))
    try:
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)
    except Exception:
        pass
    left_col = ttk.Frame(header)
    try:
        left_col.grid(row=0, column=0, sticky="w")
    except Exception:
        pass
    company_var = tk.StringVar(value="")
    company_label = ttk.Label(left_col, textvariable=company_var)
    company_label.pack(anchor="w")
    price_row = ttk.Frame(left_col)
    price_row.pack(anchor="w")
    price_var = tk.StringVar(value="")
    change_var = tk.StringVar(value="")
    # Fonts for price and change (large and half-size-ish)
    try:
        from tkinter import font as tkfont  # local import
        heading_font = tkfont.nametofont("TkHeadingFont")
        price_font = heading_font.copy(); price_font.configure(size=max(10, int(heading_font.cget("size") * 2)))
        change_font = heading_font.copy(); change_font.configure(size=max(8, int(heading_font.cget("size"))))
    except Exception:
        price_font = None
        change_font = None
    price_label = ttk.Label(price_row, textvariable=price_var)
    if price_font is not None:
        price_label.configure(font=price_font)
    price_label.pack(side="left")
    change_label = ttk.Label(price_row, textvariable=change_var)
    if change_font is not None:
        change_label.configure(font=change_font)
    change_label.pack(side="left", padx=(8, 0))
    status_var = tk.StringVar(value="")
    status_label = ttk.Label(left_col, textvariable=status_var)
    status_label.pack(anchor="w")
    link_label = ttk.Label(left_col, text="View on Yahoo Finance", foreground="#0a84ff", cursor="hand2")
    link_label.pack(anchor="w")
    def _open_symbol_link() -> None:
        try:
            sel = symbols_list.get(symbols_list.curselection()[0]) if symbols_list.curselection() else ""
        except Exception:
            sel = ""
        try:
            if sel:
                webbrowser.open_new_tab(f"https://finance.yahoo.com/quote/{sel}")
        except Exception:
            pass
    link_label.bind("<Button-1>", lambda _e: _open_symbol_link())

    def _is_after_close_eastern() -> bool:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            now = datetime.now()
        if now.weekday() >= 5:
            return True
        return (now.hour, now.minute) >= (16, 0)

    _company_name_cache: Dict[str, str] = {}
    def _get_company_name(sym: str) -> str:
        s = (sym or "").upper()
        if not s:
            return ""
        if s in _company_name_cache:
            return _company_name_cache[s]
        name = ""
        try:
            import yfinance as yf  # type: ignore
            info = getattr(yf.Ticker(s), "info", None)
            if isinstance(info, dict):
                name = (info.get("longName") or info.get("shortName") or "").strip()
        except Exception:
            name = ""
        if not name:
            name = s
        _company_name_cache[s] = name
        return name

    def update_header_for_symbol(sym: Optional[str], last: Optional[float] = None, prev: Optional[float] = None) -> None:
        s = (sym or "").upper()
        if not s:
            company_var.set("")
            price_var.set("")
            change_var.set("")
            status_var.set("")
            return
        company_name = _get_company_name(s)
        company_var.set(f"{company_name} ({s})")
        if last is None or prev is None:
            # Use provided values only; no cache here to avoid overhead
            pass
        if last is None:
            price_var.set("")
            change_var.set("")
        else:
            try:
                price_var.set(f"{last:,.2f}")
            except Exception:
                price_var.set(str(last))
            if prev is not None and prev != 0:
                try:
                    diff = last - prev
                    pct = (last / prev - 1.0) * 100.0
                except Exception:
                    diff = 0.0
                    pct = 0.0
                sign = "+" if diff > 0 else ""
                try:
                    change_var.set(f"{sign}{diff:,.2f} ({pct:+.2f}%)")
                except Exception:
                    change_var.set(f"{sign}{diff} ({pct:+.2f}%)")
                try:
                    change_label.configure(foreground=("#ef5350" if diff < 0 else ("#4caf50" if diff > 0 else "")))
                except Exception:
                    pass
            else:
                change_var.set("")
        status_var.set("At close" if _is_after_close_eastern() else "")

    def _recalc_header_fonts() -> None:
        try:
            from tkinter import font as tkfont
            heading_font2 = tkfont.nametofont("TkHeadingFont")
            pf = heading_font2.copy(); pf.configure(size=max(10, int(heading_font2.cget("size") * 2)))
            cf = heading_font2.copy(); cf.configure(size=max(8, int(heading_font2.cget("size"))))
            price_label.configure(font=pf)
            change_label.configure(font=cf)
        except Exception:
            pass

    # Radio buttons within the header row on the right side
    try:
        style = ttk.Style()
        style.configure("Mode.TRadiobutton", background="#121212", foreground="#ffffff")
        style.map("Mode.TRadiobutton", background=[("active", "#2a2a2a")], foreground=[("disabled", "#777777")])
    except Exception:
        pass
    header_mode_col = ttk.Frame(header)
    try:
        header_mode_col.grid(row=0, column=1, sticky="ne")
    except Exception:
        header_mode_col.pack(side="right", anchor="ne")
    ttk.Radiobutton(header_mode_col, text="Price over time", value="price", variable=mode_var, command=_on_mode_changed, style="Mode.TRadiobutton").pack(anchor="e")
    ttk.Radiobutton(header_mode_col, text="Performance over time", value="perf", variable=mode_var, command=_on_mode_changed, style="Mode.TRadiobutton").pack(anchor="e")

    # Figure area with dark style
    def apply_matplotlib_style(scale: float) -> None:
        base = 10 * scale
        matplotlib.rcParams.update({
            "font.family": "Atkinson Hyperlegible",
            "axes.facecolor": "#1e1e1e",
            "figure.facecolor": "#121212",
            "savefig.facecolor": "#121212",
            "text.color": "#ffffff",
            "axes.labelcolor": "#ffffff",
            "axes.edgecolor": "#ffffff",
            "xtick.color": "#ffffff",
            "ytick.color": "#ffffff",
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
            # Tick labels: size, color, and x-axis rotation for density
            for lbl in ax.get_xticklabels():
                lbl.set_fontsize(base - 1)
                try:
                    lbl.set_color("#ffffff")
                    lbl.set_rotation(45)
                    lbl.set_ha("right")
                    lbl.set_rotation_mode("anchor")
                except Exception:
                    pass
            for lbl in ax.get_yticklabels():
                lbl.set_fontsize(base - 1)
                try:
                    lbl.set_color("#ffffff")
                except Exception:
                    pass
            try:
                ax.tick_params(axis="both", which="both", labelsize=base - 1, colors="#ffffff")
            except Exception:
                pass
            leg = ax.get_legend()
            if leg is not None:
                for txt in leg.get_texts():
                    txt.set_fontsize(base - 1)
        except Exception:
            pass

    def apply_date_axis_format(target_ax) -> None:
        try:
            mdates = matplotlib.dates
            # Allow many ticks; Concise formatter shortens labels so we can show more
            locator = mdates.AutoDateLocator(minticks=8, maxticks=24)
            formatter = mdates.ConciseDateFormatter(locator)
            target_ax.xaxis.set_major_locator(locator)
            target_ax.xaxis.set_major_formatter(formatter)
        except Exception:
            try:
                # Fallback: default AutoDateLocator if Concise not available
                mdates = matplotlib.dates
                target_ax.xaxis.set_major_locator(mdates.AutoDateLocator())
                target_ax.xaxis.set_major_formatter(mdates.AutoDateFormatter(mdates.AutoDateLocator()))
            except Exception:
                pass

    apply_matplotlib_style(font_scale)

    # Create figure; we'll explicitly set sizes/fonts on scale change
    fig = Figure(figsize=(8, 5), dpi=100, facecolor="#121212", constrained_layout=True)
    ax = fig.add_subplot(111, facecolor="#1e1e1e")
    ax2 = ax.twinx()
    ax.set_title("Price History", color="#ffffff")
    ax.set_xlabel("Date", color="#ffffff")
    ax.set_ylabel("Adj Close", color="#ffffff")
    # Hide secondary y-axis by default; only show when plotting a reference series
    def set_secondary_axis_visible(visible: bool) -> None:
        try:
            ax2.get_yaxis().set_visible(visible)
            try:
                ax2.spines["right"].set_visible(visible)
            except Exception:
                pass
            # Hide label text when not visible
            ax2.set_ylabel("Ref" if visible else "", color="#ffffff")
        except Exception:
            pass
    set_secondary_axis_visible(False)

    canvas = FigureCanvasTkAgg(fig, master=right)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(fill="both", expand=True)

    def on_font_scale_changed(_evt=None):  # noqa: ANN001
        # Prefer reading scale from saved settings; fallback to Tk font size
        nonlocal font_scale
        updated = False
        try:
            fs = float(load_settings().get("font_scale", 1.25))
            if fs > 0:
                font_scale = max(0.6, min(3.0, fs))
                updated = True
        except Exception:
            updated = False
        if not updated:
            try:
                from tkinter import font as tkfont  # lazy import
                f = tkfont.nametofont("TkDefaultFont")
                current_raw = f.cget("size")
                try:
                    current = int(current_raw)
                except Exception:
                    # Some Tk variants return string; fallback parse
                    current = int(str(current_raw).strip())
                if current < 0:
                    current = -current
                font_scale = max(0.6, min(3.0, current / 10.0))
            except Exception:
                pass
        apply_matplotlib_style(font_scale)
        update_axes_fonts(ax, font_scale)
        update_axes_fonts(ax2, font_scale)
        # Use constrained_layout and a manual draw to recompute text layout
        try:
            fig.set_constrained_layout(True)
        except Exception:
            pass
        canvas.draw_idle()

    try:
        parent.bind_all("<<FontScaleChanged>>", on_font_scale_changed)
    except Exception:
        parent.bind("<<FontScaleChanged>>", on_font_scale_changed)
    try:
        parent.bind_all("<<FontScaleChanged>>", lambda _e: _recalc_header_fonts())
    except Exception:
        pass

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
        # Derive a sensible window. Ignore placeholder/zero-value events.
        today_iso = date.today().isoformat()
        if not holding.events:
            # No events: show last 1 year by default
            start_iso = (date.fromisoformat(today_iso) - timedelta(days=365)).isoformat()
            return start_iso, today_iso
        # Filter out events that carry no effect (shares==0, price==0, amount==0)
        meaningful_dates: List[str] = []
        for ev in holding.events:
            try:
                if not ev.date:
                    continue
                has_effect = False
                try:
                    if float(getattr(ev, "shares", 0.0) or 0.0) != 0.0:
                        has_effect = True
                except Exception:
                    pass
                try:
                    if float(getattr(ev, "price", 0.0) or 0.0) != 0.0:
                        has_effect = True
                except Exception:
                    pass
                try:
                    if float(getattr(ev, "amount", 0.0) or 0.0) != 0.0:
                        has_effect = True
                except Exception:
                    pass
                if has_effect:
                    meaningful_dates.append(normalize_date(ev.date))
            except Exception:
                continue
        if not meaningful_dates:
            # Only placeholders present: default to 1y window
            start_iso = (date.fromisoformat(today_iso) - timedelta(days=365)).isoformat()
            return start_iso, today_iso
        start = min(meaningful_dates)
        # End at last event date when position goes flat; else today
        shares = 0.0
        last_flat: Optional[str] = None
        for ev in sorted(holding.events, key=lambda e: normalize_date(e.date)):
            try:
                if ev.type.value == "purchase":
                    shares += float(getattr(ev, "shares", 0.0) or 0.0)
                elif ev.type.value == "sale":
                    shares -= float(getattr(ev, "shares", 0.0) or 0.0)
                if abs(shares) < 1e-9:
                    last_flat = normalize_date(ev.date)
            except Exception:
                continue
        end = last_flat or today_iso
        return start, end

    def compute_holding_return(holding: Holding) -> Optional[float]:
        # simple ROI: (last_close / first_close) - 1 over the holding date range
        sym = holding.symbol.upper()
        if sym in roi_cache:
            return roi_cache[sym]
        start, end = compute_date_range(holding)
        end_plus = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        df = fetch_price_history(sym, start, end_plus, avoid_network=True)
        if df is None or df.empty:
            roi_cache[sym] = None  # type: ignore[assignment]
            return None
        series = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
        try:
            first_price = float(series.dropna().iloc[0])
            last_price = float(series.dropna().iloc[-1])
        except Exception:
            roi_cache[sym] = None  # type: ignore[assignment]
            return None
        if first_price <= 0:
            roi_cache[sym] = None  # type: ignore[assignment]
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

    # Remember last selected symbol and listbox scroll position between sessions
    def refresh_symbols() -> None:
        symbols_list.delete(0, tk.END)
        for sym in sorted_symbols():
            symbols_list.insert(tk.END, sym)
        # select last used symbol if available, else first
        if symbols_list.size() > 0:
            try:
                s = load_settings()
                ch = (s.get("charts", {}) or {})
                last = ch.get("last_symbol")
                idx = 0
                if isinstance(last, str) and last:
                    syms = [symbols_list.get(i) for i in range(symbols_list.size())]
                    if last in syms:
                        idx = syms.index(last)
                symbols_list.selection_clear(0, tk.END)
                symbols_list.selection_set(idx)
                symbols_list.activate(idx)
                # Restore scroll offset if available
                try:
                    first = int(ch.get("listbox_first_index", -1))
                    if first >= 0:
                        symbols_list.see(first)
                except Exception:
                    pass
            except Exception:
                pass
            plot_selected()
        else:
            clear_chart()

    def clear_chart() -> None:
        ax.clear()
        ax2.clear()
        ax.set_facecolor("#1e1e1e")
        ax.set_title("Price History", color="#ffffff")
        ax.set_xlabel("Date", color="#ffffff")
        ax.set_ylabel("Adj Close", color="#ffffff")
        set_secondary_axis_visible(False)
        ax.text(0.5, 0.5, "No symbols", transform=ax.transAxes, ha="center", va="center", color="#cccccc")
        ax.grid(True, color="#333333", linestyle="--", linewidth=0.5)
        apply_date_axis_format(ax)
        for spine in ax.spines.values():
            spine.set_color("#ffffff")
        for spine in ax2.spines.values():
            spine.set_color("#ffffff")
        canvas.draw_idle()

    def find_holding(symbol: str) -> Optional[Holding]:
        for h in portfolio.holdings:
            if h.symbol.upper() == symbol.upper():
                return h
        return None

    def compute_symbol_value_series(holding: Holding, start_iso: str, end_iso: str) -> Optional[pd.Series]:
        sym = holding.symbol
        # First try values_cache which already contains per-day value and shares
        try:
            vdf = read_values_cache(sym)
        except Exception:
            vdf = None
        if vdf is not None and not vdf.empty:
            try:
                v = vdf.copy()
                start_dt = pd.to_datetime(start_iso); end_dt = pd.to_datetime(end_iso)
                if hasattr(v["date"], "dt"):
                    try:
                        v["date"] = v["date"].dt.tz_localize(None)
                    except Exception:
                        pass
                mask = (v["date"] >= start_dt) & (v["date"] <= end_dt)
                v = v.loc[mask]
                v.set_index("date", inplace=True)
                shares = pd.to_numeric(v.get("shares"), errors="coerce")
                values = pd.to_numeric(v.get("value"), errors="coerce")
                series = values.where((shares > 0) & (~values.isna()))
                series = series.fillna(0.0)
                series = series.astype(float)
                series = series.sort_index()
                return series
            except Exception:
                pass
        # Fallback: compute from price history and event shares
        try:
            end_plus = (date.fromisoformat(end_iso) + timedelta(days=1)).isoformat()
            dfp = fetch_price_history(sym, start_iso, end_plus, avoid_network=True)
            if dfp is None or dfp.empty:
                return None
            price_series = dfp["Close"] if "Close" in dfp.columns else (dfp["Adj Close"] if "Adj Close" in dfp.columns else dfp.iloc[:, 0])
            idx = pd.to_datetime(price_series.index, errors="coerce"); idx = idx.tz_localize(None) if hasattr(idx, "tz_localize") else idx
            mask = ~idx.isna(); price_series = pd.Series(price_series.values[mask], index=idx[mask]).dropna()
            # Build shares step function from events
            deltas: Dict[pd.Timestamp, float] = {}
            for ev in holding.events:
                try:
                    if not ev.date:
                        continue
                    d = pd.to_datetime(ev.date)
                    d = d.tz_localize(None) if hasattr(d, "tz_localize") else d
                    delta = 0.0
                    t = getattr(ev, "type", None)
                    if t is not None and getattr(t, "value", str(t)).lower() == "purchase":
                        delta = float(getattr(ev, "shares", 0.0) or 0.0)
                    elif t is not None and getattr(t, "value", str(t)).lower() == "sale":
                        delta = -float(getattr(ev, "shares", 0.0) or 0.0)
                    if delta != 0.0:
                        deltas[d] = deltas.get(d, 0.0) + delta
                except Exception:
                    continue
            combined_index = price_series.index
            if deltas:
                deltas_series = pd.Series(deltas).sort_index()
                combined_index = combined_index.union(deltas_series.index)
                shares_series = deltas_series.reindex(combined_index).fillna(0.0).cumsum()
                shares_on_price = shares_series.reindex(price_series.index, method="ffill").fillna(0.0)
            else:
                shares_on_price = pd.Series(0.0, index=price_series.index)
            value_series = (shares_on_price * price_series).astype(float)
            return value_series
        except Exception:
            return None

    def plot_selected() -> None:
        # Resolve a robust selection; fallback to first item if none
        idx: Optional[int] = None
        try:
            sel = symbols_list.curselection()
            if sel:
                idx = int(sel[0])
        except Exception:
            idx = None
        if idx is None:
            try:
                active_idx = symbols_list.index("active")
                idx = int(active_idx) if isinstance(active_idx, int) else 0
            except Exception:
                idx = None
        if idx is None:
            try:
                if symbols_list.size() > 0:
                    idx = 0
                    symbols_list.selection_clear(0, tk.END)
                    symbols_list.selection_set(idx)
                    symbols_list.activate(idx)
            except Exception:
                idx = None
        if idx is None:
            clear_chart()
            return
        try:
            symbol = symbols_list.get(idx)
        except Exception:
            clear_chart()
            return
        # Persist last selected symbol
        try:
            s = load_settings()
            tab = dict(s.get("charts", {}))
            tab["last_symbol"] = symbol
            s["charts"] = tab
            save_settings(s)
        except Exception:
            pass
        holding = find_holding(symbol)
        if holding is None:
            clear_chart()
            return
        start, end = compute_date_range(holding)
        # yfinance end date is exclusive, add one day
        end_plus = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        # Avoid network during UI interaction; rely on cache, worker warms it
        df = fetch_price_history(symbol, start, end_plus, avoid_network=True)
        ax.clear()
        ax2.clear()
        ax.set_facecolor("#1e1e1e")
        ax.set_title(f"{symbol} Price History", color="#ffffff")
        ax.set_xlabel("Date", color="#ffffff")
        ax.set_ylabel("Adj Close", color="#ffffff")
        set_secondary_axis_visible(False)
        if mode_var.get() == "perf":
            # Selected symbol value within the portfolio over time (in $)
            set_secondary_axis_visible(False)
            val_series = compute_symbol_value_series(holding, start, end)
            ax.clear()
            ax.set_facecolor("#1e1e1e")
            ax.set_title(f"{symbol} Value Over Time", color="#ffffff")
            ax.set_xlabel("Date", color="#ffffff")
            ax.set_ylabel("Value ($)", color="#ffffff")
            if val_series is None or val_series.dropna().empty:
                ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center", color="#cccccc")
            else:
                sdrop = val_series.dropna()
                try:
                    last_val = float(sdrop.iloc[-1]) if len(sdrop) >= 1 else None
                    prev_val = float(sdrop.iloc[-2]) if len(sdrop) >= 2 else None
                except Exception:
                    last_val = None; prev_val = None
                # Update header for selected symbol value
                try:
                    company_name = _get_company_name(symbol)
                    company_var.set(f"{company_name} ({symbol})")
                    if last_val is not None:
                        price_var.set(f"${int(round(last_val)):,}")
                        if prev_val is not None and prev_val != 0:
                            diff = last_val - prev_val
                            pct = (last_val/prev_val - 1.0) * 100.0
                            sign = "+" if diff > 0 else ""
                            change_var.set(f"{sign}${int(round(diff)):,} ({pct:+.2f}%)")
                            try:
                                change_label.configure(foreground=("#ef5350" if diff < 0 else ("#4caf50" if diff > 0 else "")))
                            except Exception:
                                pass
                        else:
                            change_var.set("")
                    else:
                        price_var.set(""); change_var.set("")
                    status_var.set("At close" if _is_after_close_eastern() else "")
                except Exception:
                    pass
                try:
                    ax.plot(sdrop.index, sdrop.values, label=symbol, color="#0a84ff")
                except Exception:
                    pass
            ax.grid(True, color="#333333", linestyle="--", linewidth=0.5)
            apply_date_axis_format(ax)
            for spine in ax.spines.values():
                spine.set_color("#ffffff")
            for spine in ax2.spines.values():
                spine.set_color("#ffffff")
            update_axes_fonts(ax, font_scale)
            update_axes_fonts(ax2, font_scale)
            canvas.draw_idle()
            return

        if df is None or df.empty:
            # Fallback to values cache: derive price = value / shares when shares > 0
            vdf = read_values_cache(symbol)
            if vdf is not None and not vdf.empty:
                try:
                    start_dt = pd.to_datetime(start)
                    end_dt = pd.to_datetime(end)
                    vdf = vdf.copy()
                    # Ensure tz-naive
                    if hasattr(vdf["date"], "dt"):
                        try:
                            vdf["date"] = vdf["date"].dt.tz_localize(None)
                        except Exception:
                            pass
                    mask = (vdf["date"] >= start_dt) & (vdf["date"] <= end_dt)
                    vdf = vdf.loc[mask]
                    vdf.set_index("date", inplace=True)
                    shares = pd.to_numeric(vdf.get("shares"), errors="coerce")
                    values = pd.to_numeric(vdf.get("value"), errors="coerce")
                    price = values.divide(shares.where(shares > 0))
                    price = price.dropna()
                    vprint(f"charts: derived price rows={len(price)} for {symbol}")
                    if not price.empty:
                        # Update header values from derived price
                        try:
                            sdrop = price.dropna()
                            last_p = float(sdrop.iloc[-1]) if len(sdrop) >= 1 else None
                            prev_p = float(sdrop.iloc[-2]) if len(sdrop) >= 2 else None
                        except Exception:
                            last_p = None; prev_p = None
                        update_header_for_symbol(symbol, last_p, prev_p)
                        if mode_var.get() == "perf":
                            # Handled earlier; keep here for structure
                            set_secondary_axis_visible(False)
                        else:
                            ax.set_ylabel("Adj Close", color="#ffffff")
                            ax.plot(price.index, price.values, label=f"{symbol} (derived)", color="#0a84ff")
                            # Reference on secondary axis
                            if ref_enable_var.get() and ref_var.get().strip():
                                ref_sym = ref_var.get().strip().upper()
                                try:
                                    ref_df = fetch_price_history(ref_sym, start, end_plus, avoid_network=True)
                                except Exception:
                                    ref_df = None
                                if ref_df is not None and not ref_df.empty:
                                    ref_series = ref_df["Close"] if "Close" in ref_df.columns else (ref_df["Adj Close"] if "Adj Close" in ref_df.columns else ref_df.iloc[:, 0])
                                    set_secondary_axis_visible(True)
                                    ax2.plot(ref_series.index, ref_series.values, label=ref_sym, color="#ff9f0a")
                        try:
                            lines, labels = ax.get_legend_handles_labels()
                            lines2, labels2 = ax2.get_legend_handles_labels()
                            leg = ax.legend(lines + lines2, labels + labels2, facecolor="#1e1e1e", edgecolor="#333333", labelcolor="#ffffff")
                        except Exception:
                            ax.legend(facecolor="#1e1e1e", edgecolor="#333333", labelcolor="#ffffff")
                    else:
                        ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center", color="#cccccc")
                except Exception:
                    ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center", color="#cccccc")
            else:
                ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center", color="#cccccc")
        else:
            # Handle either Close, Adj Close, or first column
            series = df["Close"] if "Close" in df.columns else (df["Adj Close"] if "Adj Close" in df.columns else df.iloc[:, 0])
            try:
                # Ensure DatetimeIndex and tz-naive for safety
                idx = pd.to_datetime(series.index, errors="coerce")
                idx = idx.tz_localize(None) if hasattr(idx, "tz_localize") else idx
                mask = ~idx.isna()
                series = pd.Series(series.values[mask], index=idx[mask])
            except Exception:
                pass
            # Update header with last/prev from series
            try:
                sdrop = series.dropna()
                last_p = float(sdrop.iloc[-1]) if len(sdrop) >= 1 else None
                prev_p = float(sdrop.iloc[-2]) if len(sdrop) >= 2 else None
            except Exception:
                last_p = None; prev_p = None
            update_header_for_symbol(symbol, last_p, prev_p)

            if mode_var.get() == "perf":
                # Handled earlier; no per-symbol perf plotting here
                set_secondary_axis_visible(False)
            else:
                ax.set_ylabel("Adj Close", color="#ffffff")
                splot = series.dropna()
                if splot.empty:
                    ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center", color="#cccccc")
                else:
                    ax.plot(splot.index, splot.values, label=symbol, color="#0a84ff")
                # Plot reference if enabled on secondary axis
                if ref_enable_var.get() and ref_var.get().strip():
                    ref_sym = ref_var.get().strip().upper()
                    try:
                        ref_df = fetch_price_history(ref_sym, start, end_plus, avoid_network=True)
                    except Exception:
                        ref_df = None
                    if ref_df is not None and not ref_df.empty:
                        ref_series = ref_df["Close"] if "Close" in ref_df.columns else (ref_df["Adj Close"] if "Adj Close" in ref_df.columns else ref_df.iloc[:, 0])
                        try:
                            ridx = pd.to_datetime(ref_series.index, errors="coerce")
                            ridx = ridx.tz_localize(None) if hasattr(ridx, "tz_localize") else ridx
                            rmask = ~ridx.isna()
                            ref_series = pd.Series(ref_series.values[rmask], index=ridx[rmask])
                        except Exception:
                            pass
                        rplot = ref_series.dropna()
                        if not rplot.empty:
                            set_secondary_axis_visible(True)
                            ax2.plot(rplot.index, rplot.values, label=ref_sym, color="#ff9f0a")
                else:
                    set_secondary_axis_visible(False)
            # Legends: combine from both axes
            try:
                lines, labels = ax.get_legend_handles_labels()
                lines2, labels2 = ax2.get_legend_handles_labels()
                leg = ax.legend(lines + lines2, labels + labels2, facecolor="#1e1e1e", edgecolor="#333333", labelcolor="#ffffff")
            except Exception:
                ax.legend(facecolor="#1e1e1e", edgecolor="#333333", labelcolor="#ffffff")
        ax.grid(True, color="#333333", linestyle="--", linewidth=0.5)
        apply_date_axis_format(ax)
        for spine in ax.spines.values():
            spine.set_color("#ffffff")
        for spine in ax2.spines.values():
            spine.set_color("#ffffff")
        update_axes_fonts(ax, font_scale)
        update_axes_fonts(ax2, font_scale)
        canvas.draw_idle()

    def _on_select_listbox(_e=None):  # noqa: ANN001
        plot_selected()
        # Persist listbox scroll position (first visible index)
        try:
            first_visible = symbols_list.nearest(0)
            s = load_settings()
            ch = dict(s.get("charts", {}))
            ch["listbox_first_index"] = int(first_visible)
            s["charts"] = ch
            save_settings(s)
        except Exception:
            pass

    symbols_list.bind("<<ListboxSelect>>", _on_select_listbox)
    sort_combo.bind("<<ComboboxSelected>>", lambda _e: refresh_symbols())

    # Initial load
    apply_matplotlib_style(font_scale)
    # Sync initial font scale with current app scale
    try:
        on_font_scale_changed()
    except Exception:
        pass
    reload_portfolio()

    # Restore left/right pane divider position on first idle after layout
    def _restore_sash() -> None:
        try:
            s = load_settings()
            ch = (s.get("charts", {}) or {})
            ratio = ch.get("sash0_ratio")
            abs_px = ch.get("sash0")
            width = main_pane.winfo_width()
            if width <= 1:
                # Try again shortly if geometry not ready
                try:
                    parent.after(30, _restore_sash)
                except Exception:
                    pass
                return
            if isinstance(ratio, (int, float)) and 0.0 < float(ratio) < 1.0:
                pos = int(float(ratio) * width)
                if pos > 0:
                    main_pane.sashpos(0, pos)
            elif isinstance(abs_px, int) and abs_px > 0:
                # Backward-compat: restore absolute pixel position
                main_pane.sashpos(0, int(abs_px))
        except Exception:
            pass
    try:
        parent.after_idle(_restore_sash)
    except Exception:
        _restore_sash()

    # Expose a hook on the parent so external code can trigger a refresh/plot
    def _ensure_selection_and_plot() -> None:
        try:
            if symbols_list.size() <= 0:
                clear_chart()
                return
            if not symbols_list.curselection():
                # Restore last symbol if present, else first
                try:
                    s = load_settings()
                    last = (s.get("charts", {}) or {}).get("last_symbol")
                    idx = 0
                    if isinstance(last, str) and last:
                        syms = [symbols_list.get(i) for i in range(symbols_list.size())]
                        if last in syms:
                            idx = syms.index(last)
                    symbols_list.selection_clear(0, tk.END)
                    symbols_list.selection_set(idx)
                    symbols_list.activate(idx)
                except Exception:
                    try:
                        symbols_list.selection_clear(0, tk.END)
                        symbols_list.selection_set(0)
                        symbols_list.activate(0)
                    except Exception:
                        pass
            plot_selected()
            try:
                canvas.draw()
            except Exception:
                pass
        except Exception:
            # Keep UI responsive even if something goes wrong
            pass

    def _refresh_and_plot() -> None:
        try:
            reload_portfolio()
        except Exception:
            pass
        try:
            parent.after_idle(_ensure_selection_and_plot)
        except Exception:
            _ensure_selection_and_plot()

    setattr(parent, "_charts_refresh_and_plot", _refresh_and_plot)

    # Global notification when portfolio changes (e.g., symbol added in Portfolio tab)
    try:
        def _on_portfolio_changed(_e=None):  # noqa: ANN001
            try:
                reload_portfolio()
            except Exception:
                pass
            try:
                parent.after_idle(_ensure_selection_and_plot)
            except Exception:
                _ensure_selection_and_plot()
        parent.bind_all("<<PortfolioChanged>>", _on_portfolio_changed)
    except Exception:
        pass


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
    # Persist sash position when requested
    def save_state() -> None:
        try:
            s = load_settings()
            tab = dict(s.get("charts", {}))
            try:
                main_pane = charts_frame.winfo_children()[0]
                if isinstance(main_pane, ttk.PanedWindow):
                    pos = int(main_pane.sashpos(0))
                    total = int(main_pane.winfo_width() or 0)
                    if pos > 0:
                        tab["sash0"] = pos  # keep for backward-compat
                    if pos > 0 and total > 0:
                        # Save as ratio to restore robustly across window sizes
                        tab["sash0_ratio"] = max(0.05, min(0.95, float(pos) / float(total)))
            except Exception:
                pass
            s["charts"] = tab
            save_settings(s)
        except Exception:
            pass
    try:
        charts_frame.bind_all("<<PersistUIState>>", lambda _e: save_state())
    except Exception:
        pass
