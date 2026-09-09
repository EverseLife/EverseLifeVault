# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Плиты, порода и поднятие: кости планеты до того, как за неё взялась вода (план §4.2).

Десяток центров на сфере, у каждого — вектор дрейфа. Клетка принадлежит
ближайшему центру, но «ближайший» искажён шумом, чтобы границы были рваными,
а не сотами. На границе относительная скорость плит, спроецированная на
нормаль к границе, даёт **схождение** (положительное) или **расхождение**;
схождение поднимает линейный хребет и держит его поднятием на всю эрозию,
расхождение прорезает рифт с плечами и цепочкой озёр.

**Порода** — твёрдость в [0.25, 1]: щит и ядро хребта твёрдые, осадочные
шлейфы у подножий и дно впадин мягкие. Без неё каньона не бывает: вода режет
мягкое широко, твёрдое — узко и глубоко (§4.3). **Вулканы** встают дугой над
погружением океанической плиты под материковую и парой горячих точек.

На выходе всё в долях: высота-основа в [0, 1] (уровень моря режется потом
квантилем), поднятие в [0, 1], твёрдость; в метры их переводит конвейер.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from field import noise
from field.grid import OFFSETS, Grid

#: Во сколько раз материковая плита стоит выше океанической — до шума и хребтов.
CONTINENT_BASE = (0.55, 0.70)
OCEAN_BASE = (0.15, 0.35)
#: Искажение границ плит: решётка и амплитуда шума, гнущего Вороного.
WARP_LATTICE = 4.0
WARP_AMPLITUDE = 0.09
#: Широкий шум недр — плато и впадины внутри плиты — и его вклад в основу.
INTERIOR_LATTICE = 3.0
INTERIOR_AMPLITUDE = 0.16
FINE_LATTICE = 14.0
FINE_AMPLITUDE = 0.05
#: Хребет схождения: полуширина пояса в метрах и его высота в долях.
BELT_WIDTH_M = 25_000.0
BELT_HEIGHT = 0.45
#: Рифт расхождения: полуширина и глубина; плечи стоят на удвоенной ширине.
RIFT_WIDTH_M = 12_000.0
RIFT_DEPTH = 0.22
#: Твёрдость породы по происхождению.
HARD_SHIELD = 0.78
HARD_OCEAN = 0.45
HARD_BELT_CORE = 0.98
HARD_BELT_FLANK = 0.55
HARD_RIFT = 0.50
HARD_ARC = 0.70
HARD_NOISE = 0.15
HARD_LATTICE = 10.0
HARD_FLOOR, HARD_CEIL = 0.25, 1.0
#: Дуга вулканов: на каком расстоянии за границей погружения и с каким шагом.
ARC_OFFSET_M = 40_000.0
ARC_SPACING_CELLS = 9
HOTSPOTS = 3
CONE_RADIUS_M = 6_000.0
CONE_HEIGHT = 0.22
#: Дальше этого от границы влияние плит не считается.
REACH_M = 120_000.0


@dataclass(frozen=True)
class Plates:
    plate: np.ndarray  # id плиты, int16
    base: np.ndarray  # высота-основа, [0, 1]
    uplift: np.ndarray  # скорость поднятия, [0, 1]
    hardness: np.ndarray  # твёрдость породы, [HARD_FLOOR, HARD_CEIL]
    boundary_m: np.ndarray  # расстояние до границы плит, метры
    convergence: np.ndarray  # схождение ближайшей границы, [-1, 1]
    rift: np.ndarray  # доля «рифтовости» клетки, [0, 1]
    volcano: np.ndarray  # доля «вулканичности» клетки, [0, 1]
    continental: np.ndarray  # bool по клеткам


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def _tangent(rng: np.random.Generator, at: np.ndarray) -> np.ndarray:
    """Случайный единичный вектор, касательный к сфере в точке `at`."""
    v = rng.normal(size=at.shape)
    v -= np.sum(v * at, axis=-1, keepdims=True) * at
    return _unit(v)


