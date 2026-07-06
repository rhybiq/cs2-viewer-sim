"""Loads app/ui/dark_theme.qss and substitutes its {PLACEHOLDER} tokens with
the actual hex values from app/ui/colors.py, so the two can never drift out
of sync -- the .qss file owns layout/selectors, colors.py owns the values.
"""

import os

from app.ui import colors

_QSS_PATH = os.path.join(os.path.dirname(__file__), "dark_theme.qss")


def load():
    with open(_QSS_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    return template.format(
        BG=colors.BG,
        CARD_BG=colors.CARD_BG,
        SURFACE_ALT=colors.SURFACE_ALT,
        BORDER=colors.BORDER,
        TEXT=colors.TEXT,
        MUTED=colors.MUTED,
        ACCENT=colors.ACCENT,
        ACCENT_HOVER=colors.ACCENT_HOVER,
        ACCENT_ACTIVE=colors.ACCENT_ACTIVE,
        ACCENT_TEXT=colors.ACCENT_TEXT,
    )
