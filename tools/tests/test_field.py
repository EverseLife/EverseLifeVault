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
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from field import census, erosion, forms, hydro, pipeline, store  # noqa: E402
from field.grid import Grid  # noqa: E402


def tiny(seed: int = 5, *, temp_hot: bool = False, **overrides) -> pipeline.Params:
    """`temp_hot` — тот же мир, но раскалённый: края температур выше порога
    `lava_c`, чтобы проверить лаву, не трогая ничего другого."""
    base = dict(
        planet="terra", seed=seed, step_m=6000.0, radius_m=99_600.0, sea_level=0.55,
        relief_m=3000.0, plates=8, continental_share=0.5, river_area_km2=300.0,
        warm_c=120.0 if temp_hot else 35.0, cold_c=70.0 if temp_hot else -15.0, lapse_per_km=6.5, ice_c=-8.0, ice_cap_c=-8.0, ice_rain=0.25, ice_deep_c=-20.0,
        continental_c=5.0, continental_reach_r=0.5, climate_noise_c=3.0,
        valley_depth_m=30.0, valley_width_m=600.0,
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


def test_the_sea_stands_at_its_level_and_the_land_is_what_is_left() -> None:
    """Доля суши — следствие уровня океана, а не заданное число (D-329).

    Прежде задавалась доля моря, и уровень подбирался под неё квантилем:
    сколько бы рельефа ни выросло, воды выходило ровно столько, сколько
    сказано. Проверять там было нечего — ответ был во входных данных. Теперь
    вода стоит на отметке, и проверять надо ровно то, что из этого следует:
    **поднял воду — суши стало меньше**, и нигде не наоборот.
    """
    r = pipeline.build(tiny())
    assert float(r.height_m[r.sea].max()) < 0.0 and float(r.height_m[r.land].min()) >= 0.0
    assert 0.5 * r.params.relief_m < float(r.height_m.max()) <= r.params.relief_m * 1.05
    #: Монотонность: между «вся суша» и «весь океан» доля суши только убывает.
    shares = [pipeline.build(tiny(sea_level=level)).land_share() for level in (0.35, 0.55, 0.75)]
    assert shares[0] > shares[1] > shares[2], f"суша не убывает с уровнем: {shares}"
    assert shares[0] > 0.6 and shares[2] < 0.3, f"уровень ничего не решает: {shares}"


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


def _hill(grid: Grid) -> np.ndarray:
    """Гладкая гора и ложбина рядом: у поля есть что терять, и потеря видна."""
    return 1000.0 + 800.0 * np.sin(np.radians(3.0 * grid.lat)) * np.cos(
        np.radians(3.0 * grid.lon)
    )


#: Длина оплывания, при которой на здешней клетке в 50 м схема **обязана**
#: дробить: та самая, что стояла в конвейере до ужатия планет. Берётся здесь
#: явно, а не из `erosion.DIFFUSION_STEP_M`, потому что рабочее значение
#: ходит вместе с размером планет: при 125 м на этой клетке `kd` выходит 0,54
#: — под пределом оператора, — и тест, взяв его, молча перестал бы сторожить
#: то, ради чего написан.
SLUMP_STEP_M = 500.0


def _slumped(grid: Grid, height: np.ndarray, cap: float) -> np.ndarray:
    """Та же гора, оплывшая на этой сетке при этом пределе шага."""
    was, was_step = erosion.DIFFUSION_MAX, erosion.DIFFUSION_STEP_M
    erosion.DIFFUSION_MAX = cap
    erosion.DIFFUSION_STEP_M = SLUMP_STEP_M
    try:
        return erosion.erode(
            height,
            np.zeros(grid.count, dtype=bool),
            grid,
            #: Самая мягкая порода: у неё наибольшее `kd`, ей и проверять.
            hardness=np.full(grid.count, 0.25),
            #: Без поднятия: проверяется оплывание, а не то, чем его чинят.
            uplift=np.zeros(grid.count),
            relief_m=3000.0,
            iterations=4,
            temperature=lambda h: np.full(grid.count, 20.0),
            ice_c=-8.0,
        ).height
    finally:
        erosion.DIFFUSION_MAX = was
        erosion.DIFFUSION_STEP_M = was_step


def test_green_grows_only_where_it_could(tmp_path: Path) -> None:
    """Растительность — свой растр, и он молчит там, где расти нечему (D-329).

    Зелёный цвет на карте берётся теперь только отсюда, поэтому проверять
    надо не картинку, а покров: на воде, подо льдом и на лаве его нет, вне
    полосы тепла его нет, а внутри неё он есть — иначе «зелень только у
    растительности» означало бы «зелени нет вовсе».
    """
    warm = pipeline.build(tiny(seed=11))
    green = warm.plants
    assert ((green >= 0.0) & (green <= 1.0)).all(), "покров — доля, а не что попало"
    assert green.max() > 0.2, "на земном мире обязана быть зелень"
    assert not (green[warm.water != pipeline.WATER_LAND] > 0).any(), "зелень на воде"
    assert not (green[warm.ice] > 0).any(), "зелень подо льдом"
    #: Полоса тепла — не украшение: мир, целиком лежащий за ней, гол.
    frozen = pipeline.build(tiny(seed=11, plant_warm_c=-40.0, plant_cold_c=-80.0))
    assert not (frozen.plants > 0).any(), "зелень вне полосы тепла"
    #: И покров переживает запись в файл: он едет байтом на клетку.
    store.save(warm, tmp_path)
    back = store.load(tmp_path, warm.params.planet)
    assert np.abs(back.plants - green).max() <= 1.0 / 255.0


def test_no_open_water_under_the_ice_cap() -> None:
    """Растры воды и льда не спорят друг с другом (D-329).

    Клетка не бывает разом рекой и ледяным полем: шейдер рисует по льду,
    векторный слой — по воде, и на одном месте выходили две разные земли.
    На собранной Терре таких было 225. Ледник реку кормит, но она выходит
    **из-под** него, а не течёт по нему, и спор решён в пользу льда — как в
    игре, где биом читает `ice` прежде всего остального.
    """
    r = pipeline.build(tiny(seed=11))
    ice, water = r.ice, r.water
    assert ice.any(), "мир без единой шапки эту проверку не проверяет"
    assert not (ice & (water == pipeline.WATER_RIVER)).any(), "река под шапкой"
    assert not (ice & (water == pipeline.WATER_LAKE)).any(), "озеро под шапкой"


def test_lava_flows_from_cones_on_a_hot_planet_and_nowhere_on_a_cold_one() -> None:
    """Лава — язык от жерла, а не сеть (D-329).

    Два условия, и тест держит оба порознь. **Конус**: клетка лавы обязана
    иметь вулкан выше по склону, иначе это река, покрашенная в оранжевый, —
    ровно то, чем лава была, пока её гнали через водосбор. **Жара**: та же
    планета с тем же зерном и теми же вулканами, но холодная, не даёт ни
    одной клетки — «на терре тоже будут вулканы, но они там без лавовых рек».
    """
    #: Досягаемость — **десятки клеток этой сетки**, а не метры настоящего
    #: мира: у `tiny` клетка в шесть километров, и при реестровых 0,6 км
    #: проход делал ровно ноль шагов. Тест тогда сходился тождественно —
    #: множество лавы совпадало с множеством конусов побитно, — и не держал
    #: ни спуск по приёмнику, ни порог жары, ни длину языка.
    reach_km = 30.0
    hot = pipeline.build(tiny(fluid="lava", volcanoes=12.0, temp_hot=True, lava_reach_km=reach_km))
    cold = pipeline.build(tiny(fluid="lava", volcanoes=12.0, lava_reach_km=reach_km))
    lava_hot = (hot.water == pipeline.WATER_RIVER) | (hot.water == pipeline.WATER_LAKE)
    lava_cold = (cold.water == pipeline.WATER_RIVER) | (cold.water == pipeline.WATER_LAKE)
    assert lava_hot.any(), "жаркая лавовая планета обязана течь"
    assert not lava_cold.any(), "на холодной земле лава застывает в жерле"
    #: Язык **длиннее жерла**: иначе всё, что ниже, проверяет один конус.
    cone = hot.form == forms.CODE["volcano"]
    assert (lava_hot & ~cone).any(), "лава никуда не дотекла — это не язык, а жерло"
    #: И он начинается у конуса, не дальше досягаемости **в метрах**: путь
    #: по склону не короче прямой, так что прямая обязана уложиться в неё.
    #: Считалось это шагами, и диагональный шаг уводил язык за предел в
    #: полтора раза — при заявленных двенадцати клетках выходило пятнадцать.
    steps = hot.grid.cells_for_metres(reach_km * 1000.0)
    assert steps > 1, "сетка теста обязана давать проходу хотя бы два шага"
    straight = hot.grid.dilate_distance(cone, steps + 4) * hot.grid.side_m
    assert (straight[lava_hot] <= reach_km * 1000.0).all(), (
        "лава течёт не от вулкана либо дальше положенного"
    )


def test_the_slope_slumps_and_does_not_go_off_however_fine_the_cell() -> None:
    """Оплывание дробится по устойчивости, и от дробности сетки не зависит.

    Коэффициент диффузии растёт квадратом дробности сетки, а шаг у явной
    схемы один: на клетке в 398 м самая мягкая порода давала 0,54 при пределе
    оператора 0,74, на клетке в 50 м — 12,35. Схема пошла вразнос, а
    `maximum(h, 0)` в конце итерации дожал качели в ноль: Терра и Пироксис
    собрались плоскими, медиана высоты 0 при размахе 1060 м. Тесты этого не
    увидели, потому что у здешней сетки шаг 6000 м — ни один прогон ни разу
    не подходил к пределу. Здесь шаг взят такой, при котором подходит.
    """
    #: Шар нарочно мал, а клетка — та самая, что теперь у планет: дробность
    #: сетки настоящая, клеток мало, тест быстрый.
    fine = Grid.of(2_000.0, 50.0)
    #: Дробление и вправду нужно: иначе тест сторожил бы пустое место.
    scale = (SLUMP_STEP_M / fine.side_m) ** 2
    assert erosion.DIFFUSION * scale / 0.25 > erosion.DIFFUSION_MAX

    hill = _hill(fine)
    slumped = _slumped(fine, hill, erosion.DIFFUSION_MAX)
    #: Оплывание **сглаживает**: размах падает, но гора остаётся горой.
    assert np.ptp(slumped) < np.ptp(hill)
    assert np.ptp(slumped) > np.ptp(hill) / 2

    #: И от числа частей выходит **та же земля**. Не та же клетка в клетку:
    #: диффузия линейна и по числу частей не зависит вовсе, но за ней в той
    #: же итерации идут три нелинейных процесса — врез, осадок, поднятие, — и
    #: сток, отвечая на разницу в сантиметр, изредка перекладывает русло. Это
    #: не сходится и сходиться не будет: расхождение стоит около процента
    #: размаха при любом более мелком шаге (замер: 1,16 % против половины,
    #: 1,17 % против четверти, 1,18 % против восьмушки).
    #:
    #: Держать надо то, что от этого не зависит, — и оно не зависит хорошо:
    #: размах, медиана и квантили совпадают до сотых долей процента, половина
    #: клеток расходится меньше чем на пятнадцать сантиметров, и лишь у двух
    #: процентов расхождение переваливает за метр.
    finer = _slumped(fine, hill, erosion.DIFFUSION_MAX / 2)
    span = np.ptp(slumped)
    assert abs(np.ptp(finer) - span) < 0.005 * span
    assert abs(np.median(finer) - np.median(slumped)) < 0.005 * span
    apart = np.abs(slumped - finer)
    assert np.median(apart) < 0.001 * span
    assert np.mean(apart > 0.01 * span) < 0.05

    #: А одним шагом сглаживание **раздувает** поле: размах выходит больше
    #: того, с которого начали. Оператор, обязанный ровнять, делает круче —
    #: подпись расхождения, и ровно она стояла за плоскими планетами.
    assert np.ptp(_slumped(fine, hill, 1.0e9)) > np.ptp(hill)


def test_the_river_ribbon_is_half_gone_at_its_bank():
    """Клиент режет ленту по половине доли — значит на берегу её ровно половина.

    Мера записи и порог чтения — одна пара, и порознь их менять нельзя.
    Конвейер считал долю от **половины** ширины, клиент резал по половине
    доли, — и нож вставал на четверть: лента выходила вдвое уже объявленной,
    у всех рек, кроме самых больших, закрашивалось само русло. На картинке
    это читается как «реки поуже», а не как «правило не то», и глазом поймано
    не было — поэтому сторожится арифметикой.

    Порог 0,5 живёт в шейдере другого репозитория, и общего кода у сторон
    нет: сверяются они этим тестом и парным ему на клиенте.
    """
    #: Самая широкая река (`terrain.river_wide_m`): в русле её мера ещё не
    #: упирается в единицу, и склон виден целиком.
    width = 120.0
    ramp = pipeline.STREAM_RAMP_M
    #: Берег: ровно половина, то есть под ножом.
    assert pipeline.ribbon(width / 2, width) == pytest.approx(0.5)
    #: В русле — выше половины, и настолько, насколько склон полог: мера
    #: ленты — расстояние до берега на склоне `STREAM_RAMP_M`, а не доля
    #: ширины. Крутой склон (единица в русле, ноль на ширине) между двумя
    #: клетками русла по диагонали проваливался до половины, и лента шла
    #: чётками.
    assert pipeline.ribbon(0.0, width) == pytest.approx(0.5 + width / 2 / ramp)
    assert pipeline.ribbon(width / 4, width) == pytest.approx(0.5 + width / 4 / ramp)
    #: За берегом — ниже половины на ту же меру, до нуля в полусклоне от него.
    assert pipeline.ribbon(width, width) == pytest.approx(0.5 - width / 2 / ramp)
    assert pipeline.ribbon(width / 2 + ramp / 2, width) == 0.0
    assert pipeline.ribbon(width / 2 + ramp, width) == 0.0
    #: Боковая клетка диагонального плёса (35 м от линии при клетке 50)
    #: — за берегом 60-метровой реки, но чуть: клиент режет между клетками,
    #: и от этого «чуть» зависит, что лента не пережимается.
    assert 0.45 < pipeline.ribbon(50.0 / np.sqrt(2.0), 60.0) < 0.5
    #: Ширина нулевой не бывает, но делить на неё всё равно нельзя.
    assert pipeline.ribbon(1.0, 0.0) < 0.5


def test_a_confluence_takes_a_share_of_the_sum_and_never_narrows():
    """Правило владельца и оговорка, без которой оно съедает само себя.

    «Если две реки вливаются в одну, то ширина получившейся — не сумма ширин
    входящих, а сумма ширин на 0,5» (2026-09-11). Буквально по клеткам это
    свело бы всякую реку к нулю: у клетки реки впадающая чаще всего одна, и
    половина от одной ширины — половина реки на каждом шаге вниз.
    """
    from field import hydro

    #: Цепочка из шести клеток: 0 → 1 → 2 ← 3, 2 → 4 → 5. Две равные ветви
    #: (0 и 3) сливаются в клетке 2, дальше одно русло.
    receiver = np.array([1, 2, 4, 2, 5, 5])
    #: Сверху вниз: сперва истоки, потом то, во что они впадают.
    order = np.array([0, 3, 1, 2, 4, 5])
    flow = hydro.Flow(
        filled=np.zeros(6), receiver=receiver, order=order,
        slope=np.zeros(6), distance=np.full(6, 50.0),
        area_m2=np.zeros(6), lake=np.zeros(6, dtype=bool),
    )
    river = np.ones(6, dtype=bool)
    width = hydro.widths(flow, river, narrow_m=60.0, wide_m=200.0, merge=0.5)

    #: Исток — по полу.
    assert width[0] == 60.0 and width[3] == 60.0
    #: Одна впадающая: русло несёт свою ширину дальше, а не половину её.
    assert width[1] == 60.0
    #: Две равные: половина суммы, то есть та же ширина. Ровно правило.
    assert width[2] == pytest.approx(0.5 * (width[1] + width[3]))
    #: И ниже слияния река не сужается никогда.
    assert width[4] >= width[2] and width[5] >= width[4]


def test_a_confluence_of_three_widens_and_the_ceiling_holds():
    """Трём равным долей суммы достаётся полтора, и это единственное место,
    где ширина вообще растёт; выше потолка она не идёт."""
    from field import hydro

    #: Три истока (0, 1, 2) в одну клетку 3, дальше 4.
    receiver = np.array([3, 3, 3, 4, 4])
    order = np.array([0, 1, 2, 3, 4])
    flow = hydro.Flow(
        filled=np.zeros(5), receiver=receiver, order=order,
        slope=np.zeros(5), distance=np.full(5, 50.0),
        area_m2=np.zeros(5), lake=np.zeros(5, dtype=bool),
    )
    river = np.ones(5, dtype=bool)
    width = hydro.widths(flow, river, narrow_m=60.0, wide_m=200.0, merge=0.5)
    assert width[3] == pytest.approx(90.0), "половина от трёх шестидесяток"

    #: Потолок режет там, где доля суммы его переросла.
    tight = hydro.widths(flow, river, narrow_m=60.0, wide_m=80.0, merge=0.5)
    assert tight[3] == 80.0


def test_capture_on_a_filled_flat_keeps_every_link_going_down():
    """На залитом дне уровни идут ступенями по `FILL_EPS` от берега, и цель
    захвата стоит на ступень-другую ниже в нескольких шагах: перепада на
    лестницу перемычки может не хватить. Лестница, ушедшая под цель,
    последним звеном шла бы **вверх** — и рушила бы всё, что держится на
    «каждое звено строго ниже»: порядок накопления, отсутствие колец,
    прорез в высоту. Такой захват не берётся.
    """
    from field import hydro

    params = tiny(seed=3)
    grid = pipeline.Grid.of(params.radius_m, params.step_m)
    #: Ровная суша на полметра над морем: заливка кладёт на неё лестницу
    #: по `FILL_EPS` от берега, и весь сток идёт по этим ступеням.
    sea = grid.lat < -70.0
    height = np.where(sea, -1.0, 0.5)
    flow = hydro.route(height, sea, grid, capture_m2=3 * grid.area_m2, capture_reach_cells=5)
    flat = np.arange(grid.count)
    donors = flat[flow.receiver != flat]
    assert (flow.filled[flow.receiver[donors]] < flow.filled[donors]).all(), "звено вверх"
    assert (flow.slope[donors] > 0.0).all()
    step = flow.receiver.copy()
    for _ in range(grid.count.bit_length() + 1):
        step = step[step]
    assert (flow.receiver[step] == step).all(), "кольцо в стоке"
    position = np.empty(grid.count, dtype=int)
    position[flow.order] = flat
    assert (position[donors] < position[flow.receiver[donors]]).all()


def test_the_convergence_spreads_from_the_boundary_without_steps():
    """Схождение по плите не прыгает ступенями между соседями
    (`plates.CONVERGENCE_BLUR`): `spread` кроит плиту на области Вороного
    клеток границы, и без размытия швы между областями были ступенями в
    высоте — прямыми по решётке (владелец 2026-09-11: «ромбы»). Мера —
    худшая сотая доля шагов между соседями против размаха схождения; числа
    с размытием и без — у `CONVERGENCE_BLUR`.
    """
    from field import plates

    params = tiny(seed=3)
    grid = pipeline.Grid.of(params.radius_m, params.step_m)
    tect = plates.build(
        grid, params.seed, params.plates, params.continental_share, params.sea_level,
        volcanoes=params.volcanoes,
    )
    conv = tect.convergence
    live = np.abs(conv) > 1e-9
    span = float(np.percentile(np.abs(conv[live]), 95))
    assert span > 0.0
    steps = []
    for k in range(pipeline.WAYS):
        near = grid.near[k]
        both = live & live[near]
        steps.append(np.abs(conv[both] - conv[near][both]))
    worst = float(np.percentile(np.concatenate(steps), 99))
    assert worst < 0.5 * span, f"ступень схождения {worst:.3f} при размахе {span:.3f}"


def test_the_shore_keeps_the_slope_of_the_base_on_both_sides():
    """У кромки моря высота сводится к профилю основы (`_shore_by_base`):
    один масштаб с обеих сторон, чтобы ноль между клетками стоял там, где
    основа пересекает уровень; знак у клетки тот же, что говорит маска.
    """
    grid = Grid.of(99_600.0, 3_000.0)
    #: Основа — плавный склон по широте, море — южнее нуля.
    base = grid.lat / 90.0
    _, sea = pipeline._to_metres(base, 0.0, 1000.0, grid)
    profile = pipeline._shore_profile(base, 0.0, 1000.0)
    #: Профиль симметричен: склон один по обе стороны уровня.
    assert profile[sea].min() == pytest.approx(-profile[~sea].max(), rel=0.05)
    #: Эрозия «сплющила» всё: суша на полуметре, море на минус десяти.
    flat = np.where(sea, -10.0, 0.5)
    out = pipeline._shore_by_base(flat, profile, sea, grid)
    #: Знак не тронут: море под нулём; суша не ниже нуля (клетка ровно на
    #: уровне, как экватор этого склона, стоит на нуле и остаётся сушей).
    assert (out[sea] < 0).all() and (out[~sea] >= 0).all()
    #: Первая клетка от кромки — профиль целиком, с обеих сторон.
    first_land = (~sea) & (grid.dilate_distance(sea, 3) < 1.5)
    first_sea = sea & (grid.dilate_distance(~sea, 3) < 1.5)
    assert np.allclose(out[first_land], profile[first_land])
    assert np.allclose(out[first_sea], profile[first_sea])
    #: Вдали от кромки — как было.
    far = grid.dilate_distance(sea, 3) >= 3.0
    assert np.array_equal(out[far & ~sea], flat[far & ~sea])
    #: Насыпная кромка (`pipeline.FRINGE_BLUR`): клетки моря у самой
    #: кромки, которые эрозия подняла выше нуля, стали сушей. Основа у них
    #: под уровнем, и профиль основы им не годится — сведённые к нему, они
    #: тонули (на Терре так уходили под воду восемь тысяч клеток суши).
    laid = first_sea
    sea_now = sea & ~laid
    flat_now = np.where(sea_now, -10.0, 0.5)
    out_now = pipeline._shore_by_base(flat_now, profile, sea_now, grid)
    assert (out_now[~sea_now] >= 0).all(), "суша ушла под воду"
    assert (out_now[sea_now] < 0).all()
    #: Насыпь стоит над нулём, и не полкой эрозии, а фронтом класса.
    assert (out_now[laid] > 0).all()
    assert not np.allclose(out_now[laid], flat_now[laid])
    #: Фронт симметричен: первая клетка моря за насыпью под нулём на
    #: столько же, на сколько насыпь над ним, — ноль между ними посередине.
    sea_first_now = sea_now & (grid.dilate_distance(~sea_now, 3) < 1.5)
    assert np.median(-out_now[sea_first_now]) == pytest.approx(np.median(out_now[laid]), rel=0.5)


def _staircase(grid, start, steps):
    """Русло лестницей по решётке: от `start` шаг на восток, шаг на север и
    так `steps` раз; возвращает клетки цепи и приёмники."""
    cells = [int(start)]
    for step in range(steps):
        here = cells[-1]
        near = grid.near[:, here]
        lat, lon = grid.lat[near], grid.lon[near]
        pick = int(near[np.argmax(lon)]) if step % 2 == 0 else int(near[np.argmax(lat)])
        cells.append(pick)
    receiver = np.arange(grid.count)
    for a, b in pairwise(cells):
        receiver[a] = b
    return cells, receiver


def test_the_channel_line_is_smoothed_between_its_cells():
    """Ломаная русла сглажена (`hydro.smooth_channel`, `CHANNEL_SMOOTH`):
    лестница по решётке идёт дугой, её точки ближе к прямой между концами,
    чем середины клеток, и клетки не-реки стоят где стояли. Владелец
    2026-09-12: река на ближнем кадре шла коленом.
    """
    grid = Grid.of(99_600.0, 3_000.0)
    start = int(np.argmin(np.abs(grid.lat) + np.abs(grid.lon)))
    cells, receiver = _staircase(grid, start, 10)
    river = np.zeros(grid.count, dtype=bool)
    river[cells] = True
    carried = np.zeros(grid.count)
    carried[cells] = np.arange(1, len(cells) + 1, dtype=float)
    points = hydro.smooth_channel(grid, river, receiver, carried)
    #: Прочие клетки — как были.
    assert np.array_equal(points[~river], grid.xyz[~river])
    #: Излом в вершинах: угол между звеном к вершине и звеном от неё, у
    #: середин клеток и у сглаженных точек. Лестница ломается на прямой
    #: угол в каждой вершине; дуга — на малый.
    def turning(q):
        p = q[cells]
        a = p[1:-1] - p[:-2]
        b = p[2:] - p[1:-1]
        cos = (a * b).sum(axis=1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))
        return np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))).mean()

    before = turning(grid.xyz)
    after = turning(points)
    assert before > 45.0, before
    assert after < 0.5 * before, (before, after)
    inner = cells[1:-1]
    #: И вершины ушли недалеко: угол лестницы срезается на четверть
    #: диагонали за раунд, два раунда — около половины клетки, не больше
    #: трёх четвертей.
    moved = np.linalg.norm(points[inner] - grid.xyz[inner], axis=1) * grid.radius_m
    assert moved.max() < 0.75 * grid.side_m


