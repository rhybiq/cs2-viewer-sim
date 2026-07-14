"""QAbstractTableModel backing the demo_highlights results view -- Round |
Time | Category | Players | Reason columns, rows already ranked (
find_highlights_from_demo() sorts its own output; this model just displays
it). Same shape as app/ui/highlights_table_model.py (the video-based Find
Highlights tab's model) but for demo_highlights.highlights.HighlightEvent
objects, not viewer_sim.HighlightWindow -- kept separate rather than shared
since this package deliberately has no import relationship with app/.
"""

from PySide6.QtCore import QAbstractTableModel, Qt

COLUMNS = ["Round", "Time", "Category", "Players", "Reason"]


def _format_ts(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


_SORT_KEYS = {
    0: lambda e: e.round_num,
    1: lambda e: e.time_s,
    2: lambda e: e.category,
    3: lambda e: ", ".join(e.players),  # matches the displayed Players string
    4: lambda e: e.reason,
}


class DemoHighlightsTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._events = []
        self._sort_column = None
        self._sort_order = Qt.AscendingOrder

    def set_events(self, events):
        self.beginResetModel()
        self._events = events
        self._sort_events()
        self.endResetModel()

    def clear(self):
        self.beginResetModel()
        self._events = []
        self.endResetModel()

    def sort(self, column, order=Qt.AscendingOrder):
        """Called by QTableView when a header is clicked (setSortingEnabled(True)
        in main_window.py). Persisted across set_events() so re-filtering
        (player/category) doesn't silently drop the user's chosen sort order.
        """
        self.beginResetModel()
        self._sort_column = column
        self._sort_order = order
        self._sort_events()
        self.endResetModel()

    def _sort_events(self):
        if self._sort_column is None:
            return
        key = _SORT_KEYS.get(self._sort_column)
        if key is None:
            return
        self._events = sorted(self._events, key=key, reverse=self._sort_order == Qt.DescendingOrder)

    def rowCount(self, parent=None):
        return len(self._events)

    def columnCount(self, parent=None):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        e = self._events[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return e.round_num
            if col == 1:
                return _format_ts(e.time_s)
            if col == 2:
                return e.category
            if col == 3:
                return ", ".join(e.players)
            if col == 4:
                return e.reason
        if role == Qt.ToolTipRole and col == 4:
            return e.reason
        if role == Qt.UserRole:
            return e.time_s
        return None
