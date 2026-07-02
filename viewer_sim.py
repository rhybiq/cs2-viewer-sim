#!/usr/bin/env python3
"""
viewer_sim.py -- Simulated-viewer feedback for short-form gaming clips.

No chat-model subscription required. Two layers:

  Layer 1 (deterministic): objective retention signals computed locally with
           OpenCV / ffmpeg / PySceneDetect / pyloudnorm. Runs today, zero
           model download.

  Layer 2 (simulated viewer): OPTIONAL. Sends sampled frames to a local
           vision-language model via Ollama (default: qwen2.5vl:7b) with a
           "CS2 viewer scrolling Shorts" persona. Enable with --vlm.

  Text overlay quality: OPTIONAL. Scores caption/HUD legibility (size,
           contrast, edge-clip risk) via local EasyOCR. Enable with --ocr
           (needs `pip install -r requirements-ocr.txt`).

Usage:
    python viewer_sim.py clip.mp4
    python viewer_sim.py clip.mp4 --vlm                 # add local VLM viewer
    python viewer_sim.py clip.mp4 --vlm --model gemma3:12b
    python viewer_sim.py clip.mp4 --ocr                 # add text overlay quality
    python viewer_sim.py clip.mp4 --html report.html    # write visual report

Design notes:
  - Targets vertical short-form (Shorts / Reels). Tune THRESHOLDS below.
  - Everything is CPU-friendly except Layer 2 (uses your GPU via Ollama).
  - Built to slot next to cs2_highlight_finder.py: same OpenCV frame loop
    style, so the kill-feed OCR from that tool can feed the "hook shows the
    kill by second X" check later.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import os
from dataclasses import dataclass, asdict, field
from typing import Optional

import cv2
import numpy as np

# ----------------------------------------------------------------------------
# Tunable thresholds for vertical short-form. Adjust after you calibrate
# against your own YouTube retention exports (Layer 3).
# ----------------------------------------------------------------------------
HOOK_WINDOW_S = 2.5          # first N seconds judged as "the hook"
LONG_SHOT_S = 4.5            # shots longer than this are flagged as draggy
TARGET_LUFS = -14.0          # platform loudness target
LUFS_TOLERANCE = 2.0         # +/- band considered fine
FLAT_ENERGY_PCTL = 15        # frames below this motion percentile = "flat"
FLAT_RUN_S = 2.0             # a flat stretch this long is worth flagging
SAMPLE_FPS = 4               # analysis sampling rate (not the source fps)

# Text overlay quality (--ocr, optional: needs `pip install -r requirements-ocr.txt`)
TEXT_SAMPLE_EVERY_S = 1.0     # how often to sample frames for OCR
TEXT_MAX_SAMPLES = 10         # cap OCR cost -- EasyOCR is slow per-frame on CPU
TEXT_MIN_CONFIDENCE = 0.4     # discard low-confidence OCR hits (likely noise, not real text)
TEXT_GOOD_HEIGHT_FRAC = 0.05  # text this tall (as a fraction of frame height) scores fully on size
TEXT_GOOD_CONTRAST = 60.0     # stdev of pixel intensity within the text box scoring fully on contrast
TEXT_EDGE_MARGIN_FRAC = 0.04  # text starting/ending within this margin of frame L/R risks vertical-crop clipping


def ffmpeg_bin():
    """Path to ffmpeg: a bundled copy next to a frozen exe, else whatever's on PATH."""
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "ffmpeg.exe")
        if os.path.exists(bundled):
            return bundled
    return "ffmpeg"


@dataclass
class Metric:
    name: str
    value: float
    verdict: str            # "good" | "warn" | "bad"
    note: str
    scale: str = ""          # human-readable good/warn/bad thresholds for this metric


@dataclass
class Report:
    file: str
    duration_s: float
    fps: float
    resolution: str
    is_vertical: bool
    metrics: list = field(default_factory=list)
    energy_curve: list = field(default_factory=list)   # (t, normalized_energy)
    scene_cuts_s: list = field(default_factory=list)
    flat_stretches: list = field(default_factory=list)  # (start_s, end_s)
    retention_curve: list = field(default_factory=list)  # (t, predicted_pct_remaining)
    vlm_notes: Optional[dict] = None
    persona_notes: Optional[dict] = None      # {persona_key: raw VLM response, ...}
    persona_summary: Optional[dict] = None    # aggregated view across personas
    overall_score: float = 0.0


