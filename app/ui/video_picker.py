"""Frame for choosing a video file."""

import os
from tkinter import LEFT, X, Button, Frame, Label, StringVar, filedialog

VIDEO_FILETYPES = [
    ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm"),
    ("All files", "*.*"),
]


class VideoPicker(Frame):
    def __init__(self, master, on_pick):
        super().__init__(master, padx=12, pady=12)
        self._on_pick = on_pick
        self.path_var = StringVar(value="No video selected.")
        Button(self, text="Choose Video...", command=self._choose).pack(side=LEFT)
        Label(self, textvariable=self.path_var, anchor="w", fg="#555").pack(
            side=LEFT, padx=10, fill=X, expand=True
        )

    def _choose(self):
        path = filedialog.askopenfilename(title="Choose a clip", filetypes=VIDEO_FILETYPES)
        if not path:
            return
        self.path_var.set(os.path.basename(path))
        self._on_pick(path)

    def set_label(self, text):
        self.path_var.set(text)
