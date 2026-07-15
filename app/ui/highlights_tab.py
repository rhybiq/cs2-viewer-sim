"""Find Highlights tab: scans a long raw recording (a full match, not an
already-cut clip) for candidate windows worth clipping -- action spikes,
loud moments, speech reactions, and (where EasyOCR is available) OCR-
upgraded "clutch" windows. Deliberately has its own local file picker
(app.ui.video_picker.VideoSelector, a separate instance -- not the shared
global one MainWindow owns) since a 30-60+ minute source recording is a
different kind of input than "the clip you're about to post" that the
other two tabs share state around.
"""

import os
import time

import viewer_sim as vs
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QMenu,
    QProgressBar, QPushButton, QStackedLayout, QTableView, QVBoxLayout, QWidget,
)

from app.ui import colors
from app.ui.highlights_table_model import HighlightsTableModel
from app.ui.video_picker import VideoSelector
from app.ui.workers import CallableThread

EMPTY_STATE_TEXT = "Scan a full match recording to find candidate highlight moments."


class HighlightsTab(QWidget):
    # §4: cross-tab one-job-at-a-time + QStatusBar summary, owned by MainWindow.
    analysis_started = Signal()
    analysis_finished = Signal(str)
    analysis_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_path = None
        self._thread = None
        self._busy = False
        self._cancelled = False
        self._start_time = None
        self._stt_available = False

        layout = QVBoxLayout(self)
        caption = QLabel(
            "Scan a full match VOD (30-60+ min) for candidate clippable moments: motion "
            "spikes, loud moments, speech reactions, and CS2 kill-banner sightings. A crude, "
            "honest heuristic -- not real highlight/humor detection -- meant as a starting "
            "point for editing, not a final cut list.")
        caption.setWordWrap(True)
        layout.addWidget(caption)

        self.picker = VideoSelector(on_pick=self._on_video_picked)
        layout.addWidget(self.picker)

        options_row = QHBoxLayout()
        self.speech_check = QCheckBox("Also transcribe speech to catch reaction moments (slower)")
        self.speech_check.setEnabled(False)
        self.speech_check.setToolTip("faster-whisper not detected -- optional, pip install faster-whisper")
        options_row.addWidget(self.speech_check)
        options_row.addStretch(1)
        layout.addLayout(options_row)

        action_row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setObjectName("primaryButton")
        self.scan_btn.setEnabled(False)
        self.scan_btn.clicked.connect(self._on_scan_clicked)
        action_row.addWidget(self.scan_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(140)
        self.progress.hide()
        action_row.addWidget(self.progress)
        self.stage_label = QLabel("")
        self.stage_label.setStyleSheet(f"color: {colors.MUTED};")
        self.stage_label.hide()
        action_row.addWidget(self.stage_label)
        self.elapsed_label = QLabel("")
        self.elapsed_label.setStyleSheet(f"color: {colors.MUTED};")
        self.elapsed_label.hide()
        action_row.addWidget(self.elapsed_label)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self._stack = QStackedLayout()
        self._empty_label = QLabel(EMPTY_STATE_TEXT)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {colors.MUTED};")
        self._stack.addWidget(self._empty_label)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.model = HighlightsTableModel()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self._stack.addWidget(self.table)

        stack_widget = QWidget()
        stack_widget.setLayout(self._stack)
        layout.addWidget(stack_widget, stretch=1)

    # -- external wiring (called by MainWindow) ------------------------------
    def set_stt_status(self, available):
        self._stt_available = available
        self.speech_check.setEnabled(available)
        if not available:
            self.speech_check.setChecked(False)
        self.speech_check.setToolTip(
            "" if available else "faster-whisper not detected -- optional, pip install faster-whisper")

    def set_other_tab_busy(self, busy):
        """Called by MainWindow while another tab is running -- one job at a
        time (§4.1), without disabling this whole tab.
        """
        if not busy:
            self.scan_btn.setEnabled(bool(self._video_path) and not self._busy)
        else:
            self.scan_btn.setEnabled(False)

    # -- local video selection (deliberately not the shared global one) -----
    def _on_video_picked(self, path):
        self._video_path = path
        self.scan_btn.setEnabled(not self._busy)
        self.model.clear()
        self._stack.setCurrentWidget(self._empty_label)
        self.elapsed_label.hide()

    # -- scanning -------------------------------------------------------------
    def _on_scan_clicked(self):
        if self._busy:
            # Soft cancel -- viewer_sim's scan functions have no built-in
            # cancellation (ffmpeg/OpenCV calls in flight can't be safely
            # aborted mid-call), so this lets the thread finish but discards
            # its result immediately, matching the other two tabs' pattern.
            self._cancelled = True
            self.scan_btn.setEnabled(False)
            return
        self._start_scan()

    def _start_scan(self):
        if not self._video_path:
            return
        self._busy = True
        self._cancelled = False
        self._start_time = time.monotonic()
        self.scan_btn.setText("Cancel")
        self.scan_btn.setEnabled(True)
        self.elapsed_label.hide()
        self.progress.setFormat("%p%")
        self.progress.setRange(0, 0)
        self.stage_label.setText("Scanning motion...")
        self.stage_label.show()
        self.progress.show()
        self.analysis_started.emit()

        use_speech = self._stt_available and self.speech_check.isChecked()
        self._thread = CallableThread(
            vs.find_highlights, self._video_path, use_speech=use_speech, report_progress=True)
        self._thread.stage.connect(self._on_stage)
        self._thread.progress.connect(self._on_progress)
        self._thread.done.connect(self._scan_done)
        self._thread.failed.connect(self._scan_failed)
        self._thread.start()

    def _on_stage(self, text):
        self.stage_label.setText(text)

    def _on_progress(self, done, total):
        # First progress signal means stage 2 (per-candidate OCR refinement)
        # is truly running now -- switch from the indeterminate spinner to a
        # real "N/M" count, same convention as the AI Viewer tab's panel run.
        if self.progress.maximum() == 0 and total:
            self.progress.setFormat("%v/%m candidates")
            self.progress.setRange(0, total)
            self.stage_label.hide()
        self.progress.setValue(done)

    def _reset_busy_ui(self):
        self._busy = False
        self.scan_btn.setText("Scan")
        self.scan_btn.setEnabled(bool(self._video_path))
        self.progress.hide()
        self.stage_label.hide()

    def _scan_done(self, result):
        cancelled = self._cancelled
        elapsed = time.monotonic() - self._start_time
        self._reset_busy_ui()
        if cancelled:
            self.analysis_finished.emit("Find Highlights scan cancelled.")
            return
        self.elapsed_label.setText(f"Scanned in {elapsed:.1f}s")
        self.elapsed_label.show()
        self.model.set_windows(result.windows, source_duration_s=result.source_duration_s)
        self._stack.setCurrentWidget(self.table if result.windows else self._empty_label)
        video_name = os.path.basename(self._video_path)
        self.analysis_finished.emit(
            f"Found {len(result.windows)} candidate window{'s' if len(result.windows) != 1 else ''} "
            f"in {video_name} in {elapsed:.1f}s")

    def _scan_failed(self, exc):
        cancelled = self._cancelled
        self._reset_busy_ui()
        if cancelled:
            self.analysis_finished.emit("Find Highlights scan cancelled.")
            return
        self.analysis_error.emit(f"Find Highlights scan failed: {exc}")

    # -- context menu (copy timestamps, matching Clip Metrics' convention) --
    def _show_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        menu = QMenu(self)
        copy_row_action = menu.addAction("Copy row")
        copy_ts_action = menu.addAction("Copy timestamp")
        copy_reason_action = menu.addAction("Copy reason")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        clipboard = QApplication.clipboard()
        if chosen == copy_row_action:
            values = [self.model.index(index.row(), c).data(Qt.DisplayRole)
                      for c in range(self.model.columnCount())]
            clipboard.setText("\t".join(str(v) for v in values))
        elif chosen == copy_ts_action:
            start_s, end_s = self.model.index(index.row(), 0).data(Qt.UserRole)
            clipboard.setText(f"{start_s}-{end_s}")
        elif chosen == copy_reason_action:
            reason = self.model.index(index.row(), 4).data(Qt.DisplayRole)
            clipboard.setText(str(reason))
