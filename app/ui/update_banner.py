"""Badge shown in the top bar when a newer release is available, offering to
update or download it. Lives in the top bar per §1.7 (not bottom-left, like
the old Tkinter banner).
"""

from PySide6.QtWidgets import QPushButton


class UpdateBadge(QPushButton):
    def __init__(self, on_click=None, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self.clicked.connect(self._clicked)
        self.hide()

    def _clicked(self):
        if self._on_click:
            self._on_click()

    def show_update(self, tag, action_text):
        self.setText(f"{tag} available -- {action_text}")
        self.show()

    def hide_update(self):
        self.hide()

    def set_busy(self, busy, text=None):
        self.setEnabled(not busy)
        if text:
            self.setText(text)
