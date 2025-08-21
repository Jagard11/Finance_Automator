import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import simpledialog
from typing import Optional
import pandas as pd
from datetime import datetime
import os
import webbrowser

from models import Portfolio, Holding, Event, EventType
import storage
from values_cache import mark_symbol_dirty, read_values_cache
from startup_tasks import get_task_queue
import settings


def build_portfolio_ui(parent: tk.Widget) -> None:
    portfolio: Portfolio = storage.load_portfolio()

    # Track selected holding symbol explicitly
    selected_holding_symbol: Optional[str] = None

    # Track portfolio file for change detection
    portfolio_path = storage.default_portfolio_path()
    last_mtime = os.path.getmtime(portfolio_path) if os.path.exists(portfolio_path) else 0.0

    # Top controls
    top_frame = ttk.Frame(parent)
    top_frame.pack(fill="x", padx=8, pady=8)

    # Removed Portfolio name field from top; editing lives in the Edit Portfolio dialog

    def on_edit_portfolio() -> None:
        win = tk.Toplevel(parent)
        try:
            win.title("Edit Portfolio")
        except Exception:
            pass
        win.transient(parent)
        win.grab_set()

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        # Current file name and rename entry
        current_path = storage.default_portfolio_path()
        data_dir = storage.default_data_dir()
        ttk.Label(body, text="File name (CSV):").grid(row=0, column=0, sticky="w")
        name_var = tk.StringVar(value=os.path.basename(current_path))
        name_entry = ttk.Entry(body, textvariable=name_var, width=40)
        name_entry.grid(row=0, column=1, sticky="w", padx=(6, 0))

        # Buttons row
        btns = ttk.Frame(body)
        btns.grid(row=1, column=0, columnspan=2, sticky="we", pady=(12, 0))

        def do_rename() -> None:
            new_name = (name_var.get() or "").strip()
            if not new_name:
                messagebox.showerror("Invalid name", "Please enter a file name.")
                return
            if os.sep in new_name or (os.altsep and os.altsep in new_name):
                messagebox.showerror("Invalid name", "Please enter a file name without directory separators.")
                return
            if not new_name.lower().endswith(".csv"):
                new_name += ".csv"
            new_path = os.path.join(data_dir, new_name)
            old_path = storage.default_portfolio_path()
            if os.path.abspath(new_path) == os.path.abspath(old_path):
                win.destroy()
                return
            if os.path.exists(new_path):
                messagebox.showerror("Exists", f"{new_name} already exists.")
                return
            try:
                os.rename(old_path, new_path)
            except Exception as exc:
                messagebox.showerror("Rename failed", str(exc))
                return
            try:
                storage.set_default_portfolio_path(new_path)
            except Exception:
                pass
            # Notify app and tabs
            try:
                parent.event_generate("<<PortfoliosListChanged>>", when="tail")
            except Exception:
                pass
            try:
                parent.event_generate("<<PortfolioChanged>>", when="tail")
            except Exception:
                pass
            win.destroy()

        def do_delete() -> None:
            old_path = storage.default_portfolio_path()
            fname = os.path.basename(old_path)
            if not messagebox.askyesno("Delete Portfolio", f"Are you sure you want to delete {fname}? This cannot be undone."):
                return
            try:
                os.remove(old_path)
            except Exception as exc:
                messagebox.showerror("Delete failed", str(exc))
                return
            # Choose next active portfolio if any
            new_default = None
            try:
                paths = [p for p in storage.list_portfolio_paths() if os.path.exists(p)]
                if paths:
                    new_default = paths[0]
            except Exception:
                new_default = None
            try:
                if new_default:
                    storage.set_default_portfolio_path(new_default)
            except Exception:
                pass
            try:
                parent.event_generate("<<PortfoliosListChanged>>", when="tail")
            except Exception:
                pass
            try:
                parent.event_generate("<<PortfolioChanged>>", when="tail")
            except Exception:
                pass
            win.destroy()

        ttk.Button(btns, text="Save Name", command=do_rename).pack(side="left")
        tk.Button(btns, text="DELETE", command=do_delete, fg="#ffffff", bg="#e74c3c", activebackground="#c0392b").pack(side="right")

    # Edit Portfolio button will be placed at bottom-right per spec; keep a reference
    edit_portfolio_command = on_edit_portfolio

    # Removed file switcher and local Switch button; use global selector in app header

    # Per-symbol Dividend Reinvest toggle is shown in the header for the selected symbol (right column)

    # Removed local refresh dividends button to reduce redundancy

    # Split panes: holdings list and events
    main_pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
    main_pane.pack(fill="both", expand=True, padx=8, pady=8)

    # Holdings list
    left_frame = ttk.Frame(main_pane)
    main_pane.add(left_frame, weight=1)

    ttk.Label(left_frame, text="Holdings").pack(anchor="w")

    holdings_list = tk.Listbox(left_frame, height=12)
    holdings_list.pack(fill="both", expand=True)

    NEW_SYMBOL_LABEL = "--- New Symbol ---"

    # Events section
    right_frame = ttk.Frame(main_pane)
    main_pane.add(right_frame, weight=3)

    # Prevent the left pane (symbol shelf) from collapsing fully
    try:
        main_pane.paneconfigure(left_frame, minsize=120)
    except Exception:
        pass

    # Header area above events split into left/right columns
    header = ttk.Frame(right_frame)
    header.pack(fill="x", pady=(0, 8))
    left_header = ttk.Frame(header)
    left_header.pack(side="left", fill="x", expand=True)
    right_header = ttk.Frame(header)
    right_header.pack(side="right", anchor="e")

    company_var = tk.StringVar(value="")
    company_label = ttk.Label(left_header, textvariable=company_var)
    company_label.pack(anchor="w")

    price_row = ttk.Frame(left_header)
    price_row.pack(anchor="w")

    price_var = tk.StringVar(value="")
    change_var = tk.StringVar(value="")
    # Fonts for price and change (large and half-size-ish)
    try:
        from tkinter import font as tkfont  # local import to avoid top-level dependency
        heading_font = tkfont.nametofont("TkHeadingFont")
        price_font = heading_font.copy()
        price_font.configure(size=max(10, int(heading_font.cget("size") * 2)))
        change_font = heading_font.copy()
        change_font.configure(size=max(8, int(heading_font.cget("size"))))
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
    status_label = ttk.Label(left_header, textvariable=status_var)
    status_label.pack(anchor="w")

    link_label = ttk.Label(left_header, text="View on Yahoo Finance", foreground="#0a84ff", cursor="hand2")
    link_label.pack(anchor="w")

    def _open_symbol_link(sym: str) -> None:
        try:
            if sym:
                webbrowser.open_new_tab(f"https://finance.yahoo.com/quote/{sym}")
        except Exception:
            pass

    link_label.bind("<Button-1>", lambda _e: _open_symbol_link(selected_holding_symbol or ""))

    def _is_after_close_eastern() -> bool:
        # Show "At close" after 4:00 PM ET and on weekends
        try:
            from zoneinfo import ZoneInfo  # Python 3.9+
            now = datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            now = datetime.now()
        if now.weekday() >= 5:  # Saturday/Sunday
            return True
        return (now.hour, now.minute) >= (16, 0)

    _company_name_cache = {}

    def _get_company_name(sym: str) -> str:
        s = (sym or "").upper()
        if not s:
            return ""
        if s in _company_name_cache:
            return _company_name_cache[s]
        name = ""
        try:
            import yfinance as yf
            info = getattr(yf.Ticker(s), "info", None)
            if isinstance(info, dict):
                name = (info.get("longName") or info.get("shortName") or "").strip()
        except Exception:
            name = ""
        if not name:
            name = s
        _company_name_cache[s] = name
        return name

    # Per-symbol Dividend Reinvest preference stored in settings by portfolio file
    reinvest_symbol_var = tk.BooleanVar(value=True)

    def _get_reinvest_pref_for_symbol(sym: str) -> bool:
        try:
            s = settings.load_settings()
            tab = s.get("portfolio", {})
            by_file = tab.get("reinvest_by_file", {})
            path = storage.default_portfolio_path()
            prefs = by_file.get(path) or by_file.get(os.path.basename(path)) or {}
            val = prefs.get(sym.upper()) if isinstance(prefs, dict) else None
            return True if val is None else bool(val)
        except Exception:
            return True

    def _set_reinvest_pref_for_symbol(sym: str, enabled: bool) -> None:
        try:
            s = settings.load_settings()
            tab = dict(s.get("portfolio", {}))
            by_file = dict(tab.get("reinvest_by_file", {}))
            path = storage.default_portfolio_path()
            prefs = dict(by_file.get(path) or by_file.get(os.path.basename(path)) or {})
            prefs[sym.upper()] = bool(enabled)
            by_file[path] = prefs
            by_file[os.path.basename(path)] = prefs
            tab["reinvest_by_file"] = by_file
            s["portfolio"] = tab
            settings.save_settings(s)
        except Exception:
            pass

    def on_toggle_reinvest_symbol() -> None:
        sym = selected_holding_symbol
        if not sym:
            return
        _set_reinvest_pref_for_symbol(sym, bool(reinvest_symbol_var.get()))
        # Ask background worker to re-ingest dividends so changes take effect
        try:
            q = get_task_queue()
            if q is not None:
                q.put_nowait({"type": "ingest_dividends", "path": storage.default_portfolio_path()})
        except Exception:
            pass

    ttk.Checkbutton(right_header, text="Dividend Reinvest", variable=reinvest_symbol_var, command=on_toggle_reinvest_symbol).pack(anchor="e")

    def update_header_for_symbol(sym: Optional[str], last: Optional[float] = None, prev: Optional[float] = None) -> None:
        s = (sym or "").upper()
        if not s:
            company_var.set("")
            price_var.set("")
            change_var.set("")
            status_var.set("")
            try:
                reinvest_symbol_var.set(True)
            except Exception:
                pass
            return
        company_name = _get_company_name(s)
        company_var.set(f"{company_name} ({s})")
        # Update per-symbol reinvest toggle from settings (default True)
        try:
            reinvest_symbol_var.set(_get_reinvest_pref_for_symbol(s))
        except Exception:
            pass
        # If prices not provided, read from cache helpers
        if last is None or prev is None:
            lp, pp = _get_last_and_prev_price(s)
            if last is None:
                last = lp
            if prev is None:
                prev = pp
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
                # Colorize by sign
                if diff < 0:
                    try:
                        change_label.configure(foreground="#ef5350")  # red
                    except Exception:
                        pass
                elif diff > 0:
                    try:
                        change_label.configure(foreground="#4caf50")  # green
                    except Exception:
                        pass
                else:
                    try:
                        change_label.configure(foreground="")
                    except Exception:
                        pass
            else:
                change_var.set("")
        status_var.set("At close" if _is_after_close_eastern() else "")

    # Recalculate fonts on global scale change
    def _recalc_header_fonts() -> None:
        try:
            from tkinter import font as tkfont
            heading_font2 = tkfont.nametofont("TkHeadingFont")
            pf = heading_font2.copy()
            pf.configure(size=max(10, int(heading_font2.cget("size") * 2)))
            cf = heading_font2.copy()
            cf.configure(size=max(8, int(heading_font2.cget("size"))))
            price_label.configure(font=pf)
            change_label.configure(font=cf)
        except Exception:
            pass

    try:
        parent.bind("<<FontScaleChanged>>", lambda _e: _recalc_header_fonts())
    except Exception:
        pass

    ttk.Label(right_frame, text="Events").pack(anchor="w")

    # Sortable table for events
    columns = ("symbol", "date", "type", "shares", "price", "amount", "total_gain", "total_gain_pct", "day_gain", "day_gain_pct", "note")
    # Add horizontal scrollbar
    xscroll = ttk.Scrollbar(right_frame, orient="horizontal")
    xscroll.pack(side="bottom", fill="x")
    events_tree = ttk.Treeview(right_frame, columns=columns, show="headings", selectmode="browse", xscrollcommand=xscroll.set)
    events_tree.pack(fill="both", expand=True)
    xscroll.config(command=events_tree.xview)

    events_tree.heading("symbol", text="Symbol")
    events_tree.heading("date", text="Date")
    events_tree.heading("type", text="Type")
    events_tree.heading("shares", text="Shares")
    events_tree.heading("price", text="Price")
    events_tree.heading("amount", text="Cost")
    events_tree.heading("total_gain", text="Total $")
    events_tree.heading("total_gain_pct", text="Total %")
    events_tree.heading("day_gain", text="Day $")
    events_tree.heading("day_gain_pct", text="Day %")
    events_tree.heading("note", text="Note")

    # Initial column widths (will be auto-adjusted on font scale changes)
    events_tree.column("symbol", width=100, anchor="w")
    events_tree.column("date", width=120, anchor="w")
    events_tree.column("type", width=110, anchor="w")
    events_tree.column("shares", width=90, anchor="e")
    events_tree.column("price", width=90, anchor="e")
    events_tree.column("amount", width=90, anchor="e")
    events_tree.column("note", width=300, anchor="w")
    events_tree.column("total_gain", width=110, anchor="e")
    events_tree.column("total_gain_pct", width=90, anchor="e")
    events_tree.column("day_gain", width=110, anchor="e")
    events_tree.column("day_gain_pct", width=90, anchor="e")

    # Excel-like resizing: prevent auto-stretching other columns and enforce a tiny min width
    try:
        for col_id in columns:
            events_tree.column(col_id, stretch=False, minwidth=2)
    except Exception:
        pass

    # Placeholders for new row prompts and draft buffer for new entry
    placeholder_symbol = "Enter symbol"
    placeholder_date = "YYYY-MM-DD"
    placeholder_type = "purchase"
    placeholder_shares = "shares"
    placeholder_price = "price"
    placeholder_amount = "cost"
    placeholder_note = "--- New Entry ---"

    new_entry_values = {
        "symbol": "",
        "date": "",
        "type": placeholder_type,
        "shares": "",
        "price": "",
        "amount": "",
        "note": "",
    }

    def auto_size_columns() -> None:
        try:
            from tkinter import font as tkfont
            f = tkfont.nametofont("TkDefaultFont")
            # Estimate width by character units times a factor
            def ch(n: int) -> int:
                return int(n * max(6, f.measure("0")) / 1.6)
            base_widths = {
                "symbol": ch(10),
                "date": ch(12),
                "type": ch(12),
                "shares": ch(10),
                "price": ch(10),
                "amount": ch(10),
                "total_gain": ch(12),
                "total_gain_pct": ch(10),
                "day_gain": ch(12),
                "day_gain_pct": ch(10),
                "note": ch(40),
            }
            # Ensure minimum width so header text is never truncated
            for col_id, base_w in base_widths.items():
                try:
                    header_txt = events_tree.heading(col_id, option="text")
                    header_w = f.measure(str(header_txt)) + 24
                except Exception:
                    header_w = 0
                events_tree.column(col_id, width=max(base_w, header_w))
        except Exception:
            pass

    parent.bind("<<FontScaleChanged>>", lambda _e: auto_size_columns())

    # Apply saved layout (sash position and column widths)
    def apply_saved_layout() -> None:
        try:
            s = settings.load_settings()
            tab = s.get("portfolio", {})
            # Sash position
            try:
                sash = int(tab.get("sash0", 0))
                # Clamp to the pane minimum so it never restores as fully closed
                min_left = 120
                if sash <= 0:
                    sash = min_left
                parent.after(0, lambda s=sash: main_pane.sashpos(0, max(min_left, s)))
            except Exception:
                pass
            # Column widths
            try:
                saved_cols = tab.get("columns", {})
                if isinstance(saved_cols, dict):
                    for col_id in columns:
                        try:
                            w = int(saved_cols.get(col_id, 0))
                            if w > 0:
                                # Clamp to prevent hidden columns
                                events_tree.column(col_id, width=max(2, w))
                        except Exception:
                            continue
            except Exception:
                pass
        except Exception:
            pass

    # Persist and restore selected symbol per portfolio file
    def apply_saved_selection() -> None:
        nonlocal selected_holding_symbol
        try:
            s = settings.load_settings()
            tab = s.get("portfolio", {})
            by_file = tab.get("selected_symbol_by_file", {})
            path = storage.default_portfolio_path()
            sym = (by_file.get(path) or by_file.get(os.path.basename(path)) or "") if isinstance(by_file, dict) else ""
            if sym:
                # Try to select this symbol in the list
                try:
                    items = [holdings_list.get(i) for i in range(holdings_list.size())]
                    if sym in items:
                        idx = items.index(sym)
                        holdings_list.selection_clear(0, tk.END)
                        holdings_list.selection_set(idx)
                        holdings_list.activate(idx)
                        selected_holding_symbol = sym
                        refresh_events_list()
                except Exception:
                    pass
        except Exception:
            pass

    def save_selected_symbol() -> None:
        try:
            sym = selected_holding_symbol
            if not sym:
                return
            s = settings.load_settings()
            tab = dict(s.get("portfolio", {}))
            by_file = dict(tab.get("selected_symbol_by_file", {}))
            path = storage.default_portfolio_path()
            by_file[path] = sym
            by_file[os.path.basename(path)] = sym
            tab["selected_symbol_by_file"] = by_file
            s["portfolio"] = tab
            settings.save_settings(s)
        except Exception:
            pass

    # Persist layout on request
    def save_state() -> None:
        try:
            s = settings.load_settings()
            tab = dict(s.get("portfolio", {}))
            try:
                pos = int(main_pane.sashpos(0))
                # Enforce the same minimum used for the pane so we don't persist a collapsed state
                if pos < 120:
                    pos = 120
                tab["sash0"] = pos
            except Exception:
                pass
            col_widths = {}
            for col_id in columns:
                try:
                    col_widths[col_id] = int(events_tree.column(col_id, "width"))
                except Exception:
                    continue
            tab["columns"] = col_widths
            # Selected symbol per portfolio
            try:
                sym = selected_holding_symbol
                if sym:
                    by_file = dict(tab.get("selected_symbol_by_file", {}))
                    path = storage.default_portfolio_path()
                    by_file[path] = sym
                    by_file[os.path.basename(path)] = sym
                    tab["selected_symbol_by_file"] = by_file
                
            except Exception:
                pass
            s["portfolio"] = tab
            settings.save_settings(s)
        except Exception:
            pass

    try:
        parent.bind_all("<<PersistUIState>>", lambda _e: save_state())
    except Exception:
        pass

    # Helpers: date parsing/formatting and sorting
    def parse_date_for_sorting(date_str: str) -> tuple[int, int, int]:
        s = (date_str or "").strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                dt = datetime.strptime(s, fmt)
                return (dt.year, dt.month, dt.day)
            except ValueError:
                continue
        return (9999, 12, 31)

    def format_date_for_display(date_str: str) -> str:
        s = (date_str or "").strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return s

    # Sorting state
    events_sort_column = "date"
    events_sort_reverse = False

    def get_selected_holding() -> Optional[Holding]:
        nonlocal selected_holding_symbol
        try:
            idx = holdings_list.curselection()[0]
            symbol = holdings_list.get(idx)
            selected_holding_symbol = symbol
        except IndexError:
            symbol = selected_holding_symbol
        if not symbol or symbol == NEW_SYMBOL_LABEL:
            return None
        return portfolio.get_holding(symbol)

    def get_field_value(ev: Event, col: str, symbol: str):
        if col == "symbol":
            return symbol
        if col == "date":
            return parse_date_for_sorting(ev.date)
        if col == "type":
            return ev.type.value
        if col == "shares":
            return float(ev.shares)
        if col == "price":
            return float(ev.price)
        if col == "amount":
            # sort by computed cost instead of raw amount
            try:
                if ev.type in (EventType.PURCHASE, EventType.SALE):
                    return float(ev.shares or 0.0) * float(ev.price or 0.0)
            except Exception:
                pass
            return float(ev.amount)
        if col == "note":
            return (ev.note or "").lower()
        return ""

    def build_sort_tuple(ev: Event, symbol: str, original_idx: int):
        ordered_cols = [events_sort_column] + [c for c in columns if c != events_sort_column]
        values = tuple(get_field_value(ev, c, symbol) for c in ordered_cols)
        return values + (original_idx,)

    def refresh_holdings_list() -> None:
        nonlocal selected_holding_symbol
        current_symbol = selected_holding_symbol
        holdings_list.delete(0, tk.END)
        symbols = [h.symbol for h in sorted(portfolio.holdings, key=lambda h: h.symbol)]
        for sym in symbols:
            holdings_list.insert(tk.END, sym)
        # Append new symbol row
        holdings_list.insert(tk.END, NEW_SYMBOL_LABEL)
        if symbols:
            if current_symbol in symbols:
                idx = symbols.index(current_symbol)
            else:
                idx = 0
                current_symbol = symbols[0]
            holdings_list.selection_clear(0, tk.END)
            holdings_list.selection_set(idx)
            holdings_list.activate(idx)
            selected_holding_symbol = current_symbol
        refresh_events_list()

    # Inline cell editing state
    edit_widget: Optional[tk.Widget] = None
    edit_item: Optional[str] = None
    edit_col: Optional[str] = None

    def end_edit(save: bool) -> None:
        nonlocal edit_widget, edit_item, edit_col, new_entry_values
        if edit_widget is None:
            return
        widget = edit_widget
        item = edit_item
        col = edit_col
        value = None
        if save and isinstance(widget, (tk.Entry, ttk.Entry)):
            value = widget.get()
        elif save and isinstance(widget, ttk.Combobox):
            value = widget.get()
        widget.destroy()
        edit_widget = None
        edit_item = None
        edit_col = None

        if not save or item is None or col is None:
            return

        def parse_event_type(s: str) -> EventType:
            s_norm = (s or "").strip().lower()
            for et in [EventType.PURCHASE, EventType.SALE, EventType.DIVIDEND, EventType.CASH_DEPOSIT, EventType.CASH_WITHDRAWAL]:
                if s_norm == et.value:
                    return et
            aliases = {
                "buy": EventType.PURCHASE,
                "sell": EventType.SALE,
                "div": EventType.DIVIDEND,
                "deposit": EventType.CASH_DEPOSIT,
                "withdraw": EventType.CASH_WITHDRAWAL,
                "withdrawal": EventType.CASH_WITHDRAWAL,
            }
            return aliases.get(s_norm, EventType.PURCHASE)

        # Handle new row: update draft values and commit only when symbol + another field exist
        if item == "new":
            # Update draft
            if col == "symbol":
                new_entry_values["symbol"] = (value or "").strip().upper().replace(" ", "")
            elif col == "date":
                v = (value or "").strip()
                new_entry_values["date"] = "" if v == placeholder_date else v
            elif col == "type":
                v = (value or "").strip().lower()
                new_entry_values["type"] = placeholder_type if not v else v
            elif col == "shares":
                v = (value or "").strip()
                new_entry_values["shares"] = "" if v == placeholder_shares else v
            elif col == "price":
                v = (value or "").strip()
                new_entry_values["price"] = "" if v == placeholder_price else v
            elif col == "amount":
                v = (value or "").strip()
                new_entry_values["amount"] = "" if v == placeholder_amount else v
            elif col == "note":
                v = (value or "").strip()
                new_entry_values["note"] = "" if v == placeholder_note else v

            # Update display for the new row (default symbol to the currently selected holding if empty)
            events_tree.item("new", values=(
                new_entry_values["symbol"] or (selected_holding_symbol or placeholder_symbol),
                new_entry_values["date"] or placeholder_date,
                new_entry_values["type"] or placeholder_type,
                new_entry_values["shares"] or placeholder_shares,
                new_entry_values["price"] or placeholder_price,
                new_entry_values["amount"] or placeholder_amount,
                new_entry_values["note"] or placeholder_note,
            ))

            has_other = bool(new_entry_values["date"] or new_entry_values["shares"] or new_entry_values["price"] or new_entry_values["amount"] or new_entry_values["note"] or (new_entry_values["type"] and new_entry_values["type"] != placeholder_type))
            # Allow commit when either a symbol is typed OR a holding is currently selected
            if has_other and (new_entry_values["symbol"] or get_selected_holding() is not None):
                # Commit event to the entered or existing holding
                target = portfolio.ensure_holding(new_entry_values["symbol"]) if new_entry_values["symbol"] else get_selected_holding()
                if target is None:
                    messagebox.showwarning("Missing symbol", "Enter a Symbol in the new row first.")
                    return
                # Build event
                try:
                    shares_v = float(new_entry_values["shares"]) if new_entry_values["shares"] else 0.0
                except ValueError:
                    shares_v = 0.0
                try:
                    price_v = float(new_entry_values["price"]) if new_entry_values["price"] else 0.0
                except ValueError:
                    price_v = 0.0
                try:
                    amount_v = float(new_entry_values["amount"]) if new_entry_values["amount"] else 0.0
                except ValueError:
                    amount_v = 0.0

                ev = Event(
                    date=new_entry_values["date"],
                    type=parse_event_type(new_entry_values["type"] or placeholder_type),
                    shares=shares_v,
                    price=price_v,
                    amount=amount_v,
                    note=new_entry_values["note"],
                )
                target.events.append(ev)
                mark_symbol_dirty(target.symbol)
                try:
                    storage.save_portfolio(portfolio)
                except Exception:
                    pass
                try:
                    q = get_task_queue()
                    if q is not None:
                        q.put_nowait({"type": "prefetch_symbol", "symbol": target.symbol})
                        q.put_nowait({"type": "warm_values"})
                except Exception:
                    pass

                # Reset draft and refresh
                new_entry_values = {
                    "symbol": "",
                    "date": "",
                    "type": placeholder_type,
                    "shares": "",
                    "price": "",
                    "amount": "",
                    "note": "",
                }
                refresh_holdings_list()
                try:
                    parent.event_generate("<<PortfolioChanged>>", when="tail")
                except Exception:
                    pass
            return

        # Existing row update or move
        # Determine current holding and event index from item id
        if ":" in item:
            item_symbol, idx_str = item.split(":", 1)
            try:
                idx = int(idx_str)
            except ValueError:
                return
            current_holding = portfolio.get_holding(item_symbol)
        else:
            current_holding = get_selected_holding()
            try:
                idx = int(item)
            except ValueError:
                return
        if current_holding is None or not (0 <= idx < len(current_holding.events)):
            return
        ev = current_holding.events[idx]

        def parse_float_or_zero(s: Optional[str]) -> float:
            try:
                return float(s or 0)
            except ValueError:
                return 0.0

        if col == "symbol":
            new_symbol = (value or "").strip().upper()
            if not new_symbol or new_symbol == current_holding.symbol:
                return
            del current_holding.events[idx]
            target_holding = portfolio.ensure_holding(new_symbol)
            target_holding.events.append(ev)
            mark_symbol_dirty(new_symbol)
            mark_symbol_dirty(current_holding.symbol)
            try:
                q = get_task_queue()
                if q is not None:
                    q.put_nowait({"type": "prefetch_symbol", "symbol": new_symbol})
                    q.put_nowait({"type": "warm_values"})
            except Exception:
                pass
            refresh_holdings_list()
            try:
                storage.save_portfolio(portfolio)
            except Exception:
                pass
            try:
                parent.event_generate("<<PortfolioChanged>>", when="tail")
            except Exception:
                pass
            return

        # Mark dirty for any edit
        mark_symbol_dirty(current_holding.symbol)

        if col == "date":
            ev.date = (value or "").strip()
        elif col == "type":
            ev.type = parse_event_type(value)
        elif col == "shares":
            ev.shares = parse_float_or_zero(value)
        elif col == "price":
            ev.price = parse_float_or_zero(value)
        elif col == "amount":
            # amount is auto-calculated as cost for purchase/sale; keep readonly in UI
            pass
        elif col == "note":
            ev.note = value or ""
        refresh_events_list()
        try:
            q = get_task_queue()
            if q is not None:
                q.put_nowait({"type": "warm_values"})
        except Exception:
            pass
        try:
            storage.save_portfolio(portfolio)
        except Exception:
            pass

    def begin_edit(item: str, col_id: str) -> None:
        nonlocal edit_widget, edit_item, edit_col
        # Map tree column id like #1 -> column name
        try:
            col_index = int(col_id.replace("#", "")) - 1
        except ValueError:
            return
        if not (0 <= col_index < len(columns)):
            return
        col = columns[col_index]
        # Place an editor over the cell
        bbox = events_tree.bbox(item, col_id)
        if not bbox:
            return
        x, y, w, h = bbox
        current_value = ""
        vals = events_tree.item(item, "values")
        if vals and 0 <= col_index < len(vals):
            current_value = vals[col_index]

        if col == "type":
            edit = ttk.Combobox(events_tree, state="normal", values=[
                EventType.PURCHASE.value,
                EventType.SALE.value,
                EventType.DIVIDEND.value,
                EventType.CASH_DEPOSIT.value,
                EventType.CASH_WITHDRAWAL.value,
            ])
            edit.set(current_value)
        else:
            edit = ttk.Entry(events_tree)
            edit.insert(0, current_value)

        edit.place(x=x, y=y, width=w, height=h)
        edit.focus_set()

        def on_return(_evt=None):  # noqa: ANN001
            end_edit(True)

        def on_escape(_evt=None):  # noqa: ANN001
            end_edit(False)

        edit.bind("<Return>", on_return)
        edit.bind("<Escape>", on_escape)
        edit.bind("<FocusOut>", lambda _e: end_edit(True))

        edit_widget = edit
        edit_item = item
        edit_col = col

    def on_tree_double_click(evt) -> None:  # noqa: ANN001
        region = events_tree.identify("region", evt.x, evt.y)
        if region != "cell":
            return
        item = events_tree.identify_row(evt.y)
        col = events_tree.identify_column(evt.x)
        if not item or not col:
            return
        begin_edit(item, col)

    # Column header click sorting
    def on_sort(col: str) -> None:
        nonlocal events_sort_column, events_sort_reverse
        if events_sort_column == col:
            events_sort_reverse = not events_sort_reverse
        else:
            events_sort_column = col
            events_sort_reverse = False
        refresh_events_list()

    for col in columns:
        events_tree.heading(col, text=events_tree.heading(col, option="text"), command=lambda c=col: on_sort(c))

    def _format_price(p: float) -> str:
        try:
            return f"${p:,.4f}".rstrip("0").rstrip(".")
        except Exception:
            return f"${p}"

    def _get_last_and_prev_price(symbol: str) -> tuple[float | None, float | None]:
        # Authoritative source: values_cache; if missing/incomplete, mark dirty and warm.
        last: float | None = None
        prev: float | None = None
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
                    last = (float(last_row["value"]) / s_last) if s_last else None
                if len(vdf) >= 2:
                    prev_row = vdf.iloc[-2]
                    s_prev = float(prev_row["shares"]) if float(prev_row["shares"]) > 0 else None
                    prev = (float(prev_row["value"]) / s_prev) if s_prev else None
        except Exception:
            last = last
            prev = prev
        if last is None or prev is None:
            try:
                mark_symbol_dirty(symbol)
                q = get_task_queue()
                if q is not None:
                    q.put_nowait({"type": "warm_values"})
                try:
                    parent.event_generate("<<PortfolioChanged>>", when="tail")
                except Exception:
                    pass
            except Exception:
                pass
        return last, prev

    def refresh_events_list() -> None:
        # Remember selection
        prev_selected = None
        sel = events_tree.selection()
        if sel:
            prev_selected = sel[0]
        # Clear
        for iid in events_tree.get_children():
            events_tree.delete(iid)

        # Build a view of events for selected holding only (to keep changes minimal)
        holding = get_selected_holding()
        if holding is not None:
            enumerated = list(enumerate(holding.events))
            last_price, prev_price = _get_last_and_prev_price(holding.symbol)
            # Update header with latest price info for the selected holding
            update_header_for_symbol(holding.symbol, last_price, prev_price)
            enumerated.sort(key=lambda pair: build_sort_tuple(pair[1], holding.symbol, pair[0]), reverse=events_sort_reverse)
            for original_idx, e in enumerated:
                iid = f"{holding.symbol}:{original_idx}"
                # Compute cost (non-writable): price * shares when type is purchase/sale
                try:
                    if e.type in (EventType.PURCHASE, EventType.SALE):
                        cost_val = float(e.shares or 0.0) * float(e.price or 0.0)
                        cost = f"${cost_val:,.2f}"
                    else:
                        cost = f"{e.amount:g}" if e.amount else ""
                except Exception:
                    cost = f"{e.amount:g}" if e.amount else ""

                # Price formatting
                price_txt = _format_price(float(e.price)) if e.price else ""

                # Gains
                total_gain_txt = ""
                total_gain_pct_txt = ""
                day_gain_txt = ""
                day_gain_pct_txt = ""
                try:
                    if last_price is not None and e.type in (EventType.PURCHASE, EventType.SALE):
                        # Average entry price per event row isn't precise; we use row price
                        if float(e.price or 0) > 0 and float(e.shares or 0) != 0:
                            shares_signed = float(e.shares)
                            if e.type == EventType.SALE:
                                shares_signed = -shares_signed
                            entry_val = float(e.price) * shares_signed
                            current_val = last_price * shares_signed
                            total_gain = current_val - entry_val
                            total_gain_txt = f"${total_gain:,.0f}"
                            if entry_val != 0:
                                total_gain_pct_txt = f"{(current_val/entry_val - 1.0)*100:.2f}%"
                    if last_price is not None and prev_price is not None and float(e.shares or 0) != 0 and e.type in (EventType.PURCHASE, EventType.SALE):
                        shares_signed = float(e.shares)
                        if e.type == EventType.SALE:
                            shares_signed = -shares_signed
                        day_gain = (last_price - prev_price) * shares_signed
                        day_gain_txt = f"${day_gain:,.0f}"
                        if prev_price != 0:
                            day_gain_pct_txt = f"{((last_price/prev_price)-1.0)*100:.2f}%"
                except Exception:
                    pass

                events_tree.insert("", "end", iid=iid, values=(
                    holding.symbol,
                    format_date_for_display(e.date),
                    e.type.value,
                    f"{e.shares:g}" if e.shares else "",
                    price_txt,
                    cost,
                    total_gain_txt,
                    total_gain_pct_txt,
                    day_gain_txt,
                    day_gain_pct_txt,
                    e.note,
                ))
        else:
            update_header_for_symbol(None)

        # Always include a new event row for quick entry with placeholders or draft values
        events_tree.insert("", "end", iid="new", values=(
            new_entry_values["symbol"] or (selected_holding_symbol or placeholder_symbol),
            new_entry_values["date"] or placeholder_date,
            new_entry_values["type"] or placeholder_type,
            new_entry_values["shares"] or placeholder_shares,
            (new_entry_values["price"] or placeholder_price),
            (new_entry_values["amount"] or placeholder_amount),
            "", "", "", "",
            (new_entry_values["note"] or placeholder_note),
        ))
        # Restore selection if possible
        if prev_selected and prev_selected in events_tree.get_children():
            events_tree.selection_set(prev_selected)

    def on_select_holding(_evt=None) -> None:  # noqa: ANN001
        refresh_events_list()
        # Update selected symbol tracker and persist
        try:
            _ = get_selected_holding()
            save_selected_symbol()
        except Exception:
            pass

    def on_delete_key(_evt=None) -> None:  # noqa: ANN001
        # Delete selected event
        sel = events_tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid == "new":
            return
        # Parse iid
        if ":" not in iid:
            return
        sym, idx_str = iid.split(":", 1)
        holding = portfolio.get_holding(sym)
        if holding is None:
            return
        try:
            idx = int(idx_str)
        except ValueError:
            return
        if 0 <= idx < len(holding.events):
            del holding.events[idx]
            mark_symbol_dirty(sym)
            refresh_events_list()
            try:
                q = get_task_queue()
                if q is not None:
                    q.put_nowait({"type": "warm_values"})
            except Exception:
                pass
            try:
                storage.save_portfolio(portfolio)
            except Exception:
                pass
            try:
                parent.event_generate("<<PortfolioChanged>>", when="tail")
            except Exception:
                pass

    def on_holdings_double_click(evt) -> None:  # noqa: ANN001
        nonlocal selected_holding_symbol
        # Double-clicking the "--- New Symbol ---" row prompts for a new symbol
        index = holdings_list.nearest(evt.y)
        try:
            value = holdings_list.get(index)
        except Exception:
            return
        if value != NEW_SYMBOL_LABEL:
            return
        sym = simpledialog.askstring("Add Symbol", "Enter symbol (e.g., AAPL):", parent=parent)
        if not sym:
            return
        sym = sym.strip().upper().replace(" ", "")
        if not sym:
            return
        if portfolio.get_holding(sym):
            messagebox.showinfo("Already exists", f"{sym} is already in the portfolio.")
            return
        # Ensure holding exists and persist a placeholder 0-share event so other tabs/processes see it
        holding = portfolio.ensure_holding(sym)
        try:
            placeholder_date = datetime.today().date().isoformat()
        except Exception:
            placeholder_date = ""
        try:
            holding.events.append(Event(date=placeholder_date, type=EventType.PURCHASE, shares=0.0, price=0.0, amount=0.0, note=""))
        except Exception:
            pass
        selected_holding_symbol = sym
        mark_symbol_dirty(sym)
        refresh_holdings_list()
        try:
            save_selected_symbol()
        except Exception:
            pass
        try:
            storage.save_portfolio(portfolio)
        except Exception:
            pass
        try:
            q = get_task_queue()
            if q is not None:
                q.put_nowait({"type": "prefetch_symbol", "symbol": sym})
                q.put_nowait({"type": "warm_values"})
        except Exception:
            pass
        try:
            parent.event_generate("<<PortfolioChanged>>", when="tail")
        except Exception:
            pass

    def poll_for_changes() -> None:
        nonlocal last_mtime, portfolio, selected_holding_symbol
        try:
            mtime = os.path.getmtime(portfolio_path) if os.path.exists(portfolio_path) else 0.0
        except Exception:
            mtime = last_mtime
        if mtime > last_mtime:
            last_mtime = mtime
            # Reload portfolio from disk
            current_symbol = selected_holding_symbol
            portfolio = storage.load_portfolio(portfolio_path)
            # Keep selection
            refresh_holdings_list()
            if current_symbol:
                selected_holding_symbol = current_symbol
        # Poll infrequently; heavy updates arrive via background worker
        parent.after(2000, poll_for_changes)

    events_tree.bind("<Double-1>", on_tree_double_click)
    events_tree.bind("<Delete>", on_delete_key)
    # Persist column widths after a resize gesture completes
    def _on_column_resize_end(_evt=None):  # noqa: ANN001
        # Clamp widths and persist after user finishes dragging any separator
        try:
            for col_id in columns:
                try:
                    w = int(events_tree.column(col_id, "width"))
                except Exception:
                    w = 0
                if w < 2:
                    try:
                        events_tree.column(col_id, width=2)
                    except Exception:
                        pass
            save_state()
        except Exception:
            pass
    events_tree.bind("<ButtonRelease-1>", _on_column_resize_end)
    holdings_list.bind("<<ListboxSelect>>", on_select_holding)
    holdings_list.bind("<Double-1>", on_holdings_double_click)

    # Re-apply layout when this tab/frame becomes visible again
    try:
        parent.bind("<Map>", lambda _e: apply_saved_layout())
    except Exception:
        pass

    # Save sash position after user drags the divider
    try:
        main_pane.bind("<ButtonRelease-1>", lambda _e: save_state())
    except Exception:
        pass

    # Save controls
    bottom = ttk.Frame(parent)
    bottom.pack(fill="x", padx=8, pady=8)
    ttk.Button(bottom, text="Edit Portfolio", command=edit_portfolio_command).pack(side="right")

    # Initial population and selection
    refresh_holdings_list()
    apply_saved_selection()
    # Apply saved layout after first render
    apply_saved_layout()
    # Start polling for external changes (e.g., background dividend ingestion)
    parent.after(2000, poll_for_changes)

    # Expose hook so tab-change handler can re-apply layout when returning to this tab
    try:
        setattr(parent, "_portfolio_apply_saved_layout", apply_saved_layout)
    except Exception:
        pass


def register_portfolio_tab_handlers(notebook: ttk.Notebook, portfolio_frame: tk.Widget) -> None:
    def on_tab_changed(_evt=None):  # noqa: ANN001
        try:
            current = notebook.select()
            if current == str(portfolio_frame):
                fn = getattr(portfolio_frame, "_portfolio_apply_saved_layout", None)
                if callable(fn):
                    fn()
        except Exception:
            pass
    notebook.bind("<<NotebookTabChanged>>", on_tab_changed)
