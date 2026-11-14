import os
import csv
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
from colorama import Fore
from typing import Tuple
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import plotly.graph_objects as go

_lg = logging.getLogger('etica')

def init_logging(also_time: bool, level=logging.DEBUG, coloured: bool = True) -> None:
    fmt = '[%(levelname)8s]    %(message)s'
    if also_time:
        fmt = '%(asctime)s.%(msecs)03d ' + fmt
    if coloured:
        import coloredlogs
        coloredlogs.install(fmt=fmt, level=level)
    else:
        logging.basicConfig(format=fmt,
                            datefmt='%H:%M:%S',
                            level=level)

# Constants
COL_DATA = 'Data contabile'
COL_RUN_TOT = 'Running Total'
COL_GRN_RUN_TOT = 'Grand Running Total'
COL_PLUS = 'Avere'
COL_MINUS = 'Dare'
COL_IMP = 'Importo'
COL_DESCR = 'Descrizione'
COL_CLASS = 'Class'  # appended by cluster_merged(), never in merged.csv
COL_OLS = 'OLS'

FMT_DT = '%Y%m%d'
FMT_DT_CSV = '%Y-%m-%d'  # Format used in CSV files for dates

# Adjust this path to match your notebook location relative to the data
# Currently assumes the notebook is in the same folder as the original script
# TODO get as env var PB_DATA_DIR
DATA_DIR = Path(__file__).parent.parent / 'data' / 'etica'

# Files in DATA_DIR that are not bank statements
MERGED_CSV = 'merged.csv'                  # output of load_data(), never read back
CUSTOM_CLASSES_CSV = 'custom-classes.csv'  # rules of cluster_custom()
BLACKLIST_CSV = 'blacklist.csv'            # archive only, superseded by CUSTOM_CLASSES_CSV
NOT_STATEMENTS = {MERGED_CSV, CUSTOM_CLASSES_CSV, BLACKLIST_CSV}

# Custom classes rules (CUSTOM_CLASSES_CSV): the statement columns plus the class name
COL_RULE_CLASS = 'Classe'
RULE_COLUMNS = [COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR, COL_RULE_CLASS]
RULE_ANY = '*'       # matches any value
RULE_COMMENT = '#'   # a line starting with it is ignored
CLASS_TODO = 'todo'  # movements no custom rule (nor, later, cluster_auto) classified


def load_data() -> pd.DataFrame:
    """
    https://gemini.google.com/app/9e9e957a6d672e51
    Executes the full data loading, conversion and merging pipeline, then rewrites merged.csv.
    Returns the merged movements with cleaned descriptions and no classes: see cluster_merged().
    """
    _lg.debug(f"Starting data load pipeline from {DATA_DIR}")

    # 1) Retrieve all *.xls files, convert to *.csv, and delete the original xls upon success
    for xls_path in DATA_DIR.glob('*.xls'):
        try:
            df_xls = pd.read_excel(xls_path)
            # Drop unnecessary columns if they exist, mimicking old behaviour
            df_xls = df_xls.drop(columns=['Valuta', 'Divisa', 'Causale'], errors='ignore')

            csv_path = xls_path.with_suffix('.csv')
            df_xls.to_csv(csv_path, index=False)
            os.remove(xls_path)
            _lg.info(f"Converted {xls_path.name} to CSV and removed original XLS file.")
        except Exception as e:
            _lg.error(f"Could not convert {xls_path.name}: {e}")

    # 2) Let csv_files be the set of *.csv files (excluding merged.csv, custom-classes.csv and blacklist.csv)
    # Load them into dfs_list
    csv_files = [p for p in DATA_DIR.glob('*.csv') if p.name not in NOT_STATEMENTS]

    dfs_list = []
    for csv_path in csv_files:
        try:
            df_csv = pd.read_csv(csv_path)
            if COL_DATA in df_csv.columns:
                df_csv[COL_DATA] = pd.to_datetime(df_csv[COL_DATA], errors='coerce')
            dfs_list.append(df_csv)
            _lg.info(f"Loaded {csv_path.name} into DataFrame with {len(df_csv)} rows")
        except Exception as e:
            _lg.error(f"Could not read {csv_path.name}: {e}")

    # 3) Merge dfs_list into a single dataframe df_merged
    if not dfs_list:
        _lg.warning("No CSV data found to merge.")
        df_merged = pd.DataFrame()
    else:
        df_merged: pd.DataFrame = pd.concat(dfs_list, ignore_index=True)

        # Find duplicated rows, log a warning, and remove them
        duplicates = df_merged[df_merged.duplicated(keep=False)]
        if not duplicates.empty:
            for idx, dup_row in duplicates.iterrows():
                _lg.warning(f"Duplicate row found at index {idx}: {dup_row.to_dict()}")
            num_dups = len(duplicates) // 2  # Approximate duplicate pairs
            _lg.warning(f"Found {num_dups} duplicated rows. Removing them")
            _lg.warning("FIXME this will also remove e.g. two SEPA commissions from the same day !!!")  # FIXME

        df_merged = df_merged.drop_duplicates(ignore_index=True)
        df_merged = sort_by_data_contabile(df_merged)

    # 4) Rewrite merged.csv as the dumping of df_merged
    out_csv_path = DATA_DIR / MERGED_CSV
    df_merged.to_csv(out_csv_path, index=False)
    _lg.debug(f"Dumped merged data ({len(df_merged)} rows) to {out_csv_path.name}")

    # 5) Strip away noisy text in Descrizione. TODO put in a separate config file for easier maintenance
    stripped_parts = [("CARTA N. 416363******7346 - CIRCUITO VISA", ""),
                      ("Pagamenti paesi UE DEL", ""),
                      ("ADDEBITO DIRETTO CORE RCUR Prg.Car.:", ""),
                      ("Bonifico - SEPA istantaneo a vs favore", "<BONIF>"),
                      ("Valuta EUR Paese Italia C/O", ""),
                      ("Bonifico - SEPA istantaneo", "<BONIF>"),
                      ("ADDEBITO BONIFICO DA HOME BANKING", "<BONIF>"),
                      ("BONIFICO A VOSTRO FAVORE", "<BONIF>"),]
    for old, new in stripped_parts:
        df_merged[COL_DESCR] = df_merged[COL_DESCR].str.replace(old, new, regex=False).str.strip()
    return df_merged


