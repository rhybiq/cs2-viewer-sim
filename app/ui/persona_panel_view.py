"""Panel-mode rendering for the AI Viewer (§3.2): a small consensus summary
at top (watched-to-end, avg swipe, hook-reads consensus, per-moment SFX
consensus), then one collapsible section per persona with the same
structured result view (VlmResultView) inside.
"""

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from app.ui.collapsible_section import CollapsibleSection
from app.ui.vlm_result_view import VlmResultView


class PersonaPanelView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._sections_widget = QWidget()
        self._sections_layout = QVBoxLayout(self._sections_widget)
        self._sections_layout.addStretch(1)
        scroll.setWidget(self._sections_widget)
        layout.addWidget(scroll, stretch=1)

    def show_personas(self, persona_notes, persona_summary):
        # Clear existing sections (everything except the trailing stretch).
        while self._sections_layout.count() > 1:
            item = self._sections_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if "error" in persona_summary:
            self.summary_label.setText(persona_summary["error"])
        else:
            sfx_bits = [
                f"@{s['at_s']}s: {', '.join(s['names'])} ({s['total']} flagged)"
                for s in persona_summary.get("sfx_consensus") or []
            ]
            text = (
                f"{persona_summary['watched_to_end']} watched to the end -- "
                f"avg swipe ~{persona_summary['avg_swipe_second']}s -- "
                f"hook reads consensus: {persona_summary['hook_reads_consensus']}"
            )
            if sfx_bits:
                text += "\nSFX: " + "; ".join(sfx_bits)
            self.summary_label.setText(text)

        for key, notes in persona_notes.items():
            result_view = VlmResultView()
            result_view.show_result(notes)
            section = CollapsibleSection(key, result_view, expanded=False)
            self._sections_layout.insertWidget(self._sections_layout.count() - 1, section)
