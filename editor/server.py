# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The local server of the recipe editor.

Standard library only, on purpose: the tool has to start in a fresh clone with
nothing but `pyyaml` -- the same single dependency the vault's own build has.
It binds to the loopback address and to nothing else: it writes files, and a tool
that writes files has no business listening on the network.

    python editor/server.py
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import constantsfile as consts
import ladder as model
import vaultfile as vault

STATIC = Path(__file__).resolve().parent / "static"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}


class Session:
    """Everything a request needs, and one lock so two saves never overlap."""

    def __init__(self, vault_root: Path):
        self.vault = vault_root
        self.source = vault_root / "data" / "recipes.yaml"
        #: Building types live in the other data file (D-218): four maps that
        #: must agree, and the tool keeps them in step.
        self.constants = vault_root / "data" / "constants.yaml"
        self.lock = threading.Lock()

    def open(self, text: str | None = None) -> tuple[vault.RecipesFile, model.Ladder]:
        file = vault.RecipesFile(self.source, text=text)
        derived, stale = model.load_derived(self.vault)
        ladder = model.Ladder(file, derived)
        ladder.stale = stale
        return file, ladder

    def open_constants(self, text: str | None = None) -> consts.ConstantsFile:
        return consts.ConstantsFile(self.constants, text=text)


# ------------------------------------------------------------------ handlers


def state(session: Session, _query: dict, _body: dict) -> dict:
    file, ladder = session.open()
    return {
        "vault": str(session.vault),
        "source": str(session.source),
        "stale": ladder.stale,
        "nodes": ladder.nodes(),
        "edges": ladder.edges(),
        "operations": [
            {
                "name": op["name"],
                "requires": op.get("requires") or [],
                "gives": op.get("gives") or [],
                "consumes": op.get("consumes") or [],
                "place": op.get("place"),
            }
            for op in ladder.operations
        ],
        "stations": ladder.stations(),
        #: Building types (D-218). Read from the constants file, not the recipe
        #: one -- but shown in the same window, because a type is a composition
        #: and a composition is what this tool is about.
        "buildings": _buildings(session),
        "constants_source": str(session.constants),
        "vocabulary": ladder.vocabulary(),
        "counts": {
            "recipes": len(ladder.recipes),
            "raw": len(ladder.raw),
            "materials": len(ladder.materials),
            "classes": len(ladder.class_notes),
            "operations": len(ladder.operations),
        },
        "undo": (backup.name if (backup := vault.last_backup()) else None),
    }


def recipe(session: Session, query: dict, _body: dict) -> dict:
    name = _need(query, "name")
    file, ladder = session.open()
    if name not in ladder.known_names():
        raise vault.VaultError(f"«{name}» нет в вольте")
    # Only recipes have a form. Raw material, operations and tool classes are
    # shown as they are: there are few of them, each line is explained by a
    # comment above it, and a form would only invite editing them blindly.
    authored = dict(ladder.recipes.get(name) or {})
    return {
        "name": name,
        "editable": name in ladder.recipes,
        "data": {k: v for k, v in authored.items() if k not in ("level", "section")},
        "level": authored.get("level"),
        "section": authored.get("section"),
        #: The material registry row, when the name is a material (D-215).
        "material": ladder.materials.get(name),
        "source": file.source_of(name),
        "comment": file.comment_above(name),
        "references": model.references(name, ladder),
        "cost": ladder.raw_cost(name),
        "derived": ladder.derived_recipes.get(name),
    }


def cost(session: Session, query: dict, _body: dict) -> dict:
    name = _need(query, "name")
    _, ladder = session.open()
    quantity = float(query.get("quantity", ["1"])[0])
    return ladder.raw_cost(name, quantity)


def create(session: Session, _query: dict, body: dict) -> dict:
    data = _clean(body.get("data") or {})
    level = body.get("level")
    section = body.get("section") or None
    if level is None:
        raise vault.VaultError("не выбран уровень лестницы")
    with session.lock:
        file, ladder = session.open()
        model.validate(data, ladder)
        lines = file.insert(data, int(level), section)
        vault.save(
            session.source,
            lines,
            {"name": data["name"], "data": data},
            file.mtime,
            file.newline,
        )
    return {"saved": data["name"], "check": _check(session)}


