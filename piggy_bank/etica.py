import os
import shutil
import logging
from pathlib import Path

import pandas as pd
import numpy as np
from colorama import Fore
from typing import List, Tuple
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import plotly.graph_objects as go

_lg = logging.getLogger('etica')

# Constants
COL_DATA = 'Data contabile'
COL_SALDO = 'Saldo'
COL_PLUS = 'Avere'
COL_MINUS = 'Dare'
COL_IMP = 'Importo'
COL_DESCR = 'Descrizione'
COL_OLS = 'OLS'

FMT_DT = '%Y%m%d'
FMT_DT_CSV = '%Y-%m-%d'  # Format used in CSV files for dates

# Adjust this path to match your notebook location relative to the data
# Currently assumes the notebook is in the same folder as the original script
DATA_DIR = Path(__file__).parent.parent / 'data' / 'etica'


def load_data() -> pd.DataFrame:
    """
    https://gemini.google.com/app/9e9e957a6d672e51
    Executes the full data loading, conversion, merging, and blacklisting pipeline.
    """
    _lg.info(f"Starting data load pipeline from {DATA_DIR}")

    # 1) Retrieve all *.xls files, convert to *.csv, and delete the original xls upon success
    for xls_path in DATA_DIR.glob('*.xls'):
        try:
            df_xls = pd.read_excel(xls_path)
            # Drop unnecessary columns if they exist, mimicking old behavior
            df_xls = df_xls.drop(columns=['Valuta', 'Divisa', 'Causale'], errors='ignore')

            csv_path = xls_path.with_suffix('.csv')
            df_xls.to_csv(csv_path, index=False)
            os.remove(xls_path)
            _lg.info(f"Converted {xls_path.name} to CSV and removed original XLS file.")
        except Exception as e:
            _lg.error(f"Could not convert {xls_path.name}: {e}")

    # 2) Let csv_files be the set of *.csv files (excluding blacklist.csv, merged.csv, and variations)
    # Load them into dfs_list
    exclude_files = {'blacklist.csv', 'merged.csv', 'merged-forse-immacolato.csv'}
    csv_files = [p for p in DATA_DIR.glob('*.csv') if p.name not in exclude_files]

    dfs_list = []
    for csv_path in csv_files:
        try:
            df_csv = pd.read_csv(csv_path)
            if COL_DATA in df_csv.columns:
                df_csv[COL_DATA] = pd.to_datetime(df_csv[COL_DATA], errors='coerce')
            dfs_list.append(df_csv)
            _lg.info(f"Loaded {csv_path.name} into DataFrame with {len(df_csv)} rows.")
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
            _lg.warning(f"Found {num_dups} duplicated rows. Removing them.")
            _lg.warning("FIXME this will also remove e.g. two SEPA commissions from the same day !!!")  # FIXME

        df_merged = df_merged.drop_duplicates(ignore_index=True)
        df_merged = sort_by_data_contabile(df_merged)

    # 4) Rewrite merged.csv as the dumping of df_merged
    out_csv_path = DATA_DIR / 'merged.csv'
    df_merged.to_csv(out_csv_path, index=False)
    _lg.info(f"Dumped merged data ({len(df_merged)} rows) to {out_csv_path.name}")

    # 5) Process blacklist.csv if it exists
    blacklist_path = DATA_DIR / 'blacklist.csv'
    if blacklist_path.exists():
        df_blacklist = pd.read_csv(blacklist_path)
        df_blacklist[COL_DATA] = pd.to_datetime(df_blacklist[COL_DATA], errors='coerce')

        # If a row has both Dare and Avere as NaN, log a warning and remove it
        nan_mask = df_blacklist[COL_MINUS].isna() & df_blacklist[COL_PLUS].isna()
        if nan_mask.any():
            _lg.warning(f"Found {nan_mask.sum()} rows in blacklist.csv with both {COL_MINUS} and {COL_PLUS} as NaN. Removing them.")
            df_blacklist = df_blacklist[~nan_mask]

        # Remove the 'Descrizione' column from df_merged
        if COL_DESCR in df_merged.columns:
            df_merged = df_merged.drop(columns=[COL_DESCR])

        # 6) Add "Blacklisted" column to df_merged (default 0) and flag matches
        df_merged['Blacklisted'] = 0

        for _, bl_row in df_blacklist.iterrows():
            # Build matching condition for df_merged based on available non-NaN values
            cond = (df_merged[COL_DATA] == bl_row[COL_DATA])
            if pd.notna(bl_row[COL_MINUS]):
                cond &= (df_merged[COL_MINUS] == bl_row[COL_MINUS])
            if pd.notna(bl_row[COL_PLUS]):
                cond &= (df_merged[COL_PLUS] == bl_row[COL_PLUS])

            matches = df_merged[cond]
            n_matches = len(matches)

            if n_matches == 1:
                df_merged.loc[cond, 'Blacklisted'] = 1
                _lg.info(f"Blacklisted entry matched: {bl_row[COL_DATA].date()}")
            elif n_matches > 1:
                raise ValueError(f"Found {n_matches} matches in data for blacklist entry: {bl_row.to_dict()}")
    else:
        # If no blacklist exists, ensure uniform structure
        if COL_DESCR in df_merged.columns:
            df_merged = df_merged.drop(columns=[COL_DESCR])
        df_merged['Blacklisted'] = 0

    return df_merged


