from __future__ import annotations

import threading

from prefetch import prefetch_all_symbols
from dividends import cache_and_ingest_dividends_for_file
from values_cache import warm_values_cache_for_portfolio
import storage


def _run_all() -> None:
    try:
        prefetch_all_symbols()
    except Exception as exc:  # noqa: BLE001
        print(f"Prefetch error: {exc}")
    # After prefetch, ingest dividends for each portfolio file with cache-awareness
    for path in storage.list_portfolio_paths():
        try:
            added = cache_and_ingest_dividends_for_file(path)
            if added:
                print(f"Dividends added to {path}: {added}")
        except Exception as exc:  # noqa: BLE001
            print(f"Dividend ingest error for {path}: {exc}")
    # Warm values cache
    for path in storage.list_portfolio_paths():
        try:
            updated = warm_values_cache_for_portfolio(path)
            if updated:
                print(f"Values cache updated for {path}: {updated}")
        except Exception as exc:  # noqa: BLE001
            print(f"Values cache error for {path}: {exc}")


def run_startup_tasks_in_background() -> None:
    thread = threading.Thread(target=_run_all, name="startup-tasks", daemon=True)
    thread.start()
