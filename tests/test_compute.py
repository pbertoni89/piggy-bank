import math

import pandas as pd
import pytest

from piggy_bank.etica import (COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR, COL_RUN_TOT, COL_OLS, COL_IMP, COL_INV,
                              compute_importo, compute_ols, compute_candlesticks,
                              TF_WEEKLY, TF_MONTHLY, TF_YEARLY, period_start, AggrStats, compute_period_stats,
                              COL_PERIOD,
                              COL_BL, MODE_ALL, MODE_FORCE, MODE_VETO, mode_keeps, apply_modes, build_view,
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

    out = compute_candlesticks(df, TF_MONTHLY)

    assert list(out.columns) == ['Date', 'Open', 'High', 'Low', 'Close']
    jan = out.iloc[0]
    assert (jan.Open, jan.High, jan.Low, jan.Close) == (10.0, 30.0, 10.0, 20.0)
    assert len(out) == 2
    assert list(out['Date']) == list(pd.to_datetime(['2025-01-01', '2025-02-01']))  # months start on the 1st


def test_compute_candlesticks_weekly_starts_on_monday():
    # Sun 5 Jan closes the week of Mon 30 Dec; Mon 6 Jan opens the next one
    df = pd.DataFrame({COL_DATA: ['2025-01-05', '2025-01-06', '2025-01-12'], COL_RUN_TOT: [1.0, 2.0, 3.0]})

    out = compute_candlesticks(df, TF_WEEKLY)

    assert list(out['Date']) == list(pd.to_datetime(['2024-12-30', '2025-01-06']))
    assert list(out['Close']) == [1.0, 3.0]


@pytest.mark.parametrize('timeframe, expected', [
    (TF_WEEKLY, ['2024-12-30', '2025-01-06', '2025-12-29']),
    (TF_MONTHLY, ['2025-01-01', '2025-01-01', '2025-12-01']),
    (TF_YEARLY, ['2025-01-01', '2025-01-01', '2025-01-01'])])
def test_period_start(timeframe, expected):
    dates = pd.Series(['2025-01-05', '2025-01-06', '2025-12-31'])
    assert list(period_start(dates, timeframe)) == list(pd.to_datetime(expected))


def test_aggr_stats():
    st = AggrStats([1.0, 2.0, 3.0, 10.0])
    assert (st.entries, st.min, st.max, st.sum, st.median, st.avg) == (4, 1.0, 10.0, 16.0, 2.5, 4.0)
    assert st.text('entries') == '4' and st.text('median') == '2' and st.text('std') == f'{st.std:.2f}'


def test_aggr_stats_empty_and_single():
    empty = AggrStats([])
    assert empty.entries == 0 and empty.sum == 0 and math.isnan(empty.min)
    assert AggrStats([5.0]).text('std') == '0.00'  # undefined for a single value


def test_compute_period_stats_monthly():
    df = pd.DataFrame({COL_DATA: ['2025-01-31', '2025-01-02', '2025-02-01', '2025-02-10'],
                       COL_MINUS: [-10.0, 0.0, -5.0, None],
                       COL_PLUS: [0.0, 100.0, None, 20.0]})

    out = compute_period_stats(df, TF_MONTHLY)

    assert list(out[COL_PERIOD]) == list(pd.to_datetime(['2025-01-01', '2025-02-01']))
    jan, feb = out.iloc[0], out.iloc[1]
    assert (jan[COL_MINUS], jan[COL_PLUS], jan['sum'], jan['entries'], jan['min'], jan['max']) == \
        (-10.0, 100.0, 90.0, 2, -10.0, 100.0)
    assert (feb[COL_MINUS], feb[COL_PLUS], feb['sum'], feb['median']) == (-5.0, 20.0, 15.0, 7.5)


def test_compute_period_stats_empty():
    out = compute_period_stats(pd.DataFrame(columns=[COL_DATA, COL_MINUS, COL_PLUS]), TF_YEARLY)
    assert out.empty and list(out.columns) == [COL_PERIOD, COL_MINUS, COL_PLUS, *AggrStats.FIELDS]


def test_compute_candlesticks_bad_timeframe_returns_empty():
    df = pd.DataFrame({COL_DATA: pd.to_datetime(['2025-01-01']), COL_RUN_TOT: [1.0]})

    assert compute_candlesticks(df, 'NOT_A_FREQ').empty


@pytest.mark.parametrize('mode, kept', [(MODE_ALL, [0, 1]), (MODE_FORCE, [1]), (MODE_VETO, [0])])
def test_mode_keeps(mode, kept):
    assert [flag for flag in (0, 1) if mode_keeps(mode, flag)] == kept


def test_mode_keeps_rejects_unknown_mode():
    with pytest.raises(ValueError, match='Unknown filter mode'):
        mode_keeps('only', 1)


@pytest.fixture
def flagged():
    df = ledger([
        ('2025-01-01', -100.0, None, 'BL INV'),
        ('2025-01-02', -5.0, None, 'BL'),
        ('2025-01-03', None, 3.0, 'INV'),
        ('2025-01-04', None, 7.0, 'PLAIN'),
    ])
    df[COL_BL] = [1, 1, 0, 0]
    df[COL_INV] = [1, 0, 1, 0]
    return df


@pytest.mark.parametrize('bl, inv, expected', [
    (MODE_ALL, MODE_ALL, ['BL INV', 'BL', 'INV', 'PLAIN']),
    (MODE_VETO, MODE_ALL, ['INV', 'PLAIN']),
    (MODE_FORCE, MODE_ALL, ['BL INV', 'BL']),
    (MODE_ALL, MODE_FORCE, ['BL INV', 'INV']),
    (MODE_ALL, MODE_VETO, ['BL', 'PLAIN']),
    (MODE_VETO, MODE_VETO, ['PLAIN']),
    (MODE_FORCE, MODE_FORCE, ['BL INV']),
])
def test_apply_modes_treats_both_flags_alike(flagged, bl, inv, expected):
    assert list(apply_modes(flagged, bl=bl, inv=inv)[COL_DESCR]) == expected


def test_build_view_recomputes_running_total(flagged):
    flagged = compute_importo(flagged)  # a stale total over all rows must not leak into the view

    view, m, q = build_view(flagged, inv=MODE_FORCE)

    assert list(view[COL_DESCR]) == ['BL INV', 'INV']
    assert list(view[COL_RUN_TOT]) == [-100.0, -97.0]
    assert m == pytest.approx(1.5)  # +3 EUR over 2 days


def test_sort_by_data_contabile_parses_strings():
    df = pd.DataFrame({COL_DATA: ['2025-02-01', '2025-01-01'], COL_MINUS: [-1.0, -2.0]})

    out = sort_by_data_contabile(df)

    assert list(out[COL_MINUS]) == [-2.0, -1.0]
