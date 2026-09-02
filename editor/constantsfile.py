# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""`data/constants.yaml` as text: the numbers of the game, edited one at a time.

Numbers live in the vault and only there (D-065). There are hundreds of them,
each explained by the comment above it, and for a long time they were edited
in the file by hand -- a form over all of them looked like an invitation to
edit them blindly. What the form gives instead is the one thing the file does
not: the value is checked to read back as written, the key is checked to be
unique and well-formed, and the comment above the entry stays where it is.

**Building types** were the first exception, and they stay a special case: a
type is not one number but three maps that have to agree. `build.types` says
what goes into the wall, `build.floor_growth_by_type` how much dearer the
next floor is, `build.decay_by_type` how fast the house rots. Add a type to
the first and forget the other two, and the engine finds a composition with
no rate of decay -- a crash on a tick, hours after the edit. Those three maps
are written together by `set_types` and refused by `set_entry`.

The edit is line surgery on one entry at a time -- and inside the entry, on
one field at a time: a note changed does not rewrite the value block, and a
value changed does not touch the note. It is safe for the same reason the
recipe edits are: the whole document is parsed back and compared with the one
the caller meant before a single byte is written (`store.prepare_doc`).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: The renderers are the recipe file's own: one tool, one way of writing a
#: number and one way of deciding whether a name needs quotes. A second copy
#: here would drift, and the drift would show up as a file that parses back
#: differently than it was meant.
from vaultfile import VaultError, _comparable, _flow, _number, _scalar

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

#: The layout of the file: groups at two spaces, entries at six, fields at eight.
GROUP_HEAD = re.compile(r"^  - id: (\S+)\s*$")
ENTRY_HEAD = re.compile(r"^      - key: (\S+)\s*$")
FIELD_HEAD = re.compile(r"^        ([a-z_]+):(.*)$")
GROUP_INDENT = 2
ENTRY_INDENT = 6
FIELD_INDENT = 8

#: The fields of one entry, in the order the file writes them. Exactly one of
#: the three value fields is present: a number (or a map of them), a rule the
#: engine computes, or a table the build assembles from the material registry.
FIELD_ORDER = ("key", "value", "value_from", "formula", "unit", "note", "decision")
VALUE_FIELDS = ("value", "value_from", "formula")
#: A constant's key: a namespace and a name, English snake_case, dots between.
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _trim(lines: list[str], start: int, stop: int) -> int:
    """Where a span really ends: past its own last line of substance.

    Blank lines and the comments below them introduce what comes next, not
    what came before -- the comment explaining the next constant stands under
    this one's last line, and a span that swallowed it would take it along.
    """
    while stop > start + 1 and (
        not lines[stop - 1].strip() or lines[stop - 1].lstrip().startswith("#")
    ):
        stop -= 1
    return stop


