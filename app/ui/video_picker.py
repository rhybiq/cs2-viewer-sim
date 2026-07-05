"""Global video selector (§1.2): shared state above the tabs -- both tabs
read whichever video was picked here, rather than each having its own picker.
"""

import os

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QWidget

VIDEO_FILETYPES = "Video files (*.mp4 *.mov *.mkv *.avi *.webm);;All files (*.*)"


class VideoSelector(QWidget):
    def __init__(self, on_pick=None, parent=None):
        super().__init__(parent)
        self._on_pick = on_pick

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        choose_btn = QPushButton("Choose Video...")
        choose_btn.clicked.connect(self._choose)
        layout.addWidget(choose_btn)
        self.path_label = QLabel("No video selected yet.")
        layout.addWidget(self.path_label, stretch=1)

    def _choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a clip", "", VIDEO_FILETYPES)
        if not path:
            return
        self.path_label.setText(os.path.basename(path))
        if self._on_pick:
            self._on_pick(path)

    def set_label(self, text):
        self.path_label.setText(text)
