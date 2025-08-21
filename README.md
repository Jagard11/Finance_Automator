## Finance Automator

A desktop app for tracking an investments portfolio with live prices, dividends, and performance over time. Built with Python and Tkinter, it maintains local caches so the UI is fast and usable even with limited connectivity.

### Key features
- **Multiple portfolios**: Switch between CSV files in `data/` from the app header.
- **Background worker**: Prefetches prices/dividends, warms computed values, rebuilds journals, and updates realtime prices.
- **Local caching**: Reuses cached price history, computed values, and journals under `data/cache/`.
- **Dark theme + scalable UI**: Ctrl + MouseWheel zoom, Ctrl+0 to reset.

## Quick start
1. Ensure Python 3 is installed.
2. From the repo root, run one of:
   - Linux/macOS: `./run.sh`
   - Windows: `run.bat`
   - Or, with an existing environment: `python app.py`
3. The app creates `data/` on first run and loads `data/portfolio_default.csv`.
4. Use the header portfolio dropdown to select or switch CSVs in `data/`.

### Optional flags
- `--verbose`: log background activity to the console.

## Tabs

### Summary
High-level view of current portfolio.
- **Totals**: All-time profit (includes dividends), total value, total cost, and total dividends.
- **Today**: Portfolio day P/L ($ and %), based on last and previous closes.
- **Price age**: Shows when realtime prices were last refreshed.
- **Refresh buttons**:
  - Refresh Data: warm computed values for all symbols (rebuilds journal).
  - Refresh Realtime: update all realtime prices now.

### Portfolio
Manage holdings and events.
- **Holdings list** (left): Double-click the `--- New Symbol ---` row to add a symbol.
- **Header** (right): Company name, last price, day change, Yahoo link, and per-symbol "Dividend Reinvest" toggle.
- **Events table**: Inline-editable rows for `date`, `type` (purchase, sale, dividend, cash_deposit, cash_withdrawal), `shares`, `price`, `note`.
  - A draft "new" row is always present for quick entry.
  - Press Delete to remove selected events.
- **Edit Portfolio**: Rename or delete the active CSV file.

### Charts
Visualize price or portfolio value over time.
- **Symbols**: Sort by symbol, start date, or computed return; selection persists.
- **Modes**:
  - Price over time (default)
  - Performance over time: plots the value ($) of the position in your portfolio
- **Reference**: Optionally overlay a reference symbol on a secondary Y axis.
- **Header**: Company name, last price, day change, and Yahoo link.

### Journal
Daily matrix of per-symbol portfolio values.
- Built automatically from cached values (one CSV per portfolio).
- Highlights the all‑time high (▲) for each symbol and adds a trailing "Since ATH" summary row.
- Status bar indicates when the journal is building or rendering.

## Portfolio CSV format
Portfolios are simple CSV files in `data/`. The app writes events and cash rows with a consistent schema.

Columns:
`row_type, key, value, symbol, date, type, shares, price, amount, note`

- `row_type`: `event` for symbol activity, `cash` for portfolio-level cash events
- `type` (for events): `purchase`, `sale`, `dividend`
- `type` (for cash): `cash_deposit`, `cash_withdrawal`, `dividend`

Example rows:
```
row_type,key,value,symbol,date,type,shares,price,amount,note
event,,,AAPL,2023-01-10,purchase,10,120,,
event,,,AAPL,2023-05-10,dividend,,,5.00,DIV:AAPL
cash,,,,2023-05-10,dividend,,,5.00,DIV:AAPL
```

You can maintain portfolios entirely through the UI; the CSV format is documented for reference.

## Caching and background tasks
The background worker starts with the app and:
- Prefetches price history and dividends for all symbols it finds in portfolios.
- Warms computed value caches from first event to today.
- Rebuilds per-portfolio journals.
- Refreshes realtime prices about every minute.

Cache locations under `data/cache/`:
- `<SYMBOL>_prices.csv`: historical prices (from prefetch or yfinance)
- `<SYMBOL>_dividends.csv`: per-share dividends cache
- `<SYMBOL>_values.csv`: computed daily portfolio value for the symbol
- `<SYMBOL>_realtime.json`: latest realtime price snapshot
- `portfolioName_journal.csv`: rendered journal for a given portfolio
- `dirty_symbols.json`: marks symbols that need recomputation

If data looks stale, use Summary → Refresh Data or Refresh Realtime.

## Project layout
- `app.py`: entrypoint and tab layout (no business logic)
- `summary_ui.py`, `portfolio_ui.py`, `charts_ui.py`, `journal_ui.py`: tab UIs and handlers
- `models.py`: `Portfolio`, `Holding`, `Event`, `EventType`
- `storage.py`: read/write portfolio CSVs and list/choose active portfolio
- `prefetch.py`: download and cache price/dividend history
- `market_data.py`: API access (yfinance), realtime price caching helpers
- `dividends.py`: ingest dividends (cash or DRIP) into portfolios
- `values_cache.py`: compute and cache daily per-symbol values
- `journal_builder.py`: build per-portfolio journal CSV
- `startup_tasks.py`: background worker orchestration
- `theme.py`: dark theme and font scaling
- `settings.py`: JSON settings under `data/settings.json`

## Configuration
Settings are stored at `data/settings.json`. The app persists UI state such as:
- Font scale
- Tab-specific layout (column widths, splitters)
- Last selections and per-symbol preferences (e.g., Dividend Reinvest)

## Requirements
Python 3.9+ recommended. Dependencies are installed by the run scripts from `requirements.txt`:
`pandas`, `matplotlib`, `yfinance`, `requests`, `tksheet`.

## Troubleshooting
- If you see "No data" in Charts or empty prices, ensure the symbol exists and allow the background worker to prefetch; try Summary → Refresh Data.
- If realtime prices look stale, use Summary → Refresh Realtime.

