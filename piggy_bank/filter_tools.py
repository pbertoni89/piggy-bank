from typing import Optional

from PySide6.QtCore import Signal, QDate, QTimer, Slot
from PySide6.QtWidgets import QWidget, QCheckBox, QSpacerItem, QSizePolicy

from piggy_bank.etica import *
from piggy_bank.ui.filter_tools_rc import Ui_FilterTools


class QW_FilterTools(QWidget, Ui_FilterTools):
    """Custom widget to handle filter tools."""

    CLASS_ROWS = 2  # rows of class checkboxes in qgl_classes; columns grow with the number of classes

    # Custom signal emitted when filters are stable and ready to be applied
    filters_updated = Signal()

    def __init__(self, df: pd.DataFrame, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)

        # Store startup default states
        self._default_start_date = QDate()
        self._default_end_date = QDate()
        self._default_out_range = (0.0, 1000.0)
        self._default_in_range = (0.0, 1000.0)

        # Each amount range slider and its (min, max) spin boxes, kept in sync both ways.
        # The slider holds the value the filter reads; the spin boxes mirror it and can set it.
        self.__spins = {self.qrs_out: (self.qsb_out_min, self.qsb_out_max),
                        self.qrs_in: (self.qsb_in_min, self.qsb_in_max)}

        # One checkbox per class in qsaw_classes, built by setup_classes(): {class name: checkbox}
        self.__qchk_classes = {}

        # --- Set up the debouncing timer ---
        self.__timer = QTimer(self)
        self.__timer.setSingleShot(True)  # Ensures it only fires once per timeout
        self.__timer.setInterval(1000)
        self.__timer.timeout.connect(self.filters_updated.emit)

        self.setup_dates(df)

        # Hook up internal signals to internal slots
        self.qrs_out.valueChanged.connect(self._on_qrs_out_valueChanged)
        self.qrs_in.valueChanged.connect(self._on_qrs_in_valueChanged)
        self.qsb_out_min.valueChanged.connect(self._on_qsb_out_min_valueChanged)
        self.qsb_out_max.valueChanged.connect(self._on_qsb_out_max_valueChanged)
        self.qsb_in_min.valueChanged.connect(self._on_qsb_in_min_valueChanged)
        self.qsb_in_max.valueChanged.connect(self._on_qsb_in_max_valueChanged)
        self.qchk_out.toggled.connect(self._on_qchk_out_toggled)
        self.qchk_in.toggled.connect(self._on_qchk_in_toggled)

        self.qle_description.textChanged.connect(self._on_qle_description_textChanged)
        self.qde_start.dateChanged.connect(self._on_qde_start_dateChanged)
        self.qde_end.dateChanged.connect(self._on_qde_end_dateChanged)
        self.qpb_reset.clicked.connect(self._on_qpb_reset_clicked)
        self.qpb_last_month.clicked.connect(self._on_qpb_last_month_clicked)

    def setup_classes(self, df: pd.DataFrame):
        """(Re)builds one checkbox per class of df[COL_CLASS] in qsaw_classes, labelled with its number of rows.
        They fill a grid of CLASS_ROWS rows column by column, in sorted_classes() order, and qsa_classes scrolls
        horizontally when the columns don't fit.
        New classes start checked (accepted); a class already shown keeps its checked state across reloads."""
        unchecked = set(self.excluded_classes())
        layout = self.qgl_classes
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.__qchk_classes = {}

        counts = df[COL_CLASS].value_counts()
        for cls in sorted_classes(counts.index):
            qchk = QCheckBox(f'{cls} ({counts[cls]})', self.qsaw_classes)
            qchk.setObjectName(f'qchk_class_{cls}')
            qchk.setChecked(cls not in unchecked)
            qchk.toggled.connect(self._on_qchk_class_toggled)
            idx = len(self.__qchk_classes)
            layout.addWidget(qchk, idx % self.CLASS_ROWS, idx // self.CLASS_ROWS)
            self.__qchk_classes[cls] = qchk
        # Keeps the columns packed to the left when they don't fill the area
        n_cols = -(-len(self.__qchk_classes) // self.CLASS_ROWS)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum),
                       0, n_cols, self.CLASS_ROWS, 1)
        # Never scrolls vertically: always tall enough for every row plus the horizontal scroll bar
        self.qsa_classes.setMinimumHeight(layout.sizeHint().height()
                                         + self.qsa_classes.horizontalScrollBar().sizeHint().height()
                                         + 2 * self.qsa_classes.frameWidth())

    def class_checkboxes(self) -> dict:
        """{class name: QCheckBox}, in display order."""
        return dict(self.__qchk_classes)

    def excluded_classes(self) -> set:
        """The classes whose checkbox is unchecked: their rows are filtered out."""
        return {cls for cls, qchk in self.__qchk_classes.items() if not qchk.isChecked()}

    def setup_dates(self, df: pd.DataFrame):
        """Sets qde_start and qde_end (and their reset defaults) to the min and max dates of the dataframe."""
        if df.empty:
            return
        dates = pd.to_datetime(df[COL_DATE], errors='coerce')
        min_date, max_date = dates.min(), dates.max()

        # Block signals so that reloading data doesn't trigger early filtering
        for qde in (self.qde_start, self.qde_end):
            qde.blockSignals(True)
        if not pd.isna(min_date):
            self._default_start_date = QDate(min_date.year, min_date.month, min_date.day)
            self.qde_start.setDate(self._default_start_date)
        if not pd.isna(max_date):
            self._default_end_date = QDate(max_date.year, max_date.month, max_date.day)
            self.qde_end.setDate(self._default_end_date)
        for qde in (self.qde_start, self.qde_end):
            qde.blockSignals(False)

    def setup_sliders(self, df: pd.DataFrame):
        """Sets the range sliders and their spin boxes to the exact min/max amounts of the dataframe (cents included,
        so the extreme movements pass the filter)."""
        ser_out = pd.to_numeric(df[COL_OUT], errors='coerce').dropna()
        ser_in = pd.to_numeric(df[COL_IN], errors='coerce').dropna()

        out_min = float(ser_out.min()) if not ser_out.empty else 0.0
        out_max = float(ser_out.max()) if not ser_out.empty else 1000.0

        in_min = float(ser_in.min()) if not ser_in.empty else 0.0
        in_max = float(ser_in.max()) if not ser_in.empty else 1000.0

        # Store startup defaults
        self._default_out_range = (out_min, out_max)
        self._default_in_range = (in_min, in_max)

        # Signals blocked, to prevent early filtering during setup
        for qrs, (lo, hi) in ((self.qrs_out, self._default_out_range), (self.qrs_in, self._default_in_range)):
            qrs.blockSignals(True)
            qrs.setMinimum(lo)
            qrs.setMaximum(hi)
            qrs.blockSignals(False)
            for qsb in self.__spins[qrs]:
                qsb.blockSignals(True)
                qsb.setRange(lo, hi)
                qsb.blockSignals(False)
            self.__set_range(qrs, (lo, hi))

    def __set_range(self, qrs, value: tuple):
        """Sets a range slider and its spin boxes to value, without emitting anything."""
        widgets = (qrs, *self.__spins[qrs])
        for w in widgets:
            w.blockSignals(True)
        qrs.setValue(value)
        for qsb, v in zip(self.__spins[qrs], value):
            qsb.setValue(v)
        for w in widgets:
            w.blockSignals(False)

    def __on_slider_changed(self, qrs, value: tuple):
        """The slider moved: mirror it in the spin boxes, then filter (debounced)."""
        for qsb, v in zip(self.__spins[qrs], value):
            qsb.blockSignals(True)
            qsb.setValue(v)
            qsb.blockSignals(False)
        self.__timer.start()

    def __on_spin_changed(self, qrs, side: int):
        """Spin box `side` (0 = min, 1 = max) of qrs changed: move the slider, which filters in turn.
        If min would go past max, the other spin box follows instead of crossing."""
        qsb_min, qsb_max = self.__spins[qrs]
        lo, hi = qsb_min.value(), qsb_max.value()
        if lo > hi:
            lo, hi = (lo, lo) if side == 0 else (hi, hi)
            other = qsb_max if side == 0 else qsb_min
            other.blockSignals(True)
            other.setValue(lo)
            other.blockSignals(False)
        qrs.setValue((lo, hi))  # emits valueChanged -> __on_slider_changed

    @Slot()
    def _on_qpb_reset_clicked(self):
        self.reset_filters()

    def reset_filters(self, emit: bool = True):
        """Every filter back to its startup state: all classes and directions, no text, the whole date and amount
        ranges. Emits filters_updated once, unless emit is False (the caller applies the filters itself)."""
        logging.info("Resetting UI filters to startup state...")

        # Block signals temporarily to prevent massive UI cascading
        controls = [*self.__qchk_classes.values(), self.qchk_in, self.qchk_out,
                    self.qle_description, self.qde_start, self.qde_end]

        for widget in controls:
            widget.blockSignals(True)

        # Restore states
        for qchk in self.__qchk_classes.values():
            qchk.setChecked(True)
        self.qchk_in.setChecked(True)
        self.qchk_out.setChecked(True)

        for qrs, spins in self.__spins.items():
            for w in (qrs, *spins):
                w.setEnabled(True)

        self.qle_description.setText("")

        if self._default_start_date.isValid():
            self.qde_start.setDate(self._default_start_date)
        if self._default_end_date.isValid():
            self.qde_end.setDate(self._default_end_date)

        # Restore sliders and their spin boxes
        self.__set_range(self.qrs_out, self._default_out_range)
        self.__set_range(self.qrs_in, self._default_in_range)

        # Resume signals
        for widget in controls:
            widget.blockSignals(False)

        # A pending debounced emission would filter again for nothing
        self.__timer.stop()
        if emit:
            self.filters_updated.emit()

    LAST_MONTH_DAYS = 31

    @Slot()
    def _on_qpb_last_month_clicked(self):
        """Date range from LAST_MONTH_DAYS days ago to today, then filters once."""
        today = QDate.currentDate()
        for qde, date in ((self.qde_start, today.addDays(-self.LAST_MONTH_DAYS)), (self.qde_end, today)):
            qde.blockSignals(True)
            qde.setDate(date)
            qde.blockSignals(False)
        self.filters_updated.emit()

    @Slot(tuple)
    def _on_qrs_out_valueChanged(self, value):
        self.__on_slider_changed(self.qrs_out, value)

    @Slot(tuple)
    def _on_qrs_in_valueChanged(self, value):
        self.__on_slider_changed(self.qrs_in, value)

    @Slot(float)
    def _on_qsb_out_min_valueChanged(self, _value):
        self.__on_spin_changed(self.qrs_out, 0)

    @Slot(float)
    def _on_qsb_out_max_valueChanged(self, _value):
        self.__on_spin_changed(self.qrs_out, 1)

    @Slot(float)
    def _on_qsb_in_min_valueChanged(self, _value):
        self.__on_spin_changed(self.qrs_in, 0)

    @Slot(float)
    def _on_qsb_in_max_valueChanged(self, _value):
        self.__on_spin_changed(self.qrs_in, 1)

    @Slot(bool)
    def _on_qchk_out_toggled(self, checked):
        for w in (self.qrs_out, *self.__spins[self.qrs_out]):
            w.setEnabled(checked)
        self.filters_updated.emit()

    @Slot(bool)
    def _on_qchk_in_toggled(self, checked):
        for w in (self.qrs_in, *self.__spins[self.qrs_in]):
            w.setEnabled(checked)
        self.filters_updated.emit()

    @Slot(bool)
    def _on_qchk_class_toggled(self, checked):
        # Debounced, so unchecking several classes in a row filters once
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
