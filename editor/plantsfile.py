# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Reading and surgical editing of the vault's `data/plants.yaml` (D-057, D-136).

The eight cultures of Terra are the single source the build reads: the plant
catalogue page and `build/plants.json` are generated from this file, and the
yield itself is **not** written here -- the build derives it from the hours of
care a cycle asks for (D-136). What is written is what a culture asks of its
place and what it forgives: the band it drinks in, the fertility, the light,
the traits, and the feeding table of D-296.

Half the worth of the file is in the comments between the entries -- why the
turnip is not fed mineral, why St John's wort is not fed at all -- so this
edits at the line level like the world's file does, and stands on the same
machinery (`blockfile`). The rules that keep a comment over the thing it
explains live there; what is a culture's own lives here.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

import store
from blockfile import (
    Block,
    edit_fields,
    number_of,
    render_flow,
    round_trip,
    scalar,
    scan_blocks,
    scan_sections,
    text_of,
)
from vaultfile import VaultError

#: The section the cultures lie in, and where one of them begins.
SECTION = "plants"
PLANT_HEAD = re.compile(r"^  - id:\s*(.+?)\s*$")

#: The order of a culture's fields, as the file writes them. Rendering by it
#: keeps a saved culture indistinguishable from a hand-written one.
PLANT_KEY_ORDER = (
    "id",
    "wild_name",
    "seed",
    "name",
    "gives",
    "byproduct",
    "cycle",
    "requires",
    "traits",
    "restores",
    "feeding",
    "note",
)
#: The one field that is a block list of flow mappings, one row per line.
BLOCK_LISTS = ("feeding",)
FEEDING_ORDER = ("stage", "fertilizer", "growth")
#: What makes a feeding row itself: a culture may be fed twice in one stage by
#: two different things (the brome is), so the pair names it, not the stage.
FEEDING_NAMES = ("stage", "fertilizer")

#: The fields of `requires`, in the order they lie, and the shape of each.
REQUIRES_ORDER = ("temp", "water", "fertility", "light")
TEMP_ORDER = ("min", "max")
#: The fields of `traits`, on one line.
TRAITS_ORDER = ("hardiness", "disease_risk", "density_risk", "spoilage_k")

#: The stages a growing bed can be fed in (D-296). Ripeness is not one of them:
#: what is ripe is reaped, not fed.
STAGES = ("sprout", "leaf", "bloom", "fill")
#: The five-point scales the traits are given on (D-261).
TRAIT_SCALE = 5
#: What `requires.water` and `requires.light` are given on.
NEED_SCALE = 3