# ----------------------------------------------------------------------------
# Layer 1a: video probe
# ----------------------------------------------------------------------------
def probe(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        sys.exit(f"Could not open {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    dur = frames / fps if fps else 0.0
    return fps, dur, w, h


# ----------------------------------------------------------------------------
# Layer 1b: motion / energy curve  (drives hook + flatness checks)
# ----------------------------------------------------------------------------
def energy_curve(path, sample_fps=SAMPLE_FPS):
    cap = cv2.VideoCapture(path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(src_fps / sample_fps)))
    prev = None
    idx = 0
    curve = []  # (t_seconds, mean_abs_frame_diff)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, (160, 284))  # cheap, keeps vertical aspect-ish
            if prev is not None:
                diff = float(np.mean(cv2.absdiff(g, prev)))
                curve.append((idx / src_fps, diff))
            prev = g
        idx += 1
    cap.release()
    if not curve:
        return []
    vals = np.array([v for _, v in curve])
    hi = vals.max() if vals.max() > 0 else 1.0
    return [(round(t, 3), round(v / hi, 4)) for (t, v) in curve]


HOOK_SCALE = "0-1 motion · good ≥0.35 (& ≥90% of rest) · warn ≥0.20 · bad <0.20"


def analyze_hook(curve):
    hook = [v for (t, v) in curve if t <= HOOK_WINDOW_S]
    rest = [v for (t, v) in curve if t > HOOK_WINDOW_S]
    if not hook:
        return Metric("hook_strength", 0.0, "bad", "No frames in hook window.", HOOK_SCALE)
    hook_energy = float(np.mean(hook))
    rest_energy = float(np.mean(rest)) if rest else hook_energy
    # A strong hook has motion at or above the rest of the video.
    ratio = hook_energy / rest_energy if rest_energy > 0 else 1.0
    if hook_energy >= 0.35 and ratio >= 0.9:
        verdict, note = "good", "Opens with strong motion — grabs the scroll."
    elif hook_energy >= 0.2:
        verdict, note = "warn", "Hook is soft; consider opening on the kill/action."
    else:
        verdict, note = "bad", "Slow open. #1 cause of early swipe-away on Shorts."
    return Metric("hook_strength", round(hook_energy, 3), verdict, note, HOOK_SCALE)


FLATNESS_SCALE = "seconds of dead time · good 0s · warn >0-3s · bad >3s"


def analyze_flatness(curve):
    if not curve:
        return Metric("flatness", 0.0, "bad", "No curve.", FLATNESS_SCALE), []
    vals = np.array([v for _, v in curve])
    thresh = np.percentile(vals, FLAT_ENERGY_PCTL)
    ts = [t for t, _ in curve]
    dt = np.median(np.diff(ts)) if len(ts) > 1 else 0.25
    flat_runs = []
    run_start = None
    for (t, v) in curve:
        if v <= thresh:
            run_start = t if run_start is None else run_start
            run_end = t
        else:
            if run_start is not None and (run_end - run_start) >= FLAT_RUN_S:
                flat_runs.append((round(run_start, 2), round(run_end, 2)))
            run_start = None
    if run_start is not None and (curve[-1][0] - run_start) >= FLAT_RUN_S:
        flat_runs.append((round(run_start, 2), round(curve[-1][0], 2)))
    if not flat_runs:
        return Metric("flatness", 0.0, "good",
                      "No dead stretches — energy stays up throughout.", FLATNESS_SCALE), []
    total_flat = sum(e - s for s, e in flat_runs)
    verdict = "bad" if total_flat > 3 else "warn"
    note = f"{len(flat_runs)} flat stretch(es); viewers drop where nothing moves."
    return Metric("flatness", round(total_flat, 2), verdict, note, FLATNESS_SCALE), flat_runs


# ----------------------------------------------------------------------------
# Layer 1c: pacing via scene cuts
# ----------------------------------------------------------------------------
PACING_SCALE = f"cuts/min · good ≥20 · warn ≥8-20 · bad <8 (shots >{LONG_SHOT_S}s flagged)"


def analyze_pacing(path, duration):
    try:
        from scenedetect import detect, ContentDetector
        scenes = detect(path, ContentDetector())
        cuts = [round(s[0].get_seconds(), 2) for s in scenes][1:]  # drop t=0
    except Exception as e:
        return Metric("pacing", 0.0, "warn", f"Scene detect skipped: {e}", PACING_SCALE), []
    n_cuts = len(cuts)
    cpm = (n_cuts / duration * 60) if duration else 0
    # Flag long static shots
    boundaries = [0.0] + cuts + [duration]
    long_shots = [(round(boundaries[i], 2), round(boundaries[i + 1], 2))
                  for i in range(len(boundaries) - 1)
                  if boundaries[i + 1] - boundaries[i] > LONG_SHOT_S]
    if cpm >= 20:
        verdict, note = "good", f"Snappy pacing (~{cpm:.0f} cuts/min)."
    elif cpm >= 8:
        verdict, note = "warn", f"~{cpm:.0f} cuts/min; tighten for short-form energy."
    else:
        verdict, note = "bad", f"Only ~{cpm:.0f} cuts/min; feels slow for Shorts."
    if long_shots:
        note += f" {len(long_shots)} shot(s) run >{LONG_SHOT_S}s."
    return Metric("pacing", round(cpm, 1), verdict, note, PACING_SCALE), cuts


# ----------------------------------------------------------------------------
# Layer 1d: loudness (LUFS) via ffmpeg loudnorm
# ----------------------------------------------------------------------------
LOUDNESS_SCALE = f"LUFS · good {TARGET_LUFS - LUFS_TOLERANCE:.0f} to {TARGET_LUFS + LUFS_TOLERANCE:.0f} (target {TARGET_LUFS:.0f}) · warn outside that band"


def _ffmpeg_no_window_flags():
    """Suppress the console flash when a windowed (no-console) app spawns ffmpeg on Windows."""
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return subprocess.CREATE_NO_WINDOW
    return 0


def analyze_loudness(path):
    ffmpeg_path = ffmpeg_bin()
    cmd = [ffmpeg_path, "-hide_banner", "-nostdin", "-i", path,
           "-af", "loudnorm=print_format=json", "-f", "null", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                             stdin=subprocess.DEVNULL,
                             creationflags=_ffmpeg_no_window_flags())
    except Exception as e:
        return Metric("loudness_lufs", 0.0, "warn",
                      f"ffmpeg failed to launch ({ffmpeg_path}): {e}", LOUDNESS_SCALE)

    def diagnostics():
        combined = (out.stderr or "") + (out.stdout or "")
        tail = " ".join(combined.strip().splitlines()[-3:])[-300:]
        return (f"ffmpeg exit code {out.returncode}, binary: {ffmpeg_path}. "
                f"Output: {tail or '(ffmpeg produced no output at all -- it may not be a valid '
                'executable in this environment)'}")

    txt = out.stderr
    if "Stream" not in txt or "Audio:" not in txt:
        return Metric("loudness_lufs", 0.0, "warn",
                      f"No audio stream detected by ffmpeg. {diagnostics()}", LOUDNESS_SCALE)
    start = txt.rfind("{")
    end = txt.rfind("}")
    if start == -1 or end == -1:
        return Metric("loudness_lufs", 0.0, "warn",
                      f"ffmpeg ran but printed no loudnorm summary. {diagnostics()}", LOUDNESS_SCALE)
    try:
        data = json.loads(txt[start:end + 1])
        lufs = float(data.get("input_i", 0.0))
    except Exception as e:
        return Metric("loudness_lufs", 0.0, "warn", f"Could not parse loudness output: {e}", LOUDNESS_SCALE)
    delta = lufs - TARGET_LUFS
    if abs(delta) <= LUFS_TOLERANCE:
        verdict, note = "good", f"On target ({lufs:.1f} LUFS)."
    elif delta < 0:
        verdict, note = "warn", f"{lufs:.1f} LUFS — quiet; will feel weak vs autoplay."
    else:
        verdict, note = "warn", f"{lufs:.1f} LUFS — hot; platforms will turn it down."
    return Metric("loudness_lufs", round(lufs, 1), verdict, note, LOUDNESS_SCALE)


# ----------------------------------------------------------------------------
# Layer 1e: simulated retention curve -- a heuristic "% of audience still
# watching" model derived from hook/pacing/flatness, not a measurement. Meant
# to be calibrated later against real retention exports (see Layer 3).
# ----------------------------------------------------------------------------
BASE_CHURN_PCT_PER_S = 1.2     # baseline drop-off per second of "natural" attrition
FLAT_CHURN_MULT = 3.0          # churn multiplier while inside a flat/low-energy stretch
CUT_RETENTION_BONUS = 0.6      # % retention recovered at each scene cut (re-hook moment)
HOOK_BAD_PENALTY_PCT = 15.0    # extra drop spread across the hook window if the hook is weak/bad
RETENTION_SCALE = "% predicted still watching at end · good >=50 · warn >=30 · bad <30"


def simulate_retention(curve, hook_metric, flat_runs, cuts, duration):
    """Second-by-second predicted retention, seeded at 100%. A model, not a measurement."""
    if not curve or duration <= 0:
        return []

    hook_penalty_total = 0.0
    if hook_metric.verdict == "bad":
        hook_penalty_total = HOOK_BAD_PENALTY_PCT
    elif hook_metric.verdict == "warn":
        hook_penalty_total = HOOK_BAD_PENALTY_PCT * 0.4

    cut_times = sorted(cuts or [])
    cut_idx = 0
    retention = 100.0
    points = []
    prev_t = 0.0
    for t, _energy in curve:
        dt = max(0.0, t - prev_t)
        in_flat = any(s <= t <= e for s, e in (flat_runs or []))
        retention -= BASE_CHURN_PCT_PER_S * (FLAT_CHURN_MULT if in_flat else 1.0) * dt
        if hook_penalty_total and t <= HOOK_WINDOW_S:
            retention -= hook_penalty_total * (dt / HOOK_WINDOW_S)
        while cut_idx < len(cut_times) and cut_times[cut_idx] <= t:
            retention = min(100.0, retention + CUT_RETENTION_BONUS)
            cut_idx += 1
        retention = max(0.0, min(100.0, retention))
        points.append((round(t, 2), round(retention, 1)))
        prev_t = t
    return points


def analyze_retention(retention_points):
    if not retention_points:
        return Metric("predicted_retention", 0.0, "warn",
                      "Not enough data to simulate retention.", RETENTION_SCALE)
    end_retention = retention_points[-1][1]
    if end_retention >= 50:
        verdict = "good"
        note = f"Model predicts ~{end_retention:.0f}% of viewers still watching by the end."
    elif end_retention >= 30:
        verdict = "warn"
        note = f"Model predicts ~{end_retention:.0f}% still watching by the end -- room to tighten pacing."
    else:
        verdict = "bad"
        note = f"Model predicts only ~{end_retention:.0f}% still watching by the end."
    return Metric("predicted_retention", round(end_retention, 1), verdict, note, RETENTION_SCALE)


# ----------------------------------------------------------------------------
# Layer 1f: text overlay quality -- captions + in-game HUD/kill-feed legibility
# (optional, --ocr: needs `pip install -r requirements-ocr.txt`)
# ----------------------------------------------------------------------------
TEXT_OVERLAY_SCALE = (
    "0-100 legibility (size + contrast, minus edge-clip risk) · good >=70 · "
    "warn >=40 · bad <40 (no text found scores warn -- may be intentional)"
)


def _sample_frames_bgr(path, every_s=TEXT_SAMPLE_EVERY_S, max_frames=TEXT_MAX_SAMPLES):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    dur = frame_count / fps if fps else 0.0
    frames = []
    for t in np.arange(0, dur, every_s)[:max_frames]:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    cap.release()
    return frames


def analyze_text_overlay(path):
    try:
        import easyocr
    except ImportError:
        return Metric("text_overlay", 0.0, "warn",
                      "EasyOCR not installed -- run: pip install -r requirements-ocr.txt",
                      TEXT_OVERLAY_SCALE)

    frames = _sample_frames_bgr(path)
    if not frames:
        return Metric("text_overlay", 0.0, "bad", "Could not sample frames.", TEXT_OVERLAY_SCALE)

    h_frame, w_frame = frames[0].shape[:2]
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)

    heights_frac, contrasts, edge_hits = [], [], 0
    frames_with_text = 0
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        hits = [
            (bbox, text, conf) for bbox, text, conf in reader.readtext(rgb)
            if conf >= TEXT_MIN_CONFIDENCE and text.strip()
        ]
        if not hits:
            continue
        frames_with_text += 1
        for bbox, _text, _conf in hits:
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x0, x1 = int(min(xs)), int(max(xs))
            y0, y1 = int(min(ys)), int(max(ys))
            roi = gray[y0:y1, x0:x1]
            if roi.size == 0:
                continue
            heights_frac.append((y1 - y0) / h_frame)
            contrasts.append(float(roi.std()))
            if x0 <= w_frame * TEXT_EDGE_MARGIN_FRAC or x1 >= w_frame * (1 - TEXT_EDGE_MARGIN_FRAC):
                edge_hits += 1

    if not heights_frac:
        return Metric("text_overlay", 0.0, "warn",
                      "No on-screen text/captions detected -- fine if intentional; "
                      "captions help retention for muted viewers.", TEXT_OVERLAY_SCALE)

    avg_height_frac = float(np.mean(heights_frac))
    avg_contrast = float(np.mean(contrasts))
    edge_frac = edge_hits / len(heights_frac)
    height_score = min(1.0, avg_height_frac / TEXT_GOOD_HEIGHT_FRAC)
    contrast_score = min(1.0, avg_contrast / TEXT_GOOD_CONTRAST)
    legibility = 100 * max(0.0, 0.5 * height_score + 0.5 * contrast_score - 0.4 * edge_frac)

    if legibility >= 70:
        verdict = "good"
        note = (f"Legible overlay text ({avg_height_frac * 100:.1f}% frame height, "
                f"contrast {avg_contrast:.0f}); found in {frames_with_text}/{len(frames)} sampled frames.")
    elif legibility >= 40:
        verdict = "warn"
        note = (f"Overlay text may be hard to read on mobile ({avg_height_frac * 100:.1f}% frame "
                f"height, contrast {avg_contrast:.0f}).")
    else:
        verdict = "bad"
        note = "Overlay text is small/low-contrast -- likely unreadable on mobile."
    if edge_frac > 0.3:
        note += " Some text sits near the frame edge -- check it isn't clipped by the vertical crop."
    return Metric("text_overlay", round(legibility, 1), verdict, note, TEXT_OVERLAY_SCALE)


