"""Runs viewer_sim analysis off the UI thread and delivers results back via a scheduler."""

import threading
import traceback

import viewer_sim as vs


def run_async(video_path, use_vlm, use_ocr, use_personas, on_done, on_error, schedule,
              persona_text="", custom_personas=None):
    """schedule is typically tk root.after -- keeps callbacks on the UI thread."""

    def worker():
        try:
            rep = vs.to_report(video_path, use_ocr=use_ocr)
            if use_personas:
                rep.persona_notes = vs.run_vlm_personas(video_path, personas=custom_personas)
                rep.persona_summary = vs.summarize_personas(rep.persona_notes)
            elif use_vlm:
                rep.vlm_notes = vs.run_vlm(video_path, persona=persona_text or None)
        except Exception as e:
            traceback.print_exc()
            schedule(0, on_error, e)
            return
        schedule(0, on_done, rep)

    threading.Thread(target=worker, daemon=True).start()
