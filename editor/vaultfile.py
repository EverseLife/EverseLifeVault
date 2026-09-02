# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Reading and surgical editing of the vault's `data/recipes.yaml`.

The file is not rewritten by a YAML dumper. Every entry there is a one-line flow
mapping surrounded by comments that explain *why* the recipe looks the way it
does -- and those comments are the reason the vault exists at all (see the vault
CLAUDE.md). A dumper would flatten them on the first save, so the editor works at
the line level: it locates the line of one entry and replaces, inserts or drops
exactly that line. Everything else in the file stays byte-for-byte.

The safety net is double:

  1. every rendered line is parsed back and compared with the data it came from;
  2. the whole file is parsed after the edit, and the edit is rejected unless the
     document changed in exactly the expected way.

Derived numbers (amounts, labor, mass) are never written here: the build derives
them from labour (D-133), and the editor only shows what the last build produced.

Putting the lines on disk -- the last check, the backup, the undo -- is
`store.py`: the same door for every file the editor writes.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# The one word that stands for "no machine needed" (D-216), and the spoken name
# of a station -> the recipe that makes it. Mirrors tools/build.py: the
# authority is still `build.py --check`, which the editor runs after a save.
VIRTUAL_STATIONS = ("Руками",)
STATION_ALIASES = {"Печь": "Плавильная печь"}

# Kinds the editor offers in the dropdown. The list is merged with the kinds
# actually used in the file, so a kind added in the vault shows up by itself.
KNOWN_KINDS = (
    "station",
    "furniture",
    "tool",
    "gear",
    "vehicle",
    "material",
    "consumable",
    "money",
)

# The order of keys inside one entry, taken from the file as it is written today.
# Rendering by this list keeps a saved line indistinguishable from a hand-written
# one, so the diff of an edit is one line and not the whole block.
KEY_ORDER = (
    "name",
    "id",
    "kind",
    "built",
    "class",
    "bulk",
    "liquid",
    "edible",
    "key",
    "roles",
    "food",
    "hot",
    "slot",
    "store",
    "holds",
    "mass",
    "hours",
    "mix",
    "fuel",
    "inputs",
    "amounts",
    "weights",
    "station",
    "note",
    "highlight",
)

# One material of the registry (D-215): everything not made by a recipe.
MATERIAL_KEY_ORDER = (
    "name",
    "id",
    "class",
    "relic",
    "mass",
    "bulk",
    "liquid",
    "edible",
    "rate",
    "forage",
    "fuel",
    "note",
)

# Fields the editor is allowed to write. `manual_amounts` and everything derived
# is deliberately absent: it is computed by the build, not authored.
BOOL_FIELDS = ("built", "key", "mix", "roles", "food", "hot", "bulk", "liquid", "edible")
NUMBER_FIELDS = ("mass", "store", "hours", "fuel")
LIST_FIELDS = ("inputs", "highlight")
MAP_FIELDS = ("amounts", "weights")
#: What a container may hold (D-230): the one word the build accepts, or nothing.
HOLDS_VALUES = ("жидкость",)
#: The parts of a material's `forage` row (D-210, D-254).
FORAGE_KEYS = ("finds", "handful", "place")
MATERIAL_BOOL_FIELDS = ("relic", "bulk", "liquid", "edible")
MATERIAL_NUMBER_FIELDS = ("mass", "rate", "fuel")


class VaultError(Exception):
    """A refusal the user is meant to read: the text goes straight to the UI."""


def vault_root() -> Path:
    """Where the vault lies. The editor is part of it unless told otherwise."""
    env = os.environ.get("EVERSELIFE_VAULT")
    if env:
        root = Path(env).expanduser().resolve()
    else:
        # The editor lives inside the vault it edits: one directory up.
        root = Path(__file__).resolve().parent.parent
    if not (root / "data" / "recipes.yaml").exists():
        raise VaultError(
            f"вольт не найден: {root}\n"
            "Укажите путь переменной EVERSELIFE_VAULT."
        )
    return root


# ------------------------------------------------------------------ rendering


