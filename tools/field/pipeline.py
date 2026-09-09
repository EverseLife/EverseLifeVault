# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Конвейер поля: от зерна и долей вольта до растров планеты (план §4).

Порядок — порядок процессов: плиты и порода дают основу и поднятие; уровень
моря режется квантилем, как и раньше (`terrain.sea_share`), и в метры высота
переводится размахом `terrain.relief_m`; эрозия идёт в две сетки — грубая
(шаг вчетверо крупнее) делает долины и хребты за много итераций, тонкая
догоняет детали за несколько; потом сток, климат, формы.

Один конвейер на все планеты (§4.7): планета без моря просто не получает
ни стока к морю, ни берега, потому что море — ноль, а не особый случай.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Callable

import numpy as np

from field import climate, erosion, forms, hydro, noise, plates
from field.grid import Grid

#: Дно моря для картинки, доли размаха: глубина на краю шкалы основы.
SEA_DEPTH = 0.67
#: Грубая сетка эрозии: во сколько раз крупнее шаг и сколько итераций там и там.
COARSE_FACTOR = 4
COARSE_ITERATIONS = 60
FINE_ITERATIONS = 24
#: Мелочь под грубой сеткой, когда высота переезжает на тонкую: амплитуда в
#: долях размаха и длина волны в долях радиуса; на твёрдой породе шум
#: гребенчатый.
DETAIL_AMPLITUDE = 0.015
DETAIL_WAVELENGTH_R = 0.06
#: Дальше этого «близость воды» не считается, доля радиуса.
WET_MAX_R = 0.05

WATER_LAND, WATER_SEA, WATER_LAKE, WATER_RIVER = 0, 1, 2, 3


@dataclass(frozen=True)
class Params:
    planet: str
    seed: int
    step_m: float
    radius_m: float
    sea_share: float
    relief_m: float
    plates: int
    continental_share: float
    river_area_km2: float
    warm_c: float
    cold_c: float
    lapse_per_km: float
    ice_c: float
    ice_rain: float  # ниже этой доли осадков холодная земля — мерзлота без шапки
    ice_deep_c: float  # ниже этой температуры — лёд при любой сухости
    cold_c_zonal: float  # порог тундры предпросмотра, biome.bounds.cold_c
    cool_c: float
    dry: float
    desert_lat: float
    dry_belt_lat: float
    dry_belt_width: float
    dry_belt_strength: float
    version: int
    coarse_factor: int = COARSE_FACTOR
    coarse_iterations: int = COARSE_ITERATIONS
    fine_iterations: int = FINE_ITERATIONS

    @property
    def belt(self) -> climate.DryBelt:
        return climate.DryBelt(self.dry_belt_lat, self.dry_belt_width, self.dry_belt_strength)

    @property
    def bounds(self) -> climate.Bounds:
        return climate.Bounds(self.cold_c_zonal, self.cool_c, self.dry, self.desert_lat)

    @classmethod
    def from_constants(cls, constants: dict, planet: str, **overrides) -> Params:
        """Числа мира из `build/constants.json`, как их читает движок."""
        planets = ("terra", "aquatica", "pyroxis", "aurora")
        seed = int(constants["terrain.seed"]) * len(planets) + planets.index(planet)
        share = float(constants["planet.land_area_share"][planet])
        radius_m = (share**0.5) * float(constants["planet.earth_radius_km"]) * 1000.0
        relief_m = float(constants["terrain.relief_m"])
        temp = constants["site.temp_range"]
        lapse_range = float(constants["terrain.lapse_c"])
        bounds = constants["biome.bounds"]
        params = cls(
            planet=planet,
            seed=seed,
            step_m=float(constants["terrain.step_m"]),
            radius_m=radius_m,
            sea_share=float(constants["terrain.sea_share"].get(planet, 0.0)),
            relief_m=relief_m,
            plates=int(constants["terrain.plates"]),
            continental_share=float(constants["terrain.continental_share"]),
            river_area_km2=float(constants["terrain.river_area_km2"]),
            warm_c=float(temp["max"]),
            cold_c=float(temp["min"]),
            #: Ключ пока «на весь размах» (реестр); в градусы на километр его
            #: переведёт волна климата — здесь только пересчёт.
            lapse_per_km=lapse_range / (relief_m / 1000.0),
            #: Лёд — свой порог, ниже тундры (владелец): шапка там, где
            #: мерзлота, а не везде, где тундра.
            ice_c=float(constants["terrain.ice_c"]),
            ice_rain=float(constants["terrain.ice_rain"]),
            ice_deep_c=float(constants["terrain.ice_deep_c"]),
            cold_c_zonal=float(bounds["cold_c"]),
            cool_c=float(bounds["cool_c"]),
            dry=float(bounds["dry"]),
            desert_lat=float(bounds["desert_lat"]),
            dry_belt_lat=float(constants["terrain.dry_belt_lat"]),
            dry_belt_width=float(constants["terrain.dry_belt_width"]),
            dry_belt_strength=float(constants["terrain.dry_belt_strength"]),
            #: Версия алгоритма поля (план §4.8, OQ-149): правка процесса —
            #: новая версия в реестре, и файл с другой версией — другой мир.
            version=int(constants["terrain.version"]),
        )
        return replace(params, **overrides) if overrides else params

    def digest(self) -> str:
        text = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


