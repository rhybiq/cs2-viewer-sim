# CS2 Viewer Sim — PySide6 UI Rewrite Spec

## Context for the implementer

`viewer_sim` is a fully-offline CS2 clip analyzer for short-form content (YouTube Shorts / Reels).
Current UI is Tkinter/ttk (v0.1.11) and is being rewritten in **PySide6**. The analysis backends
already exist and must be reused, not rewritten:

- **Metrics pass (deterministic, fast):** OpenCV, PySceneDetect, pyloudnorm. Produces per-metric
  rows (value, range thresholds, verdict Good/Warn/Bad, note) plus an overall 0–100 score.
- **AI Viewer pass (slow, subjective):** local VLM via Ollama. Produces simulated-viewer feedback:
  would-watch-to-end verdict, hook read (yes/no), HUD readability, general suggestion. Supports a
  single persona string OR a panel of N personas (multiple Ollama calls), with optional custom
  persona definitions (one per line, `name: description`).
- Optional pre-flight checks: Ollama + model detected; EasyOCR detected (for text-overlay quality
  option on the metrics pass).
- Outputs can be saved as HTML and/or JSON, default save location = same folder as the video.

Hard constraints: **zero cloud/paid APIs, everything local**, runs on Windows next to
DaVinci Resolve and CS2 (keep it light). Target GPU has 12GB VRAM — analysis must run off the
UI thread.

---

## 1. Window & layout structure

- [ ] **1.1** Main window title: `CS2 Viewer Sim — v<version>`. Subtitle text under the app title:
  "Simulated-viewer feedback for short-form clips — no cloud, runs locally."
- [ ] **1.2** **Global video selector above the tabs** (shared state): "Choose Video…" button +
  current filename label. Both tabs read from this single selection. If no video selected,
  both Analyze buttons are disabled with tooltip "Choose a video first."
- [ ] **1.3** **Dependency status chips** in a top bar: "Ollama + model detected" and
  "EasyOCR detected" as small green chips when present; grey/amber with a short hint when absent
  (e.g. "Ollama not found — AI Viewer disabled"). If Ollama is absent, disable the AI Viewer tab's
  Analyze button, not the whole tab.
- [ ] **1.4** **Save controls appear once**, globally (near the video selector): Save HTML checkbox,
  Save JSON checkbox, Save-to path (default label: "(same folder as the video)") + "Choose folder…".
  Output filenames must be distinct per pass: `<clip>_metrics.html/json` and `<clip>_ai_viewer.html/json`.
  Remove/hide "Save in memory" unless it does something user-visible; if kept, add a tooltip
  explaining it.
- [ ] **1.5** Two tabs, renamed:
  - **"Clip Metrics"** — caption line: "Objective signals: pacing, loudness, motion, scene cuts."
  - **"AI Viewer"** — caption line: "A simulated viewer reacts to your clip (local Ollama)."
- [ ] **1.6** Results area in each tab expands to fill the window (proper Qt layouts / stretch).
  No large fixed dead zones; controls live in a compact top strip inside each tab.
- [ ] **1.7** **Update-available notice** as a badge/button in the top bar (e.g. "v0.1.12 available"),
  not bottom-left.

## 2. Clip Metrics tab

- [ ] **2.1** Top strip: "Also check text overlay quality (captions + HUD legibility)" checkbox
  (disabled with tooltip if EasyOCR absent) + **Analyze** button.
- [ ] **2.2** **Score display anchored with results**: e.g. "Clip Score: 60/100" in a prominent
  QLabel directly above the table, background/text color by band —
  red < 50, amber 50–69, green ≥ 70 (make bands a single constant, easy to tune).
- [ ] **2.3** Results in a **QTableView with a custom model** (not QTableWidget string-stuffing).
  Columns: **Metric | Value | Verdict | Note**.
- [ ] **2.4** **Range column removed from the table**; the full threshold text (e.g.
  "cuts/min · good ≥20 · warn 8–20 · bad <8") becomes a **tooltip on the Verdict cell**.
- [ ] **2.5** **Human-readable metric names** via a display-name map:
  `hook_strength → Hook Strength`, `pacing → Pacing (cuts/min)`, `flatness → Dead Time`,
  `loudness_lufs → Loudness (LUFS)`, `predicted_retention → Predicted Retention`,
  `flat_stretches → Flat Stretches`. Unknown metrics fall back to title-cased key.
- [ ] **2.6** **Sort rows by severity**: Bad first, then Warn, then Good (stable within group).
- [ ] **2.7** Verdict cell rendered as a colored badge/pill (dark-theme-safe colors, see §5).
- [ ] **2.8** **Fix the flat-stretch double-report**: merge `flat_stretches` into the
  flatness/Dead Time row OR give it a full-sentence note including timestamps and an editing
  suggestion, e.g. "1 flat stretch at 4.75–7.25s — add a cut, zoom, or SFX here." Only one row
  should warn about a given flat stretch.
