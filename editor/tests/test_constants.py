# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The numbers of the game, edited one at a time (D-065).

What is checked is what the editor promises about the file: an entry saved
unchanged changes nothing, a number changed changes one line, and the comment
above the entry -- the reason the number is what it is -- stays where it is.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

import constantsfile as consts
import pytest
import server
import store
import vaultfile as vault
import yaml


def doc_of(path: Path) -> dict:
    return yaml.safe_load(path.read_bytes().decode("utf-8"))


def entry_of(path: Path, key: str) -> dict | None:
    for group in doc_of(path)["groups"]:
        for entry in group["constants"]:
            if entry.get("key") == key:
                return entry
    return None


def changed_lines(before: list[str], after: list[str]) -> int:
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, before, after).get_opcodes()
        if tag != "equal"
    )


def some_number(file: consts.ConstantsFile) -> str:
    return next(
        entry["key"]
        for group in file.registry()
        for entry in group["constants"]
        if entry["kind"] == "value" and isinstance(entry["value"], (int, float))
        and not isinstance(entry["value"], bool) and entry["decision"]
    )


# ----------------------------------------------------------------- reading


def test_the_registry_lists_every_constant(constants: Path):
    file = consts.ConstantsFile(constants)
    listed = {entry["key"] for group in file.registry() for entry in group["constants"]}
    assert listed == set(file.entries)
    assert len(listed) > 300
    kinds = {entry["kind"] for group in file.registry() for entry in group["constants"]}
    assert kinds == {"value", "formula", "value_from"}


def test_a_comment_above_belongs_to_its_entry(constants: Path):
    file = consts.ConstantsFile(constants)
    told = [
        entry for group in file.registry() for entry in group["constants"] if entry["comment"]
    ]
    assert told, "в файле есть константы с комментарием над ними"
    for entry in told:
        assert all(line.startswith("#") for line in entry["comment"])


# ----------------------------------------------------------------- writing


def test_saving_every_entry_unchanged_changes_nothing(constants: Path):
    """The field-level surgery must recognise every entry as itself."""
    file = consts.ConstantsFile(constants)
    for group in file.doc["groups"]:
        for entry in group["constants"]:
            if entry["key"] in consts.BUILDING_KEYS:
                continue
            lines, expect = file.set_entry(entry["key"], dict(entry))
            assert lines == file.lines, f"{entry['key']}: сохранение без правки тронуло файл"
            assert vault._comparable(expect) == vault._comparable(file.doc)