# ----------------------------------------------------------------------------
# Layer 2: simulated viewer via local Ollama VLM (optional)
# ----------------------------------------------------------------------------
def sample_frames_b64(path, every_s=1.0, max_frames=8):
    import base64
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    dur = frames / fps if fps else 0
    times = np.arange(0, dur, every_s)[:max_frames]
    out = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        # downscale to keep the VLM fast
        h, w = frame.shape[:2]
        scale = 512 / max(h, w)
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            out.append((round(float(t), 2), base64.b64encode(buf).decode()))
    cap.release()
    return out


# Built-in defaults -- content-agnostic (this tool works on any vertical short,
# not just CS2). Override or extend via the --persona / --persona-set CLI
# flags, or the persona field in the desktop app; nothing here is hardcoded
# into the request schema itself.
DEFAULT_PERSONA = (
    "You are a Counter-Strike 2 fan scrolling YouTube Shorts. You know the "
    "game, the callouts, and what a good highlight looks like."
)
PERSONAS = {
    "cs2_fan": DEFAULT_PERSONA,
    "casual_scroller": (
        "You are a casual short-form video viewer with no particular interest in "
        "gaming or this content's niche, scrolling Shorts late at night. You "
        "have zero patience for a slow start and don't recognize any "
        "genre-specific terminology or on-screen jargon."
    ),
    "non_gamer": (
        "You have no background in this content's subject matter and don't "
        "recognize any of the on-screen UI, HUD, or overlays. You're scrolling "
        "Shorts and judging this purely as a short clip of unfamiliar action."
    ),
}

