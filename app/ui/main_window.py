"""Top-level window: wires the picker, options, action bar, results, and report actions together."""

import threading
import tkinter as tk
from tkinter import BOTH, X, messagebox, ttk

from app.services import analysis, ocr, ollama
from app.ui import theme
from app.ui.action_bar import ActionBar
from app.ui.options_panel import OptionsPanel
from app.ui.report_actions import ReportActions
from app.ui.results_table import ResultsTable
from app.ui.video_picker import VideoPicker
from app.ui.vlm_panel import VlmPanel


class MainWindow:
    def __init__(self, root):
        self.root = root
        self.video_path = None
        self.report = None

        root.title("CS2 Viewer Sim")
        root.geometry("920x640")
        root.minsize(780, 520)
        theme.apply(root)

        outer = ttk.Frame(root, padding=16)
        outer.pack(fill=BOTH, expand=True)

        header = ttk.Frame(outer)
        header.pack(fill=X, pady=(0, 12))
        ttk.Label(header, text="CS2 Viewer Sim", style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, text="Simulated-viewer feedback for short-form clips -- no cloud, runs locally.",
                  style="Muted.TLabel").pack(anchor="w")

        self.picker = VideoPicker(outer, on_pick=self._on_video_picked)
        self.picker.pack(fill=X, pady=(0, 10))

        self.options = OptionsPanel(outer)
        self.options.pack(fill=X, pady=(0, 4))

        self.action_bar = ActionBar(outer, on_analyze=self._start_analysis)
        self.action_bar.pack(fill=X)

        self.score_badge = tk.Frame(outer, bg=theme.BG)
        self.score_badge.pack(pady=(2, 10))
        self.score_label = tk.Label(
            self.score_badge, text="", font=(theme.FONT_FAMILY, 20, "bold"),
            bg=theme.BG, padx=18, pady=6,
        )
        self.score_label.pack()

        self.results = ResultsTable(outer)
        self.results.pack(fill=BOTH, expand=True, pady=(0, 8))

        self.vlm_panel = VlmPanel(outer)
        self.vlm_panel.pack(fill=X, pady=(0, 8))

        self.report_actions = ReportActions(outer)
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
        self.vlm_panel.hide()
        self.score_label.config(text="", bg=theme.BG)

        analysis.run_async(
            self.video_path, self.options.use_vlm, self.options.use_ocr, self.options.use_personas,
            on_done=self._analysis_done,
            on_error=self._analysis_failed,
            schedule=self.root.after,
            persona_text=self.options.persona_text,
            custom_personas=self.options.custom_personas,
        )

    def _analysis_done(self, rep):
        self.report = rep
        self.action_bar.stop_busy("Done.")
        self.report_actions.set_report(rep)
        fg, bg = theme.score_colors(rep.overall_score)
        self.score_badge.config(bg=theme.BG)
        self.score_label.config(text=f"{rep.overall_score}/100", fg=fg, bg=bg)
        self.results.load_report(rep)
        vertical_note = "vertical" if rep.is_vertical else "NOT VERTICAL"
        self.picker.set_label(f"{rep.file}  ({rep.resolution}, {rep.duration_s}s, {vertical_note})")
        if rep.persona_summary:
            self.vlm_panel.show_personas(rep.persona_notes, rep.persona_summary)
        elif rep.vlm_notes:
            if "error" in rep.vlm_notes:
                messagebox.showwarning("AI viewer", rep.vlm_notes["error"])
            else:
                self.vlm_panel.show_vlm(rep.vlm_notes)

    def _analysis_failed(self, exc):
        self.action_bar.stop_busy("Failed.")
        messagebox.showerror("Analysis failed", str(exc))
