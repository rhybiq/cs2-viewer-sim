"""Small status chip showing whether an optional dependency (Ollama, EasyOCR)
is detected -- display-only for §1; remediation actions (pull model button,
download links) belong to whichever tab actually needs them and come later.
"""

from PySide6.QtWidgets import QLabel

from app.ui import colors


class DependencyChip(QLabel):
    def __init__(self, label, parent=None):
        super().__init__(parent)
        self._label = label
        self.set_status(False, "checking...")

    def set_status(self, ok, detail=""):
        text = f"{self._label}: {detail}" if detail else self._label
        self.setText(text)
        fg, bg = (colors.GOOD, colors.GOOD_BG) if ok else (colors.MUTED, colors.SURFACE_ALT)
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; background-color: {bg}; border-radius: 4px; "
            f"padding: 3px 8px; font-size: 9pt; }}"
        )
