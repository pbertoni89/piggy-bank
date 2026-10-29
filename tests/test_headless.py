"""Smoke tests for the deprecated headless entry points: driver.py and the etica.ipynb notebook."""
import json
import runpy
from pathlib import Path

import matplotlib
import pytest

matplotlib.use('Agg')

import matplotlib.pyplot as plt  # noqa: E402
import plotly.graph_objects as go  # noqa: E402

ROOT = Path(__file__).parent.parent / 'piggy_bank'

# No Saturdays, spread over months so candlesticks have more than one bar
ROWS = [
    ('2025-01-02', None, 1000.0, 'STIPENDIO'),
    ('2025-01-03', -100.0, None, 'PIZZA'),
    ('2025-02-03', -500.0, None, 'SOTTOSCRIZIONE TIME DEPOSIT'),
    ('2025-03-03', None, 20.0, 'Cedole BTP'),
    ('2025-04-01', -300.0, None, 'GIROCONTO'),
    ('2025-05-02', None, 1000.0, 'STIPENDIO'),
]


@pytest.fixture
def data(write_csv, monkeypatch):
    write_csv('a.csv', ROWS)
    write_csv('blacklist.csv', [(None, None, None, 'GIROCONTO')])
    monkeypatch.setattr(go.Figure, 'show', lambda self, *a, **k: None)
    monkeypatch.setattr(plt, 'show', lambda *a, **k: plt.close('all'))


def test_driver_prints_every_view(data, capsys, caplog):
    caplog.set_level('INFO')

    runpy.run_path(str(ROOT / 'driver.py'), run_name='__main__')

    assert 'Blacklisted: 1, Investments: 2' in capsys.readouterr().out
    from piggy_bank.etica import DEFAULT_VIEWS, view_label
    for bl, inv in DEFAULT_VIEWS:
        assert view_label(bl, inv) in caplog.text


def test_notebook_cells_run(data):
    nb = json.loads((ROOT / 'etica.ipynb').read_text())
    namespace = {}
    for cell in nb['cells']:
        if cell['cell_type'] != 'code':
            continue
        # Drop IPython magics, they are not Python
        source = ''.join(line for line in cell['source'] if not line.lstrip().startswith('%'))
        exec(compile(source, 'etica.ipynb', 'exec'), namespace)

    assert len(namespace['_views']) == len(namespace['DEFAULT_VIEWS'])
