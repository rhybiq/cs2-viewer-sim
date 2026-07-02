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

Usage:
    python viewer_sim.py clip.mp4
    python viewer_sim.py clip.mp4 --vlm                 # add local VLM viewer
    python viewer_sim.py clip.mp4 --vlm --model gemma3:12b
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


@dataclass
class Metric:
    name: str
    value: float
    verdict: str            # "good" | "warn" | "bad"
    note: str


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
    vlm_notes: Optional[dict] = None
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


def analyze_hook(curve):
    hook = [v for (t, v) in curve if t <= HOOK_WINDOW_S]
    rest = [v for (t, v) in curve if t > HOOK_WINDOW_S]
    if not hook:
        return Metric("hook_strength", 0.0, "bad", "No frames in hook window.")
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
    return Metric("hook_strength", round(hook_energy, 3), verdict, note)


def analyze_flatness(curve):
    if not curve:
        return Metric("flatness", 0.0, "bad", "No curve."), []
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
                      "No dead stretches — energy stays up throughout."), []
    total_flat = sum(e - s for s, e in flat_runs)
    verdict = "bad" if total_flat > 3 else "warn"
    note = f"{len(flat_runs)} flat stretch(es); viewers drop where nothing moves."
    return Metric("flatness", round(total_flat, 2), verdict, note), flat_runs


# ----------------------------------------------------------------------------
# Layer 1c: pacing via scene cuts
# ----------------------------------------------------------------------------
def analyze_pacing(path, duration):
    try:
        from scenedetect import detect, ContentDetector
        scenes = detect(path, ContentDetector())
        cuts = [round(s[0].get_seconds(), 2) for s in scenes][1:]  # drop t=0
    except Exception as e:
        return Metric("pacing", 0.0, "warn", f"Scene detect skipped: {e}"), []
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
    return Metric("pacing", round(cpm, 1), verdict, note), cuts


# ----------------------------------------------------------------------------
# Layer 1d: loudness (LUFS) via ffmpeg loudnorm
# ----------------------------------------------------------------------------
def analyze_loudness(path):
    cmd = ["ffmpeg", "-hide_banner", "-i", path,
           "-af", "loudnorm=print_format=json", "-f", "null", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        return Metric("loudness_lufs", 0.0, "warn", f"ffmpeg failed: {e}")
    txt = out.stderr
    start = txt.rfind("{")
    end = txt.rfind("}")
    if start == -1 or end == -1:
        return Metric("loudness_lufs", 0.0, "warn", "No audio / loudnorm output.")
    try:
        data = json.loads(txt[start:end + 1])
        lufs = float(data.get("input_i", 0.0))
    except Exception:
        return Metric("loudness_lufs", 0.0, "warn", "Could not parse loudness.")
    delta = lufs - TARGET_LUFS
    if abs(delta) <= LUFS_TOLERANCE:
        verdict, note = "good", f"On target ({lufs:.1f} LUFS)."
    elif delta < 0:
        verdict, note = "warn", f"{lufs:.1f} LUFS — quiet; will feel weak vs autoplay."
    else:
        verdict, note = "warn", f"{lufs:.1f} LUFS — hot; platforms will turn it down."
    return Metric("loudness_lufs", round(lufs, 1), verdict, note)


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


def run_vlm(path, model="qwen2.5vl:7b", host="http://localhost:11434"):
    import urllib.request
    frames = sample_frames_b64(path)
    if not frames:
        return {"error": "no frames sampled"}
    persona = (
        "You are a Counter-Strike 2 fan scrolling YouTube Shorts. I will show you "
        "frames sampled ~1s apart from a vertical clip, in order. Judge it as a "
        "viewer, not an editor. Answer in strict JSON with keys: "
        "swipe_second (number or null: the second you'd swipe away, null if you'd "
        "watch to the end), reason (short), hook_reads (true if the first frame "
        "makes you want to keep watching), killfeed_readable (true/false/na), "
        "suggestions (array of <=3 short strings). JSON only, no prose."
    )
    labels = ", ".join(f"frame@{t}s" for t, _ in frames)
    payload = {
        "model": model,
        "prompt": persona + f"\nFrames in order: {labels}.",
        "images": [b64 for _, b64 in frames],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.4},
    }
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            resp = json.loads(r.read().decode())
        raw = resp.get("response", "")
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": raw}
    except Exception as e:
        return {"error": f"Ollama call failed ({e}). Is `ollama serve` running "
                         f"and `{model}` pulled?"}


