# CLAUDE.md

Piggy Bank is a personal finance analyser for Banca Etica ("Estratto conto Italia") bank statement exports. It has a PySide6 desktop GUI and also a headless/notebook path. Banca Etica's exports have Italian column names; `load_data()` renames them to English on read, and everything after that is English.

## Commands

Everything runs through `driver.sh` (the local options activate `.venv/` first):

```bash
./driver.sh --update-venv           # create .venv if needed, install pyproject.toml with all extras (CPU-only torch)
./driver.sh --build-gui             # compile ui/*.ui -> ui/*_rc.py with pyside6-uic
./driver.sh --run-gui               # run the GUI, without building (PYTHONPATH=. python piggy_bank/main_window.py)
./driver.sh --deprecated-headless   # load data, print a summary per view in DEFAULT_VIEWS (piggy_bank/driver.py)
./driver.sh --run-designer          # open Qt Designer
./driver.sh --build-run-tests       # build the UI, then run pytest (extra args are passed through, e.g. --build-run-tests -k classes)
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
- `driver.py` and `piggy_bank/etica.ipynb` are deprecated, so change them freely, but keep them on the GUI model. They work on *views*: tuples of excluded classes (`etica.DEFAULT_VIEWS`, like unchecking class checkboxes in the GUI), built with `build_view(df, exclude=)`, which filters (`apply_classes`) and then recomputes that view's own running total and OLS. They call `cluster_merged(load_data())` with the default clustering settings (`AUTO_N_CLUSTERS`, `AUTO_SEED`), like the GUI at startup. The plot helpers take `{label: df}` dicts.
- Tests: `./driver.sh --build-run-tests` or `.venv/bin/python -m pytest` (configured in `pyproject.toml`, `pythonpath = ["."]`).
  - `tests/test_load_data.py` covers the ingestion pipeline. Its `data_dir` fixture monkeypatches `etica.DATA_DIR` to a tmp dir, `write_csv` writes statement CSVs, and `write_classes` writes `custom-classes.csv` from raw lines. Never point tests at the real `data/`.
  - `tests/test_classes.py` covers the custom classes rules, `cluster_custom()` and `cluster_merged()`, with the `auto_off` fixture (from `conftest.py`), so unmatched movements stay `todo`.
  - `tests/test_cluster_auto.py` covers `cluster_auto()`. **No test loads the sentence_transformers model**: an autouse `conftest.py` fixture replaces `etica.embed_texts` with `fake_embed_texts`, a hashed bag of words that is deterministic and fast. Tests that are about something other than automatic classes and expect `todo` use `auto_off` (`monkeypatch` of `etica.cluster_auto`).
  - `tests/test_compute.py` covers the pure computations and the class/view API (`apply_classes`, `build_view`).
  - `tests/test_headless.py` runs `driver.py` and every `etica.ipynb` code cell (magics dropped) on synthetic data, with `plt.show`/`go.Figure.show` stubbed.
  - `tests/test_widgets.py` uses pytest-qt, runs offscreen, and is skipped if `*_rc.py` haven't been built.
  - `tests/test_sigint.py` runs Qt in a subprocess, because `app.exit()` ends every event loop and would break pytest-qt's shared `QApplication`. Never call `qapp.exec()`/`exit()` in-process in tests. The child prints `ready` from inside the event loop (`QTimer.singleShot(0, ...)`): `app.exit()` before `exec()` starts is ignored, so a `ready` printed earlier made the test flaky on a loaded machine.
  - `tests/test_main_window.py` builds the real `MainWindow` offscreen (QtWebEngine works headless, about 2 s per window). It drives the File menu actions with `FakeDialogs`, which replaces `main_window.QFileDialog`/`QMessageBox`. `.xls` reading is faked by monkeypatching `etica.pd.read_excel`, since there's no xls writer installed.
- Install: `./driver.sh --update-venv` (`pb_update_venv`). It creates `.venv` with `python3 -m venv` if it isn't a venv yet, then runs `pip install -e '.[<every extra in pyproject.toml>]'` (extras read with `tomllib`, so Python >= 3.11). On an existing venv it only installs what's missing. The install must be editable, because `DATA_DIR` is resolved relative to the source tree.
  - **torch is CPU-only on the host too**, as in the image. It's installed from `https://download.pytorch.org/whl/cpu` and pinned in `.venv/pip-constraints.txt`. A CUDA torch found in the venv (plus its `nvidia-*`, `cuda-*`, `triton` wheels) is uninstalled first. Reason: PyPI's CUDA build is GBs, and it has no kernels for the user's Quadro P1000 (sm_61), so encoding failed with `CUDA error: no kernel image is available for execution on the device`.

