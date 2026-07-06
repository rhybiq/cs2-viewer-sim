"""A simple collapsible section: a QToolButton with an arrow that toggles
the visibility of an inner content widget. Used for per-persona sections in
the AI Viewer panel view (§3.2).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    def __init__(self, title, content_widget, expanded=False, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._toggle = QToolButton()
        self._toggle.setText(title)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._toggle.clicked.connect(self._on_toggled)
        layout.addWidget(self._toggle)

        self._content = content_widget
        self._content.setVisible(expanded)
        layout.addWidget(self._content)

    def _on_toggled(self, checked):
        self._content.setVisible(checked)
        self._toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
