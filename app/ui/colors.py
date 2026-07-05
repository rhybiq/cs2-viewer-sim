"""Framework-agnostic color tokens for the PySide6 UI -- plain hex constants,
no Qt/widget dependencies, so any module can import them without a circular
dependency on a particular widget. Carried over from the Tkinter app's
app/ui/theme.py tokens (same AA-verified light-theme values); §5 (dark QSS
theme) will retune these for a dark surface.
"""

BG = "#eef0f3"
CARD_BG = "#ffffff"
SURFACE_ALT = "#f7f8fa"
BORDER = "#8b93a0"
TEXT = "#1a1f29"
MUTED = "#5f6b7a"
ACCENT = "#3d4fd4"
ACCENT_HOVER = "#2f3fb8"
ACCENT_ACTIVE = "#28359c"
ACCENT_TEXT = "#ffffff"

GOOD = "#0f7a3a"
GOOD_BG = "#e7f7ee"
WARN = "#8a5209"
WARN_BG = "#fdf3e2"
BAD = "#c53030"
BAD_BG = "#fbeaea"


def score_colors(score):
    """(fg, bg) tint for the overall-score badge, by tier."""
    if score >= 70:
        return GOOD, GOOD_BG
    if score >= 40:
        return WARN, WARN_BG
    return BAD, BAD_BG
