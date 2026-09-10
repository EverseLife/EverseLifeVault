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

from field import climate, erosion, forms, hydro, noise, plates, provinces
from field.grid import WAYS, Grid

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
    continental_c: float  # на сколько глубина материка холоднее берега
    continental_reach_r: float  # на каком удалении от моря, доля радиуса
    climate_noise_c: float  # размах местных отклонений температуры
    climate_noise_km: float  # и их длина волны
    wind_trade_lat: float
    wind_westerly_lat: float
    wind_edge_deg: float
    dry_belt_wander_deg: float
    rain_noise: float
    dry_belt_lat: float
    dry_belt_width: float
    dry_belt_strength: float
    version: int
    coarse_factor: int = COARSE_FACTOR
    coarse_iterations: int = COARSE_ITERATIONS
    fine_iterations: int = FINE_ITERATIONS
    #: Строки `data/provinces.yaml` этой планеты (план §7): в хеше паспорта,
    #: потому что другая таблица — другие сдвиги и другое поле.
    provinces: tuple = ()
    #: Строки `biome.zonal` реестра (план §5, волна 4): та же таблица, что
    #: читает игра; в хеше паспорта, потому что она решает растр `zonal`.
    zones: tuple = ()
    #: Шкала осадков узла (`site.rain_range`): края строк `biome.zonal` — на ней.
    rain_range: tuple = (0.0, 100.0)

    @property
    def belt(self) -> climate.DryBelt:
        return climate.DryBelt(
            self.dry_belt_lat,
            self.dry_belt_width,
            self.dry_belt_strength,
            self.dry_belt_wander_deg,
            self.rain_noise,
        )

    @property
    def winds(self) -> climate.Winds:
        return climate.Winds(self.wind_trade_lat, self.wind_westerly_lat, self.wind_edge_deg)

    @property
    def weather(self) -> climate.Weather:
        return climate.Weather(
            self.continental_c, self.continental_reach_r, self.climate_noise_c, self.climate_noise_km
        )

    @property
    def zonal(self) -> tuple[climate.Zone, ...]:
        return tuple(
            climate.Zone(str(row["biome"]), *(float(v) for v in row["temp"]), *(float(v) for v in row["rain"]))
            for row in self.zones
        )

    @classmethod
    def from_constants(
        cls, constants: dict, planet: str, provinces: list[dict] | None = None, **overrides
    ) -> Params:
        """Числа мира из `build/constants.json`, как их читает движок, и
        строки провинций планеты из `build/provinces.json`."""
        planets = ("terra", "aquatica", "pyroxis", "aurora")
        seed = int(constants["terrain.seed"]) * len(planets) + planets.index(planet)
        share = float(constants["planet.land_area_share"][planet])
        radius_m = (share**0.5) * float(constants["planet.earth_radius_km"]) * 1000.0
        relief_m = float(constants["terrain.relief_m"])
        temp = constants["site.temp_range"]
        lapse_range = float(constants["terrain.lapse_c"])
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
            provinces=tuple(
                {
                    "id": str(row["id"]),
                    "rain_shift": float(row.get("rain_shift", 0.0)),
                    "temp_shift_c": float(row.get("temp_shift_c", 0.0)),
                    "vein_k": float(row.get("vein_k", 1.0)),
                    #: Фацеты, которые здесь чаще обычного (план §7, волна 8):
                    #: едут в паспорт, потому что провинции игра берёт оттуда.
                    "favours": tuple(str(f) for f in (row.get("favours") or ())),
                }
                for row in (provinces or [])
            ),
            zones=tuple(
                {"biome": str(row["biome"]), "temp": [float(v) for v in row["temp"]], "rain": [float(v) for v in row["rain"]]}
                for row in constants["biome.zonal"].values()
            ),
            rain_range=(float(constants["site.rain_range"]["min"]), float(constants["site.rain_range"]["max"])),
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
            continental_c=float(constants["terrain.continental_c"]),
            continental_reach_r=float(constants["terrain.continental_reach_r"]),
            climate_noise_c=float(constants["terrain.climate_noise_c"]),
            climate_noise_km=float(constants["terrain.climate_noise_km"]),
            wind_trade_lat=float(constants["terrain.wind_belts"]["trade_lat"]),
            wind_westerly_lat=float(constants["terrain.wind_belts"]["westerly_lat"]),
            wind_edge_deg=float(constants["terrain.wind_belts"]["edge_deg"]),
            dry_belt_wander_deg=float(constants["terrain.dry_belt_wander_deg"]),
            rain_noise=float(constants["terrain.rain_noise"]),
            dry_belt_lat=float(constants["terrain.dry_belt_lat"]),
            dry_belt_width=float(constants["terrain.dry_belt_width"]),
            dry_belt_strength=float(constants["terrain.dry_belt_strength"]),
            #: Версия алгоритма поля (план §4.8, OQ-149): правка процесса —
            #: новая версия в реестре, и файл с другой версией — другой мир.
            version=int(constants["terrain.version"]),
        )
        return replace(params, **overrides) if overrides else params

    def digest(self) -> str:
        #: Таблица биомов и её шкала в хеш не входят: растр `zonal` в файл
        #: не пишется, и правка таблицы не должна требовать пересборки поля.
        fields = {k: v for k, v in asdict(self).items() if k not in ("zones", "rain_range")}
        text = json.dumps(fields, sort_keys=True)
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
    #: Сколько земли стекает через реку, берегом которой клетка могла бы
    #: быть: наибольший сток среди неё самой и её соседей, ноль там, где
    #: реки рядом нет. По нему картинка даёт реке честную ширину (§9.2).
    #: Считается здесь, а не при чтении файла: соседи клетки — свойство
    #: сетки, и у сервера таблицы соседей нет и быть не должно.
    flow_km2: np.ndarray
    wet_m: np.ndarray  # до ближайшей воды, метры, не дальше WET_MAX_M
    river_m: np.ndarray  # до ближайшей реки или озера, метры, не дальше WET_MAX_M
    temperature_c: np.ndarray
    rain: np.ndarray  # [0, 1]
    zonal: np.ndarray  # uint8, индекс в `climate.zonal_names(params.zonal)`
    sea_m: np.ndarray  # до ближайшего моря, метры, не дальше WET_MAX_M
    province: np.ndarray  # uint8: 0 — нет, k — строка k-1 таблицы провинций
    provinces: list[dict]  # строки провинций планеты в порядке кодов
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
        #: Доля клеток и доля площади — одно и то же: сетка равноплощадная (D-328).
        return float(self.land.mean())


