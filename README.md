# Piggy Bank

A personal finance analyser for **Banca Etica** current-account statements ("Estratto conto Italia" exports).

It merges yearly statement exports into a single ledger, lets you exclude ("blacklist") movements that would distort the picture (e.g. money moved into investments), and explores the result in a desktop GUI:

- **Ledger**: a sortable table of every movement, live filters (in/out, amount ranges, description text, date range, blacklisted/investment modes), and a running total recomputed over the visible rows.
- **Aggregate stats**: count, min, max, sum, median, mean and std for all/outgoing/incoming movements.
- **Plots** (Plotly, interactive): running total with an OLS trend line, weekly/monthly/yearly balance candlesticks, amount histograms, day-of-week / day-of-month / month-of-year sums, and expense/income box plots.

There is also a headless script and a Jupyter notebook that use the same pipeline.

## Requirements

- Python ≥ 3.10
- PySide6 with QtWebEngine (installed with `PySide6`), which renders the plots
- Network access when viewing plots: `plotly.js` is loaded from a CDN

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'          # add ',notebook' for JupyterLab
./driver.sh -b                   # generate the Qt UI modules (piggy_bank/ui/*_rc.py)
```

Use an **editable** install (`-e`): the data directory is resolved relative to the source tree.

## Data

Put the exports in `data/etica/` (gitignored, so it never gets committed):

| File | Purpose |
|------|---------|
| `*.xls` | Raw exports from home banking. On load they are converted to `*.csv` and **the `.xls` is deleted**, so keep a backup elsewhere. |
| `*.csv` | Statements in `Data contabile,Dare,Avere,Descrizione` format. All of them are merged. |
| `blacklist.csv` | Optional. Movements to exclude from the "net" view (same columns). |
| `merged.csv` | Output only: the merged, sorted ledger is written here on each load. |

Files with any other extension (e.g. `*.csv.bk`) are ignored.

### Blacklist

Each row of `blacklist.csv` is one of:

- **Exact entry**: `Data contabile` plus `Dare` and/or `Avere`. It must match exactly one movement; loading fails if it matches more than one.
- **Wildcard entry**: `Dare` and `Avere` empty, `Descrizione` set. It flags every movement whose description contains that text (case-sensitive).

```csv
Data contabile,Dare,Avere,Descrizione
2026-01-14,-20000,,Versamento fondo
,,,GIROCONTO
```

### Known limitation: duplicate movements

Exports can overlap (e.g. a full-year file and a partial "bis" file), so exact duplicate rows are removed after merging. The bank exports carry no transaction ID. As a result, two genuinely distinct but identical movements (same date, amount and description, e.g. two SEPA fees on the same day) are collapsed into one. This is accepted; a warning is logged for every duplicate found.

## Usage

```bash
./driver.sh -r   # build UI and launch the GUI
./driver.sh -i   # headless: load and print the ledgers
./driver.sh -b   # rebuild the UI modules only
./driver.sh -d   # open Qt Designer to edit piggy_bank/ui/*.ui
./driver.sh -t   # build UI and run the test suite
```

Or launch the GUI through the installed entry point: `piggy-bank`.

For the notebook, open `piggy_bank/etica.ipynb` in JupyterLab.

## Tests

```bash
./driver.sh -t                  # builds the UI first, so the widget tests aren't skipped
./driver.sh -t -k blacklist -v  # extra arguments are passed to pytest
```

The widget tests run headless (`QT_QPA_PLATFORM=offscreen`). They are skipped if the UI modules haven't been generated with `./driver.sh -b`.

## License

GPL-3.0, see [LICENSE](LICENSE).
