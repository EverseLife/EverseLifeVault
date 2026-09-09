# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Сток: куда течёт каждая клетка, сколько площади через неё проходит, где вода.

Три шага, как в любой гидрологии на сетке:

1. **Заливка** (priority flood): впадины поднимаются до уровня своего слива,
   чтобы у каждой клетки суши был путь к морю. Поднятое — озеро.
2. **Приёмник**: из соседей тот, к которому круче всего вниз по залитому
   рельефу; у моря и у дна озера приёмник — сама клетка.
3. **Накопление**: клетки перебираются сверху вниз, и каждая отдаёт свою
   площадь приёмнику. Где площади много — река; река сливается с рекой
   сама собой, без единой нитки, нарисованной рукой.

Заливка и накопление — циклы на Python: у них есть порядок, который numpy
не выражает. Это цена одной сборки вольта, не старта сервера (план §4.8).

На равноплощадной сетке (D-328) сосед — номер стороны, а не сдвиг индекса,
и площадь клетки — одно число на планету: сток больше не идёт по узким
полярным клеткам иначе, чем по экваториальным.
"""

from __future__ import annotations

import array
import heapq
from dataclasses import dataclass

import numpy as np

from field.grid import WAYS, Grid

#: Насколько залитая клетка выше своего слива: чтобы по плоскому дну озера
#: вода всё-таки шла к выходу, а не стояла.
FILL_EPS = 0.01
#: Озеро — где заливка подняла клетку выше этого, метры.
LAKE_DEPTH_M = 3.0
#: Предвзятость выбора спуска: во столько раз уклон в глазах клетки может
#: быть больше или меньше честного.
WOBBLE = 0.6


def _jitter(grid: Grid, salt: int = 0) -> np.ndarray:
    """Число в [-1, 1] на клетку, одно и то же на любой машине: хеш индекса."""
    flat = np.arange(grid.count, dtype=np.int64)
    h = (flat * 2654435761 + 97 + salt * 40503) & 0xFFFFFFFF
    h = (h ^ (h >> 15)) * 2246822519 & 0xFFFFFFFF
    return h / float(0x100000000) * 2.0 - 1.0


def _ways(grid: Grid) -> array.array:
    """Соседи всех клеток одним плоским рядом целых для циклов на Python.

    Не `tolist()`: девять миллионов объектов `int` на Терре — это треть
    гигабайта, а `array` держит их четырьмя байтами и делает целое только
    на чтении.
    """
    flat = array.array("i")
    assert flat.itemsize == 4, "тип 'i' обязан быть четырёхбайтным"
    flat.frombytes(np.ascontiguousarray(grid.near.T, dtype=np.int32).tobytes())
    return flat


@dataclass(frozen=True)
class Flow:
    filled: np.ndarray  # залитая высота, м
    receiver: np.ndarray  # номер клетки-приёмника
    order: np.ndarray  # номера клеток сверху вниз
    slope: np.ndarray  # уклон к приёмнику, м/м
    distance: np.ndarray  # расстояние до приёмника, м
    area_m2: np.ndarray  # накопленная площадь, м²
    lake: np.ndarray  # bool: клетка суши под водой озера


def fill(height: np.ndarray, sea: np.ndarray, grid: Grid) -> np.ndarray:
    """Priority flood: высоты, у которых у каждой клетки суши есть спуск к морю."""
    count = grid.count
    h = height.ravel().tolist()
    sea_flat = np.asarray(sea).ravel()
    filled = [float("inf")] * count
    #: Списки, не массивы: цикл ниже трогает по одной клетке, и индексация
    #: numpy поштучно в разы дороже списка.
    closed = sea_flat.tolist()
    #: Затравка — море у берега: внутренние клетки моря закрыты и так, а в
    #: кучу их класть незачем.
    coast = np.zeros(count, dtype=bool)
    for k in range(WAYS):
        coast |= sea_flat & ~sea_flat[grid.near[k]]
    heap: list[tuple[float, int]] = []
    for flat in np.flatnonzero(coast).tolist():
        filled[flat] = h[flat]
        heap.append((h[flat], flat))
    for flat in np.flatnonzero(sea_flat).tolist():
        filled[flat] = h[flat]
    heapq.heapify(heap)
    ways = _ways(grid)
    while heap:
        level, flat = heapq.heappop(heap)
        #: Свободное место соседа — сама клетка, а она к этому мигу закрыта.
        for n in ways[flat * WAYS : flat * WAYS + WAYS]:
            if closed[n]:
                continue
            closed[n] = True
            value = h[n]
            if value < level + FILL_EPS:
                value = level + FILL_EPS
            filled[n] = value
            heapq.heappush(heap, (value, n))
    out = np.array(filled, dtype=float)
    #: Клетка, до которой вода не дошла (нет моря вовсе — сухая планета), остаётся собой.
    return np.where(np.isinf(out), np.asarray(height).ravel(), out)


def receivers(
    filled: np.ndarray, grid: Grid, wobble: float = 0.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Приёмник каждой клетки, уклон к нему и расстояние до него.

    Приёмник всегда ниже — среди соседей выбирается спуск. Какой из
    спусков, решает уклон, помноженный на `1 ± wobble` от хеша клетки и
    стороны: на гладком склоне честно самый крутой — одна и та же прямая
    через всю гору, а чуть предвзятый выбор ломает её в русло, которое
    вьётся. Уклон возвращается честный.
    """
    count = grid.count
    best_score = np.zeros(count)
    best_slope = np.zeros(count)
    best_index = np.arange(count, dtype=np.int64)
    best_dist = np.full(count, grid.side_m)
    for k in range(WAYS):
        dist = grid.distances[k]
        slope = (filled - filled[grid.near[k]]) / dist
        score = slope * (1.0 + wobble * _jitter(grid, k)) if wobble else slope
        better = (slope > 0.0) & (score > best_score)
        best_score = np.where(better, score, best_score)
        best_slope = np.where(better, slope, best_slope)
        best_index = np.where(better, grid.near[k], best_index)
        best_dist = np.where(better, dist, best_dist)
    return best_index, best_slope, best_dist


