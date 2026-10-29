import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip('piggy_bank.ui.ledger_rc', reason='UI not built, run ./driver.sh -b')

ROOT = Path(__file__).parent.parent

# Runs in a separate process: app.exit() ends every event loop, which would break pytest-qt's shared QApplication
SCRIPT = textwrap.dedent('''
    import sys
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from piggy_bank.qw_misc import install_sigint_handler

    app = QApplication(sys.argv)
    install_sigint_handler(app, interval_ms=50)
    print('ready', flush=True)
    QTimer.singleShot(10000, lambda: app.exit(-1))  # safety net if SIGINT is never handled
    sys.exit(app.exec())
''')


def test_sigint_quits_event_loop_gracefully():
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONPATH': str(ROOT)}
    proc = subprocess.Popen([sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == 'ready'
        proc.send_signal(signal.SIGINT)
        _, stderr = proc.communicate(timeout=15)
    finally:
        proc.kill()

    assert proc.returncode == 128 + signal.SIGINT, stderr
    assert 'SIGINT received' in stderr
    assert 'Traceback' not in stderr
