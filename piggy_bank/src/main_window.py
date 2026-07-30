import sys
import logging
import pandas as pd

from PySide6.QtCore import Slot, QDate, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QHeaderView
from piggy_bank.src.ui.main_window_rc import Ui_MainWindow
from piggy_bank.src import etica


class NumericTableWidgetItem(QTableWidgetItem):
    """Custom TableWidgetItem that sorts numerically instead of alphabetically."""
    def __lt__(self, other):
        try:
            # Parse text to float, treating empty strings as 0.0 for clean sorting
            val1 = float(self.text().strip()) if self.text().strip() else 0.0
            val2 = float(other.text().strip()) if other.text().strip() else 0.0
            return val1 < val2
        except ValueError:
            # Fallback to standard string comparison if it's not a valid float
            return super().__lt__(other)


# Inherit from QMainWindow FIRST, then the UI class
# noinspection PyPep8Naming
class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        df = self.get_data_source()
        self._populate_table(df)

        # Enlarge "Data contabile" column to fit data, fill remaining space with "Descrizione", fixed width for others.
        header = self.qtw_movimenti.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # Data contabile
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)            # out
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)            # in
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)          # Descrizione

        self.qtw_movimenti.setColumnWidth(1, 100)
        self.qtw_movimenti.setColumnWidth(2, 100)

        # Set qde_start and qde_end to the min and max dates from the data source
        if not df.empty and 'Data contabile' in df.columns:
            # Assumes 'Data contabile' is parsed as datetime or string dates formatted consistently (YYYY-MM-DD)
            dates = pd.to_datetime(df['Data contabile'], errors='coerce')
            min_date = dates.min()
            max_date = dates.max()

            if not pd.isna(min_date):
                self.qde_start.setDate(QDate(min_date.year, min_date.month, min_date.day))
            if not pd.isna(max_date):
                self.qde_end.setDate(QDate(max_date.year, max_date.month, max_date.day))

        # Setup range sliders and their labels
        self._setup_sliders(df)

        # --- Set up the debouncing timer ---
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)  # Ensures it only fires once per timeout
        self.filter_timer.setInterval(1000)    # 1000 milliseconds = 1 second
        self.filter_timer.timeout.connect(self._apply_filters)

        # --- Enable Sorting ---
        # It's important this is called *after* self._populate_table()
        self.qtw_movimenti.setSortingEnabled(True)

        # Apply initial filters
        self._apply_filters()

    def _setup_sliders(self, df: pd.DataFrame):
        """Calculates min/max from the dataframe and configures range sliders."""

        # Safely convert to numeric, dropping NaNs for min/max calculation
        # noinspection unresolved-references
        ser_out = pd.to_numeric(df['Dare'], errors='coerce').dropna() if not df.empty else pd.Series()
        # noinspection unresolved-references
        ser_in = pd.to_numeric(df['Avere'], errors='coerce').dropna() if not df.empty else pd.Series()

        # Extract bounds. QSlider only supports integers, so we cast to int (padding max by +1 for inclusivity).
        incl = 0  # Inclusive max for slider?
        d_min = int(ser_out.min()) if not ser_out.empty else 0
        d_max = int(ser_out.max()) + incl if not ser_out.empty else 1000

        a_min = int(ser_in.min()) if not ser_in.empty else 0
        a_max = int(ser_in.max()) + incl if not ser_in.empty else 1000
        logging.debug(f"Setting up sliders: out({d_min}, {d_max}), in({a_min}, {a_max})")

        # Configure out
        self.qrs_out.setMinimum(d_min)
        self.qrs_out.setMaximum(d_max)
        self.qrs_out.setValue((d_min, d_max))
        self.ql_out_min.setText(str(d_min))
        self.ql_out_max.setText(str(d_max))

        # Configure in
        self.qrs_in.setMinimum(a_min)
        self.qrs_in.setMaximum(a_max)
        self.qrs_in.setValue((a_min, a_max))
        self.ql_in_min.setText(str(a_min))
        self.ql_in_max.setText(str(a_max))

        # Connect signals
        self.qrs_out.valueChanged.connect(self.on_qrs_out_valueChanged)
        self.qrs_in.valueChanged.connect(self.on_qrs_in_valueChanged)

    def _populate_table(self, df: pd.DataFrame):
        logging.info("Populating qtw_movimenti with data...")

        # Turn off sorting during population for performance
        self.qtw_movimenti.setSortingEnabled(False)

        self.qtw_movimenti.setRowCount(df.shape[0])
        self.qtw_movimenti.setColumnCount(df.shape[1])
        self.qtw_movimenti.setHorizontalHeaderLabels([str(col) for col in df.columns])

        for row_idx, row in enumerate(df.itertuples(index=False)):
            for col_idx, value in enumerate(row):
                val_str = "" if pd.isna(value) else str(value)

                # out and in are columns 1 and 2. Use the custom numeric sorting item for them.
                if col_idx in (1, 2):
                    item = NumericTableWidgetItem(val_str)
                else:
                    item = QTableWidgetItem(val_str)

                # Make the cell read-only by removing the ItemIsEditable flag
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                self.qtw_movimenti.setItem(row_idx, col_idx, item)

        # Turn sorting back on
        self.qtw_movimenti.setSortingEnabled(True)
        logging.info(f"Successfully populated {df.shape[0]} rows and {df.shape[1]} columns.")

    def _apply_filters(self):
        """Unified method to evaluate all ui filters and hide/show table rows dynamically."""
        out_checked = self.qchk_out.isChecked()
        in_checked = self.qchk_in.isChecked()
        desc_text = self.qle_description.text().lower()

        start_date_str = self.qde_start.date().toString("yyyy-MM-dd")
        end_date_str = self.qde_end.date().toString("yyyy-MM-dd")

        # Get current ranges
        d_min, d_max = self.qrs_out.value()
        a_min, a_max = self.qrs_in.value()

        # Lists to hold visible values for aggregations
        visible_out = []
        visible_in = []
        visible_all = []

        for row_idx in range(self.qtw_movimenti.rowCount()):
            date_item = self.qtw_movimenti.item(row_idx, 0)
            out_item = self.qtw_movimenti.item(row_idx, 1)
            in_item = self.qtw_movimenti.item(row_idx, 2)
            desc_item = self.qtw_movimenti.item(row_idx, 3)

            date_val = date_item.text() if date_item else ""
            out_val_str = out_item.text().strip() if out_item else ""
            in_val_str = in_item.text().strip() if in_item else ""
            desc_val = desc_item.text().lower() if desc_item else ""

            is_out_row = bool(out_val_str)
            is_in_row = bool(in_val_str)

            # 1. out Filter
            if is_out_row:
                if not out_checked:
                    self.qtw_movimenti.setRowHidden(row_idx, True)
                    continue
                try:
                    out_val = float(out_val_str)
                    if not (d_min <= out_val <= d_max):
                        self.qtw_movimenti.setRowHidden(row_idx, True)
                        continue
                except ValueError:
                    pass  # If parsing fails, skip range filter and show it

            # 2. in Filter
            if is_in_row:
                if not in_checked:
                    self.qtw_movimenti.setRowHidden(row_idx, True)
                    continue
                try:
                    in_val = float(in_val_str)
                    if not (a_min <= in_val <= a_max):
                        self.qtw_movimenti.setRowHidden(row_idx, True)
                        continue
                except ValueError:
                    pass

            # 3. Description Filter
            if desc_text and desc_text not in desc_val:
                self.qtw_movimenti.setRowHidden(row_idx, True)
                continue

            # 4. Date Range Filter
            if date_val.strip():
                try:
                    row_date = pd.to_datetime(date_val).strftime("%Y-%m-%d")
                    if row_date < start_date_str or row_date > end_date_str:
                        self.qtw_movimenti.setRowHidden(row_idx, True)
                        continue
                except Exception:
                    pass

            # If it passes all criteria, make sure it's visible
            self.qtw_movimenti.setRowHidden(row_idx, False)

            # Accumulate values for visible rows
            if is_out_row:
                try:
                    val = float(out_val_str)
                    visible_out.append(val)
                    visible_all.append(-(-val))  # Treat out (Out) as negative for net calculations? NO
                except ValueError:
                    pass

            if is_in_row:
                try:
                    val = float(in_val_str)
                    visible_in.append(val)
                    visible_all.append(val)   # Treat in (In) as positive for net calculations
                except ValueError:
                    pass

        # --- UPDATE AGGREGATIONS ---

        # 1. OUT (out) Aggregations
        if not visible_out:
            self.qgb_aggr_out.setVisible(False)
        else:
            self.qgb_aggr_out.setVisible(True)
            s_out = pd.Series(visible_out)
            self.ql_aggr_out_entries.setText(str(len(s_out)))
            self.ql_aggr_out_min.setText(f"{s_out.min():.0f}")
            self.ql_aggr_out_max.setText(f"{s_out.max():.0f}")
            self.ql_aggr_out_sum.setText(f"{s_out.sum():.0f}")
            self.ql_aggr_out_avg.setText(f"{s_out.mean():.0f}")
            std = s_out.std()
            self.ql_aggr_out_std.setText(f"{std:.2f}" if pd.notna(std) else "0.00")

        # 2. IN (in) Aggregations
        if not visible_in:
            self.qgb_aggr_in.setVisible(False)
        else:
            self.qgb_aggr_in.setVisible(True)
            s_in = pd.Series(visible_in)
            self.ql_aggr_in_entries.setText(str(len(s_in)))
            self.ql_aggr_in_min.setText(f"{s_in.min():.0f}")
            self.ql_aggr_in_max.setText(f"{s_in.max():.0f}")
            self.ql_aggr_in_sum.setText(f"{s_in.sum():.0f}")
            self.ql_aggr_in_avg.setText(f"{s_in.mean():.0f}")
            std = s_in.std()
            self.ql_aggr_in_std.setText(f"{std:.2f}" if pd.notna(std) else "0.00")

        # 3. ALL (Net) Aggregations
        if not visible_all:
            self.qgb_aggr_all.setVisible(False)
        else:
            self.qgb_aggr_all.setVisible(True)
            s_all = pd.Series(visible_all)
            self.ql_aggr_all_entries.setText(str(len(s_all)))
            self.ql_aggr_all_min.setText(f"{s_all.min():.0f}")
            self.ql_aggr_all_max.setText(f"{s_all.max():.0f}")
            self.ql_aggr_all_sum.setText(f"{s_all.sum():.0f}")
            self.ql_aggr_all_avg.setText(f"{s_all.mean():.0f}")
            std = s_all.std()
            self.ql_aggr_all_std.setText(f"{std:.2f}" if pd.notna(std) else "0.00")

        logging.info(f"Filters applied: out checked={out_checked}, in checked={in_checked},"
                     f"out range=({d_min}, {d_max}), in range=({a_min}, {a_max}),"
                     f"Description contains='{desc_text}', Date range=({start_date_str}, {end_date_str})")

    @Slot(tuple)
    def on_qrs_out_valueChanged(self, value):
        logging.debug(f"out range slider changed to: {value}")
        self.ql_out_min.setText(str(value[0]))
        self.ql_out_max.setText(str(value[1]))
        # Start/Restart the timer instead of applying immediately
        self.filter_timer.start()

    @Slot(tuple)
    def on_qrs_in_valueChanged(self, value):
        logging.debug(f"in range slider changed to: {value}")
        self.ql_in_min.setText(str(value[0]))
        self.ql_in_max.setText(str(value[1]))
        # Start/Restart the timer instead of applying immediately
        self.filter_timer.start()

    @Slot(bool)
    def on_qchk_out_toggled(self, checked):
        logging.debug(f"out checkbox toggled: {checked}")
        self.qrs_out.setEnabled(checked)
        self._apply_filters()

    @Slot(bool)
    def on_qchk_in_toggled(self, checked):
        logging.debug(f"in checkbox toggled: {checked}")
        self.qrs_in.setEnabled(checked)
        self._apply_filters()

    @Slot(str)
    def on_qle_description_textChanged(self, text):
        logging.debug(f"Description text changed: {text}")
        # Start/Restart the timer instead of applying immediately
        self.filter_timer.start()

    @Slot(QDate)
    def on_qde_start_dateChanged(self, date):
        logging.debug(f"Start date changed to: {date.toString()}")
        self._apply_filters()

    @Slot(QDate)
    def on_qde_end_dateChanged(self, date):
        logging.debug(f"End date changed to: {date.toString()}")
        self._apply_filters()

    @staticmethod
    def get_data_source() -> pd.DataFrame:
        logging.info(f'Loading .xls files from {etica.DATA_DIR}...')
        _csv_bns, _dfs = etica.load_xls_dataframes_from_import()
        if not _dfs:
            raise RuntimeError('No data files found or loaded. Please check DATA_DIR path.')

        src_rows = sum(df.shape[0] for df in _dfs)
        logging.info(f'Total rows across {len(_dfs)} DataFrames: {src_rows}')
        for _bn, _df in zip(_csv_bns, _dfs):
            _fs, _fe = _bn.split('.')[0].split('_')[1:3]
            logging.info(f'  {_fs} - {_fe} : {_df.shape[0]} rows')

        _df_all = etica.merge_dataframes_no_duplicates(_dfs)

        # save now the merged file, since blacklisting will start edit it !!
        etica.merge_csvs(_csv_bns, _df_all, do_remove=True)

        # Strip hh:mm:ss from dates before populating the table: they're always 00:00:00, so we only need the date part.
        if not _df_all.empty and 'Data contabile' in _df_all.columns:
            # Converts the column to pure 'YYYY-MM-DD' strings, discarding time.
            # Invalid dates or empty cells are gracefully coerced to NaT/NaN.
            _df_all['Data contabile'] = pd.to_datetime(_df_all['Data contabile'],
                                                       errors='coerce').dt.strftime('%Y-%m-%d')
        return _df_all


def main():
    logging.basicConfig(level=logging.DEBUG)
    app = QApplication(sys.argv)
    window = MainWindow()
    logging.info("Starting Piggy Bank application")
    window.show()
    logging.info("Piggy Bank application is now running")
    rv = app.exec()
    logging.critical(f"Exiting Piggy Bank application with return value: {rv}")
    sys.exit(rv)


if __name__ == "__main__":
    main()
