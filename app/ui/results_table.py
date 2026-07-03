"""Treeview showing per-metric verdicts for the current report."""

from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, Y, Menu, ttk

VERDICT_COLOR = {"good": "#16a34a", "warn": "#d97706", "bad": "#dc2626"}
VERDICT_LABEL = {"good": "● Good", "warn": "● Warn", "bad": "● Bad"}
ROW_BG = {"odd": "#ffffff", "even": "#fafafa"}


class ResultsTable(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=(0, 8))
        cols = ("metric", "value", "range", "verdict", "note")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=8)
        headings = {"metric": "Metric", "value": "Value", "range": "Range",
                    "verdict": "Verdict", "note": "Note"}
        for c, w in zip(cols, (120, 60, 230, 70, 280)):
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=w, anchor="w")
        for verdict, color in VERDICT_COLOR.items():
            self.tree.tag_configure(verdict, foreground=color)
        self.tree.tag_configure("odd", background=ROW_BG["odd"])
        self.tree.tag_configure("even", background=ROW_BG["even"])
        scroll = ttk.Scrollbar(self, orient=VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)

        self._menu = Menu(self.tree, tearoff=0)
        self._menu.add_command(label="Copy note", command=self._copy_note)
        self._menu.add_command(label="Copy row", command=self._copy_row)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Control-c>", lambda e: self._copy_row())

    def _on_right_click(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self._menu.tk_popup(event.x_root, event.y_root)

    def _copy_note(self):
        sel = self.tree.selection()
        if not sel:
            return
        note = self.tree.set(sel[0], "note")
        self.clipboard_clear()
        self.clipboard_append(note)

    def _copy_row(self):
        sel = self.tree.selection()
        if not sel:
            return
        values = self.tree.item(sel[0], "values")
        self.clipboard_clear()
        self.clipboard_append("\t".join(str(v) for v in values))

    def clear(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

    def load_report(self, rep):
        self.clear()
        rows = list(rep.metrics)
        if rep.flat_stretches:
            rows.append({
                "name": "flat_stretches", "value": len(rep.flat_stretches), "verdict": "warn",
                "note": ", ".join(f"{s}-{e}s" for s, e in rep.flat_stretches),
            })
        for i, m in enumerate(rows):
            stripe = "odd" if i % 2 == 0 else "even"
            self.tree.insert(
                "", END,
                values=(m["name"], m["value"], m.get("scale", ""),
                        VERDICT_LABEL.get(m["verdict"], m["verdict"]), m["note"]),
                tags=(m["verdict"], stripe),
            )
