# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Равноплощадная сетка HEALPix (D-328).

Проекцию нельзя брать на веру: она вся — целочисленная арифметика по
границам областей, и ошибка в ней не падает, а тихо кладёт клетки не туда.
Что закреплено:

* клеток ровно `12 nside²`, и каждая — своя: середина клетки попадает в
  саму клетку, а разные клетки не сливаются;
* **площадь клеток равна** — это единственное, ради чего сетка выбрана, и
  меряется она броском точек по сфере, а не формулой из того же кода;
* **`nside` любое целое**, не только степень двойки: степень двойки нужна
  вложенной нумерации, которой мы не пользуемся (D-328), и тесты идут по
  нечётным и простым `nside` наравне со степенями двойки;
* соседи взаимны, их восемь, и до них одна клетка — а где не восемь,
  там сказано, почему;
* дробность выводится из общего шага вольта, а не задаётся планете.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from field import healpix  # noqa: E402

#: Терра, Пироксис, Аврора и одна нечётная для придирки.
NSIDES = (1, 2, 3, 7, 8, 13, 118, 148, 256)
TERRA_R = 99_546.875


def test_the_count_is_twelve_squares_and_every_cell_is_its_own() -> None:
    for nside in (1, 2, 3, 7, 13):
        count = healpix.npix(nside)
        assert count == 12 * nside * nside
        lat, lon = healpix.centres(nside)
        #: Середина клетки лежит в самой клетке — иначе проекция и её
        #: обратная разошлись, и ни одно чтение поля не попадёт куда надо.
        back = healpix.ang2pix(nside, lat, lon)
        assert np.array_equal(back, np.arange(count))


@pytest.mark.parametrize("nside", NSIDES)
def test_any_point_of_the_sphere_lands_in_a_cell(nside: int) -> None:
    """Ни одна точка не остаётся без клетки и не выпадает за край: полюса,
    линия даты и стыки граней — там, где целочисленная арифметика ошибается."""
    rng = np.random.default_rng(7)
    lat = np.degrees(np.arcsin(rng.uniform(-1.0, 1.0, 4000)))
    lon = rng.uniform(-180.0, 180.0, 4000)
    edge_lat = np.array([-90.0, 90.0, 0.0, 0.0, 41.81, -41.81, 89.999, -89.999])
    edge_lon = np.array([0.0, 0.0, -180.0, 180.0, 45.0, -45.0, 179.999, -179.999])
    pix = healpix.ang2pix(nside, np.r_[lat, edge_lat], np.r_[lon, edge_lon])
    assert pix.min() >= 0
    assert pix.max() < healpix.npix(nside)


@pytest.mark.parametrize("nside", (3, 8, 13))
def test_the_cells_are_equal_in_area(nside: int) -> None:
    """Бросок равномерных по сфере точек: в равноплощадной сетке каждая
    клетка ловит их одинаково часто. Меряется броском, а не формулой из
    того же кода, иначе тест проверял бы сам себя."""
    count = healpix.npix(nside)
    rng = np.random.default_rng(11)
    many = 400 * count
    lat = np.degrees(np.arcsin(rng.uniform(-1.0, 1.0, many)))
    lon = rng.uniform(-180.0, 180.0, many)
    hits = np.bincount(healpix.ang2pix(nside, lat, lon), minlength=count)
    assert hits.min() > 0
    #: При четырёхстах бросках на клетку разброс ±5σ это около 0,25.
    assert abs(hits.mean() - many / count) < 1e-9 + many / count * 0.01
    assert hits.max() / hits.mean() < 1.3
    assert hits.min() / hits.mean() > 0.7


def test_the_side_of_a_cell_is_the_step_the_vault_asks_for() -> None:
    """Дробность выводится из общего шага, и обратно сходится: это и есть
    правило «у всех планет одинаковый размер ячейки» (D-328)."""
    for radius, nside, side in (
        (99_546.875, 256, 397.9),
        (57_473.415, 148, 397.4),
        (140_780.541, 362, 398.0),
    ):
        assert healpix.nside_for(radius, 398.0) == nside
        assert healpix.cell_side_m(radius, nside) == pytest.approx(side, abs=0.1)
    #: Клетка у всех трёх одна с точностью до одной шестой процента.
    sides = [
        healpix.cell_side_m(r, healpix.nside_for(r, 398.0))
        for r in (99_546.875, 57_473.415, 140_780.541)
    ]
    assert max(sides) / min(sides) - 1 < 0.002


