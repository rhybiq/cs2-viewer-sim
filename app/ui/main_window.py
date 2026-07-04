"""Top-level window: global status/header, then a tabbed Analyze / AI Viewer layout.

Analyze (Layer 1 metrics) and AI Viewer (Ollama personas) are independent --
each has its own Analyze button and its own report-export control, and can
run without the other having run first. self.report is the shared destination
both write into, so whichever runs first creates it (Analyze via
viewer_sim.to_report, AI Viewer via a bare probe() shell) and the other fills
in more fields without clobbering it.
"""

import os
import threading
import tkinter as tk
import webbrowser
from tkinter import BOTH, LEFT, X, messagebox, ttk

import viewer_sim as vs
from app.services import analysis, ocr, ollama, updater
from app.ui import theme
from app.ui.action_bar import ActionBar
from app.ui.options_panel import AiViewerOptions, OcrToggle, OllamaStatusRow
from app.ui.report_actions import QuickReportExport
from app.ui.results_table import ResultsTable
from app.ui.update_banner import UpdateBanner
from app.ui.video_picker import VideoPicker
from app.ui.vlm_panel import VlmPanel

UPDATE_CHECK_INTERVAL_MS = 61 * 1000  # 61s -- ~59 checks/hour, just under GitHub's 60/hour unauthenticated rate limit


