import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional
from datetime import datetime

from models import Portfolio, Holding, Event, EventType
import storage


def build_portfolio_ui(parent: tk.Widget) -> None:
    portfolio: Portfolio = storage.load_portfolio()

    # Track selected holding symbol explicitly
    selected_holding_symbol: Optional[str] = None

    # Top controls
    top_frame = ttk.Frame(parent)
    top_frame.pack(fill="x", padx=8, pady=8)

    name_label = ttk.Label(top_frame, text="Portfolio:")
    name_label.pack(side="left")
    portfolio_name_var = tk.StringVar(value=portfolio.name)
    name_entry = ttk.Entry(top_frame, textvariable=portfolio_name_var, width=30)
    name_entry.pack(side="left", padx=(4, 16))

    reinvest_var = tk.BooleanVar(value=portfolio.dividend_reinvest)
    reinvest_check = ttk.Checkbutton(top_frame, text="Dividend Reinvest", variable=reinvest_var)
    reinvest_check.pack(side="left")

    # Add holding
    add_frame = ttk.LabelFrame(parent, text="Add Holding")
    add_frame.pack(fill="x", padx=8, pady=8)

    symbol_var = tk.StringVar()
    ttk.Label(add_frame, text="Symbol:").pack(side="left", padx=(8, 4))
    symbol_entry = ttk.Entry(add_frame, textvariable=symbol_var, width=12)
    symbol_entry.pack(side="left")

    def on_add_symbol() -> None:
        nonlocal selected_holding_symbol
        symbol = symbol_var.get().strip().upper()
        if not symbol:
            return
        holding = portfolio.get_holding(symbol)
        if holding is None:
            portfolio.ensure_holding(symbol)
        selected_holding_symbol = symbol
        refresh_holdings_list()
        symbol_var.set("")

    ttk.Button(add_frame, text="Add", command=on_add_symbol).pack(side="left", padx=8)

    # Split panes: holdings list and events
    main_pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
    main_pane.pack(fill="both", expand=True, padx=8, pady=8)

    # Holdings list
    left_frame = ttk.Frame(main_pane)
    main_pane.add(left_frame, weight=1)

    ttk.Label(left_frame, text="Holdings").pack(anchor="w")

    holdings_list = tk.Listbox(left_frame, height=12)
    holdings_list.pack(fill="both", expand=True)

    # Events section
    right_frame = ttk.Frame(main_pane)
    main_pane.add(right_frame, weight=3)

    ttk.Label(right_frame, text="Events").pack(anchor="w")

    # Sortable table for events
    columns = ("date", "type", "shares", "price", "amount", "note")
    events_tree = ttk.Treeview(right_frame, columns=columns, show="headings", selectmode="browse")
    events_tree.pack(fill="both", expand=True)

    events_tree.heading("date", text="Date")
    events_tree.heading("type", text="Type")
    events_tree.heading("shares", text="Shares")
    events_tree.heading("price", text="Price")
    events_tree.heading("amount", text="Amount")
    events_tree.heading("note", text="Note")

    events_tree.column("date", width=120, anchor="w")
    events_tree.column("type", width=110, anchor="w")
    events_tree.column("shares", width=90, anchor="e")
    events_tree.column("price", width=90, anchor="e")
    events_tree.column("amount", width=90, anchor="e")
    events_tree.column("note", width=300, anchor="w")

    # Add/Edit event form
    form = ttk.LabelFrame(right_frame, text="Add / Edit Event")
    form.pack(fill="x", pady=8)

    date_var = tk.StringVar()
    type_var = tk.StringVar(value=EventType.PURCHASE.value)
    shares_var = tk.StringVar()
    price_var = tk.StringVar()
    amount_var = tk.StringVar()
    note_var = tk.StringVar()

    row = ttk.Frame(form)
    row.pack(fill="x", padx=8, pady=4)
    ttk.Label(row, text="Date (YYYY-MM-DD or YYYYMMDD)").pack(side="left")
    ttk.Entry(row, textvariable=date_var, width=18).pack(side="left", padx=8)

    ttk.Label(row, text="Type").pack(side="left")
    type_combo = ttk.Combobox(row, textvariable=type_var, width=16, state="readonly",
                              values=[
                                  EventType.PURCHASE.value,
                                  EventType.SALE.value,
                                  EventType.DIVIDEND.value,
                                  EventType.CASH_DEPOSIT.value,
                                  EventType.CASH_WITHDRAWAL.value,
                              ])
    type_combo.pack(side="left", padx=8)

    row2 = ttk.Frame(form)
    row2.pack(fill="x", padx=8, pady=4)
    ttk.Label(row2, text="Shares").pack(side="left")
    ttk.Entry(row2, textvariable=shares_var, width=10).pack(side="left", padx=8)
    ttk.Label(row2, text="Price").pack(side="left")
    ttk.Entry(row2, textvariable=price_var, width=10).pack(side="left", padx=8)
    ttk.Label(row2, text="Amount").pack(side="left")
    ttk.Entry(row2, textvariable=amount_var, width=12).pack(side="left", padx=8)

    row3 = ttk.Frame(form)
    row3.pack(fill="x", padx=8, pady=4)
    ttk.Label(row3, text="Note").pack(side="left")
    ttk.Entry(row3, textvariable=note_var).pack(side="left", fill="x", expand=True, padx=8)

    # Track selection (original index in holding.events)
    selected_event_idx: Optional[int] = None

    def parse_date_for_sorting(date_str: str) -> tuple[int, int, int]:
        s = (date_str or "").strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                dt = datetime.strptime(s, fmt)
                return (dt.year, dt.month, dt.day)
            except ValueError:
                continue
        # Fallback: place unparsable dates at the end preserving relative order
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
        if not symbol:
            return None
        return portfolio.get_holding(symbol)

    def get_field_value(ev: Event, col: str):
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

    def build_sort_tuple(ev: Event, original_idx: int):
        # Primary column first, then all others as tie-breakers, then original index
        ordered_cols = [events_sort_column] + [c for c in columns if c != events_sort_column]
        values = tuple(get_field_value(ev, c) for c in ordered_cols)
        return values + (original_idx,)

    def refresh_holdings_list() -> None:
        # Preserve selection if possible
        nonlocal selected_holding_symbol
        current_symbol = selected_holding_symbol
        holdings_list.delete(0, tk.END)
        symbols = [h.symbol for h in sorted(portfolio.holdings, key=lambda h: h.symbol)]
        for sym in symbols:
            holdings_list.insert(tk.END, sym)
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

    def refresh_events_list() -> None:
        nonlocal selected_event_idx
        # Remember previously selected row id
        prev_selected = None
        sel = events_tree.selection()
        if sel:
            prev_selected = sel[0]
        # Clear tree
        for iid in events_tree.get_children():
            events_tree.delete(iid)
        selected_event_idx = None
        holding = get_selected_holding()
        if holding is None:
            return
        # Build sorted view without mutating underlying order; iid is original index
        enumerated = list(enumerate(holding.events))
        enumerated.sort(key=lambda pair: build_sort_tuple(pair[1], pair[0]), reverse=events_sort_reverse)
        for original_idx, e in enumerated:
            iid = str(original_idx)
            events_tree.insert("", "end", iid=iid, values=(
                format_date_for_display(e.date),
                e.type.value,
                f"{e.shares:g}" if e.shares else "",
                f"{e.price:g}" if e.price else "",
                f"{e.amount:g}" if e.amount else "",
                e.note,
            ))
        # Restore selection if possible
        if prev_selected and prev_selected in events_tree.get_children():
            events_tree.selection_set(prev_selected)
            selected_event_idx = int(prev_selected)

    def populate_form_from_event(ev: Event) -> None:
        date_var.set(ev.date)
        type_var.set(ev.type.value)
        shares_var.set(str(ev.shares if ev.shares else ""))
        price_var.set(str(ev.price if ev.price else ""))
        amount_var.set(str(ev.amount if ev.amount else ""))
        note_var.set(ev.note)

    def on_select_event(_evt=None) -> None:  # noqa: ANN001
        nonlocal selected_event_idx
        sel = events_tree.selection()
        if not sel:
            selected_event_idx = None
            return
        try:
            idx = int(sel[0])
        except ValueError:
            selected_event_idx = None
            return
        selected_event_idx = idx
        holding = get_selected_holding()
        if holding is None:
            return
        if 0 <= idx < len(holding.events):
            populate_form_from_event(holding.events[idx])

    def parse_form_to_values() -> tuple[str, EventType, float, float, float, str]:
        try:
            shares = float(shares_var.get() or 0)
        except ValueError:
            shares = 0.0
        try:
            price = float(price_var.get() or 0)
        except ValueError:
            price = 0.0
        try:
            amount = float(amount_var.get() or 0)
        except ValueError:
            amount = 0.0
        return (
            date_var.get().strip(),
            EventType(type_var.get()),
            shares,
            price,
            amount,
            note_var.get().strip(),
        )

    def on_add_event() -> None:
        holding = get_selected_holding()
        if holding is None and type_var.get() not in {EventType.CASH_DEPOSIT.value, EventType.CASH_WITHDRAWAL.value, EventType.DIVIDEND.value}:
            messagebox.showwarning("No holding selected", "Select a holding to add a trade event.")
            return
        date_str, ev_type, shares, price, amount, note = parse_form_to_values()
        ev = Event(date=date_str, type=ev_type, shares=shares, price=price, amount=amount, note=note)
        if ev.type in {EventType.CASH_DEPOSIT, EventType.CASH_WITHDRAWAL, EventType.DIVIDEND}:
            portfolio.cash_events.append(ev)
        else:
            holding.events.append(ev)
        refresh_events_list()
        date_var.set("")
        shares_var.set("")
        price_var.set("")
        amount_var.set("")
        note_var.set("")

    def on_update_event() -> None:
        holding = get_selected_holding()
        if holding is None:
            messagebox.showwarning("No holding selected", "Select a holding first.")
            return
        if selected_event_idx is None or not (0 <= selected_event_idx < len(holding.events)):
            messagebox.showwarning("No event selected", "Select an event to update.")
            return
        date_str, ev_type, shares, price, amount, note = parse_form_to_values()
        # If type becomes a cash-type, move to cash events
        if ev_type in {EventType.CASH_DEPOSIT, EventType.CASH_WITHDRAWAL, EventType.DIVIDEND}:
            del holding.events[selected_event_idx]
            portfolio.cash_events.append(Event(date=date_str, type=ev_type, shares=shares, price=price, amount=amount, note=note))
        else:
            ev = holding.events[selected_event_idx]
            ev.date = date_str
            ev.type = ev_type
            ev.shares = shares
            ev.price = price
            ev.amount = amount
            ev.note = note
        refresh_events_list()

    def on_delete_event() -> None:
        holding = get_selected_holding()
        if holding is None:
            messagebox.showwarning("No holding selected", "Select a holding first.")
            return
        if selected_event_idx is None or not (0 <= selected_event_idx < len(holding.events)):
            messagebox.showwarning("No event selected", "Select an event to delete.")
            return
        del holding.events[selected_event_idx]
        refresh_events_list()

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

    def on_select_holding(_evt=None) -> None:  # noqa: ANN001
        nonlocal selected_holding_symbol
        try:
            idx = holdings_list.curselection()[0]
            selected_holding_symbol = holdings_list.get(idx)
        except IndexError:
            selected_holding_symbol = selected_holding_symbol
        refresh_events_list()

    events_tree.bind("<<TreeviewSelect>>", on_select_event)
    holdings_list.bind("<<ListboxSelect>>", on_select_holding)

    # Save controls
    bottom = ttk.Frame(parent)
    bottom.pack(fill="x", padx=8, pady=8)

    symbols_label_var = tk.StringVar(value="")
    symbols_label = ttk.Label(bottom, textvariable=symbols_label_var)
    symbols_label.pack(side="left")

    def refresh_symbols_label() -> None:
        symbols_label_var.set(f"Symbols: {', '.join(sorted([h.symbol for h in portfolio.holdings]))}")

    def on_save() -> None:
        portfolio.name = portfolio_name_var.get().strip() or portfolio.name
        portfolio.dividend_reinvest = reinvest_var.get()
        storage.save_portfolio(portfolio)
        messagebox.showinfo("Saved", f"Saved to {storage.default_portfolio_path()}")

    ttk.Button(bottom, text="Save Portfolio", command=on_save).pack(side="right")

    # Initial population and selection
    refresh_holdings_list()
