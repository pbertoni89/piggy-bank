from typing import Optional

from PySide6.QtWidgets import QWidget

from piggy_bank.etica import *
from piggy_bank.ui.aggr_stats_rc import Ui_AggrStats


# Same green/red as the plots
COLOR_POSITIVE = '#2ca02c'
COLOR_NEGATIVE = '#d62728'


class AggrStats(QWidget, Ui_AggrStats):
    """Custom widget to handle aggregation statistics."""
    def __init__(self, title: str, coloured: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)
        self.qgb.setTitle(title)
        self.__coloured = coloured

    def __set_signed_text(self, label, value: float):
        """Sets the label text and, if coloured, paints it green when value >= 0, red when negative."""
        label.setText(f"{value:.0f}")
        if not self.__coloured or pd.isna(value):
            label.setStyleSheet("")
        else:
            label.setStyleSheet(f"color: {COLOR_POSITIVE if value >= 0 else COLOR_NEGATIVE};")

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
        self.__set_signed_text(self.ql_sum, s.sum())
        self.__set_signed_text(self.ql_median, s.median())
        self.__set_signed_text(self.ql_avg, s.mean())

        std = s.std()
        self.ql_std.setText(f"{std:.2f}" if pd.notna(std) else "0.00")
