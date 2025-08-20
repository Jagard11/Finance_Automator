from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class EventType(str, Enum):
    PURCHASE = "purchase"
    SALE = "sale"
    DIVIDEND = "dividend"
    CASH_DEPOSIT = "cash_deposit"
    CASH_WITHDRAWAL = "cash_withdrawal"


@dataclass
class Event:
    date: str  # ISO format YYYY-MM-DD
    type: EventType
    shares: float = 0.0
    price: float = 0.0
    amount: float = 0.0
    note: str = ""


@dataclass
class Holding:
    symbol: str
    events: List[Event] = field(default_factory=list)


@dataclass
class Portfolio:
    name: str = "Default"
    dividend_reinvest: bool = True
    holdings: List[Holding] = field(default_factory=list)
    cash_events: List[Event] = field(default_factory=list)

    def get_holding(self, symbol: str) -> Optional[Holding]:
        symbol_upper = symbol.upper()
        for holding in self.holdings:
            if holding.symbol.upper() == symbol_upper:
                return holding
        return None

    def ensure_holding(self, symbol: str) -> Holding:
        existing = self.get_holding(symbol)
        if existing is not None:
            return existing
        holding = Holding(symbol=symbol.upper())
        self.holdings.append(holding)
        return holding
