# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Поле планеты собирается процессами и остаётся честным (90-production/12).

Что закреплено:

* одно зерно — одно поле, другое зерно — другое; сетка считается от радиуса
  и шага в метрах;
* уровень моря режет долю **площади**, а не клеток;
* у каждой клетки суши есть спуск к воде: приёмник ниже, сток кончается в
  море или в озере, площадь стока растёт вниз по течению;
* формы читаются кодами из таблицы, вода — водой;
* любимые фацеты провинции доезжают до паспорта поля;
* файл поля читается назад тем же полем.

Всё на крошечной сетке: конвейер один, шаг — число (план §4.1).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from field import census, forms, hydro, pipeline, store  # noqa: E402
from field.grid import Grid  # noqa: E402


def tiny(seed: int = 5, **overrides) -> pipeline.Params:
    base = dict(
        planet="terra", seed=seed, step_m=6000.0, radius_m=99_600.0, sea_share=0.6,
        relief_m=3000.0, plates=8, continental_share=0.5, river_area_km2=300.0,
        warm_c=35.0, cold_c=-15.0, lapse_per_km=6.5, ice_c=-8.0, ice_rain=0.25, ice_deep_c=-20.0,
        continental_c=5.0, continental_reach_r=0.5, climate_noise_c=3.0,
        climate_noise_km=20.0, wind_trade_lat=30.0, wind_westerly_lat=60.0, wind_edge_deg=8.0,
        dry_belt_wander_deg=8.0, rain_noise=0.3, dry_belt_lat=27.0, dry_belt_width=10.0, dry_belt_strength=0.4, version=1,
        coarse_factor=2, coarse_iterations=6, fine_iterations=2,
        provinces=(
            {"id": "ore_ridge", "rain_shift": -5.0, "temp_shift_c": -1.0, "vein_k": 1.8,
             "favours": ("scree", "crag")},
            {"id": "wet_ridge", "rain_shift": 18.0, "temp_shift_c": 0.0, "vein_k": 0.8,
             "favours": ()},
            {"id": "salt_wedge", "rain_shift": -20.0, "temp_shift_c": 3.0, "vein_k": 0.9,
             "favours": ()},
        ),
        rain_range=(0.0, 100.0),
        zones=(
            {"biome": "tundra", "temp": [-60.0, -2.0], "rain": [0.0, 100.0]},
            {"biome": "taiga", "temp": [-2.0, 5.0], "rain": [0.0, 100.0]},
            {"biome": "steppe", "temp": [5.0, 60.0], "rain": [0.0, 30.0]},
            {"biome": "forest", "temp": [5.0, 60.0], "rain": [30.0, 100.0]},
        ),
    )
    base.update(overrides)
    return pipeline.Params(**base)