@dataclass
class Rasters:
    params: Params
    grid: Grid
    height_m: np.ndarray
    water: np.ndarray  # uint8: суша, море, озеро, река
    form: np.ndarray  # uint8, коды `forms.FORMS`
    hardness: np.ndarray  # [0.25, 1]
    area_km2: np.ndarray  # площадь стока
    wet_m: np.ndarray  # до ближайшей воды, метры, не дальше WET_MAX_M
    river_m: np.ndarray  # до ближайшей реки или озера, метры, не дальше WET_MAX_M
    temperature_c: np.ndarray
    rain: np.ndarray  # [0, 1]
    zonal: np.ndarray  # uint8, предпросмотр `climate.ZONAL_NAMES`
    plate: np.ndarray
    deposit_m: np.ndarray
    uplift: np.ndarray
    ice: np.ndarray

    @property
    def sea(self) -> np.ndarray:
        return self.water == WATER_SEA

    @property
    def land(self) -> np.ndarray:
        return self.water != WATER_SEA

    def land_share(self) -> float:
        area = np.repeat(self.grid.area_m2[:, None], self.grid.cols, axis=1)
        return float(area[self.land].sum() / area.sum())


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, share: float) -> float:
    order = np.argsort(values, axis=None)
    v = values.ravel()[order]
    w = weights.ravel()[order]
    cumulative = np.cumsum(w) / w.sum()
    return float(v[np.searchsorted(cumulative, share)])


def _to_metres(
    base: np.ndarray, sea_share: float, relief_m: float, grid: Grid
) -> tuple[np.ndarray, np.ndarray]:
    """Уровень моря — по доле **площади**, не клеток: у полюса клетка узкая,
    и квантиль по клеткам делал бы полярную сушу дешевле экваториальной."""
    weights = np.repeat(grid.area_m2[:, None], grid.cols, axis=1)
    if sea_share <= 0.0:
        level = float(base.min()) - 1e-9
    elif sea_share >= 1.0:
        level = float(base.max()) + 1e-9
    else:
        level = _weighted_quantile(base, weights, sea_share)
    top = max(float(base.max()) - level, 1e-9)
    bottom = max(level - float(base.min()), 1e-9)
    height = np.where(
        base >= level, (base - level) / top * relief_m, (base - level) / bottom * SEA_DEPTH * relief_m
    )
    return height, base < level


