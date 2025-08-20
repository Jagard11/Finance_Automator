import tkinter as tk
from tkinter import ttk

from portfolio_ui import build_portfolio_ui
from charts_ui import build_charts_ui
from theme import apply_dark_theme


def main() -> None:
    root = tk.Tk()
    root.title("Finance Automator")
    root.geometry("1000x700")

    apply_dark_theme(root)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    portfolio_frame = ttk.Frame(notebook)
    charts_frame = ttk.Frame(notebook)

    notebook.add(portfolio_frame, text="Portfolio")
    notebook.add(charts_frame, text="Charts")

    build_portfolio_ui(portfolio_frame)
    build_charts_ui(charts_frame)

    root.mainloop()


if __name__ == "__main__":
    main()
