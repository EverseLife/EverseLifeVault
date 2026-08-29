# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Reading and surgical editing of the vault's `data/world.yaml` (D-243).

The same rule as `vaultfile.py`, for the same reason: the file explains itself
in comments, and a YAML dumper would flatten every one of them on the first
save. So the editor works at the block level -- it finds the lines of one node,
one edge or one pocket and replaces exactly those. Everything around them stays
byte for byte, and the diff of an edit is the edit.

The safety net is the same three checks:

  1. **the block is parsed back** and compared with the data it was rendered
     from -- a mistake in rendering cannot slip through;
  2. **the whole file is parsed** after the edit, and it must show exactly the
     intended change and nothing else;
  3. **the file must not have moved on disk** while it was open in the editor:
     two sessions in one copy are ordinary here, and a silent overwrite of
     somebody's edit is worse than a refusal.

A node is a block, not a line: it carries machines, veins and stocks, and a
line long enough to hold them would be unreadable in the diff the vault exists
for. An edge and a stock are one line each -- they fit.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from vaultfile import VaultError, _backup, _comparable

#: The sections of the file, in the order they lie in it.
SECTIONS = ("external", "nodes", "edges", "pockets")

#: The order of keys in a node's block. Rendering by it keeps a saved node
#: indistinguishable from a hand-written one.
NODE_KEY_ORDER = (
    "key",
    "name",
    "layer",
    "parent",
    "area_m2",
    "anchor",
    "place",
    "city",
    "properties",
    "machines",
    "relics",
    "veins",
    "items",
)
#: Keys whose value is a block list of flow mappings, one per line.
NODE_BLOCK_LISTS = ("machines", "veins", "items")
#: Keys whose value is a flow list on the same line.
NODE_FLOW_LISTS = ("relics",)

EDGE_KEY_ORDER = ("a", "b", "seconds", "surface")
STOCK_KEY_ORDER = ("name", "amount", "quality", "ensure", "origin")
MACHINE_KEY_ORDER = ("name", "class", "quality")
VEIN_KEY_ORDER = ("resource", "richness", "remaining")

LAYERS = ("planet", "city", "location")
SURFACES = ("trail", "road", "paved")
#: The edge length that means "by the node's distance" (D-180).
BY_REACH = "reach"

#: Where a section begins: a key at the left margin.
_SECTION = re.compile(r"^(\w+):\s*$")
#: Where a node begins inside `nodes:`.
_NODE_HEAD = re.compile(r"^  - key:\s*(.+?)\s*$")
#: One line of `edges:`.
_EDGE_LINE = re.compile(r"^  - \{")
#: An owner inside `pockets:`.
_POCKET_HEAD = re.compile(r"^  (\S.*?):\s*$")


@dataclass(frozen=True, slots=True)
class Block:
    """Where something lies in the file: the half-open line span `[start, end)`."""

    start: int
    end: int


