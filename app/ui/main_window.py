"""Top-level window: wires the picker, options, action bar, results, and report actions together."""

import threading
import tkinter as tk
import webbrowser
from tkinter import BOTH, X, messagebox, ttk

from app.services import analysis, ocr, ollama, updater
from app.ui import theme
from app.ui.action_bar import ActionBar
from app.ui.options_panel import OptionsPanel
from app.ui.report_actions import ReportActions
from app.ui.results_table import ResultsTable
from app.ui.update_banner import UpdateBanner
from app.ui.video_picker import VideoPicker
from app.ui.vlm_panel import VlmPanel

UPDATE_CHECK_INTERVAL_MS = 30 * 1000  # 30 seconds (temporary, for testing the update flow)


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

        self._latest_release = None
        self.update_banner = UpdateBanner(outer, on_click=self._on_update_clicked)

        self.picker = VideoPicker(outer, on_pick=self._on_video_picked)
        self.picker.pack(fill=X, pady=(0, 10))

        self.options = OptionsPanel(outer, on_pull_model=self._on_pull_model)
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
                self.root.after(0, self.options.set_ollama_status, available)
                has_model = ollama.has_model()
                self.root.after(0, self.options.set_model_status, has_model)
            else:
                installed = ollama.is_installed()
                self.root.after(0, self.options.set_ollama_status, available, installed)

        threading.Thread(target=worker, daemon=True).start()

    def _on_pull_model(self):
        self.options.set_pulling(True)

        def worker():
            ok = ollama.pull_model()
            self.root.after(0, self._pull_model_done, ok)

        threading.Thread(target=worker, daemon=True).start()

    def _pull_model_done(self, ok):
        self.options.set_pulling(False)
        self.options.set_model_status(ok)
        if not ok:
            messagebox.showerror(
                "Pull failed",
                f"Couldn't pull {ollama.DEFAULT_MODEL}. Try running "
                f"`ollama pull {ollama.DEFAULT_MODEL}` yourself to see the error.",
            )

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
