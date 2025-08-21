from __future__ import annotations

import multiprocessing as mp
import time
from typing import Optional, Dict, Any

from prefetch import collect_all_symbols, fetch_and_cache_symbol
from dividends import cache_and_ingest_dividends_for_file
from values_cache import warm_values_cache_for_portfolio, mark_symbol_dirty
from journal_builder import build_journal_csv_streaming
from settings import vprint
import storage
from market_data import update_realtime_price_cache


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

    # Mark all symbols dirty to recompute values with latest algorithm
    try:
        for sym in symbols:
            mark_symbol_dirty(sym)
    except Exception:
        pass

    # After prefetch, ingest dividends for each portfolio file with cache-awareness
    for path in storage.list_portfolio_paths():
        try:
            vprint(f"startup: ingest_dividends {path}")
            added = cache_and_ingest_dividends_for_file(path)
            send({"type": "dividends:ingested", "path": path, "added": int(added)})
        except Exception as exc:  # noqa: BLE001
            send({"type": "dividends:error", "path": path, "error": str(exc)})

    # Warm values cache
    for path in storage.list_portfolio_paths():
        try:
            vprint(f"startup: warm_values {path}")
            updated = warm_values_cache_for_portfolio(path)
            send({"type": "values:warmed", "path": path, "updated": int(updated)})
        except Exception as exc:  # noqa: BLE001
            send({"type": "values:error", "path": path, "error": str(exc)})

    # Rebuild journals now that values are up to date
    for path in storage.list_portfolio_paths():
        try:
            vprint(f"startup: rebuild_journal {path}")
            build_journal_csv_streaming(path)
            send({"type": "journal:rebuilt", "path": path})
        except Exception as exc:  # noqa: BLE001
            send({"type": "journal:error", "path": path, "error": str(exc)})

    send({"type": "startup:complete"})

    # Task loop: handle on-demand jobs from UI, with periodic maintenance
    last_maint = time.time()
    last_realtime = 0.0
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

        # Periodic maintenance: warm values and rebuild journals every few minutes while running
        now = time.time()
        if now - last_maint > 180:
            for path in storage.list_portfolio_paths():
                try:
                    updated = warm_values_cache_for_portfolio(path)
                    if updated:
                        send({"type": "values:warmed", "path": path, "updated": int(updated)})
                        build_journal_csv_streaming(path)
                        send({"type": "journal:rebuilt", "path": path})
                except Exception as exc:  # noqa: BLE001
                    send({"type": "maintenance:error", "path": path, "error": str(exc)})
            last_maint = now

        # Periodic realtime price refresh (lightweight, every ~60s)
        if now - last_realtime > 60:
            try:
                syms = list(collect_all_symbols())
            except Exception:
                syms = []
            for s in syms:
                try:
                    if update_realtime_price_cache(s):
                        send({"type": "realtime:updated", "symbol": s})
                except Exception as exc:  # noqa: BLE001
                    send({"type": "realtime:error", "symbol": s, "error": str(exc)})
            if syms:
                send({"type": "realtime:batch"})
            last_realtime = now

        if task is None:
            continue
        ttype = str(task.get("type", ""))
        if ttype == "stop":
            send({"type": "worker:stopping"})
            break
        if ttype == "warm_values":
            path = task.get("path")
            prefer_cache = bool(task.get("prefer_cache", True))
            paths = [path] if isinstance(path, str) else list(storage.list_portfolio_paths())
            total_updated = 0
            for p in paths:
                try:
                    updated = warm_values_cache_for_portfolio(p, prefer_cache=prefer_cache)
                    # After warming, rebuild journal for that portfolio
                    build_journal_csv_streaming(p)
                except Exception as exc:  # noqa: BLE001
                    send({"type": "values:error", "path": p, "error": str(exc)})
                    continue
                total_updated += int(updated)
                send({"type": "values:warmed", "path": p, "updated": int(updated)})
                send({"type": "journal:rebuilt", "path": p})
            if total_updated:
                send({"type": "values:done", "updated": total_updated})
                # Touch portfolio file mtime to signal UI reloads if needed
                try:
                    for p in paths:
                        try:
                            with open(p, "a", encoding="utf-8") as _f:
                                _f.write("")
                        except Exception:
                            pass
                except Exception:
                    pass
            continue
        if ttype == "ingest_dividends":
            path = task.get("path")
            paths = [path] if isinstance(path, str) else list(storage.list_portfolio_paths())
            total_added = 0
            for p in paths:
                try:
                    added = cache_and_ingest_dividends_for_file(p)
                    if added:
                        # Warm values and rebuild journal if new dividends affected DRIP or cash
                        warm_values_cache_for_portfolio(p)
                        build_journal_csv_streaming(p)
                except Exception as exc:  # noqa: BLE001
                    send({"type": "dividends:error", "path": p, "error": str(exc)})
                    continue
                total_added += int(added)
                send({"type": "dividends:ingested", "path": p, "added": int(added)})
                send({"type": "journal:rebuilt", "path": p})
            if total_added:
                send({"type": "dividends:done", "added": total_added})
                try:
                    for p in paths:
                        try:
                            with open(p, "a", encoding="utf-8") as _f:
                                _f.write("")
                        except Exception:
                            pass
                except Exception:
                    pass
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
        if ttype == "realtime:update_all":
            syms = list(collect_all_symbols())
            updated_any = False
            for s in syms:
                try:
                    if update_realtime_price_cache(s):
                        updated_any = True
                        send({"type": "realtime:updated", "symbol": s})
                except Exception as exc:  # noqa: BLE001
                    send({"type": "realtime:error", "symbol": s, "error": str(exc)})
            if updated_any:
                send({"type": "realtime:done", "count": len(syms)})
            continue


_progress_queue: Optional[mp.Queue] = None
_task_queue: Optional[mp.Queue] = None
_proc: Optional[mp.Process] = None
_ctx: Optional[mp.context.BaseContext] = None


def get_progress_queue() -> Optional[mp.Queue]:
    return _progress_queue


def run_startup_tasks_in_background() -> None:
    global _progress_queue, _task_queue, _proc, _ctx
    if _proc is not None and _proc.is_alive():
        return
    # Use spawn to avoid copying the UI process via fork
    _ctx = mp.get_context("spawn")
    _progress_queue = _ctx.Queue()
    _task_queue = _ctx.Queue()
    _proc = _ctx.Process(target=_run_all, args=(_progress_queue, _task_queue), name="startup-tasks", daemon=True)
    _proc.start()


def get_task_queue() -> Optional[mp.Queue]:
    return _task_queue