class WorldFile:
    """`data/world.yaml` as text, as a document and as a map of source blocks."""

    def __init__(self, path: Path, text: str | None = None, newline: str | None = None):
        self.path = path
        raw = path.read_bytes()
        self.newline = newline or ("\r\n" if b"\r\n" in raw else "\n")
        self.text = text if text is not None else raw.decode("utf-8").replace("\r\n", "\n")
        self.mtime = path.stat().st_mtime_ns
        self.lines = self.text.split("\n")
        self.doc = yaml.safe_load(self.text) or {}
        self.sections = _scan_sections(self.lines)
        self.nodes = _scan_nodes(self.lines, self.sections.get("nodes"))
        self.edges = _scan_edges(self.lines, self.sections.get("edges"))
        self.pockets = _scan_pockets(self.lines, self.sections.get("pockets"))

    # -- reading -----------------------------------------------------------

    def node(self, key: str) -> dict:
        for node in self.doc.get("nodes") or []:
            if node.get("key") == key:
                return node
        raise VaultError(f"узла «{key}» нет в мире")

    def node_keys(self) -> list[str]:
        return [node["key"] for node in self.doc.get("nodes") or []]

    def edge_index(self, a: str, b: str) -> int:
        for index, edge in enumerate(self.doc.get("edges") or []):
            if {edge.get("a"), edge.get("b")} == {a, b}:
                return index
        raise VaultError(f"дороги {a} — {b} в мире нет")

    # -- editing -----------------------------------------------------------

    def put_node(
        self, data: dict, *, after: str | None = None, fresh: bool = False
    ) -> tuple[list[str], dict]:
        """Add or replace one node. Returns the new lines and the intended document.

        An existing node is edited **field by field**, not replaced wholesale:
        a node block carries comments between its lines -- why the printer at
        the forge is a city one, why the plots are where they are -- and
        rewriting the block would take them with it every save. Only the lines
        of what actually changed move.

        `fresh` says the caller means to **add** a node, not to change one.
        "Заведите узел" and "поправьте этот узел" are different intentions, and
        a typed key that happens to exist should be a refusal rather than a
        silent overwrite of somebody else's place.
        """
        data = clean_node(data)
        key = data["key"]
        rendered = render_node(data)
        _round_trip(rendered, data, f"узел «{key}»")

        lines = list(self.lines)
        doc = _copy(self.doc)
        nodes = doc.setdefault("nodes", [])
        found = self.nodes.get(key)
        if found is not None and fresh:
            raise VaultError(f"узел «{key}» уже есть: откройте его слева, чтобы поправить")
        if found is not None:
            lines = _edit_node(lines, found, self.node(key), data)
            for index, node in enumerate(nodes):
                if node.get("key") == key:
                    nodes[index] = data
                    break
        else:
            at, index = self._node_seat(after)
            lines[at:at] = [*rendered, ""]
            nodes.insert(index, data)
        return lines, doc

    def _node_seat(self, after: str | None) -> tuple[int, int]:
        """Where a new node goes: right after the named one, or at the end.

        The order in the file is the order the seed lays the world in, and a
        node's parent and anchor must already stand above it -- so "after" is
        not decoration but the one control over that.
        """
        keys = self.node_keys()
        if after and after in self.nodes:
            block = self.nodes[after]
            return block.end + 1, keys.index(after) + 1
        section = self.sections.get("nodes")
        if section is None:  # pragma: no cover -- the file always has the section
            raise VaultError("в файле мира нет раздела nodes")
        return section.end, len(keys)

    def drop_node(self, key: str) -> tuple[list[str], dict]:
        """Take a node out, with every road that led to it.

        The roads go too, and deliberately: an edge into a node that does not
        exist is not a diff worth keeping, and the build would refuse the file
        anyway. What the person means by "remove this place" is that nothing
        leads there any more.
        """
        block = self.nodes.get(key)
        if block is None:
            raise VaultError(f"узла «{key}» нет в мире")
        doc = _copy(self.doc)
        children = [
            node["key"]
            for node in doc.get("nodes") or []
            if node.get("parent") == key or node.get("anchor") == key
        ]
        if children:
            raise VaultError(
                f"на «{key}» опираются: {', '.join(children)} — сперва переставьте их"
            )
        drop: list[Block] = [block]
        for index, edge in enumerate(doc.get("edges") or []):
            if key in (edge.get("a"), edge.get("b")):
                drop.append(self.edges[index])
        lines = list(self.lines)
        #: From the bottom up: a removal above would shift every span below it.
        for span in sorted(drop, key=lambda one: one.start, reverse=True):
            end = span.end
            #: The blank line a block is followed by belongs to the block.
            if end < len(lines) and not lines[end].strip():
                end += 1
            del lines[span.start : end]
        doc["nodes"] = [node for node in doc["nodes"] if node.get("key") != key]
        doc["edges"] = [
            edge for edge in doc.get("edges") or [] if key not in (edge.get("a"), edge.get("b"))
        ]
        return lines, doc

    def put_edge(self, data: dict) -> tuple[list[str], dict]:
        """Add or replace one road. Undirected: a — b and b — a are the same road."""
        data = clean_edge(data)
        rendered = [render_flow(data, EDGE_KEY_ORDER, indent="  - ")]
        _round_trip(rendered, data, f"дорога {data['a']} — {data['b']}")

        lines = list(self.lines)
        doc = _copy(self.doc)
        edges = doc.setdefault("edges", [])
        for key in (data["a"], data["b"]):
            if key not in self.nodes:
                raise VaultError(f"дорога упирается в неизвестный узел «{key}»")
        if data["a"] == data["b"]:
            raise VaultError("дорога из узла в себя же")
        try:
            index = self.edge_index(data["a"], data["b"])
        except VaultError:
            section = self.sections.get("edges")
            if section is None:  # pragma: no cover
                raise VaultError("в файле мира нет раздела edges") from None
            lines[section.end : section.end] = rendered
            edges.append(data)
        else:
            block = self.edges[index]
            lines[block.start : block.end] = rendered
            edges[index] = data
        return lines, doc

    def drop_edge(self, a: str, b: str) -> tuple[list[str], dict]:
        index = self.edge_index(a, b)
        block = self.edges[index]
        lines = list(self.lines)
        del lines[block.start : block.end]
        doc = _copy(self.doc)
        del doc["edges"][index]
        return lines, doc

    def put_pocket(self, owner: str, stocks: list[dict]) -> tuple[list[str], dict]:
        """Set what a starting identity carries. An empty list takes the owner out."""
        doc = _copy(self.doc)
        pockets = doc.setdefault("pockets", {})
        lines = list(self.lines)
        block = self.pockets.get(owner)
        if not stocks:
            if block is None:
                raise VaultError(f"кармана «{owner}» в мире нет")
            del lines[block.start : block.end]
            del pockets[owner]
            return lines, doc
        cleaned = [clean_stock(stock) for stock in stocks]
        rendered = [
            f"  {owner}:",
            *(render_flow(stock, STOCK_KEY_ORDER, indent="    - ") for stock in cleaned),
        ]
        _round_trip(rendered, {owner: cleaned}, f"карман «{owner}»")
        if block is None:
            section = self.sections.get("pockets")
            if section is None:  # pragma: no cover
                raise VaultError("в файле мира нет раздела pockets")
            lines[section.end : section.end] = rendered
        else:
            lines[block.start : block.end] = rendered
        pockets[owner] = cleaned
        return lines, doc

    # -- writing -----------------------------------------------------------

    def save(self, lines: list[str], expect_doc: dict) -> Path:
        """Write the file back, checking it reads exactly as intended.

        The whole document rather than one entry, because an edit here moves
        more than one: dropping a node drops its roads with it.
        """
        if self.path.stat().st_mtime_ns != self.mtime:
            raise VaultError(
                "файл мира изменился на диске, пока он был открыт в редакторе. "
                "Обновите страницу и повторите правку."
            )
        text = "\n".join(lines)
        try:
            written = yaml.safe_load(text) or {}
        except yaml.YAMLError as error:
            raise VaultError(f"после правки файл перестал читаться: {error}") from error
        if _comparable(written) != _comparable(expect_doc):
            raise VaultError("после правки мир читается не так, как задумано — запись отменена")
        backup = _backup(self.path)
        self.path.write_text(text, encoding="utf-8", newline=self.newline)
        return backup