@dataclass(frozen=True, slots=True)
class Span:
    """Where an entry lies: `[start, end)` are its own lines, `lead` is where
    the comment that introduces it begins."""

    lead: int
    start: int
    end: int


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
        self.groups, self.entries, self.group_of = self._scan()

    # ------------------------------------------------------------ scanning

    def _scan(self) -> tuple[dict[str, Span], dict[str, Span], dict[str, str]]:
        """Every group and every entry as a span of lines."""
        heads = [
            (number, found.group(1))
            for number, line in enumerate(self.lines)
            if (found := GROUP_HEAD.match(line))
        ]
        groups: dict[str, Span] = {}
        entries: dict[str, Span] = {}
        group_of: dict[str, str] = {}
        for index, (start, group_id) in enumerate(heads):
            stop = heads[index + 1][0] if index + 1 < len(heads) else len(self.lines)
            end = _trim(self.lines, start, stop)
            groups[group_id] = Span(start, start, end)
            keys = [
                (number, found.group(1))
                for number in range(start, end)
                if (found := ENTRY_HEAD.match(self.lines[number]))
            ]
            floor = start + 1
            for position, (line, key) in enumerate(keys):
                stop = keys[position + 1][0] if position + 1 < len(keys) else end
                #: The comment block directly above introduces **this** entry,
                #: and goes with it if it goes: left behind, it would stand
                #: over the next entry and explain something else.
                lead = line
                while lead > floor and self.lines[lead - 1].lstrip().startswith("#"):
                    lead -= 1
                entries[key] = Span(lead, line, _trim(self.lines, line, stop))
                group_of[key] = group_id
                floor = entries[key].end
        return groups, entries, group_of

    def _fields(self, span: Span) -> dict[str, tuple[int, int]]:
        """Field name -> `[start, end)` inside one entry. A `value:` written as
        a block spans every line deeper than the key."""
        heads = [(span.start, "key")]
        for number in range(span.start + 1, span.end):
            found = FIELD_HEAD.match(self.lines[number])
            if found:
                heads.append((number, found.group(1)))
        out: dict[str, tuple[int, int]] = {}
        for index, (start, name) in enumerate(heads):
            stop = heads[index + 1][0] if index + 1 < len(heads) else span.end
            out[name] = (start, stop)
        return out

    # ------------------------------------------------------------ reading

    def value(self, key: str) -> Any:
        """What the document says this constant is."""
        return self._entry(key).get("value")

    def _entry(self, key: str) -> dict:
        for group in self.doc.get("groups") or []:
            for entry in group.get("constants") or []:
                if entry.get("key") == key:
                    return entry
        raise VaultError(f"константы «{key}» нет в реестре")

    def registry(self) -> list[dict]:
        """Every group with its constants, as the form shows them.

        Each constant carries the kind of thing it is -- a value, a formula or
        a table assembled from the material registry -- and the comment above
        it, because the comment is half of what the file says about the number.
        """
        out = []
        for group in self.doc.get("groups") or []:
            constants = []
            for entry in group.get("constants") or []:
                key = entry.get("key")
                kind = next((field for field in VALUE_FIELDS if field in entry), "value")
                span = self.entries.get(key)
                constants.append(
                    {
                        "key": key,
                        "kind": kind,
                        "value": entry.get(kind),
                        "unit": entry.get("unit"),
                        "note": entry.get("note"),
                        "decision": entry.get("decision"),
                        "comment": (
                            [line.strip() for line in self.lines[span.lead : span.start]]
                            if span else []
                        ),
                        "building": key in BUILDING_KEYS,
                    }
                )
            out.append(
                {"id": group.get("id"), "title": group.get("title") or "", "constants": constants}
            )
        return out

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
        to `store.prepare_doc`, which refuses the write if the file comes back
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

    # -- one constant at a time -----------------------------------------------

    def set_entry(self, key: str, data: dict) -> tuple[list[str], dict]:
        """Change one constant field by field. Returns the new lines and the
        intended document.

        Only the lines of the fields that changed move: a note edited leaves
        the value block byte for byte, and the comment above the entry is never
        rewritten. The building maps are refused -- they are three maps that
        must agree, and the «Здания» tab is where they agree.
        """
        if key in BUILDING_KEYS:
            raise VaultError(
                f"«{key}» — карта типов зданий: она правится во вкладке «Здания», "
                "вместе с двумя другими картами (D-218)"
            )
        span = self.entries.get(key)
        if span is None:
            raise VaultError(f"константы «{key}» нет в реестре")
        now = clean_entry(data)
        was = self._entry(key)
        if now["key"] != key and now["key"] in self.entries:
            raise VaultError(f"константа «{now['key']}» уже есть")

        fields = self._fields(span)
        edits: list[tuple[int, int, list[str], int]] = []
        seat = span.start + 1
        for rank, field in enumerate(FIELD_ORDER):
            here = fields.get(field)
            if field == "key":
                if now["key"] != key:
                    made = _render_field("key", now["key"])
                    edits.append((span.start, span.start + 1, made, rank))
                continue
            if field in now and field in was and _comparable(now[field]) == _comparable(was[field]):
                seat = here[1] if here else seat
                continue
            if field not in now:
                if here is not None:
                    edits.append((here[0], here[1], [], rank))
                continue
            made = _render_field(field, now[field])
            if here is None:
                edits.append((seat, seat, made, rank))
            else:
                #: A value block re-rendered whole would drop a comment written
                #: inside it -- the two lines over «Нефть: 0» in the weights of
                #: Pyroxis say why the zero is there. Keeping comments is what
                #: this tool is for, so such a block is refused, not flattened.
                if any(self.lines[n].lstrip().startswith("#") for n in range(here[0], here[1])):
                    raise VaultError(
                        f"у «{key}» внутри блока «{field}» есть комментарий — этот блок "
                        "правится руками, иначе комментарий пропал бы"
                    )
                edits.append((here[0], here[1], made, rank))
                seat = here[1]
        lines = list(self.lines)
        #: Bottom-up, replacements before insertions on one line, later fields
        #: first among insertions -- the same order `worldfile` keeps, for the
        #: same reason: applied otherwise, one edit would land on another.
        ordered = sorted(edits, key=lambda one: (one[0], one[1], one[3]), reverse=True)
        for start, end, made, _ in ordered:
            lines[start:end] = made

        expect = copy.deepcopy(self.doc)
        entry = next(
            entry
            for group in expect["groups"]
            for entry in group["constants"]
            if entry.get("key") == key
        )
        entry.clear()
        entry.update(now)
        return lines, expect

    def add_entry(
        self, group_id: str, data: dict, after: str | None = None
    ) -> tuple[list[str], dict]:
        """A new constant: after the named one, or last in its group."""
        now = clean_entry(data)
        if now["key"] in self.entries:
            raise VaultError(f"константа «{now['key']}» уже есть")
        group = self.groups.get(group_id)
        if group is None:
            raise VaultError(f"группы «{group_id}» нет в реестре")
        rendered = [
            line
            for field in FIELD_ORDER
            if field in now
            for line in _render_field(field, now[field])
        ]
        _round_trip(rendered, now, f"константа «{now['key']}»")

        expect = copy.deepcopy(self.doc)
        target = next(one for one in expect["groups"] if one.get("id") == group_id)
        constants = target.get("constants") or []
        if after and self.group_of.get(after) == group_id:
            seat = self.entries[after].end
            index = next(i for i, one in enumerate(constants) if one.get("key") == after) + 1
        else:
            seat = group.end
            index = len(constants)
        constants.insert(index, now)
        target["constants"] = constants
        lines = list(self.lines)
        lines[seat:seat] = rendered
        return lines, expect

    def drop_entry(self, key: str, *, with_comment: bool = True) -> tuple[list[str], dict]:
        """Take one constant out, with the comment that introduced it.

        The last constant of a group is refused: a `constants:` with nothing
        under it reads as null, and the build walks the list.
        """
        if key in BUILDING_KEYS:
            raise VaultError(f"«{key}» — карта типов зданий, без неё дома не построить (D-218)")
        span = self.entries.get(key)
        if span is None:
            raise VaultError(f"константы «{key}» нет в реестре")
        group_id = self.group_of[key]
        expect = copy.deepcopy(self.doc)
        target = next(one for one in expect["groups"] if one.get("id") == group_id)
        rows = [one for one in target.get("constants") or [] if one.get("key") != key]
        if not rows:
            raise VaultError(
                f"«{key}» — последняя константа группы «{group_id}»: пустую группу "
                "сборка не прочтёт. Удалите группу руками, вместе с её заголовком"
            )
        target["constants"] = rows
        start = span.lead if with_comment else span.start
        lines = self.lines[:start] + self.lines[span.end :]
        return lines, expect