_VLM_INSTRUCTIONS = (
    " I will show you frames sampled ~1s apart from a vertical clip, in order. "
    "Judge it as a viewer, not an editor. Answer in strict JSON with keys: "
    "swipe_second (number or null: the second you'd swipe away, null if you'd "
    "watch to the end), reason (short), hook_reads (true if the first frame "
    "makes you want to keep watching), onscreen_ui_readable (true/false/na -- "
    "is any in-frame HUD, overlay, or kill-feed legible, if the clip has one "
    "at all), suggestions (array of <=3 short strings), "
    "hook_text (a punchy on-screen caption, <=8 words, to overlay on the "
    "opening frame(s) that would stop someone scrolling -- grounded in what's "
    "actually visible, not generic), "
    "sfx_suggestions (array of <=3 objects, each {at_s: number matching one of "
    "the given frame timestamps, moment: short description of what's happening "
    "there, sfx: a short suggested sound effect name like 'whoosh', 'record "
    "scratch', 'ding', or 'impact thud'} -- pick moments that would actually "
    "benefit from a sound cue, e.g. a kill, a big peek, or a whiff). "
    "JSON only, no prose."
)


def _vlm_payload(frames, persona_intro, model):
    labels = ", ".join(f"frame@{t}s" for t, _ in frames)
    return {
        "model": model,
        "prompt": persona_intro + _VLM_INSTRUCTIONS + f"\nFrames in order: {labels}.",
        "images": [b64 for _, b64 in frames],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.4},
    }


