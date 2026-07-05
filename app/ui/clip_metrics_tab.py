"""Clip Metrics tab (§2): deterministic Layer 1 metrics -- OCR toggle +
Analyze action, a severity-colored score banner, and a QTableView of
per-metric verdicts (Metric | Value | Verdict | Note, Range as a tooltip).
"""

import viewer_sim as vs
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QHBoxLayout, QHeaderView, QLabel,
    QMenu, QMessageBox, QPushButton, QStackedLayout, QTableView, QVBoxLayout, QWidget,
)

from app.ui import colors
from app.ui.metrics_table_model import MetricsTableModel
from app.ui.workers import CallableThread

EMPTY_STATE_TEXT = "Run analysis to see pacing, loudness, and scene metrics."


class ClipMetricsTab(QWidget):
    report_ready = Signal(object)  # emits the finished Report so MainWindow can export it

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_path = None
        self._thread = None
        self._ocr_available = False

        layout = QVBoxLayout(self)
        caption = QLabel("Objective signals: pacing, loudness, motion, scene cuts.")
        layout.addWidget(caption)

        top_row = QHBoxLayout()
        self.ocr_check = QCheckBox("Also check text overlay quality (captions + HUD legibility)")
        self.ocr_check.setEnabled(False)
        self.ocr_check.setToolTip("EasyOCR not detected -- optional, pip install -r requirements-ocr.txt")
        top_row.addWidget(self.ocr_check)
        self.analyze_btn = QPushButton("Analyze")
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.clicked.connect(self._start_analysis)
        top_row.addWidget(self.analyze_btn)
        self.status_label = QLabel("")
        top_row.addWidget(self.status_label)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        self.score_label = QLabel("")
        self.score_label.setAlignment(Qt.AlignCenter)
        self.score_label.hide()
        layout.addWidget(self.score_label, alignment=Qt.AlignCenter)

        # Stacked so the empty-state placeholder and the real table share the
        # same area -- §2.10: never bare column headers over an empty grid.
        self._stack = QStackedLayout()
        self._empty_label = QLabel(EMPTY_STATE_TEXT)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {colors.MUTED};")
        self._stack.addWidget(self._empty_label)

        self.table = QTableView()
        self.model = MetricsTableModel()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self._stack.addWidget(self.table)

        stack_widget = QWidget()
        stack_widget.setLayout(self._stack)
        layout.addWidget(stack_widget, stretch=1)

    # -- external wiring (called by MainWindow) ------------------------------
    def set_video_path(self, path):
        self._video_path = path
        self.analyze_btn.setEnabled(True)
        self.model.clear()
        self._stack.setCurrentWidget(self._empty_label)
        self.score_label.hide()
        self.status_label.setText("")

    def set_ocr_available(self, available):
        self._ocr_available = available
        self.ocr_check.setEnabled(available)
        self.ocr_check.setToolTip(
            "" if available else "EasyOCR not detected -- optional, pip install -r requirements-ocr.txt")

    # -- analysis -------------------------------------------------------------
    def _start_analysis(self):
        if not self._video_path:
            return
        self.analyze_btn.setEnabled(False)
        self.status_label.setText("Analyzing...")
        use_ocr = self._ocr_available and self.ocr_check.isChecked()
        self._thread = CallableThread(vs.to_report, self._video_path, use_ocr=use_ocr)
        self._thread.done.connect(self._analysis_done)
        self._thread.failed.connect(self._analysis_failed)
        self._thread.start()

    def _analysis_done(self, rep):
        self.model.set_report(rep)
        self._stack.setCurrentWidget(self.table)
        fg, bg = colors.score_colors(rep.overall_score)
        self.score_label.setText(f"Clip Score: {rep.overall_score:.0f}/100")
        self.score_label.setStyleSheet(
            f"font-size: 16pt; font-weight: bold; padding: 6px 18px; "
            f"color: {fg}; background-color: {bg}; border-radius: 6px;")
        self.score_label.show()
        self.status_label.setText("Done.")
        self.analyze_btn.setEnabled(True)
        self.report_ready.emit(rep)

    def _analysis_failed(self, exc):
        self.status_label.setText("Failed.")
        self.analyze_btn.setEnabled(True)
        QMessageBox.critical(self, "Analysis failed", str(exc))

    # -- context menu (§2.9: actionable timestamps) --------------------------
    def _show_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        menu = QMenu(self)
        copy_row_action = menu.addAction("Copy row")
        copy_note_action = menu.addAction("Copy note")
        ts_data = self.model.index(index.row(), 0).data(Qt.UserRole)
        copy_ts_action = menu.addAction("Copy timestamps") if ts_data else None
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        clipboard = QApplication.clipboard()
        if chosen == copy_row_action:
            values = [self.model.index(index.row(), c).data(Qt.DisplayRole)
                      for c in range(self.model.columnCount())]
            clipboard.setText("\t".join(str(v) for v in values))
        elif chosen == copy_note_action:
            note = self.model.index(index.row(), 3).data(Qt.DisplayRole)
            clipboard.setText(str(note))
        elif chosen == copy_ts_action:
            clipboard.setText(", ".join(f"{s}-{e}" for s, e in ts_data))