class MainWindow:
    def __init__(self, root):
        self.root = root
        self.video_path = None
        self.report = None

        version = updater.get_current_version() or "dev build"
        root.title(f"CS2 Viewer Sim -- {version}")
        root.geometry("920x680")
        root.minsize(780, 560)
        theme.apply(root)

        outer = ttk.Frame(root, padding=16)
        outer.pack(fill=BOTH, expand=True)

        header = ttk.Frame(outer)
        header.pack(fill=X, pady=(0, 12))
        ttk.Label(header, text="CS2 Viewer Sim", style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, text=f"Simulated-viewer feedback for short-form clips -- no cloud, runs locally.  ·  {version}",
                  style="Muted.TLabel").pack(anchor="w")

        self._latest_release = None
        self.update_banner = UpdateBanner(outer, on_click=self._on_update_clicked)

        self.ollama_status = OllamaStatusRow(outer, on_pull_model=self._on_pull_model)
        self.ollama_status.pack(fill=X, pady=(0, 10))

        # Global, not tab-scoped: both Analyze and AI Viewer act on the same
        # picked video, and AI Viewer needs to be usable without ever visiting
        # the Analyze tab first.
        self.picker = VideoPicker(outer, on_pick=self._on_video_picked)
        self.picker.pack(fill=X, pady=(0, 10))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill=BOTH, expand=True)

        analyze_tab = ttk.Frame(notebook, padding=(0, 12))
        ai_viewer_tab = ttk.Frame(notebook, padding=(0, 12))
        notebook.add(analyze_tab, text="Analyze")
        notebook.add(ai_viewer_tab, text="AI Viewer")

        # -- Analyze tab: core options, Analyze action + report export, score, results --
        self.ocr_toggle = OcrToggle(analyze_tab)
        self.ocr_toggle.pack(fill=X, pady=(0, 4))

        analyze_action_row = ttk.Frame(analyze_tab)
        analyze_action_row.pack(fill=X)
        self.action_bar = ActionBar(analyze_action_row, on_analyze=self._start_analysis)
        self.action_bar.pack(side=LEFT)
        self.analyze_export = QuickReportExport(analyze_action_row)
        self.analyze_export.pack(side=LEFT, padx=(16, 0))

        self.score_badge = tk.Frame(analyze_tab, bg=theme.BG)
        self.score_badge.pack(pady=(2, 10))
        self.score_label = tk.Label(
            self.score_badge, text="", font=(theme.FONT_MONO, 20, "bold"),
            bg=theme.BG, padx=18, pady=6,
        )
        self.score_label.pack()

        self.results = ResultsTable(analyze_tab)
        self.results.pack(fill=BOTH, expand=True)

        # -- AI Viewer tab: persona config, its own Analyze action + report export, simulated viewer output --
        self.ai_viewer = AiViewerOptions(ai_viewer_tab)
        self.ai_viewer.pack(fill=X, pady=(0, 8))

        ai_action_row = ttk.Frame(ai_viewer_tab)
        ai_action_row.pack(fill=X, pady=(0, 8))
        self.ai_action_bar = ActionBar(ai_action_row, on_analyze=self._start_ai_viewer_analysis)
        self.ai_action_bar.pack(side=LEFT)
        self.ai_export = QuickReportExport(ai_action_row)
        self.ai_export.pack(side=LEFT, padx=(16, 0))

        self.vlm_panel = VlmPanel(ai_viewer_tab)
        self.vlm_panel.pack(fill=BOTH, expand=True)

        self._check_ollama()
        self._check_ocr()
        self._check_for_updates()

    def _check_for_updates(self):
        def worker():
            release = updater.check_for_update()
            self.root.after(0, self._update_check_done, release)

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(UPDATE_CHECK_INTERVAL_MS, self._check_for_updates)

    def _update_check_done(self, release):
        if not release:
            return
        self._latest_release = release
        action_text = "Update now" if updater.is_installed_via_setup() else "Download"
        self.update_banner.show(release["tag"], action_text)

    def _on_update_clicked(self):
        release = self._latest_release
        if not release:
            return
        if not updater.is_installed_via_setup():
            webbrowser.open(release.get("page_url") or "https://github.com/rhybiq/cs2-viewer-sim/releases/latest")
            return
        if not release.get("installer_url"):
            webbrowser.open(release.get("page_url") or "https://github.com/rhybiq/cs2-viewer-sim/releases/latest")
            return

        self.update_banner.set_busy(True, text="Downloading update...")

        def worker():
            try:
                path = updater.download_installer(release["installer_url"])
                updater.run_installer_silently(path)
                self.root.after(0, self._update_launched)
            except Exception as e:
                self.root.after(0, self._update_failed, e)

        threading.Thread(target=worker, daemon=True).start()

    def _update_launched(self):
        messagebox.showinfo(
            "Updating",
            "The update is installing in the background. Please restart the app in a "
            "few moments to use the new version.",
        )
        self.root.destroy()

    def _update_failed(self, exc):
        self.update_banner.set_busy(False, text=f"Update available: {self._latest_release['tag']} -- Update now")
        messagebox.showerror("Update failed", str(exc))

    def _check_ollama(self):
        def worker():
            available = ollama.is_available()
            if available:
                self.root.after(0, self.ollama_status.set_ollama_status, available)
                self.root.after(0, self.ai_viewer.set_ollama_status, available)
                has_model = ollama.has_model()
                self.root.after(0, self.ollama_status.set_model_status, has_model)
                self.root.after(0, self.ai_viewer.set_model_status, has_model)
            else:
                installed = ollama.is_installed()
                self.root.after(0, self.ollama_status.set_ollama_status, available, installed)
                self.root.after(0, self.ai_viewer.set_ollama_status, available)

        threading.Thread(target=worker, daemon=True).start()

    def _on_pull_model(self):
        self.ollama_status.set_pulling(True)

        def worker():
            ok = ollama.pull_model()
            self.root.after(0, self._pull_model_done, ok)

        threading.Thread(target=worker, daemon=True).start()

    def _pull_model_done(self, ok):
        self.ollama_status.set_pulling(False)
        self.ollama_status.set_model_status(ok)
        self.ai_viewer.set_model_status(ok)
        if not ok:
            messagebox.showerror(
                "Pull failed",
                f"Couldn't pull {ollama.DEFAULT_MODEL}. Try running "
                f"`ollama pull {ollama.DEFAULT_MODEL}` yourself to see the error.",
            )

    def _check_ocr(self):
        def worker():
            available = ocr.is_available()
            self.root.after(0, self.ocr_toggle.set_ocr_status, available)

        threading.Thread(target=worker, daemon=True).start()

    def _on_video_picked(self, path):
        self.video_path = path
        self.report = None
        self.action_bar.set_ready(True)
        self.ai_action_bar.set_ready(True)
        self.results.clear()
        self.vlm_panel.hide()
        self.score_label.config(text="", bg=theme.BG)

    def _ensure_report(self):
        """The shared Report object both tabs write into. Whichever tab runs
        first creates it; a bare probe() is enough for the AI Viewer tab to
        create a valid shell without doing Layer 1's heavier analysis.
        """
        if self.report is None:
            fps, dur, w, h = vs.probe(self.video_path)
            self.report = vs.Report(
                file=os.path.basename(self.video_path), duration_s=round(dur, 2),
                fps=round(fps, 2), resolution=f"{w}x{h}", is_vertical=h > w,
            )
        return self.report

    def _start_analysis(self):
        if not self.video_path:
            return
        self.action_bar.start_busy()

        analysis.run_async(
            self.video_path, self.ocr_toggle.use_ocr,
            on_done=self._analysis_done,
            on_error=self._analysis_failed,
            schedule=self.root.after,
        )

    def _analysis_done(self, rep):
        # Carry over anything the AI Viewer tab already produced independently.
        if self.report is not None:
            rep.vlm_notes = rep.vlm_notes or self.report.vlm_notes
            rep.persona_notes = rep.persona_notes or self.report.persona_notes
            rep.persona_summary = rep.persona_summary or self.report.persona_summary
        self.report = rep
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
        written = self.analyze_export.maybe_export(rep, self.video_path)
        self.action_bar.stop_busy(f"Done. Saved {len(written)} report(s)." if written else "Done.")

    def _analysis_failed(self, exc):
        self.action_bar.stop_busy("Failed.")
        messagebox.showerror("Analysis failed", str(exc))

    def _start_ai_viewer_analysis(self):
        if not self.video_path:
            return
        self.ai_action_bar.start_busy("Running AI viewer...")
        self.vlm_panel.hide()

        analysis.run_ai_viewer_async(
            self.video_path, self.ai_viewer.use_personas,
            on_done=self._ai_viewer_done,
            on_error=self._ai_viewer_failed,
            schedule=self.root.after,
            persona_text=self.ai_viewer.persona_text,
            custom_personas=self.ai_viewer.custom_personas,
            persona_count=self.ai_viewer.persona_count,
            sample_fps=self.ai_viewer.sample_fps,
        )

    def _ai_viewer_done(self, result):
        rep = self._ensure_report()
        if "persona_notes" in result:
            rep.persona_notes = result["persona_notes"]
            rep.persona_summary = result.get("persona_summary")
            self.vlm_panel.show_personas(rep.persona_notes, rep.persona_summary)
        else:
            rep.vlm_notes = result["vlm_notes"]
            if "error" in rep.vlm_notes:
                messagebox.showwarning("AI viewer", rep.vlm_notes["error"])
            else:
                self.vlm_panel.show_vlm(rep.vlm_notes)
        written = self.ai_export.maybe_export(rep, self.video_path)
        self.ai_action_bar.stop_busy(f"Done. Saved {len(written)} report(s)." if written else "Done.")

    def _ai_viewer_failed(self, exc):
        self.ai_action_bar.stop_busy("Failed.")
        messagebox.showerror("AI viewer failed", str(exc))
