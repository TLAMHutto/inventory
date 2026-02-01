import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox


DB_FILE = "inventory.json"


def load_db(path: Path) -> dict:
    if not path.exists():
        return {"parts": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e


def fmt_range(r: dict) -> str:
    # expects {"min":..., "max":..., "unit":...}
    try:
        lo = r.get("min")
        hi = r.get("max")
        unit = str(r.get("unit", "")).strip()
        if lo is None or hi is None:
            return ""
        if lo == hi:
            return f"{lo:g}{unit}" if isinstance(lo, (int, float)) else f"{lo}{unit}"
        # Use :g only if numeric
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            return f"{lo:g}-{hi:g}{unit}"
        return f"{lo}-{hi}{unit}"
    except Exception:
        return ""


class InventoryViewer(tk.Tk):
    def __init__(self, db_path: Path):
        super().__init__()
        self.title("Inventory Viewer")
        self.geometry("980x520")
        self.minsize(840, 420)

        self.db_path = db_path
        self.parts = []

        # Top controls
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Category:").pack(side="left")

        self.category_var = tk.StringVar(value="(All)")
        self.category_cb = ttk.Combobox(top, textvariable=self.category_var, state="readonly", width=22)
        self.category_cb.pack(side="left", padx=(6, 16))
        self.category_cb.bind("<<ComboboxSelected>>", lambda _e: self.refresh_table())

        # Optional quick text filter (remove if you truly only want category)
        ttk.Label(top, text="Search:").pack(side="left")
        self.search_var = tk.StringVar(value="")
        self.search_entry = ttk.Entry(top, textvariable=self.search_var, width=28)
        self.search_entry.pack(side="left", padx=(6, 16))
        self.search_entry.bind("<KeyRelease>", lambda _e: self.refresh_table())

        ttk.Button(top, text="Reload JSON", command=self.reload).pack(side="left")
        self.status_var = tk.StringVar(value=str(db_path))
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        # Table
                # Table
        cols = ("id", "category", "name", "voltage", "current", "qty", "notes")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=18)

        self.tree.heading("id", text="ID")
        self.tree.heading("category", text="Category")
        self.tree.heading("name", text="Name")
        self.tree.heading("voltage", text="Voltage")
        self.tree.heading("current", text="Current")
        self.tree.heading("qty", text="Qty")
        self.tree.heading("notes", text="Notes")

        self.tree.column("id", width=60, anchor="center")
        self.tree.column("category", width=120, anchor="w")
        self.tree.column("name", width=260, anchor="w")
        self.tree.column("voltage", width=120, anchor="w")
        self.tree.column("current", width=120, anchor="w")
        self.tree.column("qty", width=60, anchor="center")
        self.tree.column("notes", width=220, anchor="w")

        # Container for tree + scrollbars (PACK ONLY to avoid grid/pack conflicts)
        mid = ttk.Frame(self, padding=(10, 0, 10, 10))
        mid.pack(fill="both", expand=True)

        # Horizontal scrollbar goes at bottom
        hsb = ttk.Scrollbar(mid, orient="horizontal", command=self.tree.xview)
        hsb.pack(side="bottom", fill="x")

        # Vertical scrollbar goes at right
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        vsb.pack(side="right", fill="y")

        # Tree fills remaining space
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.pack(side="left", fill="both", expand=True)


        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)

        self.reload()

    def reload(self):
        try:
            db = load_db(self.db_path)
            raw_parts = db.get("parts", [])
            if not isinstance(raw_parts, list):
                raw_parts = []
            self.parts = raw_parts
            self.populate_category_dropdown()
            self.refresh_table()
            self.status_var.set(f"{self.db_path}  |  items: {len(self.parts)}")
        except Exception as e:
            messagebox.showerror("Load error", str(e))

    def populate_category_dropdown(self):
        cats = sorted({str(p.get("category", "")).strip() for p in self.parts if str(p.get("category", "")).strip()})
        values = ["(All)"] + cats
        self.category_cb["values"] = values
        if self.category_var.get() not in values:
            self.category_var.set("(All)")

    def refresh_table(self):
        # Clear
        for row in self.tree.get_children():
            self.tree.delete(row)

        selected_cat = self.category_var.get()
        search = self.search_var.get().strip().lower()

        def match(p: dict) -> bool:
            if selected_cat != "(All)":
                if str(p.get("category", "")).strip().lower() != selected_cat.lower():
                    return False
            if search:
                hay = " ".join([
                    str(p.get("category", "")),
                    str(p.get("name", "")),
                    str(p.get("notes", "")),
                    fmt_range(p.get("voltage", {}) if isinstance(p.get("voltage"), dict) else {}),
                    fmt_range(p.get("current", {}) if isinstance(p.get("current"), dict) else {}),
                ]).lower()
                return search in hay
            return True

        # Optional: stable ordering
        def sort_key(p: dict):
            return (str(p.get("category", "")).lower(), str(p.get("name", "")).lower(), int(p.get("id", 0) or 0))

        shown = 0
        for p in sorted(self.parts, key=sort_key):
            if not isinstance(p, dict):
                continue
            if not match(p):
                continue

            pid = p.get("id", "")
            cat = p.get("category", "")
            name = p.get("name", "")
            volt = fmt_range(p.get("voltage", {}) if isinstance(p.get("voltage"), dict) else {})
            curr = fmt_range(p.get("current", {}) if isinstance(p.get("current"), dict) else {})
            qty = p.get("quantity", "")
            notes = p.get("notes", "")

            self.tree.insert("", "end", values=(pid, cat, name, volt, curr, qty, notes))
            shown += 1

        self.status_var.set(f"{self.db_path}  |  showing: {shown} / {len(self.parts)}")


if __name__ == "__main__":
    db_path = Path(DB_FILE)
    app = InventoryViewer(db_path)
    app.mainloop()
