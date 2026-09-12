# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Климат из географии: пояса ветров, влага с моря, дождевая тень (план §4.2).

Температура — как в игре сейчас: тёплый край на экваторе, холодный на полюсе
по квадрату синуса широты, минус высота. Осадки — новое: ветер дует поясами
(пассаты к экватору, западные в умеренных, восточные у полюсов), над морем
воздух набирает влагу, над сушей теряет её дождём — сильнее там, где земля
идёт вверх по ветру, — и за хребтом остаётся сухим. Отсюда пустынный пояс на
подветренной стороне, дождевой лес на наветренном склоне и степь в глубине
материка, без единой нарисованной рукой границы.

Длины здесь — **доли радиуса планеты**, высоты — доли размаха рельефа (план
§3): земные интуиции про глубину материка и дождевую тень на планете в
шестьдесят раз меньше Земли переносятся долями, а не километрами, и один
конвейер даёт Акватике тот же климат, что Терре, а не случайность масштаба.
Где сухой пояс и насколько он сушит — числа мира, они в реестре
(`terrain.dry_belt_*`); пояса ветров — устройство циркуляции, они здесь.

Зональный биом — по таблице `biome.zonal` реестра (§5, волна 4): та же,
что читает игра, так что рендер и перепись показывают то, что увидит игрок.
Растр в файл поля не пишется — игра классифицирует сама, поверх него ещё
азональный слой (`biome.azonal`), лёд и горная черта.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from field import noise
from field.grid import Grid

#: Влага, в долях радиуса планеты: над морем воздух насыщается за
#: `EVAPORATION_R`, над сушей отдаёт дождём с длиной `RAIN_BASE_R`, теряет
#: влагу за `LAND_LOSS_R` и дышит — лес и озёра возвращают часть выпавшего —
#: за `LAND_EVAPORATION_R`.
EVAPORATION_R = 0.15
LAND_EVAPORATION_R = 2.0
LAND_LOSS_R = 4.0
RAIN_BASE_R = 1.5
#: Подъём вдоль ветра, выжимающий всю влагу, и спуск, высушивающий дождь
#: за хребтом, — в долях размаха рельефа.
LIFT_REF = 0.67
LEE_REF = 0.5
RAIN_CAP = 0.5
#: Меридиональное перемешивание влаги за шаг марша: доля влаги кольца,
#: которая за клетку пути уходит соседям по широте (пополам на север и на
#: юг), и столько же приходит от них. Без него кольца шли независимо, и
#: там, где кольцо южнее идёт над морем, а северное над сушей, на осадках
#: лежала прямая черта по параллели на всю подветренную длину (владелец
#: 2026-09-12: горизонтальные линии на слое осадков и на облаках). Черта
#: размывается до полутора десятков колец — столько успевает разойтись
#: влага, пока море и суша тянут её назад: ширину задаёт баланс доли с
#: темпами EVAPORATION_R и LAND_LOSS_R, а не длина марша. Сосед по
#: широте — воздух соседнего кольца на том же шаге марша: в экваториальном
#: поясе кольца равной длины, и он стоит на той же долготе; в полярных
#: шапках кольцо i длиной 4i, и сосед на шаге k ушёл по долготе на
#: 90°·k/(i·(i+1)) — выше ~60° размыв косой. Черте по параллели это не
#: мешает; выравнивать соседа по долготе — отдельная правка.
MERIDIONAL_MIX = 0.25
#: Решётки шумов: края сухого пояса и осадков. Их размах — в реестре
#: (`terrain.dry_belt_wander_deg`, `terrain.rain_noise`), это подбирает
#: владелец по рендеру; решётка — устройство шума.
DRY_BELT_WANDER_LATTICE = 6.0
RAIN_NOISE_LATTICE = 40.0


@dataclass(frozen=True)
class DryBelt:
    """Сухой пояс ячейки Хэдли: широта середины, полуширина, сила, размах
    блуждания края; и доля шума в осадках (всё реестр)."""

    lat: float
    width: float
    strength: float
    wander_deg: float
    rain_noise: float


@dataclass(frozen=True)
class Winds:
    """Пояса ветров (реестр `terrain.wind_belts`): до `trade_lat` пассаты на
    запад, до `westerly_lat` западные на восток, дальше полярные восточные;
    на `edge_deg` по краю осадки двух маршей смешиваются."""

    trade_lat: float
    westerly_lat: float
    edge_deg: float


