#!/usr/bin/env python3
"""
viewer_sim.py -- Simulated-viewer feedback for short-form gaming clips.

No chat-model subscription required. Two layers:

  Layer 1 (deterministic): objective retention signals computed locally with
           OpenCV / ffmpeg / PySceneDetect / pyloudnorm. Runs today, zero
           model download.

  Layer 2 (simulated viewer): OPTIONAL. Builds one shared text transcript of
           the clip per run (a dense VLM visual description, plus optional
           OCR captions and speech-to-text -- see transcribe_clip()), then
           judges it with a local LLM via Ollama (default: qwen2.5vl:7b) as a
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

# Persona panel (AI Viewer tab, up to 100 viewers)
PERSONA_MAX_CONCURRENT_CALLS = 4  # local Ollama inference is often GPU/CPU-bound
                                  # regardless of client concurrency -- bounded so a
                                  # 100-persona run doesn't open 100 connections at once

# AI Viewer frame sampling: default 1 frame/s, user-adjustable in the AI Viewer
# tab (denser sampling = the VLM sees more detail/motion, at the cost of a
# slower call -- how far to push it depends on the host machine). VLM_MAX_FRAMES
# is a hard ceiling regardless of the chosen fps, so a high fps on a long clip
# can't send an unbounded number of images in one Ollama call; sample_frames_b64's
# duration-adaptive spacing still spreads across the whole clip within that cap.
VLM_DEFAULT_SAMPLE_FPS = 1.0
VLM_MAX_FRAMES = 16

# Ollama call resilience: local Ollama can time out or crash its backend
# (e.g. a GPU-driver CUDA fault) mid-run, but it typically recovers -- either
# it was transiently slow, or it auto-respawns a crashed model runner on the
# next request. Fixed delay (not exponential backoff): that recovery is
# roughly constant-time, not the kind of transient network blip backoff is
# meant for.
OLLAMA_MAX_RETRIES = 10
OLLAMA_RETRY_DELAY_S = 4.0

# One-time clip transcription (see transcribe_clip()): computed once per clip
# instead of re-sending frames to every persona call, since Ollama has no
# cross-call vision-embedding cache. TRANSCRIPTION_MAX_FRAMES/NUM_CTX are
# sized together, not independently -- and NOT from estimated math: measured
# directly against a real clip via Ollama's own prompt_eval_count, 22 frames
# + prompt cost 12,224 tokens (~555 tokens/frame at the ~512px downscale
# sample_frames_b64 uses), against a 12288-token num_ctx -- leaving only 64
# tokens for the actual description and forcing an immediate done_reason
# "length" cutoff mid-sentence. 24 frames x ~555 + prompt (~300) + a real
# output budget (see TRANSCRIPTION_NUM_PREDICT) needs roughly 13,900-16,000
# tokens; 20480 leaves comfortable headroom without being reckless. A bigger
# num_ctx grows Ollama's KV-cache VRAM use -- on a 12GB GPU already running
# the ~6GB model weights, that's a real stability tradeoff (a live CUDA
# crash was observed earlier this session), so this isn't pushed further
# than the measured requirement.
TRANSCRIPTION_MAX_FRAMES = 24
TRANSCRIPTION_TIMEOUT_S = 600   # this one call sends far more frames than a per-persona call did
TRANSCRIPTION_NUM_CTX = 20480   # must be set explicitly -- Ollama's default context is much smaller
TRANSCRIPTION_NUM_PREDICT = 1024  # must also be set explicitly -- Ollama's own default output cap
                                   # is small enough (observed: cut off after ~90 words, mid-thought,
                                   # no natural conclusion) to silently truncate a real narrated
                                   # description long before it's actually done
STT_MODEL_SIZE = "large-v3-turbo"  # faster-whisper model size -- GPU by choice (see
                                     # transcribe_audio's own rationale/fallback for the tradeoff)
STT_SAMPLE_RATE = 16000


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


def compute_retention_curve(path):
    """Real motion-based retention curve for callers that don't need a full
    to_report() -- lets the AI Viewer ground swipe_second in physics data
    without depending on Layer 1 having run. [] for unreadable/zero-duration clips.
    """
    _, dur, _, _ = probe(path)
    curve = energy_curve(path)
    hook = analyze_hook(curve)
    _, flat_runs = analyze_flatness(curve)
    _, cuts = analyze_pacing(path, dur)
    return simulate_retention(curve, hook, flat_runs, cuts, dur)


# ----------------------------------------------------------------------------
# Layer 1f: text overlay quality -- captions + in-game HUD/kill-feed legibility
# (optional, --ocr: needs `pip install -r requirements-ocr.txt`)
# ----------------------------------------------------------------------------
TEXT_OVERLAY_SCALE = (
    "0-100 legibility (size + contrast, minus edge-clip risk) · good >=70 · "
    "warn >=40 · bad <40 (no text found scores warn -- may be intentional)"
)


def _sample_frames_bgr(path, every_s=TEXT_SAMPLE_EVERY_S, max_frames=TEXT_MAX_SAMPLES):
    # sibling: _sample_frames_bgr_timed (below) returns (t, frame) pairs for callers that need timestamps
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


def _sample_frames_bgr_timed(path, every_s=TEXT_SAMPLE_EVERY_S, max_frames=TEXT_MAX_SAMPLES):
    # sibling of _sample_frames_bgr (above); returns (t, frame) pairs instead of bare frames
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    dur = frame_count / fps if fps else 0.0
    frames = []
    for t in np.arange(0, dur, every_s)[:max_frames]:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
        ok, frame = cap.read()
        if ok:
            frames.append((float(t), frame))
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
# Layer 2a: shared clip transcription -- computed once per clip, then reused
# across every persona call. Ollama has no cross-call vision-embedding
# cache, so re-sending the same frames to every one of up to 100 persona
# calls was paying the (expensive) vision-encoding cost up to 100x for
# identical input. Combines a one-time dense VLM visual description with
# OCR captions and (optional) speech-to-text into one text transcript, fed
# to every persona as plain text from then on -- no images after this point.
# ----------------------------------------------------------------------------
def extract_captions(path, every_s=TEXT_SAMPLE_EVERY_S, max_frames=TRANSCRIPTION_MAX_FRAMES):
    """On-screen text/captions across the whole clip, timestamped -- reuses
    analyze_text_overlay's OCR approach but keeps the recognized text itself
    (for the transcript) instead of scoring legibility. [] if EasyOCR isn't
    installed or nothing is found.
    """
    try:
        import easyocr
    except ImportError:
        return []

    frames = _sample_frames_bgr_timed(path, every_s=every_s, max_frames=max_frames)
    if not frames:
        return []
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    out = []
    for t, frame in frames:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        hits = [
            text.strip() for _bbox, text, conf in reader.readtext(rgb)
            if conf >= TEXT_MIN_CONFIDENCE and text.strip()
        ]
        if hits:
            out.append((round(t, 2), " ".join(hits)))
    return out


def transcribe_audio(path):
    """Whisper transcription of the clip's spoken audio, timestamped by
    segment. GPU by choice (large-v3-turbo needs ~6GB VRAM -- roughly as
    much as Ollama's own vision-model weights, on the same card, so this is
    a real, knowingly-accepted contention risk, not an oversight). Falls
    back to a CPU attempt if the GPU load/transcribe fails (e.g. a CUDA OOM
    from that exact contention) rather than losing speech content entirely.
    [] if faster-whisper isn't installed or the clip has no audio stream.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return []

    ffmpeg_path = ffmpeg_bin()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()  # Windows: ffmpeg can't write to a file this process still holds open
    try:
        cmd = [ffmpeg_path, "-hide_banner", "-nostdin", "-y", "-i", path,
               "-vn", "-ar", str(STT_SAMPLE_RATE), "-ac", "1", "-f", "wav", tmp.name]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                             stdin=subprocess.DEVNULL, creationflags=_ffmpeg_no_window_flags())
        if "Stream" not in out.stderr or "Audio:" not in out.stderr:
            return []  # no audio stream -- same check analyze_loudness uses
        try:
            model = WhisperModel(STT_MODEL_SIZE, device="cuda", compute_type="float16")
            segments, _info = model.transcribe(tmp.name)
            return [(round(seg.start, 2), round(seg.end, 2), seg.text.strip())
                    for seg in segments if seg.text.strip()]
        except Exception as e:
            print(f"[transcribe_audio] GPU load/transcribe failed ({e}), retrying on CPU", file=sys.stderr)
            model = WhisperModel(STT_MODEL_SIZE, device="cpu", compute_type="int8")
            segments, _info = model.transcribe(tmp.name)
            return [(round(seg.start, 2), round(seg.end, 2), seg.text.strip())
                    for seg in segments if seg.text.strip()]
    except Exception:
        return []
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _transcription_instructions(is_vertical):
    # Told truthfully: this pipeline also runs on raw, not-yet-edited
    # horizontal gameplay, not just finished vertical shorts -- claiming
    # "vertical clip" unconditionally would be false and could skew the
    # description.
    clip_desc = "a vertical short-form clip" if is_vertical else "a horizontal (not yet edited into a short) clip"
    return (
        f" I will show you frames sampled across {clip_desc}, in order. "
        "Write a narrated account of what happens, in the order it happens -- "
        "tell the story of the gameplay, don't just list dry, disconnected "
        "observations. If you can identify the game being played and the "
        "map/location, say so explicitly up front. Call out specific events "
        "(kills, deaths, objectives completed, near-misses, big plays, scene "
        "changes) with roughly when they happen (e.g. 'around 3s, ...'). "
        "This is the only thing other viewers will judge the clip from -- "
        "they will not see the actual video, only what you write -- so be "
        "thorough and concrete about what's actually visible: on-screen "
        "action, any HUD/overlay/kill-feed content you can read, and "
        "anything notable about pacing or composition. Plain prose, no "
        "JSON, no commentary about being an AI."
    )


