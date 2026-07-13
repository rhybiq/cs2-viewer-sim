"""App entry point: python -m app_demo_highlights.main, or via
run_demo_highlights.py at the repo root -- mirrors app/main.py exactly (same
QApplication -> dark theme -> window -> exec chain), just for a different
window. A separate process from the "CS2 Viewer Sim" desktop app: only one
QApplication can exist per process, and this is a different domain (CS2
demo parsing) from that app's video analysis.
"""

import sys

from PySide6.QtWidgets import QApplication

from app.ui import qss_loader
from app_demo_highlights.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(qss_loader.load())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