@dataclass
class ClassRule:
    """One line of CUSTOM_CLASSES_CSV. A None field is RULE_ANY; an amount of NaN means "must be blank"."""
    line: int  # 1-based line number in the file, for log messages
    date: pd.Timestamp | None
    minus: float | None
    plus: float | None
    descr: str | None  # case-insensitive substring
    cls: str

    def mask(self, df: pd.DataFrame) -> pd.Series:
        """Which rows of df (COL_DATA as datetime) the rule matches."""
        keep = pd.Series(True, index=df.index)
        if self.date is not None:
            keep &= pd.to_datetime(df[COL_DATA], errors='coerce').dt.normalize() == self.date
        for col, amount in ((COL_MINUS, self.minus), (COL_PLUS, self.plus)):
            if amount is None:
                continue
            values = pd.to_numeric(df[col], errors='coerce')
            # Compare to the cent, so float noise from the CSV round trip doesn't matter
            keep &= values.isna() if np.isnan(amount) else (values - amount).abs() < 0.005
        if self.descr is not None:
            keep &= df[COL_DESCR].str.contains(self.descr, case=False, regex=False, na=False)
        return keep

    def __str__(self):
        def show(v):
            if v is None:
                return RULE_ANY
            if isinstance(v, float) and np.isnan(v):
                return '<blank>'
            return v.strftime(FMT_DT_CSV) if isinstance(v, pd.Timestamp) else str(v)
        return (f"line {self.line} ({show(self.date)}, {show(self.minus)}, {show(self.plus)}, "
                f"{show(self.descr)} -> {self.cls!r})")


def read_custom_classes(path: Path) -> list:
    """Parses a custom classes file into ClassRules, in file order.

    The first line must be the header RULE_COLUMNS. Then, per field:
    - Data contabile: RULE_ANY or a YYYY-MM-DD date.
    - Dare, Avere: RULE_ANY, a number (matched to the cent), or blank, meaning the movement's one must be blank.
    - Descrizione: RULE_ANY, blank (both match anything) or a case-insensitive substring.
    - Classe: any non-blank text; every distinct text is a class, typos included.
    Blank lines and lines starting with RULE_COMMENT are ignored. A malformed line is logged and skipped,
    a wrong header raises ValueError."""
    rules = []
    header_seen = False
    with open(path, newline='', encoding='utf-8-sig') as f:
        for line_no, fields in enumerate(csv.reader(f), start=1):
            fields = [x.strip() for x in fields]
            if not any(fields) or fields[0].startswith(RULE_COMMENT):
                continue
            if not header_seen:
                if fields != RULE_COLUMNS:
                    raise ValueError(f"{path.name}: line {line_no} must be the header {','.join(RULE_COLUMNS)}, "
                                     f"found {','.join(fields)}")
                header_seen = True
                continue
            try:
                rules.append(_parse_rule(line_no, fields))
            except ValueError as e:
                _lg.error(f"{path.name}: line {line_no} skipped: {e}. Line: {','.join(fields)}")
    if not header_seen:
        raise ValueError(f"{path.name}: no header line {','.join(RULE_COLUMNS)}")
    return rules


