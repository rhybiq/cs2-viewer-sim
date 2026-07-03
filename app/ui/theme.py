"""Visual design system for the desktop app: tokens + ttk style configuration.

Kept in one place so every widget module pulls from the same source of truth
instead of hardcoding colors/fonts/spacing inline. Fonts are resolved against
what's actually installed at startup (apply()) rather than assumed, since
Cascadia Mono/Segoe UI Semibold aren't guaranteed on a bare Windows install.

Contrast: every text/background pair below is AA-verified (>=4.5:1 for normal
text, >=3:1 for non-text UI component borders) at the actual font sizes this
app uses (9-10pt) -- see DESIGN.md for the computed ratios.
"""

import tkinter.font as tkfont
from tkinter import ttk

# ----------------------------------------------------------------------------
# Color tokens -- cool graphite neutrals, tinted (never pure #000/#fff), one
# confident accent. Retuned from a first draft that looked fine but measured
# short of AA at this app's real (small) type sizes -- see DESIGN.md.
# ----------------------------------------------------------------------------
BG = "#eef0f3"           # app background
CARD_BG = "#ffffff"      # section/card background
SURFACE_ALT = "#f7f8fa"  # zebra rows, recessed areas
BORDER = "#8b93a0"       # hairline borders -- 3.10:1 on white, meets the 3:1
                         # non-text/UI-component minimum (WCAG 1.4.11)
TEXT = "#1a1f29"         # primary text -- 16.5:1 on white
MUTED = "#5f6b7a"        # secondary/muted text -- 5.43:1 on white, 4.75:1 on bg
ACCENT = "#3d4fd4"       # primary action color
ACCENT_HOVER = "#2f3fb8"
ACCENT_ACTIVE = "#28359c"
ACCENT_TEXT = "#ffffff"  # 6.43:1 on ACCENT

GOOD = "#0f7a3a"         # 5.43:1 on white, 4.90:1 on GOOD_BG
GOOD_BG = "#e7f7ee"
WARN = "#8a5209"         # 6.38:1 on white, 5.80:1 on WARN_BG -- amber needed
WARN_BG = "#fdf3e2"      # real darkening to clear AA; lighter drafts failed
BAD = "#c53030"          # 5.47:1 on white, 4.70:1 on BAD_BG
BAD_BG = "#fbeaea"

# ----------------------------------------------------------------------------
# Spacing scale -- 4px base. Every margin/padding in the UI should come from
# this set rather than an arbitrary number.
# ----------------------------------------------------------------------------
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24
SPACE_XL = 32

# ----------------------------------------------------------------------------
# Typography -- resolved against installed fonts at apply() time. Defaults
# below are placeholders until apply() runs; every widget module reads these
# module attributes *after* main_window.py calls theme.apply(root) first.
# ----------------------------------------------------------------------------
FONT_FAMILY = "Segoe UI"             # UI text
FONT_HEADING_FAMILY = "Segoe UI"     # heading text
FONT_HEADING_WEIGHT = "bold"         # "normal" if a real Semibold family exists
FONT_MONO = "Consolas"               # numeric/data readouts (score badge)

_UI_FONT_CHAIN = ["Segoe UI"]
_HEADING_FONT_CHAIN = ["Segoe UI Semibold"]
_MONO_FONT_CHAIN = ["Cascadia Mono", "Consolas", "Courier New"]


def _first_available(root, chain):
    available = set(tkfont.families(root))
    for name in chain:
        if name in available:
            return name
    return None


def _resolve_fonts(root):
    global FONT_FAMILY, FONT_HEADING_FAMILY, FONT_HEADING_WEIGHT, FONT_MONO
    FONT_FAMILY = _first_available(root, _UI_FONT_CHAIN) or "Segoe UI"
    heading = _first_available(root, _HEADING_FONT_CHAIN)
    if heading:
        FONT_HEADING_FAMILY, FONT_HEADING_WEIGHT = heading, "normal"
    else:
        FONT_HEADING_FAMILY, FONT_HEADING_WEIGHT = FONT_FAMILY, "bold"
    FONT_MONO = _first_available(root, _MONO_FONT_CHAIN) or "Courier New"


