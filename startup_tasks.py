from __future__ import annotations

import threading

from prefetch import prefetch_all_symbols


def run_startup_tasks_in_background() -> None:
    thread = threading.Thread(target=prefetch_all_symbols, name="prefetch-thread", daemon=True)
    thread.start()
