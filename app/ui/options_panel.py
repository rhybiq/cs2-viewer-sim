"""Optional-layer controls, split so they can live in different places in the
tabbed layout: Ollama status is global (relevant regardless of tab), the AI
viewer/persona config lives in the AI Viewer tab, and the OCR toggle lives in
the Analyze tab alongside the other core options.
"""

import webbrowser
from tkinter import DISABLED, END, LEFT, NORMAL, X, BooleanVar, DoubleVar, IntVar, StringVar, Text, ttk

import viewer_sim as vs
from app.services import ollama
from app.ui import icons, theme


class OllamaStatusRow(ttk.Frame):
    """Global, tab-independent: whether Ollama and the VLM model are available."""

    def __init__(self, master, on_pull_model=None):
        super().__init__(master, style="Card.TFrame", padding=(16, 8))
        self._on_pull_model = on_pull_model
        self.status_label = ttk.Label(self, text="checking for Ollama...", style="CardMuted.TLabel")
        self.status_label.pack(side=LEFT)
        self.pull_btn = ttk.Button(
            self, text=f"Pull {ollama.DEFAULT_MODEL} (~6GB)", command=self._on_pull_clicked,
            image=icons.get("download", theme.TEXT), compound=LEFT,
        )
        self.download_btn = ttk.Button(
            self, text="Download Ollama", command=self._on_download_clicked,
            image=icons.get("download", theme.TEXT), compound=LEFT,
        )
        self._ollama_available = False
        self._model_available = False

    def _on_pull_clicked(self):
        if self._on_pull_model:
            self._on_pull_model()

    def _on_download_clicked(self):
        webbrowser.open(ollama.DOWNLOAD_URL)

    def set_ollama_status(self, available, installed=True):
        self._ollama_available = available
        if not available:
            self.pull_btn.pack_forget()
            if installed:
                self.download_btn.pack_forget()
                self.status_label.config(
                    text="Ollama installed but not running (optional)", foreground="", image=""
                )
            else:
                self.status_label.config(text="Ollama not installed (optional)", foreground="", image="")
                self.download_btn.pack(side=LEFT, padx=8)
        else:
            self.download_btn.pack_forget()

    def set_model_status(self, available):
        self._model_available = available
        if not self._ollama_available:
            return
        if available:
            self.pull_btn.pack_forget()
            self.status_label.config(
                text="Ollama + model detected", foreground=theme.GOOD,
                image=icons.get("check", theme.GOOD), compound=LEFT,
            )
        else:
            self.status_label.config(
                text=f"Ollama detected, but {ollama.DEFAULT_MODEL} isn't pulled",
                foreground="", image="",
            )
            self.pull_btn.pack(side=LEFT, padx=8)

    def set_pulling(self, in_progress):
        if in_progress:
            self.pull_btn.config(state=DISABLED, text="Pulling... (this can take a while)")
        else:
            self.pull_btn.config(state=NORMAL, text=f"Pull {ollama.DEFAULT_MODEL} (~6GB)")

    @property
    def ready(self):
        return self._ollama_available and self._model_available


