import math

import pandas as pd
import pytest

from piggy_bank.etica import (COL_DATE, COL_OUT, COL_IN, COL_DESCR, COL_RUN_TOT, COL_OLS, COL_AMOUNT, COL_CLASS,
                              compute_running_total, compute_ols, compute_candlesticks,
                              TF_WEEKLY, TF_MONTHLY, TF_YEARLY, period_start, AggrStats, compute_period_stats,
                              COL_PERIOD,
                              apply_classes, build_view, view_label, CLASS_TODO, sorted_classes,
                              sort_by_date)


def ledger(rows):
    df = pd.DataFrame(rows, columns=[COL_DATE, COL_OUT, COL_IN, COL_DESCR])
    df[COL_DATE] = pd.to_datetime(df[COL_DATE])
    return df


def test_compute_importo_running_total():
    df = ledger([('2025-01-01', None, 100.0, 'A'), ('2025-01-02', -30.0, None, 'B'), ('2025-01-03', -20.0, None, 'C')])

    out = compute_running_total(df)

    assert list(out[COL_RUN_TOT]) == [100.0, 70.0, 50.0]
    assert COL_AMOUNT not in out.columns
    assert COL_RUN_TOT not in df.columns  # input untouched


def test_compute_ols_recovers_exact_line():
    dates = pd.date_range('2025-01-01', periods=5, freq='D')
    df = pd.DataFrame({COL_DATE: dates, COL_RUN_TOT: [10.0 * i for i in range(5)]})

    out, m, q = compute_ols(df)

    assert m == pytest.approx(10.0)
    assert list(out[COL_OLS]) == pytest.approx(list(out[COL_RUN_TOT]), abs=1e-6)


def test_compute_ols_needs_two_points():
    df = pd.DataFrame({COL_DATE: pd.to_datetime(['2025-01-01']), COL_RUN_TOT: [1.0]})

    out, m, q = compute_ols(df)

    assert math.isnan(m) and math.isnan(q)
    assert out[COL_OLS].isna().all()


def test_compute_candlesticks_monthly_ohlc():
    df = pd.DataFrame({
        COL_DATE: pd.to_datetime(['2025-01-01', '2025-01-10', '2025-01-20', '2025-02-05']),
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
    df = pd.DataFrame({COL_DATE: ['2025-01-05', '2025-01-06', '2025-01-12'], COL_RUN_TOT: [1.0, 2.0, 3.0]})

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
    df = pd.DataFrame({COL_DATE: ['2025-01-31', '2025-01-02', '2025-02-01', '2025-02-10'],
                       COL_OUT: [-10.0, 0.0, -5.0, None],
                       COL_IN: [0.0, 100.0, None, 20.0]})

    out = compute_period_stats(df, TF_MONTHLY)

    assert list(out[COL_PERIOD]) == list(pd.to_datetime(['2025-01-01', '2025-02-01']))
    jan, feb = out.iloc[0], out.iloc[1]
    assert (jan[COL_OUT], jan[COL_IN], jan['sum'], jan['entries'], jan['min'], jan['max']) == \
        (-10.0, 100.0, 90.0, 2, -10.0, 100.0)
    assert (feb[COL_OUT], feb[COL_IN], feb['sum'], feb['median']) == (-5.0, 20.0, 15.0, 7.5)


def test_compute_period_stats_empty():
    out = compute_period_stats(pd.DataFrame(columns=[COL_DATE, COL_OUT, COL_IN]), TF_YEARLY)
    assert out.empty and list(out.columns) == [COL_PERIOD, COL_OUT, COL_IN, *AggrStats.FIELDS]


def test_compute_candlesticks_bad_timeframe_returns_empty():
    df = pd.DataFrame({COL_DATE: pd.to_datetime(['2025-01-01']), COL_RUN_TOT: [1.0]})

    assert compute_candlesticks(df, 'NOT_A_FREQ').empty


@pytest.fixture
def classified():
    df = ledger([
        ('2025-01-01', -100.0, None, 'FONDO'),
        ('2025-01-02', -5.0, None, 'PIZZA'),
        ('2025-01-03', None, 3.0, 'CEDOLE'),
        ('2025-01-04', None, 7.0, 'PLAIN'),
    ])
    df[COL_CLASS] = ['investment', 'food', 'investment', CLASS_TODO]
    return df


@pytest.mark.parametrize('exclude, expected', [
    ((), ['FONDO', 'PIZZA', 'CEDOLE', 'PLAIN']),
    (('investment',), ['PIZZA', 'PLAIN']),
    (('investment', CLASS_TODO), ['PIZZA']),
    (('no such class',), ['FONDO', 'PIZZA', 'CEDOLE', 'PLAIN']),
])
def test_apply_classes(classified, exclude, expected):
    assert list(apply_classes(classified, exclude)[COL_DESCR]) == expected


def test_build_view_recomputes_running_total(classified):
    classified = compute_running_total(classified)  # a stale total over all rows must not leak into the view

    view, m, q = build_view(classified, exclude=('food', CLASS_TODO))

    assert list(view[COL_DESCR]) == ['FONDO', 'CEDOLE']
    assert list(view[COL_RUN_TOT]) == [-100.0, -97.0]
    assert m == pytest.approx(1.5)  # +3 EUR over 2 days


def test_view_label():
    assert view_label(()) == 'all classes'
    assert view_label(('a', 'b')) == 'all but a, b'


def test_sorted_classes_puts_todo_last():
    assert sorted_classes(['todo', 'loan', 'investment', 'loan']) == ['investment', 'loan', 'todo']


def test_sort_by_data_contabile_parses_strings():
    df = pd.DataFrame({COL_DATE: ['2025-02-01', '2025-01-01'], COL_OUT: [-1.0, -2.0]})

    out = sort_by_date(df)

    assert list(out[COL_OUT]) == [-2.0, -1.0]
