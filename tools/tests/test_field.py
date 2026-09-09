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
* файл поля читается назад тем же полем.

Всё на крошечной сетке: конвейер один, шаг — число (план §4.1).
"""

from __future__ import annotations

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
        relief_m=3000.0, plates=8, continental_share=0.5, river_area_km2=20.0,
        warm_c=35.0, cold_c=-15.0, lapse_per_km=6.5, ice_c=-8.0, ice_rain=0.25, ice_deep_c=-20.0,
        continental_c=5.0, continental_reach_r=0.5, climate_noise_c=3.0,
        climate_noise_km=20.0, wind_trade_lat=30.0, wind_westerly_lat=60.0, wind_edge_deg=8.0,
        dry_belt_wander_deg=8.0, rain_noise=0.3, dry_belt_lat=27.0, dry_belt_width=10.0, dry_belt_strength=0.4, version=1,
        coarse_factor=2, coarse_iterations=6, fine_iterations=2,
        provinces=(
            {"id": "ore_ridge", "rain_shift": -5.0, "temp_shift_c": -1.0, "vein_k": 1.8},
            {"id": "wet_ridge", "rain_shift": 18.0, "temp_shift_c": 0.0, "vein_k": 0.8},
            {"id": "salt_wedge", "rain_shift": -20.0, "temp_shift_c": 3.0, "vein_k": 0.9},
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


def test_grid_is_metres_and_wraps() -> None:
    grid = Grid.of(99_600.0, 500.0)
    assert grid.rows == round(np.pi * 99_600.0 / 500.0) and grid.cols == 2 * grid.rows
    assert grid.dx[grid.rows // 2] == pytest.approx(500.0, rel=1e-3)
    assert grid.dx[0] < grid.dx[grid.rows // 2], "у полюса клетка уже"
    a = np.arange(grid.rows * grid.cols, dtype=float).reshape(grid.rows, grid.cols)
    east = grid.shift(a, 0, 1)
    assert east[0, -1] == a[0, 0], "по долготе сетка замкнута"
    north = grid.shift(a, 1, 0)
    assert north[-1, 0] == a[-1, 0], "через полюс ничего не течёт: край повторяет себя"


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
    filled = flow.filled.ravel()
    receiver = flow.receiver
    own = np.arange(receiver.size)
    lower = filled[receiver] <= filled[own]
    assert lower.all(), "приёмник не выше клетки"
    #: Клетка, которая никому не отдаёт воду и не вода сама, — пик стока
    #: посреди суши: у заливки таких нет.
    stuck = (receiver == own) & ~(r.sea | flow.lake).ravel()
    assert not stuck.any(), "у каждой клетки суши есть спуск"
    downstream = flow.area_m2.ravel()[receiver] >= flow.area_m2.ravel()
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
