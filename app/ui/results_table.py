"""Treeview showing per-metric verdicts for the current report."""

from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, Y, Frame, ttk

VERDICT_COLOR = {"good": "#1a7f37", "warn": "#9a6700", "bad": "#cf222e"}


class ResultsTable(Frame):
    def __init__(self, master):
        super().__init__(master, padx=12, pady=8)
        cols = ("metric", "value", "range", "verdict", "note")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=8)
        for c, w in zip(cols, (110, 60, 220, 60, 260)):
            self.tree.heading(c, text=c.capitalize())
            self.tree.column(c, width=w, anchor="w")
        for verdict, color in VERDICT_COLOR.items():
            self.tree.tag_configure(verdict, foreground=color)
        scroll = ttk.Scrollbar(self, orient=VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)

    def clear(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

    def load_report(self, rep):
        self.clear()
        for m in rep.metrics:
            self.tree.insert(
                "", END,
                values=(m["name"], m["value"], m.get("scale", ""), m["verdict"], m["note"]),
                tags=(m["verdict"],),
            )
        if rep.flat_stretches:
            self.tree.insert(
                "", END,
                values=("flat_stretches", len(rep.flat_stretches), "", "warn",
                        ", ".join(f"{s}-{e}s" for s, e in rep.flat_stretches)),
                tags=("warn",),
            )
