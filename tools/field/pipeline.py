# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Конвейер поля: от зерна и долей вольта до растров планеты (план §4).

Порядок — порядок процессов: плиты и порода дают основу и поднятие; уровень
моря стоит на своей отметке (`terrain.sea_level`), и в метры высота
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

from field import climate, erosion, forms, hydro, noise, plants, plates, provinces
from field.forms import VOLCANO_SHARE
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
#:
#: Потолок обязан быть выше **всякого** порога, который эти растры читает, и
#: на **самой мелкой** планете: пороги (`biome.bounds.coast_km`,
#: `biome.facet_axes.wet_km`) стоят в метрах и одни на все миры, а потолок у
#: каждого мира свой. 0,05 хватало, пока самый мелкий радиус был 14,4 км;
#: после второго ужатия (D-329) Пироксис стал 7,2 км, его потолок — 359 м, и
#: `coast_km` = 375 м оказался выше: вся суша планеты читалась берегом, а ось
#: влаги в выборе фацета не принимала нуля нигде. 0,10 держит нынешние 500 м
#: с запасом (718 м у Пироксиса) — и это правило, а не число: подняли порог
#: или ужали планету ещё раз, сверьтесь заново.
WET_MAX_R = 0.10

WATER_LAND, WATER_SEA, WATER_LAKE, WATER_RIVER = 0, 1, 2, 3

#: Чем течёт планета. Растр `water` один на все четыре: клетка либо суша,
#: либо под жидкостью, — и игре этого хватает, она и так отказывает войти.
#: Разные тут **источник** и **имя**: воду рождает дождь, лаву — вулканы и
#: рифты, и «море» Пироксиса зовётся лавовым океаном, а не морем.
FLUID_WATER, FLUID_LAVA = "water", "lava"
FLUIDS = (FLUID_WATER, FLUID_LAVA)
#: Как рисуется река: лента, чья ширина считается по дереву стока —
#: `hydro.widths`, где слияние берёт **долю суммы** ширин, а не сумму
#: (владелец 2026-09-11). Числа — в реестре (`terrain.river_narrow_m`,
#: `terrain.river_wide_m`, `terrain.river_merge`): владелец крутит их по
#: рендеру, а такое живёт в вольте, а не в конвейере.
#:
#: Ширина **преувеличена, и знаемо так**. Реки Терры несут от 0,14 до 67 км²
#: водосбора, а гидравлика (`ширина = 3·√A`, закон, которому подчиняется
#: всякая река Земли) даёт на этом от одного метра до двадцати пяти.
#: Нарисовать такое растром нельзя, и предел тут не вкусовой: игра берёт
#: долю **между** клетками и режет по половине, а на диагональном шаге русла
#: перемычки стоят в стороне клетки — в середине четырёхугольника между ними
#: интерполяция даёт `1 − 25/ширина`, и лента связна, пока ширина больше
#: одной клетки. Пол ленты — свойство **сетки**, а не воды.
#:
#: Дополнение к D-329 от 2026-09-11: расстояние меряется до русла, а не до
#: всякой пресной воды, и море из счёта не исключено — в устье лента заходит
#: за кромку, и шва между рекой и морем нет.

