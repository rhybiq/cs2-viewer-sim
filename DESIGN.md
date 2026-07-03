# Design system

This documents the desktop app's visual design system (`app/ui/theme.py`,
`app/ui/icons.py`) so future UI changes stay consistent instead of drifting
back into ad hoc colors/fonts/spacing. It's a **Tkinter/ttk desktop app**, not
a web app — several conventions below are adapted from web design-system
practice to what's actually achievable in Tk (noted inline where relevant).

## Brief

**What this is:** a local diagnostic tool a CS2 clip editor runs *during*
editing — pick a clip, get objective technical readouts (motion/pacing/
loudness/retention curve) plus an optional simulated-audience judgment, decide
ship-or-recut. Used repeatedly, in short sessions, by one technical user who
cares about exact numbers as much as verdicts. No cloud, no account, no chat.

**Personality:** precise instrument, not consumer app. Closer to a broadcast
loudness meter or color-grading scope than a SaaS dashboard — calm, legible,
quietly confident. Deliberately *not* the "AI app" look (no purple gradients
on dark, no glassmorphism, no oversized chat-bubble cards) — that aesthetic
would misrepresent a tool whose whole pitch is "this reads real pixels/audio,
it doesn't guess."

**Emotional tone:** calm confidence. A result should scan like a scope
reading — verdict color jumps out, everything else stays quiet.

## Tokens (`app/ui/theme.py`)

All colors, fonts, and spacing are module-level constants in `theme.py`. No
widget file should hardcode a hex color, font name, or pixel value that
already has a token — grep for `#[0-9a-fA-F]{6}` in `app/ui/` periodically to
catch drift.

### Color

Cool graphite neutrals (never pure `#000`/`#fff`), one confident accent,
semantic verdict colors. Every pairing below is **AA-verified** (computed via
the actual WCAG relative-luminance formula, not eyeballed) at this app's real
font sizes (9–10pt — below the 18pt/14pt-bold "large text" exemption, so the
strict 4.5:1 threshold applies to all of them, not the relaxed 3:1):

| Token | Value | Contrast | Use |
|---|---|---|---|
| `BG` | `#eef0f3` | — | app background |
| `CARD_BG` | `#ffffff` | — | card/panel background |
| `SURFACE_ALT` | `#f7f8fa` | — | zebra rows, recessed areas |
| `BORDER` | `#8b93a0` | 3.10:1 on white | hairlines (non-text UI component minimum is 3:1, not 4.5:1) |
| `TEXT` | `#1a1f29` | 16.5:1 on white | primary text |
| `MUTED` | `#5f6b7a` | 5.43:1 on white, 4.75:1 on `BG` | secondary/muted text |
| `ACCENT` | `#3d4fd4` | 6.43:1 on white | primary action |
| `ACCENT_HOVER` / `ACCENT_ACTIVE` | `#2f3fb8` / `#28359c` | — | button states |
| `ACCENT_TEXT` | `#ffffff` | 6.43:1 on `ACCENT` | text on accent buttons |
| `GOOD` / `GOOD_BG` | `#0f7a3a` / `#e7f7ee` | 5.43:1 / 4.90:1 | good verdict |
| `WARN` / `WARN_BG` | `#8a5209` / `#fdf3e2` | 6.38:1 / 5.80:1 | warn verdict |
| `BAD` / `BAD_BG` | `#c53030` / `#fbeaea` | 5.47:1 / 4.70:1 | bad verdict |

A first draft of `MUTED`/`GOOD`/`WARN`/`BORDER` measured short of AA (as low as
1.31:1 for the border, 3.52:1 for warn-on-warn-bg) before retuning — amber/
orange in particular is the hardest hue to get to 4.5:1 at this lightness.
Recompute contrast with the real formula whenever adjusting a color, don't
eyeball it.

### Typography

No bundled custom fonts (a real option, but adds packaging surface — font
files, a runtime loader or installer step — not justified yet for this scale
of app). Instead: **deliberate system-font pairing with verified fallback
chains**, resolved against what's actually installed at startup
(`theme._resolve_fonts`, called from `theme.apply(root)`), since neither
Cascadia Mono nor a separate Segoe UI Semibold family is guaranteed on a bare
Windows install:

- UI text: `Segoe UI` (`FONT_FAMILY`)
- Headings: `Segoe UI Semibold` if that family is actually installed,
  else `Segoe UI` rendered bold (`FONT_HEADING_FAMILY` / `FONT_HEADING_WEIGHT`)
- Data/numeric readouts: `Cascadia Mono` → `Consolas` → `Courier New`
  (`FONT_MONO`) — monospace-for-numbers is an instrument convention (scopes,
  terminals), not a stylistic default, and the chain guarantees something
  monospace renders even on a bare OS.

