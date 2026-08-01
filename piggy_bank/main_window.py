import sys
from PySide6.QtCore import Slot, QDate, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QHeaderView, QWidget

from piggy_bank.ui.main_window_rc import Ui_MainWindow
from piggy_bank.ui.aggr_stats_rc import Ui_AggrStats
from piggy_bank.etica import *

# Define the new constant for the UI
COL_INV = 'Blacklisted'

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


class AggrStats(QWidget, Ui_AggrStats):
    """Custom widget to handle aggregation statistics."""
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.qgb.setTitle(title)

    def update_stats(self, values: list):
        """Calculates statistics and updates labels. Hides widget if no values."""
        if not values:
            self.setVisible(False)
            return

        self.setVisible(True)
        s = pd.Series(values)

        self.ql_entries.setText(str(len(s)))
        self.ql_min.setText(f"{s.min():.0f}")
        self.ql_max.setText(f"{s.max():.0f}")
        self.ql_sum.setText(f"{s.sum():.0f}")
        self.ql_median.setText(f"{s.median():.0f}")
        self.ql_avg.setText(f"{s.mean():.0f}")

        std = s.std()
        self.ql_std.setText(f"{std:.2f}" if pd.notna(std) else "0.00")


# Inherit from QMainWindow FIRST, then the UI class
# noinspection PyPep8Naming
class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # Initialize dynamic aggregation widgets
        self.stats_all = AggrStats("All")
        self.stats_out = AggrStats("Out")
        self.stats_in = AggrStats("In")

        # Insert them into the layout (0, 1, 2 indices place them before the spacer)
        self.qvl_aggr_stats.insertWidget(0, self.stats_all)
        self.qvl_aggr_stats.insertWidget(1, self.stats_out)
        self.qvl_aggr_stats.insertWidget(2, self.stats_in)

        df = self.get_data_source()

        # Cache column indices dynamically to avoid hardcoding
        self.idx_data = df.columns.get_loc(COL_DATA)
        self.idx_out = df.columns.get_loc(COL_MINUS)
        self.idx_in = df.columns.get_loc(COL_PLUS)
        self.idx_desc = df.columns.get_loc(COL_DESCR)
        self.idx_inv = df.columns.get_loc(COL_INV)

        self._populate_table(df)

        # Configure Header layout using dynamic indices
        header = self.qtw_movimenti.horizontalHeader()
        header.setSectionResizeMode(self.idx_data, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.idx_out, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.idx_in, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.idx_desc, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.idx_inv, QHeaderView.ResizeMode.ResizeToContents)

        self.qtw_movimenti.setColumnWidth(self.idx_out, 100)
        self.qtw_movimenti.setColumnWidth(self.idx_in, 100)

        # Set qde_start and qde_end to the min and max dates
        if not df.empty:
            dates = pd.to_datetime(df[COL_DATA], errors='coerce')
            min_date, max_date = dates.min(), dates.max()

            if not pd.isna(min_date):
                self.qde_start.setDate(QDate(min_date.year, min_date.month, min_date.day))
            if not pd.isna(max_date):
                self.qde_end.setDate(QDate(max_date.year, max_date.month, max_date.day))

        # Setup range sliders and their labels
        self._setup_sliders(df)

        # Setup Default Filter State for Radio Buttons
        if not (self.qrb_all.isChecked() or self.qrb_inv_no.isChecked() or self.qrb_inv_only.isChecked()):
            self.qrb_all.setChecked(True)

        # --- Set up the debouncing timer ---
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)  # Ensures it only fires once per timeout
        self.filter_timer.setInterval(1000)
        self.filter_timer.timeout.connect(self._apply_filters)

        # Hook up radio button signals
        self.qrb_all.toggled.connect(self.on_qrb_toggled)
        self.qrb_inv_no.toggled.connect(self.on_qrb_toggled)
        self.qrb_inv_only.toggled.connect(self.on_qrb_toggled)

        # Enable sorting after population
        self.qtw_movimenti.setSortingEnabled(True)

        # Apply initial filters
        self._apply_filters()

    def _setup_sliders(self, df: pd.DataFrame):
        """Calculates min/max from the dataframe and configures range sliders."""

        # Safely convert to numeric, dropping NaNs for min/max calculation
        # noinspection unresolved-references
        ser_out = pd.to_numeric(df[COL_MINUS], errors='coerce').dropna()
        # noinspection unresolved-references
        ser_in = pd.to_numeric(df[COL_PLUS], errors='coerce').dropna()

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

                # Use numeric table items for Dare/Avere to ensure proper numeric sorting
                if col_idx in (self.idx_out, self.idx_in):
                    item = NumericTableWidgetItem(val_str)
                else:
                    item = QTableWidgetItem(val_str)

                # Set the tooltip so long text is visible on hover
                item.setToolTip(val_str)

                # Make the cell read-only
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.qtw_movimenti.setItem(row_idx, col_idx, item)

        # Turn sorting back on
        self.qtw_movimenti.setSortingEnabled(True)
        logging.info(f"Successfully populated {df.shape[0]} rows and {df.shape[1]} columns.")

    def _apply_filters(self):
        """Unified method to evaluate all ui filters and hide/show table rows dynamically."""
        logging.debug("Applying filters to qtw_movimenti...")
        out_checked = self.qchk_out.isChecked()
        in_checked = self.qchk_in.isChecked()
        desc_text = self.qle_description.text().lower()

        start_date_str = self.qde_start.date().toString("yyyy-MM-dd")
        end_date_str = self.qde_end.date().toString("yyyy-MM-dd")

        show_no_inv = self.qrb_inv_no.isChecked()
        show_only_inv = self.qrb_inv_only.isChecked()

        out_min, out_max = self.qrs_out.value()
        in_min, in_max = self.qrs_in.value()

        visible_out = []
        visible_in = []
        visible_all = []

        for row_idx in range(self.qtw_movimenti.rowCount()):
            date_item = self.qtw_movimenti.item(row_idx, self.idx_data)
            out_item = self.qtw_movimenti.item(row_idx, self.idx_out)
            in_item = self.qtw_movimenti.item(row_idx, self.idx_in)
            desc_item = self.qtw_movimenti.item(row_idx, self.idx_desc)
            bl_item = self.qtw_movimenti.item(row_idx, self.idx_inv)

            date_val = date_item.text() if date_item else ""
            out_val_str = out_item.text().strip() if out_item else ""
            in_val_str = in_item.text().strip() if in_item else ""
            desc_val = desc_item.text().lower() if desc_item else ""
            bl_val = int(bl_item.text().strip()) if (bl_item and bl_item.text().strip()) else 0

            is_out_row = bool(out_val_str)
            is_in_row = bool(in_val_str)

            # 0. Blacklist Filter
            if show_no_inv and bl_val == 1:
                self.qtw_movimenti.setRowHidden(row_idx, True)
                continue
            if show_only_inv and bl_val == 0:
                self.qtw_movimenti.setRowHidden(row_idx, True)
                continue

            # 1. Out Filter
            if is_out_row:
                if not out_checked:
                    self.qtw_movimenti.setRowHidden(row_idx, True)
                    continue
                try:
                    out_val = float(out_val_str)
                    if not (out_min <= out_val <= out_max):
                        self.qtw_movimenti.setRowHidden(row_idx, True)
                        continue
                except ValueError:
                    pass  # If parsing fails, skip range filter and show it

            # 2. In Filter
            if is_in_row:
                if not in_checked:
                    self.qtw_movimenti.setRowHidden(row_idx, True)
                    continue
                try:
                    in_val = float(in_val_str)
                    if not (in_min <= in_val <= in_max):
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
        self.stats_out.update_stats(visible_out)
        self.stats_in.update_stats(visible_in)
        self.stats_all.update_stats(visible_all)

        logging.info(f"Filters applied: out checked={out_checked}, {in_checked=},"
                     f"out range=({out_min}, {out_max}), in range=({in_min}, {in_max}),"
                     f"Description contains='{desc_text}', Date range=({start_date_str}, {end_date_str}),"
                     f"Blacklist mode=(no_inv: {show_no_inv}, only_inv: {show_only_inv})")

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

    @Slot(bool)
    def on_qrb_toggled(self, checked):
        if checked:
            self.filter_timer.start()

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
        logging.info("Loading data pipeline...")
        _df_all = load_data()

        # Enforce exact column requirements, raising an error directly if something is absent
        expected_cols = [COL_DATA, COL_PLUS, COL_MINUS, COL_DESCR, COL_INV]
        missing_cols = [col for col in expected_cols if col not in _df_all.columns]

        if missing_cols:
            raise RuntimeError(f"Dataframe is missing critical expected columns: {missing_cols}\n.{_df_all.columns}")

        if _df_all.empty:
            raise RuntimeError('No data files found or loaded. Please check DATA_DIR path.')

        # Strip hh:mm:ss from dates: they're always 00:00:00, so we only need the date part.
        _df_all[COL_DATA] = pd.to_datetime(_df_all[COL_DATA], errors='coerce').dt.strftime('%Y-%m-%d')

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
