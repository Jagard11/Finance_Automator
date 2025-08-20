from __future__ import annotations

import threading

from prefetch import prefetch_all_symbols
from dividends import ingest_dividends_for_file
import storage


def _run_all() -> None:
    try:
        prefetch_all_symbols()
    except Exception as exc:  # noqa: BLE001
        print(f"Prefetch error: {exc}")
    # After prefetch, ingest dividends for each portfolio file
    for path in storage.list_portfolio_paths():
        try:
            added = ingest_dividends_for_file(path)
            if added:
                print(f"Dividends added to {path}: {added}")
        except Exception as exc:  # noqa: BLE001
            print(f"Dividend ingest error for {path}: {exc}")


def run_startup_tasks_in_background() -> None:
    thread = threading.Thread(target=_run_all, name="startup-tasks", daemon=True)
    thread.start()
