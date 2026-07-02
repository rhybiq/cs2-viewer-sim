"""Panel showing the simulated-viewer (VLM) notes -- hook text/SFX suggestions, swipe point, etc."""

from tkinter import BOTH, DISABLED, END, NORMAL, Frame, Label, Text

import viewer_sim as vs


class VlmPanel(Frame):
    def __init__(self, master):
        super().__init__(master, padx=12, pady=(0, 8))
        self.label = Label(self, text="Simulated viewer (AI)", font=("Segoe UI", 9, "bold"))
        self.text = Text(self, height=6, wrap="word", state=DISABLED, relief="flat", bg="#f5f5f5")
        self._visible = False

    def show(self, vlm_notes):
        lines = vs.format_vlm_notes(vlm_notes)
        if not self._visible:
            self.label.pack(anchor="w")
            self.text.pack(fill=BOTH, expand=False)
            self._visible = True
        self.text.config(state=NORMAL)
        self.text.delete("1.0", END)
        self.text.insert(END, "\n".join(f"- {line}" for line in lines))
        self.text.config(state=DISABLED)

    def hide(self):
        if self._visible:
            self.label.pack_forget()
            self.text.pack_forget()
            self._visible = False
