import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import simpledialog
from typing import Optional
from datetime import datetime
import os

from models import Portfolio, Holding, Event, EventType
import storage
from values_cache import mark_symbol_dirty
from startup_tasks import get_task_queue


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

    ttk.Label(top_frame, text="Portfolio:").pack(side="left")
    portfolio_name_var = tk.StringVar(value=portfolio.name)
    ttk.Entry(top_frame, textvariable=portfolio_name_var, width=30).pack(side="left", padx=(4, 8))

    # Portfolio switcher
    ttk.Label(top_frame, text="File:").pack(side="left")
    portfolio_paths = storage.list_portfolio_paths()
    active_path = storage.default_portfolio_path()
    display_names = [os.path.basename(p) for p in portfolio_paths]
    name_to_path = {os.path.basename(p): p for p in portfolio_paths}
    portfolio_path_var = tk.StringVar(value=os.path.basename(active_path))
    path_combo = ttk.Combobox(top_frame, textvariable=portfolio_path_var, state="readonly", width=40, values=display_names)
    path_combo.pack(side="left", padx=(4, 8))

    def on_switch_portfolio() -> None:
        name = portfolio_path_var.get().strip()
        path = name_to_path.get(name, "")
        if not path:
            return
        try:
            storage.set_default_portfolio_path(path)
        except Exception:
            pass
        # Reload portfolio and refresh UI
        nonlocal portfolio, portfolio_path, last_mtime
        portfolio_path = storage.default_portfolio_path()
        try:
            last_mtime = os.path.getmtime(portfolio_path) if os.path.exists(portfolio_path) else 0.0
        except Exception:
            last_mtime = 0.0
        portfolio = storage.load_portfolio(portfolio_path)
        portfolio_name_var.set(portfolio.name)
        reinvest_var.set(portfolio.dividend_reinvest)
        refresh_holdings_list()
        try:
            parent.event_generate("<<PortfolioChanged>>", when="tail")
        except Exception:
            pass

    ttk.Button(top_frame, text="Switch", command=on_switch_portfolio).pack(side="left", padx=(0, 8))

    reinvest_var = tk.BooleanVar(value=portfolio.dividend_reinvest)
    ttk.Checkbutton(top_frame, text="Dividend Reinvest", variable=reinvest_var).pack(side="left")

    # Manual refresh dividends
    def on_refresh_dividends() -> None:
        try:
            q = get_task_queue()
            if q is not None:
                q.put_nowait({"type": "ingest_dividends", "path": storage.default_portfolio_path()})
        except Exception:
            pass
    ttk.Button(top_frame, text="Refresh Dividends", command=on_refresh_dividends).pack(side="left", padx=(8, 0))

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

    ttk.Label(right_frame, text="Events").pack(anchor="w")

    # Sortable table for events
    columns = ("symbol", "date", "type", "shares", "price", "amount", "note")
    events_tree = ttk.Treeview(right_frame, columns=columns, show="headings", selectmode="browse")
    events_tree.pack(fill="both", expand=True)

    events_tree.heading("symbol", text="Symbol")
    events_tree.heading("date", text="Date")
    events_tree.heading("type", text="Type")
    events_tree.heading("shares", text="Shares")
    events_tree.heading("price", text="Price")
    events_tree.heading("amount", text="Cost")
    events_tree.heading("note", text="Note")

    # Initial column widths (will be auto-adjusted on font scale changes)
    events_tree.column("symbol", width=100, anchor="w")
    events_tree.column("date", width=120, anchor="w")
    events_tree.column("type", width=110, anchor="w")
    events_tree.column("shares", width=90, anchor="e")
    events_tree.column("price", width=90, anchor="e")
    events_tree.column("amount", width=90, anchor="e")
    events_tree.column("note", width=300, anchor="w")

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
            events_tree.column("symbol", width=ch(10))
            events_tree.column("date", width=ch(12))
            events_tree.column("type", width=ch(12))
            events_tree.column("shares", width=ch(10))
            events_tree.column("price", width=ch(10))
            events_tree.column("amount", width=ch(10))
            events_tree.column("note", width=ch(40))
        except Exception:
            pass

    parent.bind("<<FontScaleChanged>>", lambda _e: auto_size_columns())

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
        refresh_symbols_label()
        auto_size_columns()

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

            # Update display for the new row
            events_tree.item("new", values=(
                new_entry_values["symbol"] or placeholder_symbol,
                new_entry_values["date"] or placeholder_date,
                new_entry_values["type"] or placeholder_type,
                new_entry_values["shares"] or placeholder_shares,
                new_entry_values["price"] or placeholder_price,
                new_entry_values["amount"] or placeholder_amount,
                new_entry_values["note"] or placeholder_note,
            ))

            has_symbol = bool(new_entry_values["symbol"])
            has_other = bool(new_entry_values["date"] or new_entry_values["shares"] or new_entry_values["price"] or new_entry_values["amount"] or new_entry_values["note"] or (new_entry_values["type"] and new_entry_values["type"] != placeholder_type))
            if has_symbol and has_other:
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
            ev.amount = parse_float_or_zero(value)
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
            enumerated.sort(key=lambda pair: build_sort_tuple(pair[1], holding.symbol, pair[0]), reverse=events_sort_reverse)
            for original_idx, e in enumerated:
                iid = f"{holding.symbol}:{original_idx}"
                events_tree.insert("", "end", iid=iid, values=(
                    holding.symbol,
                    format_date_for_display(e.date),
                    e.type.value,
                    f"{e.shares:g}" if e.shares else "",
                    f"{e.price:g}" if e.price else "",
                    f"{e.amount:g}" if e.amount else "",
                    e.note,
                ))

        # Always include a new event row for quick entry with placeholders or draft values
        events_tree.insert("", "end", iid="new", values=(
            new_entry_values["symbol"] or placeholder_symbol,
            new_entry_values["date"] or placeholder_date,
            new_entry_values["type"] or placeholder_type,
            new_entry_values["shares"] or placeholder_shares,
            new_entry_values["price"] or placeholder_price,
            new_entry_values["amount"] or placeholder_amount,
            new_entry_values["note"] or placeholder_note,
        ))
        # Restore selection if possible
        if prev_selected and prev_selected in events_tree.get_children():
            events_tree.selection_set(prev_selected)

    def on_select_holding(_evt=None) -> None:  # noqa: ANN001
        refresh_events_list()

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
            portfolio_name_var.set(portfolio.name)
            reinvest_var.set(portfolio.dividend_reinvest)
            # Keep selection
            refresh_holdings_list()
            if current_symbol:
                selected_holding_symbol = current_symbol
        # Poll infrequently; heavy updates arrive via background worker
        parent.after(2000, poll_for_changes)

    events_tree.bind("<Double-1>", on_tree_double_click)
    events_tree.bind("<Delete>", on_delete_key)
    holdings_list.bind("<<ListboxSelect>>", on_select_holding)
    holdings_list.bind("<Double-1>", on_holdings_double_click)

    # Save controls
    bottom = ttk.Frame(parent)
    bottom.pack(fill="x", padx=8, pady=8)

    symbols_label_var = tk.StringVar(value="")
    ttk.Label(bottom, textvariable=symbols_label_var).pack(side="left")

    def refresh_symbols_label() -> None:
        symbols_label_var.set(f"Symbols: {', '.join(sorted([h.symbol for h in portfolio.holdings]))}")

    def on_save() -> None:
        portfolio.name = portfolio_name_var.get().strip() or portfolio.name
        portfolio.dividend_reinvest = reinvest_var.get()
        storage.save_portfolio(portfolio)
        messagebox.showinfo("Saved", f"Saved to {storage.default_portfolio_path()}")
        try:
            q = get_task_queue()
            if q is not None:
                q.put_nowait({"type": "warm_values"})
        except Exception:
            pass

    ttk.Button(bottom, text="Save Portfolio", command=on_save).pack(side="right")

    # Initial population and selection
    refresh_holdings_list()
    # Start polling for external changes (e.g., background dividend ingestion)
    parent.after(2000, poll_for_changes)
