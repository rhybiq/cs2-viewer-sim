"""Report auto-export control: lives next to the Analyze button on each tab.
Tick a format before hitting Analyze; when that tab's analysis completes, the
report is written automatically -- next to the source video by default, or to
a chosen folder. No separate save button/dialog for the formats themselves --
ticking nothing means nothing gets saved.
"""

import os
from tkinter import DISABLED, LEFT, X, BooleanVar, StringVar, filedialog, ttk

from app.services import reports
from app.ui import icons, theme


class QuickReportExport(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.folder_var = StringVar(value="")  # "" = default to the video's own folder

        checks_row = ttk.Frame(self)
        checks_row.pack(fill=X, anchor="w")
        self.html_var = BooleanVar(value=False)
        ttk.Checkbutton(checks_row, text="Save HTML", variable=self.html_var).pack(side=LEFT)
        self.json_var = BooleanVar(value=False)
        ttk.Checkbutton(checks_row, text="Save JSON", variable=self.json_var).pack(side=LEFT, padx=(12, 0))
        # Placeholder for persisting analysis history (e.g. for future before/after
        # comparison across re-edits) -- not wired up to anything yet.
        self.memory_var = BooleanVar(value=False)
        ttk.Checkbutton(
            checks_row, text="Save in memory", variable=self.memory_var, state=DISABLED
        ).pack(side=LEFT, padx=(12, 0))

        folder_row = ttk.Frame(self)
        folder_row.pack(fill=X, anchor="w", pady=(4, 0))
        ttk.Label(folder_row, text="Save to:", style="CardMuted.TLabel").pack(side=LEFT)
        self.folder_label = ttk.Label(folder_row, text="(same folder as the video)", style="CardMuted.TLabel")
        self.folder_label.pack(side=LEFT, padx=(4, 8))
        ttk.Button(
            folder_row, text="Choose folder...", command=self._choose_folder,
            image=icons.get("folder", theme.TEXT), compound=LEFT,
        ).pack(side=LEFT)

    def _choose_folder(self):
        chosen = filedialog.askdirectory()
        if chosen:
            self.folder_var.set(chosen)
            self.folder_label.config(text=chosen)

    def maybe_export(self, report, video_path):
        """Writes whichever formats are ticked, to the chosen folder (or next
        to video_path by default), named after the video. Returns the list of
        paths written (empty if nothing was ticked).
        """
        if not (self.html_var.get() or self.json_var.get()):
            return []
        out_dir = self.folder_var.get() or os.path.dirname(video_path)
        base = os.path.splitext(os.path.basename(video_path))[0]
        written = []
        if self.html_var.get():
            out = os.path.join(out_dir, f"{base}_report.html")
            reports.save_html(report, out)
            written.append(out)
        if self.json_var.get():
            out = os.path.join(out_dir, f"{base}_report.json")
            reports.save_json(report, out)
            written.append(out)
        return written
