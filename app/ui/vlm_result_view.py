"""Structured rendering of a single persona's VLM verdict (§3.2): verdict
badges (Hook / Watch to end), a smaller HUD-readable chip, a copyable
suggested hook text field, an SFX checklist (copy-timestamp on right-click),
and general suggestions as a paragraph.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QVBoxLayout, QWidget,
)

from app.ui import colors

NO_HOOK_TEXT_PLACEHOLDER = "No suggestion generated"


def _badge_style(ok):
    fg, bg = (colors.GOOD, colors.GOOD_BG) if ok else (colors.BAD, colors.BAD_BG)
    return (f"QLabel {{ color: {fg}; background-color: {bg}; border-radius: 4px; "
            f"padding: 3px 10px; font-weight: bold; }}")


class VlmResultView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        badges_row = QHBoxLayout()
        self.hook_badge = QLabel("")
        self.watch_badge = QLabel("")
        self.hud_chip = QLabel("")
        self.hud_chip.setStyleSheet(f"color: {colors.MUTED}; padding: 3px 8px;")
        badges_row.addWidget(self.hook_badge)
        badges_row.addWidget(self.watch_badge)
        badges_row.addWidget(self.hud_chip)
        badges_row.addStretch(1)
        layout.addLayout(badges_row)

        self.reason_label = QLabel("")
        self.reason_label.setWordWrap(True)
        layout.addWidget(self.reason_label)

        hook_text_row = QHBoxLayout()
        hook_text_row.addWidget(QLabel("Suggested hook text:"))
        self.hook_text_field = QLineEdit()
        self.hook_text_field.setReadOnly(True)
        hook_text_row.addWidget(self.hook_text_field, stretch=1)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.hook_text_field.text()))
        hook_text_row.addWidget(copy_btn)
        layout.addLayout(hook_text_row)

        layout.addWidget(QLabel("Suggested SFX:"))
        self.sfx_list = QListWidget()
        self.sfx_list.setMaximumHeight(100)
        self.sfx_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sfx_list.customContextMenuRequested.connect(self._sfx_context_menu)
        layout.addWidget(self.sfx_list)

        self.suggestions_label = QLabel("")
        self.suggestions_label.setWordWrap(True)
        layout.addWidget(self.suggestions_label)

    def show_result(self, notes):
        if "error" in notes:
            self._clear()
            self.reason_label.setText(f"Error: {notes['error']}")
            return
        if "raw" in notes:
            self._clear()
            self.reason_label.setText(f"(unparsed response) {notes['raw']}")
            return

        hook_reads = bool(notes.get("hook_reads"))
        self.hook_badge.setText(f"Hook: {'PASS' if hook_reads else 'FAIL'}")
        self.hook_badge.setStyleSheet(_badge_style(hook_reads))

        watched = notes.get("swipe_second") is None
        self.watch_badge.setText(f"Watch to end: {'YES' if watched else 'NO'}")
        self.watch_badge.setStyleSheet(_badge_style(watched))

        hud = notes.get("onscreen_ui_readable")
        self.hud_chip.setText(f"HUD readable: {hud if hud is not None else 'n/a'}")

        reason = notes.get("reason", "")
        swipe = notes.get("swipe_second")
        if swipe is not None:
            self.reason_label.setText(f"Would swipe away at ~{swipe}s -- {reason}")
        else:
            self.reason_label.setText(f"Would watch to the end -- {reason}")

        hook_text = (notes.get("hook_text") or "").strip()
        if hook_text:
            self.hook_text_field.setText(hook_text)
            self.hook_text_field.setStyleSheet("")
        else:
            self.hook_text_field.setText(NO_HOOK_TEXT_PLACEHOLDER)
            self.hook_text_field.setStyleSheet(f"color: {colors.MUTED}; font-style: italic;")

        self.sfx_list.clear()
        for s in notes.get("sfx_suggestions") or []:
            if not isinstance(s, dict):
                continue  # the model occasionally returns a bare string instead of the asked-for object
            at = s.get("at_s", "?")
            moment = s.get("moment", "")
            sfx = s.get("sfx", "")
            item = QListWidgetItem(f"♪ {at}s -- {sfx} ({moment})")
            item.setData(Qt.UserRole, at)
            self.sfx_list.addItem(item)

        suggestions = notes.get("suggestions") or []
        self.suggestions_label.setText("\n".join(f"- {s}" for s in suggestions))

    def _sfx_context_menu(self, pos):
        item = self.sfx_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        copy_ts = menu.addAction("Copy timestamp")
        chosen = menu.exec(self.sfx_list.viewport().mapToGlobal(pos))
        if chosen == copy_ts:
            QApplication.clipboard().setText(str(item.data(Qt.UserRole)))

    def _clear(self):
        self.hook_badge.setText("")
        self.hook_badge.setStyleSheet("")
        self.watch_badge.setText("")
        self.watch_badge.setStyleSheet("")
        self.hud_chip.setText("")
        self.hook_text_field.setText("")
        self.hook_text_field.setStyleSheet("")
        self.sfx_list.clear()
        self.suggestions_label.setText("")