def eventually_rename_csv_src_file(p: Path, df: pd.DataFrame) -> str:
    if (any([p.name.startswith(t) for t in ['movimenti_', 'merged_']])
            and p.suffix == '.csv'):
        _lg.warning(f'Won\'t rename an already processed file: {p.name}')
        return p.name
    min_date = df[COL_DATA].min().strftime(FMT_DT)
    max_date = df[COL_DATA].max().strftime(FMT_DT)
    csv_filename = f'movimenti_{min_date}_{max_date}.csv'
    p_new = DATA_DIR / csv_filename
    shutil.move(p, p_new)
    return p_new.name


def load_xls_dataframes_from_import() -> Tuple[List[str], List[pd.DataFrame]]:
    """
    Scans for '*.xls' files in the data directory, converts them to CSV,
    and loads all CSVs into a list of pandas DataFrames.
    :return A tuple containing a list of CSV base-names and a list of corresponding DataFrames.
    """
    csv_bns, dataframes = [], []
    _lg.info(f'Loading .xls files from {DATA_DIR}...')

    # Convert .xls to .csv
    for xls_path in DATA_DIR.glob('*.xls'):
        try:
            df = pd.read_excel(xls_path)
            df = df.drop(columns=['Valuta', 'Divisa', 'Causale'], errors='ignore')
            df.to_csv(xls_path.with_suffix('.csv'), index=False)
            os.remove(xls_path)
            _lg.info(f'Converted {xls_path} to CSV and removed original XLS file.')
        except Exception as e:
            _lg.error(f'Could not convert {xls_path}: {e}')

    # Load .csv files
    for csv_path in DATA_DIR.glob('*.csv'):
        try:
            if csv_path.name.endswith('blacklist.csv'):
                _lg.info('Skipping blacklist.csv during loading of dataframes')
                continue
            df = pd.read_csv(csv_path)
            if COL_DATA not in df.columns:
                raise ValueError(f'Expected column "{COL_DATA}" not found')
            df[COL_DATA] = pd.to_datetime(df[COL_DATA], errors='coerce')
            # Rename CSV with date range for clarity
            bn = eventually_rename_csv_src_file(csv_path, df)
            csv_bns.append(bn)
            dataframes.append(df)
            _lg.info(f'Loaded {csv_path} into DataFrame with {len(df)} rows.')
        except Exception as e:
            _lg.error(f'Could not read {csv_path}: {e}')
    return csv_bns, dataframes


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


def merge_dataframes_no_duplicates(ldf: List[pd.DataFrame]) -> pd.DataFrame:
    """Merges multiple DataFrames and removes duplicate rows."""
    if not ldf:
        return pd.DataFrame()
    merged = pd.concat(ldf, ignore_index=True)
    merged = merged.drop_duplicates(ignore_index=True)
    merged = sort_by_data_contabile(merged)
    _lg.info(f'Merged {len(ldf)} DataFrames into one with {len(merged)} unique rows.')
    return merged


