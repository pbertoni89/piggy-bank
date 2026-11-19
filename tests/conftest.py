import os

# Qt widgets must be creatable without a display (CI, ssh, ...)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import zlib

import numpy as np
import pandas as pd
import pytest

from piggy_bank import etica
from piggy_bank.etica import CUSTOM_CLASSES_CSV, RULE_COLUMNS, SOURCE_COLUMNS, SED_DESCRIPTIONS_CSV, SED_COLUMNS

# Source statements keep Banca Etica's Italian headers: 'Data contabile', 'Dare', 'Avere', 'Descrizione'
SOURCE_HEADER = list(SOURCE_COLUMNS)


@pytest.fixture(autouse=True)
def flush_deferred_deletes():
    """After each test, runs the deleteLater()s that closing its widgets queued.

    Destroying a QWebEngineView queues the deletion of QtWebEngine internals, and no event loop runs
    after a test to process them. Left queued, they run while Python exits, after QtWebEngine has torn
    down its profile, and the interpreter crashes with SIGSEGV (exit code 139) once every test passed."""
    yield
    import gc
    from PySide6.QtCore import QCoreApplication, QEvent
    if QCoreApplication.instance() is not None:
        gc.collect()  # drop the test's last references to its widgets first
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """An empty DATA_DIR that load_data() will read from (and write merged.csv into)."""
    monkeypatch.setattr(etica, 'DATA_DIR', tmp_path)
    return tmp_path


@pytest.fixture
def write_csv(data_dir):
    """Writes rows (date, out, in, description) as a source statement CSV in DATA_DIR, None meaning an empty cell."""
    def _write(name: str, rows: list):
        pd.DataFrame(rows, columns=SOURCE_HEADER).to_csv(data_dir / name, index=False)
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


def fake_embed_texts(texts: list) -> np.ndarray:
    """Stands in for etica.embed_texts(): a normalised bag of words hashed into 64 dimensions. Deterministic,
    no model to load, and descriptions sharing words end up close, like real embeddings."""
    vectors = np.zeros((len(texts), 64))
    for row, text in enumerate(texts):
        for word in text.lower().split():
            vectors[row, zlib.crc32(word.encode()) % 64] += 1
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    """Tests never load the sentence_transformers model (slow, maybe a download)."""
    monkeypatch.setattr(etica, 'embed_texts', fake_embed_texts)


@pytest.fixture
def auto_off(monkeypatch):
    """No automatic clustering, whatever the settings: movements no custom rule matches stay CLASS_TODO."""
    monkeypatch.setattr(etica, 'cluster_auto', lambda df, classes, **kwargs: classes)


@pytest.fixture
def write_sed(data_dir):
    """Writes sed-descriptions.csv in DATA_DIR: the header, then each line verbatim (e.g. 'BONIFICO,<BONIF>')."""
    def _write(lines: list, header: str = ','.join(SED_COLUMNS)):
        path = data_dir / SED_DESCRIPTIONS_CSV
        path.write_text('\n'.join([header, *lines]) + '\n')
        return path
    return _write
