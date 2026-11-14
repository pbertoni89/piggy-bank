import os
import signal
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from pathlib import Path

import pytest

pytest.importorskip('piggy_bank.ui.ledger_rc', reason='UI not built, run ./driver.sh --build-gui')

ROOT = Path(__file__).parent.parent

# Runs in a separate process: app.exit() ends every event loop, which would break pytest-qt's shared QApplication
SCRIPT = textwrap.dedent('''
    import sys
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from piggy_bank.qw_misc import install_sigint_handler

    app = QApplication(sys.argv)
    install_sigint_handler(app, interval_ms=50)
    # Announced from inside the event loop: app.exit() before app.exec() starts is ignored, so a SIGINT
    # sent right after a 'ready' printed before exec() could be lost on a busy machine
    QTimer.singleShot(0, lambda: print('ready', flush=True))
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


# Startup work (e.g. loading data) before app.exec(): SIGINT must interrupt it, not wait for the event loop
SCRIPT_STARTUP = textwrap.dedent('''
    import sys, time
    from PySide6.QtWidgets import QApplication
    from piggy_bank.qw_misc import install_sigint_handler

    app = QApplication(sys.argv)
    install_sigint_handler(app, interval_ms=50)
    try:
        print('ready', flush=True)
        deadline = time.monotonic() + 10  # a long startup, never reaching app.exec()
        while time.monotonic() < deadline:
            time.sleep(0.01)
    except KeyboardInterrupt:
        sys.exit(130)
    sys.exit(-1)
''')


def test_sigint_interrupts_startup():
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONPATH': str(ROOT)}
    proc = subprocess.Popen([sys.executable, '-c', SCRIPT_STARTUP], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == 'ready'
        proc.send_signal(signal.SIGINT)
        _, stderr = proc.communicate(timeout=15)
    finally:
        proc.kill()

    assert proc.returncode == 128 + signal.SIGINT, stderr
    assert 'SIGINT received outside the event loop' in stderr
    assert 'Traceback' not in stderr


def test_main_installs_sigint_handler_before_loading(monkeypatch):
    """main() must install the handler before building the window (which loads the data)."""
    from piggy_bank import main_window
    calls = []

    class Stop(Exception):
        pass

    fake_app = SimpleNamespace(setWindowIcon=lambda icon: None)
    monkeypatch.setattr(main_window, 'QApplication', lambda argv: calls.append('app') or fake_app)
    monkeypatch.setattr(main_window, 'install_sigint_handler', lambda app: calls.append('sigint'))
    monkeypatch.setattr(main_window, 'apply_color_scheme', lambda app: None)
    monkeypatch.setattr(main_window, 'init_logging', lambda *a, **k: None)
    monkeypatch.setattr(main_window, 'QIcon', lambda path: None)

    def window():
        calls.append('window')
        raise Stop
    monkeypatch.setattr(main_window, 'MainWindow', window)

    with pytest.raises(Stop):
        main_window.main()
    assert calls == ['app', 'sigint', 'window']
