"""Building types (D-218): four maps that must agree, edited as one row.

The point of the whole tab is checked here. A type is a composition, a price of
the next floor, a rate of decay and a cost of upkeep, and those live in four
different maps of `data/constants.yaml`. Editing them by hand means keeping four
lists in step; forget one and the engine finds a house it cannot price or age.
Here one write touches all four, or none of them.
"""

from __future__ import annotations

from pathlib import Path

import constantsfile as consts
import pytest
import server
import vaultfile as vault
import yaml


@pytest.fixture
def session(recipes: Path, constants: Path, source: Path, monkeypatch) -> server.Session:
    made = server.Session(source.parent.parent)
    made.source = recipes
    made.constants = constants
    monkeypatch.setattr(server, "_check", lambda _session: None)
    return made


def doc_of(path: Path) -> dict:
    return yaml.safe_load(path.read_bytes().decode("utf-8"))


def maps_of(path: Path) -> dict[str, dict]:
    """The four building maps as the file reads them."""
    found: dict[str, dict] = {}
    for group in doc_of(path)["groups"]:
        for entry in group["constants"]:
            if entry.get("key") in consts.BUILDING_KEYS:
                found[entry["key"]] = entry.get("value")
    return found


BRICK = {
    "kind": "кирпичный",
    "per_m2": {"Кирпич": 30, "Раствор": 6},
    "growth": 1.4,
    "decay": 0.25,
    "upkeep": 1.1,
}


# ------------------------------------------------------------------- reading


def test_the_ladder_reads_as_rows(constants: Path):
    """Every type comes back whole: what it is built of and all three numbers."""
    rows = consts.ConstantsFile(constants).types()
    assert rows, "в вольте должны быть типы зданий"
    for row in rows:
        assert row["per_m2"], f"у «{row['kind']}» пустой состав"
        assert row["growth"] and row["decay"] is not None and row["upkeep"] is not None

    #: The order is the file's own and it means something: cheapest first, and
    #: the engine takes the first of it as the default for an unnamed house.
    assert rows[0]["kind"] == "деревянный"


# ------------------------------------------------------------------- writing


def test_a_new_type_lands_in_all_four_maps(session: server.Session, constants: Path):
    server.building_create(session, {}, {"data": BRICK})

    maps = maps_of(constants)
    assert maps[consts.COMPOSITION]["кирпичный"] == {"Кирпич": 30, "Раствор": 6}
    assert maps[consts.GROWTH]["кирпичный"] == 1.4
    assert maps[consts.DECAY]["кирпичный"] == 0.25
    assert maps[consts.UPKEEP]["кирпичный"] == 1.1

    #: The same set of names in every map is exactly what the build checks, and
    #: it must hold the moment the write returns -- not after a later fix-up.
    names = [set(maps[key]) for key in consts.BUILDING_KEYS]
    assert all(other == names[0] for other in names[1:])


def test_the_new_type_goes_last(session: server.Session, constants: Path):
    """The ladder's head is the default for an unnamed house (`estate.kinds`).

    A type appended at the front would silently become what every house without
    a named type is built of -- and the houses already standing were not.
    """
    before = [row["kind"] for row in consts.ConstantsFile(constants).types()]
    server.building_create(session, {}, {"data": BRICK})
    after = [row["kind"] for row in consts.ConstantsFile(constants).types()]
    assert after == [*before, "кирпичный"]


def test_the_rest_of_the_file_is_untouched(session: server.Session, constants: Path):
    """One block changes and nothing else: comments, units and notes survive."""
    before = doc_of(constants)
    text_before = constants.read_bytes().decode("utf-8")
    server.building_create(session, {}, {"data": BRICK})
    after = doc_of(constants)

    for group in before["groups"]:
        for entry in group["constants"]:
            if entry["key"] in consts.BUILDING_KEYS:
                continue
            twin = _entry(after, entry["key"])
            assert twin == entry, f"тронута чужая константа {entry['key']}"

    note = "Материалы на квадратный метр пола первого этажа"
    assert note in constants.read_bytes().decode("utf-8"), "комментарий к ключу потерян"
    assert text_before.count("\n") < constants.read_bytes().decode("utf-8").count("\n")


def _entry(doc: dict, key: str) -> dict | None:
    for group in doc["groups"]:
        for entry in group["constants"]:
            if entry.get("key") == key:
                return entry
    return None


