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

Зональная таблица биомов здесь — **предпросмотр** для рендера и переписи:
пороги берутся из `biome.bounds` реестра, а четыре класса, которых в
`biome.names` пока нет, ждут таблицы **biome.zonal** волны климата (§5). В
файл поля предпросмотр не пишется.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from field import noise
from field.grid import Grid

#: Пояса ветров по широте, градусы: до первого — пассаты (на запад), до
#: второго — западные (на восток), дальше — полярные восточные.
TRADE_LAT = 30.0
WESTERLY_LAT = 60.0
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
#: Край сухого пояса гуляет по долготе шумом, иначе на карте лежит полоса.
DRY_BELT_WANDER_DEG = 5.0
DRY_BELT_WANDER_LATTICE = 3.0
#: Доля шума в осадках: чтобы одинаковая равнина не была одинаково мокрой.
RAIN_NOISE = 0.15
RAIN_NOISE_LATTICE = 20.0


@dataclass(frozen=True)
class DryBelt:
    """Сухой пояс ячейки Хэдли: широта середины, полуширина, сила (реестр)."""

    lat: float
    width: float
    strength: float


@dataclass(frozen=True)
class Bounds:
    """Пороги классов из `biome.bounds` реестра (D-321)."""

    cold_c: float
    cool_c: float
    dry: float  # на шкале site.rain_range, 0..100
    desert_lat: float


def temperature(lat2d: np.ndarray, height_m: np.ndarray, warm: float, cold: float, lapse_per_km: float) -> np.ndarray:
    tilt = np.sin(np.radians(lat2d))
    return warm - (warm - cold) * tilt * tilt - lapse_per_km * np.clip(height_m, 0.0, None) / 1000.0


def wind_direction(lat: np.ndarray) -> np.ndarray:
    """+1 — воздух идёт на восток (столбцы растут), -1 — на запад."""
    a = np.abs(lat)
    return np.where(a < TRADE_LAT, -1, np.where(a < WESTERLY_LAT, 1, -1)).astype(int)


def rain(
    grid: Grid, height_m: np.ndarray, sea: np.ndarray, seed: int, relief_m: float, belt: DryBelt
) -> np.ndarray:
    """Осадки в [0, 1] по клеткам: марш влаги по ветру, два круга вокруг планеты."""
    rows, cols = height_m.shape
    direction = wind_direction(grid.lat)
    moisture = np.full(rows, 0.5)
    out = np.zeros_like(height_m)
    r = np.arange(rows)
    radius = grid.radius_m
    evaporation = np.clip(grid.dx / (EVAPORATION_R * radius), 0.0, 1.0)
    breath = np.clip(grid.dx / (LAND_EVAPORATION_R * radius), 0.0, 1.0)
    loss = np.clip(grid.dx / (LAND_LOSS_R * radius), 0.0, 1.0)
    base = grid.dx / (RAIN_BASE_R * radius)
    lift_ref = LIFT_REF * relief_m
    lee_ref = LEE_REF * relief_m
    #: Сухой пояс — нисходящий воздух: в нём дождь за шаг слабее.
    wander = noise.centred(seed + 53, grid.xyz, DRY_BELT_WANDER_LATTICE, 2) * DRY_BELT_WANDER_DEG
    in_belt = np.exp(-(((np.abs(grid.lat2d + wander) - belt.lat) / max(belt.width, 1e-9)) ** 2))
    dryness = 1.0 - belt.strength * in_belt
    for step in range(2 * cols):
        col = np.where(direction > 0, step % cols, (cols - 1 - step) % cols)
        prev = (col - direction) % cols
        here_sea = sea[r, col]
        rise = np.clip(height_m[r, col], 0.0, None) - np.clip(height_m[r, prev], 0.0, None)
        lift = np.clip(rise, 0.0, None) / lift_ref
        fall = np.clip(-rise, 0.0, None) / lee_ref
        share = np.minimum(base + lift, RAIN_CAP) * dryness[r, col]
        wet = moisture * share
        wet = np.where(here_sea, 0.0, wet)
        moisture = moisture - wet
        #: Спуск за хребтом сушит: воздух греется, и дождь за ним слабеет.
        moisture = moisture * np.exp(-fall)
        moisture = np.where(
            here_sea,
            moisture + evaporation * (1.0 - moisture),
            moisture * (1.0 - loss) + breath * (1.0 - moisture) * out[r, prev],
        )
        moisture = np.clip(moisture, 0.0, 1.0)
        #: Осадки места — не сколько выпало на клетку, а насколько мокрый
        #: здесь воздух: дождь за клетку делится на дождь ровной земли, так
        #: что равнина читает влажность воздуха, а склон против ветра — единицу.
        out[r, col] = np.where(here_sea, 0.0, np.minimum(wet / (base * dryness[r, col]), 1.0))
    scaled = np.clip(out * dryness, 0.0, 1.0)
    texture = noise.centred(seed + 51, grid.xyz, RAIN_NOISE_LATTICE, 3)
    return np.clip(scaled * (1.0 + RAIN_NOISE * texture), 0.0, 1.0)


#: Предпросмотр зональных биомов: имена классов. Пороги холода и суши —
#: реестра (`Bounds`); пороги четырёх классов, которых в реестре нет, —
#: черновик под таблицу **biome.zonal**, в долях от `dry` и в градусах.
ZONAL_NAMES = (
    "tundra", "taiga", "desert", "steppe", "semidesert", "savanna", "rainforest", "woodland", "forest",
)
SEMIDESERT_DRY = 1.4
WARM_C = 20.0
MILD_C = 14.0
SAVANNA_RAIN = 0.5
RAINFOREST_RAIN = 0.65
WOODLAND_RAIN = 0.45


def zonal(temperature_c: np.ndarray, rain01: np.ndarray, lat2d: np.ndarray, bounds: Bounds) -> np.ndarray:
    """Код зонального биома по клеткам: индекс в `ZONAL_NAMES`."""
    t, r = temperature_c, rain01 * 100.0
    rules = (
        ("tundra", t < bounds.cold_c),
        ("taiga", t < bounds.cool_c),
        ("desert", (r < bounds.dry) & (np.abs(lat2d) <= bounds.desert_lat)),
        ("steppe", r < bounds.dry),
        ("semidesert", (r < bounds.dry * SEMIDESERT_DRY) & (t >= MILD_C)),
        ("savanna", (t >= WARM_C) & (rain01 < SAVANNA_RAIN)),
        ("rainforest", (t >= WARM_C) & (rain01 >= RAINFOREST_RAIN)),
        ("woodland", (t >= MILD_C) & (rain01 < WOODLAND_RAIN)),
    )
    out = np.full(t.shape, ZONAL_NAMES.index("forest"), dtype=np.uint8)
    done = np.zeros(t.shape, dtype=bool)
    for name, hit in rules:
        take = hit & ~done
        out[take] = ZONAL_NAMES.index(name)
        done |= take
    return out