def _call_ollama(payload, host, model, timeout=180):
    import urllib.request
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode())
        raw = resp.get("response", "")
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": raw}
    except Exception as e:
        return {"error": f"Ollama call failed ({e}). Is `ollama serve` running "
                         f"and `{model}` pulled?"}


def run_vlm(path, model="qwen2.5vl:7b", host="http://localhost:11434", persona=None):
    """persona: optional custom persona description overriding the built-in default."""
    frames = sample_frames_b64(path)
    if not frames:
        return {"error": "no frames sampled"}
    payload = _vlm_payload(frames, persona or DEFAULT_PERSONA, model)
    return _call_ollama(payload, host, model)


def run_vlm_personas(path, personas=None, persona_keys=None, model="qwen2.5vl:7b", host="http://localhost:11434"):
    """Run the same sampled frames past several distinct viewer personas.

    personas: optional {name: description} dict, replacing the built-in PERSONAS
    (e.g. user-supplied personas from the CLI or desktop app). Falls back to
    the built-in defaults when omitted.
    """
    personas = personas or PERSONAS
    persona_keys = persona_keys or list(personas.keys())
    frames = sample_frames_b64(path)
    if not frames:
        return {"error": "no frames sampled"}
    results = {}
    for key in persona_keys:
        persona_intro = personas.get(key, DEFAULT_PERSONA)
        payload = _vlm_payload(frames, persona_intro, model)
        results[key] = _call_ollama(payload, host, model)
    return results


