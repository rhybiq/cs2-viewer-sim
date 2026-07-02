"""Card for choosing a video file -- the entry point of the primary flow."""

import os
from tkinter import LEFT, X, StringVar, filedialog, ttk

VIDEO_FILETYPES = [
    ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm"),
    ("All files", "*.*"),
]


class VideoPicker(ttk.Frame):
    def __init__(self, master, on_pick):
        super().__init__(master, style="Card.TFrame", padding=16)
        self._on_pick = on_pick

        row = ttk.Frame(self, style="Card.TFrame")
        row.pack(fill=X)
        ttk.Button(row, text="Choose Video...", command=self._choose).pack(side=LEFT)
        self.path_var = StringVar(value="No video selected yet.")
        ttk.Label(row, textvariable=self.path_var, style="CardMuted.TLabel").pack(
            side=LEFT, padx=12, fill=X, expand=True
        )

    def _choose(self):
        path = filedialog.askopenfilename(title="Choose a clip", filetypes=VIDEO_FILETYPES)
        if not path:
            return
        self.path_var.set(os.path.basename(path))
        self._on_pick(path)

    def set_label(self, text):
        self.path_var.set(text)
