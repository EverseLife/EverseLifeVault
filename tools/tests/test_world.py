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


def city(title, key: str = KEY) -> dict:
    """Узел, на котором основывается город: `city` — его имя (D-330).

    Узла-пустышки под живым городом больше нет, и имя города носит тот же
    узел, что стоит на карте своим.
    """
    return {"key": key, "name": "Ядро", "layer": "planet",
            "parent": "terra", "area_m2": 1, "city": title}


#: Ожидается целиком, а не по слову: жалоба, отобранная по подстроке, тихо
#: перестаёт отбираться, когда сообщение перепишут, и тест проходит впустую.
def too_long(length: int, key: str = KEY) -> str:
    return f"мир: имя города «{key}» — {length} знаков при потолке {world.WORLD_CITY_NAME_LIMIT}"


def namesakes(first: str, second: str, title: str) -> str:
    return f"мир: города «{first}» и «{second}» носят одно имя «{title}»"


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
    """`city: 2026` разберётся в int и уехало бы в `City.name` целым числом —
    это своя жалоба, а не длина чего попало."""
    assert f"мир: у «{KEY}» в `city` не имя города, а 2026 — " in " ".join(
        problems(city(2026))
    )


def test_the_old_flag_says_what_to_write_instead():
    """`city: true` — прежняя запись, когда имя города брали у узла (D-330).
    Молча она значила бы «город по имени True»: жалоба говорит, что делать."""
    found = " ".join(problems(city(True)))
    assert "городом теперь помечает имя, а не галочка (D-330)" in found


def test_an_empty_city_name_is_reported():
    """Пустая строка — не имя: город вышел бы безымянным, и канал тоже."""
    assert f"мир: имя города «{KEY}» — пустое" in problems(city("   "))


def test_two_cities_of_one_name_are_reported():
    """Имя города держится уникальным индексом в движке: раскладка с тёзками
    не «выдаст двух», а не разложится вовсе — сид упадёт посреди мира."""
    found = problems(city("Новоград"), city("Новоград", "terra.second"))
    assert namesakes(KEY, "terra.second", "Новоград") in found


def test_namesakes_are_told_apart_ignoring_case():
    """Регистр не в счёт: сверяет их Сеть, а она равняет имена каналов так."""
    found = problems(city("Новоград"), city("новоград", "terra.second"))
    assert namesakes(KEY, "terra.second", "новоград") in found


def test_two_cities_of_different_names_pass():
    found = problems(city("Новоград"), city("Старград", "terra.second"))
    assert not [p for p in found if "носят одно имя" in p]


def test_namesakes_are_only_asked_of_cities():
    """Два обычных узла-тёзки законны: городом становится только помеченный."""
    plain = {"key": "terra.field", "name": "Луг", "layer": "planet",
             "parent": "terra", "area_m2": 1}
    twin = {**plain, "key": "terra.field.two"}
    assert not [p for p in problems(plain, twin) if "носят одно имя" in p]