def _transcription_payload(frames, model, is_vertical=True):
    labels = ", ".join(f"frame@{t}s" for t, _ in frames)
    return {
        "model": model,
        "prompt": _transcription_instructions(is_vertical) + f"\nFrames in order: {labels}.",
        "images": [b64 for _, b64 in frames],
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": TRANSCRIPTION_NUM_CTX,
            "num_predict": TRANSCRIPTION_NUM_PREDICT,
        },
    }


def describe_clip_visually(path, sample_fps=VLM_DEFAULT_SAMPLE_FPS, model="qwen2.5vl:7b",
                            host="http://localhost:11434", is_vertical=True):
    frames = sample_frames_b64(path, every_s=1.0 / sample_fps, max_frames=TRANSCRIPTION_MAX_FRAMES)
    if not frames:
        return ""
    payload = _transcription_payload(frames, model, is_vertical=is_vertical)
    resp = _call_ollama(payload, host, model, timeout=TRANSCRIPTION_TIMEOUT_S)
    if isinstance(resp, dict):
        if "error" in resp:
            # Never feed the error text itself into the transcript as if it
            # were real content -- personas can't tell it apart from an
            # actual description of the clip, and will (inconsistently)
            # treat "the transcript contains an error" as a fact about the
            # clip itself. format_transcript() omits an empty visual section
            # entirely, so callers just fall back to OCR/speech alone if
            # those succeeded. Still print so the failure isn't invisible.
            print(f"[transcribe_clip] visual description failed: {resp['error']}", file=sys.stderr)
            return ""
        if "raw" in resp:
            return resp["raw"]
        return json.dumps(resp)
    return str(resp)


