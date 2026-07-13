# cs2-viewer-sim

Simulated-viewer feedback for short-form gaming clips — **no chat-model subscription required.** Point it at a vertical clip (YouTube Shorts / Reels) and get objective retention metrics plus, optionally, feedback from a local vision model acting as a viewer.

Built for CS2 highlight clips, but works on any vertical short-form video.

## Why

Every generic "give me feedback on my video" tool either needs a paid API or judges the clip from a transcript it never actually watched. This runs entirely on your own machine: the objective metrics are pure OpenCV/ffmpeg, and the "viewer" is an open-weight vision-language model running locally via [Ollama](https://ollama.com). Zero per-token cost, nothing leaves your box.

## How it works

The tool splits "viewer feedback" into layers, because they need different tech:

**Layer 1 — deterministic metrics** (runs today, zero model download)
Objective signals that correlate with short-form retention:
- **Hook strength** — motion in the first ~2.5s. A slow open is the top cause of early swipe-away.
- **Pacing** — cuts per minute via scene detection, with long-static-shot flagging.
- **Flatness** — stretches where nothing moves (likely drop-off points).
- **Loudness** — integrated LUFS vs the ~-14 platform target.
- **Aspect check** — flags a non-vertical export before you ever upload it.

**Text overlay quality** (optional, local EasyOCR, `--ocr`)
Finds on-screen text — creator captions and in-game HUD/kill-feed alike — and scores whether it's actually legible on a phone: text size, contrast against the background, and whether it sits close enough to the edge to get clipped by a vertical crop.

**Platform compliance** (optional, `--platform "YouTube Shorts"|"Instagram Reels"|"TikTok"`)
Checks the clip against that platform's actual requirements — 9:16 aspect ratio, minimum resolution, upload duration limits — and, when paired with `--ocr`, whether any detected on-screen text sits under where that platform's own UI (captions, username, action buttons) would cover it. Kept as its own metric, not blended into the overall score, since a hard requirement (wrong aspect ratio) is a different kind of problem than a retention-quality signal.

**Layer 2 — simulated viewer** (optional, local VLM via Ollama)
Samples frames and asks a local vision model, prompted as a CS2 fan scrolling Shorts, to return: which second it would swipe away, whether the hook reads, whether the kill feed is legible, and concrete suggestions.

**Layer 3 — calibration** (your data, over time)
Every run emits an `energy_curve` and flat-stretch data in its JSON output. Once you export your real YouTube retention curves, correlate them against these features to tune the thresholds to *your* audience — something no generic model can do for you.

**Layer 4 — raw-footage highlight scanning** (optional, `--scan-footage`)
A different problem from the layers above: instead of judging a clip you've already cut, this scans a full match recording (30-60+ minutes) for candidate moments worth cutting into a clip in the first place. Cheap whole-file signals — sparse motion sampling, a time-varying loudness curve (ffmpeg `ebur128`), and optionally speech-reaction bursts (local Whisper via `faster-whisper`) — flag candidate windows first; only those few candidates (typically ~10-30/hour, not the whole file) get a second, targeted pass of dense EasyOCR to upgrade a generic "action spike" into a specific "clutch" tag when it finds several distinct on-screen text events clustered together (a kill-feed proxy). Outputs a ranked list of windows (start/end, tags, confidence, reason) — it doesn't cut files for you. Deliberately crude, honest heuristics, not real highlight/humor detection: a starting point for editing, not a final cut list.

## Requirements

- Python 3.9+
- `ffmpeg` on your PATH (used for loudness measurement)
- For Layer 2 only: [Ollama](https://ollama.com) + a vision model, and a GPU with ~6 GB+ VRAM
- For text overlay quality only: `pip install -r requirements-ocr.txt` (pulls in EasyOCR + torch, ~500MB+)

## Download the desktop app

No Python required. Grab the latest installer from [Releases](https://github.com/rhybiq/cs2-viewer-sim/releases/latest), run it, then launch **CS2 Viewer Sim** from the Start Menu: pick a video, click Analyze, read the scorecard. ffmpeg is bundled in; Layer 2 (the local AI viewer) is auto-detected and offered as a checkbox if you also have [Ollama](https://ollama.com) running.

Every push to `main` and tagged release (`v*`) rebuilds the exe/installer via [`.github/workflows/build-app.yml`](.github/workflows/build-app.yml) — see [`packaging/`](packaging/) if you want to build it yourself with `packaging/build.ps1` (PyInstaller) and `packaging/installer.iss` (Inno Setup).

## Install (CLI / from source)

```bash
git clone https://github.com/rhybiq/cs2-viewer-sim.git
cd cs2-viewer-sim
pip install -r requirements.txt
```

Install `ffmpeg` separately if you don't have it (`winget install ffmpeg` on Windows, `brew install ffmpeg` on macOS, `sudo apt install ffmpeg` on Linux).

For the simulated viewer, install Ollama and pull a vision model:

```bash
ollama pull qwen2.5vl:7b     # ~6 GB, strong on text-heavy frames (kill feeds, overlays)
# or, for a broader model with more general reasoning:
ollama pull gemma3:12b
```

## Usage

```bash
# Desktop app, from source (same thing the packaged installer ships)
python run_app.py

# Layer 1 only — objective metrics + HTML report with a motion-energy curve
python viewer_sim.py yourclip.mp4 --html report.html

# Add the simulated viewer (needs Ollama running)
python viewer_sim.py yourclip.mp4 --vlm --html report.html

# Score caption/HUD text legibility (needs requirements-ocr.txt)
python viewer_sim.py yourclip.mp4 --ocr --html report.html

# Pick a different local model, dump raw JSON for calibration
python viewer_sim.py yourclip.mp4 --vlm --model gemma3:12b --json report.json

# Scan a full match VOD for candidate highlight windows instead of scoring one clip
python viewer_sim.py match_vod.mp4 --scan-footage --top-n 20
```

### Options

| Flag | Description |
|------|-------------|
| `--vlm` | Run the local Ollama vision model as a simulated viewer |
| `--model NAME` | Ollama model tag (default `qwen2.5vl:7b`) |
| `--host URL` | Ollama host (default `http://localhost:11434`) |
| `--ocr` | Score caption/HUD text legibility via local EasyOCR |
| `--platform NAME` | Check aspect ratio/resolution/duration/safe-zone against `"YouTube Shorts"`, `"Instagram Reels"`, or `"TikTok"` (pair with `--ocr` for the safe-zone-overlap part) |
| `--html PATH` | Write a visual HTML report |
| `--json PATH` | Write the raw report (feeds Layer 3 calibration) |
| `--scan-footage` | Scan a long raw recording for candidate highlight windows instead of scoring `VIDEO` as one clip |
| `--top-n N` | Max candidate windows to report for `--scan-footage` (default 20) |
| `--no-speech` | With `--scan-footage`, skip speech-based reaction detection (motion/loudness signals only, faster, no `faster-whisper` needed) |

## Example output

```
=== Simulated Viewer Report: clip.mp4 ===
1080x1920  6.0s  30.0fps  vertical
Overall: 62.5/100

  OK hook_strength       0.843   Opens with strong motion — grabs the scroll.
  XX pacing                0.0   Only ~0 cuts/min; feels slow for Shorts.
  OK flatness              0.0   No dead stretches — energy stays up throughout.
  !! loudness_lufs       -21.8   -21.8 LUFS — quiet; will feel weak vs autoplay.
```

The HTML report additionally plots motion energy over time, with blue lines for cuts and red bands over flat stretches.

## Tuning

The thresholds at the top of `viewer_sim.py` (hook window, cuts/min bands, LUFS target, flat-stretch length) are starting guesses for vertical short-form. Adjust them once you've eyeballed a few of your own clips — the pacing and loudness verdicts especially are directional, not mastering-grade.

## Roadmap

- [ ] Kill-feed hook metric — report the exact second the first kill becomes visible (can reuse the EasyOCR pass added for text overlay quality)
- [ ] Batch mode over a folder of clips
- [ ] CSV export of features across many clips for Layer 3 regression
- [x] Per-platform threshold presets (Shorts vs Reels vs TikTok) — see `--platform` / the Clip Metrics tab's "platform requirements" check
- [x] Raw-footage highlight scanning — find candidate clippable moments in a full match VOD, see `--scan-footage` / the desktop app's "Find Highlights" tab

## License

MIT — see [LICENSE](LICENSE).