def _scalar(value: str) -> str:
    """A string as it is written inside a flow mapping.

    Plain is preferred -- that is how the file is written -- and quotes appear
    only where a plain scalar would change meaning or break the flow context.
    """
    if value == "":
        return '""'
    risky = any(ch in value for ch in ",[]{}:#&*!|>'\"%@`\\") or value != value.strip()
    looks_special = value.lower() in {
        "true",
        "false",
        "yes",
        "no",
        "on",
        "off",
        "null",
        "~",
    }
    if not risky and not looks_special:
        try:
            float(value)
        except ValueError:
            return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _number(value: float) -> str:
    """A number without an exponent: `1e-05` would parse back as a string.

    A whole number keeps the form it was read in: the registry writes the
    ingots' mass as `1.0`, and a line saved untouched must come out untouched.
    A form sends whole numbers as integers, so what is authored comes out `1`.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    number = float(value)
    if number.is_integer():
        return f"{int(number)}.0"
    text = f"{number:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "0", "-0") else repr(number)


def _flow(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return _scalar(value)
    if isinstance(value, list):
        return "[" + ", ".join(_flow(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_scalar(str(k))}: {_flow(v)}" for k, v in value.items()) + "}"
    raise VaultError(f"нечего записать: {value!r}")


def key_order(data: dict, order: tuple[str, ...], existing: list[str] | None = None) -> list[str]:
    """The keys of an entry in the order they are written.

    A new entry follows the canonical order. An entry already in the file keeps
    **its own** order -- the file is not uniform to the key (`mass` stands
    before `class` on one line and after it on the next), and a save that
    reshuffled an untouched line would put noise into every diff. A key the
    entry did not have before goes where the canonical order puts it, after the
    last of its present keys that the canon lists earlier.
    """
    if not existing:
        ordered = [key for key in order if key in data]
        return ordered + [key for key in data if key not in order]
    ordered = [key for key in existing if key in data]
    rank = {key: index for index, key in enumerate(order)}
    for key in data:
        if key in ordered:
            continue
        if key not in rank:
            ordered.append(key)
            continue
        seat = 0
        for index, present in enumerate(ordered):
            if rank.get(present, -1) < rank[key]:
                seat = index + 1
        ordered.insert(seat, key)
    return ordered


def render_entry(
    data: dict,
    indent: int,
    order: tuple[str, ...] = KEY_ORDER,
    existing: list[str] | None = None,
) -> str:
    """One entry as a line of the file, verified by parsing it back."""
    ordered = key_order(data, order, existing)
    body = ", ".join(f"{key}: {_flow(data[key])}" for key in ordered)
    line = " " * indent + "- {" + body + "}"
    back = yaml.safe_load(line[indent + 2 :])
    if _comparable(back) != _comparable(data):
        raise VaultError(f"строка не читается обратно так же, как записана: {line.strip()}")
    return line


def _comparable(value: Any) -> Any:
    """Numbers compared by value: 1 written back as 1.0 is still the same amount."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    if isinstance(value, dict):
        return {k: _comparable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_comparable(v) for v in value]
    return value


# -------------------------------------------------------------------- source


@dataclass
class Entry:
    """One flow mapping in the file, with the lines it occupies."""

    name: str
    start: int  # 0-based, inclusive
    end: int  # 0-based, inclusive
    indent: int
    data: dict


LEVEL_ID = re.compile(r"^  - id: (\d+)\s*$")
SECTION_ID = re.compile(r"^      - id: (\S+)\s*$")
RECIPES_KEY = re.compile(r"^(\s*)recipes:\s*$")


def scan_entries(lines: list[str]) -> list[Entry]:
    """Every `- {...}` block of the file, one Entry each.

    Operations wrap onto several lines, so braces are counted rather than lines.
    """
    entries: list[Entry] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped.startswith("- {"):
            index += 1
            continue
        buffer = stripped
        last = index
        while buffer.count("{") != buffer.count("}"):
            last += 1
            if last >= len(lines):
                raise VaultError(f"незакрытая запись в строке {index + 1}")
            buffer += " " + lines[last].strip()
        data = yaml.safe_load(buffer[2:])
        if isinstance(data, dict) and "name" in data:
            indent = len(lines[index]) - len(lines[index].lstrip())
            entries.append(Entry(str(data["name"]), index, last, indent, data))
        index = last + 1
    return entries


