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
LOG_FORMAT = '[%(levelname)8s]    %(message)s'

# Constants
COL_DATA = 'Data contabile'
COL_SALDO = 'Saldo'
COL_PLUS = 'Avere'
COL_MINUS = 'Dare'
COL_IMP = 'Importo'
COL_DESCR = 'Descrizione'
COL_INV = 'Blacklisted'
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
    exclude_files = {'blacklist.csv', 'merged.csv'}
    csv_files = [p for p in DATA_DIR.glob('*.csv') if p.name not in exclude_files]

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

        # 6) Add blacklist column to df_merged (default 0) and flag matches
        df_merged[COL_INV] = 0

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
                df_merged.loc[cond, COL_INV] = 1
                _lg.info(f"Blacklisted entry matched: {bl_row[COL_DATA].date()}")
            elif n_matches > 1:
                raise ValueError(f"Found {n_matches} matches in data for blacklist entry: {bl_row.to_dict()}")
    else:
        # If no blacklist exists, ensure uniform structure
        if COL_DESCR in df_merged.columns:
            df_merged = df_merged.drop(columns=[COL_DESCR])
        df_merged[COL_INV] = 0

    return df_merged


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