#: Ниже этого расхода впадина — сухая котловина, а не озеро: одна клетка
#: средней отдачи планеты. Раньше озером становилась любая яма, поднятая
#: заливкой, — и на Пироксисе сухая котловина числилась озером ровно так же,
#: как проточное озеро Терры.
#:
#: Мера — **расход через клетку**, а не приток со стороны, и разница тут
#: есть: накопление считает и собственную долю клетки, поэтому впадина не
#: суше средней проходит порог сама по себе. То есть правило читается «яма
#: не суше планеты», а не «яма, в которую втекает». Слабее — да; на деле
#: разницы нет: заливка объявляет озером только то, что подняла выше
#: `hydro.LAKE_DEPTH_M`, и одиночных клеток среди озёр Терры **ноль** из
#: 1338. Ужесточать до двух клеток значит пересобирать четыре мира ради
#: числа, которое ничего не двигает.
LAKE_INFLOW_CELLS = 1.0
#: Полоса берега, клеток в обе стороны от кромки, в которой высота
#: сводится к **профилю основы** (`_shore_by_base`). Кромка моря — линия,
#: где основа пересекает свой уровень (`_to_metres`), и она гладкая; но
#: между клетками картинка режет воду по нулю **высоты**, а высота у кромки
#: была несимметрична: суша сплющена эрозией и её ограничениями в плоскость
#: на нуле, а дно по `_to_metres` уходит от уровня в `SEA_DEPTH`-раз круче,
#: чем поднимается суша. Ноль между клеткой в +0,4 и клеткой в −4,8 стоит
#: в восьми сотых клетки от суши — то есть на **серединах крайних
#: клеток суши**, и берег шёл ромбами, прямыми под сорок пять градусов с
#: углами, на любом кадре (владелец 2026-09-11: «на карте встречаются
#: ромбы», дважды). В полосе высота с обеих сторон — один и тот же
#: профиль: основа минус уровень в **одном** масштабе (суши), к первой
#: клетке от кромки целиком, к краю полосы — плавно в эрозию. Ноль тогда
#: стоит там, где основа пересекает уровень, и нулевая линия между
#: клетками — её контур.
SHORE_BAND_CELLS = 3
#: Сколько раундов сглаживается фронт класса под **насыпной кромкой**
#: (`_shore_by_base`): клетками моря, которые эрозия насыпала выше нуля
#: (`erosion.DELTA_RISE_M`) и которые стали сушей. На Терре это половина
#: первого кольца суши. Основа у них под уровнем, профиль основы им не
#: годится (сведённые к нему, они тонули — восемь тысяч клеток суши до
#: −44 м), а высота эрозии — полка на нуле с ромбами. Их берег — фронт
#: самого класса: расстояние до кромки со знаком, сглаженное на столько
#: раундов, чтобы ступени лестницы клеток разошлись в кривую, и умноженное
#: на уклон основы у кромки. Три раунда — сигма в полторы клетки.
FRINGE_BLUR = 3


