from __future__ import annotations

import csv
import os
import multiprocessing as mp
from datetime import date
from typing import List, Dict, Optional

import pandas as pd

import storage
from prefetch import cache_dir as get_cache_dir
from values_cache import read_values_cache
from settings import vprint


def journal_csv_path(portfolio_path: Optional[str] = None) -> str:
    # Single journal file per portfolio for now; default path
    name = os.path.splitext(os.path.basename(portfolio_path or storage.default_portfolio_path()))[0]
    return os.path.join(get_cache_dir(), f"{name}_journal.csv")


def build_journal_csv_streaming(portfolio_path: Optional[str] = None) -> None:
    vprint(f"build_journal_csv_streaming: start {portfolio_path}")
    portfolio = storage.load_portfolio(portfolio_path)
    symbols: List[str] = [h.symbol for h in portfolio.holdings]
    if not symbols:
        # Write empty header
        path = journal_csv_path(portfolio_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date"] + symbols)
        vprint("build_journal_csv_streaming: no symbols")
        return

    # Load per-symbol values caches
    sym_to_df: Dict[str, pd.DataFrame] = {}
    date_index: Optional[pd.DatetimeIndex] = None
    for sym in symbols:
        df = read_values_cache(sym)
        if df is None or df.empty:
            continue
        df = df.copy()
        # Ensure date column is parsed as date and drop rows with zero/NaN values
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])  # drop invalid dates
        df.set_index("date", inplace=True)
        # Remove rows where shares <= 0 or value <= 0 to avoid blank journal entries
        if "shares" in df.columns:
            try:
                df = df[pd.to_numeric(df["shares"], errors="coerce").fillna(0) > 0]
            except Exception:
                pass
        if "value" in df.columns:
            try:
                df = df[pd.to_numeric(df["value"], errors="coerce").fillna(0) > 0]
            except Exception:
                pass
        sym_to_df[sym] = df
        date_index = df.index if date_index is None else date_index.union(df.index)

    if date_index is None:
        path = journal_csv_path(portfolio_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date"] + symbols)
        vprint("build_journal_csv_streaming: empty index")
        return

    # Sort symbols for consistent columns
    symbols_sorted = sorted(symbols)

    # Write streaming rows with buffering
    path = journal_csv_path(portfolio_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date"] + symbols_sorted)
        f.flush()
        buffer: List[List[str]] = []
        for ts in date_index.sort_values():
            row = [pd.Timestamp(ts).date().isoformat()]
            for sym in symbols_sorted:
                df = sym_to_df.get(sym)
                if df is None or ts not in df.index:
                    row.append("")
                else:
                    shares = df.at[ts, "shares"] if "shares" in df.columns else None
                    if shares is not None:
                        try:
                            if float(shares) <= 0:
                                row.append("")
                                continue
                        except Exception:
                            pass
                    val = df.at[ts, "value"] if "value" in df.columns else None
                    row.append("" if val is None or pd.isna(val) else f"{float(val):.2f}")
            buffer.append(row)
            if len(buffer) >= 200:
                writer.writerows(buffer)
                f.flush()
                buffer.clear()
        if buffer:
            writer.writerows(buffer)
            f.flush()
    vprint(f"build_journal_csv_streaming: wrote to {path}")


_proc: Optional[mp.Process] = None


def rebuild_journal_in_background(portfolio_path: Optional[str] = None) -> None:
    global _proc
    if _proc is not None and _proc.is_alive():
        return
    _proc = mp.Process(target=build_journal_csv_streaming, args=(portfolio_path,), name="journal-builder", daemon=True)
    _proc.start()
