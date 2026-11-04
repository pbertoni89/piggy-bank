from typing import Optional

from PySide6.QtWidgets import QWidget

from piggy_bank.etica import *
from piggy_bank.ui.aggr_stats_rc import Ui_AggrStats


# Same green/red as the plots
COLOR_POSITIVE = '#2ca02c'
COLOR_NEGATIVE = '#d62728'


def signed_color(value: float) -> Optional[str]:
    """Green when value >= 0, red when negative, None when undefined (NaN)."""
    if pd.isna(value):
        return None
    return COLOR_POSITIVE if value >= 0 else COLOR_NEGATIVE


class QW_AggrStats(QWidget, Ui_AggrStats):
    """Custom widget showing an etica.AggrStats."""
    def __init__(self, title: str, coloured: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setupUi(self)
        self.qgb.setTitle(title)
        self.__coloured = coloured
        self.__labels = {f: getattr(self, f'ql_{f}') for f in AggrStats.FIELDS}

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

        stats = AggrStats(values)
        for field, label in self.__labels.items():
            label.setText(f"{stats.entries: 6d}" if field == 'entries' else stats.text(field))
            colour = signed_color(getattr(stats, field)) if self.__coloured and field in AggrStats.SIGNED else None
            label.setStyleSheet(f"color: {colour};" if colour else "")
