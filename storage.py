import csv
import os
from typing import Optional, List

from models import Portfolio, Holding, Event, EventType


def default_data_dir() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    return data_dir


def default_portfolio_path() -> str:
    return os.path.join(default_data_dir(), "portfolio_default.csv")


def list_portfolio_paths() -> List[str]:
    data_dir = default_data_dir()
    if not os.path.isdir(data_dir):
        return []
    paths: List[str] = []
    for name in os.listdir(data_dir):
        if not name.lower().endswith(".csv"):
            continue
        # Skip cache files if any end up here
        if name.lower().startswith("cache_"):
            continue
        paths.append(os.path.join(data_dir, name))
    return sorted(paths)


CSV_FIELDS = [
    "row_type",  # event | cash  (meta supported for backward-compat read only)
    "key",
    "value",
    "symbol",
    "date",
    "type",
    "shares",
    "price",
    "amount",
    "note",
]


def _bool_to_str(value: bool) -> str:
    return "true" if value else "false"


def _str_to_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def load_portfolio(file_path: Optional[str] = None) -> Portfolio:
    path = file_path or default_portfolio_path()
    if not os.path.exists(path):
        return Portfolio()

    portfolio = Portfolio()
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_type = (row.get("row_type") or "").strip().lower()
            if row_type == "meta":
                # Backward compatibility only; no longer written out
                key = (row.get("key") or "").strip().lower()
                val = (row.get("value") or "").strip()
                if key == "name":
                    portfolio.name = val or portfolio.name
                elif key == "dividend_reinvest":
                    portfolio.dividend_reinvest = _str_to_bool(val)
                continue

            if row_type == "event":
                symbol = (row.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                holding = portfolio.ensure_holding(symbol)
                ev = Event(
                    date=(row.get("date") or "").strip(),
                    type=EventType(row.get("type") or EventType.PURCHASE.value),
                    shares=float(row.get("shares") or 0.0),
                    price=float(row.get("price") or 0.0),
                    amount=float(row.get("amount") or 0.0),
                    note=str(row.get("note") or ""),
                )
                holding.events.append(ev)
                continue

            if row_type == "cash":
                ev = Event(
                    date=(row.get("date") or "").strip(),
                    type=EventType(row.get("type") or EventType.CASH_DEPOSIT.value),
                    shares=float(row.get("shares") or 0.0),
                    price=float(row.get("price") or 0.0),
                    amount=float(row.get("amount") or 0.0),
                    note=str(row.get("note") or ""),
                )
                portfolio.cash_events.append(ev)
                continue

    return portfolio


def save_portfolio(portfolio: Portfolio, file_path: Optional[str] = None) -> None:
    path = file_path or default_portfolio_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        # No meta rows; write only events
        for holding in portfolio.holdings:
            for ev in holding.events:
                writer.writerow({
                    "row_type": "event",
                    "key": "",
                    "value": "",
                    "symbol": holding.symbol,
                    "date": ev.date,
                    "type": ev.type.value,
                    "shares": ev.shares,
                    "price": ev.price,
                    "amount": ev.amount,
                    "note": ev.note,
                })
        for ev in portfolio.cash_events:
            writer.writerow({
                "row_type": "cash",
                "key": "",
                "value": "",
                "symbol": "",
                "date": ev.date,
                "type": ev.type.value,
                "shares": ev.shares,
                "price": ev.price,
                "amount": ev.amount,
                "note": ev.note,
            })
