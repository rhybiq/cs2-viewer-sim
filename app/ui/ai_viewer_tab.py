"""AI Viewer tab -- placeholder for §1; built out fully in §3 (persona
controls, structured verdict/SFX rendering, per-persona panel sections).
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class AiViewerTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_path = None
        layout = QVBoxLayout(self)
        caption = QLabel("A simulated viewer reacts to your clip (local Ollama).")
        layout.addWidget(caption)
        layout.addStretch(1)
        self.setLayout(layout)

    def set_video_path(self, path):
        # Stub until §3 builds out the real persona controls/Analyze action.
        self._video_path = path