def _set_in_doc(doc: dict, key: str, value: Any) -> None:
    for group in doc.get("groups") or []:
        for entry in group.get("constants") or []:
            if entry.get("key") == key:
                entry["value"] = value
                return
    raise VaultError(f"константы «{key}» нет в реестре")


# ------------------------------------------------------------------ cleaning


def clean_entry(data: dict) -> dict:
    """The fields of one constant as they will be written, checked.

    Exactly one way of saying what the constant is: a value, a formula or a
    source to assemble it from. The rest are words for the reader.
    """
    key = str(data.get("key") or "").strip()
    if not key:
        raise VaultError("у константы должен быть ключ")
    if not KEY_RE.match(key):
        raise VaultError(
            f"ключ «{key}» не годится: пространство и имя через точку, строчная "
            "латиница, цифры и подчёркивания — «craft.amount_cap»"
        )
    out: dict[str, Any] = {"key": key}
    said = [field for field in VALUE_FIELDS if data.get(field) not in (None, "")]
    if "value" in data and data["value"] is not None and "value" not in said:
        said.append("value")
    if len(said) != 1:
        raise VaultError(
            "у константы ровно одно из трёх: значение, формула либо источник "
            f"(value_from), а названо {len(said)}"
        )
    field = said[0]
    if field == "value":
        out["value"] = _clean_value(data["value"], key)
    else:
        text = str(data[field]).strip()
        if not text:
            raise VaultError(f"«{field}» у «{key}» пусто")
        out[field] = text
    for field in ("unit", "note", "decision"):
        text = str(data.get(field) or "").strip()
        if text:
            out[field] = text
    return out


