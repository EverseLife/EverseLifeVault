# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The handlers for `data/constants.yaml`: building types (D-218) and the numbers.

A building type is three maps of the constants file, a row of the small
dictionary that gives it its key and a name in every language (D-251): one
write here touches all of them, or none. Every other constant is one entry,
edited field by field.
"""

from __future__ import annotations

from typing import Any

import ladder as model
import localefile as words
import store
import vaultfile as vault
import yaml
from session import Session, name_writes, need, spoken_names

#: Where a building type's key and names live (D-251).
KINDS = words.BUILDING_KINDS


def buildings(session: Session) -> list[dict]:
    """The ladder of building types, or nothing if the file cannot say.

    A constants file the editor cannot read must not take the recipe window down
    with it: the tab shows the reason and the rest of the editor works on.
    """
    try:
        rows = session.open_constants().types()
        keys = {row.get("name"): row.get("id") for row in session.open_vocabulary().rows(KINDS)}
    except (vault.VaultError, OSError, yaml.YAMLError) as error:
        return [{"error": str(error)}]
    for row in rows:
        row["id"] = keys.get(row["kind"])
        row["names"] = spoken_names(session, KINDS, row["id"])
    return rows


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


def _types_write(session: Session, rows: list[dict]) -> store.Write:
    file = session.open_constants()
    expect = file.set_types(rows)
    return store.prepare_doc(session.constants, file.lines, expect, file.mtime, file.newline)


def _kind_write(
    session: Session, kind: str, entry_id: str, *, original: str | None = None
) -> store.Write:
    """The small dictionary with this type's key (D-251)."""
    file = session.open_vocabulary()
    row = {"name": kind, "id": entry_id}
    lines = file.put(KINDS, row, original=original)
    return store.prepare_doc(
        session.vocabulary, lines, file.expect(KINDS, row, original), file.mtime, file.newline
    )


def _kind_id(session: Session, body: dict, kind: str, *, original: str | None) -> str:
    """The key of a building type: sent by the form, or the one it already has."""
    rows = session.open_vocabulary().rows(KINDS)
    entry_id = str(body.get("id") or "").strip()
    if not entry_id and original is not None:
        entry_id = str(
            next((row.get("id") for row in rows if row.get("name") == original), "") or ""
        )
    taken = {str(row["id"]): row["name"] for row in rows if row.get("id")}
    if original is not None:
        taken = {key: owner for key, owner in taken.items() if owner != original}
    model._check_id(entry_id, kind, taken)  # noqa: SLF001 -- one module family
    return entry_id


def building_create(session: Session, _query: dict, body: dict) -> dict:
    """A new building type: one row, and all three maps get it at once (D-218)."""
    with session.lock:
        _, ladder = session.open()
        row = _clean_building(body.get("data") or {}, ladder)
        entry_id = _kind_id(session, body, row["kind"], original=None)
        names = words.clean_names(body.get("names"), session.languages(), row["kind"])
        file = session.open_constants()
        rows = file.types()
        if any(existing["kind"] == row["kind"] for existing in rows):
            raise vault.VaultError(f"тип «{row['kind']}» уже есть")
        #: Appended at the end: the ladder runs from the cheapest upwards and
        #: the engine takes the first of it as the default (`estate.kinds`), so
        #: a new type must not silently become what unnamed houses are built of.
        store.commit(
            _types_write(session, [*rows, row]),
            _kind_write(session, row["kind"], entry_id),
            *name_writes(session, KINDS, entry_id, names),
        )
    return {"saved": row["kind"], "check": session.check()}


