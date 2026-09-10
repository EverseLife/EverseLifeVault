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
from field.grid import WAYS, Grid

#: Во сколько раз материковая плита стоит выше океанической — до шума и хребтов.
CONTINENT_BASE = (0.55, 0.70)
OCEAN_BASE = (0.15, 0.35)
#: Искажение границ плит: решётка и амплитуда шума, гнущего Вороного.
#:
#: Решётка 4 гнула границу на масштабе полушария, и **вблизи она оставалась
#: прямой** — на снимке планеты материки выходили многоугольниками с прямыми
#: рёбрами, а горы садились на них треугольными клиньями (владелец
#: 2026-09-11: «не видно горных цепочек как например тянь шань»). Настоящая
#: сутура виляет на всех масштабах сразу, и решётка тут нужна такая, чтобы
#: изгиб был виден на длине самого хребта.
WARP_LATTICE = 9.0
WARP_AMPLITUDE = 0.14
#: Ширина перехода основы между плитами, в косинусах угла: 0.08 — около
#: 40 км на Терре, и ни одной ступеньки на дне.
BASE_BLEND = 0.08
#: Широкий шум недр — плато и впадины внутри плиты — и его вклад в основу.
#: Октав вчетверо больше, чем было: при четырёх самая мелкая давала рябь в
#: одну сотую размаха, и внутренность плиты выходила столом. Земля между
#: хребтами обязана иметь свой рельеф, иначе цепь стоит на скатерти.
INTERIOR_LATTICE = 3.0
INTERIOR_AMPLITUDE = 0.22
INTERIOR_OCTAVES = 7
FINE_LATTICE = 14.0
FINE_AMPLITUDE = 0.07
#: Длины — доли радиуса планеты (план §3): хребет в четверть радиуса шириной
#: — та же гора на Терре и на Авроре, а не 25 км на обеих.
#: Хребет схождения: полуширина пояса и его высота в долях.
#:
#: Пояс был четвертью радиуса — на Терре три километра поперёк, — и выходил
#: не хребтом, а широким валом: одна гладкая гауссиана, которую эрозия потом
#: чуть подрезала. Цепь узка и длинна, поэтому 0,25 → 0,11, а высота поднята,
#: чтобы гора осталась горой.
BELT_WIDTH_R = 0.11
BELT_HEIGHT = 0.62
#: Насколько ось цепи виляет поперёк себя, доли полуширины пояса, и на какой
#: решётке. Прямая ось — главный признак ненастоящей горы: у Тянь-Шаня она
#: изгибается на длине двух своих ширин.
BELT_WANDER = 0.9
BELT_WANDER_LATTICE = 16.0
#: Сколько высоты цепи приходится на ровный вал, а сколько на гряды. Ноль —
#: чистый гребенчатый фрактал (рвано и без формы), единица — прежний вал.
BELT_SMOOTH = 0.42
#: Вторая цепь, параллельная главной: предгорья и хребет за долиной. Смещение
#: — в долях полуширины пояса, доля высоты — от главной. Так у горной страны
#: появляется поперечный профиль, а не один горб.
BELT_SECOND_AT = 2.1
BELT_SECOND_SHARE = 0.45
#: Квантиль схождения, который считается «полным», и степень, с которой
#: слабое схождение подтягивается к сильному.
#:
#: Без этого высота цепи шла прямо от относительной скорости плит, а та
#: выпадает жребием: одна граница сходилась вдвое сильнее прочих, забирала
#: весь размах — высоту потом нормируют на максимум, — и на планете
#: оказывался один снежный хребет при десятке пологих валов. Нормировка на
#: квантиль делает число горных стран свойством **правила**, а не удачи
#: зерна: полной высоты достигает верхняя шестая часть сходящихся границ на
#: любом жребии.
CONVERGENCE_FULL = 0.84
CONVERGENCE_POWER = 0.6
#: Рифт расхождения: полуширина и глубина; плечи стоят на удвоенной ширине.
RIFT_WIDTH_R = 0.12
RIFT_DEPTH = 0.22
#: Гряды внутри пояса: решётка гребенчатого шума (клеток поперёк диаметра)
#: и сколько октав. Три вместо двух: у хребта обязаны быть отроги отрогов.
RIDGE_LATTICE = 34.0
RIDGE_OCTAVES = 3
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
ARC_OFFSET_R = 0.4
ARC_SPACING_R = 0.045
HOTSPOTS = 3
CONE_RADIUS_R = 0.06
CONE_HEIGHT = 0.22
#: Дальше этого от границы влияние плит не считается.
REACH_R = 1.2


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


