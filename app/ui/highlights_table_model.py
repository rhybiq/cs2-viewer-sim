"""QAbstractTableModel backing the Find Highlights results view -- Start |
End | Tags | Confidence | Reason columns, rows already ranked by confidence
(find_highlights() sorts its own output; this model just displays it).
"""

from PySide6.QtCore import QAbstractTableModel, Qt

COLUMNS = ["Start", "End", "Tags", "Confidence", "Reason"]


def _format_ts(seconds, use_minutes):
    if use_minutes:
        m = int(seconds // 60)
        s = seconds - m * 60
        return f"{m}:{s:04.1f}"
    return f"{seconds:.1f}"


class HighlightsTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._windows = []
        self._use_minutes = False

    def set_windows(self, windows, source_duration_s=0):
        self.beginResetModel()
        self._windows = windows
        self._use_minutes = source_duration_s >= 60
        self.endResetModel()

    def clear(self):
        self.beginResetModel()
        self._windows = []
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self._windows)

    def columnCount(self, parent=None):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        w = self._windows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return _format_ts(w.start_s, self._use_minutes)
            if col == 1:
                return _format_ts(w.end_s, self._use_minutes)
            if col == 2:
                return ", ".join(w.tags)
            if col == 3:
                return f"{w.confidence:.2f}"
            if col == 4:
                return w.reason
        if role == Qt.ToolTipRole and col == 4:
            return w.reason
        if role == Qt.UserRole:
            return (w.start_s, w.end_s)
        return None