## Dependencies gotchas

- **superqt** provides `QDoubleRangeSlider`, which `filter_tools.ui` promotes `qrs_out`/`qrs_in` to (header `superqt`).
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

`piggy_bank/ui/*_rc.py` are pyside6-uic output (gitignored). To change a layout, edit the `.ui` file in Designer (or the XML), then run `./driver.sh --build-gui`. Each `X.ui` produces `X_rc.py` with class `Ui_<RootWidgetName>`. Python widgets use multiple inheritance and a `QW_` prefix (`class QW_Foo(QWidget, Ui_Foo)` + `self.setupUi(self)`). `MainWindow` keeps its name.

The user often has the `.ui` files open in Designer (`./driver.sh --run-designer` opens all of them). Saving from Designer overwrites any edit made on disk in the meantime: the `calendarPopup` on `qde_start`/`qde_end` was lost this way once. Before editing a `.ui` file, ask the user to close it in Designer, or tell them to reopen it afterwards. Prefer settings that tests check (e.g. `test_filter_tools_dates_have_calendar_popup`), so a stale save is caught by `./driver.sh --build-run-tests`.

## Data (sensitive, gitignored)

The data lives in `data/etica/` (`DATA_DIR` in `etica.py`). It is real personal bank data: don't print it in bulk, copy it elsewhere or commit it. `data/etica-virgin/` holds the original `.xls` exports as a pristine backup.

`etica.load_data()` is the single ingestion pipeline. It **mutates `DATA_DIR`** as it runs:
1. Converts each `*.xls` to `*.csv` (dropping `Valuta`, `Divisa`, `Causale`) and **deletes the `.xls`**.
2. Loads every `*.csv` except `NOT_STATEMENTS` (`merged.csv`, `custom-classes.csv`, `blacklist.csv`). Files like `*.csv.bk` are ignored because they don't match the glob. Watch out for overlapping exports, e.g. `-2024.csv` + `-2024-bis.csv`.
3. Concatenates them and drops exact duplicate rows. **Known, accepted limitation:** this also collapses genuinely distinct identical movements, e.g. two SEPA fees on the same day. The exports have no transaction ID, so there's no reliable way to tell those apart from overlapping exports. Don't try to "fix" it unless asked. `test_identical_rows_are_collapsed_known_limitation` pins this behaviour.
4. Sorts by date with deterministic tiebreakers (`sort_by_date`) and rewrites `merged.csv` (output only, never read back).
5. Rewrites noisy description fragments (the hardcoded `stripped_parts` list, e.g. → `<BONIF>`).

It returns `df_merged`: the statement columns only, no classes.

### Classes

