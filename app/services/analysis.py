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
                         persona_text="", custom_personas=None, persona_count=3):
    """Runs only the AI-viewer/persona layer, independent of Layer 1 metrics."""

    def worker():
        try:
            if use_personas:
                personas = custom_personas or vs.generate_persona_pool(persona_count)
                persona_notes = vs.run_vlm_personas(video_path, personas=personas)
                result = {
                    "persona_notes": persona_notes,
                    "persona_summary": vs.summarize_personas(persona_notes),
                }
            else:
                result = {"vlm_notes": vs.run_vlm(video_path, persona=persona_text or None)}
        except Exception as e:
            traceback.print_exc()
            schedule(0, on_error, e)
            return
        schedule(0, on_done, result)

    threading.Thread(target=worker, daemon=True).start()