- [ ] **2.9** **Timestamps are actionable**: consistent `M:SS.s–M:SS.s` (or `S.ss–S.ss` for <60s
  clips) formatting in notes; row context menu (right-click) → "Copy timestamps" puts the raw
  seconds range on the clipboard for use in DaVinci Resolve.
- [ ] **2.10** **Empty state** before first run: centered placeholder text over the table area,
  "Run analysis to see pacing, loudness, and scene metrics." — never bare column headers over
  an empty grid.
- [ ] **2.11** *(Stretch goal, do last)* Thin horizontal timeline strip above the table marking
  flat/dead zones along the clip duration.

## 3. AI Viewer tab

- [ ] **3.1** Top strip: persona controls + **Analyze** button. Persona controls:
  - Single-persona line edit (placeholder: `e.g. "a cooking-video fan"`, current default "gamer").
  - Checkbox: "Use a panel of viewer personas instead (slower, several Ollama calls)" +
    "Number of viewers" spinbox.
  - Custom-personas multi-line edit (placeholder explains `name: description`, one per line,
    replaces generated pool when non-empty).
  - **Behavior:** when the panel checkbox is checked, the single-persona field is
    `setEnabled(False)`; when unchecked, the panel spinbox and custom-personas box are disabled.
    Remove the "used unless the persona panel below is enabled" sentence — the enable/disable
    state communicates it.
- [ ] **3.2** **Structured results rendering** (no hyphenated plain-text block):
  - **Verdict badges row:** "Hook: PASS/FAIL" and "Watch to end: YES/NO" as prominent colored
    badges, each with the model's one-line reason next to it. "HUD readable: yes/no" as a smaller chip.
  - **General suggestion** as a normal paragraph at the bottom.
  - Panel mode: one collapsible section per persona (persona name as header) with the same
    structure inside, plus a small consensus summary at top ("2/3 would watch to end").
- [ ] **3.3** Show the selected video filename near this tab's Analyze button (reads the global
  selection from §1.2).

## 4. Execution, status & feedback

- [ ] **4.1** **All analysis runs on QThread / QThreadPool workers** — the UI must never freeze.
  While running: Analyze button becomes "Cancel", an indeterminate progress bar (or determinate
  if the backend reports progress) shows in the tab, and the other tab's Analyze is disabled
  (one job at a time).
- [ ] **4.2** Replace the "Done." label with a **QStatusBar summary** after each run:
  e.g. `Analyzed dust2 b 1v4 choke.mp4 (8.2s clip) in 14.3s · AI: persona "gamer"` or
  `· panel of 3`. Errors surface here too, in red, with the exception message truncated.
- [ ] **4.3** Saved-file confirmation: when Save HTML/JSON is on, status bar appends
  `— saved metrics_report.html` (clickable to open containing folder is a nice-to-have).

## 5. Theme

- [ ] **5.1** **Dark theme via QSS** (single .qss file in repo, loaded at startup). Aesthetic
  target: belongs next to OBS / DaVinci Resolve. Dark grey surfaces, one accent color for
  primary buttons.
- [ ] **5.2** Verdict colors tuned for dark backgrounds — use desaturated/editor-theme tones,
  not pure `#FF0000`/`#00FF00`. Suggested: Good `#7ee2a8`, Warn `#f5c97b`, Bad `#f08080`
  (adjust freely, but keep WCAG-ish contrast against the surface).
- [ ] **5.3** Keep the monospace treatment for the score number if desired, but style it as an
  intentional design element (sized, padded, banded color), not a default beige box.

## 6. Workflow bridge (do last)

- [ ] **6.1** After a successful Clip Metrics run, show a button in that tab:
  **"Get simulated viewer reaction →"** — switches to the AI Viewer tab (same video already
  selected) and focuses its Analyze button. Makes the cheap-pass → expensive-pass pipeline explicit.

---

## Build order

1. §1 skeleton: window, top bar, global video selector, save controls, tabs, dep chips.
2. §2 Clip Metrics: model/view table, score banner, severity sort, name map, tooltips,
   flat-stretch fix, empty state, copy-timestamps.
3. §3 AI Viewer: persona controls with enable/disable logic, structured results, panel sections.
4. §4 threading + status bar (wire into both tabs as they land).
5. §5 QSS dark theme.
6. §6 pipeline button. §2.11 timeline strip only if everything else is done.

## Non-goals / guardrails

- Do **not** rewrite the analysis backends; wrap the existing functions behind worker objects.
- No new dependencies beyond PySide6 (and whatever the backends already use).
- No network calls of any kind except localhost Ollama.
- Keep Windows as the primary target; don't break launching alongside Resolve/CS2
  (avoid heavy startup work on the main thread).
