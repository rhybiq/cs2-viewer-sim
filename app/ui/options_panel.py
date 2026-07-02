"""Frame holding the optional local-AI-viewer (Ollama) toggle."""

from tkinter import DISABLED, LEFT, NORMAL, BooleanVar, Checkbutton, Frame, Label


class OptionsPanel(Frame):
    def __init__(self, master):
        super().__init__(master, padx=12)
        self.vlm_var = BooleanVar(value=False)
        self.vlm_check = Checkbutton(
            self, text="Also run local AI viewer (needs Ollama running)",
            variable=self.vlm_var, state=DISABLED,
        )
        self.vlm_check.pack(side=LEFT)
        self.status_label = Label(self, text="checking for Ollama...", fg="#888")
        self.status_label.pack(side=LEFT, padx=8)
        self._ollama_available = False

    def set_ollama_status(self, available):
        self._ollama_available = available
        if available:
            self.vlm_check.config(state=NORMAL)
            self.status_label.config(text="Ollama detected", fg="#1a7f37")
        else:
            self.vlm_var.set(False)
            self.vlm_check.config(state=DISABLED)
            self.status_label.config(text="Ollama not found (optional)", fg="#888")

    @property
    def use_vlm(self):
        return self._ollama_available and self.vlm_var.get()
