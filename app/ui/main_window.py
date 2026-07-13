"""Top-level Qt window: header, top bar (dependency chips + update badge),
global video selector, global save controls, then a tabbed Clip Metrics /
AI Viewer layout. Both tabs run their analysis off the UI thread via
app/ui/workers.py's CallableThread, enforce one-job-at-a-time across tabs,
and report their run summary (or error, in red) to a shared QStatusBar (§4).

self.report is the single Report object both tabs write into -- whichever
tab finishes first creates it (Clip Metrics via viewer_sim.to_report(), AI
Viewer via a bare probe() shell), and the other attaches its own fields
without clobbering what's already there. Save Controls exports whatever
that shared object holds at the time each tab finishes, under a filename
suffix distinct per pass (<clip>_metrics.* / <clip>_ai_viewer.*, §1.4).
"""

import os
import webbrowser

import viewer_sim as vs
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox, QTabWidget, QVBoxLayout, QWidget

from app.services import ocr, ollama, stt, updater
from app.ui import colors
from app.ui.ai_viewer_tab import AiViewerTab
from app.ui.clip_metrics_tab import ClipMetricsTab
from app.ui.highlights_tab import HighlightsTab
from app.ui.save_controls import SaveControls
from app.ui.top_bar import TopBar
from app.ui.video_picker import VideoSelector
from app.ui.workers import CallableThread

