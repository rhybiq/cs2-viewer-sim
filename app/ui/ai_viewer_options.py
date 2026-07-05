"""Persona controls for the AI Viewer tab (§3.1): single-persona text entry,
"use a panel instead" checkbox + viewer count, custom personas box, sample
rate, and the speech-to-text toggle (added after the original spec, for the
real transcription-first pipeline this app now uses -- see viewer_sim.py's
transcribe_clip()).
"""

import viewer_sim as vs
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget,
)


class AiViewerOptions(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ollama_available = False
        self._model_available = False
        self._stt_available = False

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.persona_edit = QLineEdit()
        self.persona_edit.setPlaceholderText(
            'e.g. "a cooking-video fan" (used unless the panel below is enabled)')
        form.addRow("Persona:", self.persona_edit)
        layout.addLayout(form)

        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("Frames per second sampled:"))
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(0.5, 4.0)
        self.fps_spin.setSingleStep(0.5)
        self.fps_spin.setValue(vs.VLM_DEFAULT_SAMPLE_FPS)
        fps_row.addWidget(self.fps_spin)
        fps_row.addWidget(QLabel(
            "(higher = more detail in the one-time clip description, slower; capped regardless of clip length)"))
        fps_row.addStretch(1)
        layout.addLayout(fps_row)

        self.stt_check = QCheckBox("Also transcribe spoken audio (needs faster-whisper)")
        self.stt_check.setEnabled(False)
        layout.addWidget(self.stt_check)

        panel_row = QHBoxLayout()
        self.panel_check = QCheckBox("Use a panel of viewer personas instead (slower, several Ollama calls)")
        self.panel_check.setEnabled(False)
        self.panel_check.toggled.connect(self._sync_enabled_state)
        panel_row.addWidget(self.panel_check)
        panel_row.addWidget(QLabel("Number of viewers:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 100)
        self.count_spin.setValue(3)
        self.count_spin.setEnabled(False)
        panel_row.addWidget(self.count_spin)
        panel_row.addStretch(1)
        layout.addLayout(panel_row)

        layout.addWidget(QLabel(
            "Custom personas (optional, one per line as name: description -- "
            "replaces the generated pool when non-empty):"))
        self.custom_personas_edit = QPlainTextEdit()
        self.custom_personas_edit.setMaximumHeight(70)
        layout.addWidget(self.custom_personas_edit)

    def _sync_enabled_state(self, panel_checked=None):
        if panel_checked is None:
            panel_checked = self.panel_check.isChecked()
        self.persona_edit.setEnabled(not panel_checked)
        ready = self._ollama_available and self._model_available
        self.count_spin.setEnabled(ready and panel_checked)

    def set_ollama_status(self, available):
        self._ollama_available = available
        if not available:
            self.panel_check.setChecked(False)
            self.panel_check.setEnabled(False)
        self._sync_enabled_state()

    def set_model_status(self, available):
        self._model_available = available
        if not self._ollama_available:
            return
        self.panel_check.setEnabled(available)
        self._sync_enabled_state()

    def set_stt_status(self, available):
        self._stt_available = available
        self.stt_check.setEnabled(available)
        if not available:
            self.stt_check.setChecked(False)

    @property
    def use_personas(self):
        return self.panel_check.isChecked()

    @property
    def persona_text(self):
        return self.persona_edit.text().strip()

    @property
    def persona_count(self):
        return self.count_spin.value()

    @property
    def sample_fps(self):
        return self.fps_spin.value()

    @property
    def use_speech(self):
        return self._stt_available and self.stt_check.isChecked()

    @property
    def custom_personas(self):
        """Parsed {name: description} dict from the multi-line box, or None if empty."""
        raw = self.custom_personas_edit.toPlainText().strip()
        if not raw:
            return None
        personas = {}
        for line in raw.splitlines():
            if ":" in line:
                name, desc = line.split(":", 1)
                name, desc = name.strip(), desc.strip()
                if name and desc:
                    personas[name] = desc
        return personas or None