`etica.cluster_merged(df_merged)` returns `df_clustered`: a copy with `Class` (`COL_CLASS`) appended. Everything downstream (GUI, driver, notebook) works on `df_clustered`. `merged.csv` knows nothing about classes, and classes are recomputed on every load and reload. It's a separate step from `load_data()` on purpose: the GUI re-runs it with new clustering settings (`qsb_settings_classes_num`, `qsb_settings_seed` in `classes.ui`) on the kept `df_merged`, without re-reading the files.
1. `cluster_custom(df)`: classes from the rules in `DATA_DIR/custom-classes.csv` (`CUSTOM_CLASSES_CSV`, optional), `None` where no rule matched.
2. `cluster_auto(df, classes, n_clusters, seed)`: fills the `None`s by text clustering of the descriptions (the sentence_transformers approach of `piggy_bank/text_clustering_guide.ipynb`). It is expensive, so it must never run during ledger filtering.
   - `embed_texts()` encodes with `AUTO_MODEL` (`paraphrase-multilingual-MiniLM-L12-v2`, multilingual because the descriptions are Italian; normalised embeddings), loaded once and lazily (`_load_auto_model()`, cached copy first, see the HF gotcha). Embeddings are cached per description text in `_auto_embeddings`, so re-clustering with new settings only re-runs KMeans (milliseconds). Only the first run is slow (about 10 s for the torch import and model load).
   - `KMeans(n_clusters, random_state=seed, n_init=10)`. `n_clusters` is capped at the number of distinct unclassified descriptions (with a warning); `0` turns automatic clustering off.
   - Names: `AUTO_PREFIX` + the cluster number (1 = largest; ties by first appearance, i.e. chronological; zero-padded when k >= 10, so alphabetical = size order) + the `AUTO_NAME_WORDS` (2) most distinctive keywords, from a TF-IDF with one document per cluster (`_cluster_keywords`; tokens are 3+ letters, no digits). E.g. `auto1 pagamento/pos`. A cluster with no word at all is just `auto3`.
   - Defaults `AUTO_N_CLUSTERS` = 5, `AUTO_SEED` = 42 mirror the spin boxes in `classes.ui` (`test_defaults_match_classes_ui`).
3. Whatever is left is `CLASS_TODO` (`'todo'`): only with automatic clustering off (`n_clusters=0`).