def test_editing_a_type_rewrites_its_composition(session: server.Session, constants: Path):
    server.building_update(
        session,
        {"name": ["деревянный"]},
        {"data": {
            "kind": "деревянный",
            "per_m2": {"Дерево": 12, "Верёвка": 1},
            "growth": 2.5,
            "decay": 0.6,
            "upkeep": 1.7,
        }},
    )
    maps = maps_of(constants)
    assert maps[consts.COMPOSITION]["деревянный"] == {"Дерево": 12, "Верёвка": 1}
    assert maps[consts.GROWTH]["деревянный"] == 2.5
    assert maps[consts.DECAY]["деревянный"] == 0.6
    #: The ladder keeps its order through an edit: it is read as an order.
    assert [row["kind"] for row in consts.ConstantsFile(constants).types()][0] == "деревянный"


def test_renaming_carries_the_type_through_all_four(session: server.Session, constants: Path):
    result = server.building_update(
        session, {"name": ["бетонный"]}, {"data": {**BRICK, "kind": "бетонный-новый"}}
    )
    assert result["renamed"] == "бетонный"
    maps = maps_of(constants)
    for key in consts.BUILDING_KEYS:
        assert "бетонный" not in maps[key]
        assert "бетонный-новый" in maps[key]


def test_deleting_takes_the_type_out_everywhere(session: server.Session, constants: Path):
    server.building_delete(session, {"name": ["бетонный"]}, {})
    maps = maps_of(constants)
    for key in consts.BUILDING_KEYS:
        assert "бетонный" not in maps[key], f"остался в {key}"


# -------------------------------------------------------------------- refusals


def test_a_material_the_vault_does_not_know_is_refused(session: server.Session):
    """A typo passes YAML and passes the build; it fails in the engine, at the
    moment somebody tries to build a house. The refusal belongs here."""
    with pytest.raises(vault.VaultError, match="Древесина"):
        server.building_create(
            session, {}, {"data": {**BRICK, "per_m2": {"Древесина": 10}}}
        )


def test_an_empty_composition_is_refused(session: server.Session):
    with pytest.raises(vault.VaultError, match="состав пуст"):
        server.building_create(session, {}, {"data": {**BRICK, "per_m2": {}}})


def test_a_floor_cheaper_than_the_one_below_is_refused(session: server.Session):
    """Growth under one would make a tower cheaper than a hut: not a balance
    choice but an arithmetic slip, and it is caught before it is written."""
    with pytest.raises(vault.VaultError, match="этаж"):
        server.building_create(session, {}, {"data": {**BRICK, "growth": 0.5}})


def test_a_missing_number_is_refused(session: server.Session):
    with pytest.raises(vault.VaultError, match="порча"):
        server.building_create(session, {}, {"data": {**BRICK, "decay": ""}})


def test_a_name_taken_twice_is_refused(session: server.Session):
    with pytest.raises(vault.VaultError, match="уже есть"):
        server.building_create(session, {}, {"data": {**BRICK, "kind": "деревянный"}})


def test_the_last_type_is_not_deleted(session: server.Session, constants: Path):
    rows = consts.ConstantsFile(constants).types()
    for row in rows[1:]:
        server.building_delete(session, {"name": [row["kind"]]}, {})
    with pytest.raises(vault.VaultError, match="последний тип"):
        server.building_delete(session, {"name": [rows[0]["kind"]]}, {})


def test_a_refused_write_leaves_the_file_alone(session: server.Session, constants: Path):
    before = constants.read_bytes()
    with pytest.raises(vault.VaultError):
        server.building_create(session, {}, {"data": {**BRICK, "per_m2": {"Нетакого": 1}}})
    assert constants.read_bytes() == before


# ------------------------------------------------------------------------ undo


def test_undo_walks_back_the_file_that_was_written(
    session: server.Session, constants: Path, recipes: Path
):
    """The editor writes two files now, and undo must roll back the last edit
    rather than the last recipe edit."""
    recipes_before = recipes.read_bytes()
    constants_before = constants.read_bytes()

    file = vault.RecipesFile(recipes)
    data = {k: v for k, v in file.recipes()[0].items() if k not in ("level", "section")}
    data["note"] = "правка"
    vault.save(recipes, file.replace(data["name"], data), {"name": data["name"], "data": data},
               file.mtime, file.newline)
    server.building_create(session, {}, {"data": BRICK})
    assert constants.read_bytes() != constants_before

    vault.undo(session.source)
    assert constants.read_bytes() == constants_before, "откатился не тот файл"
    assert recipes.read_bytes() != recipes_before, "правка рецепта откатилась заодно"

    #: Кнопка отката была и остаётся качелями, а не стопкой: сам откат делает
    #: копию, и следующее нажатие возвращает отменённое. Здесь проверяется не
    #: это, а что качели качают тот файл, который правили последним.
    vault.undo(session.source)
    assert constants.read_bytes() != constants_before
