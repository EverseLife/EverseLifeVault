# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The material registry (D-215): one row is all a new raw thing needs.

The point of the whole redesign is checked here: adding «Алмаз» is a single
write, and the build picks it up as a mineral without any other edit.
"""

from __future__ import annotations

from pathlib import Path

import ladder as model
import pytest
import server
import vaultfile as vault
import yaml


@pytest.fixture
def session(recipes: Path, source: Path, monkeypatch) -> server.Session:
    made = server.Session(source.parent.parent)
    made.source = recipes
    monkeypatch.setattr(server, "_check", lambda _session: None)
    return made


def doc_of(path: Path) -> dict:
    return yaml.safe_load(path.read_bytes().decode("utf-8"))


def rows_of(path: Path) -> list[dict]:
    return list(doc_of(path)["meta"]["materials"])


DIAMOND = {
    "name": "Алмаз",
    "id": "diamond",
    "class": "Ископаемое",
    "mass": 0.5,
    "bulk": True,
    "rate": 2,
}


def test_a_new_mineral_is_one_row(session: server.Session, recipes: Path):
    """«Алмаз» class «Ископаемое»: after one write it is a member of the class,
    and the expanded «Добыча» of the ladder already gives it."""
    server.material_create(session, {}, {"data": dict(DIAMOND)})

    row = next(r for r in rows_of(recipes) if r["name"] == "Алмаз")
    assert row == DIAMOND

    _, ladder = session.open()
    assert "Алмаз" in ladder.classes["Ископаемое"]
    assert "Алмаз" in ladder.raw
    assert "Алмаз" in ladder.bulk
    digging = next(op for op in ladder.operations if op.get("gives_class"))
    assert "Алмаз" in digging["gives"]


def test_the_registry_row_lands_after_the_last_one(session: server.Session, recipes: Path):
    before = recipes.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")
    server.material_create(session, {}, {"data": dict(DIAMOND)})
    after = recipes.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")
    added = [line for line in after if line not in before and "Алмаз" in line]
    assert len(added) == 1, "материал — одна строка файла"


def test_a_mineral_without_a_rate_is_refused(session: server.Session):
    """No pace -- exploration never finds the vein: the refusal says so up front."""
    poor = {k: v for k, v in DIAMOND.items() if k != "rate"}
    with pytest.raises(vault.VaultError, match="rate"):
        server.material_create(session, {}, {"data": poor})


def test_an_unknown_class_is_refused(session: server.Session):
    wrong = {**DIAMOND, "class": "Ископаемые"}
    with pytest.raises(vault.VaultError, match="не объявлен"):
        server.material_create(session, {}, {"data": wrong})


def test_a_duplicate_material_is_refused(session: server.Session):
    _, ladder = session.open()
    taken = next(iter(ladder.materials))
    with pytest.raises(vault.VaultError, match="уже есть"):
        server.material_create(session, {}, {"data": {"name": taken, "mass": 1}})


def test_a_material_is_edited_in_place(session: server.Session, recipes: Path):
    _, ladder = session.open()
    name = ladder.raw[0]
    data = dict(ladder.materials[name])
    data["mass"] = 9.5

    server.material_update(session, {"name": [name]}, {"data": data})

    row = next(r for r in rows_of(recipes) if r["name"] == name)
    assert row["mass"] == 9.5


def test_renaming_by_form_is_refused(session: server.Session):
    _, ladder = session.open()
    name = ladder.raw[0]
    data = {**ladder.materials[name], "name": "Иначе"}
    with pytest.raises(vault.VaultError, match="не переименовывается"):
        server.material_update(session, {"name": [name]}, {"data": data})


def test_a_used_material_is_not_deleted(session: server.Session):
    _, ladder = session.open()
    used = next(
        name
        for name in ladder.materials
        if model.references(name, ladder)["inputs"]
    )
    with pytest.raises(vault.VaultError, match="используется"):
        server.material_delete(session, {"name": [used]}, {})


def test_an_unused_material_is_deleted(session: server.Session, recipes: Path):
    server.material_create(session, {}, {"data": dict(DIAMOND)})
    server.material_delete(session, {"name": ["Алмаз"]}, {})
    assert all(row["name"] != "Алмаз" for row in rows_of(recipes))


def test_forage_makes_the_thing_findable(session: server.Session):
    """A `forage` pair on the row is what puts the thing on the surface (D-210)."""
    data = {**DIAMOND, "forage": {"finds": 1, "handful": 1}}
    server.material_create(session, {}, {"data": data})
    _, ladder = session.open()
    assert ladder.materials["Алмаз"]["forage"] == {"finds": 1, "handful": 1}

    hollow = {**DIAMOND, "name": "Пустышка", "forage": {"finds": 1, "handful": 0}}
    with pytest.raises(vault.VaultError, match="handful"):
        server.material_create(session, {}, {"data": hollow})