def test_a_number_changed_is_one_line(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    key = some_number(file)
    before = file.lines
    entry = dict(file._entry(key))
    entry["value"] = 12345

    server.constant_update(session, {"key": [key]}, {"data": entry})

    after = consts.ConstantsFile(constants)
    assert changed_lines(before, after.lines) == 1
    assert after.value(key) == 12345


def test_a_note_is_added_in_its_place(session: server.Session, constants: Path):
    """A new field goes where the canon puts it: after `unit`, before `decision`."""
    file = consts.ConstantsFile(constants)
    key = next(
        entry["key"]
        for group in file.registry() for entry in group["constants"]
        if entry["kind"] == "value" and entry["unit"] and entry["decision"] and not entry["note"]
    )
    entry = {**file._entry(key), "note": "пояснение из редактора"}

    server.constant_update(session, {"key": [key]}, {"data": entry})

    after = consts.ConstantsFile(constants)
    span = after.entries[key]
    block = after.lines[span.start : span.end]
    heads = [line.strip().split(":")[0] for line in block]
    assert heads == ["- key", "value", "unit", "note", "decision"]
    assert changed_lines(file.lines, after.lines) == 1


def test_a_range_and_a_table_read_back(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    ranged = next(
        entry["key"] for group in file.registry() for entry in group["constants"]
        if isinstance(entry["value"], dict) and set(entry["value"]) == {"min", "max"}
    )
    server.constant_update(
        session, {"key": [ranged]}, {"data": {**file._entry(ranged), "value": {"min": 1, "max": 9}}}
    )
    assert entry_of(constants, ranged)["value"] == {"min": 1, "max": 9}

    file = consts.ConstantsFile(constants)
    table = next(
        entry["key"] for group in file.registry() for entry in group["constants"]
        if isinstance(entry["value"], dict) and set(entry["value"]) != {"min", "max"}
        and not entry["building"]
    )
    wanted = {"первое: с двоеточием": 1, "второе": 2.5}
    server.constant_update(
        session, {"key": [table]}, {"data": {**file._entry(table), "value": wanted}}
    )
    assert entry_of(constants, table)["value"] == wanted


def test_a_value_typed_as_yaml_is_read(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    key = some_number(file)
    data = {**file._entry(key)}
    data.pop("value")
    server.constant_update(
        session, {"key": [key]}, {"data": {**data, "value_yaml": "- {from: 0, to: 1, name: x}"}}
    )
    assert entry_of(constants, key)["value"] == [{"from": 0, "to": 1, "name": "x"}]
    with pytest.raises(vault.VaultError, match="YAML"):
        server.constant_update(
            session, {"key": [key]}, {"data": {**data, "value_yaml": "{unclosed: ["}}
        )


def test_the_building_maps_are_refused_here(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    with pytest.raises(vault.VaultError, match="Здания"):
        server.constant_update(
            session, {"key": [consts.COMPOSITION]}, {"data": file._entry(consts.COMPOSITION)}
        )


def test_a_key_is_renamed_on_its_own_line(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    key = some_number(file)
    fresh = key + "_renamed"
    before = file.lines
    server.constant_update(session, {"key": [key]}, {"data": {**file._entry(key), "key": fresh}})
    after = consts.ConstantsFile(constants)
    assert fresh in after.entries and key not in after.entries
    assert changed_lines(before, after.lines) == 1


@pytest.mark.parametrize("key", ["Energy.body", "energy", "energy.", "energy.Body-print"])
def test_a_bad_key_is_refused(key: str):
    with pytest.raises(vault.VaultError, match="ключ"):
        consts.clean_entry({"key": key, "value": 1})


def test_exactly_one_way_of_saying_the_value():
    with pytest.raises(vault.VaultError, match="ровно одно"):
        consts.clean_entry({"key": "a.b", "value": 1, "formula": "x"})
    with pytest.raises(vault.VaultError, match="ровно одно"):
        consts.clean_entry({"key": "a.b"})
    assert consts.clean_entry({"key": "a.b", "value": 0})["value"] == 0
    assert consts.clean_entry({"key": "a.b", "value": False})["value"] is False


# ---------------------------------------------------------- adding, dropping


def test_a_new_constant_goes_last_in_its_group(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    group = file.doc["groups"][0]["id"]
    before = file.lines
    server.constant_create(
        session, {},
        {
            "group": group,
            "data": {"key": "anchors.new_one", "value": 7, "unit": "шт.", "note": "проба"},
        },
    )
    after = consts.ConstantsFile(constants)
    keys = [entry["key"] for entry in after.doc["groups"][0]["constants"]]
    assert keys[-1] == "anchors.new_one"
    assert changed_lines(before, after.lines) == 4
    assert entry_of(constants, "anchors.new_one") == {
        "key": "anchors.new_one", "value": 7, "unit": "шт.", "note": "проба",
    }


def test_a_new_constant_may_follow_a_named_one(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    group = file.doc["groups"][0]
    first = group["constants"][0]["key"]
    server.constant_create(
        session, {},
        {"group": group["id"], "after": first, "data": {"key": "anchors.second", "value": 1}},
    )
    after = consts.ConstantsFile(constants)
    keys = [entry["key"] for entry in after.doc["groups"][0]["constants"]]
    assert keys[1] == "anchors.second"


def test_a_taken_key_is_refused(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    key = some_number(file)
    with pytest.raises(vault.VaultError, match="уже есть"):
        server.constant_create(
            session, {}, {"group": file.group_of[key], "data": {"key": key, "value": 1}}
        )


def test_dropping_takes_the_comment_along(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    key = next(
        entry["key"] for group in file.registry() for entry in group["constants"]
        if entry["comment"] and not entry["building"]
        and len([one for one in group["constants"]]) > 1
    )
    span = file.entries[key]
    comment = file.lines[span.lead : span.start]
    server.constant_delete(session, {"key": [key]}, {})
    after = consts.ConstantsFile(constants)
    assert key not in after.entries
    assert not any(line in after.lines for line in comment)
    assert changed_lines(file.lines, after.lines) == span.end - span.lead


def test_the_last_constant_of_a_group_stays(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    group = next(one for one in file.doc["groups"] if len(one["constants"]) == 1)
    with pytest.raises(vault.VaultError, match="последняя"):
        server.constant_delete(session, {"key": [group["constants"][0]["key"]]}, {})


def test_an_edit_is_undone(session: server.Session, constants: Path):
    before = constants.read_bytes()
    file = consts.ConstantsFile(constants)
    key = some_number(file)
    server.constant_update(session, {"key": [key]}, {"data": {**file._entry(key), "value": 99}})
    assert constants.read_bytes() != before
    store.undo(session.source)
    assert constants.read_bytes() == before


def test_the_rest_of_the_file_is_untouched(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    key = some_number(file)
    comments = [line for line in file.lines if line.lstrip().startswith("#")]
    server.constant_update(session, {"key": [key]}, {"data": {**file._entry(key), "value": 99}})
    after = consts.ConstantsFile(constants)
    assert [line for line in after.lines if line.lstrip().startswith("#")] == comments
    for group in file.doc["groups"]:
        for entry in group["constants"]:
            if entry["key"] != key:
                assert entry_of(constants, entry["key"]) == entry


def test_a_value_block_with_a_comment_inside_is_refused(session: server.Session, constants: Path):
    """The lines over «Нефть: 0» say why the zero is there; a re-rendered block would drop them."""
    file = consts.ConstantsFile(constants)
    key = next(
        entry["key"]
        for group in file.doc["groups"] for entry in group["constants"]
        if entry["key"] not in consts.BUILDING_KEYS
        and any(
            file.lines[n].lstrip().startswith("#")
            for n in range(file.entries[entry["key"]].start + 1, file.entries[entry["key"]].end)
        )
    )
    before = constants.read_bytes()
    data = {**file._entry(key), "value": {"x": 1}}
    with pytest.raises(vault.VaultError, match="комментарий"):
        server.constant_update(session, {"key": [key]}, {"data": data})
    assert constants.read_bytes() == before
    #: The other fields of such an entry stay editable: only the block is fenced.
    server.constant_update(session, {"key": [key]}, {"data": {**file._entry(key), "note": "иначе"}})
    assert entry_of(constants, key)["note"] == "иначе"


def test_a_field_taken_away_takes_its_line(session: server.Session, constants: Path):
    file = consts.ConstantsFile(constants)
    key = some_number(file)
    data = dict(file._entry(key))
    unit = data.pop("unit")
    assert unit
    server.constant_update(session, {"key": [key]}, {"data": data})
    after = consts.ConstantsFile(constants)
    assert "unit" not in after._entry(key)
    assert changed_lines(file.lines, after.lines) == 1


def test_the_building_maps_are_not_dropped_here(session: server.Session):
    with pytest.raises(vault.VaultError, match="D-218"):
        server.constant_delete(session, {"key": [consts.COMPOSITION]}, {})
