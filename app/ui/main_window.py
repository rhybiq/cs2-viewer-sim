"""Top-level window: wires the picker, options, action bar, results, and report actions together."""

import threading
from tkinter import BOTH, X, Label, StringVar, messagebox

from app.services import analysis, ocr, ollama
from app.ui.action_bar import ActionBar
from app.ui.options_panel import OptionsPanel
from app.ui.report_actions import ReportActions
from app.ui.results_table import ResultsTable
from app.ui.video_picker import VideoPicker


class MainWindow:
    def __init__(self, root):
        self.root = root
        self.video_path = None
        self.report = None

        root.title("CS2 Viewer Sim")
        root.geometry("900x600")
        root.minsize(760, 480)

        self.picker = VideoPicker(root, on_pick=self._on_video_picked)
        self.picker.pack(fill=X)

        self.options = OptionsPanel(root)
        self.options.pack(fill=X)

        self.action_bar = ActionBar(root, on_analyze=self._start_analysis)
        self.action_bar.pack(fill=X)

        self.score_var = StringVar(value="")
        Label(root, textvariable=self.score_var, font=("Segoe UI", 22, "bold")).pack(pady=(4, 0))

        self.results = ResultsTable(root)
        self.results.pack(fill=BOTH, expand=True)

        self.report_actions = ReportActions(root)
        self.report_actions.pack(fill=X)

        self._check_ollama()
        self._check_ocr()

    def _check_ollama(self):
        def worker():
            available = ollama.is_available()
            self.root.after(0, self.options.set_ollama_status, available)

        threading.Thread(target=worker, daemon=True).start()

    def _check_ocr(self):
        def worker():
            available = ocr.is_available()
            self.root.after(0, self.options.set_ocr_status, available)

        threading.Thread(target=worker, daemon=True).start()

    def _on_video_picked(self, path):
        self.video_path = path
        self.action_bar.set_ready(True)

    def _start_analysis(self):
        if not self.video_path:
            return
        self.action_bar.start_busy()
        self.report_actions.set_report(None)
        self.results.clear()
        self.score_var.set("")

        analysis.run_async(
            self.video_path, self.options.use_vlm, self.options.use_ocr,
            on_done=self._analysis_done,
            on_error=self._analysis_failed,
            schedule=self.root.after,
        )

    def _analysis_done(self, rep):
        self.report = rep
        self.action_bar.stop_busy("Done.")
        self.report_actions.set_report(rep)
        self.score_var.set(f"{rep.overall_score}/100")
        self.results.load_report(rep)
        vertical_note = "vertical" if rep.is_vertical else "NOT VERTICAL"
        self.picker.set_label(f"{rep.file}  ({rep.resolution}, {rep.duration_s}s, {vertical_note})")
        if rep.vlm_notes and "error" in rep.vlm_notes:
            messagebox.showwarning("AI viewer", rep.vlm_notes["error"])

    def _analysis_failed(self, exc):
        self.action_bar.stop_busy("Failed.")
        messagebox.showerror("Analysis failed", str(exc))