def _parse_rule(line_no: int, fields: list) -> ClassRule:
    if len(fields) != len(RULE_COLUMNS):
        raise ValueError(f"expected {len(RULE_COLUMNS)} fields, found {len(fields)}")
    date_s, minus_s, plus_s, descr, cls = fields

    if date_s == RULE_ANY:
        date = None
    else:
        try:
            date = pd.Timestamp(datetime.strptime(date_s, FMT_DT_CSV))
        except ValueError:
            raise ValueError(f"{COL_DATA} must be {RULE_ANY} or a YYYY-MM-DD date, not {date_s!r}") from None

    def amount(col, s):
        if s == RULE_ANY:
            return None
        if s == '':
            return float('nan')
        try:
            return float(s)
        except ValueError:
            raise ValueError(f"{col} must be {RULE_ANY}, blank or a number, not {s!r}") from None

    if not cls:
        raise ValueError(f"{COL_RULE_CLASS} is blank")
    return ClassRule(line=line_no, date=date, minus=amount(COL_MINUS, minus_s), plus=amount(COL_PLUS, plus_s),
                     descr=None if descr in ('', RULE_ANY) else descr, cls=cls)


def cluster_custom(df: pd.DataFrame, path: Path | None = None) -> pd.Series:
    """Classes from the custom rules (default DATA_DIR/CUSTOM_CLASSES_CSV, optional): one per row of df,
    None where no rule matched. Each rule is applied to every movement, in file order. The first rule
    matching a movement classifies it for good: a later rule matching it with a different class logs
    an error and changes nothing."""
    classes = pd.Series(None, index=df.index, dtype=object)
    path = path if path is not None else DATA_DIR / CUSTOM_CLASSES_CSV
    if not path.exists():
        _lg.warning(f"No {path.name} in {path.parent}: no custom classes")
        return classes
    rules = read_custom_classes(path)
    _lg.debug(f"Loaded {len(rules)} custom class rules from {path.name}")
    if df.empty:
        return classes

    by_line = pd.Series(0, index=df.index)  # the rule that classified each row
    for rule in rules:
        mask = rule.mask(df)
        if not mask.any():
            _lg.warning(f"{path.name}: rule {rule} matches no movement")
            continue
        taken = mask & classes.notna()
        for idx in df.index[taken & (classes != rule.cls)]:
            row = df.loc[idx]
            _lg.error(f"{path.name}: rule {rule} matches a movement already classified {classes[idx]!r} "
                      f"by line {by_line[idx]}, keeping {classes[idx]!r}: {row[COL_DATA]:%Y-%m-%d}, "
                      f"{row[COL_PLUS] if pd.notna(row[COL_PLUS]) else row[COL_MINUS]} EUR, {row[COL_DESCR]}")
        new = mask & classes.isna()
        classes[new] = rule.cls
        by_line[new] = rule.line
        _lg.info(f"{path.name}: rule {rule} classified {new.sum()} movements"
                 + (f" ({taken.sum()} already classified)" if taken.any() else ''))
    return classes


def cluster_auto(df: pd.DataFrame, classes: pd.Series) -> pd.Series:
    """Classes for the rows of df that classes leaves as None. Not implemented yet: returns classes as is."""
    return classes


def cluster_merged(df_merged: pd.DataFrame) -> pd.DataFrame:
    """df_clustered: a copy of df_merged (the output of load_data()) with COL_CLASS appended.
    Custom classes first, then automatic ones for the rest; whatever is left is CLASS_TODO."""
    classes = cluster_custom(df_merged)
    classes = cluster_auto(df_merged, classes)
    df_clustered = df_merged.copy()
    df_clustered[COL_CLASS] = classes.fillna(CLASS_TODO).astype(str)
    counts = df_clustered[COL_CLASS].value_counts()
    _lg.info('Classes: ' + ', '.join(f'{c} {counts[c]}' for c in sorted_classes(counts.index)))
    return df_clustered


