"""Global save controls (§1.4): Save HTML / Save JSON checkboxes + a folder
picker, shown once near the video selector rather than duplicated per tab.
Output filenames are distinct per analysis pass (<clip>_metrics.* vs
<clip>_ai_viewer.*) so running both passes doesn't overwrite each other.
"""

import os

from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.services import history, reports


class SaveControls(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder = ""  # "" = default to the video's own folder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        checks_row = QHBoxLayout()
        self.html_check = QCheckBox("Save HTML")
        self.json_check = QCheckBox("Save JSON")
        self.history_check = QCheckBox("Save to local history")
        self.history_check.setToolTip(
            "Appends this analysis to a local SQLite history "
            f"({history.DB_PATH}) -- groundwork for future before/after "
            "comparison, nothing consumes it yet.")
        checks_row.addWidget(self.html_check)
        checks_row.addWidget(self.json_check)
        checks_row.addWidget(self.history_check)
        checks_row.addStretch(1)
        layout.addLayout(checks_row)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Save to:"))
        self.folder_label = QLabel("(same folder as the video)")
        folder_row.addWidget(self.folder_label)
        choose_btn = QPushButton("Choose folder...")
        choose_btn.clicked.connect(self._choose_folder)
        folder_row.addWidget(choose_btn)
        folder_row.addStretch(1)
        layout.addLayout(folder_row)

    def _choose_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choose save folder")
        if chosen:
            self._folder = chosen
            self.folder_label.setText(chosen)

    def maybe_export(self, report, video_path, suffix):
        """suffix distinguishes the pass ("metrics" or "ai_viewer") so Clip
        Metrics and AI Viewer runs never overwrite each other's output.
        Returns the list of paths written (empty if nothing was ticked) --
        "history" (not a real path) is appended when history_check is on,
        which os.path.basename() (used by callers to display this list)
        passes through harmlessly.
        """
        if not (self.html_check.isChecked() or self.json_check.isChecked()
                 or self.history_check.isChecked()):
            return []
        out_dir = self._folder or os.path.dirname(video_path)
        base = os.path.splitext(os.path.basename(video_path))[0]
        written = []
        if self.html_check.isChecked():
            out = os.path.join(out_dir, f"{base}_{suffix}.html")
            reports.save_html(report, out)
            written.append(out)
        if self.json_check.isChecked():
            out = os.path.join(out_dir, f"{base}_{suffix}.json")
            reports.save_json(report, out)
            written.append(out)
        if self.history_check.isChecked():
            history.save(report, video_path, suffix)
            written.append("history")
        return written