class RecipesFile:
    """`data/recipes.yaml` as text, as a document and as a map of source lines."""

    def __init__(self, path: Path, text: str | None = None, newline: str | None = None):
        self.path = path
        raw = path.read_bytes()
        # The file is written on Windows and its line endings are whatever the
        # last editor left. Reading normalises them to "\n"; writing puts back
        # what was there, or a one-line edit would come out as a diff of the
        # whole file.
        self.newline = newline or ("\r\n" if b"\r\n" in raw else "\n")
        # `text` lets an edit be built on top of another one -- a rename followed
        # by a move -- without a trip through the disk in between.
        self.text = raw.decode("utf-8").replace("\r\n", "\n") if text is None else text
        self.mtime = path.stat().st_mtime_ns
        self.lines = self.text.split("\n")
        self.doc = yaml.safe_load(self.text)
        self.entries = {entry.name: entry for entry in scan_entries(self.lines)}
        self.groups = self._groups()

    # -- structure ---------------------------------------------------------

    def _groups(self) -> dict[str, tuple[int, str | None]]:
        """Recipe name -> (level id, section id). Names are unique by contract."""
        placement: dict[str, tuple[int, str | None]] = {}
        for level in self.doc.get("levels", []):
            for recipe in level.get("recipes") or []:
                placement[recipe["name"]] = (level["id"], None)
            for section in level.get("sections") or []:
                for recipe in section.get("recipes") or []:
                    placement[recipe["name"]] = (level["id"], section["id"])
        return placement

    def levels(self) -> list[dict]:
        return [
            {
                "id": level["id"],
                "title": level.get("title", ""),
                # Whether a recipe may sit on the level itself. A level split into
                # sections has no list of its own, and the document template asks
                # for the sections by name -- a recipe put beside them would reach
                # the engine and never appear on the page.
                "plain": bool(level.get("recipes")),
                "sections": [
                    {"id": section["id"], "title": section.get("title", "")}
                    for section in level.get("sections") or []
                ],
            }
            for level in self.doc.get("levels", [])
        ]

    def recipes(self) -> list[dict]:
        out = []
        for level in self.doc.get("levels", []):
            for recipe in level.get("recipes") or []:
                out.append({**recipe, "level": level["id"], "section": None})
            for section in level.get("sections") or []:
                for recipe in section.get("recipes") or []:
                    out.append({**recipe, "level": level["id"], "section": section["id"]})
        return out

    def operations(self) -> list[dict]:
        return list(self.doc.get("operations") or [])

    def meta(self) -> dict:
        return dict(self.doc.get("meta") or {})

    def source_of(self, name: str) -> str | None:
        entry = self.entries.get(name)
        if entry is None:
            return None
        return "\n".join(self.lines[entry.start : entry.end + 1])

    def comment_above(self, name: str) -> list[str]:
        """Comment lines glued to an entry from above, without a blank between."""
        entry = self.entries.get(name)
        if entry is None:
            return []
        out: list[str] = []
        index = entry.start - 1
        while index >= 0 and self.lines[index].strip().startswith("#"):
            out.insert(0, self.lines[index])
            index -= 1
        return out

    # -- edits -------------------------------------------------------------

    def replace(self, name: str, data: dict) -> list[str]:
        entry = self.entries.get(name)
        if entry is None:
            raise VaultError(f"рецепта «{name}» нет в файле")
        line = render_entry(data, entry.indent, existing=list(entry.data))
        return self.lines[: entry.start] + [line] + self.lines[entry.end + 1 :]

    def insert(self, data: dict, level_id: int, section_id: str | None) -> list[str]:
        after, indent = self._tail_of_group(level_id, section_id)
        line = render_entry(data, indent)
        return self.lines[: after + 1] + [line] + self.lines[after + 1 :]

    def cut(self, name: str, with_comment: bool = False) -> list[str]:
        entry = self.entries.get(name)
        if entry is None:
            raise VaultError(f"рецепта «{name}» нет в файле")
        start = entry.start
        if with_comment:
            start -= len(self.comment_above(name))
        return self.lines[:start] + self.lines[entry.end + 1 :]

    def _tail_of_group(self, level_id: int, section_id: str | None) -> tuple[int, int]:
        """Where a new entry goes: after the last one of its group.

        Returns (line index to insert after, indent). An empty group has no entry
        to lean on, so the `recipes:` key itself is found by scanning.
        """
        level = next((lvl for lvl in self.doc.get("levels", []) if lvl["id"] == level_id), None)
        if level is None:
            raise VaultError(f"нет уровня {level_id}")
        sections = level.get("sections") or []
        if section_id is None and sections and not (level.get("recipes") or []):
            names = ", ".join(section["id"] for section in level["sections"])
            raise VaultError(
                f"на уровне {level_id} рецепты лежат в разделах ({names}) — выберите раздел. "
                "Рецепт рядом с разделами доехал бы до движка, но на страницу вольта не попал."
            )
        siblings = [
            self.entries[name]
            for name, group in self.groups.items()
            if group == (level_id, section_id) and name in self.entries
        ]
        if siblings:
            last = max(siblings, key=lambda entry: entry.end)
            return last.end, last.indent
        header = self._recipes_key_line(level_id, section_id)
        indent = len(self.lines[header]) - len(self.lines[header].lstrip())
        return header, indent + 2

    # -- meta list entries (D-215) ------------------------------------------

    def meta_entries(self, key: str) -> list[Entry]:
        """Flow-mapping entries of one `meta:` block list (`materials`, `classes`).

        The same `- {name: ...}` shape as a recipe, so the same scanner reads
        them -- only bounded to the block, because a class may share its name
        with a recipe («Кровать») and a global lookup would find the wrong line.
        """
        block = MetaBlock(self, key)
        return [
            entry
            for entry in scan_entries(self.lines)
            if block.start < entry.start <= block.end
        ]

    def meta_entry(self, key: str, name: str) -> Entry:
        found = [entry for entry in self.meta_entries(key) if entry.name == name]
        if not found:
            raise VaultError(f"в meta.{key} нет записи «{name}»")
        return found[0]

    def replace_meta_entry(
        self, key: str, name: str, data: dict, order: tuple[str, ...]
    ) -> list[str]:
        entry = self.meta_entry(key, name)
        line = render_entry(data, entry.indent, order, existing=list(entry.data))
        return self.lines[: entry.start] + [line] + self.lines[entry.end + 1 :]

    def insert_meta_entry(self, key: str, data: dict, order: tuple[str, ...]) -> list[str]:
        """A new entry goes after the last one of the block."""
        siblings = self.meta_entries(key)
        if siblings:
            last = max(siblings, key=lambda entry: entry.end)
            after, indent = last.end, last.indent
        else:
            block = MetaBlock(self, key)
            after, indent = block.start, block.indent
        line = render_entry(data, indent, order)
        return self.lines[: after + 1] + [line] + self.lines[after + 1 :]

    def cut_meta_entry(self, key: str, name: str) -> list[str]:
        entry = self.meta_entry(key, name)
        return self.lines[: entry.start] + self.lines[entry.end + 1 :]

    def _recipes_key_line(self, level_id: int, section_id: str | None) -> int:
        in_level = False
        in_section = section_id is None
        for index, line in enumerate(self.lines):
            level_match = LEVEL_ID.match(line)
            if level_match:
                in_level = int(level_match.group(1)) == level_id
                in_section = section_id is None
                continue
            if in_level and (section_match := SECTION_ID.match(line)):
                in_section = section_match.group(1) == section_id
                continue
            if in_level and in_section and RECIPES_KEY.match(line):
                return index
        where = f"уровень {level_id}" + (f", раздел {section_id}" if section_id else "")
        raise VaultError(f"не нашёл, куда вставлять: {where}")


