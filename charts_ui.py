import tkinter as tk
from tkinter import ttk, messagebox
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
    symbols_list = tk.Listbox(left, height=12)
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
        ax2.set_ylabel("Ref", color="#ffffff")
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

    def plot_selected() -> None:
        try:
            idx = symbols_list.curselection()[0]
        except IndexError:
            clear_chart()
            return
        symbol = symbols_list.get(idx)
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
        ax2.set_ylabel("Ref", color="#ffffff")
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
                        ax.plot(price.index, price.values, label=f"{symbol} (derived)", color="#0a84ff")
                        # Also attempt reference series if enabled
                        if ref_enable_var.get() and ref_var.get().strip():
                            ref_sym = ref_var.get().strip().upper()
                            try:
                                ref_df = fetch_price_history(ref_sym, start, end_plus, avoid_network=True)
                            except Exception:
                                ref_df = None
                            if ref_df is not None and not ref_df.empty:
                                ref_series = ref_df["Close"] if "Close" in ref_df.columns else (ref_df["Adj Close"] if "Adj Close" in ref_df.columns else ref_df.iloc[:, 0])
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
            ax.plot(series.index, series.values, label=symbol, color="#0a84ff")
            # Plot reference if enabled
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
                    ax2.plot(ref_series.index, ref_series.values, label=ref_sym, color="#ff9f0a")
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
    setattr(parent, "_charts_refresh_and_plot", lambda: (reload_portfolio(),))

    # Global notification when portfolio changes (e.g., symbol added in Portfolio tab)
    try:
        parent.bind_all("<<PortfolioChanged>>", lambda _e: reload_portfolio())
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
