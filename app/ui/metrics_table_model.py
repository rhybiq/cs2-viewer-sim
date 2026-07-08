"""Custom QAbstractTableModel backing the Clip Metrics results view (§2.3) --
Metric | Value | Verdict | Note columns, no Range column (that becomes a
tooltip on Verdict per §2.4), rows sorted by severity (§2.6).
"""

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor

from app.ui import colors

SEVERITY_ORDER = {"bad": 0, "warn": 1, "good": 2}

METRIC_DISPLAY_NAMES = {
    "hook_strength": "Hook Strength",
    "pacing": "Pacing (cuts/min)",
    "flatness": "Dead Time",
    "loudness_lufs": "Loudness (LUFS)",
    "predicted_retention": "Predicted Retention",
    "flat_stretches": "Flat Stretches",
    "ai_hook_check": "AI Hook Check",
}

VERDICT_LABELS = {"good": "Good", "warn": "Warn", "bad": "Bad"}
VERDICT_COLORS = {"good": colors.GOOD, "warn": colors.WARN, "bad": colors.BAD}

COLUMNS = ["Metric", "Value", "Verdict", "Note"]


def display_name(key):
    return METRIC_DISPLAY_NAMES.get(key, key.replace("_", " ").title())


def _format_ts(seconds, use_minutes):
    if use_minutes:
        m = int(seconds // 60)
        s = seconds - m * 60
        return f"{m}:{s:04.1f}"
    return f"{seconds:.2f}"


def _format_range(start, end, use_minutes):
    return f"{_format_ts(start, use_minutes)}-{_format_ts(end, use_minutes)}"


def build_display_metrics(rep):
    """rep.metrics as plain dicts, with flat_stretches merged into the
    flatness row's own note (timestamped, actionable) instead of appearing
    as a second, separate row warning about the same dead-time issue --
    see §2.8 (the old Tkinter table always appended a synthetic
    "flat_stretches" row alongside the existing "flatness" row).
    """
    use_minutes = rep.duration_s >= 60
    metrics = [dict(m) for m in rep.metrics]
    if rep.flat_stretches:
        ranges = ", ".join(_format_range(s, e, use_minutes) for s, e in rep.flat_stretches)
        n = len(rep.flat_stretches)
        suggestion = "add a cut, zoom, or SFX" + (" at each" if n > 1 else " here")
        note = f"{n} flat stretch{'es' if n != 1 else ''} at {ranges} -- {suggestion}."
        for m in metrics:
            if m["name"] == "flatness":
                m["note"] = note
                break
    return metrics


class MetricsTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._flat_stretches = []

    def set_report(self, rep):
        self.beginResetModel()
        self._rows = sorted(
            build_display_metrics(rep), key=lambda m: SEVERITY_ORDER.get(m["verdict"], 99))
        self._flat_stretches = rep.flat_stretches or []
        self.endResetModel()

    def clear(self):
        self.beginResetModel()
        self._rows = []
        self._flat_stretches = []
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self._rows)

    def columnCount(self, parent=None):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        m = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return display_name(m["name"])
            if col == 1:
                return m["value"]
            if col == 2:
                return VERDICT_LABELS.get(m["verdict"], m["verdict"])
            if col == 3:
                return m["note"]
        if role == Qt.ToolTipRole and col == 2:
            return m.get("scale", "")
        if role == Qt.ForegroundRole and col == 2:
            return QColor(VERDICT_COLORS.get(m["verdict"], colors.TEXT))
        if role == Qt.UserRole:
            # Raw (start, end) ranges for the "Copy timestamps" context-menu
            # action -- only the flatness row carries any right now.
            return self._flat_stretches if m["name"] == "flatness" else []
        return None
