"""Standalone window for demo_highlights -- finds highlight moments
(multi-kills, aces, clutches) in a CS2 demo file (.dem) using the match's
own recorded game-state data, not video/OCR guessing. A separate app from
"CS2 Viewer Sim" (shipped in the same installer) since this is CS2-demo
parsing, a different domain than that app's video analysis -- no shared
state, no shared imports with app/ or viewer_sim.py beyond a few
framework-agnostic UI utilities (dark theme, colors, version string)
reused as-is rather than duplicated.
"""

import os
import time
import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QStackedLayout, QTableView,
    QVBoxLayout, QWidget,
)

from app.services import updater
from app.ui import colors
from app.ui.update_banner import UpdateBadge
from app.ui.workers import CallableThread
from app_demo_highlights.highlights_table_model import DemoHighlightsTableModel
from demo_highlights.highlights import filter_events_by_player, find_highlights_from_demo

DEMO_FILETYPES = "CS2 demo files (*.dem);;All files (*.*)"
EMPTY_STATE_TEXT = "Pick a CS2 demo file (.dem) to find its highlight moments."
ALL_PLAYERS_LABEL = "All players"
# Same cadence as app/ui/main_window.py's update check (~59/hour, just under GitHub's
# 60/hour unauthenticated rate limit). Running both apps at once means the limit is
# shared across two independent pollers -- get_latest_release() already degrades to a
# silently-skipped check on any failure (incl. a 429), so this is self-healing, not a bug.
UPDATE_CHECK_INTERVAL_MS = 61 * 1000


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._demo_path = None
        self._thread = None
        self._busy = False
        self._start_time = None
        self._all_events = []  # full unfiltered scan result -- the player filter re-slices
                                 # this locally, no rescan needed
        self._scan_summary_suffix = ""
        self._latest_release = None
        self._update_threads = []  # keep refs so background CallableThreads aren't GC'd mid-run

        version = updater.get_current_version() or "dev build"
        self.setWindowTitle(f"CS2 Demo Highlights -- {version}")
        self.resize(820, 620)
        self.setMinimumSize(680, 480)

        central = QWidget()
        layout = QVBoxLayout(central)

        title = QLabel("CS2 Demo Highlights")
        title.setStyleSheet("font-size: 15pt; font-weight: bold;")
        subtitle = QLabel(
            "Multi-kills, aces, and clutches from a CS2 demo's own recorded game data "
            "-- no video, no guessing.")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        picker_row = QHBoxLayout()
        choose_btn = QPushButton("Choose Demo...")
        choose_btn.clicked.connect(self._choose_demo)
        picker_row.addWidget(choose_btn)
        self.path_label = QLabel("No demo selected yet.")
        picker_row.addWidget(self.path_label, stretch=1)
        layout.addLayout(picker_row)

        action_row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setObjectName("primaryButton")
        self.scan_btn.setEnabled(False)
        self.scan_btn.clicked.connect(self._on_scan_clicked)
        action_row.addWidget(self.scan_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate -- a demo parse is fast (well under a
        self.progress.setMaximumWidth(140)  # second on a real match), no meaningful "N of M" to show
        self.progress.hide()
        action_row.addWidget(self.progress)
        self.elapsed_label = QLabel("")
        self.elapsed_label.setStyleSheet(f"color: {colors.MUTED};")
        self.elapsed_label.hide()
        action_row.addWidget(self.elapsed_label)
        action_row.addStretch(1)
        action_row.addWidget(QLabel("Player:"))
        self.player_filter = QComboBox()
        self.player_filter.addItem(ALL_PLAYERS_LABEL)
        self.player_filter.setEnabled(False)
        self.player_filter.setMinimumWidth(160)
        self.player_filter.currentTextChanged.connect(self._on_player_filter_changed)
        action_row.addWidget(self.player_filter)
        self.update_badge = UpdateBadge(on_click=self._on_update_clicked)
        action_row.addWidget(self.update_badge)
        layout.addLayout(action_row)

        self._stack = QStackedLayout()
        self._empty_label = QLabel(EMPTY_STATE_TEXT)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {colors.MUTED};")
        self._stack.addWidget(self._empty_label)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.model = DemoHighlightsTableModel()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self._stack.addWidget(self.table)

        stack_widget = QWidget()
        stack_widget.setLayout(self._stack)
        layout.addWidget(stack_widget, stretch=1)

        central.setLayout(layout)
        self.setCentralWidget(central)

        self.status_message = QLabel("")
        self.statusBar().addWidget(self.status_message, 1)

        self._check_for_updates()

    # -- demo selection -------------------------------------------------------
    def _choose_demo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a CS2 demo", "", DEMO_FILETYPES)
        if not path:
            return
        self._demo_path = path
        self.path_label.setText(os.path.basename(path))
        self.scan_btn.setEnabled(not self._busy)
        self.model.clear()
        self._all_events = []
        self._reset_player_filter()
        self._stack.setCurrentWidget(self._empty_label)
        self.elapsed_label.hide()
        self.status_message.setText("")

    # -- scanning -------------------------------------------------------------
    def _on_scan_clicked(self):
        if not self._demo_path or self._busy:
            return
        self._start_scan()

    def _start_scan(self):
        self._busy = True
        self._start_time = time.monotonic()
        self.scan_btn.setEnabled(False)
        self.elapsed_label.hide()
        self.status_message.setText("")
        self.progress.show()

        # top_n=None -- fetch every event, not just the globally-ranked top N. The
        # player filter below needs a player's own events even if they didn't rank
        # among the match's overall highlights.
        self._thread = CallableThread(find_highlights_from_demo, self._demo_path, top_n=None)
        self._thread.done.connect(self._scan_done)
        self._thread.failed.connect(self._scan_failed)
        self._thread.start()

    def _reset_busy_ui(self):
        self._busy = False
        self.scan_btn.setEnabled(bool(self._demo_path))
        self.progress.hide()

    def _reset_player_filter(self):
        self.player_filter.blockSignals(True)
        self.player_filter.clear()
        self.player_filter.addItem(ALL_PLAYERS_LABEL)
        self.player_filter.setEnabled(False)
        self.player_filter.blockSignals(False)

    def _scan_done(self, result):
        elapsed = time.monotonic() - self._start_time
        self._reset_busy_ui()
        self.elapsed_label.setText(f"Scanned in {elapsed:.1f}s")
        self.elapsed_label.show()

        self._all_events = result.events
        players = sorted({p for e in result.events for p in e.players}, key=str.lower)
        self._reset_player_filter()
        self.player_filter.blockSignals(True)
        self.player_filter.addItems(players)
        self.player_filter.setEnabled(bool(players))
        self.player_filter.blockSignals(False)

        demo_name = os.path.basename(self._demo_path)
        self._scan_summary_suffix = f"in {demo_name} ({result.map_name}, {result.total_rounds} rounds) in {elapsed:.1f}s"
        self.model.set_events(result.events)
        self._stack.setCurrentWidget(self.table if result.events else self._empty_label)
        self.status_message.setStyleSheet(f"color: {colors.TEXT};")
        self.status_message.setText(
            f"Found {len(result.events)} highlight event{'s' if len(result.events) != 1 else ''} "
            f"{self._scan_summary_suffix}")

    def _scan_failed(self, exc):
        self._reset_busy_ui()
        self.status_message.setStyleSheet(f"color: {colors.BAD};")
        self.status_message.setText(f"Scan failed: {exc}")

    # -- player filter (local re-slice of the last scan, no rescan) -----------
    def _on_player_filter_changed(self, name):
        if name == ALL_PLAYERS_LABEL or not name:
            filtered = self._all_events
        else:
            filtered = filter_events_by_player(self._all_events, name)
        self.model.set_events(filtered)
        self._stack.setCurrentWidget(self.table if filtered else self._empty_label)
        if name != ALL_PLAYERS_LABEL and name:
            self.status_message.setText(
                f"Showing {len(filtered)} of {len(self._all_events)} highlight events for {name} "
                f"{self._scan_summary_suffix}")
        else:
            self.status_message.setText(
                f"Found {len(self._all_events)} highlight event{'s' if len(self._all_events) != 1 else ''} "
                f"{self._scan_summary_suffix}")

    # -- context menu (matching the existing tables' convention) -------------
    def _show_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        menu = QMenu(self)
        copy_row_action = menu.addAction("Copy row")
        copy_reason_action = menu.addAction("Copy reason")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        clipboard = QApplication.clipboard()
        if chosen == copy_row_action:
            values = [self.model.index(index.row(), c).data(Qt.DisplayRole)
                      for c in range(self.model.columnCount())]
            clipboard.setText("\t".join(str(v) for v in values))
        elif chosen == copy_reason_action:
            reason = self.model.index(index.row(), 4).data(Qt.DisplayRole)
            clipboard.setText(str(reason))

    # -- update check (mirrors app/ui/main_window.py's flow exactly -- same
    # shared installer covers both apps, see app/services/updater.py) --------
    def _check_for_updates(self):
        t = CallableThread(updater.check_for_update)
        t.done.connect(self._update_check_done)
        self._update_threads.append(t)
        t.start()
        QTimer.singleShot(UPDATE_CHECK_INTERVAL_MS, self._check_for_updates)

    def _update_check_done(self, release):
        if not release:
            return
        self._latest_release = release
        action_text = "Update now" if updater.is_installed_via_setup() else "Download"
        self.update_badge.show_update(release["tag"], action_text)

    def _on_update_clicked(self):
        release = self._latest_release
        if not release:
            return
        if not updater.is_installed_via_setup() or not release.get("installer_url"):
            webbrowser.open(release.get("page_url") or "https://github.com/rhybiq/cs2-viewer-sim/releases/latest")
            return

        self.update_badge.set_busy(True, "Downloading update...")
        t = CallableThread(updater.download_installer, release["installer_url"])
        t.done.connect(self._update_downloaded)
        t.failed.connect(self._update_failed)
        self._update_threads.append(t)
        t.start()

    def _update_downloaded(self, installer_path):
        QMessageBox.information(
            self, "Updating",
            "CS2 Demo Highlights will now close to finish installing the update. "
            "Reopen it in a few seconds to use the new version.",
        )
        try:
            updater.run_installer_silently(installer_path)
        except Exception as e:
            QMessageBox.critical(self, "Update failed", f"Could not launch the installer: {e}")
            return
        self.close()

    def _update_failed(self, exc):
        self.update_badge.set_busy(False, f"{self._latest_release['tag']} available -- Update now")
        QMessageBox.critical(self, "Update failed", str(exc))
