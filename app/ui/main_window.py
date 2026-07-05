"""Top-level Qt window: header, top bar (dependency chips + update badge),
global video selector, global save controls, then a tabbed Clip Metrics /
AI Viewer layout. Both tabs run their analysis off the UI thread via
app/ui/workers.py's CallableThread (§1-§3 complete); §4 still owed: a real
QStatusBar run summary and one-job-at-a-time enforcement across tabs.
"""

import webbrowser

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox, QTabWidget, QVBoxLayout, QWidget

from app.services import ocr, ollama, stt, updater
from app.ui.ai_viewer_tab import AiViewerTab
from app.ui.clip_metrics_tab import ClipMetricsTab
from app.ui.save_controls import SaveControls
from app.ui.top_bar import TopBar
from app.ui.video_picker import VideoSelector
from app.ui.workers import CallableThread

UPDATE_CHECK_INTERVAL_MS = 61 * 1000  # ~59 checks/hour, just under GitHub's 60/hour unauthenticated rate limit


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.video_path = None
        self._latest_release = None
        self._threads = []  # keep references so background CallableThreads aren't GC'd mid-run

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
        self.clip_metrics_tab.report_ready.connect(self._on_clip_metrics_report_ready)
        self.tabs.addTab(self.clip_metrics_tab, "Clip Metrics")
        self.tabs.addTab(self.ai_viewer_tab, "AI Viewer")
        layout.addWidget(self.tabs, stretch=1)

        central.setLayout(layout)
        self.setCentralWidget(central)

        self._check_ollama()
        self._check_ocr()
        self._check_stt()
        self._check_for_updates()

    def _on_video_picked(self, path):
        self.video_path = path
        self.clip_metrics_tab.set_video_path(path)
        self.ai_viewer_tab.set_video_path(path)

    def _on_clip_metrics_report_ready(self, rep):
        self.save_controls.maybe_export(rep, self.video_path, suffix="metrics")
        # Reuse the already-computed retention curve so the AI Viewer's
        # swipe_second grounding doesn't redo that motion analysis --
        # only if Layer 1 actually populated it (a bare probe()-only shell
        # would have an empty curve, which must not be treated as "already
        # computed" or swipe_second would always come back None).
        if rep.retention_curve:
            self.ai_viewer_tab.existing_retention_curve = rep.retention_curve

    # -- Ollama / EasyOCR dependency checks --------------------------------
    def _check_ollama(self):
        t = CallableThread(ollama.is_available)
        t.done.connect(self._ollama_checked)
        self._threads.append(t)
        t.start()

    def _ollama_checked(self, available):
        self.ai_viewer_tab.set_ollama_status(available)
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
