"""Generic one-shot background-call helper for the Qt UI.

Runs a single callable off the UI thread and emits its result/error back on
the Qt event loop. Deliberately QThread, not QThreadPool/QRunnable -- pooled
worker management is disproportionate until §4 wires up the real analysis
workers (which may need cancellation/one-job-at-a-time semantics); this is
just "call this function, tell me what it returned."
"""

from PySide6.QtCore import QThread, Signal


class CallableThread(QThread):
    done = Signal(object)
    failed = Signal(Exception)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as e:
            self.failed.emit(e)
            return
        self.done.emit(result)