# ------------------------------------------------------------------ scanning


def _trim(lines: list[str], start: int, stop: int) -> int:
    """Where a span really ends: past its own last line of substance.

    Blank lines and the comments below them introduce what comes next, not what
    came before -- the comment explaining the floodplain stands under the mine's
    last vein, and a span that swallowed it would take the blank line with it
    every time that vein was edited.
    """
    while stop > start + 1 and (
        not lines[stop - 1].strip() or lines[stop - 1].lstrip().startswith("#")
    ):
        stop -= 1
    return stop


def _scan_sections(lines: list[str]) -> dict[str, Block]:
    """Where each top-level section lies. `end` is past its last non-blank line."""
    heads: list[tuple[str, int]] = [
        (found.group(1), number)
        for number, line in enumerate(lines)
        if (found := _SECTION.match(line))
    ]
    found_sections: dict[str, Block] = {}
    for index, (name, start) in enumerate(heads):
        stop = heads[index + 1][1] if index + 1 < len(heads) else len(lines)
        #: Blank lines and the next section's comments belong to what follows.
        found_sections[name] = Block(start + 1, _trim(lines, start + 1, stop))
    return found_sections


def _scan_nodes(lines: list[str], section: Block | None) -> dict[str, Block]:
    """Node key -> the span of its block, comments above it excluded.

    A node's own comments stay put on an edit: the block starts at `- key:`,
    so whatever explains the node above it is never rewritten.
    """
    if section is None:
        return {}
    heads = [
        (found.group(1).strip(), number)
        for number in range(section.start, section.end)
        if (found := _NODE_HEAD.match(lines[number]))
    ]
    blocks: dict[str, Block] = {}
    for index, (key, start) in enumerate(heads):
        stop = heads[index + 1][1] if index + 1 < len(heads) else section.end
        #: Back off the blank lines and the next node's comments.
        blocks[key] = Block(start, _trim(lines, start, stop))
    return blocks


