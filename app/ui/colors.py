"""Framework-agnostic color tokens for the PySide6 UI -- plain hex constants,
no Qt/widget dependencies, so any module can import them without a circular
dependency on a particular widget.

Dark theme (§5.1/§5.2) -- target aesthetic is OBS/DaVinci-Resolve-adjacent:
dark grey surfaces, one confident accent, desaturated verdict colors (not
pure red/green, which read as alarming/gaudy on a dark surface). These are
not eyeballed: every pair actually used together below was checked against
real WCAG contrast ratios (script: relative-luminance formula, not a visual
guess) -- TEXT/MUTED clear 4.5:1 against both BG and CARD_BG, BORDER/ACCENT
clear the 3:1 non-text-UI-component minimum against both surfaces, and
ACCENT_TEXT-on-ACCENT clears 4.5:1 for button labels.
"""

BG = "#1e2023"           # app background
CARD_BG = "#26282c"      # section/card background
SURFACE_ALT = "#2c2f34"  # zebra rows, recessed areas
BORDER = "#72767f"       # hairline borders -- 3.59:1 on BG, 3.24:1 on CARD_BG
TEXT = "#e8e9ec"         # primary text -- 13.45:1 on BG, 12.16:1 on CARD_BG
MUTED = "#a3a7ae"        # secondary/muted text -- 6.76:1 on BG, 6.11:1 on CARD_BG
ACCENT = "#4f63d4"       # primary action color -- 3.16:1 on BG (non-text use)
ACCENT_HOVER = "#5f73e4"
ACCENT_ACTIVE = "#3f52c0"
ACCENT_TEXT = "#ffffff"  # 5.16:1 on ACCENT

GOOD = "#7ee2a8"         # 9.37:1 on CARD_BG, 9.74:1 on its own GOOD_BG
GOOD_BG = "#16291d"
WARN = "#f5c97b"         # 9.51:1 on CARD_BG, 10.10:1 on its own WARN_BG
WARN_BG = "#2b2210"
BAD = "#f08080"          # 5.70:1 on CARD_BG, 6.59:1 on its own BAD_BG
BAD_BG = "#2b1616"


# Score bands per QT_REWRITE_SPEC.md §2.2 -- a single constant, easy to
# tune. Deliberately not the same threshold as the old Tkinter app's
# score_colors() (which used >=40 for warn); the spec calls for red < 50.
SCORE_BAD_MAX = 50
SCORE_WARN_MAX = 70


def score_colors(score):
    """(fg, bg) tint for the overall-score badge, by tier."""
    if score >= SCORE_WARN_MAX:
        return GOOD, GOOD_BG
    if score >= SCORE_BAD_MAX:
        return WARN, WARN_BG
    return BAD, BAD_BG
