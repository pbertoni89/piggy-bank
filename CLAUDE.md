# CLAUDE.md

Piggy Bank is a personal finance analyser for Banca Etica ("Estratto conto Italia") bank statement exports. It has a PySide6 desktop GUI and also a headless/notebook path. Column names and some log messages are in Italian.

## Commands

Everything runs through `driver.sh` (the local options activate `.venv/` first):

```bash
./driver.sh --update-venv           # create .venv if needed, install pyproject.toml with all extras (CPU-only torch)
./driver.sh --build-gui             # compile ui/*.ui -> ui/*_rc.py with pyside6-uic
./driver.sh --run-gui               # run the GUI, without building (PYTHONPATH=. python piggy_bank/main_window.py)
./driver.sh --deprecated-headless   # load data, print a summary per view in DEFAULT_VIEWS (piggy_bank/driver.py)
./driver.sh --run-designer          # open Qt Designer
./driver.sh --build-run-tests       # build the UI, then run pytest (extra args are passed through, e.g. --build-run-tests -k blacklist)
./driver.sh -h                      # help
```

```bash
./driver.sh --docker-build-image   # build the `piggy-bank` image (see "Docker" below)
./driver.sh --docker-run-gui       # GUI in a container, on the host X display
./driver.sh --docker-jupyter       # JupyterLab on piggy_bank/, http://127.0.0.1:8888
docker run --rm piggy-bank test    # test suite, offscreen, inside the image
```

- `driver.sh` dispatches all options in a single `case` at the bottom. It only reads the first option, so you can't combine them; the remaining args go to that command. Only the local options source `.venv` (`pb_activate_venv`), so the `--docker-*` ones (and `--update-venv`, which may have to create it) work on a host with no venv at all.
- `driver.sh` can also be sourced (`source driver.sh`): that defines the `pb_*` functions without running anything, so you can call them one by one.
- Run Python from the repo root with `PYTHONPATH=.`. Imports are absolute (`from piggy_bank.etica import *`).
- `driver.py` and `piggy_bank/etica.ipynb` are deprecated, so change them freely, but keep them on the GUI model. They work on *views*: `(bl, inv)` mode pairs (`etica.DEFAULT_VIEWS`), built with `build_view()`, which filters and then recomputes that view's own running total and OLS. The plot helpers take `{label: df}` dicts.
- Tests: `./driver.sh --build-run-tests` or `.venv/bin/python -m pytest` (configured in `pyproject.toml`, `pythonpath = ["."]`).
  - `tests/test_load_data.py` covers the ingestion pipeline. Its `data_dir` fixture monkeypatches `etica.DATA_DIR` to a tmp dir, and `write_csv` writes statement/blacklist CSVs. Never point tests at the real `data/`.
  - `tests/test_compute.py` covers the pure computations and the mode/view API.
  - `tests/test_headless.py` runs `driver.py` and every `etica.ipynb` code cell (magics dropped) on synthetic data, with `plt.show`/`go.Figure.show` stubbed.
  - `tests/test_widgets.py` uses pytest-qt, runs offscreen, and is skipped if `*_rc.py` haven't been built.
  - `tests/test_sigint.py` runs Qt in a subprocess, because `app.exit()` ends every event loop and would break pytest-qt's shared `QApplication`. Never call `qapp.exec()`/`exit()` in-process in tests.
  - `tests/test_main_window.py` builds the real `MainWindow` offscreen (QtWebEngine works headless, about 2 s per window). It drives the File menu actions with `FakeDialogs`, which replaces `main_window.QFileDialog`/`QMessageBox`. `.xls` reading is faked by monkeypatching `etica.pd.read_excel`, since there's no xls writer installed.
- Install: `./driver.sh --update-venv` (`pb_update_venv`). It creates `.venv` with `python3 -m venv` if it isn't a venv yet, then runs `pip install -e '.[<every extra in pyproject.toml>]'` (extras read with `tomllib`, so Python >= 3.11). On an existing venv it only installs what's missing. The install must be editable, because `DATA_DIR` is resolved relative to the source tree.
  - **torch is CPU-only on the host too**, as in the image. It's installed from `https://download.pytorch.org/whl/cpu` and pinned in `.venv/pip-constraints.txt`. A CUDA torch found in the venv (plus its `nvidia-*`, `cuda-*`, `triton` wheels) is uninstalled first. Reason: PyPI's CUDA build is GBs, and it has no kernels for the user's Quadro P1000 (sm_61), so encoding failed with `CUDA error: no kernel image is available for execution on the device`.

