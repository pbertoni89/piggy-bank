# noinspection unresolved-references
import re
import sys
import pandas as pd
import logging
import plotly.graph_objects as go

from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QHeaderView
from piggy_bank.qw_misc import *
from piggy_bank.ui.main_window_rc import Ui_MainWindow
from piggy_bank.aggr_stats import AggrStats
from piggy_bank.filter_tools import FilterTools
from piggy_bank.etica import *


# noinspection PyPep8Naming
class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # Instantiate decoupled UI components
        self.ui_ledger = Ledger(self)
        self.ui_plots_lines = PlotsLines(self)
        self.ui_plots_stats = PlotsStats(self)

        # Add decoupled widgets to the MainWindow's tab layouts
        self.ql_ledger.addWidget(self.ui_ledger)
        self.ql_plots_lines.addWidget(self.ui_plots_lines)
        self.ql_plots_stats.addWidget(self.ui_plots_stats)

        df = self.get_data_source()

        # Initialise dynamic widgets
        self.stats_all = AggrStats("All")
        self.stats_out = AggrStats("Out")
        self.stats_in = AggrStats("In")
        self.ft = FilterTools(df)

        # Main window layouts
        self.qvl_aggr_stats.insertWidget(0, self.stats_all)
        self.qvl_aggr_stats.insertWidget(1, self.stats_out)
        self.qvl_aggr_stats.insertWidget(2, self.stats_in)

        # Ledger sub-widget layouts
        self.ui_ledger.ql_filter_tools.addWidget(self.ft)

        # Initialise Plot Managers for different layout sections
        self.plot_line = WebEnginePlotManager(self)
        self.ui_plots_lines.ql_line.addWidget(self.plot_line)

        self.plot_hist_import = WebEnginePlotManager(self)
        self.ui_plots_stats.ql_histograms_import.addWidget(self.plot_hist_import)

        self.plot_hist_time = WebEnginePlotManager(self)
        self.ui_plots_stats.ql_histograms_time.addWidget(self.plot_hist_time)

        self.plot_box_out = WebEnginePlotManager(self)
        self.ui_plots_stats.ql_box_whiskers_out.addWidget(self.plot_box_out)

        self.plot_box_in = WebEnginePlotManager(self)
        self.ui_plots_stats.ql_box_whiskers_in.addWidget(self.plot_box_in)

        self.plot_candles = WebEnginePlotManager(self)
        self.ui_plots_lines.ql_candle.addWidget(self.plot_candles)

        # Compile the investment regex pattern
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
        header = self.ui_ledger.qtw_ledger.horizontalHeader()
        header.setSectionResizeMode(self.__idx_data, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.__idx_out, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.__idx_in, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.__idx_desc, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.__idx_inv, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.__idx_saldo, QHeaderView.ResizeMode.Fixed)

        self.ui_ledger.qtw_ledger.setColumnWidth(self.__idx_out, 100)
        self.ui_ledger.qtw_ledger.setColumnWidth(self.__idx_in, 100)
        self.ui_ledger.qtw_ledger.setColumnWidth(self.__idx_saldo, 100)

        # Setup range sliders internally in FilterTools
        self.ft.setup_sliders(df)

        # Enable sorting after population
        self.ui_ledger.qtw_ledger.setSortingEnabled(True)
        # Force initial sorting by 'Data contabile' descending
        self.ui_ledger.qtw_ledger.sortItems(self.__idx_data, Qt.SortOrder.DescendingOrder)

        # Connect signals
        self.ft.filters_updated.connect(self._apply_filters)

        # Connect new ComboBox controls directly to plot update function
        self.ui_plots_stats.qcb_plots_histograms_import.currentIndexChanged.connect(lambda _: self._update_plot())
        self.ui_plots_stats.qcb_plots_histograms_time.currentIndexChanged.connect(lambda _: self._update_plot())
        self.ui_plots_lines.qcb_candles_time.currentIndexChanged.connect(lambda _: self._update_plot())

        # DataFrame to store dynamically filtered rows for plotting
        self.df_plot = pd.DataFrame()

        # Initial render
        logging.debug("Applying initial filters to qtw_ledger...")
        self._apply_filters()

    def _populate_table(self, df: pd.DataFrame):
        logging.debug("Populating qtw_ledger with data...")
        # Turn off sorting during population for performance
        self.ui_ledger.qtw_ledger.setSortingEnabled(False)
        self.ui_ledger.qtw_ledger.setRowCount(df.shape[0])
        self.ui_ledger.qtw_ledger.setColumnCount(df.shape[1])
        self.ui_ledger.qtw_ledger.setHorizontalHeaderLabels([str(col) for col in df.columns])

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
                self.ui_ledger.qtw_ledger.setItem(row_idx, col_idx, item)

        # Turn sorting back on
        self.ui_ledger.qtw_ledger.setSortingEnabled(True)
        logging.debug(f"Successfully populated {df.shape[0]} rows and {df.shape[1]} columns")

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
        visible_rows_info = []
        running_saldo = 0.0

        for row_idx in range(self.ui_ledger.qtw_ledger.rowCount()):
            date_item = self.ui_ledger.qtw_ledger.item(row_idx, self.__idx_data)
            out_item = self.ui_ledger.qtw_ledger.item(row_idx, self.__idx_out)
            in_item = self.ui_ledger.qtw_ledger.item(row_idx, self.__idx_in)
            desc_item = self.ui_ledger.qtw_ledger.item(row_idx, self.__idx_desc)
            bl_item = self.ui_ledger.qtw_ledger.item(row_idx, self.__idx_inv)

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
                self.ui_ledger.qtw_ledger.setRowHidden(row_idx, True)
                continue
            if show_only_bl and bl_val == 0:
                self.ui_ledger.qtw_ledger.setRowHidden(row_idx, True)
                continue

            if show_no_inv and is_inv:
                self.ui_ledger.qtw_ledger.setRowHidden(row_idx, True)
                continue
            if show_only_inv and not is_inv:
                self.ui_ledger.qtw_ledger.setRowHidden(row_idx, True)
                continue

            if is_out_row:
                if not out_checked:
                    self.ui_ledger.qtw_ledger.setRowHidden(row_idx, True)
                    continue
                try:
                    if not (out_min <= float(out_val_str) <= out_max):
                        self.ui_ledger.qtw_ledger.setRowHidden(row_idx, True)
                        continue
                except ValueError: pass

            if is_in_row:
                if not in_checked:
                    self.ui_ledger.qtw_ledger.setRowHidden(row_idx, True)
                    continue
                try:
                    if not (in_min <= float(in_val_str) <= in_max):
                        self.ui_ledger.qtw_ledger.setRowHidden(row_idx, True)
                        continue
                except ValueError: pass

            if desc_text and desc_text not in desc_val_lower:
                self.ui_ledger.qtw_ledger.setRowHidden(row_idx, True)
                continue

            if date_val.strip():
                try:
                    row_date = pd.to_datetime(date_val).strftime(FMT_DT_CSV)
                    if row_date < start_date_str or row_date > end_date_str:
                        self.ui_ledger.qtw_ledger.setRowHidden(row_idx, True)
                        continue
                except Exception:
                    pass

            # Passed all filters -> Make visible & Collect dynamic data
            self.ui_ledger.qtw_ledger.setRowHidden(row_idx, False)

            # Recalculate dynamic Importo for running totals and plotting
            try: o_val = float(out_val_str)
            except ValueError: o_val = 0.0

            try: i_val = float(in_val_str)
            except ValueError: i_val = 0.0

            imp_val = o_val + i_val

            # Store visible row info to compute chronological running sum safely
            visible_rows_info.append({
                'row_idx': row_idx,
                'date_val': date_val,
                'imp_val': imp_val,
                'o_val': o_val,
                'i_val': i_val
            })

            # Accumulate values for statistical widgets
            if is_out_row:
                try: visible_out.append(float(out_val_str))
                except ValueError: pass
            if is_in_row:
                try: visible_in.append(float(in_val_str))
                except ValueError: pass

            visible_all.append(imp_val)

        # Sort the passed rows chronologically to ensure accurate Running Total
        visible_rows_info.sort(key=lambda x: x['date_val'])

        for row_info in visible_rows_info:
            running_saldo += row_info['imp_val']

            # Update the Table UI Running Total Column Cell mapping back to the correct row_idx
            saldo_item = self.ui_ledger.qtw_ledger.item(row_info['row_idx'], self.__idx_saldo)
            if saldo_item:
                saldo_item.setText(f"{running_saldo:.2f}")

            plot_data.append({
                COL_DATA: row_info['date_val'],
                COL_IMP: row_info['imp_val'],
                COL_RUN_TOT: running_saldo,
                COL_MINUS: row_info['o_val'],
                COL_PLUS: row_info['i_val']
            })

        # Update statistical widgets
        self.stats_out.update_stats(visible_out)
        self.stats_in.update_stats(visible_in)
        self.stats_all.update_stats(visible_all)

        logging.info(f"Filters applied: out checked={out_checked}, in checked={in_checked},"
                     f"out range=({out_min}, {out_max}), in range=({in_min}, {in_max}),"
                     f"Description contains='{desc_text}', Date range=({start_date_str}, {end_date_str}),"
                     f"Modes=(no_bl: {show_no_bl}, only_bl: {show_only_bl}, no_inv: {show_no_inv}, only_inv: {show_only_inv})")

        self.df_plot = pd.DataFrame(plot_data)
        self._update_plot()

    @Slot()
    def _update_plot(self):
        if self.df_plot.empty:
            self.plot_line.render_figure(None)
            self.plot_hist_import.render_figure(None)
            self.plot_hist_time.render_figure(None)
            self.plot_candles.render_figure(None)
            self.plot_box_out.render_figure(None)
            self.plot_box_in.render_figure(None)
            return

        # 1. Main Line Plot
        fig_main = go.Figure()
        df_plot_ols, m, q = compute_ols(self.df_plot)

        fig_main.add_trace(go.Scatter(x=df_plot_ols[COL_DATA], y=df_plot_ols[COL_RUN_TOT],
                                      mode='lines', name='Running Total',
                                      line=dict(color='#1f77b4', width=2)))

        fig_main.add_trace(go.Scatter(x=df_plot_ols[COL_DATA], y=df_plot_ols[COL_IMP],
                                      mode='lines', name='Importo (Row)',
                                      line=dict(color='#2ca02c', width=1, dash='dot')))

        if COL_OLS in df_plot_ols.columns and not df_plot_ols[COL_OLS].isna().all():
            fig_main.add_trace(go.Scatter(x=df_plot_ols[COL_DATA], y=df_plot_ols[COL_OLS],
                                          mode='lines', name=f'OLS Fit<br>m = {m:.2f}',
                                          line=dict(color='#ff7f0e', width=2, dash='dash')))

        fig_main.update_layout(title='Running Total Over Time', xaxis_title='Date', yaxis_title=COL_RUN_TOT)
        fig_main.update_yaxes(minor=dict(dtick=500, showgrid=True))
        fig_main.update_layout(hovermode='x unified')
        self.plot_line.render_figure(fig_main)

        # 2. Import Histogram
        import_bin_size_str = self.ui_plots_stats.qcb_plots_histograms_import.currentText()
        import_bin_size = int(import_bin_size_str) if import_bin_size_str.isdigit() else 100

        fig_hist_import = go.Figure()
        fig_hist_import.add_trace(go.Histogram(
            x=self.df_plot[COL_IMP],
            xbins=dict(size=import_bin_size),
            name='Importo Freq',
            marker_color='#1f77b4'
        ))
        fig_hist_import.update_layout(title=f'Importo Frequency (Bin = {import_bin_size})', xaxis_title='Importo', yaxis_title='Count', bargap=0.1)
        self.plot_hist_import.render_figure(fig_hist_import)

        # 3. Time Histogram (Periodic/Seasonal Binning)
        time_bin_str = self.ui_plots_stats.qcb_plots_histograms_time.currentText()
        dates_dt = pd.to_datetime(self.df_plot[COL_DATA])
        fig_hist_time = go.Figure()

        if time_bin_str == "Weekly":
            # Group every transaction by 7 days: Mon - Sun
            x_data = dates_dt.dt.day_name()

            # --- SATURDAY SANITY CHECK ---
            if (x_data == 'Saturday').any():
                saturday_count = (x_data == 'Saturday').sum()
                raise ValueError(f"Found {saturday_count} transactions with a Saturday accounting date! Plot quirk suspected.")

            category_array = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            fig_hist_time.add_trace(go.Histogram(
                x=x_data, y=self.df_plot[COL_IMP], histfunc='sum',
                name='Importo Sum', marker_color='#2ca02c'
            ))
            fig_hist_time.update_xaxes(categoryorder='array', categoryarray=category_array)
            title_text = 'Importo Sum by Day of Week (Mon-Sun)'
            xaxis_title = 'Day of Week'

        elif time_bin_str == "Monthly":
            # Group every transaction by 31 days: 1 - 31
            x_data = dates_dt.dt.day
            fig_hist_time.add_trace(go.Histogram(
                x=x_data, y=self.df_plot[COL_IMP], histfunc='sum',
                name='Importo Sum', xbins=dict(start=0.5, end=31.5, size=1),
                marker_color='#2ca02c'
            ))
            fig_hist_time.update_xaxes(tickmode='linear', dtick=1)
            title_text = 'Importo Sum by Day of Month (1-31)'
            xaxis_title = 'Day of Month'

        else:
            # Group every transaction by 12 months: 1 - 12
            x_data = dates_dt.dt.month
            fig_hist_time.add_trace(go.Histogram(
                x=x_data, y=self.df_plot[COL_IMP], histfunc='sum',
                name='Importo Sum', xbins=dict(start=0.5, end=12.5, size=1),
                marker_color='#2ca02c'
            ))
            fig_hist_time.update_xaxes(tickmode='linear', dtick=1)
            title_text = 'Importo Sum by Month of Year (1-12)'
            xaxis_title = 'Month'

        fig_hist_time.update_layout(title=title_text, xaxis_title=xaxis_title, yaxis_title='Sum of Importo', bargap=0.1)
        self.plot_hist_time.render_figure(fig_hist_time)

        # 4. Candlesticks
        candle_time_str = self.ui_plots_lines.qcb_candles_time.currentText()
        if candle_time_str == "Weekly":
            timeframe = 'W'
        elif candle_time_str == "Monthly":
            timeframe = 'ME'
        else:
            timeframe = 'YE'

        fig_candle = go.Figure()
        df_candle = compute_candlesticks(self.df_plot, timeframe)
        if not df_candle.empty:
            fig_candle.add_trace(go.Candlestick(
                x=df_candle['Date'], open=df_candle['Open'],
                high=df_candle['High'], low=df_candle['Low'],
                close=df_candle['Close'], name=f"Candle ({candle_time_str})"
            ))
        fig_candle.update_layout(title=f'Balance Candlestick Chart ({candle_time_str})', xaxis_title='Date', yaxis_title=COL_RUN_TOT, xaxis_rangeslider_visible=False, hovermode='x unified')
        fig_candle.update_yaxes(minor=dict(dtick=500, showgrid=True))
        self.plot_candles.render_figure(fig_candle)

        # 5. Box and Whiskers (Dare & Avere)
        fig_box_out = go.Figure()
        expenses_series = self.df_plot[self.df_plot[COL_MINUS] != 0][COL_MINUS]
        fig_box_out.add_trace(go.Box(
            y=expenses_series,
            name='Expenses (Dare)',
            marker_color='#d62728'
        ))
        fig_box_out.update_layout(
            title='Expenses Distribution',
            yaxis_title='Amount',
            margin=dict(l=20, r=20, t=40, b=20)
        )
        self.plot_box_out.render_figure(fig_box_out)

        fig_box_in = go.Figure()
        incomes_series = self.df_plot[self.df_plot[COL_PLUS] != 0][COL_PLUS]
        fig_box_in.add_trace(go.Box(
            y=incomes_series,
            name='Incomes (Avere)',
            marker_color='#2ca02c'
        ))
        fig_box_in.update_layout(
            title='Incomes Distribution',
            yaxis_title='Amount',
            margin=dict(l=20, r=20, t=40, b=20)
        )
        self.plot_box_in.render_figure(fig_box_in)

    @staticmethod
    def get_data_source() -> pd.DataFrame:
        logging.debug("Loading data pipeline...")
        _df_all = load_data()

        # Provide Running Total dynamically into DataFrame right from load stage
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

    # 1. Set the global application icon
    icon = str((Path(__file__).parent / "ui" / "icon.png"))
    logging.debug(f"Setting application icon from: {icon}")
    app.setWindowIcon(QIcon(icon))

    window = MainWindow()
    logging.debug("Starting Piggy Bank application")
    window.showMaximized()
    logging.debug("Piggy Bank application is now running")
    rv = app.exec()
    logging.critical(f"Exiting Piggy Bank application with return value: {rv}")
    sys.exit(rv)


if __name__ == "__main__":
    main()
