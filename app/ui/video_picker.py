"""Global video selector (§1.2): shared state above the tabs -- both tabs
read whichever video was picked here, rather than each having its own picker.
"""

import os

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QWidget

VIDEO_FILETYPES = "Video files (*.mp4 *.mov *.mkv *.avi *.webm);;All files (*.*)"
_LAST_DIR_KEY = "video_picker/last_dir"


class VideoSelector(QWidget):
    def __init__(self, on_pick=None, parent=None):
        super().__init__(parent)
        self._on_pick = on_pick
        # Explicit org/app names (not set globally anywhere else in the app)
        # so this doesn't depend on QCoreApplication metadata being set --
        # on Windows this lives under HKCU\Software\CS2ViewerSim\CS2ViewerSim.
        self._settings = QSettings("CS2ViewerSim", "CS2ViewerSim")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        choose_btn = QPushButton("Choose Video...")
        choose_btn.clicked.connect(self._choose)
        layout.addWidget(choose_btn)
        self.path_label = QLabel("No video selected yet.")
        layout.addWidget(self.path_label, stretch=1)

    def _choose(self):
        last_dir = self._settings.value(_LAST_DIR_KEY, "")
        path, _ = QFileDialog.getOpenFileName(self, "Choose a clip", last_dir, VIDEO_FILETYPES)
        if not path:
            return
        self._settings.setValue(_LAST_DIR_KEY, os.path.dirname(path))
        self.path_label.setText(os.path.basename(path))
        if self._on_pick:
            self._on_pick(path)

    def set_label(self, text):
        self.path_label.setText(text)