def sorted_classes(classes) -> list:
    """Distinct class names in display order: alphabetical, CLASS_TODO last."""
    return sorted(set(classes), key=lambda c: (c == CLASS_TODO, c))


def sort_by_data_contabile(df: pd.DataFrame) -> pd.DataFrame:
    """Sorts the DataFrame by 'Data contabile' in ascending order.

    Secondary sort keys (COL_MINUS, COL_PLUS, COL_DESCR) are used as tiebreakers
    to guarantee a fully deterministic order for same-date rows, regardless of the
    order in which source files are loaded (filesystem glob order is non-deterministic).
    """
    try:
        df_sorted = df.copy()
        df_sorted[COL_DATA] = pd.to_datetime(df_sorted[COL_DATA], errors='coerce')
        sort_cols = [COL_DATA]
        for col in [COL_MINUS, COL_PLUS, COL_DESCR]:
            if col in df_sorted.columns:
                sort_cols.append(col)
        df_sorted = df_sorted.sort_values(sort_cols, ascending=True, na_position='last').reset_index(drop=True)
        return df_sorted
    except Exception as e:
        _lg.error(f'Could not sort by "{COL_DATA}": {e}')
        return df


def compute_importo(df: pd.DataFrame) -> pd.DataFrame:
    """Computes 'Importo' (Credit + Debit) and cumulative 'Saldo'."""
    df = df.copy()
    df[COL_IMP] = df[COL_PLUS].fillna(0) + df[COL_MINUS].fillna(0)
    df[COL_RUN_TOT] = df[COL_IMP].cumsum()
    df = df.drop(columns=[COL_IMP], errors='ignore')
    return df


def compute_ols(df: pd.DataFrame) -> Tuple[pd.DataFrame, float, float]:
    """Computes OLS fit of 'Saldo' vs Time."""
    df = df.copy()
    df[COL_DATA] = pd.to_datetime(df[COL_DATA], errors='coerce')
    df_valid = df.dropna(subset=[COL_DATA, COL_RUN_TOT])

    if len(df_valid) < 2:
        _lg.warning('Not enough valid data for OLS fit.')
        df[COL_OLS] = float('nan')
        return df, float('nan'), float('nan')

    x = df_valid[COL_DATA].map(lambda d: d.toordinal()).values.astype(float)
    y = df_valid[COL_RUN_TOT].values
    try:
        m, q = np.polyfit(x, y, 1)
        ols_vals = np.full(len(df), float('nan'))
        mask = df[COL_DATA].notna()
        x_all = df.loc[mask, COL_DATA].map(lambda d: d.toordinal()).values.astype(float)
        ols_vals[mask] = m * x_all + q
        df[COL_OLS] = ols_vals
        return df, m, q
    except Exception as e:
        _lg.error(f'OLS fit failed: {e}')
        df[COL_OLS] = float('nan')
        return df, float('nan'), float('nan')


def plot_saldo_ols(views: dict) -> None:
    """Plots running total and OLS fit over time of every view {label: df} on the same graph."""
    fig, ax1 = plt.subplots(figsize=(12, 6))
    colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
    fits = []

    for i, (lbl, df) in enumerate(views.items()):
        df, m, q = compute_ols(df)
        color = colors[i % len(colors)]
        ax1.plot(df[COL_DATA], df[COL_RUN_TOT], label=lbl, color=color)
        ax1.plot(df[COL_DATA], df[COL_OLS], label=f'OLS {lbl}', color=color, linestyle='--')
        fits.append(f'{lbl}: y = {m:.2f}x + {q:.2f}')

    ax1.set_ylabel(COL_RUN_TOT)
    ax1.legend()
    ax1.grid(True)

    ax1.text(0.01, 0.99, '\n'.join(fits), transform=ax1.transAxes, fontsize=10,
             verticalalignment='top', bbox=dict(facecolor='white', alpha=0.7, edgecolor='none'))

    ax1.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=10, maxticks=20))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.show()