def _scan_node_fields(lines: list[str], block: Block) -> dict[str, Block]:
    """Field name -> the span of its lines inside one node's block.

    A block-list field (`machines`, `items`, `veins`) spans its header and
    every entry under it, comments between the entries included: those lines
    belong to the list, and the entry-wise edit below keeps them.
    """
    heads: list[tuple[str, int]] = []
    for number in range(block.start, block.end):
        line = lines[number]
        if number == block.start:
            body = line.removeprefix("  - ")
        elif line.startswith("    ") and not line.startswith("     "):
            #: A field of the node sits at four spaces exactly: deeper than
            #: that is an entry of a list, and it is not a field of its own.
            body = line[4:]
        else:
            continue
        if body.lstrip().startswith("#"):
            continue
        name, sep, _ = body.partition(":")
        if sep and name and not name.startswith(" "):
            heads.append((name.strip(), number))
    fields: dict[str, Entry] = {}
    floor = block.start + 1
    for index, (name, start) in enumerate(heads):
        stop = heads[index + 1][1] if index + 1 < len(heads) else block.end
        #: The comment block directly above introduces **this** field, and goes
        #: with it if it goes: left behind it would stand over the next field
        #: and explain something else -- «лес и каменистая земля у шахты» over
        #: the mine's veins. The same rule an entry of a list lives by, and for
        #: the same reason.
        lead = start
        while lead > floor and lines[lead - 1].lstrip().startswith("#"):
            lead -= 1
        end = _trim(lines, start, stop)
        fields[name] = Entry(lead, start, end)
        floor = end
    return fields


@dataclass(frozen=True, slots=True)
class Entry:
    """One entry of a block list, with the comment that introduces it.

    Two spans, and the difference is what keeps the file readable. `lead` is
    where the comment above the entry begins; `start` is the entry's own line.
    **Replacing** an entry touches `[start, end)` and leaves the comment above
    it standing; **removing** one takes `[lead, end)`, because a comment left
    behind would then explain the machine below it, which it does not.
    """

    lead: int
    start: int
    end: int


def _scan_entries(lines: list[str], block: Block) -> list[Entry]:
    """Every entry of a block list, and where its introducing comment starts."""
    heads = [
        number
        for number in range(block.start + 1, block.end)
        if lines[number].startswith("      - ")
    ]
    entries: list[Entry] = []
    for index, start in enumerate(heads):
        stop = heads[index + 1] if index + 1 < len(heads) else block.end
        #: The comment block directly above, back to the previous entry.
        floor = entries[-1].end if entries else block.start + 1
        lead = start
        while lead > floor and lines[lead - 1].lstrip().startswith("#"):
            lead -= 1
        entries.append(Entry(lead, start, _trim(lines, start, stop)))
    return entries


#: One edit of the file: what to replace, with what, and which field it belongs
#: to. The rank settles the order of two edits that start on the same line.
_Edit = tuple[Block, list[str], int]