**Known limitation:** `ttk.Treeview` can't apply a font per column — a `tag`
styles the whole row, not one cell. So the results table can't make just its
"Value" column monospace without either monospacing the entire table (blurs
the Metric/Note text) or rebuilding it as individual Label widgets (loses the
built-in scrollbar/selection). Decision: the results table stays in the UI
font throughout; `FONT_MONO` is reserved for standalone numeric displays
(currently just the overall-score badge).

### Spacing

4px base scale, as named constants — use these, not arbitrary numbers:

```
SPACE_XS = 4    SPACE_SM = 8    SPACE_MD = 16    SPACE_LG = 24    SPACE_XL = 32
```

### Radius / elevation / border

Native ttk widgets on Windows can't do real drop-shadows or arbitrary corner
radii — this is a hard Tk limitation, not a stylistic choice. The achievable
equivalent: one consistent hairline-border language (`BORDER`, 1px) plus
deliberate background-tint layering (`BG` → `CARD_BG` → `SURFACE_ALT`)
standing in for elevation.

### States

`clam` is the base ttk theme (`style.theme_use("clam")` — confirmed, it's the
only built-in Windows theme that reliably honors color overrides;
`vista`/`winnative` ignore most of them). This makes `focuscolor` and
state-mapped `bordercolor` viable, which the default Tk dotted focus
rectangle badly needed replacing:

- Buttons/checkboxes/radiobuttons: `focuscolor=ACCENT`
- Entries/spinboxes: `style.map(..., bordercolor=[("focus", ACCENT)])`
- Hover/active/disabled: mapped per-widget in `apply()` — see `theme.py` for
  the full `style.map()` calls.

**Motion:** none, deliberately. Tk has no built-in transitions — animation is
only possible via manual `.after()`-driven frame loops, which is real
engineering effort for marginal gain in a desktop diagnostic tool. State
changes are instant. (No `prefers-reduced-motion` equivalent needed as a
result — there's no motion to reduce.)

## Icons (`app/ui/icons.py`)

**Grid:** 24×24 logical design grid, ~1.75px stroke weight, rendered at an
18×18 physical raster (small fixed size appropriate for buttons/labels — not
meant to scale up).

**Why hand-rolled instead of a library or SVG:** no `Pillow` dependency in the
base install (checked `requirements.txt`/`requirements-ocr.txt` — neither
pulls it in), and Canvas→image conversion is unreliable on Windows without
Ghostscript. Icons are drawn directly into a `tk.PhotoImage` pixel buffer via
a small Bresenham-line rasterizer (`icons._line`/`_polyline`), cached by
`(name, color)` in a module-level dict so Tk doesn't garbage-collect them.

**Background:** icons render on a fixed white background matching every place
they're actually placed (default button surface, `CARD_BG` labels — both
`#ffffff` in this theme). No transparency handling needed as a result; if an
icon is ever placed on a non-white surface, this assumption breaks and needs
revisiting.

**Placement strategy per widget type** (verified against real ttk
constraints before building):

| Widget | Icon support | Decision |
|---|---|---|
| `ttk.Button` | `image=` + `compound=` work | Icons on: Choose Video (`video`), Choose folder (`folder`), Pull/Download Ollama (`download`) |
| `ttk.Label` | `image=` + `compound=` work | Icons on: "detected" status labels (`check`, colored `GOOD`) |
| `ttk.Treeview` | images **only in column #0** | Verdict column is not column #0 (Metric name is) — forcing an icon there means displacing the metric name or restructuring columns. Decision: verdicts stay color-coded text only, no icon, no "●" bullet either |
| `ttk.Checkbutton` | supports image, but has its own native check glyph | Skip — an extra icon would duplicate the existing indicator |
| `tk.Label` (score badge) | supports image | Skip — the number alone reads fine; an icon here would be decorative, not clarifying |

**Current set:** `video`, `folder`, `download`, `check` — exactly the
locations above, nothing speculative. Add new icons only when a specific
placement needs one; a bigger set the app doesn't use yet would just be
untested dead code.

## Component conventions

- One primary action per view: `Primary.TButton` (solid `ACCENT` background)
  is reserved for the Analyze button on each tab; every other action is a
  plain outlined `TButton`.
- Verdict color (`GOOD`/`WARN`/`BAD`) is the only place saturated color
  appears outside the accent — it should stay that way so it keeps reading as
  a distinct signal, not blend into general UI chrome.
- Each tab (Analyze, AI Viewer) is self-contained: its own Analyze button,
  its own report-export row (`QuickReportExport`) right next to that button.
  Don't reintroduce a cross-cutting "Reports" tab — that was tried and
  explicitly reverted in favor of per-tab independence.
- Status detection (Ollama/EasyOCR available) is global (shown above the
  tabs), separate from the per-tab controls that consume that status.