def build(
    grid: Grid,
    seed: int,
    count: int,
    continental_share: float,
    sea_level: float,
    volcanoes: float = 1.0,
) -> Plates:
    """`volcanoes` — во сколько раз гуще вулканы, чем на земной планете:
    множитель **плотности**, поэтому шаг дуги делится на его корень, а горячих
    точек становится во столько же раз больше. Единица — Земля и Терра;
    Пироксис живёт вулканизмом, и одной дуги на планету ему мало (владелец
    2026-09-10: «постоянно извергаются вулканы»)."""
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
    dots = np.einsum("cx,px->pc", warped, centres)
    plate = np.argmax(dots, axis=0).astype(np.int16)
    #: Основа — не ступенька на границе, а плавный переход между плитами:
    #: веса софтмакса по близости к центрам, ширина перехода `BASE_BLEND`
    #: в косинусах угла. Хребет делает схождение, а не разница высот плит.
    weight = np.exp((dots - dots.max(axis=0, keepdims=True)) / BASE_BLEND)
    weight /= weight.sum(axis=0, keepdims=True)
    blended_base = np.einsum("pc,p->c", weight, base_of)

    #: Граница: сосед из другой плиты. Нормаль к границе — от своего центра к
    #: чужому, спроецированная на касательную плоскость клетки.
    other = np.full(plate.shape, -1, dtype=np.int16)
    for k in range(WAYS):
        near = grid.shift(plate, k)
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
    reach = grid.cells_for_metres(REACH_R * grid.radius_m)
    convergence, dist_cells = grid.spread(conv_at_boundary, boundary, reach)
    boundary_m = dist_cells * grid.side_m
    #: Чья плита по ту сторону — чтобы знать, где океан ныряет под материк.
    other_side, _ = grid.spread(oth.astype(float), boundary, reach)
    other_continental = continental[other_side.astype(int)]
    cell_continental = continental[own]

    belt_w = BELT_WIDTH_R * grid.radius_m
    rift_w = RIFT_WIDTH_R * grid.radius_m
    converging = np.clip(convergence, 0.0, None)
    #: Схождение нормируется на свой же квантиль: см. `CONVERGENCE_FULL`.
    hot = converging[converging > 0.0]
    full = float(np.quantile(hot, CONVERGENCE_FULL)) if hot.size else 1.0
    converging = np.clip(converging / max(full, 1e-9), 0.0, 1.0) ** CONVERGENCE_POWER
    diverging = np.clip(-convergence, 0.0, None)
    #: Ось цепи виляет поперёк себя: к расстоянию от границы прибавляется
    #: шум, и гауссиана перестаёт быть ровной лентой. Без этого хребет
    #: повторяет ребро Вороного — прямую, которой в горах не бывает.
    wander = noise.centred(seed + 41, warped, BELT_WANDER_LATTICE, 3) * BELT_WANDER * belt_w
    axis = boundary_m + wander
    belt = converging * np.exp(-((axis / belt_w) ** 2))
    #: Вторая цепь за долиной: та же ось, отодвинутая на пару ширин. Горная
    #: страна — не один горб, у неё есть поперечный профиль.
    belt = belt + BELT_SECOND_SHARE * converging * np.exp(
        -(((np.abs(axis) - BELT_SECOND_AT * belt_w) / belt_w) ** 2)
    )
    #: Материковая сторона поднимается шире и выше: складчатость на материке,
    #: над погружением — узкая дуга.
    belt = np.where(cell_continental, belt, belt * 0.6)
    rift = diverging * np.exp(-((boundary_m / rift_w) ** 2))
    shoulder = diverging * np.exp(-(((boundary_m - 2.0 * rift_w) / rift_w) ** 2))

    interior = noise.centred(seed + 21, xyz, INTERIOR_LATTICE, INTERIOR_OCTAVES) * INTERIOR_AMPLITUDE
    fine = noise.centred(seed + 31, xyz, FINE_LATTICE, 4) * FINE_AMPLITUDE
    #: **Гряды кладутся в саму высоту**, а не только в скорость поднятия.
    #: Прежде хребет был гладкой гауссианой, а гребенчатый шум правил лишь
    #: `uplift` — то есть эрозия резала ровный вал, и цепи из него не
    #: выходило. Теперь форма горы фрактальна с самого начала: вал держит
    #: `BELT_SMOOTH` высоты, остальное — гребни, отроги и долины между ними.
    grain = noise.ridged(seed + 81, warped, RIDGE_LATTICE, RIDGE_OCTAVES)
    ranges = belt * (BELT_SMOOTH + (1.0 - BELT_SMOOTH) * grain)
    base = blended_base + interior + fine + BELT_HEIGHT * ranges - RIFT_DEPTH * rift
    base += 0.5 * RIFT_DEPTH * shoulder

    #: Дуга вулканов над погружением: своя плита материковая, чужая — океан.
    subduction = converging > 0.15
    arc_band = subduction & cell_continental & ~other_continental
    arc_line = arc_band & (np.abs(boundary_m - ARC_OFFSET_R * grid.radius_m) <= grid.side_m * 0.75)
    cones = np.zeros(plate.shape, dtype=bool)
    density = max(float(volcanoes), 1e-6)
    #: Конусы вдоль дуги с шагом: клетки дуги в случайном порядке, каждая
    #: следующая не ближе шага дуги к уже взятым. Расстояние — по дуге, а не
    #: по индексам: у равноплощадной сетки индекс соседа ни о чём не говорит.
    on_arc = np.flatnonzero(arc_line)
    spacing = np.cos(ARC_SPACING_R / density**0.5)
    taken: list[np.ndarray] = []
    for pick in rng.permutation(on_arc.size).tolist():
        flat = int(on_arc[pick])
        point = grid.xyz[flat]
        if all(float(point @ t) < spacing for t in taken):
            taken.append(point)
            cones[flat] = True
    #: Горячие точки — на будущей суше: уровень моря режется потом, но
    #: отметка его известна заранее (`terrain.sea_level`), и вулкан больше не
    #: прикидывается квантилем, а сверяется с настоящей водой.
    level = sea_level
    candidates = np.flatnonzero(base >= level)
    if candidates.size:
        hotspots = max(1, int(round(HOTSPOTS * density)))
        for flat in rng.choice(candidates, size=min(hotspots, candidates.size), replace=False):
            cones[flat] = True
    cone_r = grid.cells_for_metres(CONE_RADIUS_R * grid.radius_m)
    cone_dist = grid.dilate_distance(cones, cone_r)
    volcano = np.clip(1.0 - cone_dist / cone_r, 0.0, 1.0)
    base += CONE_HEIGHT * volcano**2

    #: Порода — плавные веса, не ступени: у ступени по расстоянию от границы
    #: эрозия вырезала бы прямой уступ вдоль всей дуги Вороного.
    hardness = np.where(cell_continental, HARD_SHIELD, HARD_OCEAN).astype(float)
    core_w = np.clip(converging / 0.3, 0.0, 1.0) * np.exp(-((boundary_m / (0.6 * belt_w)) ** 2))
    flank_w = np.clip(converging / 0.3, 0.0, 1.0) * np.exp(-(((boundary_m - 1.3 * belt_w) / belt_w) ** 2))
    hardness = hardness + (HARD_BELT_CORE - hardness) * core_w
    hardness = hardness + (HARD_BELT_FLANK - hardness) * flank_w * (1.0 - core_w)
    hardness = hardness + (HARD_RIFT - hardness) * np.clip(rift / 0.5, 0.0, 1.0)
    hardness = hardness + (HARD_ARC - hardness) * np.clip(volcano * 2.0, 0.0, 1.0)
    hardness += noise.centred(seed + 41, xyz, HARD_LATTICE, 3) * HARD_NOISE
    hardness = np.clip(hardness, HARD_FLOOR, HARD_CEIL)

    #: Поднятие идёт по тем же грядам, что и высота: вода режет хребет там
    #: же, где он и растёт, и долины ложатся вдоль гряд, а не поперёк них.
    uplift = belt * (0.55 + 0.45 * grain)
    uplift = np.clip(uplift / max(float(uplift.max()), 1e-9), 0.0, 1.0)
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


__all__ = ["Plates", "build"]
