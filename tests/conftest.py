import os

# Qt widgets must be creatable without a display (CI, ssh, ...)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pandas as pd
import pytest

from piggy_bank import etica
from piggy_bank.etica import COL_DATA, COL_MINUS, COL_PLUS, COL_DESCR

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
