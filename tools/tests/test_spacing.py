# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Зазор между узлами: что обещает движок и чего не обещает пин.

Сажая узел, движок не ставит его ближе `map.min_gap_m` к соседям (D-319,
`places._geo_seat`). На **прибитый** пин это обещание не распространяется:
`seed_world._pinned` кладёт узел ровно туда, где сказано, и на соседей не
смотрит. Значит раскладка, написанная руками, может поставить два узла
вплотную — и до 2026-09-08 узнать об этом было неоткуда, кроме как увидеть на
карте два слипшихся кружка.

Порог тут не про красоту. Клиент рисует узел кружком **в пятую долю зазора**
(`bands.nodeRadius`), чтобы круг никогда не накрывал соседа; два узла ближе
зазора — это два кружка друг на друге, и никакой зум их не разведёт: и то и
другое в единицах карты, отношение от масштаба не зависит.
"""

from __future__ import annotations

import world

#: Терра после D-324: доля суши 1/4096 от Земли, отсюда радиус около 99.5 км.
CONSTANTS = {
    "map.min_gap_m": 6,
    "planet.land_area_share": {"terra": 0.000244140625},
    "planet.earth_radius_km": 6371,
}


def layout(*nodes: dict) -> dict:
    return {"nodes": [{"area_m2": 100, **node} for node in nodes]}


def test_two_nodes_on_one_pin_are_refused() -> None:
    """То, ради чего проверка есть."""
    doc = layout(
        {"key": "terra.town", "parent": "terra", "place": {"lat": 40.0, "lon": 20.0}},
        {"key": "terra.town.a", "parent": "terra.town", "place": {"x": 0, "y": 0}},
        {"key": "terra.town.b", "parent": "terra.town", "place": {"x": 2, "y": 0}},
    )
    found = world.check_spacing(doc, CONSTANTS)
    assert len(found) == 1, found
    assert "terra.town.a" in found[0] and "terra.town.b" in found[0]
    #: Отказ называет и расстояние, и число, по которому судит: правящему
    #: раскладку надо знать, на сколько подвинуть.
    assert "2.0 м" in found[0] and "map.min_gap_m" in found[0]


def test_the_gap_itself_passes() -> None:
    """Ровно зазор — уже не тесно: движок сажает по этому же правилу."""
    doc = layout(
        {"key": "terra.town", "parent": "terra", "place": {"lat": 40.0, "lon": 20.0}},
        {"key": "terra.town.a", "parent": "terra.town", "place": {"x": 0, "y": 0}},
        {"key": "terra.town.b", "parent": "terra.town", "place": {"x": 0, "y": 6}},
    )
    assert world.check_spacing(doc, CONSTANTS) == []


def test_metres_are_counted_from_the_anchor_and_along_the_chain() -> None:
    """Пин — метры от якоря, а не от начала карты (`seed_world._pinned`).

    Читай их от начала, и цепочка «лавка от рынка, карьер от лавки» сложилась
    бы в другие места: тесноту нашли бы там, где её нет, и проглядели бы там,
    где она есть.
    """
    doc = layout(
        {"key": "terra.town", "parent": "terra", "place": {"lat": 40.0, "lon": 20.0}},
        {"key": "terra.town.core", "parent": "terra.town", "place": {"x": 0, "y": 0}},
        {"key": "terra.town.shop", "parent": "terra.town", "anchor": "terra.town.core",
         "place": {"x": 30, "y": 0}},
        #: От рынка ещё тридцать — до ядра шестьдесят, тесноты нет. Считай
        #: от начала карты — вышло бы, что карьер стоит на рынке.
        {"key": "terra.town.pit", "parent": "terra.town", "anchor": "terra.town.shop",
         "place": {"x": 30, "y": 0}},
    )
    assert world.check_spacing(doc, CONSTANTS) == []


def test_two_maps_are_not_one() -> None:
    """Тесно бывает только на одной карте.

    Узел Авроры и узел Терры не соседи ни в каком смысле, а по метрам своих
    кадров могут прийтись рядом: у каждой планеты кадр свой.
    """
    doc = layout(
        {"key": "terra.town", "parent": "terra", "place": {"lat": 40.0, "lon": 20.0}},
        {"key": "aurora.town", "parent": "aurora", "place": {"lat": 40.0, "lon": 20.0}},
    )
    assert world.check_spacing(doc, {**CONSTANTS, "planet.land_area_share": {
        "terra": 0.000244140625, "aurora": 0.00048828125}}) == []


def test_without_the_numbers_the_check_says_nothing() -> None:
    """Нет зазора или радиуса — нечем судить, и молчание тут честнее догадки.

    Такой вольт свои проблемы объявит сам: недостающую константу поймает
    реестр, а бутстрап движка на ней падает.
    """
    doc = layout({"key": "terra.town", "parent": "terra", "place": {"lat": 40.0, "lon": 20.0}})
    assert world.check_spacing(doc, {}) == []
    assert world.check_spacing(doc, {"map.min_gap_m": 6}) == []
