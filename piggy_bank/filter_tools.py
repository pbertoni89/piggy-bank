from PySide6.QtCore import Signal, QDate, QTimer, Slot
from PySide6.QtWidgets import QWidget, QAbstractButton

from piggy_bank.etica import *
from piggy_bank.ui.filter_tools_rc import Ui_FilterTools


class FilterTools(QWidget, Ui_FilterTools):
    """Custom widget to handle filter tools."""

    # Custom signal emitted when filters are stable and ready to be applied
    filters_updated = Signal()

    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # Store startup default states
        self._default_start_date = QDate()
        self._default_end_date = QDate()
        self._default_out_range = (0, 1000)
        self._default_in_range = (0, 1000)

        # Radio button groups and their default (checked) button both come from the .ui
        self.__brg_defaults = {brg: brg.checkedButton() for brg in (self.brg_bl, self.brg_inv)}
        for brg, qrb_default in self.__brg_defaults.items():
            if qrb_default is None:
                raise RuntimeError(f'No radio button is checked by default in {brg.objectName()}, fix the .ui')

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
                self.qde_start.setDate(self._default_start_date)
            if not pd.isna(max_date):
                self._default_end_date = QDate(max_date.year, max_date.month, max_date.day)
                self.qde_end.setDate(self._default_end_date)

        # Hook up internal signals to internal slots
        self.qrs_out.valueChanged.connect(self._on_qrs_out_valueChanged)
        self.qrs_in.valueChanged.connect(self._on_qrs_in_valueChanged)
        self.qchk_out.toggled.connect(self._on_qchk_out_toggled)
        self.qchk_in.toggled.connect(self._on_qchk_in_toggled)
        for brg in self.__brg_defaults:
            brg.buttonToggled.connect(self._on_brg_buttonToggled)

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
        controls = [*self.__brg_defaults, self.qchk_in, self.qchk_out,
                    self.qle_description, self.qde_start, self.qde_end, self.qrs_in, self.qrs_out]

        for widget in controls:
            widget.blockSignals(True)

        # Restore states
        for qrb_default in self.__brg_defaults.values():
            qrb_default.setChecked(True)
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

    @Slot(QAbstractButton, bool)
    def _on_brg_buttonToggled(self, button, checked):
        if checked:
            self.__timer.start()

    @Slot(str)
    def _on_qle_description_textChanged(self, text):
        self.__timer.start()

    @Slot(QDate)
    def _on_qde_start_dateChanged(self, date):
        self.filters_updated.emit()

    @Slot(QDate)
    def _on_qde_end_dateChanged(self, date):
        self.filters_updated.emit()