def build(params: Params, log: Callable[[str], None] = lambda _: None) -> Rasters:
    fine = Grid.of(params.radius_m, params.step_m)
    log(f"grid {fine.rows}x{fine.cols} at {fine.step_m:.0f} m")
    tect = plates.build(fine, params.seed, params.plates, params.continental_share, params.sea_share)
    height, sea = _to_metres(tect.base, params.sea_share, params.relief_m, fine)
    log(f"plates: {int(tect.plate.max()) + 1}, land {float((~sea).mean()):.2f}")

    def thermometer(grid: Grid) -> Callable[[np.ndarray], np.ndarray]:
        return lambda h: climate.temperature(grid.lat2d, h, params.warm_c, params.cold_c, params.lapse_per_km)

    coarse = Grid.of(params.radius_m, params.step_m * params.coarse_factor)
    h_c = coarse.resample_from(height, fine)
    sea_c = h_c < 0.0
    hard_c = coarse.resample_from(tect.hardness, fine)
    up_c = coarse.resample_from(tect.uplift, fine)
    log(f"coarse erosion {coarse.rows}x{coarse.cols}, {params.coarse_iterations} iterations")
    coarse_done = erosion.erode(
        h_c, sea_c, coarse,
        hardness=hard_c, uplift=up_c, relief_m=params.relief_m,
        iterations=params.coarse_iterations, temperature=thermometer(coarse), ice_c=params.ice_c,
    )

    h_f = fine.resample_from(coarse_done.height, coarse)
    #: Берег — слово основы, не грубой эрозии: клетка моря остаётся под водой,
    #: клетка суши — над ней, как бы ни легла билинейная интерполяция.
    h_f = np.where(sea, np.minimum(h_f, -1.0), np.maximum(h_f, 0.5))
    lattice = noise.lattice_for(params.radius_m, DETAIL_WAVELENGTH_R * params.radius_m)
    smooth = noise.centred(params.seed + 61, fine.xyz, lattice, 3)
    sharp = noise.ridged(params.seed + 71, fine.xyz, lattice, 3) * 2.0 - 1.0
    weight = np.clip((tect.hardness - 0.5) / 0.5, 0.0, 1.0)
    detail = smooth * (1.0 - weight) + sharp * weight
    lift = 0.5 + np.clip(h_f, 0.0, None) / params.relief_m
    h_f = np.where(sea, h_f, h_f + DETAIL_AMPLITUDE * params.relief_m * detail * lift)
    log(f"fine erosion, {params.fine_iterations} iterations")
    done = erosion.erode(
        h_f, sea, fine,
        hardness=tect.hardness, uplift=tect.uplift, relief_m=params.relief_m,
        iterations=params.fine_iterations, temperature=thermometer(fine), ice_c=params.ice_c,
    )
    height = done.height
    flow = done.flow
    #: Дельта, дошедшая до кромки, — суша: море отступило от устья само.
    sea = sea & (height < 0.0)
    land = ~sea
    #: Размах — слово вольта, не эрозии: поднятие за сорок итераций уводит
    #: вершину выше `terrain.relief_m`, и суша приводится к нему линейно.
    top = float(height[land].max()) if land.any() else params.relief_m
    height = np.where(land, height * (params.relief_m / max(top, 1e-9)), height)
    flow = hydro.route(height, sea, fine)
    river = land & ~flow.lake & (flow.area_m2 >= params.river_area_km2 * 1e6)
    water = np.full(height.shape, WATER_LAND, dtype=np.uint8)
    water[sea] = WATER_SEA
    water[flow.lake] = WATER_LAKE
    water[river] = WATER_RIVER
    wet_cells = fine.cells_for_metres(WET_MAX_R * params.radius_m)
    wet_m = fine.dilate_distance(water != WATER_LAND, wet_cells) * fine.step_m
    #: Пресная вода отдельно: «у реки» и «у моря» — разные вещи для узла (D-321).
    fresh = (water == WATER_RIVER) | (water == WATER_LAKE)
    river_m = fine.dilate_distance(fresh, wet_cells) * fine.step_m

    temperature = thermometer(fine)(height)
    rain = climate.rain(fine, height, sea, params.seed, params.relief_m, params.belt)
    zonal = climate.zonal(temperature, rain, fine.lat2d, params.bounds)
    #: Шапка — где холодно и мокро, либо где очень холодно (владелец): сухая
    #: мерзлота остаётся землёй. Эрозия выше считала лёд по одной температуре
    #: — осадков до неё ещё нет; разница — сила среза на сухом холоде, и она
    #: сознательно оставлена за льдом.
    cold = temperature < params.ice_c
    ice = land & ((cold & (rain >= params.ice_rain)) | (temperature < params.ice_deep_c))
    log("forms")
    form = forms.classify(
        fine,
        forms.Inputs(
            height_m=height, sea=sea, lake=flow.lake, river=river, area_m2=flow.area_m2,
            hardness=tect.hardness, deposit_m=done.deposit, rift=tect.rift, volcano=tect.volcano,
            ice=ice, rain01=rain, relief_m=params.relief_m,
        ),
    )
    return Rasters(
        params=params, grid=fine, height_m=height, water=water, form=form,
        hardness=tect.hardness, area_km2=flow.area_m2 / 1e6, wet_m=wet_m, river_m=river_m,
        temperature_c=temperature, rain=rain, zonal=zonal, plate=tect.plate,
        deposit_m=done.deposit, uplift=tect.uplift, ice=ice,
    )
