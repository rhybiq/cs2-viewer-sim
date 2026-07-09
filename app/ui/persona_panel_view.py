"""Panel-mode results for the AI Viewer: everything below the Analyze button
when a persona panel was run, reorganized into four stacked zones so the eye
lands on the decision, not the data:

  1. Verdict banner  -- retention + avg swipe-away, color-coded, one status tag.
  2. Retention curve  -- the panel's real swipe timestamps bucketed into a
     (deliberately unsmoothed) step curve, see viewer_sim.build_persona_retention_curve.
  3. Panel summary  -- three stat cards + a ranked "top objections" list, with
     the full per-viewer table (every field, one row per persona, no separate
     detail pane) demoted into a collapsed "See all viewers".
  4. Suggested fixes  -- a curated hook-text + SFX card (see viewer_sim's
     _representative()/_curate_sfx()), not the raw per-persona dump.

Internal jargon (hook_reads_consensus, per-cluster SFX name lists, raw
persona JSON) lives only in the "Raw detection data" expander at the very
bottom, collapsed by default -- see viewer_sim.summarize_personas() for
where each zone's numbers come from.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.ui import colors
from app.ui.collapsible_section import CollapsibleSection
from app.ui.retention_curve_chart import RetentionCurveChart
from app.ui.vlm_result_view import NO_HOOK_TEXT_PLACEHOLDER

_COLUMNS = [
    "Persona", "Hook", "Watch to end", "HUD", "Reason", "Suggested hook text",
    "Suggested SFX", "Suggestions",
]
_NO_SFX_PLACEHOLDER = "--"
_NO_SUGGESTIONS_PLACEHOLDER = "--"

# Retention-tier thresholds match viewer_sim.analyze_retention's own
# good/warn/bad bands (>=50 / >=30 / below) -- the same "% still watching"
# concept, just sourced from the persona panel instead of motion simulation,
# so it reads consistently with the rest of the app's verdict coloring.
_TIER_GOOD_MIN = 50
_TIER_WARN_MIN = 30

_STATUS_TAG = {
    "good": "Clip is holding attention",
    "warn": "Viewers are dropping off",
    "bad": "Clip is being abandoned",
}


def _retention_tier(pct):
    if pct is None:
        return "warn"
    if pct >= _TIER_GOOD_MIN:
        return "good"
    if pct >= _TIER_WARN_MIN:
        return "warn"
    return "bad"


def _tier_colors(tier):
    return {"good": (colors.GOOD, colors.GOOD_BG),
            "warn": (colors.WARN, colors.WARN_BG),
            "bad": (colors.BAD, colors.BAD_BG)}[tier]


def _stat_card(caption):
    """A small bordered card: a big value line over a muted caption. Returns
    (card_widget, value_label) so callers can update the value in place.
    """
    card = QFrame()
    card.setFrameShape(QFrame.StyledPanel)
    card.setStyleSheet(
        f"QFrame {{ background-color: {colors.CARD_BG}; border: 1px solid {colors.BORDER}; "
        f"border-radius: 6px; }}")
    v = QVBoxLayout(card)
    value_label = QLabel("--")
    value_label.setAlignment(Qt.AlignCenter)
    value_label.setStyleSheet(f"font-size: 15pt; font-weight: bold; color: {colors.TEXT}; background: transparent;")
    v.addWidget(value_label)
    caption_label = QLabel(caption)
    caption_label.setAlignment(Qt.AlignCenter)
    caption_label.setStyleSheet(f"color: {colors.MUTED}; background: transparent;")
    v.addWidget(caption_label)
    return card, value_label


def _pct_text(pct):
    return f"{pct:.0f}%" if pct is not None else "n/a"


class PersonaPanelView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._persona_notes = {}
        outer = QVBoxLayout(self)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        outer.addWidget(self._error_label)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # The "See all viewers" table below shows every row at its full
        # height (no internal scrollbar) rather than a small scrolling box,
        # so with a large panel the whole results area can exceed the tab's
        # visible height -- this scroll area is what makes the rest of the
        # page (not just the table) reachable in that case.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self._content)
        outer.addWidget(scroll, stretch=1)

        # -- Zone 1: verdict banner ------------------------------------------
        self._banner = QFrame()
        banner_layout = QVBoxLayout(self._banner)
        self._banner_retention = QLabel("")
        self._banner_retention.setAlignment(Qt.AlignCenter)
        self._banner_retention.setStyleSheet("font-size: 22pt; font-weight: bold; background: transparent;")
        self._banner_swipe = QLabel("")
        self._banner_swipe.setAlignment(Qt.AlignCenter)
        self._banner_swipe.setStyleSheet("font-size: 11pt; background: transparent;")
        self._banner_tag = QLabel("")
        self._banner_tag.setAlignment(Qt.AlignCenter)
        self._banner_tag.setStyleSheet("font-style: italic; background: transparent;")
        banner_layout.addWidget(self._banner_retention)
        banner_layout.addWidget(self._banner_swipe)
        banner_layout.addWidget(self._banner_tag)
        content_layout.addWidget(self._banner)

        # -- Zone 2: retention curve ------------------------------------------
        self._chart = RetentionCurveChart()
        content_layout.addWidget(self._chart)

        # -- Zone 3: panel summary ---------------------------------------------
        stats_row = QHBoxLayout()
        self._swipe_card, self._swipe_value = _stat_card("Would swipe away")
        self._hook_card, self._hook_value = _stat_card("Hook lands")
        self._hud_card, self._hud_value = _stat_card("HUD readable")
        stats_row.addWidget(self._swipe_card)
        stats_row.addWidget(self._hook_card)
        stats_row.addWidget(self._hud_card)
        content_layout.addLayout(stats_row)

        content_layout.addWidget(QLabel("Top objections"))
        self._objections_label = QLabel("")
        self._objections_label.setWordWrap(True)
        content_layout.addWidget(self._objections_label)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Single-line cells (full text on hover via tooltip, see _fill_row) --
        # word-wrapping these free-text columns blew every row up to 5+ lines,
        # which times 100 rows made the table absurdly tall. Fixed-width
        # columns + a horizontal scrollbar keeps each row a constant height.
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for col in range(4):  # Persona / Hook / Watch to end / HUD -- short fixed values
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        for col in range(4, 8):  # Reason / Suggested hook text / Suggested SFX / Suggestions
            header.setSectionResizeMode(col, QHeaderView.Interactive)
        self.table.setColumnWidth(4, 200)
        self.table.setColumnWidth(5, 160)
        self.table.setColumnWidth(6, 220)
        self.table.setColumnWidth(7, 200)
        # No internal *vertical* scrollbar/height cap -- expanding shows every
        # row at its full height (see _resize_table_to_contents); the outer
        # QScrollArea set up above is what handles a table this size not
        # fitting the visible window. Horizontal scrolling, however, is
        # exactly how this table is meant to handle 8 columns of free text
        # not all fitting the tab's width at once.
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # QTableView draws its own QFrame box (sunken panel) independently of
        # any "border: none" in its stylesheet -- setFrameShape is what
        # actually turns that off, so only the outer table_card border below
        # is visible, not a second border around just the table.
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setStyleSheet("background: transparent; border: none;")

        # A visibly thicker/accented border (vs. the 1px hairline used for
        # smaller cards elsewhere) is what makes a card this tall still read
        # as one shape instead of fading into the page background.
        table_card = QFrame()
        table_card.setStyleSheet(
            f"QFrame {{ background-color: {colors.CARD_BG}; border: 2px solid {colors.BORDER}; "
            f"border-radius: 6px; }}")
        table_card_layout = QVBoxLayout(table_card)
        table_card_layout.addWidget(self.table)
        content_layout.addWidget(CollapsibleSection("See all viewers", table_card, expanded=False))

        # -- Zone 4: suggested fixes -------------------------------------------
        fixes_card = QGroupBox("Suggested fixes")
        fixes_layout = QVBoxLayout(fixes_card)

        hook_row = QHBoxLayout()
        hook_row.addWidget(QLabel("Suggested hook text:"))
        self._fix_hook_field = QLineEdit()
        self._fix_hook_field.setReadOnly(True)
        hook_row.addWidget(self._fix_hook_field, stretch=1)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self._fix_hook_field.text()))
        hook_row.addWidget(copy_btn)
        fixes_layout.addLayout(hook_row)

        fixes_layout.addWidget(QLabel("Suggested SFX:"))
        self._fix_sfx_label = QLabel("")
        self._fix_sfx_label.setWordWrap(True)
        fixes_layout.addWidget(self._fix_sfx_label)
        content_layout.addWidget(fixes_card)

        # -- Raw detection data (collapsed, debug-only) -------------------------
        self._raw_label = QLabel("")
        self._raw_label.setWordWrap(True)
        content_layout.addWidget(CollapsibleSection("Raw detection data", self._raw_label, expanded=False))

    def show_personas(self, persona_notes, persona_summary):
        self._persona_notes = persona_notes

        if "error" in persona_summary:
            self._error_label.setText(persona_summary["error"])
            self._content.setVisible(False)
            return
        self._error_label.setText("")
        self._content.setVisible(True)

        s = persona_summary
        tier = _retention_tier(s.get("watched_to_end_pct"))
        fg, bg = _tier_colors(tier)
        self._banner.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border-radius: 8px; }}")
        self._banner_retention.setStyleSheet(
            f"font-size: 22pt; font-weight: bold; color: {fg}; background: transparent;")
        self._banner_retention.setText(f"{s['watched_to_end_pct']:.0f}% watched to end")
        avg_swipe = s.get("avg_swipe_second")
        self._banner_swipe.setStyleSheet(f"font-size: 11pt; color: {fg}; background: transparent;")
        self._banner_swipe.setText(
            f"Average swipe-away time: ~{avg_swipe}s" if avg_swipe is not None else "No one swiped away")
        self._banner_tag.setStyleSheet(f"font-style: italic; color: {fg}; background: transparent;")
        self._banner_tag.setText(_STATUS_TAG[tier])

        retention_curve = s.get("retention_curve") or []
        duration_s = retention_curve[-1][0] if retention_curve else 0
        self._chart.set_data(retention_curve, avg_swipe, duration_s)

        self._swipe_value.setText(_pct_text(s.get("swipe_pct")))
        self._hook_value.setText(_pct_text(s.get("hook_pass_pct")))
        self._hud_value.setText(_pct_text(s.get("hud_readable_pct")))

        objections = s.get("top_objections") or []
        if objections:
            self._objections_label.setText(
                "\n".join(f"{o['pct']:.0f}% -- {o['text']}" for o in objections))
        else:
            self._objections_label.setText("No recurring objections.")

        hook_text = (s.get("suggested_hook_text") or "").strip()
        if hook_text:
            self._fix_hook_field.setText(hook_text)
            self._fix_hook_field.setStyleSheet("")
        else:
            self._fix_hook_field.setText(NO_HOOK_TEXT_PLACEHOLDER)
            self._fix_hook_field.setStyleSheet(f"color: {colors.MUTED}; font-style: italic;")

        suggested_sfx = s.get("suggested_sfx") or []
        if suggested_sfx:
            self._fix_sfx_label.setText("\n".join(
                f"{sfx['at_s']}s -- {sfx['sfx']} ({sfx['reason']})" if sfx.get("reason")
                else f"{sfx['at_s']}s -- {sfx['sfx']}"
                for sfx in suggested_sfx))
        else:
            self._fix_sfx_label.setText("No SFX suggestions.")

        raw_lines = [
            f"hook reads consensus: {s.get('hook_reads_consensus')} -- "
            f"watched to end: {s.get('watched_to_end')} -- "
            f"avg swipe: {avg_swipe}s",
        ]
        for cluster in s.get("sfx_consensus") or []:
            names = ", ".join(cluster["names"])
            raw_lines.append(f"@{cluster['at_s']}s: {names} ({cluster['total']} flagged)")
        self._raw_label.setText("\n".join(raw_lines))

        self.table.setRowCount(len(persona_notes))
        for row, (key, notes) in enumerate(persona_notes.items()):
            self._fill_row(row, key, notes)
        self._resize_table_to_contents()

    def _resize_table_to_contents(self):
        """Sizes the table to exactly fit all of its rows -- see the
        VerticalScrollBarPolicy/border comment in __init__: this table never
        scrolls internally, so it must be tall enough to show every row or
        the rest would just be clipped.
        """
        self.table.resizeRowsToContents()
        height = self.table.horizontalHeader().height() + 2 * self.table.frameWidth()
        for row in range(self.table.rowCount()):
            height += self.table.rowHeight(row)
        # Reserve room for the bottom horizontal scrollbar (see
        # setHorizontalScrollBarPolicy above) -- without this the last row
        # would be partly covered by it whenever the columns overflow the
        # table's width.
        height += self.table.horizontalScrollBar().sizeHint().height()
        self.table.setFixedHeight(height)

    def _fill_row(self, row, key, notes):
        name_item = QTableWidgetItem(key)
        name_item.setData(Qt.UserRole, key)
        self.table.setItem(row, 0, name_item)

        if "error" in notes or "raw" in notes:
            for col in range(1, len(_COLUMNS)):
                self.table.setItem(row, col, QTableWidgetItem("--"))
            return

        hook_reads = bool(notes.get("hook_reads"))
        hook_item = QTableWidgetItem("PASS" if hook_reads else "FAIL")
        hook_item.setForeground(QColor(colors.GOOD if hook_reads else colors.BAD))
        self.table.setItem(row, 1, hook_item)

        watched = notes.get("swipe_second") is None
        watch_item = QTableWidgetItem("YES" if watched else "NO")
        watch_item.setForeground(QColor(colors.GOOD if watched else colors.BAD))
        self.table.setItem(row, 2, watch_item)

        hud = notes.get("onscreen_ui_readable")
        self.table.setItem(row, 3, QTableWidgetItem(str(hud) if hud is not None else "n/a"))

        reason = notes.get("reason", "")
        swipe = notes.get("swipe_second")
        reason_text = (f"Swipe away at ~{swipe}s -- {reason}" if swipe is not None
                        else f"Watch to end -- {reason}") if reason else "--"
        reason_item = QTableWidgetItem(reason_text)
        reason_item.setToolTip(reason_text)
        self.table.setItem(row, 4, reason_item)

        hook_text = (notes.get("hook_text") or "").strip()
        hook_item = QTableWidgetItem(hook_text or NO_HOOK_TEXT_PLACEHOLDER)
        hook_item.setToolTip(hook_text or NO_HOOK_TEXT_PLACEHOLDER)
        if not hook_text:
            hook_item.setForeground(QColor(colors.MUTED))
        self.table.setItem(row, 5, hook_item)

        sfx = notes.get("sfx_suggestions") or []
        sfx_text = "; ".join(
            f"{s.get('at_s', '?')}s: {s.get('sfx', '')} ({s.get('moment', '')})"
            for s in sfx if isinstance(s, dict)
        ) or _NO_SFX_PLACEHOLDER
        sfx_item = QTableWidgetItem(sfx_text)
        sfx_item.setToolTip(sfx_text)
        self.table.setItem(row, 6, sfx_item)

        suggestions = notes.get("suggestions") or []
        suggestions_text = "; ".join(suggestions) or _NO_SUGGESTIONS_PLACEHOLDER
        suggestions_item = QTableWidgetItem(suggestions_text)
        suggestions_item.setToolTip(suggestions_text)
        self.table.setItem(row, 7, suggestions_item)
