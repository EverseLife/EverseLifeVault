# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""A thing is named in every language, and the editor writes the names (D-251).

The build refuses a vault where a thing has no name in a language of the game,
and refuses one where a name is left over from a thing that is gone. So a
create writes `locales/*.yaml` together with `recipes.yaml`, a delete takes
the name out, and undo takes both files back at once -- half an edit would be
exactly the state the build refuses.
"""

from __future__ import annotations

from pathlib import Path

import localefile as words
import pytest
import server
import store
import vaultfile as vault
import yaml

DIAMOND = {
    "name": "Алмаз", "id": "diamond", "class": "Ископаемое", "mass": 0.5, "bulk": True, "rate": 2,
}


def doc_of(path: Path) -> dict:
    return yaml.safe_load(path.read_bytes().decode("utf-8"))


def english(session: server.Session) -> Path:
    return session.locales_dir / "en.yaml"


# ---------------------------------------------------------------- the file


def test_a_name_is_put_in_alphabetical_order(locales_dir: Path):
    file = words.LocaleFile(locales_dir / "en.yaml")
    before = file.lines
    lines = file.put("goods", "diamond", "Diamond")
    assert len(lines) == len(before) + 1
    added = lines.index("  diamond: Diamond")
    #: Between its neighbours in the alphabet: a name dropped at the end of
    #: the block would be found by nobody reading it.
    above = next(line for line in reversed(lines[:added]) if line.startswith("  "))
    below = next(line for line in lines[added + 1 :] if line.startswith("  "))
    assert above.strip().split(":")[0] < "diamond" < below.strip().split(":")[0]
    assert yaml.safe_load("\n".join(lines))["goods"]["diamond"] == "Diamond"


def test_a_name_is_replaced_not_doubled(locales_dir: Path):
    file = words.LocaleFile(locales_dir / "en.yaml")
    lines = file.put("goods", "diamond", "Diamond")
    again = words.LocaleFile(locales_dir / "en.yaml", text="\n".join(lines))
    lines = again.put("goods", "diamond", "Gem")
    assert sum(1 for line in lines if line.startswith("  diamond:")) == 1
    assert yaml.safe_load("\n".join(lines))["goods"]["diamond"] == "Gem"


def test_a_name_is_dropped_and_the_rest_left_alone(locales_dir: Path):
    file = words.LocaleFile(locales_dir / "en.yaml")
    entry_id = next(iter(file.doc["goods"]))
    lines = file.drop("goods", entry_id)
    assert len(lines) == len(file.lines) - 1
    assert entry_id not in yaml.safe_load("\n".join(lines))["goods"]
    comments = [line for line in lines if line.lstrip().startswith("#")]
    assert comments == [line for line in file.lines if line.lstrip().startswith("#")]


def test_an_empty_domain_reads_as_empty(tmp_path: Path):
    path = tmp_path / "en.yaml"
    path.write_text("goods:\n  axe: Axe\nclasses: {}\n", encoding="utf-8")
    file = words.LocaleFile(path)
    lines = file.drop("goods", "axe")
    assert yaml.safe_load("\n".join(lines))["goods"] == {}
    lines = file.put("classes", "pickaxe", "Pickaxe")
    assert yaml.safe_load("\n".join(lines))["classes"] == {"pickaxe": "Pickaxe"}


def test_a_name_needing_quotes_is_quoted(locales_dir: Path):
    file = words.LocaleFile(locales_dir / "en.yaml")
    lines = file.put("goods", "odd", "Salt: coarse, #1")
    assert yaml.safe_load("\n".join(lines))["goods"]["odd"] == "Salt: coarse, #1"


def test_a_missing_language_is_refused():
    with pytest.raises(vault.VaultError, match="языке «en»"):
        words.clean_names({"en": " "}, ["en"], "Алмаз")
    assert words.clean_names({"en": " Diamond "}, ["en"], "Алмаз") == {"en": "Diamond"}


# -------------------------------------------------------- small dictionaries


def test_a_dictionary_row_is_put_and_dropped(vocabulary: Path):
    file = words.VocabularyFile(vocabulary)
    lines = file.put(words.BUILDING_KINDS, {"name": "кирпичный", "id": "brick"})
    rows = yaml.safe_load("\n".join(lines))[words.BUILDING_KINDS]
    assert rows[-1] == {"name": "кирпичный", "id": "brick"}
    assert len(lines) == len(file.lines) + 1

    again = words.VocabularyFile(vocabulary, text="\n".join(lines))
    lines = again.put(words.BUILDING_KINDS, {"name": "кирпич", "id": "brick"}, original="кирпичный")
    rows = yaml.safe_load("\n".join(lines))[words.BUILDING_KINDS]
    assert {"name": "кирпич", "id": "brick"} in rows
    assert all(row["name"] != "кирпичный" for row in rows)

    once_more = words.VocabularyFile(vocabulary, text="\n".join(lines))
    lines = once_more.drop(words.BUILDING_KINDS, "кирпич")
    rows = yaml.safe_load("\n".join(lines))[words.BUILDING_KINDS]
    assert all(row["id"] != "brick" for row in rows)


# --------------------------------------------------------------- the editor


def test_a_new_material_is_named_in_english(session: server.Session):
    server.material_create(session, {}, {"data": dict(DIAMOND), "names": {"en": "Diamond"}})
    assert doc_of(english(session))["goods"]["diamond"] == "Diamond"


def test_a_material_without_an_english_name_is_refused(session: server.Session, recipes: Path):
    before = recipes.read_bytes()
    with pytest.raises(vault.VaultError, match="языке"):
        server.material_create(session, {}, {"data": dict(DIAMOND)})
    assert recipes.read_bytes() == before


def test_a_deleted_material_loses_its_name(session: server.Session):
    server.material_create(session, {}, {"data": dict(DIAMOND), "names": {"en": "Diamond"}})
    server.material_delete(session, {"name": ["Алмаз"]}, {})
    assert "diamond" not in doc_of(english(session))["goods"]


def test_a_changed_key_moves_the_name(session: server.Session):
    server.material_create(session, {}, {"data": dict(DIAMOND), "names": {"en": "Diamond"}})
    server.material_update(
        session, {"name": ["Алмаз"]}, {"data": {**DIAMOND, "id": "gem"}, "names": {"en": "Gem"}}
    )
    goods = doc_of(english(session))["goods"]
    assert "diamond" not in goods and goods["gem"] == "Gem"


def test_a_new_recipe_is_named_and_undone_whole(session: server.Session, recipes: Path):
    _, ladder = session.open()
    level = next(lvl for lvl in ladder.file.levels() if lvl["plain"])
    data = {
        "name": "Пробник", "id": "sampler", "kind": "material",
        "inputs": [ladder.raw[0]], "station": "Руками",
    }
    recipes_before = recipes.read_bytes()
    english_before = english(session).read_bytes()

    server.create(session, {}, {"data": data, "level": level["id"], "names": {"en": "Sampler"}})
    assert doc_of(english(session))["goods"]["sampler"] == "Sampler"
    assert "Пробник" in session.open()[1].recipes

    #: One edit, two files: undo takes both back, or the build would refuse
    #: the half that stayed.
    restored = store.undo(session.source)
    assert len(restored) == 2
    assert recipes.read_bytes() == recipes_before
    assert english(session).read_bytes() == english_before


def test_a_recipe_key_change_moves_the_name(session: server.Session):
    _, ladder = session.open()
    name = next(name for name, recipe in ladder.recipes.items() if recipe.get("id"))
    data = {k: v for k, v in ladder.recipes[name].items() if k not in ("level", "section")}
    old_id = data["id"]
    body = {"data": {**data, "id": old_id + "_moved"}, "names": {"en": "Moved"}}
    server.update(session, {"name": [name]}, body)
    goods = doc_of(english(session))["goods"]
    assert old_id not in goods and goods[old_id + "_moved"] == "Moved"


def test_a_header_with_a_comment_is_not_an_inline_value(tmp_path: Path):
    path = tmp_path / "en.yaml"
    path.write_text("goods:  # the words\n  axe: Axe\n", encoding="utf-8")
    lines = words.LocaleFile(path).put("goods", "bed", "Bed")
    assert lines[0] == "goods:  # the words"
    assert yaml.safe_load("\n".join(lines))["goods"] == {"axe": "Axe", "bed": "Bed"}


def test_two_edits_never_share_a_stamp(session: server.Session, backups_elsewhere: Path):
    """The stamp groups the files of one edit; a clock that has not moved must not merge two."""
    stamps = {store.new_stamp() for _ in range(5)}
    assert len(stamps) == 5
    for label in ("locales__pt-BR", "recipes"):
        backup = backups_elsewhere / f"{label}-20260902-120000-001-01.yaml"
        assert store._split(backup) == (label, "20260902-120000-001-01")


def test_a_deleted_recipe_loses_its_name(session: server.Session):
    _, ladder = session.open()
    name = next(
        name for name, recipe in ladder.recipes.items()
        if recipe.get("id") and not any(
            name in (other.get("inputs") or []) for other in ladder.recipes.values()
        )
    )
    entry_id = ladder.recipes[name]["id"]
    assert entry_id in doc_of(english(session))["goods"]
    server.delete(session, {"name": [name]}, {})
    assert entry_id not in doc_of(english(session))["goods"]


def test_a_new_class_is_named(session: server.Session):
    _, ladder = session.open()
    server.put_class(
        session, {"name": ["Приспособа"]},
        {"id": "gadget", "members": [], "names": {"en": "Gadget"}},
    )
    assert doc_of(english(session))["classes"]["gadget"] == "Gadget"
    server.drop_class(session, {"name": ["Приспособа"]}, {})
    assert "gadget" not in doc_of(english(session))["classes"]


def test_the_form_is_told_the_names(session: server.Session):
    _, ladder = session.open()
    name = next(iter(ladder.recipes))
    payload = server.recipe(session, {"name": [name]}, {})
    assert payload["names"].get("en"), "форма обязана знать английское имя вещи"
    state = server.state(session, {}, {})
    assert state["languages"] == ["en"]
    assert state["locales"]["en"]["goods"]


# ------------------------------------------------------------- buildings


def test_a_building_type_gets_its_key_and_name(session: server.Session, vocabulary: Path):
    brick = {"kind": "кирпичный", "per_m2": {"Кирпич": 30}, "growth": 1.4, "decay": 0.25}
    server.building_create(session, {}, {"data": brick, "id": "brick", "names": {"en": "brick"}})
    rows = doc_of(vocabulary)[words.BUILDING_KINDS]
    assert {"name": "кирпичный", "id": "brick"} in rows
    assert doc_of(english(session))[words.BUILDING_KINDS]["brick"] == "brick"

    server.building_update(
        session, {"name": ["кирпичный"]}, {"data": {**brick, "kind": "кирпич"}}
    )
    rows = doc_of(vocabulary)[words.BUILDING_KINDS]
    assert {"name": "кирпич", "id": "brick"} in rows and all(r["name"] != "кирпичный" for r in rows)

    server.building_delete(session, {"name": ["кирпич"]}, {})
    assert all(row["id"] != "brick" for row in doc_of(vocabulary)[words.BUILDING_KINDS])
    assert "brick" not in doc_of(english(session))[words.BUILDING_KINDS]


def test_a_building_type_without_a_key_is_refused(session: server.Session, constants: Path):
    before = constants.read_bytes()
    brick = {"kind": "кирпичный", "per_m2": {"Кирпич": 30}, "growth": 1.4, "decay": 0.25}
    with pytest.raises(vault.VaultError, match="id"):
        server.building_create(session, {}, {"data": brick, "names": {"en": "brick"}})
    assert constants.read_bytes() == before
