"""Clip Metrics tab (§2, threading/status polish per §4): deterministic
Layer 1 metrics -- OCR toggle + Analyze/Cancel action, a severity-colored
score banner, and a QTableView of per-metric verdicts (Metric | Value |
Verdict | Note, Range as a tooltip).
"""

import time
from dataclasses import asdict

import viewer_sim as vs
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QHBoxLayout, QHeaderView, QLabel,
    QMenu, QProgressBar, QPushButton, QStackedLayout, QTableView, QVBoxLayout, QWidget,
)

from app.ui import colors
from app.ui.metrics_table_model import MetricsTableModel
from app.ui.workers import CallableThread

EMPTY_STATE_TEXT = "Run analysis to see pacing, loudness, and scene metrics."


class ClipMetricsTab(QWidget):
    report_ready = Signal(object)  # emits the finished Report so MainWindow can export it
    # §4: cross-tab one-job-at-a-time + QStatusBar summary, owned by MainWindow.
    analysis_started = Signal()
    analysis_finished = Signal(str)   # plain status-bar-ready summary text
    analysis_error = Signal(str)      # status-bar-ready error text (shown in red)
    # §6: "Get simulated viewer reaction ->" after a successful run.
    ai_viewer_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_path = None
        self._thread = None
        self._ocr_available = False
        self._ollama_available = False
        self._ollama_model_available = False
        self._busy = False
        self._cancelled = False
        self._start_time = None
        self._want_ai_hook_check = False

        layout = QVBoxLayout(self)
        caption = QLabel("Objective signals: pacing, loudness, motion, scene cuts.")
        layout.addWidget(caption)

        top_row = QHBoxLayout()
        self.ocr_check = QCheckBox("Also check text overlay quality (captions + HUD legibility)")
        self.ocr_check.setEnabled(False)
        self.ocr_check.setToolTip("EasyOCR not detected -- optional, pip install -r requirements-ocr.txt")
        top_row.addWidget(self.ocr_check)
        self.ai_hook_check = QCheckBox("Also ask AI whether the hook is actually interesting (slower, one Ollama call)")
        self.ai_hook_check.setEnabled(False)
        self.ai_hook_check.setToolTip("Ollama not detected")
        top_row.addWidget(self.ai_hook_check)
        self.analyze_btn = QPushButton("Analyze")
        self.analyze_btn.setObjectName("primaryButton")
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.clicked.connect(self._on_analyze_clicked)
        top_row.addWidget(self.analyze_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setMaximumWidth(140)
        self.progress.hide()
        top_row.addWidget(self.progress)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        score_row = QHBoxLayout()
        score_row.addStretch(1)
        self.score_label = QLabel("")
        self.score_label.setAlignment(Qt.AlignCenter)
        self.score_label.hide()
        score_row.addWidget(self.score_label)
        self.ai_viewer_btn = QPushButton("Get simulated viewer reaction →")
        self.ai_viewer_btn.hide()
        self.ai_viewer_btn.clicked.connect(self.ai_viewer_requested.emit)
        score_row.addWidget(self.ai_viewer_btn)
        score_row.addStretch(1)
        layout.addLayout(score_row)

        # Stacked so the empty-state placeholder and the real table share the
        # same area -- §2.10: never bare column headers over an empty grid.
        self._stack = QStackedLayout()
        self._empty_label = QLabel(EMPTY_STATE_TEXT)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {colors.MUTED};")
        self._stack.addWidget(self._empty_label)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
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
        self.analyze_btn.setEnabled(not self._busy)
        self.model.clear()
        self._stack.setCurrentWidget(self._empty_label)
        self.score_label.hide()
        self.ai_viewer_btn.hide()

    def set_ocr_available(self, available):
        self._ocr_available = available
        self.ocr_check.setEnabled(available)
        self.ocr_check.setToolTip(
            "" if available else "EasyOCR not detected -- optional, pip install -r requirements-ocr.txt")

    def set_ollama_status(self, available):
        self._ollama_available = available
        if not available:
            self.ai_hook_check.setChecked(False)
        self._sync_ai_hook_check_enabled()

    def set_model_status(self, available):
        self._ollama_model_available = available
        self._sync_ai_hook_check_enabled()

    def _sync_ai_hook_check_enabled(self):
        ready = self._ollama_available and self._ollama_model_available
        self.ai_hook_check.setEnabled(ready)
        self.ai_hook_check.setToolTip("" if ready else "Ollama not detected or model not pulled")

    def set_other_tab_busy(self, busy):
        """Called by MainWindow while the *other* tab is running -- one job
        at a time (§4.1), enforced without disabling this whole tab (you can
        still review whatever's already loaded here).
        """
        if not busy:
            self.analyze_btn.setEnabled(bool(self._video_path) and not self._busy)
        else:
            self.analyze_btn.setEnabled(False)

    # -- analysis -------------------------------------------------------------
    def _on_analyze_clicked(self):
        if self._busy:
            # Soft cancel: viewer_sim's analysis functions have no built-in
            # cancellation, so an in-flight ffmpeg/OpenCV call can't be
            # aborted safely mid-flight. This lets the thread finish but
            # discards its result and immediately frees the UI, rather than
            # pretending to kill a thread Python can't safely kill anyway.
            self._cancelled = True
            self.analyze_btn.setEnabled(False)
            return
        self._start_analysis()

    def _start_analysis(self):
        if not self._video_path:
            return
        self._busy = True
        self._cancelled = False
        self._start_time = time.monotonic()
        self.analyze_btn.setText("Cancel")
        self.analyze_btn.setEnabled(True)
        self.progress.show()
        self.analysis_started.emit()

        use_ocr = self._ocr_available and self.ocr_check.isChecked()
        self._want_ai_hook_check = (
            self._ollama_available and self._ollama_model_available and self.ai_hook_check.isChecked())
        self._thread = CallableThread(vs.to_report, self._video_path, use_ocr=use_ocr)
        self._thread.done.connect(self._analysis_done)
        self._thread.failed.connect(self._analysis_failed)
        self._thread.start()

    def _reset_busy_ui(self):
        self._busy = False
        self.analyze_btn.setText("Analyze")
        self.analyze_btn.setEnabled(bool(self._video_path))
        self.progress.hide()

    def _show_report(self, rep):
        self.model.set_report(rep)
        self._stack.setCurrentWidget(self.table)
        fg, bg = colors.score_colors(rep.overall_score)
        self.score_label.setText(f"Clip Score: {rep.overall_score:.0f}/100")
        self.score_label.setStyleSheet(
            f"font-size: 16pt; font-weight: bold; padding: 6px 18px; "
            f"color: {fg}; background-color: {bg}; border-radius: 6px;")
        self.score_label.show()
        self.ai_viewer_btn.show()

    def _finish_analysis(self, rep, extra_status=""):
        cancelled = self._cancelled
        self._reset_busy_ui()
        if cancelled:
            self.analysis_finished.emit("Clip Metrics analysis cancelled.")
            return
        elapsed = time.monotonic() - self._start_time
        self.report_ready.emit(rep)
        self.analysis_finished.emit(
            f"Analyzed {rep.file} ({rep.duration_s}s clip) in {elapsed:.1f}s{extra_status}")

    def _analysis_done(self, rep):
        if self._cancelled:
            self._reset_busy_ui()
            self.analysis_finished.emit("Clip Metrics analysis cancelled.")
            return
        self._show_report(rep)
        if self._want_ai_hook_check:
            # A second, chained background call -- deliberately not part of
            # to_report() itself, so the fast Layer 1 pass stays Ollama-free
            # by default and its overall_score is unaffected either way.
            self._thread = CallableThread(vs.check_hook_with_ai, self._video_path)
            self._thread.done.connect(lambda metric: self._ai_hook_check_done(rep, metric))
            self._thread.failed.connect(lambda exc: self._ai_hook_check_failed(rep, exc))
            self._thread.start()
            return
        self._finish_analysis(rep)

    def _ai_hook_check_done(self, rep, metric):
        if not self._cancelled:
            rep.metrics.append(asdict(metric))
            self._show_report(rep)
        self._finish_analysis(rep)

    def _ai_hook_check_failed(self, rep, exc):
        self._finish_analysis(rep, extra_status=f" -- AI hook check failed: {exc}")

    def _analysis_failed(self, exc):
        cancelled = self._cancelled
        self._reset_busy_ui()
        if cancelled:
            self.analysis_finished.emit("Clip Metrics analysis cancelled.")
            return
        self.analysis_error.emit(f"Clip Metrics failed: {exc}")

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
