import logging
import os
import signal
from typing import Optional

import pandas as pd
import plotly.graph_objects as go

from PySide6.QtCore import Qt, QTimer, QCoreApplication, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QTableWidgetItem, QHeaderView, QTableWidget
from PySide6.QtGui import QColor, QPalette, QBrush

try:
    # noinspection unused-imports
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False


from piggy_bank.ui.ledger_rc import Ui_Ledger
from piggy_bank.ui.plots_lines_rc import Ui_PlotsLines
from piggy_bank.ui.plots_stats_rc import Ui_PlotsStats
from piggy_bank.ui.classes_rc import Ui_Classes
from piggy_bank.ui.periods_rc import Ui_Periods
from piggy_bank.ui.movements_table_rc import Ui_MovementsTable
from piggy_bank.ui.periods_table_rc import Ui_PeriodsTable
from piggy_bank.aggr_stats import signed_color, QW_AggrStats
from piggy_bank.etica import (COL_DATE, COL_OUT, COL_IN, COL_DESCR, COL_CLASS, COL_AMOUNT, COL_PERIOD,
                              TF_WEEKLY, TF_MONTHLY, TF_YEARLY, AggrStats, compute_period_stats, sorted_classes)


def install_sigint_handler(app: QCoreApplication, interval_ms: int = 200) -> QTimer:
    """Makes SIGINT (Ctrl+C) quit gracefully, with exit code 128 + SIGINT = 130. Install it as soon as the app exists.

    - While the event loop runs, it calls app.exit(130), and app.exec() returns 130.
    - Before (or after) it, app.exit() would be ignored, so it raises KeyboardInterrupt instead, like Python's
      default handler: the caller must catch it around its startup code (see main_window.main()).

    Python only runs signal handlers when the interpreter gets control back, which never happens
    while Qt sits idle in its C++ event loop. A periodic no-op timer hands control back to Python.
    """
    def _on_sigint(signum, _frame):
        if app.thread().loopLevel() == 0:
            logging.warning('SIGINT received outside the event loop, interrupting')
            raise KeyboardInterrupt
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


class QW_Ledger(QWidget, Ui_Ledger):
    """Custom widget to handle the ledger table."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)


class QW_PlotsLines(QWidget, Ui_PlotsLines):
    """Custom widget to handle the line plots."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)


