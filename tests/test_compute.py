import math

import pandas as pd
import pytest

from piggy_bank.etica import (COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR, COL_RUN_TOT, COL_OLS, COL_IMP, COL_INV,
                              compute_importo, compute_ols, compute_candlesticks, filter_investments,
                              sort_by_data_contabile)


def ledger(rows):
    df = pd.DataFrame(rows, columns=[COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR])
    df[COL_DATA] = pd.to_datetime(df[COL_DATA])
    return df


def test_compute_importo_running_total():
    df = ledger([('2025-01-01', None, 100.0, 'A'), ('2025-01-02', -30.0, None, 'B'), ('2025-01-03', -20.0, None, 'C')])

    out = compute_importo(df)

    assert list(out[COL_RUN_TOT]) == [100.0, 70.0, 50.0]
    assert COL_IMP not in out.columns
    assert COL_RUN_TOT not in df.columns  # input untouched


def test_compute_ols_recovers_exact_line():
    dates = pd.date_range('2025-01-01', periods=5, freq='D')
    df = pd.DataFrame({COL_DATA: dates, COL_RUN_TOT: [10.0 * i for i in range(5)]})

    out, m, q = compute_ols(df)

    assert m == pytest.approx(10.0)
    assert list(out[COL_OLS]) == pytest.approx(list(out[COL_RUN_TOT]), abs=1e-6)


def test_compute_ols_needs_two_points():
    df = pd.DataFrame({COL_DATA: pd.to_datetime(['2025-01-01']), COL_RUN_TOT: [1.0]})

    out, m, q = compute_ols(df)

    assert math.isnan(m) and math.isnan(q)
    assert out[COL_OLS].isna().all()


def test_compute_candlesticks_monthly_ohlc():
    df = pd.DataFrame({
        COL_DATA: pd.to_datetime(['2025-01-01', '2025-01-10', '2025-01-20', '2025-02-05']),
        COL_RUN_TOT: [10.0, 30.0, 20.0, 5.0],
    })

    out = compute_candlesticks(df, 'ME')

    assert list(out.columns) == ['Date', 'Open', 'High', 'Low', 'Close']
    jan = out.iloc[0]
    assert (jan.Open, jan.High, jan.Low, jan.Close) == (10.0, 30.0, 10.0, 20.0)
    assert len(out) == 2


def test_compute_candlesticks_bad_timeframe_returns_empty():
    df = pd.DataFrame({COL_DATA: pd.to_datetime(['2025-01-01']), COL_RUN_TOT: [1.0]})

    assert compute_candlesticks(df, 'NOT_A_FREQ').empty


def test_filter_investments_uses_column_and_recomputes_total():
    df = ledger([
        ('2025-01-01', -100.0, None, 'SOTTOSCRIZIONE FONDI'),
        ('2025-01-02', -5.0, None, 'PIZZA'),
        ('2025-01-03', None, 3.0, 'CEDOLE BTP'),
    ])
    df[COL_INV] = [1, 0, 1]
    df = compute_importo(df)

    out = filter_investments(df)

    assert list(out[COL_DESCR]) == ['SOTTOSCRIZIONE FONDI', 'CEDOLE BTP']
    assert list(out[COL_RUN_TOT]) == [-100.0, -97.0]


def test_sort_by_data_contabile_parses_strings():
    df = pd.DataFrame({COL_DATA: ['2025-02-01', '2025-01-01'], COL_MINUS: [-1.0, -2.0]})

    out = sort_by_data_contabile(df)

    assert list(out[COL_MINUS]) == [-2.0, -1.0]