def score_colors(score):
    """(fg, bg) tint for the overall-score badge, by tier."""
    if score >= 70:
        return GOOD, GOOD_BG
    if score >= 40:
        return WARN, WARN_BG
    return BAD, BAD_BG


def apply(root):
    _resolve_fonts(root)
    root.configure(bg=BG)

    style = ttk.Style(root)
    # 'clam' is the only built-in theme that reliably honors custom colors
    # on Windows -- 'vista'/'winnative' ignore most style overrides. It also
    # supports 'focuscolor'/state-mapped bordercolor, which the focus-visible
    # treatment below depends on.
    style.theme_use("clam")

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD_BG)

    style.configure("TLabel", background=BG, foreground=TEXT, font=(FONT_FAMILY, 10))
    style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT, font=(FONT_FAMILY, 10))
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT_FAMILY, 9))
    style.configure("CardMuted.TLabel", background=CARD_BG, foreground=MUTED, font=(FONT_FAMILY, 9))
    style.configure("Header.TLabel", background=BG, foreground=TEXT,
                    font=(FONT_HEADING_FAMILY, 15, FONT_HEADING_WEIGHT))
    style.configure("SectionHeader.TLabel", background=CARD_BG, foreground=TEXT,
                    font=(FONT_HEADING_FAMILY, 9, FONT_HEADING_WEIGHT))

    style.configure("TButton", font=(FONT_FAMILY, 10), padding=(10, 6),
                    background="#ffffff", foreground=TEXT, borderwidth=1,
                    relief="solid", bordercolor=BORDER, focuscolor=ACCENT)
    style.map("TButton",
              background=[("active", SURFACE_ALT), ("disabled", SURFACE_ALT)],
              foreground=[("disabled", MUTED)],
              bordercolor=[("focus", ACCENT)])

    style.configure("Primary.TButton", font=(FONT_FAMILY, 10, "bold"), padding=(16, 8),
                    background=ACCENT, foreground=ACCENT_TEXT, borderwidth=0,
                    focuscolor=ACCENT_TEXT)
    style.map("Primary.TButton",
              background=[("active", ACCENT_HOVER), ("pressed", ACCENT_ACTIVE), ("disabled", "#b7bdf0")],
              foreground=[("disabled", "#ffffff")])

    style.configure("TCheckbutton", background=CARD_BG, foreground=TEXT,
                     font=(FONT_FAMILY, 10), focuscolor=ACCENT)
    style.map("TCheckbutton", background=[("active", CARD_BG)])

    style.configure("TRadiobutton", background=CARD_BG, foreground=TEXT,
                     font=(FONT_FAMILY, 10), focuscolor=ACCENT)
    style.map("TRadiobutton", background=[("active", CARD_BG)])

    style.configure("TEntry", padding=6, fieldbackground="#ffffff", bordercolor=BORDER)
    style.map("TEntry", bordercolor=[("focus", ACCENT)])

    style.configure("TSpinbox", padding=4, fieldbackground="#ffffff", bordercolor=BORDER)
    style.map("TSpinbox", bordercolor=[("focus", ACCENT)])

    style.configure("TNotebook", background=BG, bordercolor=BORDER)
    style.configure("TNotebook.Tab", background=SURFACE_ALT, foreground=MUTED,
                    font=(FONT_FAMILY, 10), padding=(14, 6))
    style.map("TNotebook.Tab",
              background=[("selected", CARD_BG)],
              foreground=[("selected", TEXT)])

    style.configure("TProgressbar", background=ACCENT, troughcolor="#e2e5ea",
                    borderwidth=0, thickness=6)

    style.configure(
        "Treeview",
        background="#ffffff", fieldbackground="#ffffff", foreground=TEXT,
        font=(FONT_FAMILY, 9), rowheight=24, borderwidth=0,
    )
    style.configure("Treeview.Heading", font=(FONT_FAMILY, 9, "bold"),
                     background=SURFACE_ALT, foreground=TEXT, relief="flat")
    style.map("Treeview", background=[("selected", "#dde1fa")], foreground=[("selected", TEXT)])