def build(grid: Grid, seed: int, count: int, continental_share: float) -> Plates:
    rng = np.random.default_rng(seed)
    count = max(2, int(count))
    centres = _unit(rng.normal(size=(count, 3)))
    speed = rng.uniform(0.3, 1.0, size=(count, 1))
    velocity = _tangent(rng, centres) * speed
    continental = rng.random(count) < continental_share
    if not continental.any():
        continental[rng.integers(count)] = True
    base_of = np.where(
        continental,
        rng.uniform(*CONTINENT_BASE, size=count),
        rng.uniform(*OCEAN_BASE, size=count),
    )

    xyz = grid.xyz
    warp = np.stack(
        [noise.centred(seed + 11 + i, xyz, WARP_LATTICE, 3) for i in range(3)], axis=-1
    )
    warped = _unit(xyz + WARP_AMPLITUDE * warp)
    dots = np.einsum("rcx,px->prc", warped, centres)
    plate = np.argmax(dots, axis=0).astype(np.int16)

    #: Граница: сосед из другой плиты. Нормаль к границе — от своего центра к
    #: чужому, спроецированная на касательную плоскость клетки.
    other = np.full(plate.shape, -1, dtype=np.int16)
    for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        near = grid.shift(plate, dr, dc)
        other = np.where((other < 0) & (near != plate), near, other)
    boundary = other >= 0
    own = plate.astype(int)
    oth = np.where(boundary, other, plate).astype(int)
    normal = centres[oth] - centres[own]
    normal -= np.sum(normal * xyz, axis=-1, keepdims=True) * xyz
    normal = _unit(normal)
    relative = velocity[own] - velocity[oth]
    conv_at_boundary = np.where(boundary, np.sum(relative * normal, axis=-1), 0.0)
    #: На двух сторонах одной границы схождение читается одинаково: нормали
    #: противоположны, и относительные скорости тоже.
    reach = grid.cells_for_metres(REACH_M)
    convergence, dist_cells = grid.spread(conv_at_boundary, boundary, reach)
    boundary_m = dist_cells * grid.step_m
    #: Чья плита по ту сторону — чтобы знать, где океан ныряет под материк.
    other_side, _ = grid.spread(oth.astype(float), boundary, reach)
    other_continental = continental[other_side.astype(int)]
    cell_continental = continental[own]

    belt_w = BELT_WIDTH_M
    rift_w = RIFT_WIDTH_M
    converging = np.clip(convergence, 0.0, None)
    diverging = np.clip(-convergence, 0.0, None)
    belt = converging * np.exp(-((boundary_m / belt_w) ** 2))
    #: Материковая сторона поднимается шире и выше: складчатость на материке,
    #: над погружением — узкая дуга.
    belt = np.where(cell_continental, belt, belt * 0.6)
    rift = diverging * np.exp(-((boundary_m / rift_w) ** 2))
    shoulder = diverging * np.exp(-(((boundary_m - 2.0 * rift_w) / rift_w) ** 2))

    interior = noise.centred(seed + 21, xyz, INTERIOR_LATTICE, 4) * INTERIOR_AMPLITUDE
    fine = noise.centred(seed + 31, xyz, FINE_LATTICE, 3) * FINE_AMPLITUDE
    base = base_of[own] + interior + fine + BELT_HEIGHT * belt - RIFT_DEPTH * rift
    base += 0.5 * RIFT_DEPTH * shoulder

    #: Дуга вулканов над погружением: своя плита материковая, чужая — океан.
    subduction = converging > 0.15
    arc_band = subduction & cell_continental & ~other_continental
    arc_line = arc_band & (np.abs(boundary_m - ARC_OFFSET_M) <= grid.step_m * 0.75)
    rows_idx, cols_idx = np.nonzero(arc_line)
    cones = np.zeros(plate.shape, dtype=bool)
    if rows_idx.size:
        keep = (rows_idx // ARC_SPACING_CELLS + cols_idx // ARC_SPACING_CELLS) % 2 == 0
        keep &= (rows_idx % ARC_SPACING_CELLS == 0) | (cols_idx % ARC_SPACING_CELLS == 0)
        cones[rows_idx[keep], cols_idx[keep]] = True
    land_like = base_of[own] >= CONTINENT_BASE[0]
    candidates = np.flatnonzero(land_like)
    if candidates.size:
        for flat in rng.choice(candidates, size=min(HOTSPOTS, candidates.size), replace=False):
            cones.flat[flat] = True
    cone_r = grid.cells_for_metres(CONE_RADIUS_M)
    cone_dist = grid.dilate_distance(cones, cone_r)
    volcano = np.clip(1.0 - cone_dist / cone_r, 0.0, 1.0)
    base += CONE_HEIGHT * volcano**2

    hardness = np.where(cell_continental, HARD_SHIELD, HARD_OCEAN)
    core = converging > 0.1
    hardness = np.where(core & (boundary_m < 0.5 * belt_w), HARD_BELT_CORE, hardness)
    hardness = np.where(
        core & (boundary_m >= 0.5 * belt_w) & (boundary_m < 2.0 * belt_w), HARD_BELT_FLANK, hardness
    )
    hardness = np.where(rift > 0.3, HARD_RIFT, hardness)
    hardness = np.where(volcano > 0.0, HARD_ARC, hardness)
    hardness += noise.centred(seed + 41, xyz, HARD_LATTICE, 3) * HARD_NOISE
    hardness = np.clip(hardness, HARD_FLOOR, HARD_CEIL)

    uplift = np.clip(belt / max(float(belt.max()), 1e-9), 0.0, 1.0)
    return Plates(
        plate=plate,
        base=np.clip(base, 0.0, 1.5),
        uplift=uplift,
        hardness=hardness,
        boundary_m=boundary_m,
        convergence=np.clip(convergence, -1.0, 1.0),
        rift=np.clip(rift, 0.0, 1.0),
        volcano=volcano,
        continental=cell_continental,
    )


__all__ = ["Plates", "build", "OFFSETS"]
