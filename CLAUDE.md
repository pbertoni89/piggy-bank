# CLAUDE.md

Piggy Bank is a personal finance analyser for Banca Etica ("Estratto conto Italia") bank statement exports. It has a PySide6 desktop GUI and also a headless/notebook path. Column names and some log messages are in Italian.

## Commands

Everything runs through `driver.sh`, which activates `.venv/` first:

```bash
./driver.sh -b   # compile ui/*.ui -> ui/*_rc.py with pyside6-uic
./driver.sh -r   # build the UI, then run the GUI (PYTHONPATH=. python piggy_bank/main_window.py)
./driver.sh -i   # headless pipeline: load data, print the DataFrames (piggy_bank/driver.py)
./driver.sh -d   # open Qt Designer
./driver.sh -t   # build the UI, then run pytest (extra args are passed through, e.g. -t -k blacklist)
```

- `driver.sh` only reads the first flag, so you can't combine them.
- Run Python from the repo root with `PYTHONPATH=.`. Imports are absolute (`from piggy_bank.etica import *`).
- `piggy_bank/etica.ipynb` runs the same steps as `driver.py`, plus matplotlib/plotly plots.
- Tests: `./driver.sh -t` or `.venv/bin/python -m pytest` (configured in `pyproject.toml`, `pythonpath = ["."]`).
  - `tests/test_load_data.py` covers the ingestion pipeline. Its `data_dir` fixture monkeypatches `etica.DATA_DIR` to a tmp dir, and `write_csv` writes statement/blacklist CSVs. Never point tests at the real `data/`.
  - `tests/test_compute.py` covers the pure computations.
  - `tests/test_widgets.py` uses pytest-qt, runs offscreen, and is skipped if `*_rc.py` haven't been built. `MainWindow` isn't tested (QtWebEngine).
- Install: `pip install -e '.[dev]'`. It must be editable, because `DATA_DIR` is resolved relative to the source tree.

## Dependencies gotchas

- **superqt** provides `QRangeSlider`, which `filter_tools.ui` promotes to (header `superqt`).
- Plots need `PySide6.QtWebEngineWidgets`. Without it, `WebEnginePlotManager` shows a placeholder label instead of plots.
- Plotly HTML loads `plotly.js` from a CDN (`include_plotlyjs='cdn'`), so plots need network access.

## Generated files: never edit `*_rc.py`

`piggy_bank/ui/*_rc.py` are pyside6-uic output (gitignored). To change a layout, edit the `.ui` file in Designer (or the XML), then run `./driver.sh -b`. Each `X.ui` produces `X_rc.py` with class `Ui_<RootWidgetName>`. Python widgets use multiple inheritance (`class Foo(QWidget, Ui_Foo)` + `self.setupUi(self)`).

## Data (sensitive, gitignored)

The data lives in `data/etica/` (`DATA_DIR` in `etica.py`). It is real personal bank data: don't print it in bulk, copy it elsewhere or commit it. `data/etica-virgin/` holds the original `.xls` exports as a pristine backup.

`etica.load_data()` is the single ingestion pipeline. It **mutates `DATA_DIR`** as it runs:
1. Converts each `*.xls` to `*.csv` (dropping `Valuta`, `Divisa`, `Causale`) and **deletes the `.xls`**.
2. Loads every `*.csv` except `blacklist.csv` and `merged.csv`. Files like `*.csv.bk` are ignored because they don't match the glob. Watch out for overlapping exports, e.g. `-2024.csv` + `-2024-bis.csv`.
3. Concatenates them and drops exact duplicate rows. **Known, accepted limitation:** this also collapses genuinely distinct identical movements, e.g. two SEPA fees on the same day. The exports have no transaction ID, so there's no reliable way to tell those apart from overlapping exports. Don't try to "fix" it unless asked. `test_identical_rows_are_collapsed_known_limitation` pins this behaviour.
4. Sorts by date with deterministic tiebreakers (`sort_by_data_contabile`) and rewrites `merged.csv` (output only, never read back).
5. Applies `blacklist.csv` to set `Blacklisted` = 0/1:
   - **Exact row**: `Data contabile` plus `Dare` and/or `Avere`. It must match exactly one row; more than one raises `ValueError`, zero logs an error.
   - **Wildcard row**: `Dare` and `Avere` empty, `Descrizione` set. Case-sensitive substring match on description.
   - A row with no `Dare`, `Avere` or `Descrizione` (even if it has a date) counts as empty and is dropped.