def _edit_node(lines: list[str], block: Block, was: dict, now: dict) -> list[str]:
    """Apply a node's changes line by line, leaving everything else untouched.

    Edits are applied **from the bottom up**, so an insertion never shifts a
    span below it. Two edits can start on the same line -- a field inserted
    right before the field that follows it -- and then the order matters twice
    over, which is what the sort key is for:

    * a **replacement** goes before an **insertion** at the same line (`end`
      decides): applied the other way round, the insertion would be written
      over by the replacement that follows it;
    * of two **insertions** at the same line, the later field goes first
      (`rank` decides), so the earlier one ends up above it and the block comes
      out in the canonical order rather than backwards.
    """
    was, now = clean_node(was), clean_node(now)
    fields = _scan_node_fields(lines, block)
    edits: list[_Edit] = []
    #: Where a field that is new to this node goes: after the last field that
    #: precedes it in the canonical order and is already in the file.
    seat = block.start + 1
    for rank, key in enumerate(NODE_KEY_ORDER):
        span = fields.get(key)
        if key in now and _comparable(now.get(key)) == _comparable(was.get(key)):
            if span is not None:
                seat = span.end
            continue
        if key not in now:
            if span is not None:
                #: From `lead`, so the field's own comment leaves with it.
                edits.append((Block(span.lead, span.end), [], rank))
            continue
        if span is None:
            edits.append((Block(seat, seat), _render_field(key, now[key], head=(key == "key")), rank))
            continue
        made = _render_field(key, now[key], head=(key == "key"))
        if key in NODE_BLOCK_LISTS:
            edits.extend(
                _edit_entries(lines, Block(span.start, span.end), key, was.get(key) or [], now[key], rank)
            )
        else:
            #: From `start`, not `lead`: the field stays, and so does what
            #: explains it.
            edits.append((Block(span.start, span.end), made, rank))
        seat = span.end
    out = list(lines)
    for span, made, _ in sorted(
        edits, key=lambda one: (one[0].start, one[0].end, one[2]), reverse=True
    ):
        out[span.start : span.end] = made
    return out


def _identity(entry: dict) -> str:
    """What makes an entry itself: the thing it names.

    Entries are matched by this rather than by position, so removing the second
    machine of seven does not shift the other six onto each other's comments --
    the survivors are recognised and left exactly where they lie.
    """
    for key in ("name", "class", "resource"):
        if entry.get(key):
            return f"{key}:{entry[key]}"
    return ""


def _pair(was: list, now: list) -> list[int | None]:
    """For each entry of `now`, which entry of `was` it is -- or None if it is new.

    Identity first, position second. Identity alone would treat a **renamed**
    machine as a removal and an addition, which loses its place in the list and
    the comment above it; position alone is what put those comments on the
    wrong machines to begin with. So the named survivors are pinned first, and
    whatever is left over on both sides is paired in order -- which is exactly
    the rename case.
    """
    taken: set[int] = set()
    found: list[int | None] = [None] * len(now)
    by_identity: dict[str, list[int]] = {}
    for index, entry in enumerate(was):
        by_identity.setdefault(_identity(entry), []).append(index)
    for index, entry in enumerate(now):
        queue = by_identity.get(_identity(entry)) or []
        while queue:
            candidate = queue.pop(0)
            if candidate not in taken:
                taken.add(candidate)
                found[index] = candidate
                break
    spare = [index for index in range(len(was)) if index not in taken]
    for index, at in enumerate(found):
        if at is None and spare:
            found[index] = spare.pop(0)
    return found


def _edit_entries(
    lines: list[str], span: Block, key: str, was: list, now: list, rank: int
) -> list[_Edit]:
    """The changes to one block list, entry by entry."""
    order = {"machines": MACHINE_KEY_ORDER, "veins": VEIN_KEY_ORDER}.get(key, STOCK_KEY_ORDER)
    entries = _scan_entries(lines, span)
    #: A list the scan cannot see entry by entry -- one folded into block
    #: mappings by hand, say -- is **refused**, not rewritten whole. Rewriting
    #: it would drop every comment inside it silently, and this module exists
    #: to keep those. A refusal costs one hand edit; a silent loss costs the
    #: reason the file was written the way it was.
    if len(entries) != len(was):
        raise VaultError(
            f"список «{key}» записан не по одной записи в строку — "
            "правьте его в файле, иначе комментарии внутри пропадут"
        )

    paired = _pair(was, now)
    edits: list[_Edit] = []
    for index, at in enumerate(paired):
        if at is None:
            continue
        if _comparable(was[at]) != _comparable(now[index]):
            entry = entries[at]
            made = [render_flow(now[index], order, indent="      - ")]
            edits.append((Block(entry.start, entry.end), made, rank))
    for index, entry in enumerate(entries):
        if index not in {at for at in paired if at is not None}:
            #: Gone, and its comment with it: left behind, it would stand over
            #: the next entry and explain something else entirely.
            edits.append((Block(entry.lead, entry.end), [], rank))
    fresh = [now[index] for index, at in enumerate(paired) if at is None]
    if fresh:
        at = entries[-1].end if entries else span.end
        edits.append(
            (Block(at, at), [render_flow(one, order, indent="      - ") for one in fresh], rank)
        )
    return edits