def merge_csvs(l_csv_bns: List[str], df: pd.DataFrame, do_remove: bool) -> None:
    """Merges CSV files into a single CSV and returns the path.

    The resulting filename is generated from the earliest and latest dates found in
    the DataFrame column `COL_DATA` using format `movimenti_YYYYMMDD_YYYYMMDD.csv`.
    If dates are missing the name will contain `unknown_dates`. If the target file
    already exists a numeric `_vN` suffix is appended to avoid clobbering.
    Original CSV files listed in `csvs` are removed when possible.
    """

    # Determine a helpful basename from dates if possible
    dates = pd.to_datetime(df[COL_DATA], errors='coerce')
    min_date, max_date = dates.min(), dates.max()
    min_date, max_date = min_date.strftime(FMT_DT), max_date.strftime(FMT_DT)
    # bn = f'merged_{min_date}_{max_date}.csv'
    bn = f'merged.csv'  # Git will be happier without continuous renames

    _lg.info(f'Merging {df.shape[0]} rows into {bn}, from {min_date} to {max_date}')
    out_csv_path = DATA_DIR / bn
    if out_csv_path.exists():
        _lg.warning(f'{bn} already exists. Overwriting')
    df.to_csv(out_csv_path, index=False)

    # Try to remove the original CSVs; accept Path or str inputs
    if do_remove:
        for bn in l_csv_bns:
            if bn.startswith('merged_') or bn.startswith('blacklist'):
                _lg.info(f'Skipping removal of {bn} since it looks like a merged file or blacklist')
                continue
            p = Path(os.path.join(DATA_DIR, bn))
            if p.exists():
                _lg.info(f'Removing source CSV: {bn}')
                p.unlink()
            else:
                _lg.error(f'Could not find {bn} to remove after merging')


def load_blacklist() -> pd.DataFrame:
    in_csv_path = DATA_DIR / 'blacklist.csv'
    try:
        if not in_csv_path.exists():
            raise FileNotFoundError(f'No blacklist.csv found in {DATA_DIR}. No blacklisting will be applied.')

        df_bl = pd.read_csv(in_csv_path)
        # Ensure required columns exist
        for col in [COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR]:
            if col not in df_bl.columns:
                raise ValueError(f'Expected column "{col}" not found in blacklist.csv')
        # Convert date column to datetime
        df_bl[COL_DATA] = pd.to_datetime(df_bl[COL_DATA], errors='coerce')
        return df_bl
    except Exception as e:
        _lg.warning(f'Failed to load blacklist.csv: {e}')
        return pd.DataFrame(columns=[COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR])