def plot_saldo_ols_interactive(views: dict) -> None:
    """Interactive Plotly plot of every view {label: df} with its OLS line, zoomable and hoverable."""
    fig = go.Figure()

    for lbl, df in views.items():
        df, m, _ = compute_ols(df)
        fig.add_trace(go.Scatter(x=df[COL_DATA], y=df[COL_RUN_TOT], mode='lines', name=lbl, line=dict(width=2)))
        fig.add_trace(go.Scatter(x=df[COL_DATA], y=df[COL_OLS], mode='lines', name=f'OLS {lbl} (m = {m:.2f})',
                                 line=dict(width=2, dash='dash')))

    fig.update_layout(title='Running Total and OLS Fit (Interactive, Zoomable & Hoverable)',
                      xaxis_title=COL_DATA,
                      yaxis_title=COL_RUN_TOT,
                      hovermode='x unified',
                      template='plotly_white',
                      height=600)
    fig.show()


# Time frames, as shown in the GUI combo boxes. Every period starts at its natural boundary:
# weeks on Monday (pandas' 'W' period runs Monday to Sunday), months on the 1st, years on January 1st.
TF_WEEKLY = 'Weekly'
TF_MONTHLY = 'Monthly'
TF_YEARLY = 'Yearly'
TIMEFRAMES = {TF_WEEKLY: 'W', TF_MONTHLY: 'M', TF_YEARLY: 'Y'}


def period_start(dates: pd.Series, timeframe: str) -> pd.Series:
    """Maps each date to the first day of its period (see TIMEFRAMES). Raises KeyError on an unknown timeframe."""
    return pd.to_datetime(dates).dt.to_period(TIMEFRAMES[timeframe]).dt.start_time


def compute_candlesticks(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """OHLC candlesticks of the running total, one per period (TF_WEEKLY/TF_MONTHLY/TF_YEARLY).
    'Date' is the period's first day. Periods with no rows are left out."""
    df_copy = df.copy()
    df_copy[COL_DATA] = pd.to_datetime(df_copy[COL_DATA], errors='coerce')
    df_copy = df_copy.dropna(subset=[COL_DATA, COL_RUN_TOT])

    if timeframe not in TIMEFRAMES:
        _lg.error(f"Unknown candlestick timeframe '{timeframe}', expected one of {list(TIMEFRAMES)}")
        return pd.DataFrame()

    # Stable sort, so 'first'/'last' are the chronological open/close even on unsorted input
    df_copy = df_copy.sort_values(COL_DATA, kind='stable')
    rv = df_copy.groupby(period_start(df_copy[COL_DATA], timeframe))[COL_RUN_TOT].agg(
        Open='first',
        High='max',
        Low='min',
        Close='last'
    )
    rv.index.name = 'Date'
    return rv.reset_index()


class AggrStats:
    """Summary statistics of a list of amounts (no Qt): entries, min, max, sum, median, avg, std.
    Empty input gives 0 entries, sum 0 and NaN for the rest. std is the sample one, NaN under 2 values."""
    FIELDS = ('entries', 'min', 'max', 'sum', 'median', 'avg', 'std')
    SIGNED = ('sum', 'median', 'avg')  # the fields whose sign matters (coloured green/red in the GUI)

    def __init__(self, values):
        s = pd.Series(values, dtype=float)
        self.entries = len(s)
        self.min = s.min()
        self.max = s.max()
        self.sum = s.sum()
        self.median = s.median()
        self.avg = s.mean()
        self.std = s.std()

    def text(self, field: str) -> str:
        """The field formatted for display, see format()."""
        return self.format(field, getattr(self, field))

    @staticmethod
    def format(field: str, value) -> str:
        """Formats a field value: entries as an integer, std with 2 decimals (0.00 when undefined),
        everything else rounded to units."""
        if field == 'entries':
            return f"{int(value):d}"
        if field == 'std':
            return f"{value:.2f}" if pd.notna(value) else "0.00"
        return f"{value:.0f}"

    def __repr__(self):
        return 'AggrStats(' + ', '.join(f'{f}={getattr(self, f)!r}' for f in self.FIELDS) + ')'


COL_PERIOD = 'Date'


def compute_period_stats(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """One row per period with rows (TF_WEEKLY/TF_MONTHLY/TF_YEARLY), oldest first.
    Columns: COL_PERIOD (the period's first day), COL_MINUS (sum of outflows), COL_PLUS (sum of inflows),
    then the AggrStats FIELDS over the amounts (Dare + Avere) of that period."""
    columns = [COL_PERIOD, COL_MINUS, COL_PLUS, *AggrStats.FIELDS]
    if df.empty:
        return pd.DataFrame(columns=columns)
    out = pd.to_numeric(df[COL_MINUS], errors='coerce').fillna(0)
    inc = pd.to_numeric(df[COL_PLUS], errors='coerce').fillna(0)
    tmp = pd.DataFrame({COL_PERIOD: period_start(df[COL_DATA], timeframe),
                        COL_MINUS: out, COL_PLUS: inc, COL_IMP: out + inc})
    rows = []
    for start, grp in tmp.groupby(COL_PERIOD, sort=True):
        st = AggrStats(grp[COL_IMP])
        rows.append({COL_PERIOD: start, COL_MINUS: grp[COL_MINUS].sum(), COL_PLUS: grp[COL_PLUS].sum(),
                     **{f: getattr(st, f) for f in AggrStats.FIELDS}})
    return pd.DataFrame(rows, columns=columns)


def plot_candlestick(df: pd.DataFrame, lbl: str) -> None:
    # Plot
    close_diff = np.diff(df['Close'].values, prepend=np.nan)
    dates_num = mdates.date2num(df['Date'].values)

    fig2, ax3 = plt.subplots(figsize=(12, 3))
    width = np.min(np.diff(dates_num)) * 0.8 if len(dates_num) > 1 else 1
    ax3.bar(dates_num, close_diff, width=width, align='center', color=np.where(close_diff >= 0, 'green', 'red'))
    ax3.set_ylabel('Δ Close')
    ax3.set_title(f'Δ Derivative of {lbl} Close')
    ax3.grid(True)
    ax3.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=10, maxticks=20))
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig2.autofmt_xdate()
    plt.tight_layout()
    plt.show()