def _render_field(key: str, value: Any, *, head: bool) -> list[str]:
    """One field of a node as the lines it takes in the file."""
    indent = "  - " if head else "    "
    if key in NODE_BLOCK_LISTS:
        order = {"machines": MACHINE_KEY_ORDER, "veins": VEIN_KEY_ORDER}.get(key, STOCK_KEY_ORDER)
        return [
            f"{indent}{key}:",
            *(render_flow(one, order, indent="      - ") for one in value),
        ]
    if key in NODE_FLOW_LISTS:
        return [f"{indent}{key}: [{', '.join(_scalar(one) for one in value)}]"]
    return [f"{indent}{key}: {_scalar(value)}"]


def _scan_edges(lines: list[str], section: Block | None) -> list[Block]:
    """The span of each road, in the order the document has them."""
    if section is None:
        return []
    return [
        Block(number, number + 1)
        for number in range(section.start, section.end)
        if _EDGE_LINE.match(lines[number])
    ]


def _scan_pockets(lines: list[str], section: Block | None) -> dict[str, Block]:
    if section is None:
        return {}
    heads = [
        (found.group(1).strip(), number)
        for number in range(section.start, section.end)
        if (found := _POCKET_HEAD.match(lines[number]))
    ]
    blocks: dict[str, Block] = {}
    for index, (owner, start) in enumerate(heads):
        stop = heads[index + 1][1] if index + 1 < len(heads) else section.end
        blocks[owner] = Block(start, _trim(lines, start, stop))
    return blocks


# ----------------------------------------------------------------- rendering


def render_node(data: dict) -> list[str]:
    """One node as the block of lines it lies in the file as."""
    lines: list[str] = []
    for key in NODE_KEY_ORDER:
        if key not in data:
            continue
        lines.extend(_render_field(key, data[key], head=not lines))
    return lines


def render_flow(data: dict, order: tuple[str, ...], *, indent: str) -> str:
    """One entry as a flow mapping on a single line."""
    body = ", ".join(f"{key}: {_scalar(data[key])}" for key in order if key in data)
    return f"{indent}{{{body}}}"


def _mapping(value: dict) -> str:
    return "{" + ", ".join(f"{_key(k)}: {_scalar(v)}" for k, v in value.items()) + "}"


def _key(name: Any) -> str:
    return str(name)