def blacklist(df: pd.DataFrame, df_bl: pd.DataFrame, bl_l: list) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Removes rows matching specific (date, amount) pairs from the DataFrame.

    Returns a tuple of (df_filtered, df_removed) where:
    - df_filtered: DataFrame with blacklisted entries removed
    - df_removed: DataFrame containing the removed blacklisted entries
    """
    df = df.copy()
    removed_rows = []
    tot_bl = 0

    # TODO from df_bl, extract (date_str, amount) pairs for blacklisting
    _lg.info(f'Applying blacklist with {len(df_bl)} = {len(bl_l)} entries.')
    _lg.debug(f'Blacklist entries from df_bl:\n{df_bl[[COL_DATA, COL_MINUS]]}')
    _lg.debug(f'Blacklist entries from bl_l:\n{bl_l}')

    # for _, row in df_bl.iterrows():
    #   date_str = row[COL_DATA]
    #   amount = row[COL_MINUS]
    for date_str, amount in bl_l:
        _lg.warning(f'Blacklisting entry: {amount} EUR on {date_str}')
        target_date = pd.to_datetime(date_str)
        # Keep rows that do NOT match both conditions
        mask = (df[COL_DATA] == target_date) & (df[COL_MINUS] == amount)
        # Count matching rows (mask is a boolean Series)
        matches = df.loc[mask]
        # noinspection PyTypeChecker
        n_matches = len(matches)
        if n_matches != 1:
            # noinspection PyStringConversionWithoutDunderMethod
            raise ValueError(f'Blacklist entry ({date_str}, {amount}) found {n_matches} '
                             f'times in DataFrame; expected 1. Rows:\n{matches}')
        # Collect removed rows and drop the single matching row
        removed_rows.append(matches)
        df = df[~mask]
        tot_bl -= amount
    _lg.info(f'Total blacklisted amount: {tot_bl:.2f} EUR')

    df_filtered = sort_by_data_contabile(df.reset_index(drop=True))
    df_removed = pd.concat(removed_rows, ignore_index=True) if removed_rows else pd.DataFrame()

    return df_filtered, df_removed


def compute_importo(df: pd.DataFrame) -> pd.DataFrame:
    """Computes 'Importo' (Credit + Debit) and cumulative 'Saldo'."""
    df = df.copy()
    df[COL_IMP] = df[COL_PLUS].fillna(0) + df[COL_MINUS].fillna(0)
    df[COL_SALDO] = df[COL_IMP].cumsum()
    df = df.drop(columns=[COL_IMP], errors='ignore')
    return df


def compute_ols(df: pd.DataFrame) -> Tuple[pd.DataFrame, float, float]:
    """Computes OLS fit of 'Saldo' vs Time."""
    df = df.copy()
    df[COL_DATA] = pd.to_datetime(df[COL_DATA], errors='coerce')
    df_valid = df.dropna(subset=[COL_DATA, COL_SALDO])

    if len(df_valid) < 2:
        _lg.warning('Not enough valid data for OLS fit.')
        df['OLS'] = float('nan')
        return df, float('nan'), float('nan')

    x = df_valid[COL_DATA].map(lambda d: d.toordinal()).values.astype(float)
    y = df_valid[COL_SALDO].values
    try:
        m, q = np.polyfit(x, y, 1)
        ols_vals = np.full(len(df), float('nan'))
        mask = df[COL_DATA].notna()
        x_all = df.loc[mask, COL_DATA].map(lambda d: d.toordinal()).values.astype(float)
        ols_vals[mask] = m * x_all + q
        df['OLS'] = ols_vals
        return df, m, q
    except Exception as e:
        _lg.error(f'OLS fit failed: {e}')
        df['OLS'] = float('nan')
        return df, float('nan'), float('nan')


def plot_saldo_ols(_df1: pd.DataFrame, _df2: pd.DataFrame) -> None:
    """Plots 'Saldo' and OLS fit over time for two dataframes on the same graph."""
    # Compute OLS for both dataframes
    df1, m1, q1 = compute_ols(_df1)
    df2, m2, q2 = compute_ols(_df2)

    fig, ax1 = plt.subplots(figsize=(12, 6))

    # Plot df1 (overall balance) in blue
    ax1.plot(df1[COL_DATA], df1[COL_SALDO], label='Saldo netto', color='tab:blue')
    ax1.plot(df1[COL_DATA], df1['OLS'], label='OLS fit netto', color='tab:orange', linestyle='--')

    # Plot df2 (investment balance) in green
    ax1.plot(df2[COL_DATA], df2[COL_SALDO], label='Saldo grezzo', color='tab:green')
    ax1.plot(df2[COL_DATA], df2['OLS'], label='OLS fit grezzo', color='tab:red', linestyle='--')

    ax1.set_ylabel(COL_SALDO)
    ax1.legend()
    ax1.grid(True)

    all_saldos = pd.concat([df1[COL_SALDO], df2[COL_SALDO]]).dropna()
    if not all_saldos.empty:
        max_saldo_ever = all_saldos.max()
        if type(max_saldo_ever) in [np.float64, float]:
            ax1.set_ylim(0, max_saldo_ever * 1.1)

    label = (f'OLS Saldo: y = {m1:.2f}x + {q1:.2f}\n'
             f'OLS Inv:   y = {m2:.2f}x + {q2:.2f}')
    ax1.text(0.01, 0.99, label, transform=ax1.transAxes, fontsize=10,
             verticalalignment='top', bbox=dict(facecolor='white', alpha=0.7, edgecolor='none'))

    ax1.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=10, maxticks=20))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.show()


def plot_saldo_ols_interactive(_df_net: pd.DataFrame, _df_all: pd.DataFrame) -> None:
    """Interactive Plotly plot of _df_net and _df_all with OLS lines, zoomable and hoverable."""
    fig = go.Figure()

    # Add net balance line
    fig.add_trace(go.Scatter(x=_df_net[COL_DATA], y=_df_net[COL_SALDO],
                             mode='lines', name='Saldo netto',
                             line=dict(color='#1f77b4', width=2)))

    # Add net OLS line
    fig.add_trace(go.Scatter(x=_df_net[COL_DATA], y=_df_net['OLS'],
                             mode='lines', name='OLS fit netto',
                             line=dict(color='#ff7f0e', width=2, dash='dash')))

    # Add all balance line
    fig.add_trace(go.Scatter(x=_df_all[COL_DATA], y=_df_all[COL_SALDO],
                             mode='lines', name='Saldo grezzo',
                             line=dict(color='#2ca02c', width=2)))

    # Add all OLS line
    fig.add_trace(go.Scatter(x=_df_all[COL_DATA], y=_df_all['OLS'],
                             mode='lines', name='OLS fit grezzo',
                             line=dict(color='#d62728', width=2, dash='dash')))

    fig.update_layout(title='Saldo and OLS Fit (Interactive, Zoomable & Hoverable)',
                      xaxis_title='Data contabile',
                      yaxis_title=COL_SALDO,
                      hovermode='x unified',
                      template='plotly_white',
                      height=600)
    fig.show()


def compute_candlesticks(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resamples 'Saldo' to OHLC candlesticks based on timeframe."""
    df_copy = df.copy()
    df_copy[COL_DATA] = pd.to_datetime(df_copy[COL_DATA], errors='coerce')
    df_copy = df_copy.dropna(subset=[COL_DATA, COL_SALDO])
    df_copy = df_copy.set_index(COL_DATA)

    try:
        rv = df_copy[COL_SALDO].resample(timeframe).agg(
            Open='first',
            High='max',
            Low='min',
            Close='last'
        )
    except Exception as e:
        _lg.error(f"Resampling with timeframe '{timeframe}' failed: {e}")
        return pd.DataFrame()

    rv = rv.dropna()
    rv = rv.reset_index()
    rv = rv.rename(columns={COL_DATA: 'Date'})
    return rv


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


