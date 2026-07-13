"""AI Viewer tab (§3, threading/status polish per §4): persona controls +
Analyze/Cancel action, then either a single structured result
(VlmResultView) or a persona-panel view (PersonaPanelView) with a consensus
summary and collapsible per-persona sections.
"""

import os
import time

import viewer_sim as vs
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QStackedLayout,
    QVBoxLayout, QWidget,
)

from app.ui import colors
from app.ui.ai_viewer_options import AiViewerOptions
from app.ui.persona_panel_view import PersonaPanelView
from app.ui.vlm_result_view import VlmResultView
from app.ui.workers import CallableThread

EMPTY_STATE_TEXT = "Run the AI viewer to see a simulated viewer's reaction."


class AiViewerTab(QWidget):
    # §4: cross-tab one-job-at-a-time + QStatusBar summary, owned by MainWindow.
    analysis_started = Signal()
    analysis_finished = Signal(str)
    analysis_error = Signal(str)
    # {"vlm_notes": ...} or {"persona_notes": ..., "persona_summary": ...} --
    # MainWindow attaches this to the shared Report and exports it (§1.4).
    result_ready = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_path = None
        self._thread = None
        self._busy = False
        self._cancelled = False
        self._start_time = None
        # Set by MainWindow when the Clip Metrics tab already computed a
        # retention curve for this clip, so swipe_second grounding doesn't
        # redo that motion analysis from scratch.
        self.existing_retention_curve = None

        layout = QVBoxLayout(self)
        caption = QLabel("A simulated viewer reacts to your clip (local Ollama).")
        layout.addWidget(caption)

        self.options = AiViewerOptions()
        layout.addWidget(self.options)

        action_row = QHBoxLayout()
        self.analyze_btn = QPushButton("Analyze")
        self.analyze_btn.setObjectName("primaryButton")
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.clicked.connect(self._on_analyze_clicked)
        action_row.addWidget(self.analyze_btn)
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

        self.single_view = VlmResultView()
        self._stack.addWidget(self.single_view)

        self.panel_view = PersonaPanelView()
        self._stack.addWidget(self.panel_view)

        stack_widget = QWidget()
        stack_widget.setLayout(self._stack)
        layout.addWidget(stack_widget, stretch=1)

    # -- external wiring (called by MainWindow) ------------------------------
    def set_video_path(self, path):
        self._video_path = path
        self.analyze_btn.setEnabled(not self._busy)
        self._stack.setCurrentWidget(self._empty_label)

    def set_ollama_status(self, available):
        self.options.set_ollama_status(available)

    def set_model_status(self, available):
        self.options.set_model_status(available)

    def set_stt_status(self, available):
        self.options.set_stt_status(available)

    def set_other_tab_busy(self, busy):
        """Called by MainWindow while the *other* tab is running -- one job
        at a time (§4.1), without disabling this whole tab.
        """
        if not busy:
            self.analyze_btn.setEnabled(bool(self._video_path) and not self._busy)
        else:
            self.analyze_btn.setEnabled(False)

    # -- analysis -------------------------------------------------------------
    def _on_analyze_clicked(self):
        if self._busy:
            # Soft cancel -- see the equivalent Clip Metrics comment: Ollama
            # calls in flight can't be safely aborted mid-request, so this
            # lets the thread finish but discards its result immediately.
            self._cancelled = True
            self.analyze_btn.setEnabled(False)
            return
        self._start_analysis()

    def _mode_label(self):
        if self.options.use_personas:
            return f"panel of {self.options.persona_count}"
        persona = self.options.persona_text
        return f'persona "{persona}"' if persona else "default persona"

    def _start_analysis(self):
        if not self._video_path:
            return
        self._busy = True
        self._cancelled = False
        self._start_time = time.monotonic()
        self.analyze_btn.setText("Cancel")
        self.analyze_btn.setEnabled(True)
        self.elapsed_label.hide()
        self.stage_label.hide()
        self.progress.show()
        self.analysis_started.emit()

        if self.options.use_personas:
            custom = self.options.custom_personas
            if custom:
                personas, patience_by_key = custom, {}
            else:
                personas, patience_by_key = vs.generate_persona_pool(self.options.persona_count)
            # Starts indeterminate, not the "N/100" determinate format --
            # transcript generation (frame sampling + the one-time vision
            # call) happens before the first persona call even starts, and
            # showing "0/100" for that whole stretch looks identical to "0
            # of 100 calls finished, just slow" when actually none have
            # started. _on_panel_stage/_on_panel_progress switch it over
            # once the persona loop itself is truly what's running.
            self.progress.setFormat("%p%")
            self.progress.setRange(0, 0)
            self.stage_label.setText("Generating clip transcript...")
            self.stage_label.show()
            self._thread = CallableThread(
                vs.run_vlm_personas, self._video_path, personas=personas,
                sample_fps=self.options.sample_fps, patience_by_key=patience_by_key,
                retention_curve=self.existing_retention_curve,
                use_captions=True, use_speech=self.options.use_speech,
                report_progress=True,
            )
            self._thread.stage.connect(self._on_panel_stage)
            self._thread.progress.connect(self._on_panel_progress)
            self._thread.done.connect(self._panel_done)
        else:
            self.progress.setFormat("%p%")  # Qt's own default -- irrelevant while indeterminate anyway
            self.progress.setRange(0, 0)
            self._thread = CallableThread(
                vs.run_vlm, self._video_path, persona=self.options.persona_text or None,
                sample_fps=self.options.sample_fps, retention_curve=self.existing_retention_curve,
                use_captions=True, use_speech=self.options.use_speech,
            )
            self._thread.done.connect(self._single_done)
        self._thread.failed.connect(self._analysis_failed)
        self._thread.start()

    def _on_panel_stage(self, text):
        self.stage_label.setText(text)

    def _on_panel_progress(self, done, total):
        # First progress signal means the persona loop is truly running now
        # -- switch from the indeterminate spinner to a real "N/100" count,
        # and clear the stage label since the progress bar itself now
        # carries that information.
        if self.progress.maximum() == 0:
            self.progress.setFormat("%v/%m viewers")
            self.progress.setRange(0, total)
            self.stage_label.hide()
        self.progress.setValue(done)

    def _reset_busy_ui(self):
        self._busy = False
        self.analyze_btn.setText("Analyze")
        self.analyze_btn.setEnabled(bool(self._video_path))
        self.progress.hide()
        self.stage_label.hide()

    def _show_elapsed(self, elapsed):
        self.elapsed_label.setText(f"Analyzed in {elapsed:.1f}s")
        self.elapsed_label.show()

    def _single_done(self, notes):
        cancelled = self._cancelled
        elapsed = time.monotonic() - self._start_time
        self._reset_busy_ui()
        if cancelled:
            self.analysis_finished.emit("AI Viewer analysis cancelled.")
            return
        self._show_elapsed(elapsed)
        self.single_view.show_result(notes)
        self._stack.setCurrentWidget(self.single_view)
        if "error" in notes:
            QMessageBox.warning(self, "AI viewer", notes["error"])
        self.result_ready.emit({"vlm_notes": notes})
        video_name = os.path.basename(self._video_path)
        self.analysis_finished.emit(
            f"AI Viewer analyzed {video_name} in {elapsed:.1f}s -- {self._mode_label()}")

    def _clip_duration_s(self):
        # Reuse Clip Metrics' retention curve if it already ran (its last
        # timestamp is the clip length) instead of re-probing the file.
        if self.existing_retention_curve:
            return self.existing_retention_curve[-1][0]
        try:
            return vs.probe(self._video_path)[1]
        except Exception:
            return None

    def _panel_done(self, persona_notes):
        cancelled = self._cancelled
        elapsed = time.monotonic() - self._start_time
        self._reset_busy_ui()
        if cancelled:
            self.analysis_finished.emit("AI Viewer analysis cancelled.")
            return
        self._show_elapsed(elapsed)
        summary = vs.summarize_personas(persona_notes, duration_s=self._clip_duration_s())
        self.panel_view.show_personas(persona_notes, summary)
        self._stack.setCurrentWidget(self.panel_view)
        self.result_ready.emit({"persona_notes": persona_notes, "persona_summary": summary})
        video_name = os.path.basename(self._video_path)
        self.analysis_finished.emit(
            f"AI Viewer analyzed {video_name} in {elapsed:.1f}s -- {self._mode_label()}")

    def _analysis_failed(self, exc):
        cancelled = self._cancelled
        self._reset_busy_ui()
        if cancelled:
            self.analysis_finished.emit("AI Viewer analysis cancelled.")
            return
        self.analysis_error.emit(f"AI Viewer failed: {exc}")
