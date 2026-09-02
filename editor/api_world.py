# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The handlers for `data/world.yaml`: the layout of the starting world (D-243)."""

from __future__ import annotations

import sys
from pathlib import Path

import ladder as model
from session import Session, need

#: The catalogue of place properties lives beside the vault's build: the build
#: checks the world by it, and the form offers exactly what the check accepts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import world as worldtool  # noqa: E402 -- the path has to be set first


def world(session: Session, _query: dict, _body: dict) -> dict:
    """The starting world's layout, and what the vault offers to put into it.

    The palettes come with the layout rather than being asked for separately:
    the person placing a machine wants the list of machines in front of them,
    and a second round trip to get it would only make the tab open slower.
    """
    file = session.open_world()
    _, ladder = session.open()
    return {
        "source": str(session.world),
        "external": file.doc.get("external") or [],
        "nodes": file.doc.get("nodes") or [],
        "edges": file.doc.get("edges") or [],
        "pockets": file.doc.get("pockets") or {},
        "palette": _world_palette(ladder),
        #: Place properties as a closed list with an explanation of each: the
        #: same person edits them and the machines, and the word «даль» does
        #: not explain itself. The list is the one the check refuses by
        #: (`tools/world.py`), not a second one: two lists would part ways on
        #: the first new property, and the form would offer what the build
        #: would not take.
        "properties": worldtool.WORLD_PROPERTIES,
    }


def _world_palette(ladder: model.Ladder) -> dict:
    """What may stand in a node, be dug out of it, or lie in it.

    Split by what the world does with each: machines and furniture stand
    (D-106), raw material is what a vein yields (D-151), and anything the vault
    knows at all may lie in a container. Classes are offered beside machines
    because a layout usually wants "any terminal" rather than a named one
    (D-215) -- the engine binds behaviour to the class.
    """
    standing = sorted(
        name
        for name, recipe in ladder.recipes.items()
        if recipe.get("kind") in ("station", "furniture")
    )
    return {
        "machines": standing,
        #: Only classes with something makeable in them: a class of relics
        #: alone is placed as a relic, not assembled.
        "classes": sorted(
            klass
            for klass, members in ladder.classes.items()
            if any(
                ladder.recipes.get(member, {}).get("kind") in ("station", "furniture")
                for member in members
            )
        ),
        "relics": sorted(
            klass
            for klass, members in ladder.classes.items()
            if any(ladder.materials.get(member, {}).get("relic") for member in members)
        ),
        "raw": sorted(ladder.raw),
        "things": sorted(set(ladder.recipes) | set(ladder.materials) | set(ladder.op_outputs)),
    }


def world_node(session: Session, query: dict, body: dict) -> dict:
    """Add or change one node of the layout.

    `fresh` is the "+ узел" button rather than the form of a node already open:
    it refuses a key that is taken instead of writing over somebody's place.
    """
    after = (query.get("after") or [None])[0]
    fresh = (query.get("fresh") or [""])[0] == "1"
    with session.lock:
        file = session.open_world()
        lines, doc = file.put_node(body, after=after, fresh=fresh)
        file.save(lines, doc)
    return {"key": body.get("key"), "check": session.check()}


def world_node_delete(session: Session, query: dict, _body: dict) -> dict:
    key = need(query, "key")
    with session.lock:
        file = session.open_world()
        lines, doc = file.drop_node(key)
        file.save(lines, doc)
    return {"key": key, "check": session.check()}


def world_edge(session: Session, _query: dict, body: dict) -> dict:
    with session.lock:
        file = session.open_world()
        lines, doc = file.put_edge(body)
        file.save(lines, doc)
    return {"a": body.get("a"), "b": body.get("b"), "check": session.check()}


def world_edge_delete(session: Session, query: dict, _body: dict) -> dict:
    a, b = need(query, "a"), need(query, "b")
    with session.lock:
        file = session.open_world()
        lines, doc = file.drop_edge(a, b)
        file.save(lines, doc)
    return {"a": a, "b": b, "check": session.check()}


def world_pocket(session: Session, query: dict, body: dict) -> dict:
    """Set what a starting identity carries. An empty list takes the pocket out."""
    owner = need(query, "owner")
    with session.lock:
        file = session.open_world()
        lines, doc = file.put_pocket(owner, body.get("items") or [])
        file.save(lines, doc)
    return {"owner": owner, "check": session.check()}


ROUTES = {
    ("GET", "/api/world"): world,
    ("PUT", "/api/world/node"): world_node,
    ("DELETE", "/api/world/node"): world_node_delete,
    ("PUT", "/api/world/edge"): world_edge,
    ("DELETE", "/api/world/edge"): world_edge_delete,
    ("PUT", "/api/world/pocket"): world_pocket,
}
