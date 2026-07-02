"""Row with the Save HTML / Save JSON report buttons."""

import webbrowser
from tkinter import DISABLED, LEFT, NORMAL, filedialog, messagebox, ttk

from app.services import reports


class ReportActions(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=(0, 10))
        self.report = None
        self.html_btn = ttk.Button(self, text="Save HTML Report...", command=self.save_html, state=DISABLED)
        self.html_btn.pack(side=LEFT)
        self.json_btn = ttk.Button(self, text="Save JSON Report...", command=self.save_json, state=DISABLED)
        self.json_btn.pack(side=LEFT, padx=8)

    def set_report(self, report):
        self.report = report
        state = NORMAL if report else DISABLED
        self.html_btn.config(state=state)
        self.json_btn.config(state=state)

    def save_html(self):
        if not self.report:
            return
        out = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML", "*.html")])
        if not out:
            return
        reports.save_html(self.report, out)
        if messagebox.askyesno("Report saved", f"Saved to {out}\nOpen it now?"):
            webbrowser.open(out)

    def save_json(self):
        if not self.report:
            return
        out = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not out:
            return
        reports.save_json(self.report, out)
        messagebox.showinfo("Report saved", f"Saved to {out}")
