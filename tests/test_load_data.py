import pandas as pd
import pytest

from piggy_bank import etica
from piggy_bank.etica import COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR, load_data


def test_merges_and_sorts_all_statements(write_csv, data_dir):
    write_csv('estrattocontoitalia-2025.csv', [
        ('2025-03-01', -10.0, None, 'COFFEE'),
        ('2025-01-01', None, 100.0, 'SALARY'),
    ])
    write_csv('estrattocontoitalia-2024.csv', [
        ('2024-12-31', -5.0, None, 'BREAD'),
    ])

    df = load_data()

    assert list(df[COL_DESCR]) == ['BREAD', 'SALARY', 'COFFEE']
    assert pd.api.types.is_datetime64_any_dtype(df[COL_DATA])
    # Classes are cluster_merged()'s job
    assert list(df.columns) == [COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR]


def test_same_date_order_is_deterministic(write_csv):
    write_csv('a.csv', [('2025-01-01', -1.0, None, 'B'), ('2025-01-01', -2.0, None, 'A')])

    df = load_data()

    # Tiebreak on Dare ascending
    assert list(df[COL_MINUS]) == [-2.0, -1.0]


def test_writes_merged_csv_and_ignores_it_on_reload(write_csv, data_dir):
    write_csv('a.csv', [('2025-01-01', -1.0, None, 'X')])

    load_data()
    assert (data_dir / 'merged.csv').exists()

    # merged.csv must not be read back in, otherwise rows would double up (then be deduplicated)
    df = load_data()
    assert len(df) == 1


def test_backup_files_are_ignored(write_csv, data_dir):
    write_csv('a.csv', [('2025-01-01', -1.0, None, 'X')])
    (data_dir / 'old.csv.bk').write_text((data_dir / 'a.csv').read_text().replace('X', 'Y'))

    df = load_data()

    assert list(df[COL_DESCR]) == ['X']


def test_overlapping_exports_are_deduplicated(write_csv):
    write_csv('2024.csv', [('2024-01-01', -1.0, None, 'X'), ('2024-02-01', -2.0, None, 'Y')])
    write_csv('2024-bis.csv', [('2024-02-01', -2.0, None, 'Y'), ('2024-03-01', -3.0, None, 'Z')])

    df = load_data()

    assert list(df[COL_DESCR]) == ['X', 'Y', 'Z']


def test_identical_rows_are_collapsed_known_limitation(write_csv):
    """Two genuinely distinct but identical transactions (e.g. two SEPA fees on the same day)
    are indistinguishable from an overlapping export, so one is dropped. Accepted limitation."""
    write_csv('a.csv', [('2025-01-01', -1.0, None, 'COMMISSIONI'), ('2025-01-01', -1.0, None, 'COMMISSIONI')])

    df = load_data()

    assert len(df) == 1


def test_xls_is_converted_to_csv_and_removed(data_dir, monkeypatch):
    xls = data_dir / 'estrattocontoitalia-2025.xls'
    xls.write_bytes(b'not really excel')
    fake = pd.DataFrame({COL_DATA: ['2025-01-01'], COL_MINUS: [-1.0], COL_PLUS: [None],
                         COL_DESCR: ['X'], 'Valuta': ['2025-01-02'], 'Divisa': ['EUR'], 'Causale': ['42']})
    monkeypatch.setattr(etica.pd, 'read_excel', lambda path: fake.copy())

    df = load_data()

    assert not xls.exists()
    converted = pd.read_csv(data_dir / 'estrattocontoitalia-2025.csv')
    assert list(converted.columns) == [COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR]
    assert len(df) == 1


def test_description_noise_is_stripped(write_csv):
    write_csv('a.csv', [
        ('2025-01-01', None, 50.0, 'Bonifico - SEPA istantaneo a vs favore MARIO'),
        ('2025-01-02', -50.0, None, 'ADDEBITO BONIFICO DA HOME BANKING LUIGI'),
    ])

    df = load_data()

    assert list(df[COL_DESCR]) == ['<BONIF> MARIO', '<BONIF> LUIGI']


def test_rules_and_archived_blacklist_are_not_statements(write_csv, write_classes, data_dir):
    write_csv('a.csv', [('2025-01-01', -1.0, None, 'X')])
    write_csv('blacklist.csv', [(None, None, None, 'X')])
    write_classes(['*,*,*,X,misc'])

    df = load_data()

    assert len(df) == 1
    assert list(pd.read_csv(data_dir / 'merged.csv').columns) == [COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR]