def format_transcript(captions, speech, visual):
    """Combines the visual description, OCR captions, and speech transcript
    into one text block, omitting any section that came back empty rather
    than printing an empty header for it.
    """
    sections = []
    if visual:
        sections.append("Visual description of the clip:\n" + visual)
    if captions:
        cap_lines = "\n".join(f"  {t}s: {text}" for t, text in captions)
        sections.append("On-screen text/captions detected (OCR, may contain errors):\n" + cap_lines)
    if speech:
        speech_lines = "\n".join(f"  {s}-{e}s: {text}" for s, e, text in speech)
        sections.append("Spoken audio, transcribed (may contain errors):\n" + speech_lines)
    return "\n\n".join(sections)


def transcribe_clip(path, sample_fps=VLM_DEFAULT_SAMPLE_FPS, model="qwen2.5vl:7b",
                     host="http://localhost:11434", use_captions=True, use_speech=True):
    """One-time, shared transcription of a clip -- see the Layer 2a comment
    above for why this replaced per-persona frame sending. use_captions/
    use_speech gracefully degrade to skipped (not an error) if the relevant
    optional dependency isn't installed.
    """
    _, _, w, h = probe(path)
    visual = describe_clip_visually(path, sample_fps=sample_fps, model=model, host=host, is_vertical=h > w)
    captions = extract_captions(path) if use_captions else []
    speech = transcribe_audio(path) if use_speech else []
    return format_transcript(captions, speech, visual)


