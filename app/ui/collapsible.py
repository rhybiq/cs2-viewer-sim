"""A click-to-expand section, used to tuck away advanced/rarely-used controls."""

from tkinter import BOTH, X, ttk

from app.ui import theme


class CollapsibleSection(ttk.Frame):
    def __init__(self, master, title, start_expanded=False):
        super().__init__(master, style="Card.TFrame")
        self._expanded = start_expanded

        self.toggle_var_text = f"{title}"
        self.header = ttk.Button(
            self, style="TButton", command=self._toggle,
            text=self._header_text(),
        )
        self.header.pack(fill=X, padx=1, pady=1)

        self.body = ttk.Frame(self, style="Card.TFrame", padding=(12, 8))
        if self._expanded:
            self.body.pack(fill=BOTH, expand=True)

    def _header_text(self):
        arrow = "▾" if self._expanded else "▸"
        return f"{arrow}  {self.toggle_var_text}"

    def _toggle(self):
        self._expanded = not self._expanded
        self.header.config(text=self._header_text())
        if self._expanded:
            self.body.pack(fill=BOTH, expand=True)
        else:
            self.body.pack_forget()