def _to_metres(
    base: np.ndarray, sea_share: float, relief_m: float, grid: Grid
) -> tuple[np.ndarray, np.ndarray]:
    """Уровень моря — по доле **площади**, не клеток. На равноплощадной сетке
    (D-328) это одно и то же, и взвешенный квантиль стал обычным: у полюса
    клетка такая же, как на экваторе, и полярная суша больше не дешевле."""
    if sea_share <= 0.0:
        level = float(base.min()) - 1e-9
    elif sea_share >= 1.0:
        level = float(base.max()) + 1e-9
    else:
        level = float(np.quantile(base, sea_share))
    top = max(float(base.max()) - level, 1e-9)
    bottom = max(level - float(base.min()), 1e-9)
    height = np.where(
        base >= level, (base - level) / top * relief_m, (base - level) / bottom * SEA_DEPTH * relief_m
    )
    return height, base < level


def build(params: Params, log: Callable[[str], None] = lambda _: None) -> Rasters:
    fine = Grid.of(params.radius_m, params.step_m)
    log(f"grid nside {fine.nside}, {fine.count:,} cells of {fine.side_m:.1f} m")
    tect = plates.build(fine, params.seed, params.plates, params.continental_share, params.sea_share)
    height, sea = _to_metres(tect.base, params.sea_share, params.relief_m, fine)
    log(f"plates: {int(tect.plate.max()) + 1}, land {float((~sea).mean()):.2f}")

    def thermometer(
        grid: Grid, sea_mask: np.ndarray, sea_m: np.ndarray | None = None
    ) -> Callable[[np.ndarray], np.ndarray]:
        #: Расстояние до моря и шум климата — раз на сетку; высота — при каждом чтении.
        if sea_m is None:
            #: Дальше глубины материка ответ всё равно упирается в единицу,
            #: и заливке незачем обходить планету ради него.
            _, sea_m = grid.nearest(
                sea_mask, grid.cells_for_metres(params.continental_reach_r * params.radius_m)
            )
        lattice = noise.lattice_for(params.radius_m, params.climate_noise_km * 1000.0)
        texture = noise.centred(params.seed + 91, grid.xyz, lattice, 3)
        weather = params.weather
        return lambda h: climate.temperature(
            grid.lat, h, params.warm_c, params.cold_c, params.lapse_per_km,
            sea_m=sea_m, radius_m=params.radius_m, weather=weather, texture=texture,
        )

    coarse = Grid.of(params.radius_m, params.step_m * params.coarse_factor)
    h_c = coarse.resample_from(height, fine)
    sea_c = h_c < 0.0
    hard_c = coarse.resample_from(tect.hardness, fine)
    up_c = coarse.resample_from(tect.uplift, fine)
    log(f"coarse erosion nside {coarse.nside}, {params.coarse_iterations} iterations")
    coarse_done = erosion.erode(
        h_c, sea_c, coarse,
        hardness=hard_c, uplift=up_c, relief_m=params.relief_m,
        iterations=params.coarse_iterations, temperature=thermometer(coarse, sea_c), ice_c=params.ice_c,
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
        iterations=params.fine_iterations, temperature=thermometer(fine, sea), ice_c=params.ice_c,
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
    water = np.full(fine.count, WATER_LAND, dtype=np.uint8)
    water[sea] = WATER_SEA
    water[flow.lake] = WATER_LAKE
    water[river] = WATER_RIVER
    wet_cells = fine.cells_for_metres(WET_MAX_R * params.radius_m)
    wet_m = fine.dilate_distance(water != WATER_LAND, wet_cells) * fine.side_m
    #: Пресная вода отдельно: «у реки» и «у моря» — разные вещи для узла (D-321).
    fresh = (water == WATER_RIVER) | (water == WATER_LAKE)
    river_m = fine.dilate_distance(fresh, wet_cells) * fine.side_m

    #: До моря — и термометру (глубина материка), и файлу: «у моря» для узла
    #: (D-321) читается из растра, а не восемью лучами по высотам.
    _, sea_m = fine.nearest(
        sea, fine.cells_for_metres(params.continental_reach_r * params.radius_m)
    )
    temperature = thermometer(fine, sea, sea_m)(height)
    rain = climate.rain(fine, height, sea, params.seed, params.relief_m, params.belt, params.winds)
    #: Провинции (план §7) сдвигают осадки и температуру до классификатора
    #: (§5): характер области — в самих растрах, а не только в подписи.
    log("provinces")
    realm = provinces.build(fine, params.seed, land, list(params.provinces))
    rain = np.clip(rain + provinces.shifts(realm, "rain_shift") / 100.0, 0.0, 1.0)
    temperature = np.minimum(temperature + provinces.shifts(realm, "temp_shift_c"), params.warm_c)
    #: Классификатор читает растры такими, какими их хранит файл (целые
    #: градусы, осадки в 1/255): рендер судит то, что получит узел, а не
    #: то, что видел конвейер до записи.
    zonal = climate.zonal(np.round(temperature), np.round(rain * 255.0) / 255.0, params.zonal, params.rain_range)
    #: Шапка — где холодно и мокро, либо где очень холодно (владелец): сухая
    #: мерзлота остаётся землёй. Эрозия выше считала лёд по одной температуре
    #: — осадков до неё ещё нет; разница — сила среза на сухом холоде, и она
    #: сознательно оставлена за льдом.
    cold = temperature < params.ice_c
    ice = land & ((cold & (rain >= params.ice_rain)) | (temperature < params.ice_deep_c))
    #: Ширина реки читается со стока её берега (план §9.2, D-328).
    bank = np.where(river, flow.area_m2 / 1e6, 0.0)
    flow_km2 = bank.copy()
    for k in range(WAYS):
        flow_km2 = np.maximum(flow_km2, bank[fine.near[k]])
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
        hardness=tect.hardness, area_km2=flow.area_m2 / 1e6, flow_km2=flow_km2,
        wet_m=wet_m, river_m=river_m,
        temperature_c=temperature, rain=rain, zonal=zonal, plate=tect.plate,
        sea_m=np.minimum(sea_m, WET_MAX_R * params.radius_m),
        deposit_m=done.deposit, uplift=tect.uplift, ice=ice,
        province=realm.raster, provinces=realm.table,
    )
