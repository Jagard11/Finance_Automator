import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from datetime import datetime
from typing import Dict, List, Optional

import os
import time
import pandas as pd
import math

import storage
from models import Portfolio
from journal_builder import journal_csv_path, rebuild_journal_in_background
import settings


def build_journal_ui(parent: tk.Widget) -> None:
	portfolio = storage.load_portfolio()

	# Status row (shows when journal is building/loading)
	status_row = ttk.Frame(parent)
	status_row.pack(fill="x", padx=8, pady=(6, 0))
	status_var = tk.StringVar(value="")
	status_label = ttk.Label(status_row, textvariable=status_var)
	status_label.pack(side="left")
	status_bar = ttk.Progressbar(status_row, mode="indeterminate", length=120)
	# status_bar is started/stopped dynamically; keep it packed when active only

	def show_status(text: str, spinning: bool = False) -> None:
		status_var.set(text)
		# Update tab label suffix if handler is attached
		try:
			setter = getattr(parent, "_journal_set_tab_suffix", None)
			if callable(setter):
				suffix = ""
				if spinning and text:
					suffix = " (" + text.replace("...", "").strip() + "...)"
				elif text:
					suffix = " (" + text + ")"
				setter(suffix)
		except Exception:
			pass
		if spinning:
			try:
				status_bar.pack(side="left", padx=(8, 0))
				status_bar.start(50)
			except Exception:
				pass
		else:
			try:
				status_bar.stop()
				status_bar.pack_forget()
			except Exception:
				pass

	# Fonts
	default_font = tkfont.nametofont("TkDefaultFont")
	highlight_font = tkfont.Font(family=default_font.cget("family"), size=default_font.cget("size"), weight="bold", underline=1)

	# Virtualized sheet for large tables with per-cell styling
	from tksheet import Sheet  # type: ignore
	container = ttk.Frame(parent)
	container.pack(fill="both", expand=True)
	container.grid_rowconfigure(0, weight=1)
	container.grid_columnconfigure(0, weight=1)
	
	sheet = Sheet(container)
	# Dark theme to avoid white flash and match app theme
	# Resolve font tuples for tksheet (expects tuples like (family, size, style))
	try:
		_base_family = default_font.cget("family")
		_base_size = int(default_font.cget("size"))
		head_f = tkfont.nametofont("TkHeadingFont")
		_head_family = head_f.cget("family")
		_head_size = int(head_f.cget("size"))
		_table_font = (_base_family, _base_size, "normal")
		_index_font = (_base_family, _base_size, "normal")
		_header_font = (_head_family, _head_size, "bold")
	except Exception:
		_table_font = ("Sans", 10, "normal")
		_index_font = ("Sans", 10, "normal")
		_header_font = ("Sans", 11, "bold")

	sheet.set_options(
		table_bg="#1e1e1e",
		table_fg="#dddddd",
		header_bg="#2b2b2b",
		header_fg="#ffffff",
		# Match row index (row numbers) styling to header to honor dark theme
		index_bg="#2b2b2b",
		index_fg="#ffffff",
		index_border_fg="#333333",
		top_left_bg="#2b2b2b",
		header_border_fg="#333333",
		table_grid_fg="#2a2a2a",
		row_height=24,
		header_height=28,
		# Ensure tksheet uses the app's fonts
		table_font=_table_font,
		header_font=_header_font,
		index_font=_index_font,
	)
	sheet.enable_bindings((
		"single_select",
		"row_select",
		"column_select",
		"arrowkeys",
		"right_click_popup_menu",
		"rc_insert_row",
		"rc_delete_row",
		"rc_insert_column",
		"rc_delete_column",
		"copy",
		"cut",
		"paste",
		"edit_cell",
	))
	sheet.grid(row=0, column=0, sticky="nsew")

	# Persist and restore column widths
	def _apply_saved_layout() -> None:
		try:
			s = settings.load_settings()
			tab = s.get("journal", {})
			saved = tab.get("columns", [])
			if isinstance(saved, list) and saved:
				for c, w in enumerate(saved):
					try:
						w_int = int(w)
						if w_int > 0:
							sheet.column_width(c, width=w_int)
					except Exception:
						continue
		except Exception:
			pass

	def _save_state() -> None:
		try:
			s = settings.load_settings()
			tab = dict(s.get("journal", {}))
			widths: List[int] = []
			try:
				ncols = sheet.total_columns()
			except Exception:
				ncols = 0
			for c in range(ncols):
				w = None
				try:
					# Prefer explicit getter if available
					w = int(sheet.get_column_width(c))
				except Exception:
					try:
						# Fallback: column_width can also return current width if width is None in some versions
						w = int(sheet.column_width(c))  # type: ignore[misc]
					except Exception:
						w = None
				if isinstance(w, int) and w > 0:
					widths.append(w)
			tab["columns"] = widths
			s["journal"] = tab
			settings.save_settings(s)
		except Exception:
			pass

	try:
		parent.bind_all("<<PersistUIState>>", lambda _e: _save_state())
	except Exception:
		pass

	journal_path = journal_csv_path()
	last_mtime = os.path.getmtime(journal_path) if os.path.exists(journal_path) else 0.0
	last_refresh = 0.0
	journal_active = False

	def read_journal() -> pd.DataFrame:
		if not os.path.exists(journal_path):
			return pd.DataFrame()
		try:
			df = pd.read_csv(journal_path)
			if df.empty or df.shape[1] <= 1:
				return pd.DataFrame()
			df["date"] = pd.to_datetime(df["date"]).dt.date
			df.set_index("date", inplace=True)
			return df
		except Exception:
			return pd.DataFrame()

	def refresh_grid() -> None:
		nonlocal last_refresh
		now = time.time()
		if now - last_refresh < 1.0:
			return
		last_refresh = now
		df = read_journal()
		if df is None or df.empty:
			show_status("Building journal...", spinning=True)
			rebuild_journal_in_background()
			return
		show_status("Rendering journal...", spinning=True)
		# Drop all-empty columns (symbols with no values)
		df = df.dropna(axis=1, how="all")
		if df.shape[1] == 0:
			show_status("No journal data available yet.", spinning=False)
			return
		symbols = list(df.columns)
		# Build data matrix
		rows = list(df.index)
		data: List[List[str]] = []
		for d in rows:
			row: List[str] = [getattr(d, "isoformat", lambda: str(d))()]
			for sym in symbols:
				val = df.at[d, sym]
				if pd.isna(val):
					row.append("")
					continue
				try:
					num = float(val)
					dollars = math.ceil(num)
					row.append(f"${dollars:,}")
				except Exception:
					row.append(str(val))
			data.append(row)
		
		# Set headers and data
		sheet.headers(["date"] + symbols)
		sheet.set_sheet_data(data, reset_highlights=True, redraw=False)
		# Apply saved layout now that columns exist
		_apply_saved_layout()
		nrows = len(data)
		# Center align headers and columns
		for c in range(len(symbols) + 1):
			try:
				sheet.align_header(c, align="center")
				sheet.align_column(c, align="center")
			except Exception:
				pass
		
		# Compute per-symbol ATHs and defer styling to next idle to keep first paint instant
		ath_targets: List[tuple[int, int]] = []
		# Build a robust map from date->row index for precise targeting
		row_index_map: Dict[pd.Timestamp, int] = {}
		for idx, d in enumerate(rows):
			try:
				row_index_map[pd.Timestamp(d)] = idx
			except Exception:
				try:
					row_index_map[pd.to_datetime(d)] = idx
				except Exception:
					continue
		for col_idx, sym in enumerate(symbols, start=1):
			try:
				coln = pd.to_numeric(df[sym], errors="coerce")
				if coln.isna().all():
					continue
				max_label = coln.idxmax()
				# Resolve row position using the map to avoid type mismatches
				try:
					row_pos = row_index_map[pd.Timestamp(max_label)]
				except Exception:
					try:
						row_pos = row_index_map[pd.to_datetime(max_label)]
					except Exception:
						continue
				ath_targets.append((row_pos, col_idx))
				valtxt = sheet.get_cell_data(row_pos, col_idx)
				if not str(valtxt).startswith("▲ "):
					sheet.set_cell_data(row_pos, col_idx, f"▲ {valtxt}", redraw=False)
			except Exception:
				continue
		
		# Separator and summary rows
		# Insert exactly one blank separator row immediately after last data row
		sep = [""] * (1 + len(symbols))
		sheet.insert_rows(rows=[sep], idx=nrows, redraw=False)
		last_row_label = ["Since ATH"]
		last_vals = []
		for sym in symbols:
			try:
				coln = pd.to_numeric(df[sym], errors="coerce").ffill()
				if coln.isna().all():
					last_vals.append("")
					continue
				ath = float(coln.max())
				ath_date = coln.idxmax()
				last_v = float(coln.iloc[-1])
				days = (pd.to_datetime(rows[-1]) - pd.to_datetime(ath_date)).days
				pct = 0.0 if ath == 0 else ((last_v / ath) - 1.0) * 100.0
				last_vals.append(f"{days}d, {pct:+.2f}%")
			except Exception:
				last_vals.append("")
		last_row = last_row_label + last_vals
		# Insert summary row right after separator row
		sheet.insert_rows(rows=[last_row], idx=nrows + 1, redraw=False)
		# Ensure the last row is visually distinct by applying a subtle background
		try:
			last_index = nrows + 1
			for c in range(sheet.total_columns()):
				sheet.highlight_cells(row=last_index, column=c, bg="#203040", fg=None, border_color=None, redraw=False)
		except Exception:
			pass
		
		# Zebra striping
		sheet.set_options(table_grid_fg="#2a2a2a")
		sheet.redraw()
		# Apply bold/underline to ATH cells after first paint for responsiveness
		def _apply_ath_styles() -> None:
			for r, c in ath_targets:
				try:
					# Per-cell bold + underline, plus a bright foreground for visibility
					sheet.highlight_cells(row=r, column=c, bg=None, fg="#ffd166", border_color=None, redraw=False, font=highlight_font)
				except Exception:
					pass
			sheet.redraw()
		parent.after(0, _apply_ath_styles)
		show_status("Journal ready", spinning=False)
		parent.after(1500, lambda: show_status("", spinning=False))

	def poll_for_updates() -> None:
		nonlocal last_mtime
		try:
			m = os.path.getmtime(journal_path) if os.path.exists(journal_path) else 0.0
		except Exception:
			m = last_mtime
		if m > last_mtime:
			last_mtime = m
			refresh_grid()
		parent.after(1000, poll_for_updates)

	def reload_and_refresh() -> None:
		try:
			dfnt = tkfont.nametofont("TkDefaultFont")
			highlight_font.configure(family=dfnt.cget("family"), size=dfnt.cget("size"))
		except Exception:
			pass
		refresh_grid()

	parent.bind("<<FontScaleChanged>>", lambda _e: reload_and_refresh())

	# Initial content and polling
	show_status("Waiting to build journal...", spinning=False)
	parent.after(1000, poll_for_updates)

	# Expose hooks
	setattr(parent, "_journal_refresh", reload_and_refresh)
	def set_active(active: bool) -> None:
		nonlocal journal_active
		journal_active = active
		if active:
			refresh_grid()
	setattr(parent, "_journal_set_active", set_active)


def register_journal_tab_handlers(notebook: ttk.Notebook, journal_frame: tk.Widget) -> None:
	def on_tab_changed(_evt=None):  # noqa: ANN001
		try:
			current = notebook.select()
			if current == str(journal_frame):
				setter = getattr(journal_frame, "_journal_set_active", None)
				if callable(setter):
					setter(True)
				fn = getattr(journal_frame, "_journal_refresh", None)
				if callable(fn):
					fn()
			else:
				setter = getattr(journal_frame, "_journal_set_active", None)
				if callable(setter):
					setter(False)
		except Exception:
			pass
	notebook.bind("<<NotebookTabChanged>>", on_tab_changed)