class PlantsFile:
    """`data/plants.yaml` as text, as a document and as a map of source blocks."""

    def __init__(self, path: Path, text: str | None = None, newline: str | None = None):
        self.path = path
        raw = path.read_bytes()
        self.newline = newline or ("\r\n" if b"\r\n" in raw else "\n")
        self.text = text if text is not None else raw.decode("utf-8").replace("\r\n", "\n")
        self.mtime = path.stat().st_mtime_ns
        self.lines = self.text.split("\n")
        self.doc = yaml.safe_load(self.text) or {}
        self.sections = scan_sections(self.lines)
        self.plants = scan_blocks(self.lines, self.sections.get(SECTION), PLANT_HEAD)

    # -- reading -----------------------------------------------------------

    def ids(self) -> list[str]:
        return [str(one.get("id")) for one in self.doc.get(SECTION) or []]

    def plant(self, plant_id: str) -> dict:
        for one in self.doc.get(SECTION) or []:
            if one.get("id") == plant_id:
                return one
        raise VaultError(f"культуры «{plant_id}» нет в файле")

    # -- editing -----------------------------------------------------------

    def put_plant(self, data: dict, *, fresh: bool = False) -> tuple[list[str], dict]:
        """Add or replace one culture. Returns the new lines and the intended document.

        An existing culture is edited **field by field**: its block carries the
        comments that explain why it is fed what it is fed, and rewriting the
        block whole would take them with it on every save. Only the lines of
        what actually changed move.

        `fresh` is the "+ культура" button rather than the form of one already
        open: an id that is taken is a refusal, not a silent overwrite.
        """
        data = clean_plant(data)
        plant_id = data["id"]
        rendered = render_plant(data)
        round_trip(rendered, data, f"культура «{plant_id}»")

        lines = list(self.lines)
        doc = copy.deepcopy(self.doc)
        plants = doc.setdefault(SECTION, [])
        found = self.plants.get(plant_id)
        if found is not None and fresh:
            raise VaultError(f"культура «{plant_id}» уже есть: откройте её слева, чтобы поправить")
        if found is not None:
            lines = _edit_plant(lines, found, self.plant(plant_id), data)
            for index, one in enumerate(plants):
                if one.get("id") == plant_id:
                    plants[index] = data
                    break
        else:
            section = self.sections.get(SECTION)
            if section is None:  # pragma: no cover -- the file always has the section
                raise VaultError("в файле культур нет раздела plants")
            lines[section.end : section.end] = ["", *rendered]
            plants.append(data)
        return lines, doc

    def drop_plant(self, plant_id: str) -> tuple[list[str], dict]:
        """Take a culture out, with the comment that introduces it."""
        block = self.plants.get(plant_id)
        if block is None:
            raise VaultError(f"культуры «{plant_id}» нет в файле")
        self.plant(plant_id)
        lines = list(self.lines)
        #: The blank line above goes too, or the file grows a gap per removal.
        start = block.start
        while start > 0 and not lines[start - 1].strip():
            start -= 1
        del lines[start : block.end]
        doc = copy.deepcopy(self.doc)
        doc[SECTION] = [one for one in (doc.get(SECTION) or []) if one.get("id") != plant_id]
        return lines, doc

    def save(self, lines: list[str], expect_doc: dict) -> Path:
        return store.save_doc(self.path, lines, expect_doc, self.mtime, self.newline)


def _edit_plant(lines: list[str], block: Block, was: dict, now: dict) -> list[str]:
    """One culture's changes, line by line.

    The feeding table is edited row by row only when there are rows on both
    sides: a table that was `[]` -- or is becoming `[]` -- needs its header
    line rewritten too, and that is a field edit, not an entry edit.
    """
    was, now = clean_plant(was), clean_plant(now)
    entry_wise = bool(was.get("feeding")) and bool(now.get("feeding"))
    return edit_fields(
        lines,
        block,
        was,
        now,
        order=PLANT_KEY_ORDER,
        head_key="id",
        render=_render_field,
        block_lists=BLOCK_LISTS if entry_wise else (),
        entry_orders={"feeding": FEEDING_ORDER},
        entry_names=FEEDING_NAMES,
    )


# ----------------------------------------------------------------- rendering


def render_plant(data: dict) -> list[str]:
    """One culture as the block of lines it lies in the file as."""
    lines: list[str] = []
    for key in PLANT_KEY_ORDER:
        if key not in data:
            continue
        lines.extend(_render_field(key, data[key], head=not lines))
    return lines


def _render_field(key: str, value: Any, *, head: bool) -> list[str]:
    """One field of a culture as the lines it takes in the file."""
    indent = "  - " if head else "    "
    if key == "requires":
        out = [f"{indent}{key}:"]
        for name in REQUIRES_ORDER:
            if name not in value:
                continue
            said = (
                render_flow(value[name], TEMP_ORDER, indent="").strip()
                if name == "temp"
                else scalar(value[name], flow=False)
            )
            out.append(f"      {name}: {said}")
        return out
    if key == "traits":
        return [f"{indent}{key}: {render_flow(value, TRAITS_ORDER, indent='').strip()}"]
    if key == "feeding":
        if not value:
            return [f"{indent}{key}: []"]
        return [
            f"{indent}{key}:",
            *(render_flow(one, FEEDING_ORDER, indent="      - ") for one in value),
        ]
    #: A field on its own line: the note of a culture is a sentence with
    #: commas in it, and quoting those would put quotation marks around
    #: every note in the file.
    return [f"{indent}{key}: {scalar(value, flow=False)}"]


