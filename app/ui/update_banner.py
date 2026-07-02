"""Banner shown when a newer release is available, offering to update or download it."""

from tkinter import DISABLED, LEFT, NORMAL, X, ttk


class UpdateBanner(ttk.Frame):
    def __init__(self, master, on_click):
        super().__init__(master)
        self._on_click = on_click
        self.btn = ttk.Button(self, command=self._clicked)
        self.btn.pack(side=LEFT)
        self._visible = False

    def _clicked(self):
        self._on_click()

    def show(self, tag, action_text):
        self.btn.config(text=f"Update available: {tag} -- {action_text}")
        if not self._visible:
            self.pack(fill=X, pady=(0, 10))
            self._visible = True

    def hide(self):
        if self._visible:
            self.pack_forget()
            self._visible = False

    def set_busy(self, busy, text=None):
        self.btn.config(state=DISABLED if busy else NORMAL)
        if text:
            self.btn.config(text=text)