6. Rewrites noisy `Descrizione` fragments (the hardcoded `stripped_parts` list, e.g. → `<BONIF>`).

Column constants (use these, not string literals): `COL_DATA`='Data contabile', `COL_MINUS`='Dare' (outflows, negative), `COL_PLUS`='Avere' (inflows), `COL_DESCR`='Descrizione', `COL_INV`='Blacklisted', `COL_RUN_TOT`='Running Total', `COL_IMP`='Importo', `COL_OLS`='OLS'. Amount = `Avere.fillna(0) + Dare.fillna(0)`.

"Blacklisted" means excluded from the "net" view, e.g. transfers in and out of investments. Investments are detected by `etica.INV_REGEX` (case-sensitive) on the description. Both `filter_investments` and `MainWindow` use it, so don't hardcode the pattern anywhere else.

## Architecture

- `etica.py`: pure pandas/numpy logic (loading, `compute_importo`, `compute_ols` linear fit of the running total vs date ordinal, `compute_candlesticks` OHLC resample) plus matplotlib/plotly helpers for the notebook. It has no Qt imports, so keep it that way.
- `main_window.py`: `MainWindow` and `main()`. `get_data_source()` calls `load_data()`, adds the running total, checks the required columns, and formats dates as `YYYY-MM-DD` strings.
  - The ledger `QTableWidget` is the source of truth for filtering. `_apply_filters()` walks the table rows, hides the rows that fail the filters, and recomputes the `Running Total` cells chronologically over the *visible* rows only. It builds `self.df_plot` and calls `_update_plot()`, which redraws every Plotly figure (line+OLS, amount histogram, weekday/day-of-month/month histogram, candlesticks, box plots).
  - The weekday histogram deliberately raises if any transaction falls on a Saturday (a sanity check).
- `filter_tools.py`: `FilterTools` widget (direction checkboxes, `QRangeSlider` amount ranges, description text, date range, two independent radio groups, reset).
  - `brg_bl` (`qrb_bl_all/force/veto`) and `brg_inv` (`qrb_inv_all/force/veto`): **All** = no constraint, **Force** = keep only matching rows, **Veto** = drop matching rows. "Matching" means `Blacklisted == 1` for BL and an `INV_REGEX` hit for INV. Both groups apply together (AND).
  - The groups are wired through the `QButtonGroup`s that uic generates (`brg.buttonToggled` → `_on_brg_buttonToggled`, `checkedButton()` for defaults). Group membership lives only in the `.ui`, so don't keep Python lists of radios. Each group's default is whichever radio has `checked=true` in the `.ui` (the **All** ones). It's captured at init in `__brg_defaults` and restored by reset. A group with no checked radio raises at startup. It emits `filters_updated`, debounced with a 1 s single-shot `QTimer` for sliders and text.
- `aggr_stats.py`: `AggrStats` box (All/Out/In summary stats over the visible values).
- `qw_misc.py`: `WebEnginePlotManager` (renders a `go.Figure` to HTML in a `QWebEngineView`, dark theme `#111111`), `NumericTableWidgetItem` (numeric sort), and thin wrappers `Ledger`, `PlotsLines`, `PlotsStats` that load their `.ui` files.
- The main window has tabs whose layouts (`ql_ledger`, `ql_plots_lines`, `ql_plots_stats`, `qvl_aggr_stats`) get the sub-widgets inserted at runtime.

## Conventions

- Qt widget names use a type prefix: `qpb_` push button, `qrb_` radio, `qchk_` checkbox, `qle_` line edit, `qde_` date edit, `qrs_` range slider, `qcb_` combo box, `qtw_` table, `ql_`/`qvl_` layouts (also `ql_` labels in FilterTools), `qgb_` group box.
- Slots are named `_on_<widget>_<signal>` and decorated with `@Slot(...)`.
- Wrap programmatic widget updates in `blockSignals(True/False)` so they don't trigger filter cascades.
- Logging goes through the stdlib `logging` module, configured via `etica.init_logging()`.
- Modules use `from piggy_bank.etica import *` to get the constants, `pd`, `np`, `logging`, etc.