def test_a_river_carves_its_valley_by_its_flow():
    """Долина реки (`pipeline._carve_valleys`, D-331): русло опущено на долю
    глубины по корню из расхода, земля рядом — по параболе до края долины,
    дальше нетронута, и ничто не ниже трети своей высоты.
    """
    grid = Grid.of(99_600.0, 3_000.0)
    start = int(np.argmin(np.abs(grid.lat) + np.abs(grid.lon)))
    cells, _ = _staircase(grid, start, 12)
    land = np.ones(grid.count, dtype=bool)
    height = np.full(grid.count, 100.0)
    carried = np.zeros(grid.count)
    carried[cells] = np.linspace(0.25, 1.0, len(cells)) * 1e9
    params = tiny(valley_depth_m=40.0, valley_width_m=9_000.0, river_area_km2=0.1)
    no_lake = np.zeros(grid.count, dtype=bool)
    out = pipeline._carve_valleys(height, grid, land, no_lake, carried, params)
    #: Русло: самая полноводная клетка на всю глубину, исток на половину.
    assert out[cells[-1]] == pytest.approx(60.0)
    assert out[cells[0]] == pytest.approx(100.0 - 40.0 * 0.5)
    #: Вниз по руслу только глубже.
    assert (np.diff(out[cells]) <= 1e-9).all()
    #: Рядом с руслом — опущено, за краем долины — как было.
    beside = int(grid.near[0, cells[-1]])
    assert 60.0 < out[beside] < 100.0
    far = grid.dilate_distance(np.isin(np.arange(grid.count), cells), 6) >= 5.0
    assert np.array_equal(out[far], height[far])
    #: Не ниже трети своей высоты, даже у глубокой долины над низкой землёй.
    low = np.full(grid.count, 30.0)
    assert (pipeline._carve_valleys(low, grid, land, no_lake, carried, params) >= 9.0).all()
    #: Озеро — не река: котловина с самым большим притоком не роется, и её
    #: берег остаётся где был (ревью 2026-09-12).
    lake = np.zeros(grid.count, dtype=bool)
    lake[cells[-1]] = True
    kept = pipeline._carve_valleys(height, grid, land, lake, carried, params)
    #: Not dug as a river is -- the neighbour's valley still reaches it.
    assert kept[cells[-1]] > out[cells[-1]] + 1.0
    assert kept[cells[-2]] < 100.0
    #: Без глубины — без долин.
    still = tiny(valley_depth_m=0.0)
    assert np.array_equal(pipeline._carve_valleys(height, grid, land, no_lake, carried, still), height)