# ---------------------------------------------------------------------- meta


class MetaBlock:
    """One `meta:` key that holds a plain block list or a plain mapping.

    `bulk` says which things are measured rather than counted, `units` says what
    word to draw next to the number. Both are lists of names, both are edited one
    line at a time -- and both sit among comments that explain the choice, so the
    same line-level discipline applies here as to a recipe.
    """

    def __init__(self, file: RecipesFile, key: str):
        self.file = file
        self.key = key
        self.start, self.end, self.indent = self._span()

    def _span(self) -> tuple[int, int, int]:
        """Lines of the block: the key itself, then everything indented under it."""
        header = re.compile(rf"^(\s*){re.escape(self.key)}:\s*(\S.*)?$")
        for index, line in enumerate(self.file.lines):
            match = header.match(line)
            if not match or len(match.group(1)) != 2:  # only keys directly under meta:
                continue
            indent = len(match.group(1))
            if match.group(2):  # written inline, `units: {}` -- one line, no body
                return index, index, indent + 2
            last = index
            for offset in range(index + 1, len(self.file.lines)):
                text = self.file.lines[offset]
                if not text.strip():
                    continue
                if len(text) - len(text.lstrip()) <= indent:
                    break
                last = offset
            return index, last, indent + 2
        raise VaultError(f"в meta нет ключа «{self.key}»")

    def _body(self) -> list[int]:
        """Line numbers of the entries, comments and blanks left out."""
        def written(line: str) -> bool:
            return bool(line.strip()) and not line.lstrip().startswith("#")

        return [
            index
            for index in range(self.start + 1, self.end + 1)
            if written(self.file.lines[index])
        ]

    # -- list --------------------------------------------------------------

    def toggle(self, name: str, present: bool) -> list[str]:
        """Put a name into a block list, or take it out. Idempotent."""
        lines = list(self.file.lines)
        found = [
            index
            for index in self._body()
            if lines[index].strip() == f"- {_scalar(name)}" or lines[index].strip() == f"- {name}"
        ]
        if present and not found:
            entry = " " * self.indent + f"- {_scalar(name)}"
            at = (self._body() or [self.start])[-1] + 1
            return lines[:at] + [entry] + lines[at:]
        if not present and found:
            for index in reversed(found):
                del lines[index]
            if not self._body_after(lines):
                # Ключ без единой записи прочитался бы как пустота, а не как
                # пустой список: `bulk:` — это None, `bulk: []` — это ноль вещей.
                lines[self.start] = " " * (self.indent - 2) + f"{self.key}: []"
        return lines

    # -- mapping -----------------------------------------------------------

    def put(self, name: str, value: str | float | None) -> list[str]:
        """Set a mapping entry, or drop it when there is no value.

        Zero counts as a value: energy weighs nothing, and that is a statement
        about the world, not a missing number.
        """
        lines = list(self.file.lines)
        key = re.compile(rf"^\s*{re.escape(name)}\s*:\s")
        found = [index for index in self._body() if key.match(lines[index])]
        if value is not None and value != "":
            entry = " " * self.indent + f"{_scalar(name)}: {_flow(value)}"
            if found:
                lines[found[0]] = entry
                return lines
            if lines[self.start].strip().endswith("{}"):
                # `units: {}` -- an empty map written inline. The first entry
                # turns it into a block, and the key loses its braces.
                lines[self.start] = lines[self.start].rsplit(":", 1)[0] + ":"
            at = (self._body() or [self.start])[-1] + 1
            return lines[:at] + [entry] + lines[at:]
        for index in reversed(found):
            del lines[index]
        if not found:
            return lines
        if not self._body_after(lines):
            # The last entry is gone: an empty block key would not parse.
            lines[self.start] = " " * (self.indent - 2) + f"{self.key}: {{}}"
        return lines

    def _body_after(self, lines: list[str]) -> bool:
        """Whether anything is left under the key after a deletion."""
        for offset in range(self.start + 1, len(lines)):
            text = lines[offset]
            if not text.strip() or text.lstrip().startswith("#"):
                continue
            return len(text) - len(text.lstrip()) >= self.indent
        return False