@dataclass(frozen=True)
class Params:
    planet: str
    seed: int
    step_m: float
    radius_m: float
    sea_level: float
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
    #: Чем течёт эта планета (`FLUIDS`): решает, откуда берётся жидкость и
    #: как её зовут. В хеше паспорта — другая жидкость, другое поле.
    fluid: str = FLUID_WATER
    #: Во сколько раз гуще вулканы, чем на земной планете (`terrain.volcanoes`).
    volcanoes: float = 1.0
    #: Выше этой температуры земли лава на ней держится расплавом, ниже —
    #: застывает у жерла (`terrain.lava_c`).
    lava_c: float = 60.0
    #: Как далеко язык уходит от конуса, км (`terrain.lava_reach_km`).
    lava_reach_km: float = 0.6
    #: Полоса, в которой растёт зелень, °C (`terrain.plant_temp`).
    plant_warm_c: float = 32.0
    plant_cold_c: float = -5.0
    #: Доля шкалы осадков, при которой воды покрову вдоволь
    #: (`terrain.plant_rain`).
    plant_rain: float = 0.45
    #: На каком удалении близость пресной воды перестаёт помогать покрову,
    #: км (`biome.facet_axes.wet_km` — та же длина, что у оси влаги).
    plant_wet_km: float = 0.5
    #: Ширина русла: исток начинается с пола, слияние берёт `river_merge`
    #: долю суммы впадающих, потолок держит вилку сверху (`hydro.widths`).
    #: Пол — свойство сетки, а не воды: лента уже диагонали клетки рвётся
    #: на пятна.
    river_narrow_m: float = 60.0
    river_wide_m: float = 120.0
    river_merge: float = 0.5
    #: Досягаемость захвата русла, м (`terrain.capture_reach_m`): русло не
    #: дальше этого от русла крупнее и ниже отдаёт ему воду (`hydro.capture`).
    capture_reach_m: float = 250.0

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
        #: Зерно — своё у каждой планеты (владелец, 2026-09-10). Раньше оно было
        #: одно, а миры разводились по номеру планеты в кортеже: перевыбрать
        #: Аврору, не тронув Терру, было нельзя вовсе, а перестановка планет в
        #: кортеже молча меняла все четыре мира сразу.
        seed = int(constants["terrain.seed"][planet])
        share = float(constants["planet.land_area_share"][planet])
        radius_m = (share**0.5) * float(constants["planet.earth_radius_km"]) * 1000.0
        relief_m = float(constants["terrain.relief_m"])
        #: Тёплый и холодный края — тоже свои: одна пара на четыре мира держала
        #: Пироксис при −34 °C со льдом на пятой части суши, а Аврору — при +35
        #: с дюнами. Земной диапазон остался у Терры, и он же — шкала узла
        #: (`site.temp_range`), по которой игра рисует градусник.
        temp = constants["terrain.temp_range"][planet]
        lapse_range = float(constants["terrain.lapse_c"])
        params = cls(
            planet=planet,
            seed=seed,
            step_m=float(constants["terrain.step_m"]),
            radius_m=radius_m,
            sea_level=float(constants["terrain.sea_level"][planet]),
            relief_m=relief_m,
            plates=int(constants["terrain.plates"]),
            continental_share=float(constants["terrain.continental_share"]),
            volcanoes=float(constants["terrain.volcanoes"][planet]),
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
            fluid=_fluid(constants["terrain.fluid"][planet]),
            lava_c=float(constants["terrain.lava_c"]),
            lava_reach_km=float(constants["terrain.lava_reach_km"]),
            plant_warm_c=float(constants["terrain.plant_temp"]["max"]),
            plant_cold_c=float(constants["terrain.plant_temp"]["min"]),
            plant_rain=float(constants["terrain.plant_rain"]),
            plant_wet_km=float(constants["biome.facet_axes"]["wet_km"]),
            river_narrow_m=float(constants["terrain.river_narrow_m"]),
            river_wide_m=float(constants["terrain.river_wide_m"]),
            river_merge=float(constants["terrain.river_merge"]),
            capture_reach_m=float(constants["terrain.capture_reach_m"]),
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
    #: Лента реки, [0, 1]: единица в русле, ноль за берегом. Ширина уже в
    #: ней — она взята у ближайшего русла (`hydro.widths`).
    stream: np.ndarray
    #: Доля клетки под растительностью, [0, 1] (`field.plants`). Отдельно от
    #: биома и от формы: зелёный цвет на карте берётся отсюда и больше
    #: ниоткуда, поэтому планета без покрова выходит без зелени сама.
    plants: np.ndarray

    @property
    def sea(self) -> np.ndarray:
        return self.water == WATER_SEA

    @property
    def land(self) -> np.ndarray:
        return self.water != WATER_SEA

    def land_share(self) -> float:
        #: Доля клеток и доля площади — одно и то же: сетка равноплощадная (D-328).
        return float(self.land.mean())


def _shore_profile(base: np.ndarray, sea_level: float, relief_m: float) -> np.ndarray:
    """Профиль берега: основа минус уровень в масштабе **суши** с обеих
    сторон, метры. Не `_to_metres`: та уводит дно в `SEA_DEPTH` раз круче,
    чем поднимает сушу, и ноль между двумя клетками съезжает к суше."""
    level = float(sea_level)
    top = max(float(base.max()) - level, 1e-9)
    return (np.asarray(base, dtype=float) - level) / top * relief_m


def _shore_by_base(
    height: np.ndarray, profile: np.ndarray, sea: np.ndarray, grid: Grid
) -> np.ndarray:
    """Высота у кромки моря сводится к профилю основы (`SHORE_BAND_CELLS`).

    К первой клетке от кромки — целиком профиль, к краю полосы — плавно
    прежняя высота; знак не меняется: у клетки суши профиль не ниже нуля,
    у клетки моря — не выше (`_to_metres` делит их той же основой), а
    эрозия держит сушу над нулём и море под ним, так что и смесь знака не
    меняет. Что меняется — что стоит между клетками: ноль ложится туда,
    где основа пересекает уровень, с обеих сторон одинаково, и нулевая
    линия картинки — контур основы, а не середины крайних клеток.

    Исключение — **насыпная кромка** (`FRINGE_BLUR`): клетки моря, которые
    эрозия насыпала выше нуля и которые стали сушей (`build`: море усыхает
    по высоте). Основа у них под уровнем, и профиль основы им не годится:
    сведённые к нему, они тонули. В полосе вокруг них профиль — фронт
    самого класса, сглаженный: расстояние до кромки со знаком, размытое
    на `FRINGE_BLUR` раундов и умноженное на уклон основы у кромки, так
    что ноль стоит посередине между насыпью и морем и лестница клеток
    разошлась в кривую. Где и этот фронт спорит с классом (мыс в одну
    клетку), высота остаётся эрозии.
    """
    reach = float(SHORE_BAND_CELLS)
    sea = np.asarray(sea)
    #: Суша у моря и море у суши: каждая сторона меряется до другой. Первая
    #: клетка от кромки стоит в шаге; на ней вес единица, на краю — ноль.
    to_sea = grid.dilate_distance(sea, SHORE_BAND_CELLS)
    to_land = grid.dilate_distance(~sea, SHORE_BAND_CELLS)
    away = np.where(sea, to_land, to_sea)
    #: Первое кольцо стоит в шаге-полтора (диагональ), и весь профиль ему.
    weight = np.clip((reach - away) / (reach - 1.5), 0.0, 1.0)
    laid = ~sea & (profile < 0.0)
    if laid.any():
        #: Уклон у кромки, метров на клетку: профиль основы в первом кольце
        #: там, где он и класс согласны.
        first = (away < 1.75) & (sea == (profile < 0.0))
        rise = float(np.median(np.abs(profile[first]))) if first.any() else 1.0
        front = grid.blur(np.where(sea, -to_land, to_sea), FRINGE_BLUR) * max(rise, 0.1)
        zone = grid.dilate_distance(laid, SHORE_BAND_CELLS) < reach
        profile = np.where(zone, front, profile)
    #: Знак профиля спорит с классом — профиль не его.
    weight = np.where(sea == (profile < 0.0), weight, 0.0)
    return weight * profile + (1.0 - weight) * height


def _to_metres(
    base: np.ndarray, sea_level: float, relief_m: float, grid: Grid
) -> tuple[np.ndarray, np.ndarray]:
    """Высота в метрах и маска моря по **уровню мирового океана**.

    Уровень — число в собственных единицах основы (`terrain.sea_level`), а не
    доля площади под водой. Разница не в записи, а в том, что из чего
    следует. Прежде задавалась **доля моря**, и уровень подбирался под неё
    квантилем: сколько бы рельефа ни выросло, воды всегда оказывалось ровно
    столько, сколько сказано, — то есть океан подгонялся под ответ. Теперь
    вода стоит на своей отметке, а сколько над ней суши, решает сам рельеф
    (владелец 2026-09-11: «процент суши указывался не отдельной константой, а
    был следствием константы»). Доля суши стала измеряемой величиной и
    записывается в паспорт.
    """
    level = float(sea_level)
    top = max(float(base.max()) - level, 1e-9)
    bottom = max(level - float(base.min()), 1e-9)
    height = np.where(
        base >= level, (base - level) / top * relief_m, (base - level) / bottom * SEA_DEPTH * relief_m
    )
    return height, base < level


#: Склон ленты реки: на скольких метрах её мера проходит от единицы до
#: нуля, с берегом ровно посередине. Клиент читает ленту **между** клетками,
#: и склон обязан быть пологим против клетки: мера, падавшая от единицы в
#: русле до нуля за ширину реки — за одну клетку, — между двумя клетками
#: русла, стоящими по диагонали, проваливалась до половины, и нож резал
#: ленту в чётки: перехват вдвое уже ленты на каждом шаге (владелец
#: 2026-09-11: артефакты шейдера). Вторая половина той же починки —
#: расстояние до **линии** русла, а не до ближайшей его клетки
#: (`hydro.channel_distance`): у диагонального плёса боковая клетка стоит
#: в 35 м от линии, а до середины ближайшей клетки русла ей 50, и лента
#: по такому расстоянию выходила вдвое уже. С пологим склоном и честным
#: расстоянием билинейное чтение клиента даёт 60-метровую ленту ровно
#: 59–61 м и на прямом плёсе, и на диагональном, и в перехвате между
#: клетками русла (счёт на синтетической сетке 2026-09-11). Сглаживание
#: сплайном пробовали — оно сужает диагональный плёс до 52 м, потому что
#: скругляет излом меры в русле; не нужно.
STREAM_RAMP_M = 200.0


def ribbon(gap_m: np.ndarray | float, width_m: np.ndarray | float):
    """Мера ленты реки в клетке: расстояние до русла против полуширины
    русла, на склоне в `STREAM_RAMP_M` метров.

    **Половина меры — берег.** Клиент режет ленту там, где мера переваливает
    за половину (`shade.ts`, как у озера), то есть ровно на `gap = width / 2`;
    в русле она выше половины на долю полуширины от склона, за берегом — ниже
    на долю расстояния. Мера записи и порог чтения — одна пара, и порознь их
    менять нельзя; порог живёт в другом репозитории, поэтому здесь стоит
    отдельная функция, а под ней — тест.
    """
    return np.clip(0.5 + (np.asarray(width_m) / 2.0 - gap_m) / STREAM_RAMP_M, 0.0, 1.0)


def _fluid(word: object) -> str:
    """Слово `terrain.fluid`, сверенное со списком.

    Иначе опечатка проходит всю цепь молча: `== FLUID_LAVA` даёт False, и
    Пироксис пересобирается водным миром с дождём и речной сетью — без
    единого отказа, потому что «lava» и «Lava» одинаково строки.
    """
    if str(word) not in FLUIDS:
        raise ValueError(f"terrain.fluid: «{word}» — не {' и не '.join(FLUIDS)}")
    return str(word)


def _yield(params: Params, rain: np.ndarray, temperature: np.ndarray) -> np.ndarray:
    """Сколько **воды** отдаёт клетка, доля: дождь, и только там, где он не
    выпадает снегом. Замёрзшая клетка воду копит, а не отдаёт, и оттого
    ледяная шапка рек ниже себя не рождает.

    Ноль по всей суше — законный ответ, а не сбой: планета, у которой вся
    вода — лёд, не имеет ни рек, ни озёр, и `hydro.discharge` скажет это
    нулями. Форму земли это не трогает: долины и каньоны режет геометрия
    склона (`flow.area_m2`), и на Авроре они остаются такими же, какими были.

    Лавы здесь нет намеренно. Она не выпадает с неба и не собирается
    водосбором: она выходит из конуса и течёт вниз, пока не остынет
    (`_lava_tongues`). Пропущенная через ту же сеть, она давала на Пироксисе
    ветвистую речную систему, крашенную в оранжевый, — воду, а не лаву
    (владелец 2026-09-10: «реки на пироксисе не должны генерироваться как
    обычные водные реки»).
    """
    return np.where(temperature >= params.ice_c, rain, 0.0)


def _lava_tongues(
    params: Params,
    grid: Grid,
    flow,
    volcano: np.ndarray,
    temperature: np.ndarray,
    land: np.ndarray,
) -> np.ndarray:
    """Лавовые языки: где лава вышла из конуса и куда дотекла.

    Не река и не сеть. Лава начинается в жерле, идёт вниз по тому же спуску,
    что и вода, и **застывает**, отойдя от источника, — язык, а не водосбор.
    Оттого их не сливает в одно русло: два соседних конуса дают два потока,
    а не приток и главную реку.

    Два условия, и оба нужны. **Конус** — иначе течь неоткуда; отсюда
    `terrain.volcanoes`: вулканы есть на каждой планете, но там, где их одна
    штука на полушарие, и лавы не видно. **Жара** — `terrain.lava_c`: лава
    на холодной земле застывает у самого жерла, и на Терре вулканы стоят без
    единого потока, хотя вулканы у неё есть (владелец 2026-09-10). Порог тот
    же, за которым в `biome.zonal` кончается всякая растительность: земля,
    на которой держится расплав, ничего не растит, и наоборот.
    """
    hot = land & (temperature >= params.lava_c)
    vent = hot & (volcano >= VOLCANO_SHARE)
    reach_m = params.lava_reach_km * 1000.0
    out = vent.copy()
    #: Досягаемость расходуется **метрами пути**, а не числом шагов. Шаг по
    #: диагонали длиннее стороны в корень из двух, и счёт шагами уводил язык
    #: до сорока процентов дальше объявленного: на Пироксисе он доходил до
    #: пятнадцати клеток при заявленных двенадцати. `flow.distance` знает
    #: длину каждого шага, и она же тратится.
    left = np.where(vent, reach_m, 0.0)
    receiver = flow.receiver
    front = vent
    #: Верхняя граница числа шагов: короче стороны шага не бывает. Она здесь
    #: страховкой от бесконечного цикла, а не мерой длины.
    for _ in range(int(reach_m / grid.side_m) + 2):
        if not front.any():
            break
        idx = np.flatnonzero(front)
        moved = receiver[idx]
        #: Клетка, чей приёмник — она сама, это дно: море, озеро или яма.
        budget = left[idx] - flow.distance[idx]
        keep = (moved != idx) & hot[moved] & (budget > 0.0)
        gain = np.zeros(grid.count)
        #: Два языка могут прийти в одну клетку; дальше идёт тот, у кого
        #: осталось больше, иначе первый обрубал бы второй.
        np.maximum.at(gain, moved[keep], budget[keep])
        better = gain > left
        left = np.maximum(left, gain)
        out |= better
        front = better
    return out


def build(params: Params, log: Callable[[str], None] = lambda _: None) -> Rasters:
    fine = Grid.of(params.radius_m, params.step_m)
    log(f"grid nside {fine.nside}, {fine.count:,} cells of {fine.side_m:.1f} m")
    tect = plates.build(
        fine, params.seed, params.plates, params.continental_share, params.sea_level,
        volcanoes=params.volcanoes,
    )
    height, sea = _to_metres(tect.base, params.sea_level, params.relief_m, fine)
    #: Профиль берега по основе, до эрозии: у кромки он вернётся в поле
    #: (`_shore_by_base`), потому что кромка моря — контур основы.
    shore = _shore_profile(tect.base, params.sea_level, params.relief_m)
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
    #: Климат — **до** воды, а не после. Раньше он считался в конце, потому
    #: что реку решала одна геометрия склона; теперь реку решает то, что по
    #: ней течёт, а течёт по ней дождь — и знать его надо раньше.
    #: До моря — и термометру (глубина материка), и файлу: «у моря» для узла
    #: (D-321) читается из растра, а не восемью лучами по высотам.
    _, sea_m = fine.nearest(
        sea, fine.cells_for_metres(params.continental_reach_r * params.radius_m)
    )
    warmth = thermometer(fine, sea, sea_m)
    temperature = warmth(height)
    #: Дождя на лавовой планете нет вовсе, и это не упрощение: марш влаги
    #: набирает её **над морем**, а море Пироксиса — расплавленный камень.
    #: Пустить его через тот же марш значило бы получить дождевые леса на
    #: наветренном берегу лавового океана. Осадки там ноль по всей планете,
    #: и вся она поэтому сушь — чем и должна быть.
    rain = (
        np.zeros(fine.count)
        if params.fluid == FLUID_LAVA
        else climate.rain(fine, height, sea, params.seed, params.relief_m, params.belt, params.winds)
    )

    #: Провинции (план §7) сдвигают осадки и температуру **здесь**, до воды,
    #: а не после классификатора, как раньше. Пока реку решала геометрия
    #: склона, порядок был не важен; теперь её решают дождь и жара, и сдвиг,
    #: применённый после, разводил файл с самим собой: на Терре 319 речных
    #: клеток лежали при записанной температуре ниже `ice_c`, а на Пироксисе
    #: 13 клеток лавы — холоднее `lava_c`, то есть холоднее порога, которым
    #: та же лава и разрешена. Растр и вода теперь считаются по одним числам.
    log("provinces")
    realm = provinces.build(fine, params.seed, land, list(params.provinces))
    if params.fluid != FLUID_LAVA:
        #: Провинция двигает осадки только там, где им есть от чего двигаться.
        #: На лавовой планете дождя нет, а сдвиг — это прибавка к нулю:
        #: «влажная провинция» вырастала на планете без единой капли и снимала
        #: с трети суши признак сухости, по которому та и должна быть
        #: каменистой.
        rain = np.clip(rain + provinces.shifts(realm, "rain_shift") / 100.0, 0.0, 1.0)
    def weather(h: np.ndarray) -> np.ndarray:
        return np.minimum(warmth(h) + provinces.shifts(realm, "temp_shift_c"), params.warm_c)

    temperature = weather(height)

    #: Последний сток — с захватом: параллельные русла сливаются
    #: (`hydro.capture`, досягаемость `terrain.capture_reach_m`), и
    #: перемычки, которые захват прорезал, ложатся в высоту — река, идущая
    #: через гребень поверх него, была бы рисунком, а не водой. Русло для
    #: захвата мерится тем же, чем ниже решается река: расходом, то есть
    #: площадью, взвешенной отдачей (`hydro.yield_share`); по голой площади
    #: захват резал бы гребни под русла, которых рекой не будет — на Авроре
    #: и Пироксисе все, на Терре в пустынях. Потому климат стоит выше.
    flow = hydro.route(
        height,
        sea,
        fine,
        capture_m2=params.river_area_km2 * 1e6,
        capture_reach_cells=fine.cells_for_metres(params.capture_reach_m),
        capture_yield=hydro.yield_share(_yield(params, rain, temperature), land),
    )
    height = np.where(land, np.minimum(height, flow.filled), height)
    height = _shore_by_base(height, shore, sea, fine)
    #: Перемычки опустили клетки на метры: температура пересчитывается по
    #: окончательной высоте — это формула, и растр обязан сходиться с
    #: высотой в файле. Осадки — нет: марш влаги идёт на волне в сотни
    #: метров и этих метров не видит, а стоит секунды.
    temperature = weather(height)

    #: Шапка — где холодно и мокро, либо где очень холодно (владелец): сухая
    #: мерзлота остаётся землёй. Эрозия выше считала лёд по одной температуре
    #: — осадков до неё ещё нет; разница — сила среза на сухом холоде, и она
    #: сознательно оставлена за льдом.
    #:
    #: Считается **до** воды, потому что вода под шапкой не течёт. Пока лёд
    #: считался после, растры спорили: 225 клеток Терры были разом рекой и
    #: ледяным полем, и шейдер рисовал в них лёд, а векторный слой — русло.
    cold = temperature < params.ice_c
    #: Море замерзает тоже. Растр льда покрывал одну сушу, и Аврора, получив
    #: океаны (владелец 2026-09-11), вышла бы белым материком в синей воде
    #: при −25 °C на экваторе. Порог у моря тот же, `terrain.ice_c`: там, где
    #: земля под шапкой, вода под припаем. Клетка при этом остаётся водой —
    #: форма у неё `sea`, движок в неё не пускает, — и лёд на ней только
    #: цвет и слово. Терре та же строка дала полярные припаи, которых у неё
    #: не было вовсе.
    ice = (land & ((cold & (rain >= params.ice_rain)) | (temperature < params.ice_deep_c))) | (
        sea & cold
    )

    log("discharge")
    given = _yield(params, rain, temperature)
    carried = hydro.discharge(flow, fine, given, land)
    #: `& ~ice` — шапка сверху: ледник кормит реку, но она выходит из-под
    #: него, а не течёт по нему. Спор двух растров решается в пользу льда,
    #: как и в игре: биом читает `ice` прежде всего остального.
    river = land & ~ice & ~flow.lake & (carried >= params.river_area_km2 * 1e6)
    #: Озеро — впадина **не суше планеты** (`LAKE_INFLOW_CELLS`, там же о
    #: том, почему не «в которую втекает»).
    lake = flow.lake & ~ice & (carried >= LAKE_INFLOW_CELLS * fine.area_m2)
    #: Лава — своим ходом, от жерла вниз, и на любой планете: вулканы есть у
    #: всех, а потечёт ли от них хоть что-нибудь, решает жара.
    log("lava")
    lava = _lava_tongues(params, fine, flow, tect.volcano, temperature, land)
    water = np.full(fine.count, WATER_LAND, dtype=np.uint8)
    water[sea] = WATER_SEA
    water[lake] = WATER_LAKE
    water[river] = WATER_RIVER
    #: Язык, забредший во впадину, стоит в ней озером; остальной — поток.
    water[lava & flow.lake] = WATER_LAKE
    water[lava & ~flow.lake] = WATER_RIVER
    wet_cells = fine.cells_for_metres(WET_MAX_R * params.radius_m)
    wet_m = fine.dilate_distance(water != WATER_LAND, wet_cells) * fine.side_m
    #: Пресная вода отдельно: «у реки» и «у моря» — разные вещи для узла
    #: (D-321). Лава сюда не входит: узел у лавового потока не «у воды», и
    #: пить оттуда нечего — иначе разведка нашла бы на Пироксисе реку.
    fresh = (river | lake) & ~lava
    river_m = fine.dilate_distance(fresh, wet_cells) * fine.side_m

    #: Лента реки: расстояние до **русла** (не до всякой пресной воды) против
    #: ширины, которую даёт расход этого самого русла. Считается здесь, а не
    #: при чтении файла: ширина берётся у ближайшей реки, а «ближайшая» —
    #: свойство сетки, которой у сервера нет.
    #:
    #: Море из счёта не исключено намеренно: лента доходит до кромки и
    #: заходит за неё, поэтому в устье река и море смыкаются без шва. Озеро
    #: источником не считается — иначе вокруг каждого озера рисовалось бы
    #: речное кольцо.
    log("stream")
    #: Докуда лента вообще не ноль: полуширина самой широкой реки и полсклона
    #: за берегом; дальше ближайшее русло не ищется, и мера там ноль.
    #: Расстояние — до линии русла, не до его клетки (`hydro.channel_distance`).
    wide_cells = fine.cells_for_metres(params.river_wide_m / 2.0 + STREAM_RAMP_M / 2.0)
    source, gap_m = hydro.channel_distance(fine, river, flow.receiver, wide_cells)
    channel = hydro.widths(
        flow,
        river,
        narrow_m=params.river_narrow_m,
        wide_m=params.river_wide_m,
        merge=params.river_merge,
    )
    width_m = np.where(source >= 0, channel[np.maximum(source, 0)], params.river_narrow_m)
    stream = ribbon(gap_m, width_m)
    #: Классификатор читает растры такими, какими их хранит файл (целые
    #: градусы, осадки в 1/255): рендер судит то, что получит узел, а не
    #: то, что видел конвейер до записи.
    zonal = climate.zonal(np.round(temperature), np.round(rain * 255.0) / 255.0, params.zonal, params.rain_range)
    #: Ширина реки читается со стока её берега (план §9.2, D-328) — с того,
    #: что по ней идёт, а не с площади склона над ней: сухой водосбор реку
    #: больше не рождает, и широкой её тоже делать не должен.
    bank = np.where(river, carried / 1e6, 0.0)
    flow_km2 = bank.copy()
    for k in range(WAYS):
        flow_km2 = np.maximum(flow_km2, bank[fine.near[k]])
    log("forms")
    form = forms.classify(
        fine,
        forms.Inputs(
            height_m=height, sea=sea, lake=lake, river=river, area_m2=flow.area_m2,
            hardness=tect.hardness, deposit_m=done.deposit, rift=tect.rift, volcano=tect.volcano,
            ice=ice, rain01=rain, relief_m=params.relief_m,
        ),
    )
    #: Растительность — последней: ей нужны и климат, и вода, и лёд, и лава.
    #: Отдельным растром, а не оттенком в чужой шкале: зелёный цвет на карте
    #: берётся отсюда и больше ниоткуда, и планета без покрова выходит без
    #: зелени сама, без единой оговорки про планету.
    log("plants")
    green = plants.cover(
        fine,
        temperature_c=temperature,
        rain01=rain,
        river_m=river_m,
        height_m=height,
        hardness=tect.hardness,
        land=land,
        barren=ice | lava | (water != WATER_LAND),
        warm_c=params.plant_warm_c,
        cold_c=params.plant_cold_c,
        rain_full=params.plant_rain,
        wet_km=params.plant_wet_km,
    )
    return Rasters(
        params=params, grid=fine, height_m=height, water=water, form=form,
        hardness=tect.hardness, area_km2=flow.area_m2 / 1e6, flow_km2=flow_km2,
        wet_m=wet_m, river_m=river_m,
        temperature_c=temperature, rain=rain, zonal=zonal, plate=tect.plate,
        sea_m=np.minimum(sea_m, WET_MAX_R * params.radius_m),
        deposit_m=done.deposit, uplift=tect.uplift, ice=ice, plants=green, stream=stream,
        province=realm.raster, provinces=realm.table,
    )