def accumulate(receiver: np.ndarray, order: np.ndarray, area: np.ndarray) -> np.ndarray:
    """Площадь, стекающая через каждую клетку: своя плюс всё, что выше."""
    total = area.astype(float).tolist()
    recv = receiver.tolist()
    for i in order.tolist():
        j = recv[i]
        if j != i:
            total[j] += total[i]
    return np.array(total)


def route(height: np.ndarray, sea: np.ndarray, grid: Grid) -> Flow:
    filled = fill(height, sea, grid)
    receiver, slope, distance = receivers(filled, grid, WOBBLE)
    order = np.argsort(filled)[::-1]
    acc = accumulate(receiver, order, np.full(grid.count, grid.area_m2))
    lake = (filled - height > LAKE_DEPTH_M) & ~sea
    return Flow(
        filled=filled,
        receiver=receiver,
        order=order,
        slope=slope,
        distance=distance,
        area_m2=acc,
        lake=lake,
    )


def downstream(
    flow: Flow, source: np.ndarray, keep: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Провести `source` (объём на клетку) вниз по стоку: в каждой клетке
    оседает доля `keep` того, что через неё прошло, остальное идёт дальше.
    Возвращает осевшее и прошедшее насквозь."""
    recv = flow.receiver.tolist()
    inflow = [0.0] * len(recv)
    src = np.broadcast_to(source, (len(recv),)).tolist()
    kp = np.broadcast_to(keep, (len(recv),)).tolist()
    settled = [0.0] * len(recv)
    passed = [0.0] * len(recv)
    for i in flow.order.tolist():
        total = src[i] + inflow[i]
        stay = total * kp[i]
        settled[i] = stay
        through = total - stay
        passed[i] = through
        j = recv[i]
        if j != i:
            inflow[j] += through
    return np.array(settled), np.array(passed)
