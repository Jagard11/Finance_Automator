from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import pandas as pd

import storage
from market_data import fetch_dividends, fetch_price_history
from models import Portfolio, Holding, Event, EventType


DIV_NOTE_PREFIX = "DIV:"
DRIP_NOTE_PREFIX = "DRIP:"


def _normalize_date(date_str: str) -> str:
    s = (date_str or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s


@dataclass
class OwnedSharesOnDate:
    date: str  # ISO
    shares: float


def compute_owned_shares_on_date(holding: Holding, target_date_iso: str) -> float:
    target = datetime.fromisoformat(_normalize_date(target_date_iso)).date()
    shares = 0.0
    # Process events up to and including the target date
    for ev in sorted(holding.events, key=lambda e: _normalize_date(e.date)):
        ev_date_iso = _normalize_date(ev.date)
        if not ev_date_iso:
            continue
        ev_dt = datetime.fromisoformat(ev_date_iso).date()
        if ev_dt > target:
            break
        if ev.type == EventType.PURCHASE:
            shares += float(ev.shares or 0)
        elif ev.type == EventType.SALE:
            shares -= float(ev.shares or 0)
        # Reinvest purchases we create are also PURCHASE
    return max(shares, 0.0)


def _has_cash_dividend_on_date(portfolio: Portfolio, symbol: str, on_date_iso: str) -> bool:
    marker = f"{DIV_NOTE_PREFIX}{symbol.upper()}"
    for ev in portfolio.cash_events:
        if ev.type == EventType.DIVIDEND and _normalize_date(ev.date) == on_date_iso and (ev.note or "").startswith(marker):
            return True
    return False


def _has_drip_purchase_on_date(holding: Holding, symbol: str, on_date_iso: str) -> bool:
    marker = f"{DRIP_NOTE_PREFIX}{symbol.upper()}"
    for ev in holding.events:
        if ev.type == EventType.PURCHASE and _normalize_date(ev.date) == on_date_iso and (ev.note or "").startswith(marker):
            return True
    return False


def _first_available_close_price(symbol: str, on_date_iso: str) -> Optional[float]:
    # Try on date, then next few business days
    start_dt = datetime.fromisoformat(on_date_iso).date()
    end_dt = start_dt + timedelta(days=5)
    df = fetch_price_history(symbol, on_date_iso, (end_dt + timedelta(days=1)).isoformat())
    if isinstance(df, pd.DataFrame) and not df.empty:
        series = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
        for idx, val in series.items():
            try:
                return float(val)
            except Exception:  # noqa: BLE001
                continue
    return None


def ingest_dividends_for_portfolio(portfolio: Portfolio, start_date_iso: Optional[str] = None, end_date_iso: Optional[str] = None, reinvest: Optional[bool] = None) -> int:
    """
    Fetch dividend events for each symbol in the portfolio and add cash dividend events.
    If reinvest is True, also add a purchase event for the dividend amount at the next available close price.
    Returns the count of new events added.
    """
    changes = 0
    if reinvest is None:
        reinvest = getattr(portfolio, "dividend_reinvest", False)

    # Determine global default range from portfolio events if not provided
    if start_date_iso is None or end_date_iso is None:
        all_dates: list[str] = []
        for h in portfolio.holdings:
            for ev in h.events:
                if ev.date:
                    all_dates.append(_normalize_date(ev.date))
        if all_dates:
            start_date_iso = start_date_iso or min(all_dates)
        else:
            start_date_iso = start_date_iso or date.today().isoformat()
        end_date_iso = end_date_iso or date.today().isoformat()

    for holding in portfolio.holdings:
        symbol = holding.symbol.upper()
        # Fetch dividend-per-share series for range
        series = fetch_dividends(symbol, start_date_iso, end_date_iso)
        if series is None or series.empty:
            continue
        # Iterate ex-dividend dates
        for ex_dt, per_share in series.items():
            try:
                ex_iso = pd.Timestamp(ex_dt).date().isoformat()
            except Exception:  # noqa: BLE001
                continue
            shares_owned = compute_owned_shares_on_date(holding, ex_iso)
            if shares_owned <= 0.0:
                continue
            cash_amount = float(per_share) * shares_owned
            if cash_amount == 0.0:
                continue
            # Add cash dividend if not exists
            if not _has_cash_dividend_on_date(portfolio, symbol, ex_iso):
                portfolio.cash_events.append(Event(
                    date=ex_iso,
                    type=EventType.DIVIDEND,
                    amount=cash_amount,
                    note=f"{DIV_NOTE_PREFIX}{symbol}",
                ))
                changes += 1
            # Optionally reinvest: add a purchase with computed shares
            if reinvest and not _has_drip_purchase_on_date(holding, symbol, ex_iso):
                price = _first_available_close_price(symbol, ex_iso)
                if price and price > 0:
                    shares_to_add = cash_amount / price
                    holding.events.append(Event(
                        date=ex_iso,
                        type=EventType.PURCHASE,
                        shares=shares_to_add,
                        price=price,
                        amount=0.0,
                        note=f"{DRIP_NOTE_PREFIX}{symbol}",
                    ))
                    changes += 1
    return changes


def ingest_dividends_for_file(portfolio_path: str) -> int:
    portfolio = storage.load_portfolio(portfolio_path)
    num = ingest_dividends_for_portfolio(portfolio)
    if num:
        storage.save_portfolio(portfolio, portfolio_path)
    return num
