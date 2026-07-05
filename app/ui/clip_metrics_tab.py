"""Clip Metrics tab -- placeholder for §1; built out fully in §2 (QTableView
results, score banner, severity sort, flat-stretch fix, etc.).
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class ClipMetricsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        caption = QLabel("Objective signals: pacing, loudness, motion, scene cuts.")
        layout.addWidget(caption)
        layout.addStretch(1)
        self.setLayout(layout)
