import logging
import signal
from typing import Optional

import plotly.graph_objects as go

from PySide6.QtCore import Qt, QTimer, QCoreApplication
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QTableWidgetItem
from PySide6.QtGui import QColor

try:
    # noinspection unused-imports
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False


from piggy_bank.ui.ledger_rc import Ui_Ledger
from piggy_bank.ui.plots_lines_rc import Ui_PlotsLines
from piggy_bank.ui.plots_stats_rc import Ui_PlotsStats


def install_sigint_handler(app: QCoreApplication, interval_ms: int = 200) -> QTimer:
    """Makes SIGINT (Ctrl+C) quit the Qt event loop gracefully, with exit code 128 + SIGINT = 130.

    Python only runs signal handlers when the interpreter gets control back, which never happens
    while Qt sits idle in its C++ event loop. A periodic no-op timer hands control back to Python.
    """
    def _on_sigint(signum, _frame):
        logging.warning('SIGINT received, quitting')
        app.exit(128 + signum)

    signal.signal(signal.SIGINT, _on_sigint)
    timer = QTimer(app)
    timer.timeout.connect(lambda: None)
    timer.start(interval_ms)
    return timer


def get_html_centered_message(msg: str) -> str:
    return f"""
            <!DOCTYPE html>
            <html>
            <head>
            <style>
              html, body {{
                height: 100%;
                width: 100%;
                margin: 0;
                padding: 0;
                display: flex;
                justify-content: center;
                align-items: center;
                font-family: sans-serif;
                background-color: #111111; /* Match dark theme */
                color: #ffffff; /* Match dark theme text */
                overflow: hidden;
              }}
            </style>
            </head>
            <body>
              <h3>{msg}</h3>
            </body>
            </html>
            """


class WebEnginePlotManager(QWidget):
    """Encapsulates a single Plotly go.Figure into a QWebEngineView."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if HAS_WEBENGINE:
            self.web_view = QWebEngineView()
            # Force background colour instantly to prevent white flashing during load
            self.web_view.page().setBackgroundColor(QColor('#111111'))
            self.web_view.setHtml(get_html_centered_message("Loading data..."))
            layout.addWidget(self.web_view)
        else:
            logging.error("PySide6.QtWebEngineWidgets not found. Plotting disabled.")
            self.web_view = None
            lbl = QLabel("Plotting requires PySide6-WebEngine module.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)

    def render_figure(self, fig: Optional[go.Figure]):
        """Generates the HTML for the provided Plotly figure and sends it to the webview."""
        if not HAS_WEBENGINE or self.web_view is None:
            return

        if fig is None:
            self.web_view.setHtml(get_html_centered_message("No data to display"))
            return

        # We must set autosize=True for dynamic resizing
        fig.update_layout(template='plotly_dark', margin=dict(l=20, r=20, t=40, b=20), autosize=True)

        config = {'responsive': True}
        raw_html = fig.to_html(include_plotlyjs='cdn', full_html=False, config=config)

        # Use string replacement to inject styling directly into the <body> tag
        # This removes the white border without breaking Plotly's responsiveness
        html = raw_html.replace(
            '<body>',
            '<body style="margin: 0px; padding: 0px; background-color: #111111; overflow: hidden;">'
        )

        # Push to web engine
        self.web_view.setHtml(html)


class NumericTableWidgetItem(QTableWidgetItem):
    """Custom TableWidgetItem that sorts numerically instead of alphabetically."""
    def __lt__(self, other):
        try:
            val1 = float(self.text().strip()) if self.text().strip() else 0.0
            val2 = float(other.text().strip()) if other.text().strip() else 0.0
            return val1 < val2
        except ValueError:
            return super().__lt__(other)


class Ledger(QWidget, Ui_Ledger):
    """Custom widget to handle the ledger table."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)


class PlotsLines(QWidget, Ui_PlotsLines):
    """Custom widget to handle the line plots."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)


class PlotsStats(QWidget, Ui_PlotsStats):
    """Custom widget to handle the statistical plots."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)
