"""App entry point: python -m app.main, or via run_app.py at the repo root."""

import sys

from PySide6.QtWidgets import QApplication

from app.ui import qss_loader
from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(qss_loader.load())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
