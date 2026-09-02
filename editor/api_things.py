# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The handlers for things of the ladder: recipes, materials, classes, measures.

Every write here is one edit of `data/recipes.yaml` -- and, since D-251, of
every `data/locales/*.yaml` beside it: a thing without a name in each language
is a thing the build refuses, so the name is asked for with the thing and
written under the same stamp. Undo takes both back together.
"""

from __future__ import annotations

import copy
from typing import Any

import ladder as model
import localefile as words
import store
import vaultfile as vault
from session import Session, name_writes, need, spoken_names

#: Where a thing's name lives in the locale files: recipes and materials are
#: goods, and share one space of keys (D-251); classes have their own.
GOODS = "goods"
CLASSES = "classes"


def recipe(session: Session, query: dict, _body: dict) -> dict:
    name = need(query, "name")
    file, ladder = session.open()
    if name not in ladder.known_names():
        raise vault.VaultError(f"«{name}» нет в вольте")
    # Only recipes have a form. Raw material, operations and tool classes are
    # shown as they are: there are few of them, each line is explained by a
    # comment above it, and a form would only invite editing them blindly.
    authored = dict(ladder.recipes.get(name) or {})
    material = ladder.materials.get(name)
    entry_id = authored.get("id") or (material or {}).get("id")
    return {
        "name": name,
        "editable": name in ladder.recipes,
        "data": {k: v for k, v in authored.items() if k not in ("level", "section")},
        "level": authored.get("level"),
        "section": authored.get("section"),
        #: The material registry row, when the name is a material (D-215).
        "material": material,
        #: What the other languages call it (D-251): shown beside the name,
        #: written with it.
        "names": spoken_names(session, GOODS, entry_id),
        "source": file.source_of(name),
        "comment": file.comment_above(name),
        "references": model.references(name, ladder),
        "cost": ladder.raw_cost(name),
        "derived": ladder.derived_recipes.get(name),
    }


def cost(session: Session, query: dict, _body: dict) -> dict:
    name = need(query, "name")
    _, ladder = session.open()
    quantity = float(query.get("quantity", ["1"])[0])
    return ladder.raw_cost(name, quantity)


def create(session: Session, _query: dict, body: dict) -> dict:
    data = clean_recipe(body.get("data") or {})
    level = body.get("level")
    section = body.get("section") or None
    if level is None:
        raise vault.VaultError("не выбран уровень лестницы")
    names = words.clean_names(body.get("names"), session.languages(), data["name"])
    with session.lock:
        file, ladder = session.open()
        model.validate(data, ladder)
        lines = file.insert(data, int(level), section)
        writes = [
            store.prepare(
                session.source, lines, {"name": data["name"], "data": data},
                file.mtime, file.newline,
            ),
            *name_writes(session, GOODS, data.get("id"), names),
        ]
        store.commit(*writes)
    return {"saved": data["name"], "check": session.check()}


def update(session: Session, query: dict, body: dict) -> dict:
    original = need(query, "name")
    data = clean_recipe(body.get("data") or {})
    rename_refs = bool(body.get("rename_refs"))
    names = (
        words.clean_names(body.get("names"), session.languages(), data["name"])
        if body.get("names") is not None
        else None
    )
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
        writes = [
            store.prepare(
                session.source, lines, expect,
                file.mtime if not renamed else None, file.newline,
            ),
            *name_writes(session, GOODS, data.get("id"), names, was_id=was.get("id")),
        ]
        store.commit(*writes)
    return {"saved": data["name"], "renamed": renamed, "check": session.check()}


def delete(session: Session, query: dict, body: dict) -> dict:
    name = need(query, "name")
    with session.lock:
        file, ladder = session.open()
        if name not in ladder.recipes:
            raise vault.VaultError(f"рецепта «{name}» нет в файле")
        lines = file.cut(name, with_comment=bool(body.get("with_comment")))
        writes = [
            store.prepare(
                session.source, lines, {"name": name, "data": None}, file.mtime, file.newline
            ),
            *name_writes(session, GOODS, ladder.recipes[name].get("id"), None, gone=True),
        ]
        store.commit(*writes)
    return {"deleted": name, "check": session.check()}


def measure(session: Session, query: dict, body: dict) -> dict:
    """How a thing is measured: whole or fractional, and by what word.

    Since D-215 the fraction sign lives on the thing's own line -- `bulk: true`
    on a recipe or a material row -- and `units` stays a `meta` map, because a
    word to draw is presentation, not a property of the thing. Mass may be set
    here for a material only: a recipe's mass belongs to its form.
    """
    name = need(query, "name")
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
        store.save_doc(session.source, lines, expect, file.mtime, file.newline)
    return {"measured": name, "check": session.check()}


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


# ------------------------------------------------------------ classes (D-215)


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
    name = need(query, "name").strip()
    #: A body without a note leaves the note as it is: the composition may be
    #: set from the side of the thing, with no word about the class itself.
    note = str(body.get("note") or "").strip() if "note" in body else None
    entry_id = str(body.get("id") or "").strip()
    members = [str(item).strip() for item in (body.get("members") or []) if str(item).strip()]
    with session.lock:
        file, ladder = session.open()
        original = name if name in ladder.class_notes else None
        model.validate_class(name, members, ladder, original=original, entry_id=entry_id)
        #: A new class needs its name in every language; an existing one keeps
        #: what it has unless the form sent new names.
        names = (
            words.clean_names(body.get("names"), session.languages(), name)
            if original is None or body.get("names") is not None
            else None
        )
        class_id = entry_id if original is None else ladder.class_ids.get(name)

        expect = copy.deepcopy(file.doc)
        lines = list(file.lines)
        if original is None:
            declaration = {
                "name": name,
                "id": entry_id,
                **({"note": note} if note else {}),
            }
            expect["meta"].setdefault("classes", []).append(declaration)
            step = vault.RecipesFile(
                session.source, text="\n".join(lines), newline=file.newline
            )
            lines = step.insert_meta_entry("classes", declaration, ("name", "id", "note"))
        elif note is not None and note != (ladder.class_notes.get(name) or ""):
            declaration = {"name": name, "id": class_id, **({"note": note} if note else {})}
            for index, entry in enumerate(expect["meta"].get("classes") or []):
                if entry.get("name") == name:
                    expect["meta"]["classes"][index] = declaration
            step = vault.RecipesFile(
                session.source, text="\n".join(lines), newline=file.newline
            )
            lines = step.replace_meta_entry("classes", name, declaration, ("name", "id", "note"))

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

        writes = [
            store.prepare_doc(session.source, lines, expect, file.mtime, file.newline),
            *name_writes(session, CLASSES, class_id, names),
        ]
        store.commit(*writes)
        #: Said about the file as it now is, not as it was: the warning is about
        #: what the person will see on the picture after this write.
        warning = model.class_warning(name, session.open()[1])
    return {
        "class": name,
        "created": original is None,
        "warning": warning,
        "check": session.check(),
    }


def drop_class(session: Session, query: dict, _body: dict) -> dict:
    """Take a thing class out of the file: the declaration and every `class:`
    field naming it. The things themselves stay, of course."""
    name = need(query, "name")
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
        writes = [
            store.prepare_doc(session.source, lines, expect, file.mtime, file.newline),
            *name_writes(session, CLASSES, ladder.class_ids.get(name), None, gone=True),
        ]
        store.commit(*writes)
    warning = (
        f"класс «{name}» помечен как поведение движка — без него это поведение "
        "потеряет все свои вещи"
        if note.startswith("поведение")
        else None
    )
    return {"deleted": name, "warning": warning, "check": session.check()}


def membership(session: Session, query: dict, body: dict) -> dict:
    """The class of one thing -- set from the side of the thing (D-215).

    A person editing a pickaxe thinks "this is a pickaxe", not "add a member to
    the class". A thing has one class, so more than one is refused up front.
    """
    name = need(query, "name")
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
        store.save_doc(session.source, lines, expect, file.mtime, file.newline)
    return {"name": name, "classes": wanted, "check": session.check()}


# ---------------------------------------------------------- materials (D-215)


def material_create(session: Session, _query: dict, body: dict) -> dict:
    """A new material: one registry row is all a new raw thing needs (D-215)."""
    data = clean_material(body.get("data") or {})
    names = words.clean_names(body.get("names"), session.languages(), data["name"])
    with session.lock:
        file, ladder = session.open()
        model.validate_material(data, ladder)
        expect = copy.deepcopy(file.doc)
        expect["meta"].setdefault("materials", []).append(data)
        lines = file.insert_meta_entry("materials", data, vault.MATERIAL_KEY_ORDER)
        writes = [
            store.prepare_doc(session.source, lines, expect, file.mtime, file.newline),
            *name_writes(session, GOODS, data.get("id"), names),
        ]
        store.commit(*writes)
    return {"saved": data["name"], "check": session.check()}


def material_update(session: Session, query: dict, body: dict) -> dict:
    original = need(query, "name")
    data = clean_material(body.get("data") or {})
    if data.get("name") != original:
        raise vault.VaultError(
            "материал не переименовывается формой: на имя ссылаются рецепты, "
            "операции и мир. Переименование — отдельный осознанный шаг."
        )
    names = (
        words.clean_names(body.get("names"), session.languages(), original)
        if body.get("names") is not None
        else None
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
        writes = [
            store.prepare_doc(session.source, lines, expect, file.mtime, file.newline),
            *name_writes(
                session, GOODS, data.get("id"), names,
                was_id=ladder.materials[original].get("id"),
            ),
        ]
        store.commit(*writes)
    return {"saved": original, "check": session.check()}


def material_delete(session: Session, query: dict, _body: dict) -> dict:
    name = need(query, "name")
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
        writes = [
            store.prepare_doc(session.source, lines, expect, file.mtime, file.newline),
            *name_writes(session, GOODS, ladder.materials[name].get("id"), None, gone=True),
        ]
        store.commit(*writes)
    return {"deleted": name, "check": session.check()}


# ------------------------------------------------------------------ cleaning


def clean_recipe(data: dict) -> dict:
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
        if key in vault.BOOL_FIELDS:
            value = True
        out[key] = value
    if "name" not in out:
        raise vault.VaultError("у рецепта должно быть название")
    if "holds" in out and out["holds"] not in vault.HOLDS_VALUES:
        raise vault.VaultError(
            f"`holds` бывает только {', '.join(vault.HOLDS_VALUES)}, а не «{out['holds']}» (D-230)"
        )
    if "holds" in out and not out.get("store"):
        raise vault.VaultError("тара без объёма: `holds` требует «вмещает, кг» (D-230)")
    return out


def clean_material(data: dict) -> dict:
    out: dict[str, Any] = {}
    for key in vault.MATERIAL_KEY_ORDER:
        if key not in data:
            continue
        value = data[key]
        if value in (None, "", [], {}) or (key in vault.MATERIAL_BOOL_FIELDS and not value):
            continue
        if key in vault.MATERIAL_NUMBER_FIELDS:
            value = float(value)
            value = int(value) if float(value).is_integer() else value
        if key in vault.MATERIAL_BOOL_FIELDS:
            value = True
        if key == "forage":
            value = _clean_forage(value)
            if not value:
                continue
        out[key] = value
    if "name" not in out:
        raise vault.VaultError("у материала должно быть название")
    if "mass" not in out:
        #: Zero is a legal mass (energy weighs nothing) -- it survives the
        #: cleaning only if given explicitly as 0.
        if isinstance(data.get("mass"), (int, float)) and not isinstance(data.get("mass"), bool):
            out["mass"] = 0
        else:
            raise vault.VaultError("у материала должна быть масса (можно 0)")
    return out


def _clean_forage(value: Any) -> dict:
    """The gathering row (D-210, D-254): how often, how much, and where."""
    if not isinstance(value, dict):
        raise vault.VaultError("`forage` — это {finds, handful, place}")
    out: dict[str, Any] = {}
    for part in vault.FORAGE_KEYS:
        given = value.get(part)
        if given in (None, ""):
            continue
        if part == "place":
            out[part] = str(given).strip()
        else:
            number = float(given)
            out[part] = int(number) if number.is_integer() else number
    if "place" in out and not ("finds" in out or "handful" in out):
        raise vault.VaultError("`forage.place` без чисел: где лежит вещь, которую не находят?")
    return out