def summarize_personas(persona_results):
    """Aggregate per-persona VLM verdicts into one view: consensus + averages."""
    valid = {k: v for k, v in persona_results.items() if "error" not in v and "raw" not in v}
    if not valid:
        return {"error": "No persona responses parsed successfully."}
    swipe_seconds = [v.get("swipe_second") for v in valid.values()]
    watched_full = sum(1 for s in swipe_seconds if s is None)
    numeric_swipes = [s for s in swipe_seconds if isinstance(s, (int, float))]
    hook_votes = [bool(v.get("hook_reads")) for v in valid.values() if "hook_reads" in v]
    return {
        "personas_run": list(valid.keys()),
        "watched_to_end": f"{watched_full}/{len(valid)}",
        "avg_swipe_second": round(sum(numeric_swipes) / len(numeric_swipes), 1) if numeric_swipes else None,
        "hook_reads_consensus": (sum(hook_votes) >= len(hook_votes) / 2) if hook_votes else None,
    }


# ----------------------------------------------------------------------------
# Scoring + reporting
# ----------------------------------------------------------------------------
def score(metrics):
    w = {"good": 1.0, "warn": 0.5, "bad": 0.0}
    if not metrics:
        return 0.0
    return round(100 * sum(w[m.verdict] for m in metrics) / len(metrics), 1)


def to_report(path, use_ocr=False):
    fps, dur, w, h = probe(path)
    curve = energy_curve(path)
    hook = analyze_hook(curve)
    flat_metric, flat_runs = analyze_flatness(curve)
    pace_metric, cuts = analyze_pacing(path, dur)
    loud = analyze_loudness(path)
    retention_points = simulate_retention(curve, hook, flat_runs, cuts, dur)
    retention_metric = analyze_retention(retention_points)
    metrics = [hook, pace_metric, flat_metric, loud, retention_metric]
    if use_ocr:
        metrics.append(analyze_text_overlay(path))
    return Report(
        file=os.path.basename(path),
        duration_s=round(dur, 2),
        fps=round(fps, 2),
        resolution=f"{w}x{h}",
        is_vertical=h > w,
        metrics=[asdict(m) for m in metrics],
        energy_curve=curve,
        scene_cuts_s=cuts,
        flat_stretches=flat_runs,
        retention_curve=retention_points,
        overall_score=score(metrics),
    )