# ----------------------------------------------------------------------------
# Layer 2: simulated viewer via local Ollama VLM (optional)
# ----------------------------------------------------------------------------
def sample_frames_b64(path, every_s=1.0, max_frames=8):
    """Samples up to max_frames stills for the VLM. If the clip is longer than
    max_frames * every_s, spaces samples evenly across the *whole* duration
    instead of only ever covering the opening seconds -- otherwise a viewer
    persona is judging an N-second trailer of the clip, not the clip, and
    "would watch to the end" is meaningless since it never saw the rest.
    """
    import base64
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    dur = frames / fps if fps else 0
    if dur > max_frames * every_s:
        every_s = dur / max_frames
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

# Trait dimensions for generating a larger, varied pool of social-media viewer
# personas on demand (--persona-count / the desktop app's viewer-count field),
# rather than hand-authoring each one. 4 x 3 x 3 x 3 = 108 distinct combinations.
_PERSONA_TRAIT_DIMENSIONS = [
    [
        "deeply familiar with this content's genre and its jargon, callouts, and conventions",
        "a casual fan of this content's genre who follows it sometimes but not closely",
        "someone who enjoys this general category of content but doesn't know this specific niche",
        "someone with no background in this content's subject matter who doesn't recognize any on-screen UI, HUD, or overlays",
    ],
    [
        "extremely impatient, swiping away within 1-2 seconds if nothing grabs them immediately",
        "moderately patient, giving a clip a few seconds before deciding whether to keep watching",
        "a patient completionist who tends to watch clips through to the end out of habit",
    ],
    [
        "scrolling TikTok during a commute",
        "scrolling YouTube Shorts late at night",
        "scrolling Instagram Reels on a lunch break",
    ],
    [
        "bored and actively looking for something to snap their attention",
        "specifically hunting for content like this",
        "half-distracted, only half paying attention to the screen while doing something else",
    ],
]


_PATIENCE_BUCKETS = ["impatient", "moderate", "patient"]  # aligned to _PERSONA_TRAIT_DIMENSIONS[1] order


