import logging
import os
import signal
from typing import Optional

import plotly.graph_objects as go

from PySide6.QtCore import Qt, QTimer, QCoreApplication
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QTableWidgetItem
from PySide6.QtGui import QColor, QPalette

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


ENV_COLOR_SCHEME = 'PIGGYBANK_COLOR_SCHEME'


def dark_palette() -> QPalette:
    """A dark palette for the Fusion style, close to Qt's own Fusion dark scheme."""
    window, base, text, accent = QColor('#323232'), QColor('#1e1e1e'), QColor('#f0f0f0'), QColor('#2a82da')
    disabled = QColor('#7f7f7f')
    p = QPalette()
    for role, colour in (
            (QPalette.ColorRole.Window, window),
            (QPalette.ColorRole.WindowText, text),
            (QPalette.ColorRole.Base, base),
            (QPalette.ColorRole.AlternateBase, QColor('#2a2a2a')),
            (QPalette.ColorRole.ToolTipBase, window),
            (QPalette.ColorRole.ToolTipText, text),
            (QPalette.ColorRole.PlaceholderText, QColor('#9a9a9a')),
            (QPalette.ColorRole.Text, text),
            (QPalette.ColorRole.Button, QColor('#3c3c3c')),
            (QPalette.ColorRole.ButtonText, text),
            (QPalette.ColorRole.BrightText, QColor('#ff5555')),
            (QPalette.ColorRole.Light, QColor('#505050')),
            (QPalette.ColorRole.Midlight, QColor('#424242')),
            (QPalette.ColorRole.Mid, QColor('#2b2b2b')),
            (QPalette.ColorRole.Dark, QColor('#1a1a1a')),
            (QPalette.ColorRole.Shadow, QColor('#000000')),
            (QPalette.ColorRole.Highlight, accent),
            (QPalette.ColorRole.HighlightedText, QColor('#ffffff')),
            (QPalette.ColorRole.Link, accent),
            (QPalette.ColorRole.LinkVisited, QColor('#a070d0'))):
        p.setColor(role, colour)
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText, QPalette.ColorRole.HighlightedText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor('#505050'))
    return p


def apply_color_scheme(app: QApplication, scheme: Optional[str] = None) -> str:
    """Applies the colour scheme requested by $PIGGYBANK_COLOR_SCHEME ('dark' or 'light'), or by `scheme`.

    Unset means: leave it to Qt, which follows the desktop on a native host. In Docker, Qt can't
    see the desktop's setting, so driver.sh reads it on the host and passes it in this variable.
    The platform's own dark scheme is preferred. If the platform ignores the request (Qt's generic
    theme, used in the container, does), it falls back to Fusion with `dark_palette()`.
    Returns what was applied: '' (nothing), 'light', 'dark' (platform) or 'dark-fusion'.
    """
    scheme = (os.environ.get(ENV_COLOR_SCHEME, '') if scheme is None else scheme).strip().lower()
    if not scheme:
        return ''
    wanted = {'dark': Qt.ColorScheme.Dark, 'light': Qt.ColorScheme.Light}.get(scheme)
    if wanted is None:
        logging.warning(f"Ignoring {ENV_COLOR_SCHEME}={scheme!r}: expected 'dark' or 'light'")
        return ''
    hints = app.styleHints()
    hints.setColorScheme(wanted)
    if hints.colorScheme() == wanted or wanted == Qt.ColorScheme.Light:
        # Light is Qt's default anyway when the platform has no scheme of its own
        logging.debug(f"Colour scheme: {scheme} (platform)")
        return scheme
    app.setStyle('Fusion')
    app.setPalette(dark_palette())
    logging.debug("Colour scheme: dark (Fusion palette, the platform ignored the request)")
    return 'dark-fusion'


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
