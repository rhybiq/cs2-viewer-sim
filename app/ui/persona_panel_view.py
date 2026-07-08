"""Panel-mode rendering for the AI Viewer (§3.2): a small consensus summary
at top (watched-to-end, avg swipe, hook-reads consensus, per-moment SFX
consensus), then a sortable summary table (one row per persona) with the
full structured result (VlmResultView) for the selected row shown below --
a table scans much better than N stacked accordions once there are more
than a couple of personas, but the free-text reason/SFX/suggestions still
need the detail pane since they don't fit a cell.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.ui import colors
from app.ui.vlm_result_view import VlmResultView

_COLUMNS = ["Persona", "Hook", "Watch to end", "HUD", "Hook text"]


class PersonaPanelView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self._persona_notes = {}

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setMaximumHeight(220)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.table)

        layout.addWidget(QLabel("Selected viewer:"))
        self.detail_view = VlmResultView()
        layout.addWidget(self.detail_view, stretch=1)

    def show_personas(self, persona_notes, persona_summary):
        self._persona_notes = persona_notes

        if "error" in persona_summary:
            self.summary_label.setText(persona_summary["error"])
        else:
            sfx_bits = [
                f"@{s['at_s']}s: {', '.join(s['names'])} ({s['total']} flagged)"
                for s in persona_summary.get("sfx_consensus") or []
            ]
            text = (
                f"{persona_summary['watched_to_end']} watched to the end -- "
                f"avg swipe ~{persona_summary['avg_swipe_second']}s -- "
                f"hook reads consensus: {persona_summary['hook_reads_consensus']}"
            )
            if sfx_bits:
                text += "\nSFX: " + "; ".join(sfx_bits)
            self.summary_label.setText(text)

        self.table.setRowCount(len(persona_notes))
        for row, (key, notes) in enumerate(persona_notes.items()):
            self._fill_row(row, key, notes)

        if persona_notes:
            self.table.selectRow(0)
        else:
            self.detail_view.show_result({})

    def _fill_row(self, row, key, notes):
        name_item = QTableWidgetItem(key)
        name_item.setData(Qt.UserRole, key)
        self.table.setItem(row, 0, name_item)

        if "error" in notes or "raw" in notes:
            for col in range(1, len(_COLUMNS)):
                self.table.setItem(row, col, QTableWidgetItem("--"))
            return

        hook_reads = bool(notes.get("hook_reads"))
        hook_item = QTableWidgetItem("PASS" if hook_reads else "FAIL")
        hook_item.setForeground(QColor(colors.GOOD if hook_reads else colors.BAD))
        self.table.setItem(row, 1, hook_item)

        watched = notes.get("swipe_second") is None
        watch_item = QTableWidgetItem("YES" if watched else "NO")
        watch_item.setForeground(QColor(colors.GOOD if watched else colors.BAD))
        self.table.setItem(row, 2, watch_item)

        hud = notes.get("onscreen_ui_readable")
        self.table.setItem(row, 3, QTableWidgetItem(str(hud) if hud is not None else "n/a"))

        self.table.setItem(row, 4, QTableWidgetItem(notes.get("hook_text", "") or ""))

    def _on_row_selected(self):
        items = self.table.selectedItems()
        if not items:
            return
        key = self.table.item(items[0].row(), 0).data(Qt.UserRole)
        self.detail_view.show_result(self._persona_notes.get(key, {}))