def _clean_value(value: Any, key: str) -> Any:
    """A value the file can hold: a number, a word, a switch, a range, a table."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise VaultError(f"у «{key}» пустое значение")
        return text
    if isinstance(value, dict):
        if not value:
            raise VaultError(f"у «{key}» пустая таблица")
        return {str(name): _clean_value(item, key) for name, item in value.items()}
    if isinstance(value, list):
        if not value:
            raise VaultError(f"у «{key}» пустой список")
        return [_clean_value(item, key) for item in value]
    raise VaultError(f"у «{key}» значение непонятного вида: {value!r}")


# ----------------------------------------------------------------- rendering

#: Words YAML would read as something other than text, and so must be quoted.
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~", ""}
#: What a plain scalar may not start with, or contain, in block context.
_BLOCK_START = re.compile(r"^[-?:,\[\]{}#&*!|>'\"%@`]")
_BLOCK_INSIDE = re.compile(r": | #|:$|^\s|\s$|\n")


def _block_scalar(value: Any) -> str:
    """A scalar as it is written after `note:` -- plain where YAML allows it.

    Block context is laxer than a flow mapping: a comma or a bracket inside a
    sentence is only text here, and quoting it would make every note with a
    comma come out in quotes that the hand-written ones do not have.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _number(value)
    text = str(value)
    numeric = re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", text)
    quoted = _BLOCK_START.match(text) or _BLOCK_INSIDE.search(text)
    if text.lower() in _RESERVED or numeric or quoted:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _is_flat(value: Any) -> bool:
    """Whether a value fits on the key's own line: a scalar, a range, a list of scalars."""
    if isinstance(value, dict):
        return set(value) == {"min", "max"}
    if isinstance(value, list):
        return all(not isinstance(item, (dict, list)) for item in value)
    return True


def _render_field(field: str, value: Any) -> list[str]:
    """One field of an entry as the lines it takes in the file."""
    if field == "key":
        return [f"{' ' * ENTRY_INDENT}- key: {value}"]
    pad = " " * FIELD_INDENT
    if field != "value" or _is_flat(value):
        text = _flow(value) if isinstance(value, (dict, list)) else _block_scalar(value)
        return [f"{pad}{field}: {text}"]
    out = [f"{pad}value:"]
    if isinstance(value, dict):
        out.extend(_render_block(value, FIELD_INDENT + 2))
    else:
        out.extend(f"{pad}  - {_flow(item)}" for item in value)
    return out


def _render_block(mapping: dict, indent: int) -> list[str]:
    """A mapping as a block, nested where its values are mappings themselves."""
    out = []
    for name, value in mapping.items():
        if isinstance(value, dict) and not _is_flat(value):
            out.append(f"{' ' * indent}{_block_scalar(str(name))}:")
            out.extend(_render_block(value, indent + 2))
        else:
            text = _flow(value) if isinstance(value, (dict, list)) else _block_scalar(value)
            out.append(f"{' ' * indent}{_block_scalar(str(name))}: {text}")
    return out


def _round_trip(rendered: list[str], data: dict, what: str) -> None:
    """The rendered lines must read back as exactly what they were made from."""
    body = "\n".join(line[ENTRY_INDENT:] for line in rendered)
    try:
        read = yaml.safe_load(body)
    except yaml.YAMLError as error:
        raise VaultError(f"{what} не читается обратно: {error}") from error
    if isinstance(read, list) and len(read) == 1:
        read = read[0]
    if _comparable(read) != _comparable(data):
        raise VaultError(f"{what} записалась бы не тем, чем задумана: {read} != {data}")


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