def format_vlm_notes(vlm_notes):
    """Turn the VLM's JSON response into human-readable lines."""
    if "error" in vlm_notes:
        return [f"Error: {vlm_notes['error']}"]
    if "raw" in vlm_notes:
        return [f"(unparsed response) {vlm_notes['raw']}"]

    lines = []
    swipe = vlm_notes.get("swipe_second")
    reason = vlm_notes.get("reason", "")
    if swipe is not None:
        lines.append(f"Would swipe away at ~{swipe}s ({reason})")
    else:
        lines.append(f"Would watch to the end ({reason})")
    if "hook_reads" in vlm_notes:
        lines.append(f"Hook reads: {'yes' if vlm_notes['hook_reads'] else 'no'}")
    if "onscreen_ui_readable" in vlm_notes:
        lines.append(f"On-screen UI/HUD readable: {vlm_notes['onscreen_ui_readable']}")
    if vlm_notes.get("hook_text"):
        lines.append(f'Suggested hook text: "{vlm_notes["hook_text"]}"')
    for s in vlm_notes.get("sfx_suggestions") or []:
        at = s.get("at_s", "?")
        moment = s.get("moment", "")
        sfx = s.get("sfx", "")
        lines.append(f"Suggested SFX @ {at}s: {sfx} ({moment})")
    for s in vlm_notes.get("suggestions") or []:
        lines.append(f"Suggestion: {s}")
    return lines


def print_report(rep: Report):
    icon = {"good": "OK ", "warn": "!! ", "bad": "XX "}
    print(f"\n=== Simulated Viewer Report: {rep.file} ===")
    print(f"{rep.resolution}  {rep.duration_s}s  {rep.fps}fps  "
          f"{'vertical' if rep.is_vertical else 'NOT VERTICAL (wrong aspect!)'}")
    print(f"Overall: {rep.overall_score}/100\n")
    for m in rep.metrics:
        print(f"  {icon[m['verdict']]}{m['name']:16} {m['value']:>8}   {m['note']}")
    if rep.flat_stretches:
        print("\n  Flat stretches (likely drop-off points):")
        for s, e in rep.flat_stretches:
            print(f"    - {s}s -> {e}s")
    if rep.persona_summary:
        print("\n  Simulated viewer panel (personas):")
        for key, notes in (rep.persona_notes or {}).items():
            print(f"    [{key}]")
            print("     ", json.dumps(notes, indent=2).replace("\n", "\n      "))
        s = rep.persona_summary
        if "error" not in s:
            print(f"    Summary: {s['watched_to_end']} watched to the end, "
                  f"avg swipe ~{s['avg_swipe_second']}s, "
                  f"hook reads consensus: {s['hook_reads_consensus']}")
        else:
            print(f"    {s['error']}")
    elif rep.vlm_notes:
        print("\n  Simulated viewer (VLM):")
        for line in format_vlm_notes(rep.vlm_notes):
            print(f"    - {line}")
    print()