def test_the_ribbon_read_between_cells_keeps_its_width_on_the_diagonal():
    """Мера ленты (`pipeline.ribbon`) записана так, чтобы билинейное чтение
    клиента давало ленту объявленной ширины и на прямом плёсе, и на
    диагональном, и в перехвате между клетками русла: те самые 59–61 м, что
    названы у `STREAM_RAMP_M` и в шейдере. Считается на плоской сетке в 50 м
    — расстояние до линии русла, мера, чтение между клетками, нож на
    половине, — то есть проверяется пара «запись — чтение», а не сфера.
    """
    side = 50.0
    width = 60.0

    def raster_for(points):
        n = 40
        grid = np.zeros((n, n))
        segs = list(pairwise(points))
        channel = {tuple(np.round(q / side).astype(int)) for q in points}
        for i in range(n):
            for j in range(n):
                c = np.array([j * side, i * side])
                gap = min(_to_segment(c, a, b) for a, b in segs)
                if (j, i) in channel:
                    gap = 0.0
                grid[i, j] = pipeline.ribbon(gap, width)
        return grid

    def read(grid, x, y):
        x0, y0 = int(np.floor(x)), int(np.floor(y))
        fx, fy = x - x0, y - y0
        top = (1 - fx) * grid[y0, x0] + fx * grid[y0, x0 + 1]
        low = (1 - fx) * grid[y0 + 1, x0] + fx * grid[y0 + 1, x0 + 1]
        return (1 - fy) * top + fy * low

    def wet_metres(grid, centre, direction):
        steps = np.arange(-120, 120.1, 0.5)
        wet = [read(grid, *((centre + s * direction) / side)) > 0.5 for s in steps]
        return float(np.sum(wet) * 0.5)

    axis = raster_for(np.array([[20 * side, k * side] for k in range(5, 35)], float))
    diagonal = raster_for(np.array([[(5 + k) * side, (5 + k) * side] for k in range(30)], float))
    east = np.array([1.0, 0.0])
    across = np.array([1.0, -1.0]) / np.sqrt(2.0)
    for grid, centre, direction in (
        (axis, np.array([20 * side, 20 * side]), east),
        (axis, np.array([20 * side, 20.5 * side]), east),
        (diagonal, np.array([20 * side, 20 * side]), across),
        #: Перехват: середина между двумя клетками русла по диагонали.
        (diagonal, np.array([20.5 * side, 20.5 * side]), across),
    ):
        assert abs(wet_metres(grid, centre, direction) - width) <= 2.0


