"""AI Viewer tab (§3): persona controls + Analyze action, then either a
single structured result (VlmResultView) or a persona-panel view
(PersonaPanelView) with a consensus summary and collapsible per-persona
sections.
"""

import os

import viewer_sim as vs
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QStackedLayout, QVBoxLayout, QWidget,
)

from app.ui import colors
from app.ui.ai_viewer_options import AiViewerOptions
from app.ui.persona_panel_view import PersonaPanelView
from app.ui.vlm_result_view import VlmResultView
from app.ui.workers import CallableThread

EMPTY_STATE_TEXT = "Run the AI viewer to see a simulated viewer's reaction."


class AiViewerTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_path = None
        self._thread = None
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
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.clicked.connect(self._start_analysis)
        action_row.addWidget(self.analyze_btn)
        self.video_label = QLabel("No video selected yet.")
        action_row.addWidget(self.video_label)
        self.status_label = QLabel("")
        action_row.addWidget(self.status_label)
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
        self.analyze_btn.setEnabled(True)
        self.video_label.setText(os.path.basename(path))
        self.status_label.setText("")
        self._stack.setCurrentWidget(self._empty_label)

    def set_ollama_status(self, available):
        self.options.set_ollama_status(available)

    def set_model_status(self, available):
        self.options.set_model_status(available)

    def set_stt_status(self, available):
        self.options.set_stt_status(available)

    # -- analysis -------------------------------------------------------------
    def _start_analysis(self):
        if not self._video_path:
            return
        self.analyze_btn.setEnabled(False)
        self.status_label.setText("Running AI viewer...")

        if self.options.use_personas:
            custom = self.options.custom_personas
            if custom:
                personas, patience_by_key = custom, {}
            else:
                personas, patience_by_key = vs.generate_persona_pool(self.options.persona_count)
            self._thread = CallableThread(
                vs.run_vlm_personas, self._video_path, personas=personas,
                sample_fps=self.options.sample_fps, patience_by_key=patience_by_key,
                retention_curve=self.existing_retention_curve,
                use_captions=True, use_speech=self.options.use_speech,
            )
            self._thread.done.connect(self._panel_done)
        else:
            self._thread = CallableThread(
                vs.run_vlm, self._video_path, persona=self.options.persona_text or None,
                sample_fps=self.options.sample_fps, retention_curve=self.existing_retention_curve,
                use_captions=True, use_speech=self.options.use_speech,
            )
            self._thread.done.connect(self._single_done)
        self._thread.failed.connect(self._analysis_failed)
        self._thread.start()

    def _single_done(self, notes):
        self.single_view.show_result(notes)
        self._stack.setCurrentWidget(self.single_view)
        if "error" in notes:
            QMessageBox.warning(self, "AI viewer", notes["error"])
        self.status_label.setText("Done.")
        self.analyze_btn.setEnabled(True)

    def _panel_done(self, persona_notes):
        summary = vs.summarize_personas(persona_notes)
        self.panel_view.show_personas(persona_notes, summary)
        self._stack.setCurrentWidget(self.panel_view)
        self.status_label.setText("Done.")
        self.analyze_btn.setEnabled(True)

    def _analysis_failed(self, exc):
        self.status_label.setText("Failed.")
        self.analyze_btn.setEnabled(True)
        QMessageBox.critical(self, "AI viewer failed", str(exc))