class QW_PlotsStats(QWidget, Ui_PlotsStats):
    """Custom widget to handle the statistical plots."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)


class StaticColumnsTable:
    """Fills a QTableWidget whose columns are fixed in its .ui: each column shows the DataFrame column named like
    its header text. Add, remove or reorder columns in Designer, no code change needed; a header text not in
    `known` raises ValueError at construction, so a typo shows up at startup.

    Cells are read-only, numeric DataFrame columns sort numerically. default_sort (header text, order) is applied
    once at construction: after that, the sort the user picks by clicking a header is kept across refreshes.
    The stretch column (if present) takes the spare width."""

    def __init__(self, qtw: QTableWidget, known, default_sort: Optional[tuple] = None, stretch: Optional[str] = None):
        self.qtw = qtw
        self.columns = [qtw.horizontalHeaderItem(c).text() for c in range(qtw.columnCount())]
        unknown = [c for c in self.columns if c not in known]
        if unknown:
            raise ValueError(f'{qtw.objectName()}: unknown column headers {unknown}, expected some of {list(known)}')
        qtw.setSortingEnabled(True)
        if stretch in self.columns:
            qtw.horizontalHeader().setSectionResizeMode(self.columns.index(stretch), QHeaderView.ResizeMode.Stretch)
        if default_sort and default_sort[0] in self.columns:
            qtw.sortItems(self.columns.index(default_sort[0]), default_sort[1])

    def show_frame(self, df: pd.DataFrame, formats: Optional[dict] = None, colours: Optional[dict] = None):
        """Fills the table with df, which must have every header column.
        formats: {column: value -> str}; without one, NaN is blank, a float has 2 decimals, the rest is str().
        colours: {column: value -> colour name or None}, for the text."""
        formats, colours = formats or {}, colours or {}
        qtw = self.qtw
        qtw.setSortingEnabled(False)
        qtw.setRowCount(len(df))
        for col_idx, col in enumerate(self.columns):
            numeric = pd.api.types.is_numeric_dtype(df[col])
            fmt = formats.get(col, self.format)
            colour_of = colours.get(col)
            for row_idx, value in enumerate(df[col]):
                text = fmt(value)
                item = NumericTableWidgetItem(text) if numeric else QTableWidgetItem(text)
                colour = colour_of(value) if colour_of else None
                if colour:
                    item.setForeground(QBrush(QColor(colour)))
                item.setToolTip(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                qtw.setItem(row_idx, col_idx, item)
        qtw.setSortingEnabled(True)  # re-sorts by the current sort indicator

    @staticmethod
    def format(value) -> str:
        if pd.isna(value):
            return ''
        return f'{value:.2f}' if isinstance(value, float) else str(value)


class QW_MovementsTable(QWidget, Ui_MovementsTable):
    """Movements (ledger rows) in qtw_movements, columns from movements_table.ui (any of KNOWN), newest first.
    Out and In are 0 when blank in the ledger, and shown blank here too."""
    KNOWN = (COL_DATE, COL_OUT, COL_IN, COL_DESCR, COL_AMOUNT, COL_CLASS)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)
        self.table = StaticColumnsTable(self.qtw_movements, self.KNOWN,
                                        default_sort=(COL_DATE, Qt.SortOrder.DescendingOrder), stretch=COL_DESCR)

    def show_movements(self, df: pd.DataFrame):
        """df: ledger rows with (at least) the header columns, e.g. MainWindow.df_plot."""
        self.table.show_frame(df, formats={COL_OUT: self._amount, COL_IN: self._amount})

    @staticmethod
    def _amount(value) -> str:
        return '' if pd.isna(value) or value == 0 else f'{value:.2f}'


class QW_PeriodsTable(QWidget, Ui_PeriodsTable):
    """Period stats in qtw_periods, columns from periods_table.ui: 'Date' (the period), 'Out', 'In', or an
    AggrStats field capitalised ('Sum', 'Entries', ...). Newest first; the SIGNED fields are green/red."""
    HEADERS = {COL_PERIOD: 'Date', COL_OUT: 'Out', COL_IN: 'In', **{f: f.capitalize() for f in AggrStats.FIELDS}}
    PERIOD_FORMATS = {TF_WEEKLY: '%Y-%m-%d', TF_MONTHLY: '%Y-%m', TF_YEARLY: '%Y'}

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)
        self.table = StaticColumnsTable(self.qtw_periods, self.HEADERS.values(),
                                        default_sort=(self.HEADERS[COL_PERIOD], Qt.SortOrder.DescendingOrder))

    def show_periods(self, df_periods: pd.DataFrame, timeframe: str):
        """df_periods: the output of etica.compute_period_stats() for this timeframe."""
        fmt = self.PERIOD_FORMATS[timeframe]
        formats = {self.HEADERS[COL_PERIOD]: lambda d: d.strftime(fmt),
                   self.HEADERS[COL_OUT]: lambda v: f"{v:.0f}", self.HEADERS[COL_IN]: lambda v: f"{v:.0f}"}
        colours = {}
        for f in AggrStats.FIELDS:
            formats[self.HEADERS[f]] = lambda v, f=f: AggrStats.format(f, v)
            if f in AggrStats.SIGNED:
                colours[self.HEADERS[f]] = signed_color
        self.table.show_frame(df_periods.rename(columns=self.HEADERS), formats, colours)


class QW_Classes(QWidget, Ui_Classes):
    """Classes tab. qtw_tabs has one tab per class among the visible ledger rows (so the ledger filters apply),
    labelled with the class name, each with a QW_MovementsTable of that class's movements (columns from
    movements_table.ui). Alongside, qsac_aggr stacks a QW_AggrStats per visible class (same order), titled with the
    class name, over that class's amounts. qsa_aggr scrolls vertically only: its minimum width fits the boxes.
    The clustering settings (qsb_settings_classes_num = n_clusters, qsb_settings_seed = seed, see
    etica.cluster_auto()) emit clustering_changed, debounced: the owner re-clusters the whole data.
    qhl_charts is not implemented yet."""

    clustering_changed = Signal()
    DEBOUNCE_MS = 1000

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)
        # Re-clustering is expensive: one signal per burst of spin box steps or keystrokes
        self.__timer = QTimer(self)
        self.__timer.setSingleShot(True)
        self.__timer.setInterval(self.DEBOUNCE_MS)
        self.__timer.timeout.connect(self.clustering_changed.emit)
        self.qsb_settings_classes_num.valueChanged.connect(self._on_qsb_settings_classes_num_valueChanged)
        self.qsb_settings_seed.valueChanged.connect(self._on_qsb_settings_seed_valueChanged)
        # {class name: its widget}. A class's widgets are reused while the class stays visible (a table keeps its sort)
        self.__tables = {}
        self.__aggr = {}

    def clustering_settings(self) -> dict:
        """The keyword arguments of etica.cluster_merged() / cluster_auto(): {'n_clusters': ..., 'seed': ...}."""
        return {'n_clusters': self.qsb_settings_classes_num.value(), 'seed': self.qsb_settings_seed.value()}

    @Slot(int)
    def _on_qsb_settings_classes_num_valueChanged(self, _):
        self.__timer.start()

    @Slot(int)
    def _on_qsb_settings_seed_valueChanged(self, _):
        self.__timer.start()

    def class_tables(self) -> dict:
        """{class name: QW_MovementsTable}, in tab order."""
        return dict(self.__tables)

    def class_aggr_stats(self) -> dict:
        """{class name: QW_AggrStats}, in display order."""
        return dict(self.__aggr)

    def update_classes(self, df: pd.DataFrame):
        """Rebuilds the tabs and the stats boxes from df, the visible ledger rows (COL_DATE, COL_OUT, COL_IN,
        COL_DESCR, COL_CLASS, COL_AMOUNT), keeping the current tab selected if its class is still there."""
        tabs = self.qtw_tabs
        current = tabs.tabText(tabs.currentIndex()) if tabs.count() else None
        classes = sorted_classes(df[COL_CLASS]) if not df.empty else []

        tabs.blockSignals(True)
        tabs.clear()  # removes the tabs, not their widgets
        aggr_layout = self.qsac_aggr.layout()
        while aggr_layout.count():
            aggr_layout.takeAt(0)  # detaches the boxes (and the stretch), the boxes stay alive
        for cls in [c for c in self.__tables if c not in classes]:
            self.__tables.pop(cls).deleteLater()
            self.__aggr.pop(cls).deleteLater()

        for cls in classes:
            rows = df[df[COL_CLASS] == cls]
            table = self.__tables.get(cls) or QW_MovementsTable()
            table.show_movements(rows)
            tabs.addTab(table, cls)
            stats = self.__aggr.get(cls) or QW_AggrStats(cls, coloured=True, parent=self.qsac_aggr)
            stats.update_stats(rows[COL_AMOUNT].tolist())
            aggr_layout.addWidget(stats)
            self.__tables[cls], self.__aggr[cls] = table, stats
        aggr_layout.addStretch()
        # Display order
        self.__tables = {cls: self.__tables[cls] for cls in classes}
        self.__aggr = {cls: self.__aggr[cls] for cls in classes}

        if current in self.__tables:
            tabs.setCurrentIndex(classes.index(current))
        tabs.blockSignals(False)

        # Never scrolls horizontally: always wide enough for the boxes plus the vertical scroll bar
        sa = self.qsa_aggr
        sa.setMinimumWidth(aggr_layout.sizeHint().width() + sa.verticalScrollBar().sizeHint().width()
                           + 2 * sa.frameWidth())


class QW_Periods(QWidget, Ui_Periods):
    """Periods tab: a QW_PeriodsTable in qvl_periods with one row per period (qcb_periods_time) of the visible
    ledger rows: outflows, inflows and the etica.AggrStats of the amounts."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)
        self.table = QW_PeriodsTable(self)
        self.qvl_periods.addWidget(self.table)

        self.__df = pd.DataFrame(columns=[COL_DATE, COL_OUT, COL_IN])
        self.qcb_periods_time.currentIndexChanged.connect(self._on_qcb_periods_time_currentIndexChanged)

    def timeframe(self) -> str:
        return self.qcb_periods_time.currentText()

    def update_periods(self, df: pd.DataFrame):
        """Stores df (the visible ledger rows: COL_DATE, COL_OUT, COL_IN) and refreshes the table."""
        self.__df = df
        self._populate()

    @Slot(int)
    def _on_qcb_periods_time_currentIndexChanged(self, _index: int):
        self._populate()

    def _populate(self):
        timeframe = self.timeframe()
        self.table.show_periods(compute_period_stats(self.__df, timeframe), timeframe)