def _to_segment(p, a, b):
    ab = b - a
    t = float(np.clip(((p - a) @ ab) / (ab @ ab), 0.0, 1.0))
    return float(np.linalg.norm(p - (a + t * ab)))


def test_the_distance_to_a_channel_is_to_its_line_not_to_its_cells():
    """Лента реки пишется по расстоянию до **линии** русла (`hydro.channel_distance`).

    Рядом с руслом, идущим по диагонали сетки, боковая клетка стоит в
    полуклетке от линии, а до середины ближайшей клетки русла ей целая
    клетка: расстояние до клеток делало диагональные плёсы вдвое уже.
    """
    from field import hydro

    grid = Grid.of(99_600.0, 3_000.0)
    #: Русло — цепочка клеток по одной стороне света от истока, каждая
    #: течёт в следующую; сторона выбрана так, чтобы цепочка шла по
    #: диагонали клетки: соседи-«диагонали» стоят дальше прямых.
    flat = np.arange(grid.count)
    start = int(np.argmin(np.abs(grid.lat) + np.abs(grid.lon)))
    #: Стороны света считаются у самой стартовой клетки: какая из них —
    #: диагональ клетки, зависит от того, где на грани стоишь; свободные
    #: места (сосед — сама клетка) не в счёт.
    distances = grid.distances[:, start].copy()
    real = grid.near[:, start] != start
    diagonal = int(np.argmax(np.where(real, distances, -np.inf)))
    straight = int(np.argmin(np.where(real, distances, np.inf)))
    chain = [start]
    for _ in range(6):
        chain.append(int(grid.near[diagonal][chain[-1]]))
    river = np.zeros(grid.count, dtype=bool)
    river[chain] = True
    receiver = flat.copy()
    for a, b in pairwise(chain):
        receiver[a] = b
    source, gap = hydro.channel_distance(grid, river, receiver, 3)
    #: На самом русле — ноль, и клетка знает своего ближайшего.
    assert gap[chain[3]] == pytest.approx(0.0, abs=1e-6)
    assert source[chain[3]] == chain[3]
    #: Клетка сбоку от середины цепочки: до ближайшей клетки русла — шаг
    #: сетки, до линии — заметно меньше (у ломаной через диагонали клеток
    #: боковой сосед по прямой стороне стоит в полушаге от линии).
    beside = int(grid.near[straight][chain[3]])
    assert not river[beside]
    to_cell = float(grid.distances[straight, chain[3]])
    assert gap[beside] < 0.8 * to_cell
    assert gap[beside] > 0.4 * to_cell
    #: Дальше досягаемости — бесконечность и никакого источника.
    assert np.isinf(gap[source < 0]).all()
    assert (gap[source >= 0] < np.inf).all()