## Dependencies gotchas

- **superqt** provides `QRangeSlider`, which `filter_tools.ui` promotes to (header `superqt`).
- Plots need `PySide6.QtWebEngineWidgets`. Without it, `WebEnginePlotManager` shows a placeholder label instead of plots.
- **ipywidgets** (`notebook` extra) is needed for `tqdm.auto` progress bars in Jupyter; without it, `TqdmWarning: IProgress not found`.
- **Hugging Face Hub warning:** `SentenceTransformer('name')` contacts the Hub on every load, even with the model cached, and the server answers `You are sending unauthenticated requests to the HF Hub` (an `X-HF-Warning` header). Load with `local_files_only=True` first and fall back to a normal load (download) on `OSError`; or set `HF_TOKEN`.
- Plotly HTML loads `plotly.js` from a CDN (`include_plotlyjs='cdn'`), so plots need network access.

## Docker

Files: `Dockerfile`, `.dockerignore`, and the `--docker-*` functions in `driver.sh`. One image serves the GUI, JupyterLab and the tests. It was verified on Fedora 44 with Docker 29: all tests pass in the image, and JupyterLab serves the notebooks. GUI display on the host was not verified by Claude (that needs a real display).

### Setting up a new host
1. Install Docker (or Podman, then `export PIGGYBANK_ENGINE=podman`). A local `.venv` is only needed for the non-Docker flags.
2. Copy `data/` by hand: it is gitignored real bank data, so a clone doesn't have it. `driver.sh` creates an empty `data/etica/` if it's missing.
3. `./driver.sh --docker-build-image`. The first build is slow (Qt, QtWebEngine, PyTorch). After that, only the layers that changed are rebuilt.
4. For the GUI you need an X server (XWayland is fine) and `xhost`, which `--docker-run-gui` calls itself. On Fedora that's `xorg-x11-server-utils`, on Debian/Ubuntu `x11-xserver-utils`.

### Image design (decisions already made, keep them)
- **Base `python:3.14-slim`** (Debian trixie), with the `dev` and `notebook` extras installed. Official Jupyter images were rejected: they're conda-based (a second Python setup alongside pip), you don't control the Python version, and they don't help with the GUI. The PySide6 wheels include Qt but not the system libraries it needs, so the `apt-get` list (Qt xcb plugin and QtWebEngine/Chromium libraries) is required. If the GUI fails with a missing `.so` or "could not load the Qt platform plugin xcb", add the library there.
- **Layer order, heaviest and most stable first**, so a `pyproject.toml` edit rebuilds only the last layer:
  - Layer A: `torch` from `https://download.pytorch.org/whl/cpu`.
  - Layer B: `PySide6` and `superqt`.
  - Layer C: everything listed in `pyproject.toml`, read with `tomllib`.

  Every `pip install` uses a BuildKit cache mount (`/root/.cache/pip`), so a rebuilt layer reuses downloads. That's why `PIP_NO_CACHE_DIR` is not set. When you add a dependency, just add it to the toml. Only a new *huge* dependency deserves its own layer, before C.