@dataclass(frozen=True)
class Zone:
    """Строка `biome.zonal` реестра: прямоугольник диаграммы Уиттекера.
    Нижний край входит, верхний нет, кроме верхнего края плоскости."""

    biome: str
    temp_min: float
    temp_max: float
    rain_min: float  # на шкале site.rain_range, 0..100
    rain_max: float


@dataclass(frozen=True)
class Weather:
    """Что кроме широты и высоты решает среднюю температуру (реестр):
    насколько глубина материка холоднее берега и на каком удалении от моря
    (доля радиуса), насколько и на какой длине волны гуляет местный климат."""

    continental_c: float
    continental_reach_r: float
    noise_c: float
    noise_km: float


def temperature(
    lat: np.ndarray,
    height_m: np.ndarray,
    warm: float,
    cold: float,
    lapse_per_km: float,
    sea_m: np.ndarray | None = None,
    radius_m: float = 1.0,
    weather: Weather | None = None,
    texture: np.ndarray | None = None,
) -> np.ndarray:
    """Средняя температура: широта, высота, глубина материка, местный шум.

    Без моря и погоды — одна широта с высотой, как в игре сейчас. Глубина
    материка холодит сильнее к полюсам (квадрат синуса широты: у экватора
    интерьер не холоднее берега), шум — ровный по планете.
    """
    tilt = np.sin(np.radians(lat))
    t = warm - (warm - cold) * tilt * tilt - lapse_per_km * np.clip(height_m, 0.0, None) / 1000.0
    if weather is not None and sea_m is not None:
        inland = np.clip(sea_m / (weather.continental_reach_r * radius_m), 0.0, 1.0)
        t = t - weather.continental_c * inland * (0.3 + 0.7 * tilt * tilt)
    if weather is not None and texture is not None:
        t = t + weather.noise_c * texture
    #: Тёплый край реестра — потолок: местный шум не греет выше него, а
    #: холодный край высота и глубина материка перебирают честно.
    return np.minimum(t, warm)


def rain(
    grid: Grid,
    height_m: np.ndarray,
    sea: np.ndarray,
    seed: int,
    relief_m: float,
    belt: DryBelt,
    winds: Winds,
) -> np.ndarray:
    """Осадки в [0, 1] по клеткам: марш влаги по ветру, два круга вокруг планеты.

    Ветер не меняется по одной параллели: марш идёт дважды, на запад и на
    восток, и в каждой клетке осадки смешиваются по её поясу — с краем,
    гуляющим по долготе шумом, — иначе на 30° и 60° лежала бы прямая черта.
    """
    wander = noise.centred(seed + 53, grid.xyz, DRY_BELT_WANDER_LATTICE, 2) * belt.wander_deg
    #: Сухой пояс — нисходящий воздух: в нём дождь за шаг слабее.
    in_belt = np.exp(-(((np.abs(grid.lat + wander) - belt.lat) / max(belt.width, 1e-9)) ** 2))
    dryness = 1.0 - belt.strength * in_belt
    westward = _march(grid, height_m, sea, -1, relief_m, dryness)
    eastward = _march(grid, height_m, sea, 1, relief_m, dryness)
    shifted = np.abs(grid.lat + wander)
    edge = max(winds.edge_deg, 1e-9)
    west_share = _smoothstep((shifted - winds.trade_lat) / edge) * (
        1.0 - _smoothstep((shifted - winds.westerly_lat) / edge)
    )
    out = westward * (1.0 - west_share) + eastward * west_share
    scaled = np.clip(out * dryness, 0.0, 1.0)
    texture = noise.centred(seed + 51, grid.xyz, RAIN_NOISE_LATTICE, 3)
    return np.clip(scaled * (1.0 + belt.rain_noise * texture), 0.0, 1.0)


