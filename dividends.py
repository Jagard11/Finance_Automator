from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional, Dict, Set

import pandas as pd

import storage
from market_data import fetch_dividends, fetch_price_history
from models import Portfolio, Holding, Event, EventType
from prefetch import cache_dir as get_cache_dir


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


def _has_symbol_dividend_on_date(holding: Holding, symbol: str, on_date_iso: str) -> bool:
    marker = f"{DIV_NOTE_PREFIX}{symbol.upper()}"
    for ev in holding.events:
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
        for _, val in series.items():
            try:
                return float(val)
            except Exception:  # noqa: BLE001
                continue
    return None


# =====================
# Cache helpers
# =====================

def _dividend_cache_path(symbol: str) -> str:
    return os.path.join(get_cache_dir(), f"{symbol.upper()}_dividends.csv")


def _read_dividend_cache(symbol: str) -> Dict[str, float]:
    path = _dividend_cache_path(symbol)
    if not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path)
        cache: Dict[str, float] = {}
        for _, row in df.iterrows():
            d = str(row.get("date", "")).strip()
            if not d:
                continue
            cache[d] = float(row.get("per_share", 0.0))
        return cache
    except Exception:  # noqa: BLE001
        return {}


def _write_dividend_cache(symbol: str, series: pd.Series) -> None:
    path = _dividend_cache_path(symbol)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Merge existing
    existing = _read_dividend_cache(symbol)
    merged: Dict[str, float] = dict(existing)
    for idx, val in series.items():
        try:
            iso = pd.Timestamp(idx).date().isoformat()
            merged[iso] = float(val)
        except Exception:  # noqa: BLE001
            continue
    df = pd.DataFrame({"date": list(merged.keys()), "per_share": list(merged.values())})
    df.sort_values("date").to_csv(path, index=False)


# =====================
# Ingestion API
# =====================

def ingest_dividends_for_holding_range(portfolio: Portfolio, holding: Holding, start_date_iso: str, end_date_iso: str, reinvest: Optional[bool] = None) -> int:
    changes = 0
    if reinvest is None:
        reinvest = getattr(portfolio, "dividend_reinvest", False)
    symbol = holding.symbol.upper()
    series = fetch_dividends(symbol, start_date_iso, end_date_iso)
    if series is None or series.empty:
        return 0
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
        # Holding-level dividend event
        if not _has_symbol_dividend_on_date(holding, symbol, ex_iso):
            holding.events.append(Event(
                date=ex_iso,
                type=EventType.DIVIDEND,
                amount=cash_amount,
                note=f"{DIV_NOTE_PREFIX}{symbol}",
            ))
            changes += 1
        # Cash vs DRIP
        if reinvest:
            if not _has_drip_purchase_on_date(holding, symbol, ex_iso):
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
        else:
            if not _has_cash_dividend_on_date(portfolio, symbol, ex_iso):
                portfolio.cash_events.append(Event(
                    date=ex_iso,
                    type=EventType.DIVIDEND,
                    amount=cash_amount,
                    note=f"{DIV_NOTE_PREFIX}{symbol}",
                ))
                changes += 1
    return changes


def cache_and_ingest_dividends_for_file(portfolio_path: str) -> int:
    portfolio = storage.load_portfolio(portfolio_path)
    total_changes = 0
    today_iso = date.today().isoformat()
    for holding in portfolio.holdings:
        if not holding.events:
            continue
        symbol = holding.symbol.upper()
        start_iso = min(_normalize_date(e.date) for e in holding.events if e.date)
        # Fetch full series for [start..today]
        series = fetch_dividends(symbol, start_iso, today_iso)
        if series is None or series.empty:
            continue
        # Compare with cache
        cache_map = _read_dividend_cache(symbol)
        cached_dates: Set[str] = set(cache_map.keys())
        series_dates: Set[str] = set(pd.Timestamp(idx).date().isoformat() for idx in series.index)
        new_dates = sorted(d for d in series_dates if d not in cached_dates)
        if not new_dates and cached_dates:
            # Nothing new -> skip
            continue
        # Ingest full range (ensures consistency even if cache is partial)
        changes = ingest_dividends_for_holding_range(portfolio, holding, start_iso, today_iso)
        total_changes += changes
        # Update cache with full series
        _write_dividend_cache(symbol, series)
        # If new dividends were discovered, run a second pass to account for DRIP compounding
        if changes > 0:
            total_changes += ingest_dividends_for_holding_range(portfolio, holding, start_iso, today_iso)
    if total_changes:
        storage.save_portfolio(portfolio, portfolio_path)
    return total_changes
