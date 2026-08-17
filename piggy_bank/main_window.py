# noinspection unresolved-references
import re
import sys
from PySide6.QtCore import Signal, Slot, QDate, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QHeaderView, QWidget, QLabel, QVBoxLayout

try:
    # noinspection unused-imports
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

from piggy_bank.ui.main_window_rc import Ui_MainWindow
from piggy_bank.ui.aggr_stats_rc import Ui_AggrStats
from piggy_bank.ui.filter_tools_rc import Ui_FilterTools
from piggy_bank.etica import *


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


class NumericTableWidgetItem(QTableWidgetItem):
    """Custom TableWidgetItem that sorts numerically instead of alphabetically."""
    def __lt__(self, other):
        try:
            val1 = float(self.text().strip()) if self.text().strip() else 0.0
            val2 = float(other.text().strip()) if other.text().strip() else 0.0
            return val1 < val2
        except ValueError:
            return super().__lt__(other)


class FilterTools(QWidget, Ui_FilterTools):
    """Custom widget to handle filter tools."""

    # Custom signal emitted when filters are stable and ready to be applied
    filters_updated = Signal()
    plots_updated = Signal()

    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # Store startup default states
        self._default_start_date = QDate()
        self._default_end_date = QDate()
        self._default_out_range = (0, 1000)
        self._default_in_range = (0, 1000)

        # Setup Default Filter State for Radio Buttons
        if not any([qrb.isChecked() for qrb in [self.qrb_all, self.qrb_bl_no, self.qrb_bl_only, self.qrb_inv_only, self.qrb_inv_no]]):
            self.qrb_all.setChecked(True)

        # --- Set up the debouncing timer ---
        self.__timer = QTimer(self)
        self.__timer.setSingleShot(True)  # Ensures it only fires once per timeout
        self.__timer.setInterval(1000)
        self.__timer.timeout.connect(self.filters_updated.emit)

        # Set qde_start and qde_end to the min and max dates
        if not df.empty:
            dates = pd.to_datetime(df[COL_DATA], errors='coerce')
            min_date, max_date = dates.min(), dates.max()

            if not pd.isna(min_date):
                self._default_start_date = QDate(min_date.year, min_date.month, min_date.day)
                self.qde_start.setDate(QDate(min_date.year, min_date.month, min_date.day))
            if not pd.isna(max_date):
                self._default_end_date = QDate(max_date.year, max_date.month, max_date.day)
                self.qde_end.setDate(QDate(max_date.year, max_date.month, max_date.day))

        # Hook up internal signals to internal slots
        self.qrs_out.valueChanged.connect(self._on_qrs_out_valueChanged)
        self.qrs_in.valueChanged.connect(self._on_qrs_in_valueChanged)
        self.qchk_out.toggled.connect(self._on_qchk_out_toggled)
        self.qchk_in.toggled.connect(self._on_qchk_in_toggled)
        self.qrb_all.toggled.connect(self._on_bg_filter_toggled)
        self.qrb_bl_no.toggled.connect(self._on_bg_filter_toggled)
        self.qrb_bl_only.toggled.connect(self._on_bg_filter_toggled)
        self.qrb_inv_only.toggled.connect(self._on_bg_filter_toggled)
        self.qrb_inv_no.toggled.connect(self._on_bg_filter_toggled)

        self.qrb_plot_line.toggled.connect(self._on_bg_plot_toggled)
        self.qrb_plot_candle_w.toggled.connect(self._on_bg_plot_toggled)
        self.qrb_plot_candle_m.toggled.connect(self._on_bg_plot_toggled)

        self.qle_description.textChanged.connect(self._on_qle_description_textChanged)
        self.qde_start.dateChanged.connect(self._on_qde_start_dateChanged)
        self.qde_end.dateChanged.connect(self._on_qde_end_dateChanged)
        self.qpb_reset.clicked.connect(self._on_qpb_reset_clicked)

    def setup_sliders(self, df: pd.DataFrame):
        """Calculates min/max from the dataframe and configures range sliders."""
        ser_out = pd.to_numeric(df[COL_MINUS], errors='coerce').dropna()
        ser_in = pd.to_numeric(df[COL_PLUS], errors='coerce').dropna()

        incl = 0  # Inclusive max for slider
        out_min = int(ser_out.min()) if not ser_out.empty else 0
        out_max = int(ser_out.max()) + incl if not ser_out.empty else 1000

        in_min = int(ser_in.min()) if not ser_in.empty else 0
        in_max = int(ser_in.max()) + incl if not ser_in.empty else 1000

        # Store startup defaults
        self._default_out_range = (out_min, out_max)
        self._default_in_range = (in_min, in_max)

        # Block signals temporarily to prevent early filtering during setup
        self.qrs_out.blockSignals(True)
        self.qrs_out.setMinimum(out_min)
        self.qrs_out.setMaximum(out_max)
        self.qrs_out.setValue((out_min, out_max))
        self.ql_out_min.setText(str(out_min))
        self.ql_out_max.setText(str(out_max))
        self.qrs_out.blockSignals(False)

        self.qrs_in.blockSignals(True)
        self.qrs_in.setMinimum(in_min)
        self.qrs_in.setMaximum(in_max)
        self.qrs_in.setValue((in_min, in_max))
        self.ql_in_min.setText(str(in_min))
        self.ql_in_max.setText(str(in_max))
        self.qrs_in.blockSignals(False)

    @Slot()
    def _on_qpb_reset_clicked(self):
        logging.info("Resetting UI filters to startup state...")

        # Block signals temporarily to prevent massive UI cascading
        controls = [self.qrb_all, self.qrb_plot_line, self.qchk_in, self.qchk_out,
                    self.qle_description, self.qde_start, self.qde_end, self.qrs_in, self.qrs_out]

        for widget in controls:
            widget.blockSignals(True)

        # Restore states
        self.qrb_all.setChecked(True)
        self.qrb_plot_line.setChecked(True)
        self.qchk_in.setChecked(True)
        self.qchk_out.setChecked(True)

        self.qrs_out.setEnabled(True)
        self.qrs_in.setEnabled(True)

        self.qle_description.setText("")

        if self._default_start_date.isValid():
            self.qde_start.setDate(self._default_start_date)
        if self._default_end_date.isValid():
            self.qde_end.setDate(self._default_end_date)

        # Restore sliders and internal text labels
        self.qrs_out.setValue(self._default_out_range)
        self.qrs_in.setValue(self._default_in_range)
        self.ql_out_min.setText(str(self._default_out_range[0]))
        self.ql_out_max.setText(str(self._default_out_range[1]))
        self.ql_in_min.setText(str(self._default_in_range[0]))
        self.ql_in_max.setText(str(self._default_in_range[1]))

        # Resume signals
        for widget in controls:
            widget.blockSignals(False)

        # Emit standard signals manually
        self.filters_updated.emit()
        self.plots_updated.emit()

    @Slot(tuple)
    def _on_qrs_out_valueChanged(self, value):
        self.ql_out_min.setText(str(value[0]))
        self.ql_out_max.setText(str(value[1]))
        self.__timer.start()

    @Slot(tuple)
    def _on_qrs_in_valueChanged(self, value):
        self.ql_in_min.setText(str(value[0]))
        self.ql_in_max.setText(str(value[1]))
        self.__timer.start()

    @Slot(bool)
    def _on_qchk_out_toggled(self, checked):
        self.qrs_out.setEnabled(checked)
        self.filters_updated.emit()

    @Slot(bool)
    def _on_qchk_in_toggled(self, checked):
        self.qrs_in.setEnabled(checked)
        self.filters_updated.emit()

    @Slot(bool)
    def _on_bg_filter_toggled(self, checked):
        if checked:
            self.__timer.start()

    def _on_bg_plot_toggled(self, checked):
        if checked:
            self.plots_updated.emit()

    @Slot(str)
    def _on_qle_description_textChanged(self, text):
        self.__timer.start()

    @Slot(QDate)
    def _on_qde_start_dateChanged(self, date):
        self.filters_updated.emit()

    @Slot(QDate)
    def _on_qde_end_dateChanged(self, date):
        self.filters_updated.emit()