# ------------------------------------------------------------------ cleaning

_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def clean_plant(data: dict) -> dict:
    """The authored fields of a culture, checked and without the empty ones.

    Checked here rather than at the build: the build refuses the whole file,
    and a form should say which field is wrong while the person is still
    looking at it. What the build alone can judge -- that a culture good at
    everything must not exist (D-057) -- stays the build's.
    """
    plant_id = text_of(data.get("id"), "идентификатор культуры")
    if not _ID.fullmatch(plant_id):
        raise VaultError(
            f"идентификатор «{plant_id}»: латиница в нижнем регистре, цифры и подчёркивание (D-251)"
        )
    out: dict[str, Any] = {
        "id": plant_id,
        "wild_name": text_of(data.get("wild_name"), "имя дикого предка"),
        "seed": text_of(data.get("seed"), "чем сеют"),
        "name": text_of(data.get("name"), "название культуры"),
        "gives": text_of(data.get("gives"), "что даёт культура"),
    }
    if str(data.get("byproduct") or "").strip():
        out["byproduct"] = str(data["byproduct"]).strip()
    out["cycle"] = number_of(data.get("cycle"), "длина цикла", above=1)
    out["requires"] = _clean_requires(data.get("requires") or {})
    out["traits"] = _clean_traits(data.get("traits") or {})
    if data.get("restores") not in (None, "", 0):
        out["restores"] = number_of(data["restores"], "возврат плодородия", above=0, below=100)
    out["feeding"] = _clean_feeding(data.get("feeding") or [])
    if str(data.get("note") or "").strip():
        out["note"] = str(data["note"]).strip()
    return out


def _clean_requires(data: dict) -> dict:
    temp = data.get("temp") or {}
    low = number_of(temp.get("min"), "нижняя температура", above=-100, below=100)
    high = number_of(temp.get("max"), "верхняя температура", above=-100, below=100)
    if low >= high:
        raise VaultError("температура: нижняя граница должна быть ниже верхней")
    return {
        "temp": {"min": low, "max": high},
        "water": int(number_of(data.get("water"), "потребность в воде", above=1, below=NEED_SCALE)),
        "fertility": number_of(data.get("fertility"), "требуемое плодородие", above=0, below=100),
        "light": int(number_of(data.get("light"), "светолюбивость", above=1, below=NEED_SCALE)),
    }


def _clean_traits(data: dict) -> dict:
    out = {}
    for key, what in (
        ("hardiness", "выносливость"),
        ("disease_risk", "боязнь напастей"),
        ("density_risk", "боязнь тесноты"),
    ):
        out[key] = int(number_of(data.get(key), what, above=1, below=TRAIT_SCALE))
    out["spoilage_k"] = number_of(data.get("spoilage_k"), "множитель порчи", above=0, below=10)
    return out


def _clean_feeding(rows: list) -> list[dict]:
    """The feeding table (D-296): a stage, a fertilizer and what it quickens.

    Two rows for one pair are refused: the engine reads the first match, and a
    second one would be a number nobody could see the effect of.
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        stage = str((row or {}).get("stage") or "").strip()
        if stage not in STAGES:
            raise VaultError(f"фаза «{stage}»: бывают только {', '.join(STAGES)}")
        fertilizer = text_of((row or {}).get("fertilizer"), "чем кормят")
        pair = (stage, fertilizer)
        if pair in seen:
            raise VaultError(f"«{fertilizer}» в фазу «{stage}» записано дважды")
        seen.add(pair)
        out.append(
            {
                "stage": stage,
                "fertilizer": fertilizer,
                "growth": number_of(row.get("growth"), "ускорение роста", above=1, below=500),
            }
        )
    return out
