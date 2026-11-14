import os

# Qt widgets must be creatable without a display (CI, ssh, ...)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pandas as pd
import pytest

from piggy_bank import etica
from piggy_bank.etica import COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR, CUSTOM_CLASSES_CSV, RULE_COLUMNS

HEADER = [COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """An empty DATA_DIR that load_data() will read from (and write merged.csv into)."""
    monkeypatch.setattr(etica, 'DATA_DIR', tmp_path)
    return tmp_path


@pytest.fixture
def write_csv(data_dir):
    """Writes rows (date, dare, avere, descrizione) as a CSV in DATA_DIR, None meaning an empty cell."""
    def _write(name: str, rows: list):
        pd.DataFrame(rows, columns=HEADER).to_csv(data_dir / name, index=False)
        return data_dir / name
    return _write


@pytest.fixture
def write_classes(data_dir):
    """Writes custom-classes.csv in DATA_DIR: the header, then each line verbatim (e.g. '*,*,*,PIZZA,food')."""
    def _write(lines: list, header: str = ','.join(RULE_COLUMNS)):
        path = data_dir / CUSTOM_CLASSES_CSV
        path.write_text('\n'.join([header, *lines]) + '\n')
        return path
    return _write
