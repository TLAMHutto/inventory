from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DB_VERSION = 1


# ----------------------------
# Models
# ----------------------------

@dataclass
class RangeSpec:
    min: float
    max: float
    unit: str

    def normalized(self) -> "RangeSpec":
        lo, hi = (self.min, self.max) if self.min <= self.max else (self.max, self.min)
        return RangeSpec(lo, hi, self.unit.strip())

    def fmt(self) -> str:
        r = self.normalized()
        if r.min == r.max:
            return f"{r.min:g}{r.unit}"
        return f"{r.min:g}-{r.max:g}{r.unit}"

    def key(self) -> str:
        r = self.normalized()
        return f"{r.min:g}-{r.max:g}{r.unit}".lower()


@dataclass
class Part:
    category: str
    name: str
    voltage: RangeSpec
    current: RangeSpec
    quantity: int
    notes: str = ""

    def normalized(self) -> "Part":
        return Part(
            category=self.category.strip(),
            name=self.name.strip(),
            voltage=self.voltage.normalized(),
            current=self.current.normalized(),
            quantity=int(self.quantity),
            notes=self.notes.strip(),
        )

    def dedupe_key(self) -> Tuple[str, str, str, str]:
        p = self.normalized()
        return (p.category.lower(), p.name.lower(), p.voltage.key(), p.current.key())


# ----------------------------
# DB
# ----------------------------

def empty_db() -> Dict[str, Any]:
    return {"version": DB_VERSION, "parts": []}


