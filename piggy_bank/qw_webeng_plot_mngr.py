import logging
import plotly.graph_objects as go

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtGui import QColor

try:
    # noinspection unused-imports
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False


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
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if HAS_WEBENGINE:
            self.web_view = QWebEngineView()
            # Force background color instantly to prevent white flashing during load
            self.web_view.page().setBackgroundColor(QColor('#111111'))
            self.web_view.setHtml(get_html_centered_message("Loading data..."))
            layout.addWidget(self.web_view)
        else:
            logging.error("PySide6.QtWebEngineWidgets not found. Plotting disabled.")
            self.web_view = None
            lbl = QLabel("Plotting requires PySide6-WebEngine module.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)

    def render_figure(self, fig: go.Figure):
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