def test_the_cell_is_the_same_everywhere_pole_and_equator() -> None:
    """То, ради чего сетка сменилась на HEALPix (D-328): клетка у полюса
    такая же, как на экваторе. У прежней сетки ширина клетки падала
    косинусом широты, и полюс приходилось лечить полом и сжатием."""
    grid = Grid.of(99_600.0, 500.0)
    assert grid.side_m == pytest.approx(500.0, rel=0.005)
    assert grid.count == 12 * grid.nside**2
    #: Расстояние до соседа — везде около стороны клетки, а не вдвое меньше
    #: у полюса: берётся десятая часть самых полярных клеток и весь экватор.
    polar = np.argsort(np.abs(grid.lat))[-grid.count // 10 :]
    belt = np.argsort(np.abs(grid.lat))[: grid.count // 10]
    for where in (polar, belt):
        real = np.where(grid.near[:, where] != where, grid.distances[:, where], np.nan)
        assert np.nanmin(real) > 0.5 * grid.side_m
        assert np.nanmax(real) < 2.0 * grid.side_m


def test_a_neighbour_is_a_gather_and_the_way_back_is_the_same_way() -> None:
    """`shift` на равноплощадной сетке — выборка по таблице соседей, а не
    прокрутка массива; и если А видит Б, то Б видит А, иначе сток течёт
    в клетку, которая о нём не знает."""
    grid = Grid.of(99_600.0, 12_000.0)
    a = np.arange(grid.count, dtype=float)
    for k in range(grid.near.shape[0]):
        assert np.array_equal(grid.shift(a, k), a[grid.near[k]])
    sets = [set(grid.near[:, p].tolist()) - {p} for p in range(grid.count)]
    for p, mine in enumerate(sets):
        assert all(p in sets[q] for q in mine)
    assert (grid.ways >= 7).all()


def test_the_slope_of_a_known_field_is_the_slope_it_should_be() -> None:
    """Наклон на сетке без строк и столбцов решается параболой по соседям.
    Поле `A·z` (`z` — та самая ось сферы) имеет известный градиент —
    `A·cos(широты)/R` на север и ноль на восток, — и известную кривизну.

    Мера тут не для красоты: у клеток на стыках базовых граней соседей
    девять, а не восемь, и плоскость по такому набору ловила кривизну поля
    в наклон — до 4 % ошибки на этих клетках при долях процента на всех
    остальных. Это шов по рёбрам граней той же природы, что полярная рябь,
    из-за которой сетку и меняли (D-328), и порог здесь стоит там, где
    парабола, а не там, где плоскость.
    """
    grid = Grid.of(99_600.0, 6_000.0)
    amplitude = 3_000.0
    height = amplitude * np.sin(np.radians(grid.lat))
    east, north = grid.gradient(height)
    want = amplitude * np.cos(np.radians(grid.lat)) / grid.radius_m
    assert np.abs(north - want).max() < 0.001 * np.abs(want).max()
    assert np.abs(east).max() < 0.001 * np.abs(want).max()
    #: Кривизна ровного поля — ноль, а не мусор на стыках граней; кривизна
    #: `A·z` на сфере — `-2A·z/R²`, в тех же долях, в каких её брала прежняя
    #: сетка средним по восьми соседям (`3/8` квадрата стороны).
    assert np.abs(grid.laplacian(np.full(grid.count, 7.0))).max() < 1e-9
    curve = 0.375 * grid.side_m**2 * (-2.0 * height / grid.radius_m**2)
    assert np.abs(grid.laplacian(height) - curve).max() < 0.01 * np.abs(curve).max()


def test_the_nearest_source_is_the_nearest_source() -> None:
    """Прыжковая заливка ищет ближайший источник шагами по сфере. Ответ
    сверяется перебором: на этой сетке он ещё по карману."""
    grid = Grid.of(99_600.0, 12_000.0)
    rng = np.random.default_rng(3)
    source = np.zeros(grid.count, dtype=bool)
    source[rng.choice(grid.count, size=12, replace=False)] = True
    _, metres = grid.nearest(source)
    seeds = grid.xyz[source]
    cosine = np.clip(grid.xyz @ seeds.T, -1.0, 1.0)
    honest = np.arccos(cosine).min(axis=1) * grid.radius_m
    assert np.abs(metres - honest).max() < 0.5 * grid.side_m
    #: Без единого источника — бесконечность, а не ближайший ноль.
    empty, far = grid.nearest(np.zeros(grid.count, dtype=bool))
    assert (empty < 0).all() and np.isinf(far).all()


def test_reading_from_a_coarser_grid_keeps_a_smooth_field_smooth() -> None:
    """Билинейки на HEALPix нет, и её место занимает вес по расстоянию:
    гладкое поле грубой сетки читается на тонкой без ступеней."""
    fine = Grid.of(99_600.0, 3_000.0)
    coarse = Grid.of(99_600.0, 12_000.0)
    #: Гладкое **на сфере**, а не на широте с долготой: `cos(долготы)` у
    #: полюса скачет от клетки к клетке и сглаживанию не подлежит нигде.
    aim = np.array([0.3, -0.5, 0.8])
    read = fine.resample_from(coarse.xyz @ aim, coarse)
    want = fine.xyz @ aim
    assert np.abs(read - want).max() < 0.02
    #: Постоянное поле остаётся постоянным: веса складываются в единицу.
    assert np.abs(fine.resample_from(np.full(coarse.count, 5.0), coarse) - 5.0).max() < 1e-9


def test_the_same_seed_builds_the_same_field_and_another_seed_another() -> None:
    one = pipeline.build(tiny())
    twin = pipeline.build(tiny())
    other = pipeline.build(tiny(seed=6))
    assert np.array_equal(one.height_m, twin.height_m) and np.array_equal(one.form, twin.form)
    assert not np.array_equal(one.height_m, other.height_m)


def test_the_sea_is_the_share_of_the_area_asked_for() -> None:
    r = pipeline.build(tiny())
    assert r.land_share() == pytest.approx(0.4, abs=0.03)
    assert float(r.height_m[r.sea].max()) < 0.0 and float(r.height_m[r.land].min()) >= 0.0
    assert 0.5 * r.params.relief_m < float(r.height_m.max()) <= r.params.relief_m * 1.05


def test_every_land_cell_drains_to_water() -> None:
    r = pipeline.build(tiny())
    flow = hydro.route(r.height_m, r.sea, r.grid)
    filled = flow.filled
    receiver = flow.receiver
    own = np.arange(receiver.size)
    lower = filled[receiver] <= filled[own]
    assert lower.all(), "приёмник не выше клетки"
    #: Клетка, которая никому не отдаёт воду и не вода сама, — пик стока
    #: посреди суши: у заливки таких нет.
    stuck = (receiver == own) & ~(r.sea | flow.lake)
    assert not stuck.any(), "у каждой клетки суши есть спуск"
    downstream = flow.area_m2[receiver] >= flow.area_m2
    assert downstream.all(), "площадь стока растёт вниз"
    assert (r.water == pipeline.WATER_RIVER).any(), "реки есть"


def test_forms_are_codes_of_the_table_and_water_is_water() -> None:
    r = pipeline.build(tiny())
    assert int(r.form.max()) < len(forms.FORMS)
    assert (r.form[r.sea] == forms.CODE["sea"]).all()
    lake = r.water == pipeline.WATER_LAKE
    assert (r.form[lake] == forms.CODE["lake"]).all()
    assert (r.form[r.land & ~lake] != forms.CODE["sea"]).all()
    rep = census.report(r)
    assert set(rep["forms"]) == {key for key, _, _ in forms.FORMS} - {"sea"}
    assert 0.0 <= rep["walk"]["form_changes_mean"]
    assert census.markdown(rep).startswith("### terra")


def test_provinces_cover_the_land_and_nothing_else() -> None:
    """Каждая клетка суши в какой-то провинции, ни одна клетка моря — ни в
    какой; провинций столько, сколько строк, и у каждой есть земля (план §7)."""
    r = pipeline.build(tiny())
    assert (r.province[r.sea] == 0).all()
    assert (r.province[r.land] > 0).all()
    assert [row["id"] for row in r.provinces] == ["ore_ridge", "wet_ridge", "salt_wedge"]
    for code in range(1, len(r.provinces) + 1):
        assert (r.province == code).any(), code
    #: Без строк — без провинций, и поле собирается всё равно.
    bare = pipeline.build(tiny(provinces=()))
    assert not bare.province.any() and bare.provinces == []


def test_the_file_reads_back_as_the_same_field(tmp_path: Path) -> None:
    r = pipeline.build(tiny())
    store.save(r, tmp_path)
    back = store.load(tmp_path, "terra")
    assert back.params == r.params
    assert np.allclose(back.height_m, r.height_m, atol=0.01)
    assert np.array_equal(back.form, r.form) and np.array_equal(back.water, r.water)
    assert np.array_equal(back.province, r.province) and back.provinces == r.provinces
    assert back.params.digest() == r.params.digest()
    #: Любимые фацеты провинции едут в паспорт (план §7, волна 8): игра берёт
    #: провинции оттуда, и список, потерянный здесь, молча ничего не делал бы.
    #: В самом файле это список — JSON кортежей не знает, — а прочитанное
    #: назад поле обязано быть равно исходному, поэтому кортеж возвращается.
    written = json.loads((tmp_path / "terra.json").read_text(encoding="utf-8"))
    assert written["provinces"][0]["favours"] == ["scree", "crag"]
    assert written["provinces"][1]["favours"] == []
    assert back.provinces[0]["favours"] == ("scree", "crag")
