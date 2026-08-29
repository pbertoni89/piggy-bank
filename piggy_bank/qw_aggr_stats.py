from PySide6.QtWidgets import QWidget

from piggy_bank.etica import *
from piggy_bank.ui.aggr_stats_rc import Ui_AggrStats


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
