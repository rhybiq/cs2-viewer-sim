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
    # (completed, total) -- only emitted when report_progress=True and fn
    # actually calls the on_progress callback it's given; emit() from inside
    # run() is safe here since Qt queues delivery to the receiver's (UI)
    # thread automatically for cross-thread signal connections.
    progress = Signal(int, int)

    def __init__(self, fn, *args, report_progress=False, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._report_progress = report_progress

    def run(self):
        try:
            if self._report_progress:
                self._kwargs["on_progress"] = lambda done, total: self.progress.emit(done, total)
            result = self._fn(*self._args, **self._kwargs)
        except Exception as e:
            self.failed.emit(e)
            return
        self.done.emit(result)