# ----------------------------------------------------------------------------
# Scoring + reporting
# ----------------------------------------------------------------------------
def score(metrics):
    w = {"good": 1.0, "warn": 0.5, "bad": 0.0}
    if not metrics:
        return 0.0
    return round(100 * sum(w[m.verdict] for m in metrics) / len(metrics), 1)


def to_report(path):
    fps, dur, w, h = probe(path)
    curve = energy_curve(path)
    hook = analyze_hook(curve)
    flat_metric, flat_runs = analyze_flatness(curve)
    pace_metric, cuts = analyze_pacing(path, dur)
    loud = analyze_loudness(path)
    metrics = [hook, pace_metric, flat_metric, loud]
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
        overall_score=score(metrics),
    )


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
    if rep.vlm_notes:
        print("\n  Simulated viewer (VLM):")
        print("   ", json.dumps(rep.vlm_notes, indent=2).replace("\n", "\n    "))
    print()


def write_html(rep: Report, out_path):
    pts = rep.energy_curve or []
    maxt = pts[-1][0] if pts else 1
    W, H = 900, 260
    def x(t): return 40 + (t / maxt) * (W - 60) if maxt else 40
    def y(v): return H - 30 - v * (H - 60)
    poly = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in pts)
    flat_rects = "".join(
        f'<rect x="{x(s):.1f}" y="20" width="{x(e)-x(s):.1f}" height="{H-50}" '
        f'fill="#ff4d4d" opacity="0.12"/>' for s, e in rep.flat_stretches)
    cut_lines = "".join(
        f'<line x1="{x(c):.1f}" y1="20" x2="{x(c):.1f}" y2="{H-30}" '
        f'stroke="#4da6ff" stroke-width="1" opacity="0.5"/>'
        for c in rep.scene_cuts_s)
    rows = "".join(
        f'<tr><td>{m["name"]}</td><td>{m["value"]}</td>'
        f'<td class="{m["verdict"]}">{m["verdict"].upper()}</td>'
        f'<td>{m["note"]}</td></tr>' for m in rep.metrics)
    vlm = (f"<pre>{json.dumps(rep.vlm_notes, indent=2)}</pre>"
           if rep.vlm_notes else "<p><em>Layer 2 not run (use --vlm).</em></p>")
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
<text x="40" y="15" fill="#888" font-size="11">motion energy over time
(blue=cut, red=flat stretch)</text>
</svg>
<table><tr><th>Metric</th><th>Value</th><th>Verdict</th><th>Note</th></tr>
{rows}</table>
<h2 style="font-size:1.05rem">Simulated viewer</h2>{vlm}
"""
    with open(out_path, "w") as f:
        f.write(html)


def main():
    ap = argparse.ArgumentParser(description="Simulated-viewer feedback for shorts.")
    ap.add_argument("video")
    ap.add_argument("--vlm", action="store_true", help="run local Ollama VLM viewer")
    ap.add_argument("--model", default="qwen2.5vl:7b")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--html", metavar="PATH", help="write HTML report")
    ap.add_argument("--json", metavar="PATH", help="write raw JSON report")
    args = ap.parse_args()

    rep = to_report(args.video)
    if args.vlm:
        rep.vlm_notes = run_vlm(args.video, args.model, args.host)
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