def update(session: Session, query: dict, body: dict) -> dict:
    original = _need(query, "name")
    data = _clean(body.get("data") or {})
    rename_refs = bool(body.get("rename_refs"))
    with session.lock:
        file, ladder = session.open()
        if original not in ladder.recipes:
            raise vault.VaultError(f"рецепта «{original}» нет в файле")
        model.validate(data, ladder, original=original)

        renamed = data["name"] != original
        text = file.text
        if renamed and original in ladder.class_notes:
            raise vault.VaultError(
                f"«{original}» — ещё и имя класса, на которое завязано поведение "
                "движка. Сплошная замена переименовала бы и класс: переименуйте "
                "без обновления ссылок и поправьте их руками."
            )
        if renamed and rename_refs:
            text = vault.rename_everywhere(file.text, original, data["name"])
            file = vault.RecipesFile(session.source, text=text, newline=file.newline)

        was = ladder.recipes[original]
        target = int(body["level"]) if body.get("level") is not None else was["level"]
        section = (body.get("section") if "section" in body else was["section"]) or None
        moved = (target, section) != (was["level"], was["section"])

        key = data["name"] if (renamed and rename_refs) else original
        if moved:
            file = vault.RecipesFile(
                session.source, text="\n".join(file.cut(key)), newline=file.newline
            )
            lines = file.insert(data, target, section)
        else:
            lines = file.replace(key, data)

        expect: dict[str, Any] = {"name": data["name"], "data": data}
        if renamed:
            expect["absent"] = [original]
        vault.save(
            session.source,
            lines,
            expect,
            file.mtime if not renamed else None,
            file.newline,
        )
    return {"saved": data["name"], "renamed": renamed, "check": _check(session)}


def delete(session: Session, query: dict, body: dict) -> dict:
    name = _need(query, "name")
    with session.lock:
        file, ladder = session.open()
        if name not in ladder.recipes:
            raise vault.VaultError(f"рецепта «{name}» нет в файле")
        lines = file.cut(name, with_comment=bool(body.get("with_comment")))
        vault.save(
            session.source,
            lines,
            {"name": name, "data": None},
            file.mtime,
            file.newline,
        )
    return {"deleted": name, "check": _check(session)}


def measure(session: Session, query: dict, body: dict) -> dict:
    """How a thing is measured: whole or fractional, and by what word.

    Since D-215 the fraction sign lives on the thing's own line -- `bulk: true`
    on a recipe or a material row -- and `units` stays a `meta` map, because a
    word to draw is presentation, not a property of the thing. Mass may be set
    here for a material only: a recipe's mass belongs to its form.
    """
    name = _need(query, "name")
    unit = str(body.get("unit") or "").strip()
    bulk = bool(body.get("bulk"))
    with session.lock:
        file, ladder = session.open()
        if name not in ladder.known_names():
            raise vault.VaultError(f"«{name}» нет в вольте")
        is_material = name in ladder.materials
        if not is_material and name not in ladder.recipes:
            raise vault.VaultError(
                f"«{name}» не вещь, а требование — измерения у него нет"
            )
        if "mass" in body and not is_material:
            raise vault.VaultError(
                f"«{name}» — рецепт: его масса задаётся полем «масса, кг» в форме, "
                "а не здесь. Иначе у одной вещи стало бы два веса."
            )

        data = _entry_data(ladder, name)
        if bulk:
            data["bulk"] = True
        else:
            data.pop("bulk", None)
        if "mass" in body and is_material:
            mass = body.get("mass")
            if not isinstance(mass, (int, float)) or isinstance(mass, bool) or mass < 0:
                raise vault.VaultError("масса должна быть числом не меньше нуля")
            data["mass"] = int(mass) if float(mass).is_integer() else float(mass)
            model.validate_material(data, ladder, original=name)

        expect = copy.deepcopy(file.doc)
        _expect_entry(expect, name, data, is_material=is_material)
        units = {
            k: v for k, v in (expect["meta"].get("units") or {}).items() if k != name
        }
        if unit:
            units[name] = unit
        expect["meta"]["units"] = units

        lines = _write_entry(
            session, file, list(file.lines), name, data, is_material=is_material
        )
        after = vault.RecipesFile(
            session.source, text="\n".join(lines), newline=file.newline
        )
        lines = vault.MetaBlock(after, "units").put(name, unit or None)
        vault.save_doc(session.source, lines, expect, file.mtime, file.newline)
    return {"measured": name, "check": _check(session)}