def building_update(session: Session, query: dict, body: dict) -> dict:
    original = need(query, "name")
    with session.lock:
        _, ladder = session.open()
        row = _clean_building(body.get("data") or {}, ladder)
        file = session.open_constants()
        rows = file.types()
        if not any(existing["kind"] == original for existing in rows):
            raise vault.VaultError(f"типа «{original}» нет в файле")
        if row["kind"] != original and any(x["kind"] == row["kind"] for x in rows):
            raise vault.VaultError(f"тип «{row['kind']}» уже есть")
        vocabulary = session.open_vocabulary()
        was = vocabulary.row(KINDS, original) or {}
        entry_id = _kind_id(session, body, row["kind"], original=original)
        names = (
            words.clean_names(body.get("names"), session.languages(), row["kind"])
            if body.get("names") is not None
            else None
        )
        #: Renaming is allowed and is a real edit: the type's name is written on
        #: every house already standing, so the engine's migration has to follow.
        #: The tool says so rather than pretending the rename is free.
        writes = [
            _types_write(
                session,
                [row if existing["kind"] == original else existing for existing in rows],
            ),
        ]
        if was.get("name") != row["kind"] or was.get("id") != entry_id:
            writes.append(
                _kind_write(session, row["kind"], entry_id, original=original if was else None)
            )
        writes += name_writes(session, KINDS, entry_id, names, was_id=was.get("id"))
        store.commit(*writes)
    return {
        "saved": row["kind"],
        "renamed": None if row["kind"] == original else original,
        "check": session.check(),
    }


def building_delete(session: Session, query: dict, _body: dict) -> dict:
    name = need(query, "name")
    with session.lock:
        file = session.open_constants()
        rows = file.types()
        if not any(existing["kind"] == name for existing in rows):
            raise vault.VaultError(f"типа «{name}» нет в файле")
        if len(rows) == 1:
            raise vault.VaultError(
                "это последний тип: строить дома было бы не из чего"
            )
        writes = [_types_write(session, [row for row in rows if row["kind"] != name])]
        vocabulary = session.open_vocabulary()
        was = vocabulary.row(KINDS, name)
        if was is not None:
            writes.append(
                store.prepare_doc(
                    session.vocabulary, vocabulary.drop(KINDS, name),
                    vocabulary.expect(KINDS, None, name), vocabulary.mtime, vocabulary.newline,
                )
            )
            writes += name_writes(session, KINDS, was.get("id"), None, gone=True)
        store.commit(*writes)
    return {"deleted": name, "check": session.check()}


# ------------------------------------------------------------ the numbers


def constants(session: Session, _query: dict, _body: dict) -> dict:
    """The whole registry, group by group, with the comment above each number."""
    file = session.open_constants()
    return {"source": str(session.constants), "groups": file.registry()}


def _entry_fields(body: dict) -> dict:
    """The fields the form sent, with a value written as YAML parsed into one.

    A table or a list is easier to type as the file writes it than as a form of
    rows, so the form may send `value_yaml`; a number comes as a number.
    """
    data = dict(body.get("data") or {})
    text = data.pop("value_yaml", None)
    if isinstance(text, str) and text.strip():
        try:
            data["value"] = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise vault.VaultError(f"значение не читается как YAML: {error}") from error
    return data


def constant_create(session: Session, _query: dict, body: dict) -> dict:
    group = str(body.get("group") or "").strip()
    if not group:
        raise vault.VaultError("не выбрана группа констант")
    with session.lock:
        file = session.open_constants()
        data = _entry_fields(body)
        lines, expect = file.add_entry(group, data, after=body.get("after") or None)
        store.save_doc(session.constants, lines, expect, file.mtime, file.newline)
    return {"saved": data.get("key"), "check": session.check()}


def constant_update(session: Session, query: dict, body: dict) -> dict:
    key = need(query, "key")
    with session.lock:
        file = session.open_constants()
        data = _entry_fields(body)
        lines, expect = file.set_entry(key, data)
        store.save_doc(session.constants, lines, expect, file.mtime, file.newline)
    return {
        "saved": data.get("key") or key,
        "renamed": None if (data.get("key") or key) == key else key,
        "check": session.check(),
    }


def constant_delete(session: Session, query: dict, body: dict) -> dict:
    key = need(query, "key")
    with session.lock:
        file = session.open_constants()
        lines, expect = file.drop_entry(key, with_comment=bool(body.get("with_comment", True)))
        store.save_doc(session.constants, lines, expect, file.mtime, file.newline)
    return {"deleted": key, "check": session.check()}


ROUTES = {
    ("POST", "/api/building"): building_create,
    ("PUT", "/api/building"): building_update,
    ("DELETE", "/api/building"): building_delete,
    ("GET", "/api/constants"): constants,
    ("POST", "/api/constant"): constant_create,
    ("PUT", "/api/constant"): constant_update,
    ("DELETE", "/api/constant"): constant_delete,
}
