"""How a thing is measured: whole or fractional, and by what word.

Since D-215 the fraction sign is `bulk: true` on the thing's own line -- a
recipe or a material row -- and only `units` stays a `meta` map. The same rule
holds as everywhere: touch one line, leave the rest of the file alone.
"""

from __future__ import annotations

import copy
from difflib import SequenceMatcher
from pathlib import Path

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


def written(path: Path, lines: list[str], expect: dict) -> dict:
    file = vault.RecipesFile(path)
    vault.save_doc(path, lines, expect, file.mtime, file.newline)
    return doc_of(path)


def changed_lines(before: str, after: str) -> int:
    """Lines added plus lines removed.

    Positional comparison would not do: one inserted line shifts everything
    below it and would count as hundreds.
    """
    old = before.replace("\r\n", "\n").split("\n")
    new = after.replace("\r\n", "\n").split("\n")
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new).get_opcodes()
        if tag != "equal"
    )


def material_named(path: Path, name: str) -> dict:
    return next(
        row for row in doc_of(path)["meta"]["materials"] if row["name"] == name
    )


# ---------------------------------------------------------------------- bulk


def test_a_recipe_becomes_fractional_by_one_line(session: server.Session, recipes: Path):
    before = recipes.read_bytes().decode("utf-8")
    _, ladder = session.open()
    name = next(
        name for name, r in ladder.recipes.items() if not r.get("bulk")
    )

    server.measure(session, {"name": [name]}, {"bulk": True})

    _, after = session.open()
    assert name in after.bulk
    assert changed_lines(before, recipes.read_bytes().decode("utf-8")) == 1


def test_a_material_becomes_whole_again(session: server.Session, recipes: Path):
    _, ladder = session.open()
    name = next(
        name for name, m in ladder.materials.items() if m.get("bulk")
    )

    server.measure(session, {"name": [name]}, {"bulk": False})

    _, after = session.open()
    assert name not in after.bulk
    assert "bulk" not in material_named(recipes, name)


def test_measuring_what_is_already_so_still_writes_the_same_line(
    session: server.Session, recipes: Path
):
    """Idempotent in meaning: the document reads the same afterwards."""
    _, ladder = session.open()
    name = next(name for name, m in ladder.materials.items() if m.get("bulk"))
    before = doc_of(recipes)

    server.measure(session, {"name": [name]}, {"bulk": True})

    assert doc_of(recipes) == before


def test_an_emptied_list_stays_a_list(tmp_path: Path):
    """`bulk:` with nothing under it reads as null, not as zero things.

    The generic MetaBlock machinery is still used for `units`; the guard lives
    on, so it stays proven.
    """
    path = tmp_path / "recipes.yaml"
    path.write_text("meta:\n  bulk:\n    - Камень\nlevels: []\n", encoding="utf-8")
    file = vault.RecipesFile(path)
    lines = vault.MetaBlock(file, "bulk").toggle("Камень", False)
    assert yaml.safe_load("\n".join(lines))["meta"]["bulk"] == []


# --------------------------------------------------------------------- units


def test_a_unit_is_written_and_taken_back(recipes: Path):
    file = vault.RecipesFile(recipes)
    name = file.recipes()[0]["name"]

    expect = copy.deepcopy(file.doc)
    expect["meta"]["units"] = {**(expect["meta"].get("units") or {}), name: "м"}
    doc = written(recipes, vault.MetaBlock(file, "units").put(name, "м"), expect)
    assert doc["meta"]["units"][name] == "м"

    file = vault.RecipesFile(recipes)
    expect = copy.deepcopy(file.doc)
    expect["meta"]["units"] = {}
    doc = written(recipes, vault.MetaBlock(file, "units").put(name, None), expect)
    assert doc["meta"]["units"] == {}


def test_a_unit_is_replaced_not_doubled(recipes: Path):
    file = vault.RecipesFile(recipes)
    name = file.recipes()[0]["name"]
    lines = vault.MetaBlock(file, "units").put(name, "м")

    file = vault.RecipesFile(recipes, text="\n".join(lines))
    lines = vault.MetaBlock(file, "units").put(name, "л")
    doc = yaml.safe_load("\n".join(lines))
    assert doc["meta"]["units"] == {name: "л"}
    block = vault.MetaBlock(vault.RecipesFile(recipes, text="\n".join(lines)), "units")
    assert sum(1 for line in lines[block.start : block.end + 1] if name in line) == 1


def test_a_unit_with_a_colon_is_quoted_not_broken(recipes: Path):
    file = vault.RecipesFile(recipes)
    name = file.recipes()[0]["name"]
    lines = vault.MetaBlock(file, "units").put(name, "шт: пара")
    assert yaml.safe_load("\n".join(lines))["meta"]["units"][name] == "шт: пара"


# ---------------------------------------------------------------------- mass


def test_the_mass_of_a_material_is_writable(session: server.Session, recipes: Path):
    """Material mass is the floor of the whole system: everything made is capped by it."""
    _, ladder = session.open()
    name = ladder.raw[0]

    server.measure(session, {"name": [name]}, {"bulk": name in ladder.bulk, "mass": 2.5})

    assert material_named(recipes, name)["mass"] == 2.5


def test_a_weightless_thing_keeps_its_zero(session: server.Session, recipes: Path):
    """Energy weighs nothing, and that is a statement, not a missing number."""
    _, ladder = session.open()
    name = next(name for name, m in ladder.materials.items() if m.get("mass") == 0)

    server.measure(session, {"name": [name]}, {"bulk": name in ladder.bulk, "mass": 0})

    assert material_named(recipes, name)["mass"] == 0


def test_a_recipe_may_be_measured_but_not_weighed_here(session: server.Session):
    """Unit and fractionality belong to any thing; mass belongs to the recipe line."""
    _, ladder = session.open()
    name = next(iter(ladder.recipes))
    with pytest.raises(vault.VaultError, match="рецепт"):
        server.measure(session, {"name": [name]}, {"bulk": False, "mass": 3})


def test_a_negative_mass_is_refused(session: server.Session):
    _, ladder = session.open()
    name = ladder.raw[0]
    with pytest.raises(vault.VaultError, match="не меньше нуля"):
        server.measure(
            session, {"name": [name]}, {"bulk": name in ladder.bulk, "mass": -1}
        )


# ------------------------------------------------------------------ guarding


def test_a_wrong_expectation_stops_the_write(recipes: Path):
    """The whole document is compared, so a slip in line arithmetic cannot pass."""
    file = vault.RecipesFile(recipes)
    name = file.recipes()[0]["name"]
    lines = vault.MetaBlock(file, "units").put(name, "м")
    with pytest.raises(vault.VaultError, match="не так, как задумано"):
        vault.save_doc(recipes, lines, file.doc, file.mtime, file.newline)


def test_the_rest_of_the_file_is_left_alone(recipes: Path):
    """Comments around the block explain the design; a unit must not disturb them."""
    before = recipes.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")
    file = vault.RecipesFile(recipes)
    name = file.recipes()[0]["name"]
    lines = vault.MetaBlock(file, "units").put(name, "м")
    comments = [line for line in lines if line.lstrip().startswith("#")]
    assert comments == [line for line in before if line.lstrip().startswith("#")]