def _entry_data(ladder: model.Ladder, name: str) -> dict:
    """The authored line of a thing -- a recipe or a material row."""
    found = ladder.recipes.get(name)
    if found is not None:
        return {
            key: value
            for key, value in found.items()
            if key not in ("level", "section") and value is not None
        }
    material = ladder.materials.get(name)
    if material is not None:
        return dict(material)
    raise vault.VaultError(f"«{name}» — не вещь: класс носят рецепты и материалы")


def _write_entry(
    session: Session, file: vault.RecipesFile, lines: list[str], name: str, data: dict,
    *, is_material: bool,
) -> list[str]:
    """Replace one thing's line in the running edit chain."""
    step = vault.RecipesFile(session.source, text="\n".join(lines), newline=file.newline)
    if is_material:
        return step.replace_meta_entry("materials", name, data, vault.MATERIAL_KEY_ORDER)
    return step.replace(name, data)


def _expect_entry(expect: dict, name: str, data: dict, *, is_material: bool) -> None:
    """Mutate the expected document the same way the lines were mutated."""
    if is_material:
        rows = expect["meta"]["materials"]
        for index, row in enumerate(rows):
            if row.get("name") == name:
                rows[index] = data
                return
        raise vault.VaultError(f"в meta.materials нет «{name}»")
    found = vault._find_recipe(expect, name)  # noqa: SLF001 -- one module family
    if found is None:
        raise vault.VaultError(f"рецепта «{name}» нет в файле")
    found.clear()
    found.update(data)


def put_class(session: Session, query: dict, body: dict) -> dict:
    """Declare a thing class and set its members (D-215).

    A class is a declaration in `meta.classes` plus a `class:` field on each
    member's own line -- so this handler edits several lines, each with the
    same one-line surgery, and verifies the whole document once.

    Renaming is deliberately not offered. A class name is what the engine
    behaviour binds to, and a sweep over the file would also catch the thing of
    the same name where there is one («Топор»). Make the new class, move the
    members, delete the old one -- three visible steps instead of one blind sweep.
    """
    name = _need(query, "name").strip()
    note = str(body.get("note") or "").strip()
    members = [str(item).strip() for item in (body.get("members") or []) if str(item).strip()]
    with session.lock:
        file, ladder = session.open()
        original = name if name in ladder.class_notes else None
        model.validate_class(name, members, ladder, original=original)

        expect = copy.deepcopy(file.doc)
        lines = list(file.lines)
        if original is None:
            declaration = {"name": name, **({"note": note} if note else {})}
            expect["meta"].setdefault("classes", []).append(declaration)
            step = vault.RecipesFile(
                session.source, text="\n".join(lines), newline=file.newline
            )
            lines = step.insert_meta_entry("classes", declaration, ("name", "note"))

        was = set(ladder.classes.get(name, ()))
        for member in sorted(was - set(members)):
            data = _entry_data(ladder, member)
            data.pop("class", None)
            is_material = member in ladder.materials
            _expect_entry(expect, member, data, is_material=is_material)
            lines = _write_entry(session, file, lines, member, data, is_material=is_material)
        for member in members:
            if member in was:
                continue
            data = _entry_data(ladder, member)
            data["class"] = name
            is_material = member in ladder.materials
            _expect_entry(expect, member, data, is_material=is_material)
            lines = _write_entry(session, file, lines, member, data, is_material=is_material)

        vault.save_doc(session.source, lines, expect, file.mtime, file.newline)
        #: Said about the file as it now is, not as it was: the warning is about
        #: what the person will see on the picture after this write.
        warning = model.class_warning(name, session.open()[1])
    return {
        "class": name,
        "created": original is None,
        "warning": warning,
        "check": _check(session),
    }


