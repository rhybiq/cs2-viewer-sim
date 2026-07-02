"""Row with the primary Analyze action, progress bar, and status text."""

from tkinter import DISABLED, LEFT, NORMAL, StringVar, ttk


class ActionBar(ttk.Frame):
    def __init__(self, master, on_analyze):
        super().__init__(master, padding=(0, 12))
        self.analyze_btn = ttk.Button(
            self, text="Analyze", command=on_analyze, state=DISABLED, style="Primary.TButton"
        )
        self.analyze_btn.pack(side=LEFT)
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=140)
        self.status_var = StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, style="Muted.TLabel").pack(side=LEFT, padx=12)

    def set_ready(self, ready):
        self.analyze_btn.config(state=NORMAL if ready else DISABLED)

    def start_busy(self, text="Analyzing..."):
        self.analyze_btn.config(state=DISABLED)
        self.status_var.set(text)
        self.progress.pack(side=LEFT, padx=(12, 12))
        self.progress.start(12)

    def stop_busy(self, text=""):
        self.progress.stop()
        self.progress.pack_forget()
        self.status_var.set(text)
        self.analyze_btn.config(state=NORMAL)
