import tkinter as tk
from tkinter import ttk
import time
import sys
from contextlib import contextmanager
from time import perf_counter

from portfolio_ui import build_portfolio_ui
from charts_ui import build_charts_ui, register_charts_tab_handlers
from summary_ui import build_summary_ui, register_summary_tab_handlers
from journal_ui import build_journal_ui, register_journal_tab_handlers
from theme import apply_dark_theme
from startup_tasks import run_startup_tasks_in_background, get_progress_queue


def main() -> None:
    root = tk.Tk()
    root.title("Finance Automator")
    root.geometry("1100x800")

    scaler = apply_dark_theme(root)

    # Zoom handlers: Ctrl + MouseWheel (Windows), Ctrl + Button-4/5 (Linux), Ctrl+0 reset
    def on_ctrl_mousewheel(event: tk.Event) -> None:  # type: ignore[override]
        if (event.state & 0x0004) == 0:  # Control not pressed
            return
        delta = getattr(event, "delta", 0)
        if delta == 0:
            # Linux: use num 4/5
            num = getattr(event, "num", None)
            if num == 4:
                delta = 120
            elif num == 5:
                delta = -120
        step = 0.05
        if delta > 0:
            scaler.update_scale(scaler.scale + step)
        elif delta < 0:
            scaler.update_scale(scaler.scale - step)

    def on_reset(_evt=None) -> None:  # noqa: ANN001
        scaler.update_scale(1.25)

    root.bind_all("<Control-MouseWheel>", on_ctrl_mousewheel)
    root.bind_all("<Control-Button-4>", on_ctrl_mousewheel)
    root.bind_all("<Control-Button-5>", on_ctrl_mousewheel)
    root.bind_all("<Control-Key-0>", on_reset)
    root.bind_all("<Control-KP_0>", on_reset)

    # Kick off startup tasks (prefetch) without blocking UI
    run_startup_tasks_in_background()

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    summary_frame = ttk.Frame(notebook)
    portfolio_frame = ttk.Frame(notebook)
    charts_frame = ttk.Frame(notebook)
    journal_frame = ttk.Frame(notebook)

    notebook.add(summary_frame, text="Summary")
    notebook.add(portfolio_frame, text="Portfolio")
    notebook.add(charts_frame, text="Charts")
    notebook.add(journal_frame, text="Journal")

    build_summary_ui(summary_frame)
    build_portfolio_ui(portfolio_frame)
    build_charts_ui(charts_frame)
    build_journal_ui(journal_frame)

    register_summary_tab_handlers(notebook, summary_frame)
    register_charts_tab_handlers(notebook, charts_frame)
    # Inject a helper so the journal tab can set a suffix while building
    def set_journal_tab_suffix(suffix: str) -> None:
        try:
            idx = notebook.index(journal_frame)
            base = "Journal"
            notebook.tab(idx, text=base + suffix)
        except Exception:
            pass
    setattr(journal_frame, "_journal_set_tab_suffix", set_journal_tab_suffix)

    register_journal_tab_handlers(notebook, journal_frame)

    # Lightweight IPC polling with rate limiting (<= 10 fps)
    last_ui_refresh = 0.0

    # Optional debug-stall profiler
    DEBUGSTALL = any(arg == "--debugstall" for arg in sys.argv)

    class FrameProfiler:
        def __init__(self, enabled: bool) -> None:
            self.enabled = enabled
            self.current_frame_totals = {}
            self.batch_totals = {}
            self.batch_counts = {}
            self.frames_in_batch = 0

        def start_frame(self) -> None:
            if not self.enabled:
                return
            self.current_frame_totals = {}

        @contextmanager
        def section(self, label: str):
            if not self.enabled:
                yield
                return
            t0 = perf_counter()
            try:
                yield
            finally:
                dt = (perf_counter() - t0)
                self.current_frame_totals[label] = self.current_frame_totals.get(label, 0.0) + dt

        def end_frame(self) -> None:
            if not self.enabled:
                return
            for k, v in self.current_frame_totals.items():
                self.batch_totals[k] = self.batch_totals.get(k, 0.0) + v
                self.batch_counts[k] = self.batch_counts.get(k, 0) + 1
            self.frames_in_batch += 1
            if self.frames_in_batch >= 30:
                # Print top time consumers over the last 30 frames
                totals = sorted(self.batch_totals.items(), key=lambda kv: kv[1], reverse=True)
                lines = []
                for k, v in totals[:8]:
                    avg_ms = (v / max(1, self.batch_counts.get(k, 1))) * 1000.0
                    lines.append(f"{k}={v*1000.0:.1f}ms (avg {avg_ms:.2f}ms)")
                if lines:
                    print("DEBUGSTALL: last 30 frames -> " + "; ".join(lines))
                # Reset batch
                self.batch_totals.clear()
                self.batch_counts.clear()
                self.frames_in_batch = 0

    profiler = FrameProfiler(DEBUGSTALL)

    def refresh_all_throttled() -> None:
        nonlocal last_ui_refresh
        now = time.time()
        # 0.15s min interval (~6-7 fps)
        if now - last_ui_refresh < 0.15:
            return
        last_ui_refresh = now
        try:
            fn = getattr(summary_frame, "_summary_refresh", None)
            if callable(fn):
                with profiler.section("refresh_summary"):
                    fn()
        except Exception:
            pass
        # Journal and Charts are self-refreshing on tab changes or file mtimes;
        # avoid triggering heavy redraws here to keep UI responsive

    def poll_worker_messages() -> None:
        profiler.start_frame()
        q = get_progress_queue()
        if q is not None:
            with profiler.section("queue_drain"):
                drained = 0
                # Read a small batch each tick to avoid UI jank
                while drained < 50:
                    try:
                        with profiler.section("queue_get"):
                            msg = q.get_nowait()
                    except Exception:
                        break
                    drained += 1
                    # On any progress affecting portfolio/caches, schedule a refresh
                    t = str(msg.get("type", ""))
                    if t.startswith("dividends:") or t.startswith("values:") or t in {"prefetch:done", "startup:complete"}:
                        with profiler.section("refresh_all"):
                            refresh_all_throttled()
        # Poll at ~10 fps
        root.after(100, poll_worker_messages)
        profiler.end_frame()

    # Start polling the background worker queue
    root.after(100, poll_worker_messages)

    # Ensure Summary is default selected tab
    notebook.select(summary_frame)

    root.mainloop()


if __name__ == "__main__":
    main()
