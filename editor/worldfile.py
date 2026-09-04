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

import store
from blockfile import (
    Block,
    edit_fields,
    number_of as _number,
    render_flow,
    round_trip as _round_trip,
    scalar as _scalar,
    scan_blocks,
    scan_sections as _scan_sections,
    text_of as _text,
    trim as _trim,
)
from vaultfile import VaultError

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
#: Which order each block list is written in, and what makes an entry of
#: one itself: the name it is recognised by across an edit.
ENTRY_ORDERS = {
    "machines": MACHINE_KEY_ORDER,
    "veins": VEIN_KEY_ORDER,
    "items": STOCK_KEY_ORDER,
}
ENTRY_NAMES = ("name", "class", "resource")

LAYERS = ("planet", "city", "location")
SURFACES = ("trail", "road", "paved")
#: The edge length that means "by the node's distance" (D-180).
BY_REACH = "reach"

#: Where a node begins inside `nodes:`.
_NODE_HEAD = re.compile(r"^  - key:\s*(.+?)\s*$")
#: One line of `edges:`.
_EDGE_LINE = re.compile(r"^  - \{")
#: An owner inside `pockets:`.
_POCKET_HEAD = re.compile(r"^  (\S.*?):\s*$")


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
        self.nodes = scan_blocks(self.lines, self.sections.get("nodes"), _NODE_HEAD)
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
        return store.commit(
            store.prepare_doc(self.path, lines, expect_doc, self.mtime, self.newline)
        )[0]


# ------------------------------------------------------------------ scanning


def _edit_node(lines: list[str], block: Block, was: dict, now: dict) -> list[str]:
    """Apply a node's changes line by line, leaving everything else untouched.

    The world's own part of the job: what a node's fields are called, in which
    order they lie and which of them are lists. How a line is found and moved
    without disturbing the comment above it is `blockfile`'s (D-243).
    """
    return edit_fields(
        lines,
        block,
        clean_node(was),
        clean_node(now),
        order=NODE_KEY_ORDER,
        head_key="key",
        render=_render_field,
        block_lists=NODE_BLOCK_LISTS,
        entry_orders=ENTRY_ORDERS,
        entry_names=ENTRY_NAMES,
    )


def _render_field(key: str, value: Any, *, head: bool) -> list[str]:
    """One field of a node as the lines it takes in the file."""
    indent = "  - " if head else "    "
    if key in NODE_BLOCK_LISTS:
        order = ENTRY_ORDERS[key]
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


def _copy(doc: dict) -> dict:
    return copy.deepcopy(doc)
