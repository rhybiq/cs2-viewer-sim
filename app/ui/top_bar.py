"""Top bar: dependency status chips (Ollama/model, EasyOCR) on the left,
update-available badge right-aligned. §1.3/§1.7 of QT_REWRITE_SPEC.md.
"""

from PySide6.QtWidgets import QHBoxLayout, QWidget

from app.ui.dependency_chip import DependencyChip
from app.ui.update_banner import UpdateBadge


class TopBar(QWidget):
    def __init__(self, on_update_clicked=None, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.ollama_chip = DependencyChip("Ollama")
        self.ocr_chip = DependencyChip("EasyOCR")
        layout.addWidget(self.ollama_chip)
        layout.addWidget(self.ocr_chip)
        layout.addStretch(1)

        self.update_badge = UpdateBadge(on_click=on_update_clicked)
        layout.addWidget(self.update_badge)

    def show_update(self, tag, action_text):
        self.update_badge.show_update(tag, action_text)

    def hide_update(self):
        self.update_badge.hide_update()

    def set_update_busy(self, busy, text=None):
        self.update_badge.set_busy(busy, text)
