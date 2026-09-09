# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Фацеты и их связь с провинциями (план ландшафта §6, §7).

Что закреплено:

* у каждого биома реестра есть лицо, и лицо не стоит под биомом, которого
  нет: узел без фацета остался бы шестым одинаковым «Берегом» (волна 7);
* оси выбора объявлены и положительны — движок читает их по имени, и
  отсутствующая ось падала бы уже при находке;
* `favours` провинции называет фацет, который существует: ключ с опечаткой
  ничего не сломал бы и ничего не сделал — провинция молча осталась бы без
  характера (волна 8).
"""

from __future__ import annotations

import build

AXES = {
    "wave_m": 200,
    "slope_full": 0.2,
    "wet_km": 4,
    "patch_km": 1,
    "soft_edge": 0.25,
    "favour_k": 2.5,
}
CONSTANTS = {"biome.names": {"forest": "Лес", "coast": "Берег"}, "biome.facet_axes": AXES}
FACETS = {
    "forest": [{"id": "thicket"}, {"id": "knoll"}],
    "coast": [{"id": "beach_strip"}],
}


def test_every_biome_has_a_face_and_no_face_stands_under_a_stranger():
    assert build.check_facets(CONSTANTS, FACETS) == []
    lost = build.check_facets(CONSTANTS, {**FACETS, "swamp": [{"id": "quagmire"}]})
    assert any("swamp" in problem for problem in lost)
    bare = build.check_facets(CONSTANTS, {"forest": FACETS["forest"], "coast": []})
    assert any("coast" in problem for problem in bare)


def test_an_axis_the_engine_reads_must_be_declared_and_positive():
    for axis in AXES:
        without = {**CONSTANTS, "biome.facet_axes": {k: v for k, v in AXES.items() if k != axis}}
        assert any(axis in problem for problem in build.check_facets(without, FACETS))
        zeroed = {**CONSTANTS, "biome.facet_axes": {**AXES, axis: 0}}
        assert any(axis in problem for problem in build.check_facets(zeroed, FACETS))


def test_a_province_may_only_favour_a_face_that_exists():
    good = {"terra": [{"id": "ore_ridge", "favours": ["knoll"]}]}
    assert build.check_favours(good, FACETS) == []
    typo = {"terra": [{"id": "ore_ridge", "favours": ["knol"]}]}
    problems = build.check_favours(typo, FACETS)
    assert len(problems) == 1 and "knol" in problems[0] and "ore_ridge" in problems[0]


def test_a_province_need_not_favour_anything_and_facets_may_not_be_there_yet():
    assert build.check_favours({"terra": [{"id": "ore_ridge"}]}, FACETS) == []
    assert build.check_favours({"terra": [{"id": "ore_ridge", "favours": []}]}, FACETS) == []
    #: Пока таблицы фацетов нет, проверять не с чем — так вольт собирался
    #: между волнами 3 и 7, когда `favours` уже были написаны, а лиц не было.
    assert build.check_favours({"terra": [{"id": "x", "favours": ["knoll"]}]}, {}) == []