def drop_class(session: Session, query: dict, _body: dict) -> dict:
    """Take a thing class out of the file: the declaration and every `class:`
    field naming it. The things themselves stay, of course."""
    name = _need(query, "name")
    with session.lock:
        file, ladder = session.open()
        if name not in ladder.class_notes:
            raise vault.VaultError(f"класса «{name}» в вольте нет")
        note = ladder.class_notes.get(name) or ""

        expect = copy.deepcopy(file.doc)
        expect["meta"]["classes"] = [
            entry
            for entry in (expect["meta"].get("classes") or [])
            if entry.get("name") != name
        ]
        lines = file.cut_meta_entry("classes", name)
        for member in ladder.classes.get(name, ()):
            data = _entry_data(ladder, member)
            data.pop("class", None)
            is_material = member in ladder.materials
            _expect_entry(expect, member, data, is_material=is_material)
            lines = _write_entry(session, file, lines, member, data, is_material=is_material)
        vault.save_doc(session.source, lines, expect, file.mtime, file.newline)
    warning = (
        f"класс «{name}» помечен как поведение движка — без него это поведение "
        "потеряет все свои вещи"
        if note.startswith("поведение")
        else None
    )
    return {"deleted": name, "warning": warning, "check": _check(session)}


def membership(session: Session, query: dict, body: dict) -> dict:
    """The class of one thing -- set from the side of the thing (D-215).

    A person editing a pickaxe thinks "this is a pickaxe", not "add a member to
    the class". A thing has one class, so more than one is refused up front.
    """
    name = _need(query, "name")
    wanted = [str(item).strip() for item in (body.get("classes") or []) if str(item).strip()]
    if len(wanted) > 1:
        raise vault.VaultError(
            f"у вещи один класс (D-215), а названо {len(wanted)}: {', '.join(wanted)}"
        )
    chosen = wanted[0] if wanted else None
    with session.lock:
        file, ladder = session.open()
        if chosen is not None and chosen not in ladder.class_notes:
            raise vault.VaultError(f"класса «{chosen}» в вольте нет — сперва заведите его")
        data = _entry_data(ladder, name)
        if data.get("class") == chosen or (chosen is None and "class" not in data):
            return {"name": name, "classes": wanted, "check": None}
        if chosen is None:
            data.pop("class", None)
        else:
            data["class"] = chosen

        expect = copy.deepcopy(file.doc)
        is_material = name in ladder.materials
        _expect_entry(expect, name, data, is_material=is_material)
        lines = _write_entry(session, file, list(file.lines), name, data, is_material=is_material)
        vault.save_doc(session.source, lines, expect, file.mtime, file.newline)
    return {"name": name, "classes": wanted, "check": _check(session)}


# ------------------------------------------------- building types (D-218)


def _buildings(session: Session) -> list[dict]:
    """The ladder of building types, or nothing if the file cannot say.

    A constants file the editor cannot read must not take the recipe window down
    with it: the tab shows the reason and the rest of the editor works on.
    """
    try:
        return session.open_constants().types()
    except (vault.VaultError, OSError) as error:
        return [{"error": str(error)}]


BUILDING_NUMBERS = (
    ("growth", "рост цены этажа", 1.0),
    ("decay", "порча, % в сутки", 0.0),
)


def _clean_building(data: dict, ladder: model.Ladder) -> dict:
    """One type's row, checked against the vault before a line is written.

    The check that matters is the composition: a material named with a typo
    would pass YAML, pass the build and only fail in the engine, at the moment
    somebody tries to build a house of it.
    """
    kind = str(data.get("kind") or "").strip()
    if not kind:
        raise vault.VaultError("у типа здания должно быть название")

    parts = data.get("per_m2") or {}
    if not isinstance(parts, dict) or not parts:
        raise vault.VaultError(f"«{kind}»: состав пуст — из чего-то дом строить надо")
    known = ladder.known_names()
    composition: dict[str, float] = {}
    for raw_name, raw_amount in parts.items():
        name = str(raw_name).strip()
        if not name:
            continue
        if name not in known:
            raise vault.VaultError(
                f"«{kind}»: материала «{name}» нет в вольте. "
                "Сначала заведите его в реестре материалов."
            )
        amount = _positive(raw_amount, f"«{kind}» → «{name}»")
        composition[name] = amount
    if not composition:
        raise vault.VaultError(f"«{kind}»: состав пуст — из чего-то дом строить надо")

    row = {"kind": kind, "per_m2": composition}
    for field, label, floor in BUILDING_NUMBERS:
        value = data.get(field)
        if value in (None, ""):
            raise vault.VaultError(f"«{kind}»: не задано «{label}»")
        number = float(value)
        if number < floor:
            raise vault.VaultError(
                f"«{kind}»: «{label}» не бывает меньше {_pretty(floor)}"
            )
        row[field] = int(number) if float(number).is_integer() else number
    return row