def filter_investments(df: pd.DataFrame) -> pd.DataFrame:
    """Filters investment transactions and appends synthetic bias rows."""

    mask = df[COL_DESCR].str.contains('FONDI|PROVENTI|CEDOLE|DEPOSIT', case=True, na=False, regex=True)
    rv = df[mask].reset_index(drop=True).copy()
    rv = rv.drop(columns=[COL_OLS], errors='ignore')
    rv = compute_importo(rv)
    _lg.info(f'Found {mask.sum()} = {rv.shape[0]} investment-related transactions.')
    return rv


def print_investments_summary(df: pd.DataFrame) -> None:
    _lg.info('Investimenti correttamente chiusi (quelli aperti sono blacklisted!!!):')
    _lg.info(df.drop(columns=[COL_DESCR], errors='ignore'))

    if not df.empty:
        saldo_inv = df[COL_SALDO].iloc[-1]
        col = Fore.GREEN if saldo_inv >= 0 else Fore.RED
        saldo_inv = f'{col}{saldo_inv:.2f} EUR{Fore.RESET}'
    else:
        saldo_inv = 'N/A'
    _lg.info(f'Saldo finale investimenti: {saldo_inv}')


def plot_investments(df: pd.DataFrame) -> None:
    """Plots the 'Saldo' of investment-related transactions over time."""
    if not df.empty:
        fig_inv, ax2 = plt.subplots(figsize=(12, 3))
        ax2.bar(df[COL_DATA], df[COL_SALDO], color='purple')
        ax2.set_ylabel(COL_SALDO)
        ax2.set_title('Investimenti')
        ax2.grid(True)
        ax2.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=10, maxticks=20))
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        fig_inv.autofmt_xdate()
        plt.tight_layout()
        plt.show()
