# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The cultures file, and the one promise the editor makes about it (D-057).

The promise is the world file's: **an edit changes what was edited and nothing
else.** It is worth as much here, because a culture is a block of lines and the
comments between them carry the balance of the game -- why the turnip is not
fed mineral, why St John's wort is not fed at all, why the brome eats whatever
it is given.

So most of these tests are about what a save does *not* do. What it must do is
one thing: refuse a culture the build would refuse, while the person is still
looking at the field.
"""

from __future__ import annotations

import copy
from pathlib import Path

import api_plants as api
import plantsfile as crops
import pytest
import vaultfile as vault
import yaml


def open_plants(path: Path) -> crops.PlantsFile:
    return crops.PlantsFile(path)


def save(file: crops.PlantsFile, edit) -> crops.PlantsFile:
    lines, doc = edit
    file.save(lines, doc)
    return crops.PlantsFile(file.path)


def test_every_culture_renders_back_identically(plants: Path) -> None:
    """The lines the editor would write are the lines already in the file.

    If rendering and the file ever disagree, the first save of a culture
    reformats it and the diff of a one-number change becomes the whole block.
    Compared against the file with its comments taken out: rendering makes a
    block of data, and the comments around it are what a save must not touch.
    """
    file = open_plants(plants)
    for plant_id, block in file.plants.items():
        body = [
            line
            for line in file.lines[block.start : block.end]
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert body == crops.render_plant(crops.clean_plant(file.plant(plant_id))), plant_id


def test_saving_a_culture_unchanged_changes_nothing(plants: Path) -> None:
    file = open_plants(plants)
    before = file.text
    after = save(file, file.put_plant(file.plant("spelt")))
    assert after.text == before


def test_editing_one_number_moves_one_line(plants: Path) -> None:
    """The whole point of the module: a cycle changed is a cycle changed."""
    file = open_plants(plants)
    before = file.lines
    data = copy.deepcopy(file.plant("turnip"))
    data["cycle"] = 5
    after = save(file, file.put_plant(data))
    moved = [
        (was, now) for was, now in zip(before, after.lines, strict=False) if was != now
    ]
    assert len(moved) == 1
    assert moved[0][1].strip() == "cycle: 5"
    assert after.plant("turnip")["cycle"] == 5


def test_the_comment_over_a_feeding_table_stays(plants: Path) -> None:
    """The turnip's table is explained by the line above it: mineral runs the
    root to leaf. A row added must not carry that away."""
    file = open_plants(plants)
    before = "\n".join(file.lines)
    assert "ботву" in before
    data = copy.deepcopy(file.plant("turnip"))
    data["feeding"] = [*data["feeding"], {"stage": "leaf", "fertilizer": "compost", "growth": 40}]
    after = save(file, file.put_plant(data))
    assert "ботву" in after.text
    assert len(after.plant("turnip")["feeding"]) == 2
    #: And the row that was there is where it was, untouched.
    assert after.plant("turnip")["feeding"][0] == file.plant("turnip")["feeding"][0]


def test_a_row_removed_from_the_middle_leaves_the_others_where_they_lie(plants: Path) -> None:
    file = open_plants(plants)
    was = file.plant("brome")["feeding"]
    assert len(was) == 4, "тесту нужна культура с несколькими строками подкормки"
    data = copy.deepcopy(file.plant("brome"))
    del data["feeding"][1]
    after = save(file, file.put_plant(data))
    assert after.plant("brome")["feeding"] == [was[0], was[2], was[3]]


def test_a_culture_that_is_not_fed_keeps_its_empty_table(plants: Path) -> None:
    """St John's wort is fed nothing, and the file says so with `feeding: []`.
    Rows added and taken away again must leave that line as it was."""
    file = open_plants(plants)
    assert file.plant("stjohnswort")["feeding"] == []
    data = copy.deepcopy(file.plant("stjohnswort"))
    data["feeding"] = [{"stage": "sprout", "fertilizer": "compost", "growth": 30}]
    after = save(file, file.put_plant(data))
    assert after.plant("stjohnswort")["feeding"] == data["feeding"]

    back = copy.deepcopy(after.plant("stjohnswort"))
    back["feeding"] = []
    final = save(after, after.put_plant(back))
    assert final.plant("stjohnswort")["feeding"] == []
    assert "feeding: []" in final.text


def test_a_new_culture_lands_at_the_end_and_reads_back(plants: Path) -> None:
    file = open_plants(plants)
    data = {
        "id": "millet",
        "wild_name": "Дикое просо",
        "seed": "Семена проса",
        "name": "Просо",
        "gives": "Зерно",
        "cycle": 5,
        "requires": {"temp": {"min": 8, "max": 32}, "water": 1, "fertility": 25, "light": 3},
        "traits": {"hardiness": 4, "disease_risk": 2, "density_risk": 2, "spoilage_k": 0.4},
        "feeding": [{"stage": "leaf", "fertilizer": "compost", "growth": 50}],
        "note": "Засухоустойчивое зерно",
    }
    after = save(file, file.put_plant(data, fresh=True))
    assert after.ids()[-1] == "millet"
    assert after.plant("millet") == data
    #: And the neighbour above it is untouched, comment and all.
    assert after.text.count("Страховка от неурожая") == 1


def test_an_id_that_exists_is_not_quietly_overwritten(plants: Path) -> None:
    file = open_plants(plants)
    with pytest.raises(vault.VaultError, match="уже есть"):
        file.put_plant(dict(file.plant("spelt"), name="Другая полба"), fresh=True)


def test_a_culture_removed_takes_its_block_and_no_other(plants: Path) -> None:
    file = open_plants(plants)
    after = save(file, file.drop_plant("camelina"))
    assert "camelina" not in after.ids()
    assert len(after.ids()) == len(file.ids()) - 1
    for plant_id in after.ids():
        assert after.plant(plant_id) == file.plant(plant_id)


def test_the_document_is_what_the_build_will_read(plants: Path) -> None:
    """The file after a save parses to exactly the intended document: the check
    `store.prepare_doc` makes, made here against the real file."""
    file = open_plants(plants)
    data = copy.deepcopy(file.plant("flax"))
    data["traits"]["disease_risk"] = 4
    lines, doc = file.put_plant(data)
    file.save(lines, doc)
    assert yaml.safe_load(Path(file.path).read_text(encoding="utf-8")) == doc


# --- what the form must refuse while the person is still looking at it -------


def test_a_culture_needs_a_name_in_the_vault_s_own_language(plants: Path) -> None:
    file = open_plants(plants)
    data = dict(file.plant("spelt"), name="  ")
    with pytest.raises(vault.VaultError, match="название"):
        file.put_plant(data)


def test_an_id_is_a_stable_key(plants: Path) -> None:
    file = open_plants(plants)
    with pytest.raises(vault.VaultError, match="D-251"):
        file.put_plant(dict(file.plant("spelt"), id="Полба"))


def test_a_band_of_temperature_runs_upwards(plants: Path) -> None:
    file = open_plants(plants)
    data = copy.deepcopy(file.plant("spelt"))
    data["requires"]["temp"] = {"min": 30, "max": 4}
    with pytest.raises(vault.VaultError, match="ниже верхней"):
        file.put_plant(data)


def test_a_trait_stays_on_its_five_point_scale(plants: Path) -> None:
    file = open_plants(plants)
    data = copy.deepcopy(file.plant("spelt"))
    data["traits"]["disease_risk"] = 9
    with pytest.raises(vault.VaultError, match="боязнь напастей"):
        file.put_plant(data)


def test_a_feeding_stage_is_one_the_engine_knows(plants: Path) -> None:
    """`ripe` is not a stage of feeding: what is ripe is reaped (D-296)."""
    file = open_plants(plants)
    data = copy.deepcopy(file.plant("spelt"))
    data["feeding"] = [{"stage": "ripe", "fertilizer": "compost", "growth": 50}]
    with pytest.raises(vault.VaultError, match="фаза"):
        file.put_plant(data)


def test_one_pair_is_not_written_twice(plants: Path) -> None:
    file = open_plants(plants)
    data = copy.deepcopy(file.plant("spelt"))
    data["feeding"] = [
        {"stage": "leaf", "fertilizer": "compost", "growth": 50},
        {"stage": "leaf", "fertilizer": "compost", "growth": 70},
    ]
    with pytest.raises(vault.VaultError, match="дважды"):
        file.put_plant(data)


def test_a_file_that_moved_on_disk_is_not_overwritten(plants: Path) -> None:
    """Two sessions in one copy are ordinary here, and the second save must
    refuse rather than write over the first."""
    file = open_plants(plants)
    other = open_plants(plants)
    save(file, file.put_plant(dict(file.plant("spelt"), cycle=7)))
    with pytest.raises(vault.VaultError):
        save(other, other.put_plant(dict(other.plant("turnip"), cycle=3)))


# --- the handlers: the file and the names move together (D-251) ---------------


def read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_api_writes_the_name_of_the_culture_and_of_its_ancestor(session, plants: Path) -> None:
    """A culture is not made until every language knows it and its wild
    ancestor: the build refuses the rest, so the form asks for both (D-260)."""
    answer = api.plants(session, {}, {})
    turnip = next(one for one in answer["plants"] if one["id"] == "turnip")
    api.plant_put(
        session,
        {"was": ["turnip"]},
        {"data": turnip, "names": {"en": "Garden turnip"}, "wild": {"en": "Wild turnip"}},
    )
    english = read(session.locales_dir / "en.yaml")["plants"]
    assert english["turnip"] == "Garden turnip"
    assert english["turnip_wild"] == "Wild turnip"
    #: And the cultures' own file did not move for a name-only change.
    assert read(plants)["plants"] == read(session.plants)["plants"]


def test_the_form_does_not_rename_a_culture(session) -> None:
    """An id is what the engine, the base and the wire know a culture by: a form
    that renamed it would leave two cultures and one name."""
    answer = api.plants(session, {}, {})
    spelt = next(one for one in answer["plants"] if one["id"] == "spelt")
    with pytest.raises(vault.VaultError, match="не переименовывается"):
        api.plant_put(session, {"was": ["spelt"]}, {"data": {**spelt, "id": "spelt2"}})
    assert [one["id"] for one in api.plants(session, {}, {})["plants"]].count("spelt") == 1


def test_a_culture_deleted_loses_its_names_too(session) -> None:
    api.plant_delete(session, {"id": ["camelina"]}, {})
    english = read(session.locales_dir / "en.yaml")["plants"]
    assert "camelina" not in english and "camelina_wild" not in english
    assert "camelina" not in [one["id"] for one in api.plants(session, {}, {})["plants"]]


def test_the_stages_come_from_the_vault_not_from_the_editor(session) -> None:
    """A stage added to `farm.stage_bounds` is feedable the same day: the build
    reads the stages from there, and so does the form."""
    answer = api.plants(session, {}, {})
    assert answer["stages"][0] == crops.SPROUT
    bounds = session.open_constants().value("farm.stage_bounds")
    assert answer["stages"] == [crops.SPROUT, *bounds]


def test_the_palette_offers_the_fertilizer_class_by_its_key(session) -> None:
    """The feeding table names things by their stable ids (D-251), and the class
    is found by its own key rather than by its Russian name (D-215)."""
    palette = api.plants(session, {}, {})["palette"]
    assert "compost" in palette["fertilizers"]
    assert all(one.islower() and " " not in one for one in palette["fertilizers"])


def test_a_field_the_form_does_not_know_is_named(session) -> None:
    """Not dropped silently, and not left to the document check to refuse with
    a puzzle for a message."""
    answer = api.plants(session, {}, {})
    spelt = next(one for one in answer["plants"] if one["id"] == "spelt")
    with pytest.raises(vault.VaultError, match="«ripens_in»"):
        api.plant_put(session, {"was": ["spelt"]}, {"data": {**spelt, "ripens_in": 3}})


def test_a_scale_admits_its_own_ends(session) -> None:
    """One and five are on the five-point scale, and one and three on the other:
    an `above` where the vault means `at_least` would refuse the brome."""
    answer = api.plants(session, {}, {})
    brome = next(one for one in answer["plants"] if one["id"] == "brome")
    assert brome["traits"]["density_risk"] == 1 and brome["requires"]["water"] == 1
    api.plant_put(session, {"was": ["brome"]}, {"data": brome})


def test_a_new_culture_leaves_the_vault_buildable(session, plants: Path) -> None:
    """The whole point of the tab: what it writes, the build accepts. Three names
    are owed -- the culture's, its ancestor's and its seed's (D-251, D-260) --
    and all three land in one write per file rather than over each other."""
    api.plant_put(
        session,
        {"fresh": ["1"]},
        {
            "data": {
                "id": "millet",
                "wild_name": "Дикое просо",
                "seed": "Семена проса",
                "name": "Просо",
                "gives": "Зерно",
                "cycle": 5,
                "requires": {"temp": {"min": 8, "max": 32}, "water": 1, "fertility": 25, "light": 3},
                "traits": {"hardiness": 4, "disease_risk": 2, "density_risk": 2, "spoilage_k": 0.4},
                "feeding": [{"stage": "leaf", "fertilizer": "compost", "growth": 50}],
                "note": "Засухоустойчивое зерно",
            },
            "names": {"en": "Millet"},
            "wild": {"en": "Wild millet"},
            "seed": {"en": "Millet seeds"},
        },
    )
    english = read(session.locales_dir / "en.yaml")
    assert english["plants"]["millet"] == "Millet"
    assert english["plants"]["millet_wild"] == "Wild millet"
    assert english["goods"]["millet_seeds"] == "Millet seeds", "семя — тоже товар (seed_ids)"
    assert "millet" in [one["id"] for one in read(session.plants)["plants"]]


def test_a_produce_without_an_hour_of_labour_is_refused(session) -> None:
    """A culture whose produce is not in `harvest.rates` has no yield to derive
    (D-136), and the build would refuse the whole file for it."""
    answer = api.plants(session, {}, {})
    spelt = next(one for one in answer["plants"] if one["id"] == "spelt")
    with pytest.raises(vault.VaultError, match="harvest.rates"):
        api.plant_put(session, {"was": ["spelt"]}, {"data": {**spelt, "gives": "Сталь"}})


def test_a_feeding_of_something_that_is_not_a_fertilizer_is_refused(session) -> None:
    answer = api.plants(session, {}, {})
    spelt = next(one for one in answer["plants"] if one["id"] == "spelt")
    broken = {**spelt, "feeding": [{"stage": "leaf", "fertilizer": "steel", "growth": 50}]}
    with pytest.raises(vault.VaultError, match="Удобрение"):
        api.plant_put(session, {"was": ["spelt"]}, {"data": broken})
