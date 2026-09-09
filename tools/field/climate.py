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

Зональная таблица биомов здесь — **предпросмотр** для рендера и переписи:
настоящая едет в вольт таблицей **biome.zonal** волной климата (§5).
"""

from __future__ import annotations

import numpy as np

from field import noise
from field.grid import Grid

#: Пояса ветров по широте, градусы: до первого — пассаты (на запад), до
#: второго — западные (на восток), дальше — полярные восточные.
TRADE_LAT = 30.0
WESTERLY_LAT = 60.0
#: Влага: испарение над морем за шаг, потеря над сушей за шаг, базовый дождь
#: и орографический — на единицу подъёма (м/м) вдоль ветра.
EVAPORATION = 0.08
LAND_LOSS = 0.004
RAIN_BASE = 0.012
RAIN_LIFT = 3.5
RAIN_CAP = 0.5
#: Доля шума в осадках: чтобы одинаковая равнина не была одинаково мокрой.
RAIN_NOISE = 0.15
RAIN_NOISE_LATTICE = 20.0
#: Осадки нормируются на этот квантиль суши: сверху всё «очень мокро».
RAIN_TOP_QUANTILE = 0.97


def temperature(lat2d: np.ndarray, height_m: np.ndarray, warm: float, cold: float, lapse_per_km: float) -> np.ndarray:
    tilt = np.sin(np.radians(lat2d))
    return warm - (warm - cold) * tilt * tilt - lapse_per_km * np.clip(height_m, 0.0, None) / 1000.0


def wind_direction(lat: np.ndarray) -> np.ndarray:
    """+1 — воздух идёт на восток (столбцы растут), -1 — на запад."""
    a = np.abs(lat)
    return np.where(a < TRADE_LAT, -1, np.where(a < WESTERLY_LAT, 1, -1)).astype(int)


def rain(grid: Grid, height_m: np.ndarray, sea: np.ndarray, seed: int) -> np.ndarray:
    """Осадки в [0, 1] по клеткам: марш влаги по ветру, два круга вокруг планеты."""
    rows, cols = height_m.shape
    direction = wind_direction(grid.lat)
    moisture = np.full(rows, 0.5)
    out = np.zeros_like(height_m)
    r = np.arange(rows)
    for step in range(2 * cols):
        col = np.where(direction > 0, step % cols, (cols - 1 - step) % cols)
        prev = (col - direction) % cols
        here_sea = sea[r, col]
        rise = (height_m[r, col] - height_m[r, prev]) / grid.dx
        lift = np.clip(rise, 0.0, None)
        fall = np.clip(-rise, 0.0, None)
        wet = moisture * np.minimum(RAIN_BASE + RAIN_LIFT * lift, RAIN_CAP)
        wet = np.where(here_sea, 0.0, wet)
        #: Спуск за хребтом сушит: воздух греется и дождя не даёт.
        wet = wet * np.exp(-RAIN_LIFT * fall)
        moisture = moisture - wet
        moisture = np.where(here_sea, moisture + EVAPORATION * (1.0 - moisture), moisture * (1.0 - LAND_LOSS))
        moisture = np.clip(moisture, 0.0, 1.0)
        out[r, col] = wet
    land = ~sea
    top = float(np.quantile(out[land], RAIN_TOP_QUANTILE)) if land.any() else 1.0
    scaled = np.clip(out / max(top, 1e-9), 0.0, 1.0)
    texture = noise.fractal(seed + 51, grid.xyz, RAIN_NOISE_LATTICE, 3)
    return np.clip(scaled * (1.0 - RAIN_NOISE) + texture * RAIN_NOISE * scaled.mean() * 2.0, 0.0, 1.0)


#: Предпросмотр зональных биомов: коды и пороги. Оси — температура, °C, и
#: осадки в [0, 1]. Не таблица вольта, а черновик под её проверку.
ZONAL = (
    ("tundra", lambda t, r: t < -2.0),
    ("taiga", lambda t, r: t < 5.0),
    ("desert", lambda t, r: (r < 0.12) & (t >= 18.0)),
    ("semidesert", lambda t, r: (r < 0.2) & (t >= 12.0)),
    ("steppe", lambda t, r: r < 0.3),
    ("savanna", lambda t, r: (t >= 20.0) & (r < 0.5)),
    ("rainforest", lambda t, r: (t >= 20.0) & (r >= 0.65)),
    ("woodland", lambda t, r: (t >= 14.0) & (r < 0.45)),
    ("forest", lambda t, r: np.ones_like(t, dtype=bool)),
)
ZONAL_NAMES = tuple(name for name, _ in ZONAL)


def zonal(temperature_c: np.ndarray, rain01: np.ndarray) -> np.ndarray:
    """Код зонального биома по клеткам: индекс в `ZONAL_NAMES`."""
    out = np.full(temperature_c.shape, len(ZONAL) - 1, dtype=np.uint8)
    done = np.zeros(temperature_c.shape, dtype=bool)
    for code, (_, rule) in enumerate(ZONAL):
        hit = rule(temperature_c, rain01) & ~done
        out[hit] = code
        done |= hit
    return out
