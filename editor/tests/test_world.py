# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The world file, and the one promise the editor makes about it (D-243).

The promise is the same as for recipes: **an edit changes what was edited and
nothing else.** Here it is worth more than there, because a node is a block of
lines rather than one line, and the comments between those lines are half of
why the file exists -- why the printer at the forge is the city's and not the
Forerunners', why the plots are sized the way they are, why the road out of
the gate is a road and not a trail.

So the tests below are mostly about what a save does *not* do.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import vaultfile as vault
import worldfile as layout
import yaml


def open_world(path: Path) -> layout.WorldFile:
    return layout.WorldFile(path)


def save(file: layout.WorldFile, edit) -> layout.WorldFile:
    lines, doc = edit
    file.save(lines, doc)
    return layout.WorldFile(file.path)


def test_every_node_renders_back_identically(world: Path) -> None:
    """The lines the editor would write are the lines already in the file.

    The same guard `test_every_recipe_line_renders_back_identically` gives the
    ladder: if rendering and the file ever disagree, the first save of a node
    reformats it, and the diff of a one-field change becomes the whole block.

    Compared against the file **with its comments taken out**, because that is
    the honest comparison: rendering makes a block of data, and the comments
    around that data are what a save is not allowed to touch (which is what the
    tests below are about). Anything else in the block -- spacing, quoting,
    key order, how a number is written -- has to match to the character.
    """
    file = open_world(world)
    for key, block in file.nodes.items():
        body = [
            line for line in file.lines[block.start : block.end]
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert body == layout.render_node(layout.clean_node(file.node(key))), key


def test_saving_a_node_unchanged_changes_nothing(world: Path) -> None:
    file = open_world(world)
    for key in file.node_keys():
        lines, _ = file.put_node(file.node(key))
        assert lines == file.lines, key


def test_editing_one_field_moves_one_line(world: Path) -> None:
    """And the comments around it stay where they were."""
    file = open_world(world)
    before = file.lines
    node = copy.deepcopy(file.node("terra.capital.forge"))
    node["area_m2"] = 300
    lines, doc = file.put_node(node)

    assert len(lines) == len(before)
    changed = [index for index, line in enumerate(lines) if line != before[index]]
    assert len(changed) == 1
    assert lines[changed[0]].strip() == "area_m2: 300"
    file.save(lines, doc)
    #: And the reason the machines are what they are is still in the file.
    assert "Город продаёт не жизнь, а скорость" in world.read_text(encoding="utf-8")


def test_a_machine_added_keeps_the_comments_of_the_others(world: Path) -> None:
    """The list is edited entry by entry: what explains a machine stays above it."""
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.capital.forge"))
    node["machines"].append({"name": "Ткацкий станок", "quality": 55})
    again = save(file, file.put_node(node))

    text = world.read_text(encoding="utf-8")
    assert "Сундук (D-181)" in text
    assert "Электростанция гражданская (D-082)" in text
    machines = [one.get("name") for one in again.node("terra.capital.forge")["machines"]]
    assert machines[-1] == "Ткацкий станок"


def test_a_machine_removed_from_the_middle_leaves_the_others_explained(world: Path) -> None:
    """The comments must not slide onto the machines below them.

    This is the whole reason entries are matched by what they name rather than
    by position. Removing the second of the forge's seven machines used to
    shift the rest by one against the comments in the gaps -- and every guard
    passed, because the *data* was right; only the comments lied, which is the
    one thing this file exists to keep straight.
    """
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.capital.forge"))
    node["machines"] = [one for one in node["machines"] if one.get("name") != "Плавильная печь"]
    save(file, file.put_node(node))

    lines = world.read_text(encoding="utf-8").split("\n")
    explained = {
        "Кровать": "мастер живёт при деле",
        "Сундук": "D-181",
        "Угольная станция": "Электростанция гражданская",
    }
    for machine, comment in explained.items():
        at = next(index for index, line in enumerate(lines) if f"name: {machine}," in line)
        above = "\n".join(lines[max(0, at - 3) : at])
        assert comment in above, f"комментарий уехал с «{machine}»: {above!r}"
    assert "Плавильная печь" not in "\n".join(lines)


def test_a_field_removed_takes_its_comment_with_it(world: Path) -> None:
    """The same rule an entry lives by, one storey up.

    Clearing the mine's properties used to leave «лес и каменистая земля у
    шахты» standing over its veins, where it explains nothing and lies about
    everything. Two clicks in the form, every guard passing, and the file's
    reason for being written that way quietly reattached to the wrong thing.
    """
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.coal"))
    node.pop("properties")
    save(file, file.put_node(node))

    text = world.read_text(encoding="utf-8")
    assert "первый топор делается здесь" not in text
    #: And the node itself is otherwise whole.
    again = open_world(world)
    assert [vein["resource"] for vein in again.node("terra.coal")["veins"]] == [
        "Уголь",
        "Медная руда",
    ]
    #: The comment of the node above it is untouched: only this field's went.
    assert "Ближние ресурсы возят ежедневно" in text


def test_a_field_changed_keeps_its_comment(world: Path) -> None:
    """A field that stays keeps what explains it. The other half of the rule."""
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.coal"))
    node["properties"] = {**node["properties"], "лес": False}
    save(file, file.put_node(node))
    assert "первый топор делается здесь" in world.read_text(encoding="utf-8")


def test_a_machine_renamed_keeps_its_place_and_its_comment(world: Path) -> None:
    """A rename is one entry changing, not one leaving and another arriving."""
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.capital.forge"))
    at = next(i for i, one in enumerate(node["machines"]) if one.get("name") == "Кровать")
    node["machines"][at] = {"name": "Койка", "quality": 50}
    again = save(file, file.put_node(node))

    names = [one.get("name") or one.get("class") for one in again.node("terra.capital.forge")["machines"]]
    assert names[at] == "Койка", names
    lines = world.read_text(encoding="utf-8").split("\n")
    where = next(index for index, line in enumerate(lines) if "name: Койка," in line)
    assert "мастер живёт при деле" in lines[where - 1]


def test_two_fields_added_at_once_come_out_in_order(world: Path) -> None:
    """Two edits can start on the same line, and then their order decides
    whether the block reads back at all."""
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.capital.pit"))
    node["relics"] = ["Биопринтер"]
    node["items"] = [{"name": "Уголь", "amount": 2, "quality": 50, "origin": "проба"}]
    again = save(file, file.put_node(node))
    kept = again.node("terra.capital.pit")
    assert kept["relics"] == ["Биопринтер"]
    assert kept["items"][0]["name"] == "Уголь"
    #: And the block still renders back the way the editor would write it.
    block = again.nodes["terra.capital.pit"]
    body = [
        line for line in again.lines[block.start : block.end]
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert body == layout.render_node(layout.clean_node(kept))


def test_a_field_inserted_before_one_that_changed(world: Path) -> None:
    """An insertion and a replacement on the same line: neither may eat the other."""
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.capital.pit"))
    node["layer"] = "location"
    node["name"] = "Забой у стены, нижний ярус"
    again = save(file, file.put_node(node))
    kept = again.node("terra.capital.pit")
    assert kept["layer"] == "location"
    assert kept["name"] == "Забой у стены, нижний ярус"
    assert kept["parent"] == "terra.capital"


def test_a_key_that_already_exists_is_not_quietly_overwritten(world: Path) -> None:
    """"Add a node" and "change that node" are different intentions."""
    file = open_world(world)
    with pytest.raises(vault.VaultError, match="уже есть"):
        file.put_node(
            {"key": "terra.capital.forge", "name": "Другая мастерская", "area_m2": 10},
            fresh=True,
        )


def test_a_vein_removed_takes_its_line_and_no_other(world: Path) -> None:
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.coal"))
    node["veins"] = node["veins"][:1]
    lines, doc = file.put_node(node)

    gone = [line for line in file.lines if line not in lines]
    assert gone == ["      - {resource: Медная руда, richness: 41, remaining: 18000}"]
    again = save(file, (lines, doc))
    assert "первый топор делается здесь" in world.read_text(encoding="utf-8")
    assert [vein["resource"] for vein in again.node("terra.coal")["veins"]] == ["Уголь"]


def test_a_place_pinned_and_unpinned(world: Path) -> None:
    """Dragging a node writes its place; clearing it hands the node back to the engine."""
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.capital.gate"))
    node["place"] = {"x": 12.5, "y": -40}
    again = save(file, file.put_node(node))
    assert again.node("terra.capital.gate")["place"] == {"x": 12.5, "y": -40}

    loose = copy.deepcopy(again.node("terra.capital.gate"))
    loose.pop("place")
    third = save(again, again.put_node(loose))
    assert "place" not in third.node("terra.capital.gate")


def test_a_new_node_lands_after_the_one_it_hangs_on(world: Path) -> None:
    """Order in the file is the order the seed lays the world in.

    A node whose parent or anchor stands below it would be laid before the
    thing it is laid beside -- the build refuses that, and the editor must not
    write it in the first place.
    """
    file = open_world(world)
    again = save(file, file.put_node(
        {
            "key": "terra.quarry",
            "name": "Каменоломня",
            "layer": "planet",
            "parent": "terra",
            "area_m2": 500,
            "anchor": "terra.capital.gate",
        },
        after="terra.coal",
    ))
    keys = again.node_keys()
    assert keys.index("terra.quarry") == keys.index("terra.coal") + 1
    assert again.node("terra.quarry")["anchor"] == "terra.capital.gate"


def test_a_node_removed_takes_its_roads(world: Path) -> None:
    """"Remove this place" means nothing leads there any more."""
    file = open_world(world)
    again = save(file, file.drop_node("terra.capital.lot3"))
    assert "terra.capital.lot3" not in again.node_keys()
    assert not [
        edge for edge in again.doc["edges"] if "terra.capital.lot3" in (edge["a"], edge["b"])
    ]


def test_a_node_somebody_stands_on_is_not_removed(world: Path) -> None:
    """The refusal names who is standing on it, so it can be moved first."""
    file = open_world(world)
    with pytest.raises(vault.VaultError, match="опираются"):
        file.drop_node("terra.capital.forge")


def test_roads_are_undirected(world: Path) -> None:
    """a -- b and b -- a are one road: the way there is the way back."""
    file = open_world(world)
    again = save(file, file.put_edge(
        {"a": "terra.capital.lot1", "b": "terra.capital.forge", "seconds": 45, "surface": "paved"}
    ))
    matching = [
        edge for edge in again.doc["edges"]
        if {edge["a"], edge["b"]} == {"terra.capital.forge", "terra.capital.lot1"}
    ]
    assert len(matching) == 1
    assert matching[0]["seconds"] == 45


def test_a_road_into_nowhere_is_refused(world: Path) -> None:
    file = open_world(world)
    with pytest.raises(vault.VaultError, match="неизвестный узел"):
        file.put_edge({"a": "terra.capital.gate", "b": "terra.atlantis", "surface": "road"})


def test_a_road_by_reach_keeps_its_word(world: Path) -> None:
    """«По дали» is not a number and must not become one (D-180)."""
    file = open_world(world)
    edge = [
        one for one in file.doc["edges"]
        if {one["a"], one["b"]} == {"terra.capital.gate", "terra.coal"}
    ][0]
    assert edge["seconds"] == "reach"
    again = save(file, file.put_edge(dict(edge)))
    assert again.doc["edges"][file.edge_index("terra.capital.gate", "terra.coal")]["seconds"] == "reach"


def test_a_pocket_is_written_and_taken_away(world: Path) -> None:
    file = open_world(world)
    again = save(file, file.put_pocket("Хём", [
        {"name": "Железная руда", "amount": 30, "quality": 64, "origin": "проба"},
        {"name": "Уголь", "amount": 5, "quality": 50, "origin": "проба"},
    ]))
    assert [one["name"] for one in again.doc["pockets"]["Хём"]] == ["Железная руда", "Уголь"]
    third = save(again, again.put_pocket("Хём", []))
    assert "Хём" not in third.doc["pockets"]
    #: The other pocket is untouched: they are edited apart.
    assert "Тэрн" in third.doc["pockets"]


def test_a_thing_without_a_ground_is_refused(world: Path) -> None:
    """Matter never arrives in the world anonymously (pillar P1)."""
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.capital.forge"))
    node["items"].append({"name": "Уголь", "amount": 5, "quality": 50})
    with pytest.raises(vault.VaultError, match="основание"):
        file.put_node(node)


def test_a_machine_is_a_thing_or_a_class_and_not_both(world: Path) -> None:
    """A class is a hole in a requirement (D-215), not a second name for a thing."""
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.capital.port"))
    node["machines"] = [{"name": "Космическая верфь", "class": "Верфь", "quality": 60}]
    with pytest.raises(vault.VaultError, match="либо вещью, либо классом"):
        file.put_node(node)


def test_a_key_is_ascii_and_dotted(world: Path) -> None:
    """The key is what the world knows a node by for ever (D-007), and the
    engine's own layer keys are read off it."""
    file = open_world(world)
    with pytest.raises(vault.VaultError, match="не годится"):
        file.put_node({"key": "Столица", "name": "Столица", "area_m2": 100})


def test_a_file_that_moved_on_disk_is_not_overwritten(world: Path) -> None:
    """Two sessions in one copy are ordinary here (vault CLAUDE.md)."""
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.capital.gate"))
    node["area_m2"] = 90
    lines, doc = file.put_node(node)
    world.write_text(world.read_text(encoding="utf-8") + "\n# чужая правка\n", encoding="utf-8")
    with pytest.raises(vault.VaultError, match="изменился на диске"):
        file.save(lines, doc)


def test_the_document_is_what_the_engine_will_read(world: Path) -> None:
    """Whatever the editor writes must parse into the shape the seed expects."""
    file = open_world(world)
    node = copy.deepcopy(file.node("terra.capital.market"))
    node["items"] = [{"name": "Уголь", "amount": 5, "quality": 50, "origin": "проба"}]
    save(file, file.put_node(node))
    doc = yaml.safe_load(world.read_text(encoding="utf-8"))
    market = [one for one in doc["nodes"] if one["key"] == "terra.capital.market"][0]
    assert market["items"] == [
        {"name": "Уголь", "amount": 5, "quality": 50, "origin": "проба"}
    ]
