# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Раскладка стартового мира: правила, которые обязаны сработать до движка.

Проверяется правило, а не вольт: документы здесь синтетические и умещаются в
экран. Настоящую раскладку меряет `python tools/build.py --check`.
"""

from __future__ import annotations

import world

#: Реестр вещей ни при чём: проверяется имя узла, а не то, что в нём стоит.
EMPTY_RECIPES: dict = {"meta": {"raw": []}, "operations": [], "levels": []}
KEY = "terra.capital"


def problems(*nodes: dict) -> list[str]:
    doc = {"external": ["terra"], "nodes": list(nodes)}
    return world.check_world(doc, EMPTY_RECIPES, lambda _doc: ())


def city(name, key: str = KEY) -> dict:
    return {"key": key, "name": name, "layer": "planet", "parent": "terra",
            "area_m2": 1, "city": True}


#: Ожидается целиком, а не по слову: жалоба, отобранная по подстроке, тихо
#: перестаёт отбираться, когда сообщение перепишут, и тест проходит впустую.
def too_long(length: int, key: str = KEY) -> str:
    return f"мир: имя города «{key}» — {length} знаков при потолке {world.WORLD_CITY_NAME_LIMIT}"


def test_a_city_name_at_the_ceiling_passes():
    found = problems(city("Г" * world.WORLD_CITY_NAME_LIMIT))
    assert too_long(world.WORLD_CITY_NAME_LIMIT) not in found


def test_a_longer_city_name_is_reported():
    over = world.WORLD_CITY_NAME_LIMIT + 1
    assert too_long(over) in problems(city("Г" * over))


def test_the_ceiling_is_only_asked_of_cities():
    long_name = "Г" * (world.WORLD_CITY_NAME_LIMIT + 1)
    plain = {"key": "terra.field", "name": long_name, "layer": "planet",
             "parent": "terra", "area_m2": 1}
    assert too_long(len(long_name), "terra.field") not in problems(plain)


def test_a_name_that_is_not_a_string_is_reported():
    """`name: 2026` разберётся в int, пройдёт проверку «без имени» и уедет в
    `City.name` целым числом — это своя жалоба, а не длина чего попало."""
    assert f"мир: имя города «{KEY}» — не строка" in problems(city(2026))
