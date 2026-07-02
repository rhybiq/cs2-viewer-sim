"""Frame with the Analyze button, progress bar, and status text."""

from tkinter import DISABLED, LEFT, NORMAL, Button, Frame, Label, StringVar, ttk


class ActionBar(Frame):
    def __init__(self, master, on_analyze):
        super().__init__(master, padx=12, pady=8)
        self.analyze_btn = Button(self, text="Analyze", command=on_analyze, state=DISABLED)
        self.analyze_btn.pack(side=LEFT)
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.status_var = StringVar(value="")
        Label(self, textvariable=self.status_var, fg="#555").pack(side=LEFT, padx=10)

    def set_ready(self, ready):
        self.analyze_btn.config(state=NORMAL if ready else DISABLED)

    def start_busy(self, text="Analyzing..."):
        self.analyze_btn.config(state=DISABLED)
        self.status_var.set(text)
        self.progress.pack(side=LEFT, padx=8)
        self.progress.start(12)

    def stop_busy(self, text=""):
        self.progress.stop()
        self.progress.pack_forget()
        self.status_var.set(text)
        self.analyze_btn.config(state=NORMAL)
