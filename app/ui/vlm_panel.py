"""Panel showing simulated-viewer results: single VLM pass or the multi-persona panel."""

from tkinter import BOTH, DISABLED, END, NORMAL, Frame, Label, Text

import viewer_sim as vs


class VlmPanel(Frame):
    def __init__(self, master):
        super().__init__(master, padx=12, pady=(0, 8))
        self.label = Label(self, text="Simulated viewer (AI)", font=("Segoe UI", 9, "bold"))
        self.text = Text(self, height=7, wrap="word", state=DISABLED, relief="flat", bg="#f5f5f5")
        self._visible = False

    def _display(self, title, body):
        if not self._visible:
            self.label.pack(anchor="w")
            self.text.pack(fill=BOTH, expand=False)
            self._visible = True
        self.label.config(text=title)
        self.text.config(state=NORMAL)
        self.text.delete("1.0", END)
        self.text.insert(END, body)
        self.text.config(state=DISABLED)

    def show_vlm(self, vlm_notes):
        lines = vs.format_vlm_notes(vlm_notes)
        self._display("Simulated viewer (AI)", "\n".join(f"- {line}" for line in lines))

    def show_personas(self, persona_notes, persona_summary):
        lines = []
        for key, notes in (persona_notes or {}).items():
            lines.append(f"[{key}]")
            lines.extend(f"  - {line}" for line in vs.format_vlm_notes(notes))
            lines.append("")
        if persona_summary:
            if "error" in persona_summary:
                lines.append(persona_summary["error"])
            else:
                lines.append(
                    f"Summary: {persona_summary['watched_to_end']} watched to the end, "
                    f"avg swipe ~{persona_summary['avg_swipe_second']}s, "
                    f"hook reads consensus: {persona_summary['hook_reads_consensus']}"
                )
        self._display("Simulated viewer panel (personas)", "\n".join(lines))

    def hide(self):
        if self._visible:
            self.label.pack_forget()
            self.text.pack_forget()
            self._visible = False
