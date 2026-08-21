"""`data/constants.yaml` as text: the building types the editor may change (D-218).

Numbers live in the vault and only there (D-065), and almost all of them are
edited in the file by hand -- there are hundreds, each explained by the comment
above it, and a form over all of them would only invite editing them blindly.

**Building types are the exception**, and for one reason: a type is not one
number but three maps that have to agree. `build.types` says what goes into the
wall, `build.floor_growth_by_type` how much dearer the next floor is,
`build.decay_by_type` how fast the house rots. Add a type to the first and
forget the other two, and the engine finds a composition with no rate of decay
-- a crash on a tick, hours after the edit. Keeping three maps in step is
exactly the work a tool should do instead of a person, so here it does.

The edit is line surgery on one `value:` block at a time, and it is safe for the
same reason the recipe edits are: the whole document is parsed back and compared
with the one the caller meant before a single byte is written (`vaultfile.save_doc`).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

#: The renderers are the recipe file's own: one tool, one way of writing a
#: number and one way of deciding whether a name needs quotes. A second copy
#: here would drift, and the drift would show up as a file that parses back
#: differently than it was meant.
from vaultfile import VaultError, _number, _scalar

#: The three maps a building type lives in. The order is the order they are
#: written in; `build.types` leads because it is the one that names the types --
#: the other two follow its ladder. Upkeep used to be a fourth; it went with the
#: mechanic itself (D-219): the land tax takes the money, decay takes the walls.
COMPOSITION = "build.types"
GROWTH = "build.floor_growth_by_type"
DECAY = "build.decay_by_type"
BUILDING_KEYS = (COMPOSITION, GROWTH, DECAY)

#: What each map holds per type, for the messages and for the form.
FLAT_KEYS = {
    GROWTH: ("growth", "во сколько раз следующий этаж дороже предыдущего"),
    DECAY: ("decay", "процентов состояния в сутки"),
}

KEY_LINE = re.compile(r"^(\s*)- key: (\S+)\s*$")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


class ConstantsFile:
    """The constants file as text, as a document and as a map of source lines."""

    def __init__(self, path: Path, text: str | None = None):
        self.path = path
        raw = text if text is not None else path.read_bytes().decode("utf-8")
        self.newline = "\r\n" if "\r\n" in raw else "\n"
        self.lines = raw.replace("\r\n", "\n").split("\n")
        #: Read before the edit and checked at the write: a file changed on disk
        #: under an open editor must not be overwritten from a stale page.
        self.mtime = None if text is not None else path.stat().st_mtime_ns
        self.doc = yaml.safe_load("\n".join(self.lines))

    # ------------------------------------------------------------ reading

    def value(self, key: str) -> Any:
        """What the document says this constant is."""
        for group in self.doc.get("groups") or []:
            for entry in group.get("constants") or []:
                if entry.get("key") == key:
                    return entry.get("value")
        raise VaultError(f"константы «{key}» нет в реестре")

    def types(self) -> list[dict]:
        """Every building type as one row: composition and both numbers.

        The ladder's order is the order of `build.types` and nothing else: it
        runs from the log hut to the all-metal house, and the shop window in the
        game shows it exactly so.
        """
        composition = self.value(COMPOSITION) or {}
        numbers = {key: (self.value(key) or {}) for key in FLAT_KEYS}
        rows = []
        for name, parts in composition.items():
            row = {"kind": name, "per_m2": dict(parts)}
            for key, (field, _) in FLAT_KEYS.items():
                row[field] = numbers[key].get(name)
            rows.append(row)
        return rows

    # ------------------------------------------------------------ writing

    def _value_span(self, key: str) -> tuple[int, int, int]:
        """Where one constant's `value:` block lies: (first, last, indent).

        `last` is exclusive. The block ends at the first line that is not deeper
        than `value:` itself -- the entry's own `unit`, `note` or `decision`, or
        the next `- key:` altogether.
        """
        start = None
        indent = 0
        for index, line in enumerate(self.lines):
            found = KEY_LINE.match(line)
            if found and found.group(2) == key:
                start = index
                indent = len(found.group(1))
                break
        if start is None:
            raise VaultError(f"в файле нет строки «- key: {key}»")

        for index in range(start + 1, len(self.lines)):
            line = self.lines[index]
            if not line.strip():
                continue
            here = _indent_of(line)
            if here <= indent:
                break
            if here == indent + 2 and line.strip().startswith("value:"):
                last = index + 1
                while last < len(self.lines):
                    below = self.lines[last]
                    #: A blank line ends the block as surely as a shallower one:
                    #: inside a value there are none, and one appearing would
                    #: mean the file is laid out differently than this assumes.
                    if not below.strip() or _indent_of(below) <= here:
                        break
                    last += 1
                return index, last, here
        raise VaultError(f"у «{key}» нет блока `value:` — правится руками")

    def set_map(self, key: str, mapping: dict, *, nested: bool) -> None:
        """Rewrite one constant's `value:` block from the map given.

        The whole block is re-rendered rather than patched line by line: the
        types come and go, and a diff of two maps expressed as line edits would
        be more code than the render and less obvious than it.
        """
        first, last, indent = self._value_span(key)
        self.lines[first:last] = _render_map(mapping, indent, nested=nested)

    def set_types(self, rows: list[dict]) -> dict:
        """Write all three maps from one ladder of types, and say what was meant.

        The blocks are written from the bottom of the file upwards, so that
        splicing one does not move the line numbers of the ones still to come.

        Returns the document as it must read afterwards -- the caller hands that
        to `vaultfile.save_doc`, which refuses the write if the file comes back
        saying anything else.
        """
        composition = {row["kind"]: dict(row["per_m2"]) for row in rows}
        flat = {
            key: {row["kind"]: row[field] for row in rows}
            for key, (field, _) in FLAT_KEYS.items()
        }

        expect = copy.deepcopy(self.doc)
        _set_in_doc(expect, COMPOSITION, composition)
        for key, values in flat.items():
            _set_in_doc(expect, key, values)

        #: Bottom-up: each splice shifts everything below it.
        order = sorted(BUILDING_KEYS, key=lambda key: self._value_span(key)[0], reverse=True)
        for key in order:
            if key == COMPOSITION:
                self.set_map(key, composition, nested=True)
            else:
                self.set_map(key, flat[key], nested=False)
        return expect


def _set_in_doc(doc: dict, key: str, value: Any) -> None:
    for group in doc.get("groups") or []:
        for entry in group.get("constants") or []:
            if entry.get("key") == key:
                entry["value"] = value
                return
    raise VaultError(f"константы «{key}» нет в реестре")


def _render_map(mapping: dict, indent: int, *, nested: bool) -> list[str]:
    """A `value:` block as lines, checked by parsing it back.

    The check is the same one `render_entry` makes for a recipe: a name the
    renderer quoted wrongly would otherwise reach the file and be found by the
    build, an hour and one confusing message later.
    """
    if not mapping:
        raise VaultError("пустая карта: у константы должно остаться хотя бы одно значение")
    out = [" " * indent + "value:"]
    for name, value in mapping.items():
        if nested:
            if not value:
                raise VaultError(f"у «{name}» пустой состав")
            out.append(" " * (indent + 2) + f"{_scalar(str(name))}:")
            for part, amount in value.items():
                out.append(
                    " " * (indent + 4) + f"{_scalar(str(part))}: {_number(amount)}"
                )
        else:
            if value is None:
                raise VaultError(f"у «{name}» не задано число")
            out.append(" " * (indent + 2) + f"{_scalar(str(name))}: {_number(value)}")

    body = "\n".join(line[indent:] for line in out)
    back = yaml.safe_load(body)
    if not isinstance(back, dict) or "value" not in back:
        raise VaultError("блок значения не читается обратно как значение")
    if not _same(back["value"], mapping):
        raise VaultError("блок значения читается не так, как записан")
    return out


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(map(str, right)):
            return False
        return all(_same(left[str(k)], v) for k, v in right.items())
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return round(float(left), 6) == round(float(right), 6)
    return left == right