#: Words YAML reads as something other than a string, and so must be quoted.
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~", ""}
#: Characters that end a scalar inside a flow mapping, or start a special one.
_NEEDS_QUOTES = re.compile(r"^[-?:,\[\]{}#&*!|>'\"%@`]|[:,\[\]{}]|^\s|\s$")


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{value:g}" if isinstance(value, float) else str(value)
    if isinstance(value, dict):
        return _mapping(value)
    if isinstance(value, list):
        return "[" + ", ".join(_scalar(one) for one in value) + "]"
    text = str(value)
    numeric = re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", text)
    if text.lower() in _RESERVED or numeric or _NEEDS_QUOTES.search(text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _round_trip(rendered: list[str], data: Any, what: str) -> None:
    """The rendered lines must read back as exactly what they were made from."""
    body = "\n".join(line[2:] if line.startswith("  ") else line for line in rendered)
    try:
        read = yaml.safe_load(body)
    except yaml.YAMLError as error:
        raise VaultError(f"{what} не читается обратно: {error}") from error
    if isinstance(read, list) and len(read) == 1 and not isinstance(data, list):
        read = read[0]
    if _comparable(read) != _comparable(data):
        raise VaultError(f"{what} записался бы не тем, чем задуман: {read} != {data}")


# ------------------------------------------------------------------ cleaning


def clean_node(data: dict) -> dict:
    """The authored fields of a node, checked and without the empty ones."""
    key = str(data.get("key") or "").strip()
    if not key:
        raise VaultError("у узла должен быть ключ")
    if not re.fullmatch(r"[a-z0-9]+(\.[a-z0-9]+)*", key):
        raise VaultError(
            f"ключ «{key}» не годится: только латиница, цифры и точки — «terra.capital.forge»"
        )
    out: dict[str, Any] = {"key": key, "name": _text(data.get("name"), "имя узла")}
    layer = data.get("layer") or "city"
    if layer not in LAYERS:
        raise VaultError(f"слой «{layer}» не из {', '.join(LAYERS)}")
    #: `city` is the default and the file leaves it out: written in, it would
    #: appear on every node the editor ever touched and on no other.
    if layer != "city":
        out["layer"] = layer
    if data.get("parent"):
        out["parent"] = str(data["parent"])
    out["area_m2"] = _number(data.get("area_m2"), "площадь", above=0)
    if data.get("anchor"):
        out["anchor"] = str(data["anchor"])
    place = data.get("place")
    if place:
        out["place"] = {
            "x": _number(place.get("x"), "x на карте", above=None),
            "y": _number(place.get("y"), "y на карте", above=None),
        }
    if data.get("city"):
        out["city"] = True
    properties = data.get("properties") or {}
    if properties:
        if not isinstance(properties, dict):
            raise VaultError("свойства узла — это словарь")
        out["properties"] = properties
    machines = [_clean_machine(one) for one in data.get("machines") or []]
    if machines:
        out["machines"] = machines
    relics = [str(one) for one in data.get("relics") or [] if str(one).strip()]
    if relics:
        out["relics"] = relics
    veins = [_clean_vein(one) for one in data.get("veins") or []]
    if veins:
        out["veins"] = veins
    items = [clean_stock(one) for one in data.get("items") or []]
    if items:
        out["items"] = items
    return out


def _clean_machine(data: dict) -> dict:
    name, thing_class = (data.get("name") or "").strip(), (data.get("class") or "").strip()
    if bool(name) == bool(thing_class):
        raise VaultError("станок задаётся либо вещью, либо классом вещей — но не обоими сразу")
    out: dict[str, Any] = {"name": name} if name else {"class": thing_class}
    out["quality"] = _number(data.get("quality"), "качество станка", above=0, below=100)
    return out


def _clean_vein(data: dict) -> dict:
    return {
        "resource": _text(data.get("resource"), "вид жилы"),
        "richness": _number(data.get("richness"), "богатство жилы", above=0, below=100),
        "remaining": _number(data.get("remaining"), "запас жилы", above=0),
    }


def clean_stock(data: dict) -> dict:
    out: dict[str, Any] = {"name": _text(data.get("name"), "название вещи")}
    amount = data.get("amount")
    if amount not in (None, "", 1):
        out["amount"] = _number(amount, "количество", above=0)
    out["quality"] = _number(data.get("quality"), "качество", above=0, below=100)
    if data.get("ensure"):
        out["ensure"] = True
    #: Matter never arrives in the world anonymously (pillar P1), so the ground
    #: is not an optional field of a form but the reason the thing may be there.
    out["origin"] = _text(data.get("origin"), "основание (origin)")
    return out


def clean_edge(data: dict) -> dict:
    out: dict[str, Any] = {
        "a": _text(data.get("a"), "конец дороги"),
        "b": _text(data.get("b"), "конец дороги"),
    }
    seconds = data.get("seconds")
    if seconds == BY_REACH:
        out["seconds"] = BY_REACH
    elif seconds not in (None, ""):
        out["seconds"] = _number(seconds, "секунды", above=0)
    surface = data.get("surface") or "road"
    if surface not in SURFACES:
        raise VaultError(f"покрытие «{surface}» не из {', '.join(SURFACES)}")
    out["surface"] = surface
    return out


def _text(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise VaultError(f"не задано: {what}")
    return text


def _number(value: Any, what: str, *, above: float | None, below: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise VaultError(f"«{what}» — это число, а не «{value}»") from None
    if above is not None and number <= above:
        raise VaultError(f"«{what}» должно быть больше {above:g}")
    if below is not None and number > below:
        raise VaultError(f"«{what}» должно быть не больше {below:g}")
    return int(number) if float(number).is_integer() else number


def _copy(doc: dict) -> dict:
    return copy.deepcopy(doc)
