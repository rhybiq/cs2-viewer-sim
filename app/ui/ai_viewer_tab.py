"""AI Viewer tab -- placeholder for §1; built out fully in §3 (persona
controls, structured verdict/SFX rendering, per-persona panel sections).
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class AiViewerTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        caption = QLabel("A simulated viewer reacts to your clip (local Ollama).")
        layout.addWidget(caption)
        layout.addStretch(1)
        self.setLayout(layout)
