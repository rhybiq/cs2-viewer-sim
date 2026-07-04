"""Runs viewer_sim analysis off the UI thread and delivers results back via a scheduler.

The Analyze tab (Layer 1 metrics) and the AI Viewer tab (Ollama personas) are
independent -- each has its own trigger and its own async runner below, so
one doesn't have to complete before the other can run.
"""

import threading
import traceback

import viewer_sim as vs


def run_async(video_path, use_ocr, on_done, on_error, schedule):
    """schedule is typically tk root.after -- keeps callbacks on the UI thread."""

    def worker():
        try:
            rep = vs.to_report(video_path, use_ocr=use_ocr)
        except Exception as e:
            traceback.print_exc()
            schedule(0, on_error, e)
            return
        schedule(0, on_done, rep)

    threading.Thread(target=worker, daemon=True).start()


def run_ai_viewer_async(video_path, use_personas, on_done, on_error, schedule,
                         persona_text="", custom_personas=None, persona_count=3,
                         sample_fps=None, existing_retention_curve=None,
                         use_captions=True, use_speech=True):
    """Runs only the AI-viewer/persona layer, independent of Layer 1 metrics.

    existing_retention_curve: pass Report.retention_curve if the Analyze tab
    already ran for this video, so swipe_second grounding doesn't recompute
    motion analysis that's already available. None (default) computes it fresh.
    use_captions/use_speech: include OCR captions / speech-to-text in the
    shared clip transcript (see viewer_sim.transcribe_clip()); both gracefully
    degrade if the relevant optional dependency isn't installed.
    """

    def worker():
        try:
            fps = sample_fps if sample_fps is not None else vs.VLM_DEFAULT_SAMPLE_FPS
            if use_personas:
                if custom_personas:
                    personas, patience_by_key = custom_personas, {}
                else:
                    personas, patience_by_key = vs.generate_persona_pool(persona_count)
                persona_notes = vs.run_vlm_personas(
                    video_path, personas=personas, sample_fps=fps,
                    patience_by_key=patience_by_key, retention_curve=existing_retention_curve,
                    use_captions=use_captions, use_speech=use_speech)
                result = {
                    "persona_notes": persona_notes,
                    "persona_summary": vs.summarize_personas(persona_notes),
                }
            else:
                result = {"vlm_notes": vs.run_vlm(video_path, persona=persona_text or None, sample_fps=fps,
                                                    retention_curve=existing_retention_curve,
                                                    use_captions=use_captions, use_speech=use_speech)}
        except Exception as e:
            traceback.print_exc()
            schedule(0, on_error, e)
            return
        schedule(0, on_done, result)

    threading.Thread(target=worker, daemon=True).start()