- **PyTorch is CPU-only, on purpose.** `sentence_transformers` pulls `torch`, and PyPI's Linux `torch` is the CUDA build, which adds GBs of `nvidia-*` wheels. Layer A writes the installed `torch==X+cpu` into `/etc/pip-constraints.txt` (`PIP_CONSTRAINT`). If a later dependency wants a different torch, the build fails instead of silently pulling CUDA. Fix that by bumping layer A, never by dropping the constraint.
- **`scikit-learn` and `sentence_transformers` are core dependencies, not an extra.** The GUI will use them, so don't move them to an optional extra.
- **Editable install at `/app`**, because `DATA_DIR` resolves relative to the source tree (`/app/data/etica`). `*_rc.py` are generated at build time; `.dockerignore` excludes stale host copies.
- **Non-root user `piggy` with the host's UID/GID** (build args, which `--docker-build-image` passes). `load_data()` deletes `.xls` files and rewrites `merged.csv` in the mounted `data/`, and those files must stay owned by the host user.
- **Entrypoint modes:** `gui` (the default, runs the `piggy-bank` script), `test` (pytest with `QT_QPA_PLATFORM=offscreen`, extra args passed through), `driver`, `jupyter` (JupyterLab with root `/app/piggy_bank`, port 8888). Anything else is run as a plain command.
- **Environment:** `QTWEBENGINE_DISABLE_SANDBOX=1`, because Chromium's sandbox needs user namespaces that containers don't grant.
- **Software rendering by default** (`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`, `LIBGL_ALWAYS_SOFTWARE=1`). Without the host GPU, Mesa logs `Failed to query drm device` / `failed to load driver: crocus`, and Chromium's GPU init then **hangs the first `QWebEngineView` forever** (in `WebEnginePlotManager.__init__`): no window, 0% CPU, no QtWebEngineProcess. Found on a Haswell laptop (Fedora 44, KDE Wayland). `PIGGYBANK_GPU=1 ./driver.sh --docker-run-gui` passes `/dev/dri` plus the host's `video`/`render` groups and re-enables the GPU; it also reached the event loop on that laptop. The image only has Mesa, so GPU mode won't work with NVIDIA's proprietary driver. Logs about Vulkan instances and `/run/dbus/system_bus_socket` are harmless.
- **`/home/piggy/.cache` must be created owned by `piggy`** (the Dockerfile `install -d` lists it explicitly). Otherwise Docker or `install` creates it as root when it makes the model-cache mount point, and matplotlib warns `mkdir -p failed for path /home/piggy/.cache/matplotlib`.
- **Dark theme:** Qt in the container can't see the desktop's theme and defaults to light.
  - `driver.sh` (`pb_host_color_scheme`) reads it on the host from the freedesktop settings portal (`gdbus ... org.freedesktop.appearance color-scheme`: 1 = dark, 2 = light). It passes the result as `PIGGYBANK_COLOR_SCHEME`, which you can also set by hand to override detection.
  - `main()` calls `qw_misc.apply_color_scheme(app)`. Unset means no change, so on a native host Qt follows the desktop as before. With `dark`, it first tries `styleHints().setColorScheme()`; Qt's generic theme (the one used in the container) ignores that, so it falls back to Fusion + `dark_palette()`.
  - Rejected alternative: mounting the session D-Bus with `QT_QPA_PLATFORMTHEME=xdgdesktopportal`. It works and follows the desktop live, but it exposes the whole desktop session to the container (`systemd-run --user`, the secrets wallet, ...).
  - The theme is read once, at launch.
