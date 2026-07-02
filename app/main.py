"""App entry point: python -m app.main, or via run_app.py at the repo root."""

from tkinter import Tk

from app.ui.main_window import MainWindow


def main():
    root = Tk()
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