UPDATE_CHECK_INTERVAL_MS = 61 * 1000  # ~59 checks/hour, just under GitHub's 60/hour unauthenticated rate limit


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.video_path = None
        self.report = None
        self._latest_release = None
        self._threads = []  # keep references so background CallableThreads aren't GC'd mid-run
        self._pending_export_paths = []  # bridges report_ready/result_ready -> analysis_finished

        version = updater.get_current_version() or "dev build"
        self.setWindowTitle(f"CS2 Viewer Sim -- {version}")
        self.resize(920, 680)
        self.setMinimumSize(780, 560)

        central = QWidget()
        layout = QVBoxLayout(central)

        title = QLabel("CS2 Viewer Sim")
        title.setStyleSheet("font-size: 15pt; font-weight: bold;")
        # Subtitle is the fixed sentence only, not concatenated with the
        # version -- the version already lives in the window title.
        subtitle = QLabel("Simulated-viewer feedback for short-form clips -- no cloud, runs locally.")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.top_bar = TopBar(on_update_clicked=self._on_update_clicked)
        layout.addWidget(self.top_bar)

        # Global, not tab-scoped: both tabs act on the same picked video, and
        # AI Viewer needs to be usable without ever visiting Clip Metrics first.
        self.video_selector = VideoSelector(on_pick=self._on_video_picked)
        layout.addWidget(self.video_selector)

        self.save_controls = SaveControls()
        layout.addWidget(self.save_controls)

        self.tabs = QTabWidget()
        self.clip_metrics_tab = ClipMetricsTab()
        self.ai_viewer_tab = AiViewerTab()
        self.highlights_tab = HighlightsTab()
        self.clip_metrics_tab.report_ready.connect(self._on_clip_metrics_report_ready)
        self.ai_viewer_tab.result_ready.connect(self._on_ai_viewer_result_ready)
        self.clip_metrics_tab.ai_viewer_requested.connect(self._go_to_ai_viewer)

        # §4.1: one analysis job at a time across all three tabs -- Find
        # Highlights has its own independent video (a raw VOD, not the
        # shared global pick) but still competes for the same CPU/GPU
        # resources (OpenCV/ffmpeg/EasyOCR/faster-whisper), so it joins the
        # same mutual-exclusion wiring as the other two.
        self.clip_metrics_tab.analysis_started.connect(
            lambda: self.ai_viewer_tab.set_other_tab_busy(True))
        self.clip_metrics_tab.analysis_started.connect(
            lambda: self.highlights_tab.set_other_tab_busy(True))
        self.clip_metrics_tab.analysis_finished.connect(
            lambda text: self.ai_viewer_tab.set_other_tab_busy(False))
        self.clip_metrics_tab.analysis_finished.connect(
            lambda text: self.highlights_tab.set_other_tab_busy(False))
        self.clip_metrics_tab.analysis_finished.connect(self._show_status)
        self.clip_metrics_tab.analysis_error.connect(
            lambda text: self.ai_viewer_tab.set_other_tab_busy(False))
        self.clip_metrics_tab.analysis_error.connect(
            lambda text: self.highlights_tab.set_other_tab_busy(False))
        self.clip_metrics_tab.analysis_error.connect(self._show_status_error)

        self.ai_viewer_tab.analysis_started.connect(
            lambda: self.clip_metrics_tab.set_other_tab_busy(True))
        self.ai_viewer_tab.analysis_started.connect(
            lambda: self.highlights_tab.set_other_tab_busy(True))
        self.ai_viewer_tab.analysis_finished.connect(
            lambda text: self.clip_metrics_tab.set_other_tab_busy(False))
        self.ai_viewer_tab.analysis_finished.connect(
            lambda text: self.highlights_tab.set_other_tab_busy(False))
        self.ai_viewer_tab.analysis_finished.connect(self._show_status)
        self.ai_viewer_tab.analysis_error.connect(
            lambda text: self.clip_metrics_tab.set_other_tab_busy(False))
        self.ai_viewer_tab.analysis_error.connect(
            lambda text: self.highlights_tab.set_other_tab_busy(False))
        self.ai_viewer_tab.analysis_error.connect(self._show_status_error)

        self.highlights_tab.analysis_started.connect(
            lambda: self.clip_metrics_tab.set_other_tab_busy(True))
        self.highlights_tab.analysis_started.connect(
            lambda: self.ai_viewer_tab.set_other_tab_busy(True))
        self.highlights_tab.analysis_finished.connect(
            lambda text: self.clip_metrics_tab.set_other_tab_busy(False))
        self.highlights_tab.analysis_finished.connect(
            lambda text: self.ai_viewer_tab.set_other_tab_busy(False))
        self.highlights_tab.analysis_finished.connect(self._show_status)
        self.highlights_tab.analysis_error.connect(
            lambda text: self.clip_metrics_tab.set_other_tab_busy(False))
        self.highlights_tab.analysis_error.connect(
            lambda text: self.ai_viewer_tab.set_other_tab_busy(False))
        self.highlights_tab.analysis_error.connect(self._show_status_error)

        self.tabs.addTab(self.clip_metrics_tab, "Clip Metrics")
        self.tabs.addTab(self.ai_viewer_tab, "AI Viewer")
        self.tabs.addTab(self.highlights_tab, "Find Highlights")
        layout.addWidget(self.tabs, stretch=1)

        central.setLayout(layout)
        self.setCentralWidget(central)

        self.status_message = QLabel("")
        self.statusBar().addWidget(self.status_message, 1)

        self._check_ollama()
        self._check_ocr()
        self._check_stt()
        self._check_for_updates()

    def _on_video_picked(self, path):
        self.video_path = path
        self.report = None
        self.clip_metrics_tab.set_video_path(path)
        self.ai_viewer_tab.set_video_path(path)

    def _go_to_ai_viewer(self):
        # §6: "Get simulated viewer reaction ->" -- same video already
        # selected (global state), just switch tabs and focus the button.
        self.tabs.setCurrentWidget(self.ai_viewer_tab)
        self.ai_viewer_tab.analyze_btn.setFocus()

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

    def _on_clip_metrics_report_ready(self, rep):
        # Carry over anything the AI Viewer tab already produced independently.
        if self.report is not None:
            rep.vlm_notes = rep.vlm_notes or self.report.vlm_notes
            rep.persona_notes = rep.persona_notes or self.report.persona_notes
            rep.persona_summary = rep.persona_summary or self.report.persona_summary
        self.report = rep
        self._pending_export_paths = self.save_controls.maybe_export(rep, self.video_path, suffix="metrics")
        # Reuse the already-computed retention curve so the AI Viewer's
        # swipe_second grounding doesn't redo that motion analysis --
        # only if Layer 1 actually populated it (a bare probe()-only shell
        # would have an empty curve, which must not be treated as "already
        # computed" or swipe_second would always come back None).
        if rep.retention_curve:
            self.ai_viewer_tab.existing_retention_curve = rep.retention_curve

    def _on_ai_viewer_result_ready(self, result):
        rep = self._ensure_report()
        if "persona_notes" in result:
            rep.persona_notes = result["persona_notes"]
            rep.persona_summary = result.get("persona_summary")
        else:
            rep.vlm_notes = result["vlm_notes"]
        self._pending_export_paths = self.save_controls.maybe_export(rep, self.video_path, suffix="ai_viewer")

    # -- shared status bar (§4.2/§4.3) --------------------------------------
    def _show_status(self, text):
        if self._pending_export_paths:
            names = ", ".join(os.path.basename(p) for p in self._pending_export_paths)
            text += f" -- saved {names}"
        self._pending_export_paths = []
        self.status_message.setStyleSheet(f"color: {colors.TEXT};")
        self.status_message.setText(text)

    def _show_status_error(self, text):
        self._pending_export_paths = []
        truncated = text if len(text) <= 200 else text[:200] + "..."
        self.status_message.setStyleSheet(f"color: {colors.BAD};")
        self.status_message.setText(truncated)

    # -- Ollama / EasyOCR dependency checks --------------------------------
    def _check_ollama(self):
        t = CallableThread(ollama.is_available)
        t.done.connect(self._ollama_checked)
        self._threads.append(t)
        t.start()

    def _ollama_checked(self, available):
        self.ai_viewer_tab.set_ollama_status(available)
        self.clip_metrics_tab.set_ollama_status(available)
        if available:
            self.top_bar.ollama_chip.set_status(True, "detected")
            t = CallableThread(ollama.has_model)
            t.done.connect(self._ollama_model_checked)
            self._threads.append(t)
            t.start()
        else:
            installed = ollama.is_installed()
            self.top_bar.ollama_chip.set_status(
                False, "installed, not running" if installed else "not installed")

    def _ollama_model_checked(self, has_model):
        self.top_bar.ollama_chip.set_status(
            has_model, "model ready" if has_model else f"{ollama.DEFAULT_MODEL} not pulled")
        self.ai_viewer_tab.set_model_status(has_model)
        self.clip_metrics_tab.set_model_status(has_model)

    def _check_ocr(self):
        t = CallableThread(ocr.is_available)
        t.done.connect(self._ocr_checked)
        self._threads.append(t)
        t.start()

    def _ocr_checked(self, available):
        self.top_bar.ocr_chip.set_status(available, "detected" if available else "not installed")
        self.clip_metrics_tab.set_ocr_available(available)

    def _check_stt(self):
        t = CallableThread(stt.is_available)
        t.done.connect(self.ai_viewer_tab.set_stt_status)
        t.done.connect(self.highlights_tab.set_stt_status)
        self._threads.append(t)
        t.start()

    # -- Update check --------------------------------------------------------
    def _check_for_updates(self):
        t = CallableThread(updater.check_for_update)
        t.done.connect(self._update_check_done)
        self._threads.append(t)
        t.start()
        QTimer.singleShot(UPDATE_CHECK_INTERVAL_MS, self._check_for_updates)

    def _update_check_done(self, release):
        if not release:
            return
        self._latest_release = release
        action_text = "Update now" if updater.is_installed_via_setup() else "Download"
        self.top_bar.show_update(release["tag"], action_text)

    def _on_update_clicked(self):
        release = self._latest_release
        if not release:
            return
        if not updater.is_installed_via_setup() or not release.get("installer_url"):
            webbrowser.open(release.get("page_url") or "https://github.com/rhybiq/cs2-viewer-sim/releases/latest")
            return

        self.top_bar.set_update_busy(True, "Downloading update...")
        t = CallableThread(updater.download_installer, release["installer_url"])
        t.done.connect(self._update_downloaded)
        t.failed.connect(self._update_failed)
        self._threads.append(t)
        t.start()

    def _update_downloaded(self, installer_path):
        # Shown *before* launching the installer, not after -- see the
        # equivalent Tkinter comment history for why (installer needs the
        # exe's file lock released; nothing should block between launch and
        # actually closing).
        QMessageBox.information(
            self, "Updating",
            "CS2 Viewer Sim will now close to finish installing the update. "
            "Reopen it in a few seconds to use the new version.",
        )
        try:
            updater.run_installer_silently(installer_path)
        except Exception as e:
            QMessageBox.critical(self, "Update failed", f"Could not launch the installer: {e}")
            return
        self.close()

    def _update_failed(self, exc):
        self.top_bar.set_update_busy(False, f"{self._latest_release['tag']} available -- Update now")
        QMessageBox.critical(self, "Update failed", str(exc))