class AiViewerOptions(ttk.Frame):
    """Lives in the AI Viewer tab: fully independent of the Analyze tab -- has
    its own Analyze button (see main_window.py), so these controls are just
    "single viewer vs. persona panel" mode config, not a run/don't-run toggle.
    """

    def __init__(self, master):
        super().__init__(master, style="Card.TFrame", padding=16)

        ttk.Label(self, text="Persona (optional, e.g. \"a cooking-video fan\") -- "
                             "used unless the persona panel below is enabled:",
                  style="CardMuted.TLabel").pack(anchor="w")
        self.persona_var = StringVar(value="")
        ttk.Entry(self, textvariable=self.persona_var).pack(fill=X, pady=(2, 10))

        fps_row = ttk.Frame(self, style="Card.TFrame")
        fps_row.pack(fill=X, pady=(0, 10))
        ttk.Label(fps_row, text="Frames per second sampled:", style="CardMuted.TLabel").pack(side=LEFT)
        self.sample_fps_var = DoubleVar(value=vs.VLM_DEFAULT_SAMPLE_FPS)
        ttk.Spinbox(
            fps_row, from_=0.5, to=4.0, increment=0.5, textvariable=self.sample_fps_var,
            width=5, format="%.1f",
        ).pack(side=LEFT, padx=(6, 8))
        ttk.Label(
            fps_row, text="(higher = more detail per call, slower; capped regardless of clip length)",
            style="CardMuted.TLabel",
        ).pack(side=LEFT)

        personas_row = ttk.Frame(self, style="Card.TFrame")
        personas_row.pack(fill=X)
        self.personas_var = BooleanVar(value=False)
        self.personas_check = ttk.Checkbutton(
            personas_row, text="Use a panel of viewer personas instead (slower, several Ollama calls)",
            variable=self.personas_var, state=DISABLED, command=self._sync_count_state,
        )
        self.personas_check.pack(side=LEFT)
        ttk.Label(personas_row, text="Number of viewers:", style="CardMuted.TLabel").pack(side=LEFT, padx=(16, 4))
        self.count_var = IntVar(value=3)
        self.count_spin = ttk.Spinbox(
            personas_row, from_=1, to=100, textvariable=self.count_var, width=5, state=DISABLED
        )
        self.count_spin.pack(side=LEFT)

        ttk.Label(self, text="Custom personas for the panel (optional, one per line as "
                             "name: description -- replaces the generated pool when non-empty):",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(12, 2))
        self.persona_set_text = Text(self, height=3, wrap="word", relief="solid", borderwidth=1)
        self.persona_set_text.pack(fill=X)

        self._ollama_available = False
        self._model_available = False

    def _sync_count_state(self):
        ready = self._ollama_available and self._model_available
        self.count_spin.config(state=NORMAL if (ready and self.personas_var.get()) else DISABLED)

    def set_ollama_status(self, available):
        self._ollama_available = available
        if not available:
            self.personas_var.set(False)
            self.personas_check.config(state=DISABLED)
        self._sync_count_state()

    def set_model_status(self, available):
        self._model_available = available
        if not self._ollama_available:
            return
        self.personas_check.config(state=NORMAL if available else DISABLED)
        self._sync_count_state()

    @property
    def ready(self):
        return self._ollama_available and self._model_available

    @property
    def use_personas(self):
        return self.personas_var.get()

    @property
    def persona_text(self):
        """Free-text persona override for single-viewer (--vlm) mode, or '' for the default."""
        return self.persona_var.get().strip()

    @property
    def persona_count(self):
        try:
            n = int(self.count_var.get())
        except (ValueError, TypeError):
            return 3
        return max(1, min(100, n))

    @property
    def sample_fps(self):
        try:
            fps = float(self.sample_fps_var.get())
        except (ValueError, TypeError):
            return vs.VLM_DEFAULT_SAMPLE_FPS
        return max(0.1, min(4.0, fps))

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


class OcrToggle(ttk.Frame):
    """Lives in the Analyze tab: the deterministic OCR-based text-overlay check."""

    def __init__(self, master):
        super().__init__(master, style="Card.TFrame", padding=(16, 10))
        self.ocr_var = BooleanVar(value=False)
        self.ocr_check = ttk.Checkbutton(
            self, text="Also check text overlay quality (captions + HUD legibility)",
            variable=self.ocr_var, state=DISABLED,
        )
        self.ocr_check.pack(side=LEFT)
        self.ocr_status_label = ttk.Label(self, text="checking for EasyOCR...", style="CardMuted.TLabel")
        self.ocr_status_label.pack(side=LEFT, padx=8)
        self._ocr_available = False

    def set_ocr_status(self, available):
        self._ocr_available = available
        if available:
            self.ocr_check.config(state=NORMAL)
            self.ocr_status_label.config(
                text="EasyOCR detected", foreground=theme.GOOD,
                image=icons.get("check", theme.GOOD), compound=LEFT,
            )
        else:
            self.ocr_var.set(False)
            self.ocr_check.config(state=DISABLED)
            self.ocr_status_label.config(
                text="EasyOCR not installed (optional, pip install -r requirements-ocr.txt)",
                foreground="", image="",
            )

    @property
    def use_ocr(self):
        return self._ocr_available and self.ocr_var.get()
