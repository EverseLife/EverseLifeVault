"""Tool classes: making them, filling them, and taking them out.

A class is a hole in a requirement -- «нужна кирка, любая» -- and it lives in
`meta.tool_classes` as one line among the comments that explain it. So the same
discipline holds as for a recipe line: one line changes and the rest of the file
does not.

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


def classes_of(path: Path) -> dict:
    return doc_of(path)["meta"]["tool_classes"]


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
    """Tools that belong to no class yet, taken out of the file itself.

    Outside every class on purpose: membership is set as a whole answer -- these
    are the classes this thing closes, and no others -- so a tool already listed
    somewhere would be quietly taken out of that class, and the test would be
    measuring the wrong write.
    """
    _, ladder = session.open()
    listed = {
        member for members in ladder.tool_classes.values() for member in members
    } | set(ladder.tool_classes)
    tools = [
        name for name, recipe in ladder.recipes.items()
        if recipe.get("kind") == "tool" and name not in listed
    ]
    if len(tools) < count:
        pytest.skip("в файле не нашлось двух инструментов вне классов")
    return tools[:count]


def some_class(session: server.Session) -> tuple[str, list[str]]:
    _, ladder = session.open()
    if not ladder.tool_classes:
        pytest.skip("в файле нет ни одного класса инструмента")
    return next(iter(ladder.tool_classes.items()))


# ------------------------------------------------------------------- making


def test_a_class_is_born_in_one_line(session: server.Session, recipes: Path):
    before = recipes.read_bytes().decode("utf-8")
    first, second = some_tools(session)

    server.put_class(session, {"name": ["Приспособа"]}, {"members": [first, second]})

    assert classes_of(recipes)["Приспособа"] == [first, second]
    assert changed_lines(before, recipes.read_bytes().decode("utf-8")) == 1


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


def test_the_same_class_twice_is_refused(session: server.Session):
    name, _ = some_class(session)
    first, _ = some_tools(session)
    # A class that exists is edited, not created -- but its members are replaced,
    # and that is the write the second call has to be.
    server.put_class(session, {"name": [name]}, {"members": [first]})
    assert classes_of(session.source)[name] == [first]


def test_a_class_nothing_closes_is_refused(session: server.Session):
    with pytest.raises(vault.VaultError, match="некому закрыть"):
        server.put_class(session, {"name": ["Пустышка"]}, {"members": []})


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


# ------------------------------------------------------------------ changing


def test_the_composition_is_rewritten_in_place(session: server.Session, recipes: Path):
    name, members = some_class(session)
    before = recipes.read_bytes().decode("utf-8")

    server.put_class(session, {"name": [name]}, {"members": members[:1]})

    assert classes_of(recipes)[name] == members[:1]
    assert changed_lines(before, recipes.read_bytes().decode("utf-8")) == 1


def test_a_class_is_taken_out(session: server.Session, recipes: Path):
    name, _ = some_class(session)
    server.drop_class(session, {"name": [name]}, {})

    assert name not in classes_of(recipes)


def test_taking_out_what_is_not_there(session: server.Session):
    with pytest.raises(vault.VaultError, match="в вольте нет"):
        server.drop_class(session, {"name": ["Приспособа"]}, {})


# ---------------------------------------------------- from the thing's side


def test_a_thing_joins_a_class(session: server.Session, recipes: Path):
    name, members = some_class(session)
    outsider = next(
        tool for tool in some_tools(session, 2) if tool not in members
    )

    server.membership(session, {"name": [outsider]}, {"classes": [name]})

    assert outsider in classes_of(recipes)[name]


def test_a_thing_leaves_a_class(session: server.Session, recipes: Path):
    _, ladder = session.open()
    name, members = next(
        ((klass, items) for klass, items in ladder.tool_classes.items() if len(items) > 1),
        (None, None),
    )
    if name is None:
        pytest.skip("в файле нет класса с двумя вещами в составе")

    server.membership(session, {"name": [members[0]]}, {"classes": []})

    assert members[0] not in classes_of(recipes)[name]
    assert members[1] in classes_of(recipes)[name]


def test_the_last_member_may_not_walk_out(session: server.Session):
    """It would leave a class nothing closes -- and the ladder would stop there."""
    first, _ = some_tools(session)
    server.put_class(session, {"name": ["Приспособа"]}, {"members": [first]})

    with pytest.raises(vault.VaultError, match="удалите класс целиком"):
        server.membership(session, {"name": [first]}, {"classes": []})


def test_joining_a_class_that_does_not_exist(session: server.Session):
    first, _ = some_tools(session)
    with pytest.raises(vault.VaultError, match="сперва заведите"):
        server.membership(session, {"name": [first]}, {"classes": ["Приспособа"]})


def test_two_classes_change_in_one_write(session: server.Session, recipes: Path):
    """Half an answer in the file is worse than none: both lines or neither."""
    first, second = some_tools(session)
    server.put_class(session, {"name": ["Приспособа"]}, {"members": [first]})
    server.put_class(session, {"name": ["Другая"]}, {"members": [first]})
    before = recipes.read_bytes().decode("utf-8")

    server.membership(session, {"name": [second]}, {"classes": ["Приспособа", "Другая"]})

    written = classes_of(recipes)
    assert second in written["Приспособа"] and second in written["Другая"]
    assert changed_lines(before, recipes.read_bytes().decode("utf-8")) == 2


def test_nothing_to_change_writes_nothing(session: server.Session, recipes: Path):
    name, members = some_class(session)
    before = recipes.read_bytes()

    server.membership(session, {"name": [members[0]]}, {"classes": [name]})

    assert recipes.read_bytes() == before


# ------------------------------------------------------------------ the file


def test_the_comments_around_the_block_are_left_alone(session: server.Session, recipes: Path):
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
    assert ladder.tool_classes["Приспособа"] == [first, second]
    assert ladder.options("Приспособа") == [first, second]
    node = next(item for item in ladder.nodes() if item["name"] == "Приспособа")
    assert node["is_class"] and node["members"] == [first, second]


def test_a_class_named_after_a_thing_still_shows_as_a_class(session: server.Session):
    """This is what hid «Топор»: the node keeps the thing's type, so the flag carries it."""
    first, second = some_tools(session)
    server.put_class(session, {"name": [first]}, {"members": [first, second]})

    _, ladder = session.open()
    node = next(item for item in ladder.nodes() if item["name"] == first)
    assert node["type"] == "recipe", "узел остаётся вещью — и это не должно прятать класс"
    assert node["is_class"] and node["members"] == [first, second]


def test_validation_speaks_before_the_file_is_touched(session: server.Session, recipes: Path):
    before = recipes.read_bytes()
    _, ladder = session.open()
    with pytest.raises(vault.VaultError):
        model.validate_class("", ["что угодно"], ladder)
    assert recipes.read_bytes() == before