def _mixed(moisture: np.ndarray, share: float) -> np.ndarray:
    """Влага колец после обмена с соседями по широте: `share` уходит пополам
    на север и на юг, полярные кольца меняются лишь с одним соседом. Сумма
    по кольцам сохраняется (обмен, а не потеря); одинокий всплеск на одном
    кольце расплывается, как и положено воздуху."""
    if moisture.size < 2 or share <= 0.0:
        return moisture
    north = np.concatenate(([moisture[0]], moisture[:-1]))
    south = np.concatenate((moisture[1:], [moisture[-1]]))
    return moisture * (1.0 - share) + 0.5 * share * (north + south)


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t + 0.5, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _march(
    grid: Grid, height_m: np.ndarray, sea: np.ndarray, direction: int, relief_m: float, dryness: np.ndarray
) -> np.ndarray:
    """Влага, гонимая в одну сторону по всем кольцам сразу: +1 на восток, -1 на запад.

    Кольцо равной широты — это и есть параллель, по которой дует ветер, и
    ради него сетка выбрана HEALPix, а не икосферой (D-328): у икосферы
    замкнутого пояса клеток нет вовсе. Кольца разной длины — полярное из
    четырёх клеток, экваториальное из `4 nside`, — и каждое идёт по кругу
    своим шагом: короткое кольцо и по земле короче, ветер обходит его чаще.
    """
    table, lengths = grid.rings
    rings, wide = table.shape
    seats = np.arange(rings)
    lat = grid.lat[table[:, 0]]
    #: Шаг вдоль кольца — его длина по земле, делённая на число клеток.
    along = 2.0 * np.pi * grid.radius_m * np.cos(np.radians(lat)) / lengths
    moisture = np.full(rings, 0.5)
    out = np.zeros(grid.count)
    radius = grid.radius_m
    evaporation = np.clip(along / (EVAPORATION_R * radius), 0.0, 1.0)
    breath = np.clip(along / (LAND_EVAPORATION_R * radius), 0.0, 1.0)
    loss = np.clip(along / (LAND_LOSS_R * radius), 0.0, 1.0)
    base = along / (RAIN_BASE_R * radius)
    lift_ref = LIFT_REF * relief_m
    lee_ref = LEE_REF * relief_m
    for step in range(2 * wide):
        walk = step if direction > 0 else -step - 1
        here = table[seats, walk % lengths]
        back = table[seats, (walk - direction) % lengths]
        here_sea = sea[here]
        rise = np.clip(height_m[here], 0.0, None) - np.clip(height_m[back], 0.0, None)
        lift = np.clip(rise, 0.0, None) / lift_ref
        fall = np.clip(-rise, 0.0, None) / lee_ref
        share = np.minimum(base + lift, RAIN_CAP) * dryness[here]
        wet = moisture * share
        wet = np.where(here_sea, 0.0, wet)
        moisture = moisture - wet
        #: Спуск за хребтом сушит: воздух греется, и дождь за ним слабеет.
        moisture = moisture * np.exp(-fall)
        moisture = np.where(
            here_sea,
            moisture + evaporation * (1.0 - moisture),
            moisture * (1.0 - loss) + breath * (1.0 - moisture) * out[back],
        )
        moisture = _mixed(np.clip(moisture, 0.0, 1.0), MERIDIONAL_MIX)
        #: Осадки места — не сколько выпало на клетку, а насколько мокрый
        #: здесь воздух: дождь за клетку делится на дождь ровной земли, так
        #: что равнина читает влажность воздуха, а склон против ветра — единицу.
        out[here] = np.where(here_sea, 0.0, np.minimum(wet / (base * dryness[here]), 1.0))
    return out


def zonal_names(zones: tuple[Zone, ...]) -> list[str]:
    """Биомы таблицы в порядке первого появления: коды растра `zonal`."""
    out: list[str] = []
    for zone in zones:
        if zone.biome not in out:
            out.append(zone.biome)
    return out


def zonal(
    temperature_c: np.ndarray,
    rain01: np.ndarray,
    zones: tuple[Zone, ...],
    rain_range: tuple[float, float] = (0.0, 100.0),
) -> np.ndarray:
    """Код зонального биома по клеткам по таблице `biome.zonal` реестра —
    той же, что читает игра (`engine/biome.zonal`, волна 4): индекс в
    `zonal_names(zones)`. Осадки [0, 1] переводятся на шкалу узла
    (`site.rain_range`), как это делает `engine/terrain.climate_at`. Нижний
    край строки входит, верхний нет, кроме верхнего края плоскости; точка
    за плоскостью прижимается к её краю."""
    names = zonal_names(zones)
    top_t, top_r = max(z.temp_max for z in zones), max(z.rain_max for z in zones)
    t = np.clip(temperature_c, min(z.temp_min for z in zones), top_t)
    rain = rain_range[0] + (rain_range[1] - rain_range[0]) * rain01
    r = np.clip(rain, min(z.rain_min for z in zones), top_r)
    out = np.full(t.shape, 255, dtype=np.uint8)
    for zone in zones:
        in_t = (t >= zone.temp_min) & ((t < zone.temp_max) | ((t == top_t) & (zone.temp_max == top_t)))
        in_r = (r >= zone.rain_min) & ((r < zone.rain_max) | ((r == top_r) & (zone.rain_max == top_r)))
        take = in_t & in_r & (out == 255)
        out[take] = names.index(zone.biome)
    return out
