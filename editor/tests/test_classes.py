# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Thing classes: declaring them, filling them, and taking them out (D-215).

A class is a declaration in `meta.classes` plus a `class:` field on each
member's own line. So an edit touches the declaration line and the members'
lines -- each with the same one-line surgery -- and nothing else in the file.

Nothing here names a recipe or a class of the real vault. The file is a living
document, and a test that spelled «Кирка» out would start failing the day the
vault renamed it. Every example is picked out of the file at run time, and what
is asserted is the rule.
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
    """A session editing the copy, reading derived numbers from the real vault.

    `--check` is the vault's own build, and running it here would say nothing
    about the editor while costing a subprocess per test.
    """
    made = server.Session(source.parent.parent)
    made.source = recipes
    monkeypatch.setattr(server, "_check", lambda _session: None)
    return made


def doc_of(path: Path) -> dict:
    return yaml.safe_load(path.read_bytes().decode("utf-8"))


def classes_of(path: Path) -> dict[str, list[str]]:
    """Class -> members, read back the way the build reads them."""
    doc = doc_of(path)
    members: dict[str, list[str]] = {
        entry["name"]: [] for entry in doc["meta"].get("classes") or []
    }
    for material in doc["meta"].get("materials") or []:
        if material.get("class"):
            members.setdefault(material["class"], []).append(material["name"])
    for level in doc.get("levels") or []:
        rows = list(level.get("recipes") or [])
        for section in level.get("sections") or []:
            rows.extend(section.get("recipes") or [])
        for recipe in rows:
            if recipe.get("class"):
                members.setdefault(recipe["class"], []).append(recipe["name"])
    return members


def changed_lines(before: str, after: str) -> int:
    from difflib import SequenceMatcher

    old = before.replace("\r\n", "\n").split("\n")
    new = after.replace("\r\n", "\n").split("\n")
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new).get_opcodes()
        if tag != "equal"
    )


def some_tools(session: server.Session, count: int = 2) -> list[str]:
    """Tools that belong to no class yet, taken out of the file itself."""
    _, ladder = session.open()
    tools = [
        name
        for name, recipe in ladder.recipes.items()
        if recipe.get("kind") == "tool" and not recipe.get("class")
    ]
    if len(tools) < count:
        pytest.skip("в файле не нашлось двух инструментов вне классов")
    return tools[:count]


def some_class(session: server.Session) -> tuple[str, list[str]]:
    _, ladder = session.open()
    filled = {klass: items for klass, items in ladder.classes.items() if items}
    if not filled:
        pytest.skip("в файле нет ни одного класса с составом")
    return next(iter(filled.items()))


# ------------------------------------------------------------------- making


def test_a_class_is_born_as_declaration_plus_members(
    session: server.Session, recipes: Path
):
    before = recipes.read_bytes().decode("utf-8")
    first, second = some_tools(session)

    server.put_class(session, {"name": ["Приспособа"]}, {"members": [first, second]})

    assert sorted(classes_of(recipes)["Приспособа"]) == sorted([first, second])
    #: One declaration line plus a `class:` field on each member's line.
    assert changed_lines(before, recipes.read_bytes().decode("utf-8")) == 1 + 2


def test_a_new_class_says_nobody_asks_for_it(session: server.Session):
    """The whole story of «Утвари»: a class hangs there until something requires it."""
    first, _ = some_tools(session)
    answer = server.put_class(session, {"name": ["Приспособа"]}, {"members": [first]})

    assert answer["created"] is True
    assert "никто не требует" in answer["warning"]


def test_a_class_named_after_a_thing_is_written_but_flagged(session: server.Session):
    """The file already does this with «Топором», so it is allowed -- and said aloud."""
    first, second = some_tools(session)
    answer = server.put_class(session, {"name": [first]}, {"members": [first, second]})

    assert answer["warning"] and "название вещи" in answer["warning"]


def test_an_empty_class_is_a_declaration(session: server.Session, recipes: Path):
    """A class may be declared ahead of its things (D-215): the declaration is
    what protects the `class:` fields from typos, so it comes first."""
    answer = server.put_class(session, {"name": ["Пустышка"]}, {"members": []})
    assert answer["created"] is True
    assert classes_of(recipes)["Пустышка"] == []


def test_a_member_nobody_makes_is_refused(session: server.Session):
    with pytest.raises(vault.VaultError, match="не рецепт"):
        server.put_class(session, {"name": ["Приспособа"]}, {"members": ["Вечный двигатель"]})


def test_a_class_is_not_closed_by_another_class(session: server.Session):
    """There are no nested classes: `options` resolves one level and one only."""
    name, _ = some_class(session)
    first, _ = some_tools(session)
    with pytest.raises(vault.VaultError, match="сам класс"):
        server.put_class(session, {"name": ["Приспособа"]}, {"members": [first, name]})


def test_one_thing_listed_twice_is_refused(session: server.Session):
    first, _ = some_tools(session)
    with pytest.raises(vault.VaultError, match="дважды"):
        server.put_class(session, {"name": ["Приспособа"]}, {"members": [first, first]})


def test_a_thing_has_one_class(session: server.Session):
    """A member of one class may not be pulled into another: one thing, one class."""
    name, members = some_class(session)
    with pytest.raises(vault.VaultError, match="один класс|уже в классе"):
        server.put_class(session, {"name": ["Приспособа"]}, {"members": [members[0]]})