def test_a_channel_near_a_larger_lower_one_is_captured_by_it():
    """Параллельные русла сливаются (`hydro.capture`, владелец 2026-09-11).

    Спуск по самому крутому уклону кладёт два ручья на ровный склон в ногу,
    и гребень между ними никто не режет. Русло, у которого в нескольких
    клетках течёт русло крупнее и ниже, отдаёт ему воду по прорезанной
    перемычке; сток остаётся деревом, а каждое звено идёт строго вниз.
    """
    from field import hydro

    #: Крохотный мир: сетка та же, что у прочих тестов; рельеф — ровный
    #: склон к «морю» на одной стороне, чтобы спуск лёг параллельными
    #: линиями.
    params = tiny(seed=3)
    grid = pipeline.Grid.of(params.radius_m, params.step_m)
    #: Склон по широте: чем южнее, тем ниже; море — южная шапка.
    height = (grid.lat + 90.0) * 10.0
    sea = grid.lat < -70.0
    plain = hydro.route(height, sea, grid)
    flow = hydro.route(height, sea, grid, capture_m2=3 * grid.area_m2, capture_reach_cells=5)
    flat = np.arange(grid.count)
    #: Дерево стока цело: каждая клетка доходит до устья.
    step = flow.receiver.copy()
    for _ in range(grid.count.bit_length() + 1):
        step = step[step]
    assert (flow.receiver[step] == step).all(), "кольцо в стоке"
    #: Каждое звено строго вниз по залитой высоте — это и держит дерево.
    donors = flat[flow.receiver != flat]
    assert (flow.filled[flow.receiver[donors]] < flow.filled[donors]).all()
    #: И обход идёт сверху вниз по дереву: приёмник всегда позже донора.
    position = np.empty(grid.count, dtype=int)
    position[flow.order] = flat
    assert (position[donors] < position[flow.receiver[donors]]).all()
    #: Захват состоялся хоть где-то: есть клетки, чей приёмник — не самый
    #: крутой спуск, а русло поодаль.
    assert (flow.receiver != plain.receiver).any(), "ни одно русло не приняло соседа"
    #: Перемычка прорезана, а не перепрыгнута: залитая высота только
    #: опускалась, и опускалась где-то.
    assert (flow.filled <= plain.filled + 1e-9).all()
    assert (flow.filled < plain.filled - 1e-9).any()
    #: Отданное вбок не теряется: площадь у устьев та же, что суша.
    land = ~sea
    roots = flow.receiver == flat
    assert flow.area_m2[roots & land].sum() + flow.area_m2[roots & sea].sum() >= land.sum() * grid.area_m2 * 0.99
    #: Русла сходятся: устьев у моря стало не больше, чем без захвата.
    def mouths(f):
        return (sea[f.receiver] & land & (f.area_m2 >= 3 * grid.area_m2)).sum()

    assert mouths(flow) <= mouths(plain)