class AggrStats(QWidget, Ui_AggrStats):
    """Custom widget to handle aggregation statistics."""
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.qgb.setTitle(title)

    def update_stats(self, values: list, hide_if_empty: bool = False):
        """Calculates statistics and updates labels. Hides widget if no values."""
        if values:
            self.setVisible(True)
            self.setEnabled(True)
        else:
            if hide_if_empty:
                self.setVisible(False)
                return
            else:
                self.setEnabled(False)

        s = pd.Series(values)

        self.ql_entries.setText(f"{len(s): 6d}")
        self.ql_min.setText(f"{s.min():.0f}")
        self.ql_max.setText(f"{s.max():.0f}")
        self.ql_sum.setText(f"{s.sum():.0f}")
        self.ql_median.setText(f"{s.median():.0f}")
        self.ql_avg.setText(f"{s.mean():.0f}")

        std = s.std()
        self.ql_std.setText(f"{std:.2f}" if pd.notna(std) else "0.00")


class WebEnginePlotManager(QWidget):
    """Encapsulates all Plotly and QWebEngineView generation logic within a dedicated QWidget."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.df_plot = pd.DataFrame()

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

    def set_data(self, plot_data: list):
        """Stores the list of dicts as a DataFrame for plotting."""
        self.df_plot = pd.DataFrame(plot_data)

    def render_plot(self, line_checked: bool, candle_w_checked: bool):
        """Generates the Plotly figure based on the selected mode and sends it to the webview."""
        if not HAS_WEBENGINE or self.web_view is None:
            return

        if self.df_plot.empty:
            self.web_view.setHtml(get_html_centered_message("No data to display"))
            return

        fig = go.Figure()

        if line_checked:
            # Line graph + OLS
            df_plot_ols, m, q = compute_ols(self.df_plot)

            fig.add_trace(go.Scatter(x=df_plot_ols[COL_DATA], y=df_plot_ols[COL_RUN_TOT],
                                     mode='lines', name='Running Total',
                                     line=dict(color='#1f77b4', width=2)))

            if COL_OLS in df_plot_ols.columns and not df_plot_ols[COL_OLS].isna().all():
                fig.add_trace(go.Scatter(x=df_plot_ols[COL_DATA], y=df_plot_ols[COL_OLS],
                                         mode='lines', name=f'OLS Fit\nm = {m:.2f}',
                                         line=dict(color='#ff7f0e', width=2, dash='dash')))

            fig.update_layout(title='Running Total Over Time', xaxis_title='Date', yaxis_title=COL_RUN_TOT)

        else:
            # Candlesticks
            timeframe = 'W' if candle_w_checked else 'ME'
            df_candle = compute_candlesticks(self.df_plot, timeframe)

            if not df_candle.empty:
                fig.add_trace(go.Candlestick(x=df_candle['Date'],
                                             open=df_candle['Open'],
                                             high=df_candle['High'],
                                             low=df_candle['Low'],
                                             close=df_candle['Close'],
                                             name=f"Candle ({timeframe})"))

            fig.update_layout(title=f'Balance Candlestick Chart ({timeframe})',
                              xaxis_title='Date',
                              yaxis_title=COL_RUN_TOT,
                              xaxis_rangeslider_visible=False)

        # We must set autosize=True for dynamic resizing
        fig.update_layout(template='plotly_dark', margin=dict(l=20, r=20, t=40, b=20), hovermode='x unified', autosize=True)

        # Enforce minor ticks at every 500 units on the Y-Axis
        fig.update_yaxes(minor=dict(dtick=500, showgrid=True))

        # Generate HTML with default 100% width/height so Plotly's native ResizeObserver remains active
        raw_html = fig.to_html(include_plotlyjs='cdn')

        # Use string replacement to inject styling directly into the <body> tag
        # This removes the white border without breaking Plotly's responsiveness
        html = raw_html.replace(
            '<body>',
            '<body style="margin: 0px; padding: 0px; background-color: #111111; overflow: hidden;">'
        )

        # Push to web engine
        self.web_view.setHtml(html)


# noinspection PyPep8Naming
class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        df = self.get_data_source()

        # Initialize dynamic widgets
        self.stats_all = AggrStats("All")
        self.stats_out = AggrStats("Out")
        self.stats_in = AggrStats("In")
        self.ft = FilterTools(df)

        # Instantiate the Plot Manager as a QWidget with MainWindow as its parent
        self.plot_manager = WebEnginePlotManager(self)

        # Insert items into corresponding layouts
        self.qvl_aggr_stats.insertWidget(0, self.stats_all)
        self.qvl_aggr_stats.insertWidget(1, self.stats_out)
        self.qvl_aggr_stats.insertWidget(2, self.stats_in)
        self.qhl_filter_tools.addWidget(self.ft)

        # Add the plot manager to tab_plots layout (for max space)
        # or keep it in qhl_plot inside the ledger tab if desired.
        # self.tab_plots.layout().addWidget(self.plot_manager)
        self.qhl_plot.addWidget(self.plot_manager)

        # Compile the investment regex pattern (Case sensitive match per requirements)
        self.__inv_pattern = re.compile(r'FONDI|PROVENTI|CEDOLE|DEPOSIT')

        # Cache column indices dynamically to avoid hardcoding
        self.__idx_data = df.columns.get_loc(COL_DATA)
        self.__idx_out = df.columns.get_loc(COL_MINUS)
        self.__idx_in = df.columns.get_loc(COL_PLUS)
        self.__idx_desc = df.columns.get_loc(COL_DESCR)
        self.__idx_inv = df.columns.get_loc(COL_INV)
        self.__idx_saldo = df.columns.get_loc(COL_RUN_TOT)

        self._populate_table(df)

        # Configure Header layout
        header = self.qtw_ledger.horizontalHeader()
        header.setSectionResizeMode(self.__idx_data, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.__idx_out, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.__idx_in, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.__idx_desc, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.__idx_inv, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.__idx_saldo, QHeaderView.ResizeMode.Fixed)

        self.qtw_ledger.setColumnWidth(self.__idx_out, 100)
        self.qtw_ledger.setColumnWidth(self.__idx_in, 100)
        self.qtw_ledger.setColumnWidth(self.__idx_saldo, 100)

        # Setup range sliders internally in FilterTools
        self.ft.setup_sliders(df)
        # Enable sorting after population
        self.qtw_ledger.setSortingEnabled(True)

        # Connect signals
        self.ft.filters_updated.connect(self._apply_filters)
        self.ft.plots_updated.connect(self._update_plot)

        # Initial render
        logging.info("Applying initial filters to qtw_ledger...")
        self._apply_filters()

    def _populate_table(self, df: pd.DataFrame):
        logging.info("Populating qtw_ledger with data...")
        # Turn off sorting during population for performance
        self.qtw_ledger.setSortingEnabled(False)
        self.qtw_ledger.setRowCount(df.shape[0])
        self.qtw_ledger.setColumnCount(df.shape[1])
        self.qtw_ledger.setHorizontalHeaderLabels([str(col) for col in df.columns])

        for row_idx, row in enumerate(df.itertuples(index=False)):
            for col_idx, value in enumerate(row):
                # The running saldo cells will be populated dynamically in _apply_filters
                if col_idx == self.__idx_saldo:
                    val_str = "0.00"
                else:
                    val_str = "" if pd.isna(value) else str(value)

                # Use numeric table items for Dare/Avere to ensure proper numeric sorting
                if col_idx in (self.__idx_out, self.__idx_in, self.__idx_saldo):
                    item = NumericTableWidgetItem(val_str)
                else:
                    item = QTableWidgetItem(val_str)

                # Set the tooltip so long text is visible on hover, and make the cell read-only
                item.setToolTip(val_str)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.qtw_ledger.setItem(row_idx, col_idx, item)

        # Turn sorting back on
        self.qtw_ledger.setSortingEnabled(True)
        logging.info(f"Successfully populated {df.shape[0]} rows and {df.shape[1]} columns.")

    @Slot()
    def _apply_filters(self):
        """Unified method to evaluate all ui filters, hide/show table rows dynamically, and tally sums."""
        out_checked = self.ft.qchk_out.isChecked()
        in_checked = self.ft.qchk_in.isChecked()
        desc_text = self.ft.qle_description.text().lower()

        start_date_str = self.ft.qde_start.date().toString("yyyy-MM-dd")
        end_date_str = self.ft.qde_end.date().toString("yyyy-MM-dd")

        show_no_bl = self.ft.qrb_bl_no.isChecked()
        show_only_bl = self.ft.qrb_bl_only.isChecked()
        show_no_inv = self.ft.qrb_inv_no.isChecked()
        show_only_inv = self.ft.qrb_inv_only.isChecked()

        out_min, out_max = self.ft.qrs_out.value()
        in_min, in_max = self.ft.qrs_in.value()

        visible_out = []
        visible_in = []
        visible_all = []

        plot_data = []
        running_saldo = 0.0

        for row_idx in range(self.qtw_ledger.rowCount()):
            date_item = self.qtw_ledger.item(row_idx, self.__idx_data)
            out_item = self.qtw_ledger.item(row_idx, self.__idx_out)
            in_item = self.qtw_ledger.item(row_idx, self.__idx_in)
            desc_item = self.qtw_ledger.item(row_idx, self.__idx_desc)
            bl_item = self.qtw_ledger.item(row_idx, self.__idx_inv)

            date_val = date_item.text() if date_item else ""
            out_val_str = out_item.text().strip() if out_item else ""
            in_val_str = in_item.text().strip() if in_item else ""

            # Keep original case for regex evaluation, lowercase for free-text search
            desc_val_original = desc_item.text() if desc_item else ""
            desc_val_lower = desc_val_original.lower()
            bl_val = int(bl_item.text().strip()) if (bl_item and bl_item.text().strip()) else 0

            is_out_row = bool(out_val_str)
            is_in_row = bool(in_val_str)
            # Determine if this row is an Investment based on the regex
            is_inv = bool(self.__inv_pattern.search(desc_val_original))

            # Filter checks
            if show_no_bl and bl_val == 1:
                self.qtw_ledger.setRowHidden(row_idx, True)
                continue
            if show_only_bl and bl_val == 0:
                self.qtw_ledger.setRowHidden(row_idx, True)
                continue

            if show_no_inv and is_inv:
                self.qtw_ledger.setRowHidden(row_idx, True)
                continue
            if show_only_inv and not is_inv:
                self.qtw_ledger.setRowHidden(row_idx, True)
                continue

            if is_out_row:
                if not out_checked:
                    self.qtw_ledger.setRowHidden(row_idx, True)
                    continue
                try:
                    if not (out_min <= float(out_val_str) <= out_max):
                        self.qtw_ledger.setRowHidden(row_idx, True)
                        continue
                except ValueError: pass

            if is_in_row:
                if not in_checked:
                    self.qtw_ledger.setRowHidden(row_idx, True)
                    continue
                try:
                    if not (in_min <= float(in_val_str) <= in_max):
                        self.qtw_ledger.setRowHidden(row_idx, True)
                        continue
                except ValueError: pass

            if desc_text and desc_text not in desc_val_lower:
                self.qtw_ledger.setRowHidden(row_idx, True)
                continue

            if date_val.strip():
                try:
                    row_date = pd.to_datetime(date_val).strftime(FMT_DT_CSV)
                    if row_date < start_date_str or row_date > end_date_str:
                        self.qtw_ledger.setRowHidden(row_idx, True)
                        continue
                except Exception:
                    pass

            # Passed all filters -> Make visible & Collect dynamic data
            self.qtw_ledger.setRowHidden(row_idx, False)

            # Recalculate dynamic Importo for running totals and plotting
            try:
                o_val = float(out_val_str)
            except ValueError:
                o_val = 0.0
            try:
                i_val = float(in_val_str)
            except ValueError:
                i_val = 0.0

            imp_val = o_val + i_val
            running_saldo += imp_val

            # Update the Table UI Running Total Column Cell
            saldo_item = self.qtw_ledger.item(row_idx, self.__idx_saldo)
            if saldo_item:
                saldo_item.setText(f"{running_saldo:.2f}")

            # Queue details for plotting
            plot_data.append({
                COL_DATA: date_val,
                COL_RUN_TOT: running_saldo
            })

            # Accumulate values for statistical widgets
            if is_out_row:
                try: visible_out.append(float(out_val_str))
                except ValueError: pass
            if is_in_row:
                try: visible_in.append(float(in_val_str))
                except ValueError: pass

            visible_all.append(imp_val)

        # Update Aggregations & Plot
        self.stats_out.update_stats(visible_out)
        self.stats_in.update_stats(visible_in)
        self.stats_all.update_stats(visible_all)

        logging.info(f"Filters applied: out checked={out_checked}, in checked={in_checked},"
                     f"out range=({out_min}, {out_max}), in range=({in_min}, {in_max}),"
                     f"Description contains='{desc_text}', Date range=({start_date_str}, {end_date_str}),"
                     f"Modes=(no_bl: {show_no_bl}, only_bl: {show_only_bl}, no_inv: {show_no_inv}, only_inv: {show_only_inv})")

        self.plot_manager.set_data(plot_data)
        self._update_plot()

    @Slot()
    def _update_plot(self):
        line_checked = self.ft.qrb_plot_line.isChecked()
        candle_w_checked = self.ft.qrb_plot_candle_w.isChecked()
        self.plot_manager.render_plot(line_checked, candle_w_checked)

    @staticmethod
    def get_data_source() -> pd.DataFrame:
        logging.info("Loading data pipeline...")
        _df_all = load_data()

        # Provide Running Total dynamically into DataFrame right from load stage, dropping Importo
        _df_all[COL_RUN_TOT] = (pd.to_numeric(_df_all[COL_PLUS], errors='coerce').fillna(0) + \
                                pd.to_numeric(_df_all[COL_MINUS], errors='coerce').fillna(0)).cumsum()

        expected_cols = [COL_DATA, COL_PLUS, COL_MINUS, COL_DESCR, COL_INV, COL_RUN_TOT]
        missing_cols = [col for col in expected_cols if col not in _df_all.columns]

        if missing_cols:
            raise RuntimeError(f"Dataframe is missing critical expected columns: {missing_cols}\n.{_df_all.columns}")

        if _df_all.empty:
            raise RuntimeError('No data files found or loaded. Please check DATA_DIR path.')

        # Strip hh:mm:ss from dates
        _df_all[COL_DATA] = pd.to_datetime(_df_all[COL_DATA], errors='coerce').dt.strftime(FMT_DT_CSV)
        return _df_all


def main():
    init_logging(True)
    app = QApplication(sys.argv)
    window = MainWindow()
    logging.info("Starting Piggy Bank application")
    window.showMaximized()
    logging.info("Piggy Bank application is now running")
    rv = app.exec()
    logging.critical(f"Exiting Piggy Bank application with return value: {rv}")
    sys.exit(rv)


if __name__ == "__main__":
    main()
