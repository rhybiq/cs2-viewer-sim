"""Optional-layer toggles.

The primary AI-viewer toggle stays visible at all times; everything else
(persona customization, multi-persona panel, OCR) lives behind a collapsible
"Advanced options" section so it doesn't compete for attention with the main
pick-video -> analyze flow.
"""

import webbrowser
from tkinter import DISABLED, END, LEFT, NORMAL, X, BooleanVar, StringVar, Text, ttk

from app.services import ollama
from app.ui.collapsible import CollapsibleSection


class OptionsPanel(ttk.Frame):
    def __init__(self, master, on_pull_model=None):
        super().__init__(master, style="Card.TFrame", padding=16)
        self._on_pull_model = on_pull_model

        vlm_row = ttk.Frame(self, style="Card.TFrame")
        vlm_row.pack(fill=X)
        self.vlm_var = BooleanVar(value=False)
        self.vlm_check = ttk.Checkbutton(
            vlm_row, text="Also run local AI viewer (needs Ollama running)",
            variable=self.vlm_var, state=DISABLED,
        )
        self.vlm_check.pack(side=LEFT)
        self.vlm_status_label = ttk.Label(vlm_row, text="checking for Ollama...", style="CardMuted.TLabel")
        self.vlm_status_label.pack(side=LEFT, padx=8)
        self.pull_btn = ttk.Button(
            vlm_row, text=f"Pull {ollama.DEFAULT_MODEL} (~6GB)", command=self._on_pull_clicked
        )
        self.download_btn = ttk.Button(
            vlm_row, text="Download Ollama", command=self._on_download_clicked
        )
        self._ollama_available = False
        self._model_available = False

        self.advanced = CollapsibleSection(self, "Advanced: personas & text overlay quality")
        self.advanced.pack(fill=X, pady=(10, 0))
        body = self.advanced.body

        ttk.Label(body, text="Persona (optional, e.g. \"a cooking-video fan\"):",
                  style="CardMuted.TLabel").pack(anchor="w")
        self.persona_var = StringVar(value="")
        ttk.Entry(body, textvariable=self.persona_var).pack(fill=X, pady=(2, 10))

        self.personas_var = BooleanVar(value=False)
        self.personas_check = ttk.Checkbutton(
            body, text="Simulate multiple viewer personas instead (slower, several Ollama calls)",
            variable=self.personas_var, state=DISABLED,
        )
        self.personas_check.pack(anchor="w")

        ttk.Label(body, text="Custom personas for the panel (optional, one per line as "
                             "name: description -- replaces the built-in 3 when non-empty):",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(10, 2))
        self.persona_set_text = Text(body, height=3, wrap="word", relief="solid", borderwidth=1)
        self.persona_set_text.pack(fill=X)

        ocr_row = ttk.Frame(body, style="Card.TFrame")
        ocr_row.pack(fill=X, pady=(12, 0))
        self.ocr_var = BooleanVar(value=False)
        self.ocr_check = ttk.Checkbutton(
            ocr_row, text="Also check text overlay quality (captions + HUD legibility)",
            variable=self.ocr_var, state=DISABLED,
        )
        self.ocr_check.pack(side=LEFT)
        self.ocr_status_label = ttk.Label(ocr_row, text="checking for EasyOCR...", style="CardMuted.TLabel")
        self.ocr_status_label.pack(side=LEFT, padx=8)
        self._ocr_available = False

    def _on_pull_clicked(self):
        if self._on_pull_model:
            self._on_pull_model()

    def _on_download_clicked(self):
        webbrowser.open(ollama.DOWNLOAD_URL)

    def set_ollama_status(self, available, installed=True):
        self._ollama_available = available
        if not available:
            self.vlm_var.set(False)
            self.personas_var.set(False)
            self.vlm_check.config(state=DISABLED)
            self.personas_check.config(state=DISABLED)
            self.pull_btn.pack_forget()
            if installed:
                self.download_btn.pack_forget()
                self.vlm_status_label.config(text="Ollama installed but not running (optional)")
            else:
                self.vlm_status_label.config(text="Ollama not installed (optional)")
                self.download_btn.pack(side=LEFT, padx=8)
        else:
            self.download_btn.pack_forget()

    def set_model_status(self, available):
        """Whether the specific VLM model (not just the Ollama server) is pulled."""
        self._model_available = available
        if not self._ollama_available:
            return
        if available:
            self.vlm_check.config(state=NORMAL)
            self.personas_check.config(state=NORMAL)
            self.pull_btn.pack_forget()
            self.vlm_status_label.config(text="Ollama + model detected", foreground="#16a34a")
        else:
            self.vlm_check.config(state=DISABLED)
            self.personas_check.config(state=DISABLED)
            self.vlm_status_label.config(text=f"Ollama detected, but {ollama.DEFAULT_MODEL} isn't pulled")
            self.pull_btn.pack(side=LEFT, padx=8)

    def set_pulling(self, in_progress):
        if in_progress:
            self.pull_btn.config(state=DISABLED, text="Pulling... (this can take a while)")
        else:
            self.pull_btn.config(state=NORMAL, text=f"Pull {ollama.DEFAULT_MODEL} (~6GB)")

    def set_ocr_status(self, available):
        self._ocr_available = available
        if available:
            self.ocr_check.config(state=NORMAL)
            self.ocr_status_label.config(text="EasyOCR detected", foreground="#16a34a")
        else:
            self.ocr_var.set(False)
            self.ocr_check.config(state=DISABLED)
            self.ocr_status_label.config(
                text="EasyOCR not installed (optional, pip install -r requirements-ocr.txt)"
            )

    @property
    def use_vlm(self):
        return self._ollama_available and self._model_available and self.vlm_var.get()

    @property
    def use_personas(self):
        return self._ollama_available and self._model_available and self.personas_var.get()

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