# -------------------------------------------------------------------- rename


def rename_everywhere(text: str, old: str, new: str) -> str:
    """Rename a thing in every place the file names it.

    A recipe name is not only its own entry: it is an input somewhere, a station
    somewhere else, a member of a tool class, a line in `bulk`. Renaming the entry
    alone would leave the ladder broken, so the whole file is swept.

    The sweep is textual -- that is what keeps the formatting and the comments --
    and it is verified structurally: both documents are parsed, the same
    substitution is applied to the old one, and the two must come out identical.
    Anything the text touched that the substitution did not is a mistake, and the
    edit is refused instead of written.
    """
    if _scalar(new) != new:
        raise VaultError(
            f"название «{new}» пришлось бы брать в кавычки — переименовать по всему "
            "файлу не берусь. Уберите запятые, двоеточия и скобки."
        )
    pattern = re.compile(rf"(?<![\w\-]){re.escape(old)}(?![\w\-])")

    renamed = "\n".join(
        line if line.lstrip().startswith("#") else pattern.sub(new, line)
        for line in text.split("\n")
    )
    if _substitute(yaml.safe_load(text), pattern, new) != yaml.safe_load(renamed):
        raise VaultError(
            "переименование задело не только это название — правка отменена. "
            "Переименуйте без обновления ссылок и поправьте их руками."
        )
    return renamed


def _substitute(value: Any, pattern: re.Pattern, new: str) -> Any:
    if isinstance(value, str):
        return pattern.sub(new, value)
    if isinstance(value, list):
        return [_substitute(item, pattern, new) for item in value]
    if isinstance(value, dict):
        return {
            _substitute(key, pattern, new): _substitute(item, pattern, new)
            for key, item in value.items()
        }
    return value


# --------------------------------------------------------------- the document


def _find_recipe(doc: dict, name: str) -> dict | None:
    for level in doc.get("levels", []):
        for recipe in level.get("recipes") or []:
            if recipe.get("name") == name:
                return recipe
        for section in level.get("sections") or []:
            for recipe in section.get("recipes") or []:
                if recipe.get("name") == name:
                    return recipe
    return None