- **Debugging a hang:** run `python -c "import faulthandler,sys; faulthandler.dump_traceback_later(20, exit=True); sys.argv=['piggy-bank']; from piggy_bank.main_window import main; main()"` in the container (with the GUI's `docker run` options). A healthy start ends up waiting in `app.exec()` in `main()`.

### Runtime (`driver.sh`)
- **`data/` is never in the image** (`.dockerignore`). It is always bind-mounted at `/app/data` with `:z`, which relabels it for SELinux on Fedora.
- **`--docker-run-gui`:** runs `xhost +SI:localuser:$USER`, mounts `/tmp/.X11-unix` and `DISPLAY`, and sets `--shm-size=512m`, because Chromium crashes on the default 64 MB `/dev/shm`.
- **`--docker-jupyter`:**
  - It also mounts `piggy_bank/`, so notebook edits land in the repo and `etica.py` changes are live without a rebuild. Don't mount single notebook files: Jupyter's atomic save renames files, which fails on a file bind mount.
  - The port is published on `127.0.0.1` only, because the notebooks see real bank data. Log in with the `?token=` URL it prints.
- **Hugging Face cache:** both modes mount the named volume `piggy-bank-hf-cache` at `/home/piggy/.cache/huggingface`, so sentence_transformers models are downloaded once and survive `--rm`.
  - The Dockerfile pre-creates that directory owned by `piggy`, because a new named volume copies its ownership from the image.
  - If the volume was ever created by an older image, it's owned by root and downloads fail: `docker volume rm piggy-bank-hf-cache`, rebuild.
- **Overrides:** `PIGGYBANK_ENGINE`, `PIGGYBANK_IMAGE`, `PIGGYBANK_JUPYTER_PORT`, `PIGGYBANK_HF_VOLUME`, `PIGGYBANK_GPU=1` and `PIGGYBANK_COLOR_SCHEME=dark|light` (GUI only, see above).
- **Plots need network:** they load `plotly.js` from a CDN. The default bridge network is fine.
- **Wayland:** the image uses X11 (works through XWayland). Native Wayland would need the Wayland client libraries in the image and the Wayland socket mounted.

### compose.yml: deliberately not used (for now)
Everything is a one-off, interactive container, and compose can't do the host-side steps (`xhost`, checking `DISPLAY`, passing `id -u`/`id -g`). `driver.sh` would still be needed, and mounts, ports and volumes would be defined in two places. Revisit it if a long-running service appears, e.g. an always-on Jupyter server or a database. Then move the configuration into `compose.yml` and have `driver.sh` call `docker compose`.

## Generated files: never edit `*_rc.py`

`piggy_bank/ui/*_rc.py` are pyside6-uic output (gitignored). To change a layout, edit the `.ui` file in Designer (or the XML), then run `./driver.sh --build-gui`. Each `X.ui` produces `X_rc.py` with class `Ui_<RootWidgetName>`. Python widgets use multiple inheritance (`class Foo(QWidget, Ui_Foo)` + `self.setupUi(self)`).

The user often has the `.ui` files open in Designer (`./driver.sh --run-designer` opens all of them). Saving from Designer overwrites any edit made on disk in the meantime: the `calendarPopup` on `qde_start`/`qde_end` was lost this way once. Before editing a `.ui` file, ask the user to close it in Designer, or tell them to reopen it afterwards. Prefer settings that tests check (e.g. `test_filter_tools_dates_have_calendar_popup`), so a stale save is caught by `./driver.sh --build-run-tests`.

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
   - **Open question (undecided, don't act on it unprompted):** the wildcard row type is ambiguous. `Descrizione` is only a note in exact rows but the match pattern in wildcard rows, and the user marks wildcard rows with `*` in the date column, which the code ignores (any date or blank behaves the same). The user's wildcard rows (`TIME DEPOSIT`) overlap with `INV_REGEX` and may be removed. Options proposed: (a) drop wildcard support from `load_data()`, so every row is an exact date+amount match and `Descrizione` is always a note; (b) keep wildcards but require `*` in the date column and reject other amount-less rows. Removing the wildcard rows from the data breaks nothing.
6. Rewrites noisy `Descrizione` fragments (the hardcoded `stripped_parts` list, e.g. → `<BONIF>`).
7. Sets `Investment` = 0/1 from `INV_REGEX` on the *cleaned* description. Like `Blacklisted`, it is computed on every load and isn't in `merged.csv` (which is written at step 4).

Column constants (use these, not string literals): `COL_DATA`='Data contabile', `COL_MINUS`='Dare' (outflows, negative), `COL_PLUS`='Avere' (inflows), `COL_DESCR`='Descrizione', `COL_BL`='Blacklisted', `COL_INV`='Investment', `COL_RUN_TOT`='Running Total', `COL_IMP`='Importo', `COL_OLS`='OLS'. Amount = `Avere.fillna(0) + Dare.fillna(0)`.

`Blacklisted` and `Investment` are two independent 0/1 flags at the same logical level: in the GUI each is just a filter (All/Force/Veto radios). The filter rule lives in `etica`: modes `MODE_ALL`/`MODE_FORCE`/`MODE_VETO`, `mode_keeps(mode, flag)` (per row, used by the GUI) and `apply_modes(df, bl=, inv=)` (per DataFrame, used by the headless side). Never special-case one flag over the other. Investments are detected by `etica.INV_REGEX` (case-insensitive substring) only inside `load_data()`. Everything else (`filter_investments`, the ledger table, the INV radios) reads the `Investment` column, so don't match the pattern anywhere else. "bl"/"inv" naming is consistent throughout: `COL_BL`/`COL_INV`, `__idx_bl`/`__idx_inv`, `brg_bl`/`brg_inv`.

## Architecture

- `etica.py`: pure pandas/numpy logic (loading, `compute_importo`, `compute_ols` linear fit of the running total vs date ordinal, `compute_candlesticks` OHLC resample) plus matplotlib/plotly helpers for the notebook. It has no Qt imports, so keep it that way.
- `main_window.py`: `MainWindow` and `main()`. `get_data_source()` calls `load_data()`, adds the running total, checks the required columns, and formats dates as `YYYY-MM-DD` strings.
  - `_show_data(df)` holds everything that depends on the data (column indices, table, header, date and amount ranges, sort, `_apply_filters`). It runs at startup and again on every reload (`_reload_data()`). The other filters (text, direction, radios) are kept across reloads.
  - File menu: `qa_import_data` copies a chosen `.xls` into `DATA_DIR` (confirming first if that statement's `.csv` already exists). `qa_import_blacklist` overwrites `DATA_DIR/blacklist.csv`. Both go through `_import_and_reload()`, which reloads and, on any failure (including an xls that `load_data()` couldn't convert), restores the touched files and reloads the previous state. `qa_export_data` copies `merged.csv` wherever the user picks.
  - `main_window` reads `etica.DATA_DIR` through the module, not the star import, so tests can redirect it.
  - The ledger `QTableWidget` is the source of truth for filtering. `_apply_filters()` walks the table rows, hides the rows that fail the filters, and recomputes the `Running Total` cells chronologically over the *visible* rows only. It builds `self.df_plot` and calls `_update_plot()`, which redraws every Plotly figure (line+OLS, amount histogram, weekday/day-of-month/month histogram, candlesticks, box plots).
  - The weekday histogram deliberately raises if any transaction falls on a Saturday (a sanity check).
- `filter_tools.py`: `FilterTools` widget (direction checkboxes, `QRangeSlider` amount ranges, description text, date range, two independent radio groups, reset).
  - `brg_bl` (`qrb_bl_all/force/veto`) and `brg_inv` (`qrb_inv_all/force/veto`): **All** = no constraint, **Force** = keep only matching rows, **Veto** = drop matching rows. "Matching" means `Blacklisted == 1` for BL and `Investment == 1` for INV. Both groups apply together (AND).
  - The groups are wired through the `QButtonGroup`s that uic generates (`brg.buttonToggled` → `_on_brg_buttonToggled`, `checkedButton()` for defaults). Group membership lives only in the `.ui`, so don't keep Python lists of radios. Each group's default is whichever radio has `checked=true` in the `.ui` (the **All** ones). It's captured at init in `__brg_defaults` and restored by reset. A group with no checked radio raises at startup. Each radio's mode is its objectName suffix (`qrb_bl_force` → `force`), read via `FilterTools.bl_mode()`/`inv_mode()`, so new radios must end in `_all`/`_force`/`_veto` (also checked at startup). It emits `filters_updated`, debounced with a 1 s single-shot `QTimer` for sliders and text.
- `aggr_stats.py`: `AggrStats` box (All/Out/In summary stats over the visible values). With `coloured=True` (only `stats_all`), sum, median and average are green when >= 0 and red when negative, using the plots' `#2ca02c`/`#d62728`.
- `qw_misc.py`: `install_sigint_handler(app)` (Ctrl+C → `app.exit(130)`; a 200 ms no-op `QTimer` lets Python run signal handlers while Qt idles; `main()` installs it right before `app.exec()` and catches `KeyboardInterrupt` during startup). `WebEnginePlotManager` (renders a `go.Figure` to HTML in a `QWebEngineView`, dark theme `#111111`), `NumericTableWidgetItem` (numeric sort), and thin wrappers `Ledger`, `PlotsLines`, `PlotsStats` that load their `.ui` files.
- The main window has tabs whose layouts (`ql_ledger`, `ql_plots_lines`, `ql_plots_stats`, `qvl_aggr_stats`) get the sub-widgets inserted at runtime.

## Conventions

- Qt widget names use a type prefix: `qpb_` push button, `qrb_` radio, `qchk_` checkbox, `qle_` line edit, `qde_` date edit, `qrs_` range slider, `qcb_` combo box, `qtw_` table, `ql_`/`qvl_` layouts (also `ql_` labels in FilterTools), `qgb_` group box.
- Slots are named `_on_<widget>_<signal>` and decorated with `@Slot(...)`.
- Wrap programmatic widget updates in `blockSignals(True/False)` so they don't trigger filter cascades.
- Logging goes through the stdlib `logging` module, configured via `etica.init_logging()`.
- Modules use `from piggy_bank.etica import *` to get the constants, `pd`, `np`, `logging`, etc.