def generate_persona_pool(n, seed=42):
    """A pool of up to len(all combinations) distinct viewer personas, built by
    combining independent traits (game familiarity, attention span, platform
    habit, mood) rather than hand-authoring each one. Deterministic for a given
    seed so re-running with the same count is reproducible.

    Returns (personas, patience_by_key): personas is {key: description_text} as
    before; patience_by_key is {key: "impatient"|"moderate"|"patient"}, derived
    from which attention-span trait (dimension 1) produced each persona, so
    derive_swipe_second() can ground swipe timing in each persona's actual
    stated patience rather than asking the VLM to invent a number.
    """
    import itertools
    import random

    combos = list(itertools.product(*_PERSONA_TRAIT_DIMENSIONS))
    random.Random(seed).shuffle(combos)
    n = max(1, min(n, len(combos)))
    personas, patience_by_key = {}, {}
    for i, combo in enumerate(combos[:n]):
        key = f"viewer_{i + 1}"
        personas[key] = "You are " + ", ".join(combo) + "."
        patience_by_key[key] = _PATIENCE_BUCKETS[_PERSONA_TRAIT_DIMENSIONS[1].index(combo[1])]
    return personas, patience_by_key


# Curve-relative (not fixed-percentage) swipe-point thresholds: each persona's
# threshold is a fraction of THIS clip's own total predicted churn, so
# patience buckets differentiate consistently regardless of a given clip's
# length/quality, rather than everyone converging on "watch to the end" for
# any clip that isn't badly flat.
PERSONA_PATIENCE_CHURN_FRACTIONS = {"impatient": 0.25, "moderate": 0.65, "patient": 0.95}
HOOK_FAIL_FRACTION_PENALTY = 0.15  # bail earlier (as a fraction of the clip's own churn) when hook_reads is false


