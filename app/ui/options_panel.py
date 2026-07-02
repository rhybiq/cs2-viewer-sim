"""Frame holding the optional-layer toggles: local AI viewer (Ollama) and text overlay quality (EasyOCR)."""

from tkinter import (
    DISABLED, END, LEFT, NORMAL, TOP, X, BooleanVar, Checkbutton, Entry, Frame, Label,
    StringVar, Text,
)


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

        persona_row = Frame(self)
        persona_row.pack(side=TOP, fill=X)
        Label(persona_row, text="  Persona (optional, e.g. \"a cooking-video fan\"):", fg="#555").pack(side=LEFT)
        self.persona_var = StringVar(value="")
        self.persona_entry = Entry(persona_row, textvariable=self.persona_var, width=40)
        self.persona_entry.pack(side=LEFT, padx=6, fill=X, expand=True)

        personas_row = Frame(self)
        personas_row.pack(side=TOP, fill=X)
        self.personas_var = BooleanVar(value=False)
        self.personas_check = Checkbutton(
            personas_row,
            text="  Simulate multiple viewer personas instead (slower, several Ollama calls)",
            variable=self.personas_var, state=DISABLED,
        )
        self.personas_check.pack(side=LEFT)

        Label(self, text="  Custom personas for the panel (optional, one per line as "
                         "name: description -- replaces the built-in 3 when non-empty):",
              fg="#555").pack(side=TOP, anchor="w")
        self.persona_set_text = Text(self, height=3, wrap="word")
        self.persona_set_text.pack(side=TOP, fill=X)

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
            self.personas_check.config(state=NORMAL)
            self.vlm_status_label.config(text="Ollama detected", fg="#1a7f37")
        else:
            self.vlm_var.set(False)
            self.personas_var.set(False)
            self.vlm_check.config(state=DISABLED)
            self.personas_check.config(state=DISABLED)
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
    def use_personas(self):
        return self._ollama_available and self.personas_var.get()

    @property
    def use_ocr(self):
        return self._ocr_available and self.ocr_var.get()

    @property
    def persona_text(self):
        """Free-text persona override for single-viewer (--vlm) mode, or '' for the default."""
        return self.persona_var.get().strip()

    @property
    def custom_personas(self):
        """Parsed {name: description} dict from the multi-line box, or None if empty."""
        raw = self.persona_set_text.get("1.0", END).strip()
        if not raw:
            return None
        personas = {}
        for line in raw.splitlines():
            if ":" in line:
                name, desc = line.split(":", 1)
                name, desc = name.strip(), desc.strip()
                if name and desc:
                    personas[name] = desc
        return personas or None
