"""Runs viewer_sim analysis off the UI thread and delivers results back via a scheduler."""

import threading
import traceback

import viewer_sim as vs


def run_async(video_path, use_vlm, on_done, on_error, schedule):
    """schedule is typically tk root.after -- keeps callbacks on the UI thread."""

    def worker():
        try:
            rep = vs.to_report(video_path)
            if use_vlm:
                rep.vlm_notes = vs.run_vlm(video_path)
        except Exception as e:
            traceback.print_exc()
            schedule(0, on_error, e)
            return
        schedule(0, on_done, rep)

    threading.Thread(target=worker, daemon=True).start()