# ------------------------------------------------------------------ changing


def test_the_composition_is_rewritten_in_place(session: server.Session, recipes: Path):
    name, members = some_class(session)
    before = recipes.read_bytes().decode("utf-8")

    server.put_class(session, {"name": [name]}, {"members": members[:1]})

    assert classes_of(recipes)[name] == members[:1]
    #: Only the lines of the members that left changed: their `class:` is gone.
    assert changed_lines(before, recipes.read_bytes().decode("utf-8")) == len(members) - 1


def test_a_class_is_taken_out(session: server.Session, recipes: Path):
    name, members = some_class(session)
    server.drop_class(session, {"name": [name]}, {})

    written = classes_of(recipes)
    assert name not in written
    for member in members:
        assert all(member not in items for items in written.values())


def test_taking_out_what_is_not_there(session: server.Session):
    with pytest.raises(vault.VaultError, match="в вольте нет"):
        server.drop_class(session, {"name": ["Приспособа"]}, {})


# ---------------------------------------------------- from the thing's side


def test_a_thing_joins_a_class(session: server.Session, recipes: Path):
    name, members = some_class(session)
    outsider = next(tool for tool in some_tools(session, 2) if tool not in members)

    server.membership(session, {"name": [outsider]}, {"classes": [name]})

    assert outsider in classes_of(recipes)[name]


def test_a_thing_leaves_a_class(session: server.Session, recipes: Path):
    _, ladder = session.open()
    name, members = next(
        ((klass, items) for klass, items in ladder.classes.items() if len(items) > 1),
        (None, None),
    )
    if name is None:
        pytest.skip("в файле нет класса с двумя вещами в составе")

    server.membership(session, {"name": [members[0]]}, {"classes": []})

    assert members[0] not in classes_of(recipes)[name]
    assert members[1] in classes_of(recipes)[name]


def test_two_classes_at_once_are_refused(session: server.Session):
    """A thing has one class (D-215): half a pickaxe half a bed does not exist."""
    first, _ = some_tools(session)
    server.put_class(session, {"name": ["Приспособа"]}, {"members": []})
    server.put_class(session, {"name": ["Другая"]}, {"members": []})
    with pytest.raises(vault.VaultError, match="один класс"):
        server.membership(
            session, {"name": [first]}, {"classes": ["Приспособа", "Другая"]}
        )


def test_joining_a_class_that_does_not_exist(session: server.Session):
    first, _ = some_tools(session)
    with pytest.raises(vault.VaultError, match="сперва заведите"):
        server.membership(session, {"name": [first]}, {"classes": ["Приспособа"]})


def test_nothing_to_change_writes_nothing(session: server.Session, recipes: Path):
    name, members = some_class(session)
    before = recipes.read_bytes()

    server.membership(session, {"name": [members[0]]}, {"classes": [name]})

    assert recipes.read_bytes() == before


# ------------------------------------------------------------------ the file


def test_the_comments_around_the_block_are_left_alone(
    session: server.Session, recipes: Path
):
    before = recipes.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")
    first, _ = some_tools(session)

    server.put_class(session, {"name": ["Приспособа"]}, {"members": [first]})

    after = recipes.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")
    assert [line for line in after if line.lstrip().startswith("#")] == [
        line for line in before if line.lstrip().startswith("#")
    ]


def test_the_ladder_reads_the_new_class_back(session: server.Session):
    """Written is not enough: the walk must see the class as a way to close a hole."""
    first, second = some_tools(session)
    server.put_class(session, {"name": ["Приспособа"]}, {"members": [first, second]})

    _, ladder = session.open()
    assert ladder.classes["Приспособа"] == sorted([first, second])
    assert ladder.options("Приспособа") == sorted([first, second])
    node = next(item for item in ladder.nodes() if item["name"] == "Приспособа")
    assert node["is_class"] and node["members"] == sorted([first, second])


def test_a_class_named_after_a_thing_still_shows_as_a_class(session: server.Session):
    """This is what hid «Топор»: the node keeps the thing's type, so the flag carries it."""
    first, second = some_tools(session)
    server.put_class(session, {"name": [first]}, {"members": [first, second]})

    _, ladder = session.open()
    node = next(item for item in ladder.nodes() if item["name"] == first)
    assert node["type"] == "recipe", "узел остаётся вещью — и это не должно прятать класс"
    assert node["is_class"] and node["members"] == sorted([first, second])


def test_renaming_a_thing_that_names_a_class_is_refused(session: server.Session):
    """A sweep would rename the class too, and engine behaviour binds to it."""
    _, ladder = session.open()
    shared = next(
        (name for name in ladder.class_notes if name in ladder.recipes), None
    )
    if shared is None:
        pytest.skip("в файле нет вещи, одноимённой классу")
    data = dict(ladder.recipes[shared])
    data.pop("level", None), data.pop("section", None)
    data["name"] = "Переименованная"
    with pytest.raises(vault.VaultError, match="имя класса"):
        server.update(
            session, {"name": [shared]}, {"data": data, "rename_refs": True}
        )


def test_validation_speaks_before_the_file_is_touched(
    session: server.Session, recipes: Path
):
    before = recipes.read_bytes()
    _, ladder = session.open()
    with pytest.raises(vault.VaultError):
        model.validate_class("", ["что угодно"], ladder)
    assert recipes.read_bytes() == before