@pytest.mark.parametrize("nside", (3, 8, 13, 32))
def test_the_neighbours_are_mutual_and_a_cell_away(nside: int) -> None:
    """Сосед соседа — я сам. Несимметричная таблица соседей сделала бы сток
    односторонним: вода утекала бы в клетку, которая о ней не знает."""
    near = healpix.neighbours(nside, TERRA_R)
    count = healpix.npix(nside)
    assert near.shape == (healpix.WAYS, count)
    assert near.min() >= 0 and near.max() < count
    sets = [set(near[:, p]) - {p} for p in range(count)]
    for p in range(count):
        for q in sets[p]:
            assert p in sets[q], f"{p} считает соседом {q}, а {q} его — нет"
    #: Соседей у клетки восемь — четыре через ребро и четыре через угол.
    #: Меньше восьми только у восьми угловых клеток базовых граней, где
    #: сходятся три грани; больше восьми даёт объединение с обратной
    #: стороной у клеток на стыках, и мест под них отведено с запасом.
    #: Замер: ровно восемь у 85 % клеток при nside 3 и у 96 % при nside 64 —
    #: чем дробнее сетка, тем меньше в ней стыков на клетку.
    counts = np.array([len(one) for one in sets])
    assert counts.min() >= 7
    assert counts.max() <= healpix.WAYS
    assert (counts == 8).mean() > 0.8, f"восьмёрок только {(counts == 8).mean():.0%}"


@pytest.mark.parametrize("nside", (8, 13))
def test_a_neighbour_stands_about_a_cell_off(nside: int) -> None:
    """Ни один «сосед» не оказывается на другом конце планеты: шаг по сфере
    ищет соседа, а не первую попавшуюся клетку."""
    near = healpix.neighbours(nside, TERRA_R)
    lat, lon = healpix.centres(nside)
    side = healpix.cell_side_m(TERRA_R, nside)
    one = np.stack(
        [
            np.cos(np.radians(lat)) * np.cos(np.radians(lon)),
            np.cos(np.radians(lat)) * np.sin(np.radians(lon)),
            np.sin(np.radians(lat)),
        ]
    )
    for k in range(healpix.WAYS):
        other = one[:, near[k]]
        cosine = np.clip((one * other).sum(axis=0), -1.0, 1.0)
        metres = TERRA_R * np.arccos(cosine)
        assert metres.max() < 2.5 * side, f"сторона {k}: сосед в {metres.max():.0f} м"


def test_the_grid_holds_at_a_prime_nside() -> None:
    """Отдельно и нарочно: 13 — не степень двойки и вообще простое. Если
    где-то в проекции остался сдвиг битов вместо деления, ляжет здесь."""
    nside = 13
    count = healpix.npix(nside)
    lat, lon = healpix.centres(nside)
    assert np.array_equal(healpix.ang2pix(nside, lat, lon), np.arange(count))
    #: И площади всё так же равны.
    rng = np.random.default_rng(3)
    many = 300 * count
    hits = np.bincount(
        healpix.ang2pix(
            nside,
            np.degrees(np.arcsin(rng.uniform(-1.0, 1.0, many))),
            rng.uniform(-180.0, 180.0, many),
        ),
        minlength=count,
    )
    assert hits.max() / hits.mean() < 1.3


def test_the_rings_are_rings_of_one_latitude() -> None:
    """Клетки лежат кольцами равной широты — на этом стоит марш влаги по
    поясам (§4.2), и это то, чего нет у икосферы."""
    nside = 8
    lat, _ = healpix.centres(nside)
    rings = np.unique(np.round(lat, 6))
    #: Колец ровно `4 nside - 1`, как обещает статья.
    assert len(rings) == 4 * nside - 1