def plot_candlestick_interactive(df: pd.DataFrame, lbl: str) -> None:
    fig = go.Figure(data=[go.Candlestick(x=df['Date'],
                                         open=df['Open'],
                                         high=df['High'],
                                         low=df['Low'],
                                         close=df['Close'])])
    fig.update_layout(title=f'Monthly Candlesticks (Interactive) for {lbl}', xaxis_title='Date', yaxis_title='Saldo')
    fig.show()


def apply_classes(df: pd.DataFrame, exclude=()) -> pd.DataFrame:
    """Drops the rows whose COL_CLASS is in exclude, exactly as unchecking classes in the GUI does."""
    return df[~df[COL_CLASS].isin(exclude)].reset_index(drop=True)


def view_label(exclude=()) -> str:
    return 'all classes' if not exclude else 'all but ' + ', '.join(exclude)


def build_view(df: pd.DataFrame, exclude=()) -> Tuple[pd.DataFrame, float, float]:
    """Filters df by class, then computes its own running total and OLS fit. Returns (view, m, q)."""
    rv = apply_classes(df, exclude).drop(columns=[COL_RUN_TOT, COL_OLS], errors='ignore')
    rv = compute_importo(rv)
    return compute_ols(rv)


def print_view_summary(df: pd.DataFrame, lbl: str, m: float = float('nan')) -> None:
    """Logs size, final running total and OLS slope (per day) of a view."""
    if not df.empty:
        final = df[COL_RUN_TOT].iloc[-1]
        col = Fore.GREEN if final >= 0 else Fore.RED
        final = f'{col}{final:.2f} EUR{Fore.RESET}'
    else:
        final = 'N/A'
    _lg.info(f'{lbl}: {len(df)} rows, final running total {final}, trend {m:+.2f} EUR/day')


def plot_view_bars(df: pd.DataFrame, lbl: str) -> None:
    """Plots the running total of a view as bars over time."""
    if not df.empty:
        fig, ax = plt.subplots(figsize=(12, 3))
        ax.bar(df[COL_DATA], df[COL_RUN_TOT], color='purple')
        ax.set_ylabel(COL_RUN_TOT)
        ax.set_title(lbl)
        ax.grid(True)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=10, maxticks=20))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        fig.autofmt_xdate()
        plt.tight_layout()
        plt.show()


# Views shown by driver.py and the notebook: the classes each one excludes. Edit to taste:
# the names are those of custom-classes.csv, an unknown one just excludes nothing.
DEFAULT_VIEWS = [
    (),
    ('investment',),
    ('blacklist', 'investment'),
]