def _as_bool(value):
    """Ollama's format=json should yield real JSON booleans, but coerce
    defensively -- bool("false") is True in Python, which would silently
    defeat the exact hook_reads/swipe_second consistency this exists to fix.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "no", "0", "")
    return bool(value)


def derive_swipe_second(retention_curve, patience="moderate", hook_reads=True):
    """Where this persona would swipe away, derived from the clip's own real
    retention curve (simulate_retention) rather than asked of the VLM -- a 7B
    model reliably judges yes/no on hook_reads, not a precise timestamp.
    Threshold is relative to THIS clip's own total predicted churn (not a
    fixed retention percentage), so patience buckets differentiate
    consistently regardless of clip length/quality. Two distinct hook
    signals coexist by design: analyze_hook() is Layer 1's objective,
    motion-only verdict baked into the shared curve; hook_reads here is each
    persona's subjective VLM judgment, which nudges that persona's own
    threshold via HOOK_FAIL_FRACTION_PENALTY. They can legitimately disagree.
    """
    if not retention_curve:
        return None
    start_retention = retention_curve[0][1]
    end_retention = retention_curve[-1][1]
    total_churn = start_retention - end_retention
    if total_churn <= 0:
        return None  # retention never drops -- no one swipes

    frac = PERSONA_PATIENCE_CHURN_FRACTIONS.get(patience, PERSONA_PATIENCE_CHURN_FRACTIONS["moderate"])
    if not _as_bool(hook_reads):
        frac = max(frac - HOOK_FAIL_FRACTION_PENALTY, 0.05)
    target_retention = start_retention - total_churn * frac

    for t, pct in retention_curve:
        if pct <= target_retention:
            return t
    return None


def _persona_instructions():
    # The persona judges a text transcript (see transcribe_clip()) instead
    # of being shown frames directly.
    return (
        " I will give you a transcript describing a short-form clip (a "
        "visual description, plus any on-screen captions and any spoken "
        "audio that were detected) instead of showing you the frames "
        "directly. Judge it as a viewer would, based only on this "
        "transcript. Answer in strict JSON with keys: "
        "reason (short), hook_reads (true if the opening described "
        "makes you want to keep watching), onscreen_ui_readable (true/false/na -- "
        "does the transcript suggest any in-frame HUD, overlay, or kill-feed is "
        "legible, if the clip has one at all), suggestions (array of <=3 short "
        "strings), "
        "hook_text (a punchy on-screen caption, <=8 words, to overlay on the "
        "opening moment described that would stop someone scrolling -- grounded "
        "in what's actually described, not generic), "
        "sfx_suggestions (array of <=3 objects, each {at_s: number -- an "
        "approximate moment mentioned in the transcript, doesn't need to be "
        "exact, moment: short description of what's happening there, sfx: a "
        "short (1-4 word) sound effect name you invent specifically for that "
        "exact moment -- it should sound different for a headshot than for a "
        "footstep or a big miss; don't default to the same generic effect "
        "for every suggestion} -- pick moments that would actually benefit "
        "from a sound cue, e.g. a kill, a big peek, or a whiff). "
        "JSON only, no prose."
    )


def _persona_text_payload(transcript, persona_intro, model):
    return {
        "model": model,
        "prompt": persona_intro + _persona_instructions() + f"\nTranscript:\n{transcript}",
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.4},
    }


def _call_ollama(payload, host, model, timeout=180):
    """Up to OLLAMA_MAX_RETRIES attempts, OLLAMA_RETRY_DELAY_S apart, on any
    failure (timeout, connection error, HTTP error, backend crash) -- local
    Ollama recovery from any of those is roughly constant-time (a transient
    slowdown, or auto-respawning a crashed model runner on the next request),
    so a fixed delay suits it better than exponential backoff. Returns the
    last error dict if every attempt fails, same shape as a single failed
    call always returned.
    """
    import time
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode()
    last_error = {"error": "Ollama call never attempted"}
    for attempt in range(1, OLLAMA_MAX_RETRIES + 1):
        req = urllib.request.Request(
            f"{host}/api/generate", data=data,
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
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode()[:500]
            except Exception:
                body = "(no response body)"
            last_error = {"error": f"Ollama call failed (HTTP {e.code}: {e.reason}). Server said: {body}"}
        except Exception as e:
            last_error = {"error": f"Ollama call failed ({e}). Is `ollama serve` running "
                                   f"and `{model}` pulled?"}
        if attempt < OLLAMA_MAX_RETRIES:
            time.sleep(OLLAMA_RETRY_DELAY_S)
    return last_error


def run_vlm(path, model="qwen2.5vl:7b", host="http://localhost:11434", persona=None,
            sample_fps=VLM_DEFAULT_SAMPLE_FPS, retention_curve=None,
            use_captions=True, use_speech=True):
    """persona: optional custom persona description overriding the built-in default.
    sample_fps: frames/sec sampled for the one-time transcription pass (see
    transcribe_clip()) -- higher sees more detail/motion at the cost of a
    slower one-time call; capped by TRANSCRIPTION_MAX_FRAMES regardless.
    retention_curve: pass an already-computed curve (e.g. from to_report()'s
    Report.retention_curve) to skip recomputing it; None computes it here.
    use_captions/use_speech: include OCR captions / speech-to-text in the
    shared transcript; both gracefully degrade to skipped if the relevant
    optional dependency isn't installed.
    swipe_second is derived from this curve, not asked of the model -- see
    derive_swipe_second(). Single/custom personas have no structured patience
    trait, so this always uses the "moderate" bucket.
    """
    transcript = transcribe_clip(path, sample_fps=sample_fps, model=model, host=host,
                                  use_captions=use_captions, use_speech=use_speech)
    if not transcript:
        return {"error": "could not transcribe clip"}
    payload = _persona_text_payload(transcript, persona or DEFAULT_PERSONA, model)
    resp = _call_ollama(payload, host, model)
    if isinstance(resp, dict) and "error" not in resp and "raw" not in resp:
        curve = retention_curve if retention_curve is not None else compute_retention_curve(path)
        resp["swipe_second"] = derive_swipe_second(curve, "moderate", resp.get("hook_reads", True))
    return resp


def run_vlm_personas(path, personas=None, persona_keys=None, model="qwen2.5vl:7b", host="http://localhost:11434",
                      sample_fps=VLM_DEFAULT_SAMPLE_FPS, patience_by_key=None, retention_curve=None,
                      use_captions=True, use_speech=True):
    """Run the same shared clip transcript (see transcribe_clip()) past
    several distinct viewer personas as independent text-only calls, up to
    PERSONA_MAX_CONCURRENT_CALLS at a time -- these are I/O-bound HTTP calls
    to a local server, so a thread pool overlaps their network/queue wait
    time instead of running strictly one-at-a-time. The transcript is
    computed once for the whole panel, not per persona: Ollama has no
    cross-call vision-embedding cache, so re-sending frames to every one of
    up to 100 persona calls was paying the (expensive) vision-encoding cost
    up to 100x for identical input -- one shared text transcript up front,
    then text-only per-persona calls, avoids that entirely.

    personas: optional {name: description} dict, replacing the built-in PERSONAS
    (e.g. user-supplied personas from the CLI or desktop app). Falls back to
    the built-in defaults when omitted.
    sample_fps: frames/sec sampled for the one-time transcription pass --
    higher sees more detail/motion at the cost of a slower one-time call;
    capped by TRANSCRIPTION_MAX_FRAMES regardless.
    patience_by_key: optional {name: "impatient"|"moderate"|"patient"} (from
    generate_persona_pool()) used to ground each persona's swipe_second in the
    clip's real retention curve rather than asking the model to invent a
    number -- see derive_swipe_second(). Personas missing from this dict (e.g.
    custom/CLI --persona-set personas with no structured trait data) default
    to "moderate".
    retention_curve: pass an already-computed curve (e.g. from to_report()'s
    Report.retention_curve) to skip recomputing it; None computes it here.
    use_captions/use_speech: include OCR captions / speech-to-text in the
    shared transcript; both gracefully degrade to skipped if the relevant
    optional dependency isn't installed.
    """
    import concurrent.futures

    personas = personas or PERSONAS
    persona_keys = persona_keys or list(personas.keys())
    transcript = transcribe_clip(path, sample_fps=sample_fps, model=model, host=host,
                                  use_captions=use_captions, use_speech=use_speech)
    if not transcript:
        return {key: {"error": "could not transcribe clip"} for key in persona_keys}
    curve = retention_curve if retention_curve is not None else compute_retention_curve(path)
    patience_by_key = patience_by_key or {}

    def _run_one(key):
        persona_intro = personas.get(key, DEFAULT_PERSONA)
        payload = _persona_text_payload(transcript, persona_intro, model)
        resp = _call_ollama(payload, host, model)
        if isinstance(resp, dict) and "error" not in resp and "raw" not in resp:
            resp["swipe_second"] = derive_swipe_second(
                curve, patience_by_key.get(key, "moderate"), resp.get("hook_reads", True))
        return key, resp

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=PERSONA_MAX_CONCURRENT_CALLS) as executor:
        for key, result in executor.map(_run_one, persona_keys):
            results[key] = result
    return results


SFX_CLUSTER_TOLERANCE_S = 2.0  # sfx suggestions within this many seconds of each other are
                                # treated as the same moment when building consensus -- at_s is
                                # an approximate moment reference (not an exact frame match), so
                                # different personas will naturally land a second or two apart
                                # when describing what's really the same event


def _cluster_sfx_suggestions(persona_results, tolerance_s=SFX_CLUSTER_TOLERANCE_S):
    """Groups sfx_suggestions across personas into per-moment clusters -- e.g.
    if several personas independently flag the same ~13s moment as worth a
    sound cue, surface that as one moment listing all the distinct names
    they suggested, instead of 30+ raw, unaggregated per-persona lines.
    Deliberately doesn't force a single "winning" name: personas are asked
    to invent a name specific to each moment (see _persona_instructions()),
    so exact-string agreement across personas is rare by design -- the real
    signal is "multiple personas independently thought this moment needed a
    sound," not "they all typed the same word."
    """
    valid = {k: v for k, v in persona_results.items() if "error" not in v and "raw" not in v}
    entries = []
    for key, v in valid.items():
        for s in v.get("sfx_suggestions") or []:
            if not isinstance(s, dict):
                continue  # the model occasionally returns a bare string instead of the asked-for object
            at_s = s.get("at_s")
            sfx = (s.get("sfx") or "").strip()
            if isinstance(at_s, (int, float)) and sfx:
                entries.append((float(at_s), sfx, key))
    if not entries:
        return []
    entries.sort(key=lambda e: e[0])

    clusters = [[entries[0]]]
    for at_s, sfx, key in entries[1:]:
        if at_s - clusters[-1][-1][0] <= tolerance_s:
            clusters[-1].append((at_s, sfx, key))
        else:
            clusters.append([(at_s, sfx, key)])

    result = []
    for cluster in clusters:
        names = []
        for _, sfx, _key in cluster:
            if sfx.lower() not in (n.lower() for n in names):
                names.append(sfx)
        # "total" is distinct personas involved, not raw entry count -- a
        # single persona can suggest several moments that land in the same
        # cluster (e.g. 3 quick suggestions within one 2s window), and that
        # must not be miscounted as 3 separate personas agreeing.
        persona_count = len({key for _, _, key in cluster})
        avg_at = sum(at for at, _, _ in cluster) / len(cluster)
        result.append({
            "at_s": round(avg_at, 1),
            "names": names,
            "total": persona_count,
        })
    return result


def summarize_personas(persona_results):
    """Aggregate per-persona VLM verdicts into one view: consensus + averages."""
    valid = {k: v for k, v in persona_results.items() if "error" not in v and "raw" not in v}
    if not valid:
        return {"error": "No persona responses parsed successfully."}
    swipe_seconds = [v.get("swipe_second") for v in valid.values()]
    watched_full = sum(1 for s in swipe_seconds if s is None)
    numeric_swipes = [s for s in swipe_seconds if isinstance(s, (int, float))]
    hook_votes = [_as_bool(v.get("hook_reads")) for v in valid.values() if "hook_reads" in v]
    return {
        "personas_run": list(valid.keys()),
        "watched_to_end": f"{watched_full}/{len(valid)}",
        "avg_swipe_second": round(sum(numeric_swipes) / len(numeric_swipes), 1) if numeric_swipes else None,
        "hook_reads_consensus": (sum(hook_votes) >= len(hook_votes) / 2) if hook_votes else None,
        "sfx_consensus": _cluster_sfx_suggestions(persona_results),
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
        if not isinstance(s, dict):
            continue  # the model occasionally returns a bare string instead of the asked-for object
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
            for sfx in s.get("sfx_consensus") or []:
                names = ", ".join(sfx["names"])
                n = sfx["total"]
                print(f"    Suggested SFX @ {sfx['at_s']}s: {names} "
                      f"({n} persona{'s' if n != 1 else ''} flagged this moment)")
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
        if "error" not in s:
            sfx_lines = "".join(
                f"<li>Suggested SFX @ {sfx['at_s']}s: {', '.join(sfx['names'])} "
                f"({sfx['total']} persona{'s' if sfx['total'] != 1 else ''} flagged this moment)</li>"
                for sfx in s.get("sfx_consensus") or []
            )
            summary_line = (
                f"<p>{s['watched_to_end']} watched to the end · avg swipe ~{s['avg_swipe_second']}s · "
                f"hook reads consensus: {s['hook_reads_consensus']}</p>"
                + (f"<ul>{sfx_lines}</ul>" if sfx_lines else "")
            )
        else:
            summary_line = f"<p>{s['error']}</p>"
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
        rep.persona_notes = run_vlm_personas(args.video, personas=personas, model=args.model, host=args.host,
                                              retention_curve=rep.retention_curve)
        rep.persona_summary = summarize_personas(rep.persona_notes)
    elif args.vlm:
        rep.vlm_notes = run_vlm(args.video, args.model, args.host, persona=args.persona,
                                 retention_curve=rep.retention_curve)
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