def _positive(value: Any, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise vault.VaultError(f"{what}: «{value}» — не число") from error
    if number <= 0:
        raise vault.VaultError(f"{what}: расход должен быть больше нуля")
    return int(number) if number.is_integer() else number


def _pretty(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _save_types(session: Session, rows: list[dict]) -> None:
    file = session.open_constants()
    expect = file.set_types(rows)
    vault.save_doc(session.constants, file.lines, expect, file.mtime, file.newline)


def building_create(session: Session, _query: dict, body: dict) -> dict:
    """A new building type: one row, and all three maps get it at once (D-218)."""
    with session.lock:
        _, ladder = session.open()
        row = _clean_building(body.get("data") or {}, ladder)
        file = session.open_constants()
        rows = file.types()
        if any(existing["kind"] == row["kind"] for existing in rows):
            raise vault.VaultError(f"тип «{row['kind']}» уже есть")
        #: Appended at the end: the ladder runs from the cheapest upwards and
        #: the engine takes the first of it as the default (`estate.kinds`), so
        #: a new type must not silently become what unnamed houses are built of.
        _save_types(session, [*rows, row])
    return {"saved": row["kind"], "check": _check(session)}


def building_update(session: Session, query: dict, body: dict) -> dict:
    original = _need(query, "name")
    with session.lock:
        _, ladder = session.open()
        row = _clean_building(body.get("data") or {}, ladder)
        file = session.open_constants()
        rows = file.types()
        if not any(existing["kind"] == original for existing in rows):
            raise vault.VaultError(f"типа «{original}» нет в файле")
        if row["kind"] != original and any(x["kind"] == row["kind"] for x in rows):
            raise vault.VaultError(f"тип «{row['kind']}» уже есть")
        #: Renaming is allowed and is a real edit: the type's name is written on
        #: every house already standing, so the engine's migration has to follow.
        #: The tool says so rather than pretending the rename is free.
        _save_types(
            session,
            [row if existing["kind"] == original else existing for existing in rows],
        )
    return {
        "saved": row["kind"],
        "renamed": None if row["kind"] == original else original,
        "check": _check(session),
    }


def building_delete(session: Session, query: dict, _body: dict) -> dict:
    name = _need(query, "name")
    with session.lock:
        file = session.open_constants()
        rows = file.types()
        if not any(existing["kind"] == name for existing in rows):
            raise vault.VaultError(f"типа «{name}» нет в файле")
        if len(rows) == 1:
            raise vault.VaultError(
                "это последний тип: строить дома было бы не из чего"
            )
        _save_types(session, [row for row in rows if row["kind"] != name])
    return {"deleted": name, "check": _check(session)}


def material_create(session: Session, _query: dict, body: dict) -> dict:
    """A new material: one registry row is all a new raw thing needs (D-215)."""
    data = _clean_material(body.get("data") or {})
    with session.lock:
        file, ladder = session.open()
        model.validate_material(data, ladder)
        expect = copy.deepcopy(file.doc)
        expect["meta"].setdefault("materials", []).append(data)
        lines = file.insert_meta_entry("materials", data, vault.MATERIAL_KEY_ORDER)
        vault.save_doc(session.source, lines, expect, file.mtime, file.newline)
    return {"saved": data["name"], "check": _check(session)}


def material_update(session: Session, query: dict, body: dict) -> dict:
    original = _need(query, "name")
    data = _clean_material(body.get("data") or {})
    if data.get("name") != original:
        raise vault.VaultError(
            "материал не переименовывается формой: на имя ссылаются рецепты, "
            "операции и мир. Переименование — отдельный осознанный шаг."
        )
    with session.lock:
        file, ladder = session.open()
        if original not in ladder.materials:
            raise vault.VaultError(f"материала «{original}» нет в файле")
        model.validate_material(data, ladder, original=original)
        expect = copy.deepcopy(file.doc)
        _expect_entry(expect, original, data, is_material=True)
        lines = file.replace_meta_entry(
            "materials", original, data, vault.MATERIAL_KEY_ORDER
        )
        vault.save_doc(session.source, lines, expect, file.mtime, file.newline)
    return {"saved": original, "check": _check(session)}


def material_delete(session: Session, query: dict, _body: dict) -> dict:
    name = _need(query, "name")
    with session.lock:
        file, ladder = session.open()
        if name not in ladder.materials:
            raise vault.VaultError(f"материала «{name}» нет в файле")
        used = model.references(name, ladder)
        holders = [*used["inputs"], *used["stations"], *used["operations"]]
        if holders:
            listed = ", ".join(f"«{x}»" for x in holders[:5])
            raise vault.VaultError(
                f"«{name}» используется: {listed}"
                + (" и ещё" if len(holders) > 5 else "")
                + ". Сначала уберите ссылки."
            )
        expect = copy.deepcopy(file.doc)
        expect["meta"]["materials"] = [
            row
            for row in (expect["meta"].get("materials") or [])
            if row.get("name") != name
        ]
        lines = file.cut_meta_entry("materials", name)
        vault.save_doc(session.source, lines, expect, file.mtime, file.newline)
    return {"deleted": name, "check": _check(session)}


MATERIAL_BOOL_FIELDS = ("bulk", "edible")
MATERIAL_NUMBER_FIELDS = ("mass", "rate", "fuel")


def _clean_material(data: dict) -> dict:
    out: dict[str, Any] = {}
    for key in vault.MATERIAL_KEY_ORDER:
        if key not in data:
            continue
        value = data[key]
        if value in (None, "", [], {}) or (key in MATERIAL_BOOL_FIELDS and not value):
            continue
        if key in MATERIAL_NUMBER_FIELDS:
            value = float(value)
            value = int(value) if float(value).is_integer() else value
        if key == "forage":
            value = {
                part: (int(v) if float(v).is_integer() else float(v))
                for part, v in value.items()
                if part in ("finds", "handful") and v not in (None, "")
            }
            if not value:
                continue
        out[key] = value
    if "name" not in out:
        raise vault.VaultError("у материала должно быть название")
    if "mass" not in out:
        #: Zero is a legal mass (energy weighs nothing) -- it survives _clean
        #: only if given explicitly as 0.
        if isinstance(data.get("mass"), (int, float)):
            out["mass"] = 0
        else:
            raise vault.VaultError("у материала должна быть масса (можно 0)")
    return out


def undo(session: Session, _query: dict, _body: dict) -> dict:
    #: Which file is rolled back is decided by which was written last, not by
    #: the tab in front of the person: the editor writes two of them now (D-218).
    with session.lock:
        restored = vault.undo(session.source)
    return {"restored": restored, "check": _check(session)}


def check(session: Session, _query: dict, _body: dict) -> dict:
    return _check(session)


def build(session: Session, _query: dict, _body: dict) -> dict:
    return _run([sys.executable, "tools/build.py"], session.vault)


def masses(session: Session, _query: dict, _body: dict) -> dict:
    """Recompute every item's mass out of its inputs and report (D-228).

    Writes nothing, and that is the point: mass is derived, and derived numbers
    are shown, never written back into the source (D-133). Written back, an
    auto mass would become an authored one on the next read and stop counting
    itself -- so the answer to "why is this one not moving" is the report,
    which names every item whose mass is pinned by hand.
    """
    return _run([sys.executable, "tools/build.py", "--masses"], session.vault)


ROUTES = {
    ("GET", "/api/state"): state,
    ("GET", "/api/recipe"): recipe,
    ("GET", "/api/cost"): cost,
    ("POST", "/api/recipe"): create,
    ("PUT", "/api/recipe"): update,
    ("DELETE", "/api/recipe"): delete,
    ("POST", "/api/material"): material_create,
    ("PUT", "/api/material"): material_update,
    ("DELETE", "/api/material"): material_delete,
    ("POST", "/api/building"): building_create,
    ("PUT", "/api/building"): building_update,
    ("DELETE", "/api/building"): building_delete,
    ("PUT", "/api/measure"): measure,
    ("PUT", "/api/class"): put_class,
    ("DELETE", "/api/class"): drop_class,
    ("PUT", "/api/classes"): membership,
    ("POST", "/api/masses"): masses,
    ("POST", "/api/check"): check,
    ("POST", "/api/build"): build,
    ("POST", "/api/undo"): undo,
}


# ------------------------------------------------------------------- helpers


def _need(query: dict, key: str) -> str:
    values = query.get(key)
    if not values or not values[0]:
        raise vault.VaultError(f"не хватает параметра «{key}»")
    return values[0]


def _clean(data: dict) -> dict:
    """The authored fields, without the empty ones the form always sends."""
    out: dict[str, Any] = {}
    for key in vault.KEY_ORDER:
        if key not in data:
            continue
        value = data[key]
        if value in (None, "", [], {}) or (key in vault.BOOL_FIELDS and not value):
            continue
        if key in vault.NUMBER_FIELDS:
            value = float(value)
            value = int(value) if float(value).is_integer() else value
        if key in vault.MAP_FIELDS:
            value = {k: (int(v) if float(v).is_integer() else float(v)) for k, v in value.items()}
        out[key] = value
    if "name" not in out:
        raise vault.VaultError("у рецепта должно быть название")
    return out


def _check(session: Session) -> dict:
    return _run([sys.executable, "tools/build.py", "--check"], session.vault)


def _run(command: list[str], cwd: Path) -> dict:
    """Run a vault tool and bring its words back as they were printed.

    Windows would hand the child a cp1251 pipe and the Russian output would come
    back as question marks, so the child is told to speak UTF-8.
    """
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        done = subprocess.run(
            command, cwd=cwd, capture_output=True, env=env, timeout=300, check=False
        )
    except FileNotFoundError as error:
        raise vault.VaultError(f"не удалось запустить: {' '.join(command)} ({error})") from error
    text = (done.stdout + done.stderr).decode("utf-8", errors="replace").strip()
    return {"command": " ".join(command), "code": done.returncode, "output": text}


# -------------------------------------------------------------------- server


class Handler(BaseHTTPRequestHandler):
    session: Session

    protocol_version = "HTTP/1.1"
    server_version = "vault-editor"

    def do_GET(self) -> None:  # noqa: N802 -- the name is the stdlib's
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._api("GET", parsed)
            return
        self._static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        self._api("POST", urlparse(self.path))

    def do_PUT(self) -> None:  # noqa: N802
        self._api("PUT", urlparse(self.path))

    def do_DELETE(self) -> None:  # noqa: N802
        self._api("DELETE", urlparse(self.path))

    def log_message(self, fmt: str, *args: Any) -> None:
        if "500" in str(args) or "400" in str(args):
            super().log_message(fmt, *args)

    # -- plumbing ----------------------------------------------------------

    def _api(self, method: str, parsed) -> None:
        route = ROUTES.get((method, parsed.path))
        if route is None:
            self._send(404, {"error": f"нет такого адреса: {method} {parsed.path}"})
            return
        try:
            body = self._body()
            payload = route(self.session, parse_qs(parsed.query), body)
            self._send(200, payload)
        except vault.VaultError as error:
            self._send(400, {"error": str(error)})
        except Exception as error:  # noqa: BLE001 -- a dev tool reports, not dies
            import traceback

            self._send(500, {"error": f"{type(error).__name__}: {error}",
                             "trace": traceback.format_exc()})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def _static(self, path: str) -> None:
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC / name).resolve()
        if not target.is_file() or STATIC.resolve() not in target.parents:
            self._send(404, {"error": f"нет файла: {name}"})
            return
        payload = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "text/plain"))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Редактор рецептов вольта Everse.Life")
    port = int(os.environ.get("EVERSELIFE_EDITOR_PORT", 8765))
    parser.add_argument("--port", type=int, default=port)
    parser.add_argument("--vault", default=None, help="путь к вольту гейм-дизайна")
    # Loopback by default: инструмент пишет в файлы. В контейнере петля своя, и
    # снаружи к ней не пробиться, поэтому образ поднимает сервер на 0.0.0.0 —
    # границей там служит проброс порта, а не адрес.
    parser.add_argument(
        "--host",
        default=os.environ.get("EVERSELIFE_EDITOR_HOST", "127.0.0.1"),
        help="адрес, на котором слушать (по умолчанию только петля)",
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if args.vault:
        os.environ["EVERSELIFE_VAULT"] = args.vault
    try:
        root = vault.vault_root()
    except vault.VaultError as error:
        print(error, file=sys.stderr)
        return 1

    Handler.session = Session(root)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host  # noqa: S104
    url = f"http://{shown}:{args.port}/"
    print(f"Редактор рецептов: {url}")
    print(f"Вольт: {root}")
    print("Правится только data/recipes.yaml. Ctrl+C — выход.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nВыход.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
