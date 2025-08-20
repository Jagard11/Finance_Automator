import tkinter as tk
from tkinter import ttk

from portfolio_ui import build_portfolio_ui
from charts_ui import build_charts_ui, register_charts_tab_handlers
from theme import apply_dark_theme
from startup_tasks import run_startup_tasks_in_background


def main() -> None:
    root = tk.Tk()
    root.title("Finance Automator")
    root.geometry("1000x700")

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

    # Windows/macOS style
    root.bind_all("<Control-MouseWheel>", on_ctrl_mousewheel)
    # X11 style (Linux)
    root.bind_all("<Control-Button-4>", on_ctrl_mousewheel)
    root.bind_all("<Control-Button-5>", on_ctrl_mousewheel)
    # Reset shortcuts
    root.bind_all("<Control-Key-0>", on_reset)
    root.bind_all("<Control-KP_0>", on_reset)

    # Kick off startup tasks (prefetch) without blocking UI
    run_startup_tasks_in_background()

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    portfolio_frame = ttk.Frame(notebook)
    charts_frame = ttk.Frame(notebook)

    notebook.add(portfolio_frame, text="Portfolio")
    notebook.add(charts_frame, text="Charts")

    build_portfolio_ui(portfolio_frame)
    build_charts_ui(charts_frame)
    register_charts_tab_handlers(notebook, charts_frame)

    root.mainloop()


if __name__ == "__main__":
    main()