def load_db(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return empty_db()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return empty_db()

    if not isinstance(data, dict):
        return empty_db()
    if "parts" not in data or not isinstance(data["parts"], list):
        data["parts"] = []
    if "version" not in data:
        data["version"] = DB_VERSION
    return data


def save_db(path: Path, db: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")


def next_id(parts: List[Dict[str, Any]]) -> int:
    m = 0
    for p in parts:
        try:
            m = max(m, int(p.get("id", 0)))
        except Exception:
            pass
    return m + 1


def part_from_dict(d: Dict[str, Any]) -> Part:
    return Part(
        category=d["category"],
        name=d["name"],
        voltage=RangeSpec(**d["voltage"]),
        current=RangeSpec(**d["current"]),
        quantity=int(d["quantity"]),
        notes=str(d.get("notes", "")),
    )


def part_to_dict(p: Part) -> Dict[str, Any]:
    return asdict(p.normalized())


# ----------------------------
# Parsing + Validation
# ----------------------------

def parse_range(text: str, unit: str) -> RangeSpec:
    s = text.strip().lower().replace(" ", "")
    if not s:
        raise ValueError("range is empty")
    if not unit.strip():
        raise ValueError("unit is empty")

    if "-" in s:
        a, b = s.split("-", 1)
        lo = float(a)
        hi = float(b)
    else:
        lo = hi = float(s)
    return RangeSpec(lo, hi, unit.strip())


def validate_part(p: Part) -> Part:
    p = p.normalized()
    if not p.category:
        raise ValueError("category is required")
    if not p.name:
        raise ValueError("name is required")
    if p.quantity <= 0:
        raise ValueError("quantity must be > 0")
    if p.voltage.min < 0 or p.voltage.max < 0:
        raise ValueError("voltage cannot be negative")
    if p.current.min < 0 or p.current.max < 0:
        raise ValueError("current cannot be negative")
    return p


# ----------------------------
# UI helpers
# ----------------------------

def prompt(text: str, default: Optional[str] = None) -> str:
    if default is None:
        return input(f"{text}: ").strip()
    v = input(f"{text} [{default}]: ").strip()
    return v if v else default


def prompt_int(text: str, default: int) -> int:
    while True:
        raw = prompt(text, str(default))
        try:
            n = int(raw)
            if n <= 0:
                print("Enter a positive integer.")
                continue
            return n
        except ValueError:
            print("Enter a valid integer.")


def prompt_range(label: str, def_range: str, def_unit: str) -> RangeSpec:
    while True:
        r = prompt(f"{label} range (e.g. 1-24)", def_range)
        u = prompt(f"{label} unit (e.g. V, mA, A)", def_unit)
        try:
            return parse_range(r, u)
        except Exception as e:
            print(f"Invalid {label.lower()}: {e}")


def print_table(rows: List[List[str]]) -> None:
    if not rows:
        print("(no results)")
        return
    widths = [max(len(str(cell)) for cell in col) for col in zip(*rows)]
    for i, row in enumerate(rows):
        print("  ".join(str(cell).ljust(widths[j]) for j, cell in enumerate(row)))
        if i == 0:
            print("  ".join("-" * w for w in widths))


def tokenize(line: str) -> List[str]:
    # Supports quoted strings: add "DC-DC Buck" ...
    return shlex.split(line)


def help_text() -> str:
    return """Commands:
  help
  exit | quit

  add
      Interactive add prompt. Merges duplicates by spec (category+name+V-range+I-range).

  list [category]
      list            -> all
      list Sensor     -> only Sensor

  search <keywords...> [--cat <category>]
      search resistor 10k
      search dht --cat Sensor

  show <id>
      show 3

  remove <id> [-n <decrement>]
      remove 3        -> delete item
      remove 3 -n 2   -> decrement qty by 2 (removes if hits 0)

  edit <id>
      Interactive edit for an item.

Tips:
  - Put names with spaces in quotes: add then Name: "DC-DC Buck Converter"
"""


def matches_keywords(p: Part, keywords: List[str]) -> bool:
    hay = f"{p.category} {p.name} {p.notes} {p.voltage.fmt()} {p.current.fmt()}".lower()
    return all(k.lower() in hay for k in keywords)


# ----------------------------
# Actions
# ----------------------------

def action_add(db_path: Path, db: Dict[str, Any]) -> None:
    category = prompt("Category (Power/Sensor/Conductor/etc)")
    name = prompt("Name")
    voltage = prompt_range("Voltage", "1-24", "V")
    current = prompt_range("Current", "0-1", "A")
    qty = prompt_int("Quantity", 1)
    notes = prompt("Notes (optional)", "")

    p = validate_part(Part(category, name, voltage, current, qty, notes))
    parts: List[Dict[str, Any]] = db["parts"]

    # Merge duplicates by key
    k = p.dedupe_key()
    for item in parts:
        try:
            existing = part_from_dict(item)
        except Exception:
            continue
        if existing.dedupe_key() == k:
            item["quantity"] = int(item.get("quantity", 0)) + p.quantity
            save_db(db_path, db)
            print(f"Merged with existing item. New quantity: {item['quantity']}")
            return

    d = part_to_dict(p)
    d["id"] = next_id(parts)
    parts.append(d)
    save_db(db_path, db)
    print(f"Added. id={d['id']}")


def action_list(db: Dict[str, Any], category: Optional[str]) -> None:
    rows = [["ID", "Category", "Name", "Voltage", "Current", "Qty"]]
    for d in db["parts"]:
        try:
            p = part_from_dict(d)
        except Exception:
            continue
        if category and p.category.lower() != category.lower():
            continue
        rows.append([str(d.get("id", "")), p.category, p.name, p.voltage.fmt(), p.current.fmt(), str(p.quantity)])
    print_table(rows)


def action_search(db: Dict[str, Any], keywords: List[str], category: Optional[str]) -> None:
    rows = [["ID", "Category", "Name", "Voltage", "Current", "Qty"]]
    for d in db["parts"]:
        try:
            p = part_from_dict(d)
        except Exception:
            continue
        if category and p.category.lower() != category.lower():
            continue
        if matches_keywords(p, keywords):
            rows.append([str(d.get("id", "")), p.category, p.name, p.voltage.fmt(), p.current.fmt(), str(p.quantity)])
    print_table(rows)


def action_show(db: Dict[str, Any], id_: int) -> None:
    for d in db["parts"]:
        if int(d.get("id", -1)) == id_:
            p = part_from_dict(d)
            print(f"ID:       {d.get('id')}")
            print(f"Category: {p.category}")
            print(f"Name:     {p.name}")
            print(f"Voltage:  {p.voltage.fmt()}")
            print(f"Current:  {p.current.fmt()}")
            print(f"Quantity: {p.quantity}")
            if p.notes:
                print(f"Notes:    {p.notes}")
            return
    print("Not found.")


def action_remove(db_path: Path, db: Dict[str, Any], id_: int, decrement: Optional[int]) -> None:
    parts = db["parts"]
    for i, d in enumerate(parts):
        if int(d.get("id", -1)) == id_:
            if decrement is None:
                parts.pop(i)
                save_db(db_path, db)
                print("Deleted.")
                return
            if decrement <= 0:
                print("Decrement must be > 0.")
                return
            q = int(d.get("quantity", 0))
            q2 = q - decrement
            if q2 > 0:
                d["quantity"] = q2
                save_db(db_path, db)
                print(f"Decremented. New quantity: {q2}")
            else:
                parts.pop(i)
                save_db(db_path, db)
                print("Quantity hit 0; removed.")
            return
    print("Not found.")


def action_edit(db_path: Path, db: Dict[str, Any], id_: int) -> None:
    for d in db["parts"]:
        if int(d.get("id", -1)) == id_:
            p = part_from_dict(d)

            category = prompt("Category", p.category)
            name = prompt("Name", p.name)

            v_def = f"{p.voltage.min:g}-{p.voltage.max:g}" if p.voltage.min != p.voltage.max else f"{p.voltage.min:g}"
            i_def = f"{p.current.min:g}-{p.current.max:g}" if p.current.min != p.current.max else f"{p.current.min:g}"

            voltage = prompt_range("Voltage", v_def, p.voltage.unit)
            current = prompt_range("Current", i_def, p.current.unit)
            qty = prompt_int("Quantity", p.quantity)
            notes = prompt("Notes", p.notes)

            updated = validate_part(Part(category, name, voltage, current, qty, notes))
            d.update(part_to_dict(updated))
            save_db(db_path, db)
            print("Updated.")
            return
    print("Not found.")


# ----------------------------
# REPL
# ----------------------------

def repl(db_path: Path) -> None:
    db = load_db(db_path)
    print("Electrical Inventory CLI")
    print(f"DB: {db_path.resolve()}")
    print("Type 'help' for commands.\n")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not line:
            continue

        try:
            args = tokenize(line)
        except ValueError as e:
            print(f"Parse error: {e}")
            continue

        cmd = args[0].lower()

        if cmd in ("exit", "quit"):
            break
        if cmd == "help":
            print(help_text())
            continue

        # Reload each loop in case user edits file externally
        db = load_db(db_path)

        try:
            if cmd == "add":
                action_add(db_path, db)

            elif cmd == "list":
                category = args[1] if len(args) >= 2 else None
                action_list(db, category)

            elif cmd == "search":
                if len(args) < 2:
                    print("Usage: search <keywords...> [--cat <category>]")
                    continue
                # parse optional --cat
                category = None
                keywords: List[str] = []
                i = 1
                while i < len(args):
                    if args[i] == "--cat" and i + 1 < len(args):
                        category = args[i + 1]
                        i += 2
                    else:
                        keywords.append(args[i])
                        i += 1
                action_search(db, keywords, category)

            elif cmd == "show":
                if len(args) != 2:
                    print("Usage: show <id>")
                    continue
                action_show(db, int(args[1]))

            elif cmd == "remove":
                if len(args) not in (2, 4):
                    print("Usage: remove <id> [-n <decrement>]")
                    continue
                id_ = int(args[1])
                dec = None
                if len(args) == 4:
                    if args[2] != "-n":
                        print("Usage: remove <id> [-n <decrement>]")
                        continue
                    dec = int(args[3])
                action_remove(db_path, db, id_, dec)

            elif cmd == "edit":
                if len(args) != 2:
                    print("Usage: edit <id>")
                    continue
                action_edit(db_path, db, int(args[1]))

            else:
                print("Unknown command. Type 'help' for a list of commands.")

        except Exception as e:
            print(f"Error: {e}")


def main() -> None:
    db_path = Path("inventory.json")
    repl(db_path)


if __name__ == "__main__":
    main()
