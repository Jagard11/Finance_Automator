from __future__ import annotations

import multiprocessing as mp
import time
from typing import Optional, Dict, Any

from prefetch import collect_all_symbols, fetch_and_cache_symbol
from dividends import cache_and_ingest_dividends_for_file
from values_cache import warm_values_cache_for_portfolio
import storage


def _run_all(progress_q: Optional[mp.Queue] = None, task_q: Optional[mp.Queue] = None) -> None:
    def send(msg: Dict[str, Any]) -> None:
        try:
            if progress_q is not None:
                progress_q.put_nowait(msg)
        except Exception:  # noqa: BLE001
            pass

    try:
        symbols = collect_all_symbols()
        total = len(symbols)
        done = 0
        send({"type": "prefetch:start", "total": total})
        for sym in sorted(symbols):
            try:
                fetch_and_cache_symbol(sym)
            except Exception as exc:  # noqa: BLE001
                send({"type": "prefetch:error", "symbol": sym, "error": str(exc)})
            finally:
                done += 1
                # Coarse progress updates
                if done == total or done % 5 == 0:
                    send({"type": "prefetch:progress", "done": done, "total": total})
        send({"type": "prefetch:done", "total": total})
    except Exception as exc:  # noqa: BLE001
        send({"type": "prefetch:fatal", "error": str(exc)})

    # After prefetch, ingest dividends for each portfolio file with cache-awareness
    for path in storage.list_portfolio_paths():
        try:
            added = cache_and_ingest_dividends_for_file(path)
            send({"type": "dividends:ingested", "path": path, "added": int(added)})
        except Exception as exc:  # noqa: BLE001
            send({"type": "dividends:error", "path": path, "error": str(exc)})

    # Warm values cache
    for path in storage.list_portfolio_paths():
        try:
            updated = warm_values_cache_for_portfolio(path)
            send({"type": "values:warmed", "path": path, "updated": int(updated)})
        except Exception as exc:  # noqa: BLE001
            send({"type": "values:error", "path": path, "error": str(exc)})

    send({"type": "startup:complete"})

    # Task loop: handle on-demand jobs from UI
    while True:
        try:
            task = None
            if task_q is not None:
                # Wait briefly to allow batching multiple UI changes
                task = task_q.get(timeout=0.5)
            else:
                time.sleep(0.5)
        except Exception:
            task = None

        if task is None:
            continue
        ttype = str(task.get("type", ""))
        if ttype == "stop":
            send({"type": "worker:stopping"})
            break
        if ttype == "warm_values":
            path = task.get("path")
            paths = [path] if isinstance(path, str) else list(storage.list_portfolio_paths())
            total_updated = 0
            for p in paths:
                try:
                    updated = warm_values_cache_for_portfolio(p)
                except Exception as exc:  # noqa: BLE001
                    send({"type": "values:error", "path": p, "error": str(exc)})
                    continue
                total_updated += int(updated)
                send({"type": "values:warmed", "path": p, "updated": int(updated)})
            if total_updated:
                send({"type": "values:done", "updated": total_updated})
            continue
        if ttype == "prefetch_symbol":
            sym = str(task.get("symbol", "")).strip().upper()
            if sym:
                try:
                    fetch_and_cache_symbol(sym)
                    send({"type": "prefetch:one", "symbol": sym})
                except Exception as exc:  # noqa: BLE001
                    send({"type": "prefetch:error", "symbol": sym, "error": str(exc)})
            continue


_progress_queue: Optional[mp.Queue] = None
_task_queue: Optional[mp.Queue] = None
_proc: Optional[mp.Process] = None


def get_progress_queue() -> Optional[mp.Queue]:
    return _progress_queue


def run_startup_tasks_in_background() -> None:
    global _progress_queue, _task_queue, _proc
    if _proc is not None and _proc.is_alive():
        return
    _progress_queue = mp.Queue()
    _task_queue = mp.Queue()
    _proc = mp.Process(target=_run_all, args=(_progress_queue, _task_queue), name="startup-tasks", daemon=True)
    _proc.start()


def get_task_queue() -> Optional[mp.Queue]:
    return _task_queue
