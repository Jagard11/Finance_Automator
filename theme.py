from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

import settings


_DEFAULT_FONTS = {
    "TkDefaultFont": ("Atkinson Hyperlegible", 10),
    "TkTextFont": ("Atkinson Hyperlegible", 10),
    "TkFixedFont": ("Atkinson Hyperlegible", 10),
    "TkMenuFont": ("Atkinson Hyperlegible", 10),
    "TkHeadingFont": ("Atkinson Hyperlegible", 11, "bold"),
    "TkIconFont": ("Atkinson Hyperlegible", 10),
    "TkTooltipFont": ("Atkinson Hyperlegible", 9),
}


class FontScaler:
    def __init__(self, root: tk.Tk, initial_scale: float) -> None:
        self.root = root
        self.scale = max(0.5, min(initial_scale, 3.0))
        self._init_named_fonts()
        self.apply_scale()

    def _init_named_fonts(self) -> None:
        def resolve_family(requested: str) -> str:
            try:
                families = list(tkfont.families())
            except Exception:
                families = []
            normalized = {f.replace(" ", "").replace("-", "").lower(): f for f in families}
            req_norm = requested.replace(" ", "").replace("-", "").lower()
            if req_norm in normalized:
                return normalized[req_norm]
            # Try fuzzy match for Atkinson family names
            if "atkinson" in req_norm:
                for key, actual in normalized.items():
                    if "atkinson" in key and "hyperlegible" in key:
                        return actual
            # Fallback to a sane default
            return "Sans"

        for name, (family, size, *style) in _DEFAULT_FONTS.items():
            try:
                f = tkfont.nametofont(name)
            except tk.TclError:
                f = tkfont.Font(name=name, exists=False)
            f.config(family=resolve_family(family), size=size, weight=(style[0] if style else "normal"))

    def apply_scale(self) -> None:
        for name in _DEFAULT_FONTS.keys():
            f = tkfont.nametofont(name)
            base = _DEFAULT_FONTS[name][1]
            f.configure(size=max(6, int(round(base * self.scale))))
        # Scale common widget metrics
        style = ttk.Style(self.root)
        base_row = 22
        style.configure("Treeview", rowheight=max(16, int(round(base_row * self.scale))))
        # Increase control heights to avoid cropped text
        pad_v = max(2, int(round(4 * self.scale)))
        pad_h = max(4, int(round(6 * self.scale)))
        style.configure("TEntry", padding=(pad_h, pad_v))
        style.configure("TCombobox", padding=(pad_h, pad_v))
        style.configure("TButton", padding=(pad_h, pad_v))
        # Force redraw
        self.root.update_idletasks()

    def update_scale(self, new_scale: float) -> None:
        self.scale = max(0.5, min(new_scale, 3.0))
        self.apply_scale()
        s = settings.load_settings()
        s["font_scale"] = self.scale
        settings.save_settings(s)
        # Broadcast a virtual event so views can react (e.g., update charts/fonts/column widths)
        try:
            # Generate on root and globally so any nested frames receive it
            self.root.event_generate("<<FontScaleChanged>>", when="tail")
            self.root.event_generate("<<FontScaleChanged>>", when="tail", state=0)
        except Exception:
            pass


def apply_dark_theme(root: tk.Tk) -> FontScaler:
    s = settings.load_settings()
    scaler = FontScaler(root, float(s.get("font_scale", 1.25)))

    bg = "#121212"
    surface = "#1e1e1e"
    text = "#ffffff"
    text_muted = "#cccccc"
    accent = "#0a84ff"
    select_bg = "#264F78"

    root.configure(bg=bg)

    # Tk option database for classic widgets (e.g., Listbox)
    root.option_add("*background", surface)
    root.option_add("*foreground", text)
    # Ensure classic widgets default to the app font
    try:
        root.option_add("*Font", "TkDefaultFont")
    except Exception:
        pass
    root.option_add("*Listbox.background", surface)
    root.option_add("*Listbox.foreground", text)
    root.option_add("*Listbox.selectBackground", select_bg)
    root.option_add("*Listbox.selectForeground", text)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # Base surfaces
    style.configure("TFrame", background=bg)
    style.configure("TLabelframe", background=bg)
    style.configure("TLabelframe.Label", background=bg, foreground=text)
    style.configure("TLabel", background=bg, foreground=text)
    style.configure("TCheckbutton", background=bg, foreground=text)

    # Ensure ttk widgets inherit the application font
    try:
        default_font = tkfont.nametofont("TkDefaultFont")
        heading_font = tkfont.nametofont("TkHeadingFont")
        style.configure("TLabel", font=default_font)
        style.configure("TButton", font=default_font)
        style.configure("TCheckbutton", font=default_font)
        style.configure("TEntry", font=default_font)
        style.configure("TCombobox", font=default_font)
        style.configure("TNotebook.Tab", font=default_font)
        style.configure("Treeview", font=default_font)
        style.configure("Treeview.Heading", font=heading_font)
    except Exception:
        pass

    # Notebook and tabs
    style.configure("TNotebook", background=bg, borderwidth=0)
    style.configure("TNotebook.Tab", background=surface, foreground=text_muted)
    style.map(
        "TNotebook.Tab",
        background=[("selected", surface)],
        foreground=[("selected", text)],
    )

    # Buttons
    style.configure("TButton", background=surface, foreground=text)
    style.map(
        "TButton",
        background=[("active", "#2a2a2a"), ("pressed", "#333333")],
        foreground=[("disabled", "#777777")],
    )

    # Entries and combos
    style.configure("TEntry", fieldbackground=surface, background=surface, foreground=text)
    style.configure("TCombobox", fieldbackground=surface, background=surface, foreground=text)
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", surface)],
    )

    # Paned window
    style.configure("TPanedwindow", background=bg)

    # Treeview
    style.configure(
        "Treeview",
        background=surface,
        fieldbackground=surface,
        foreground=text,
        bordercolor=surface,
        lightcolor=surface,
        darkcolor=surface,
        rowheight=max(16, int(round(22 * scaler.scale))),
    )
    style.map(
        "Treeview",
        background=[("selected", select_bg)],
        foreground=[("selected", text)],
    )
    style.configure("Treeview.Heading", background=surface, foreground=text_muted)
    style.map(
        "Treeview.Heading",
        background=[("active", surface)],
        foreground=[("!disabled", text)],
    )

    return scaler
