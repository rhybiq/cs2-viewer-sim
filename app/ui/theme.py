"""Visual design system for the desktop app: palette + ttk style configuration.

Kept in one place so every widget module pulls from the same source of truth
instead of hardcoding colors/fonts inline.
"""

from tkinter import ttk

BG = "#f4f5f7"           # app background
CARD_BG = "#ffffff"      # section/card background
BORDER = "#e2e4e9"       # hairline borders around cards
TEXT = "#1f2430"         # primary text
MUTED = "#6b7280"        # secondary/muted text
ACCENT = "#4f46e5"       # primary action color (indigo)
ACCENT_HOVER = "#4338ca"
ACCENT_TEXT = "#ffffff"

GOOD = "#16a34a"
GOOD_BG = "#eafaf0"
WARN = "#d97706"
WARN_BG = "#fef7e6"
BAD = "#dc2626"
BAD_BG = "#fdecec"

FONT_FAMILY = "Segoe UI"


def score_colors(score):
    """(fg, bg) tint for the overall-score badge, by tier."""
    if score >= 70:
        return GOOD, GOOD_BG
    if score >= 40:
        return WARN, WARN_BG
    return BAD, BAD_BG


def apply(root):
    root.configure(bg=BG)

    style = ttk.Style(root)
    # 'clam' is the only built-in theme that reliably honors custom colors
    # on Windows -- 'vista'/'winnative' ignore most style overrides.
    style.theme_use("clam")

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD_BG)

    style.configure("TLabel", background=BG, foreground=TEXT, font=(FONT_FAMILY, 10))
    style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT, font=(FONT_FAMILY, 10))
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT_FAMILY, 9))
    style.configure("CardMuted.TLabel", background=CARD_BG, foreground=MUTED, font=(FONT_FAMILY, 9))
    style.configure("Header.TLabel", background=BG, foreground=TEXT, font=(FONT_FAMILY, 15, "bold"))
    style.configure("SectionHeader.TLabel", background=CARD_BG, foreground=TEXT,
                    font=(FONT_FAMILY, 9, "bold"))

    style.configure("TButton", font=(FONT_FAMILY, 10), padding=(10, 6),
                    background="#ffffff", foreground=TEXT, borderwidth=1,
                    relief="solid", bordercolor=BORDER)
    style.map("TButton",
              background=[("active", "#f3f4f6"), ("disabled", "#f3f4f6")],
              foreground=[("disabled", MUTED)])

    style.configure("Primary.TButton", font=(FONT_FAMILY, 10, "bold"), padding=(16, 8),
                    background=ACCENT, foreground=ACCENT_TEXT, borderwidth=0)
    style.map("Primary.TButton",
              background=[("active", ACCENT_HOVER), ("disabled", "#c7c9f5")],
              foreground=[("disabled", "#ffffff")])

    style.configure("TCheckbutton", background=CARD_BG, foreground=TEXT, font=(FONT_FAMILY, 10))
    style.map("TCheckbutton", background=[("active", CARD_BG)])

    style.configure("TEntry", padding=6, fieldbackground="#ffffff", bordercolor=BORDER)

    style.configure("TProgressbar", background=ACCENT, troughcolor="#e5e7eb",
                    borderwidth=0, thickness=6)

    style.configure(
        "Treeview",
        background="#ffffff", fieldbackground="#ffffff", foreground=TEXT,
        font=(FONT_FAMILY, 9), rowheight=24, borderwidth=0,
    )
    style.configure("Treeview.Heading", font=(FONT_FAMILY, 9, "bold"),
                     background="#f3f4f6", foreground=TEXT, relief="flat")
    style.map("Treeview", background=[("selected", "#e5e5fa")], foreground=[("selected", TEXT)])