`custom-classes.csv` (`read_custom_classes()` → `ClassRule`s): header `Date,Out,In,Description,Class` (`RULE_COLUMNS`), then one rule per line, read with the `csv` module (quotes work).
- Date: `*` (any) or `YYYY-MM-DD`. Out/In: `*` (any), blank (the movement's must be blank) or a number (matched to the cent). Description: `*` or blank (any), else a case-insensitive literal substring of the *cleaned* description. Class: any non-blank text; each distinct text is a class, typos included (`loans` ≠ `loan`), by the user's choice.
- Rules apply in file order, each to every movement. First match wins: a later rule with a *different* class logs an error per movement and changes nothing; the same class is silent. A rule matching nothing logs a warning. A rule may match many movements.
- `#` lines and blank lines are skipped. Malformed lines (field count, date, amount, blank class) are logged and skipped; a wrong or missing header raises `ValueError`, so a bad import via the File menu rolls back.
- `blacklist.csv` (the old 0/1 `Blacklisted` flag) and `INV_REGEX` (the old `Investment` flag) are gone. The user's real `custom-classes.csv` was migrated from both: exact blacklist rows got the placeholder class `blacklist`, the `TIME DEPOSIT` wildcards and the `FONDI|PROVENTI|CEDOLE|DEPOSIT` terms got `investment`. `blacklist.csv` stays in `data/` as an archive, never read.

Column constants (use these, not string literals): `COL_DATE`='Date', `COL_OUT`='Out' (outflows, negative), `COL_IN`='In' (inflows), `COL_DESCR`='Description', `COL_CLASS`='Class' (the column of `df_clustered`, and of the rules file), `COL_RUN_TOT`='Running Total', `COL_AMOUNT`='Amount', `COL_OLS`='OLS'. Amount = `In.fillna(0) + Out.fillna(0)`.

**Italian names live only in source data.** The `.xls` exports and the `.csv` converted from them keep Banca Etica's headers (`Data contabile`, `Dare`, `Avere`, `Descrizione`; `Valuta`, `Divisa`, `Causale` are dropped, `SOURCE_DROPPED`). `load_data()` renames them with `SOURCE_COLUMNS` right after reading each CSV, so `merged.csv`, the rules file, every DataFrame, identifier and GUI label is English. The ledger header comes from the DataFrame columns and must match `ledger.ui` (`test_ledger_header_is_english`). Tests write statements with the Italian headers (`write_csv`, the fake `read_excel`).

Class filtering: the GUI keeps a row unless its class is unchecked (`QW_FilterTools.excluded_classes()`); the headless side uses `apply_classes(df, exclude)`, the same rule. `sorted_classes()` is the display order (alphabetical, `todo` last).

## Architecture

- `etica.py`: pure pandas/numpy logic (loading, `compute_running_total`, `compute_ols` linear fit of the running total vs date ordinal, `compute_candlesticks` OHLC per period, `compute_period_stats`) plus matplotlib/plotly helpers for the notebook. It has no Qt imports, so keep it that way.
  - Time frames are `TF_WEEKLY`/`TF_MONTHLY`/`TF_YEARLY` (the combo box texts), mapped by `TIMEFRAMES` to pandas periods. `period_start()` is the single bucketing rule: weeks start on Monday, months on the 1st, years on January 1st. Candlesticks and the periods table both use it; don't use `resample('ME'/'W')`, which labels periods by their end.
  - `AggrStats` (non-Qt) computes entries/min/max/sum/median/avg/std of a list of amounts and formats them (`text()`, static `format()`). `FIELDS` is the order, `SIGNED` the fields coloured green/red. Both `QW_AggrStats` and `QW_Periods` use it.
- `main_window.py`: `MainWindow` and `main()`. `self.df_merged` keeps `load_data()`'s output (set at startup and by `_reload_data()`); `_clustered_data()` runs `cluster_merged(self.df_merged, **ui_classes.clustering_settings())` and `prepare_data()` (adds the running total, checks the required columns, formats dates as `YYYY-MM-DD` strings).
  - Clustering settings: `QW_Classes.clustering_changed` (debounced 1 s) → `_on_ui_classes_clustering_changed()`: re-clusters the whole `df_merged` without reading the files again (wait cursor), then `_show_data(df, reset_filters=True)`, which calls `ft.reset_filters(emit=False)` before filtering. Every filter is reset, since the classes they referred to are gone. On failure: `QMessageBox.critical`, previous data kept.
  - `_show_data(df)` holds everything that depends on the data (column indices, table, header, date and amount ranges, class checkboxes, sort, `_apply_filters`). It runs at startup and again on every reload (`_reload_data()`). The other filters (text, direction) are kept across reloads, and so are unchecked classes that still exist.
  - File menu: `qa_import_data` copies a chosen `.xls` into `DATA_DIR` (confirming first if that statement's `.csv` already exists). `qa_import_custom_classes` overwrites `DATA_DIR/custom-classes.csv` (the action keeps its old objectName and text in `main_window.ui` until the user renames it in Designer). Both go through `_import_and_reload()`, which reloads and, on any failure (including an xls that `load_data()` couldn't convert), restores the touched files and reloads the previous state. `qa_export_data` copies `merged.csv` wherever the user picks.
  - `main_window` reads `etica.DATA_DIR` through the module, not the star import, so tests can redirect it.
  - The ledger `QTableWidget` is the source of truth for filtering. `_apply_filters()` walks the table rows, hides the rows that fail the filters, and recomputes the `Running Total` cells chronologically over the *visible* rows only. It builds `self.df_plot` (the visible rows, chronological: `Date`, `Amount`, `Running Total`, `Out`, `In` with blanks as 0, `Description`, `Class`), feeds it to `ui_periods.update_periods()` and `ui_classes.update_classes()`, and calls `_update_plot()`, which redraws every Plotly figure (line+OLS, amount histogram, weekday/day-of-month/month histogram, candlesticks, box plots).
  - The weekday histogram deliberately raises if any transaction falls on a Saturday (a sanity check).
- `filter_tools.py`: `QW_FilterTools` widget (direction checkboxes, `QDoubleRangeSlider` amount ranges with min/max spin boxes, description text, date range, class checkboxes, reset, last month).
  - `qpb_last_month`: `qde_end` = today, `qde_start` = today − `LAST_MONTH_DAYS` (31) days, plain day arithmetic by the user's choice (no calendar months). Both dates are set with signals blocked, then `filters_updated` is emitted once.
  - Amount ranges: `qrs_out`/`qrs_in` (superqt `QDoubleRangeSlider`s) each have two `QDoubleSpinBox`es (`qsb_out_min`/`qsb_out_max`, `qsb_in_min`/`qsb_in_max`; 2 decimals, ±10.0 step, set in the `.ui`), kept in sync both ways (`__spins`). The slider holds the value `_apply_filters()` reads. A slider change mirrors into the spin boxes and starts the debounce timer; a spin box change moves the slider, which filters in turn. A min pushed past the max (or vice versa) drags the other spin box along instead of crossing. Spin boxes have `keyboardTracking=false` in the `.ui`, so typed values apply on Enter/focus-out, not per keystroke. `setup_sliders()` sets slider and spin box ranges from the data; the direction checkboxes enable/disable slider and spin boxes together. Slider and spin box bounds are the exact data min/max, cents included: never `int()` them, truncating toward zero would push an extreme Out minimum or In maximum with cents outside the range, hiding that movement.
  - Class checkboxes are built at runtime by `setup_classes(df)` (called from `_show_data`) inside `qsaw_classes` (the widget of the `qsa_classes` scroll area, in `qgb_classes`), one per class, in the `qgl_classes` grid: `CLASS_ROWS` (2) rows, filled column by column, as many columns as needed, then an expanding spacer. `qsa_classes` scrolls horizontally only (vertical bar `AlwaysOff` in the `.ui`), and `setup_classes` sets its minimum height so both rows plus the horizontal bar always fit. Checkboxes are labelled `name (count)`, objectName `qchk_class_<name>`. All start checked (= accept every class). On a rebuild, a class that was unchecked stays unchecked; new ones are checked. `class_checkboxes()` gives `{name: QCheckBox}`, `excluded_classes()` the unchecked names. Toggling is debounced like text; reset checks them all.
  - The old `qgb_bl`/`qbg_inv` radio groups (`brg_bl`/`brg_inv`) are unwired; the user deletes them from the `.ui`. No code may reference them.
  - It emits `filters_updated`, debounced with a 1 s single-shot `QTimer` for sliders, text and class checkboxes.
  - `reset_filters(emit=True)` (the `qpb_reset` slot calls it) restores every filter and stops a pending debounce; `emit=False` lets the caller filter itself (re-clustering does).
- `aggr_stats.py`: `QW_AggrStats` box (All/Out/In summary stats over the visible values, computed by `etica.AggrStats`). With `coloured=True` (only `stats_all`), sum, median and average are green when >= 0 and red when negative (`signed_color()`), using the plots' `#2ca02c`/`#d62728`.
- `qw_misc.py`: `install_sigint_handler(app)` (Ctrl+C → `app.exit(130)`; a 200 ms no-op `QTimer` lets Python run signal handlers while Qt idles; `main()` installs it right after creating the `QApplication`, so Ctrl+C works during the whole startup: before `app.exec()` the handler raises `KeyboardInterrupt` (`app.exit()` would be ignored, `loopLevel() == 0`), which `main()` catches around all startup code and exits 130; during the loop it calls `app.exit(130)`. Only Ctrl+C during module imports, before `main()`, still prints Python's traceback). `WebEnginePlotManager` (renders a `go.Figure` to HTML in a `QWebEngineView`, dark theme `#111111`), `NumericTableWidgetItem` (numeric sort), thin wrappers `QW_Ledger`, `QW_PlotsLines`, `QW_PlotsStats` that load their `.ui` files, `QW_Classes` (Classes tab, `classes.ui`, root `Classes`) and `QW_Periods` (Periods tab, `periods.ui`).
  - **Tables have static columns, set in Designer** (the user's preference): `StaticColumnsTable(qtw, known, default_sort=, stretch=)` fills a `QTableWidget` by matching each header text to the DataFrame column of the same name, so columns are added, removed or reordered in the `.ui` with no code change. A header not in `known` raises `ValueError` at construction. Cells are read-only, numeric columns sort numerically, `default_sort` applies once at construction, so the user's header-click sort survives refreshes. Never set columns from code.
    - `QW_MovementsTable` (`movements_table.ui`, `qtw_movements`): ledger rows, headers among `KNOWN` (Date, Out, In, Description, Amount, Class; currently Date, Out, In, Description), newest first, Description stretched, Out/In blank when 0. `show_movements(df)`.
    - `QW_PeriodsTable` (`periods_table.ui`, `qtw_periods`): period stats, headers among `HEADERS` values ('Date' = the period, 'Out', 'In', capitalised `AggrStats` fields), newest first, `SIGNED` fields green/red. `show_periods(df_periods, timeframe)`.
    - Periods and class tabs need different columns (stats vs Description), hence two table `.ui` files. Running Total makes no sense in either (the user's call).
  - `QW_Periods.update_periods(df_plot)`: keeps the frame and re-renders its `QW_PeriodsTable` (`self.table`, inserted in `qvl_periods`) by itself when `qcb_periods_time` changes. One row per period: Out/In sums plus the `AggrStats` of the amounts.
  - `QW_Classes.update_classes(df_plot)`: one tab in `qtw_tabs` (a `QTabWidget`, despite the `qtw_` prefix) per class among the *visible* rows, so every ledger filter applies, labelled with the class name, in `sorted_classes()` order. Each tab is a `QW_MovementsTable` of that class's movements. Alongside, `qsac_aggr` (the widget of the `qsa_aggr` scroll area) stacks one `QW_AggrStats` per visible class, in the same order, titled with the class name, over that class's amounts, coloured like the ledger's *All* box; `class_aggr_stats()` gives `{class: box}`. `qsa_aggr` scrolls vertically only (horizontal bar `AlwaysOff` in the `.ui`), and `update_classes` sets its minimum width to fit the boxes plus the vertical bar. A class's table and box are reused while it stays visible (the table keeps its sort), and the selected tab is kept. `class_tables()` gives `{class: table}`. The clustering settings `qsb_settings_classes_num` (= `n_clusters`, 0 = off) and `qsb_settings_seed` (= KMeans `random_state`) start the 1 s debounce timer of `clustering_changed`; `clustering_settings()` gives `{'n_clusters', 'seed'}`. `qhl_charts` is not implemented yet.
- `MainWindow.__init__` always selects `tab_ledger`, ignoring the `currentIndex` saved in `main_window.ui` (checked by `test_starts_on_ledger_tab`). Designer saves whichever tab was last selected, so `currentIndex` changes in almost every `main_window.ui` diff. That's expected noise: don't report it, don't "fix" it in the `.ui`.
- The main window has tabs whose layouts (`ql_ledger`, `ql_plots_lines`, `ql_plots_stats`, `ql_classes`, `ql_periods`, `qvl_aggr_stats`) get the sub-widgets inserted at runtime (`ui_ledger`, `ui_plots_lines`, `ui_plots_stats`, `ui_classes`, `ui_periods`). `test_every_tab_hosts_its_widget` checks the tab ↔ widget mapping.

## Conventions

- Qt widget names use a type prefix: `qpb_` push button, `qrb_` radio, `qchk_` checkbox, `qle_` line edit, `qde_` date edit, `qrs_` range slider, `qsb_` spin box, `qcb_` combo box, `qtw_` table, `ql_`/`qvl_` layouts (also `ql_` labels in FilterTools), `qgb_` group box.
- Slots are named `_on_<widget>_<signal>` and decorated with `@Slot(...)`.
- Wrap programmatic widget updates in `blockSignals(True/False)` so they don't trigger filter cascades.
- Logging goes through the stdlib `logging` module, configured via `etica.init_logging()`.
- Modules use `from piggy_bank.etica import *` to get the constants, `pd`, `np`, `logging`, etc.
