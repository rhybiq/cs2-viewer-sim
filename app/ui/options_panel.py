"""Frame holding the optional-layer toggles: local AI viewer (Ollama) and text overlay quality (EasyOCR)."""

from tkinter import BOTTOM, DISABLED, LEFT, NORMAL, TOP, X, BooleanVar, Checkbutton, Frame, Label


class OptionsPanel(Frame):
    def __init__(self, master):
        super().__init__(master, padx=12)

        vlm_row = Frame(self)
        vlm_row.pack(side=TOP, fill=X)
        self.vlm_var = BooleanVar(value=False)
        self.vlm_check = Checkbutton(
            vlm_row, text="Also run local AI viewer (needs Ollama running)",
            variable=self.vlm_var, state=DISABLED,
        )
        self.vlm_check.pack(side=LEFT)
        self.vlm_status_label = Label(vlm_row, text="checking for Ollama...", fg="#888")
        self.vlm_status_label.pack(side=LEFT, padx=8)
        self._ollama_available = False

        ocr_row = Frame(self)
        ocr_row.pack(side=TOP, fill=X)
        self.ocr_var = BooleanVar(value=False)
        self.ocr_check = Checkbutton(
            ocr_row, text="Also check text overlay quality (captions + HUD legibility)",
            variable=self.ocr_var, state=DISABLED,
        )
        self.ocr_check.pack(side=LEFT)
        self.ocr_status_label = Label(ocr_row, text="checking for EasyOCR...", fg="#888")
        self.ocr_status_label.pack(side=LEFT, padx=8)
        self._ocr_available = False

    def set_ollama_status(self, available):
        self._ollama_available = available
        if available:
            self.vlm_check.config(state=NORMAL)
            self.vlm_status_label.config(text="Ollama detected", fg="#1a7f37")
        else:
            self.vlm_var.set(False)
            self.vlm_check.config(state=DISABLED)
            self.vlm_status_label.config(text="Ollama not found (optional)", fg="#888")

    def set_ocr_status(self, available):
        self._ocr_available = available
        if available:
            self.ocr_check.config(state=NORMAL)
            self.ocr_status_label.config(text="EasyOCR detected", fg="#1a7f37")
        else:
            self.ocr_var.set(False)
            self.ocr_check.config(state=DISABLED)
            self.ocr_status_label.config(
                text="EasyOCR not installed (optional, pip install -r requirements-ocr.txt)", fg="#888"
            )

    @property
    def use_vlm(self):
        return self._ollama_available and self.vlm_var.get()

    @property
    def use_ocr(self):
        return self._ocr_available and self.ocr_var.get()
