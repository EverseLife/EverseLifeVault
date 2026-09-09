# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Провинции: суша, разрезанная на области с именем и характером (план §7).

Провинция — не биом, а имя: она пересекает биомы и сдвигает их числа.
Столько провинций, сколько строк в `data/provinces.yaml` для планеты, от
того же зерна, что и всё поле. Центры садятся на сушу с отступом друг от
друга, чтобы области были одного порядка, клетка идёт к ближайшему центру
по дуге в искривлённых шумом координатах — так границы рваные, а не соты.
Море провинции не имеет; озеро внутри суши — имеет, оно её часть.

Сдвиги провинции — осадков и температуры — ложатся на растры **до**
классификатора (§5): «Солёный клин» сух и на карте биомов, а не только
подписью. Множитель жилы читает разведка при находке.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from field import noise
from field.grid import Grid

#: Искажение границ: решётка и амплитуда шума, гнущего Вороного.
WARP_LATTICE = 8.0
WARP_AMPLITUDE = 0.04
#: Центры не ближе этой доли «ровной» ширины провинции друг к другу:
#: ширина — корень из площади суши на провинцию.
SPACING_SHARE = 0.55
#: Сколько раз пробовать посадить центр, прежде чем ослабить отступ.
TRIES = 4000


@dataclass(frozen=True)
class Provinces:
    raster: np.ndarray  # uint8: 0 — нет провинции (море), k — строка k-1 таблицы
    table: list[dict]  # строки data/provinces.yaml этой планеты, в порядке кодов


def build(grid: Grid, seed: int, land: np.ndarray, table: list[dict]) -> Provinces:
    count = len(table)
    raster = np.zeros(land.shape, dtype=np.uint8)
    if count == 0 or not land.any():
        return Provinces(raster=raster, table=list(table))
    assert count < 256, "провинций больше, чем кодов в байте"
    rng = np.random.default_rng(seed + 101)
    xyz = grid.xyz
    area = np.repeat(grid.area_m2[:, None], grid.cols, axis=1)
    land_area = float(area[land].sum())
    spacing = SPACING_SHARE * (land_area / count) ** 0.5
    #: Центры: случайные клетки суши с отступом; отступ ослабляется, если
    #: суша слишком дробная, чтобы вместить их все.
    candidates = np.flatnonzero(land.ravel())
    centres: list[np.ndarray] = []
    min_cos = np.cos(spacing / grid.radius_m)
    while len(centres) < count:
        placed = False
        for _ in range(TRIES):
            flat = int(rng.choice(candidates))
            point = xyz.reshape(-1, 3)[flat]
            if all(float(point @ c) < min_cos for c in centres):
                centres.append(point)
                placed = True
                break
        if not placed:
            min_cos = np.cos(np.arccos(min_cos) * 0.7)
    seeds = np.stack(centres)
    warp = np.stack(
        [noise.centred(seed + 111 + i, xyz, WARP_LATTICE, 3) for i in range(3)], axis=-1
    )
    warped = xyz + WARP_AMPLITUDE * warp
    warped /= np.maximum(np.linalg.norm(warped, axis=-1, keepdims=True), 1e-12)
    best = np.full(land.shape, -1.0)
    nearest = np.zeros(land.shape, dtype=np.int32)
    for k in range(count):
        dot = warped @ seeds[k]
        better = dot > best
        best = np.where(better, dot, best)
        nearest = np.where(better, k, nearest)
    raster[land] = (nearest[land] + 1).astype(np.uint8)
    return Provinces(raster=raster, table=list(table))


def shifts(provinces: Provinces, key: str) -> np.ndarray:
    """Сдвиг `key` (`rain_shift`, `temp_shift_c`) по клеткам: ноль вне провинций."""
    lookup = np.array([0.0] + [float(row.get(key, 0.0)) for row in provinces.table])
    return lookup[provinces.raster]