def write_html(rep: Report, out_path):
    pts = rep.energy_curve or []
    maxt = pts[-1][0] if pts else 1
    W, H = 900, 260
    def x(t): return 40 + (t / maxt) * (W - 60) if maxt else 40
    def y(v): return H - 30 - v * (H - 60)
    def y_pct(v): return H - 30 - (v / 100) * (H - 60)
    poly = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in pts)
    retention_poly = " ".join(f"{x(t):.1f},{y_pct(v):.1f}" for t, v in rep.retention_curve or [])
    flat_rects = "".join(
        f'<rect x="{x(s):.1f}" y="20" width="{x(e)-x(s):.1f}" height="{H-50}" '
        f'fill="#ff4d4d" opacity="0.12"/>' for s, e in rep.flat_stretches)
    cut_lines = "".join(
        f'<line x1="{x(c):.1f}" y1="20" x2="{x(c):.1f}" y2="{H-30}" '
        f'stroke="#4da6ff" stroke-width="1" opacity="0.5"/>'
        for c in rep.scene_cuts_s)
    rows = "".join(
        f'<tr><td>{m["name"]}</td><td>{m["value"]}</td>'
        f'<td>{m.get("scale", "")}</td>'
        f'<td class="{m["verdict"]}">{m["verdict"].upper()}</td>'
        f'<td>{m["note"]}</td></tr>' for m in rep.metrics)
    if rep.persona_summary:
        persona_rows = "".join(
            f"<tr><td>{key}</td><td><ul>"
            + "".join(f"<li>{line}</li>" for line in format_vlm_notes(notes))
            + "</ul></td></tr>"
            for key, notes in (rep.persona_notes or {}).items())
        s = rep.persona_summary
        summary_line = (
            f"<p>{s['watched_to_end']} watched to the end · avg swipe ~{s['avg_swipe_second']}s · "
            f"hook reads consensus: {s['hook_reads_consensus']}</p>"
            if "error" not in s else f"<p>{s['error']}</p>"
        )
        vlm = (f"<table><tr><th>Persona</th><th>Response</th></tr>{persona_rows}</table>{summary_line}")
    elif rep.vlm_notes:
        vlm = "<ul>" + "".join(f"<li>{line}</li>" for line in format_vlm_notes(rep.vlm_notes)) + "</ul>"
    else:
        vlm = "<p><em>Layer 2 not run (use --vlm or --personas).</em></p>"
    html = f"""<!doctype html><meta charset=utf8>
<style>
body{{font-family:system-ui,Segoe UI,sans-serif;max-width:940px;margin:2rem auto;
color:#eee;background:#141414}}
h1{{font-size:1.3rem}} table{{border-collapse:collapse;width:100%;margin:1rem 0}}
td,th{{border:1px solid #333;padding:6px 10px;text-align:left;font-size:.9rem}}
.good{{color:#4ade80}}.warn{{color:#fbbf24}}.bad{{color:#f87171}}
.score{{font-size:2rem;font-weight:700}}
svg{{background:#1c1c1c;border-radius:8px}} pre{{background:#1c1c1c;padding:1rem;
border-radius:8px;overflow:auto}}
</style>
<h1>Simulated Viewer Report — {rep.file}</h1>
<p>{rep.resolution} · {rep.duration_s}s · {rep.fps}fps ·
{"vertical" if rep.is_vertical else "<span class=bad>NOT VERTICAL</span>"}</p>
<p class="score">{rep.overall_score}<span style="font-size:1rem">/100</span></p>
<svg viewBox="0 0 {W} {H}" width="100%">
{flat_rects}{cut_lines}
<polyline points="{poly}" fill="none" stroke="#4ade80" stroke-width="2"/>
<polyline points="{retention_poly}" fill="none" stroke="#f97316" stroke-width="2" stroke-dasharray="4 3"/>
<text x="40" y="15" fill="#888" font-size="11">motion energy (green) · predicted retention % (orange dashed)
(blue=cut, red=flat stretch)</text>
</svg>
<table><tr><th>Metric</th><th>Value</th><th>Range</th><th>Verdict</th><th>Note</th></tr>
{rows}</table>
<h2 style="font-size:1.05rem">{"Simulated viewer panel (personas)" if rep.persona_summary else "Simulated viewer"}</h2>{vlm}
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Simulated-viewer feedback for shorts.")
    ap.add_argument("video")
    ap.add_argument("--vlm", action="store_true", help="run local Ollama VLM viewer")
    ap.add_argument("--persona", metavar="TEXT",
                    help="custom persona description for --vlm, overriding the built-in "
                         "default (e.g. --persona \"You are a cooking-video fan...\")")
    ap.add_argument("--personas", action="store_true",
                    help="run multiple viewer personas via Ollama instead of a single pass "
                         "(implies --vlm)")
    ap.add_argument("--persona-set", metavar="NAME=TEXT", action="append",
                    help="add/override a persona for --personas mode, e.g. "
                         "--persona-set cooking_fan=\"You are a home cook scrolling Shorts...\" "
                         "(repeatable; replaces the built-in persona panel when given)")
    ap.add_argument("--model", default="qwen2.5vl:7b")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--ocr", action="store_true",
                    help="score caption/HUD text legibility (needs requirements-ocr.txt)")
    ap.add_argument("--html", metavar="PATH", help="write HTML report")
    ap.add_argument("--json", metavar="PATH", help="write raw JSON report")
    args = ap.parse_args()

    rep = to_report(args.video, use_ocr=args.ocr)
    if args.personas:
        custom_personas = {}
        for item in args.persona_set or []:
            if "=" in item:
                name, desc = item.split("=", 1)
                custom_personas[name.strip()] = desc.strip()
        personas = custom_personas or None
        rep.persona_notes = run_vlm_personas(args.video, personas=personas, model=args.model, host=args.host)
        rep.persona_summary = summarize_personas(rep.persona_notes)
    elif args.vlm:
        rep.vlm_notes = run_vlm(args.video, args.model, args.host, persona=args.persona)
    print_report(rep)
    if args.html:
        write_html(rep, args.html)
        print(f"HTML report -> {args.html}")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(asdict(rep), f, indent=2)
        print(f"JSON report -> {args.json}")


if __name__ == "__main__":
    main()
