# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Сток: куда течёт каждая клетка, сколько площади через неё проходит, где вода.

Три шага, как в любой гидрологии на сетке:

1. **Заливка** (priority flood): впадины поднимаются до уровня своего слива,
   чтобы у каждой клетки суши был путь к морю. Поднятое — озеро.
2. **Приёмник**: из восьми соседей тот, к которому круче всего вниз по
   залитому рельефу; у моря и у дна озера приёмник — сама клетка.
3. **Накопление**: клетки перебираются сверху вниз, и каждая отдаёт свою
   площадь приёмнику. Где площади много — река; река сливается с рекой
   сама собой, без единой нитки, нарисованной рукой.

Заливка и накопление — циклы на Python: у них есть порядок, который numpy
не выражает. На сетке в 500 м это секунды на планету, и это цена одной
сборки вольта, не старта сервера (план §4.8).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

from field.grid import OFFSETS, Grid

#: Насколько залитая клетка выше своего слива: чтобы по плоскому дну озера
#: вода всё-таки шла к выходу, а не стояла.
FILL_EPS = 0.01
#: Озеро — где заливка подняла клетку выше этого, метры.
LAKE_DEPTH_M = 0.5


@dataclass(frozen=True)
class Flow:
    filled: np.ndarray  # залитая высота, м
    receiver: np.ndarray  # плоский индекс приёмника, (rows*cols,)
    order: np.ndarray  # плоские индексы сверху вниз
    slope: np.ndarray  # уклон к приёмнику, м/м, (rows, cols)
    distance: np.ndarray  # расстояние до приёмника, м, (rows, cols)
    area_m2: np.ndarray  # накопленная площадь, м², (rows, cols)
    lake: np.ndarray  # bool: клетка суши под водой озера


def fill(height: np.ndarray, sea: np.ndarray, grid: Grid) -> np.ndarray:
    """Priority flood: высоты, у которых у каждой клетки суши есть спуск к морю."""
    rows, cols = height.shape
    h = height.ravel().tolist()
    sea_flat = sea.ravel()
    filled = [float("inf")] * (rows * cols)
    #: Списки, не массивы: цикл ниже трогает по одной клетке, и индексация
    #: numpy поштучно в разы дороже списка.
    closed = sea_flat.tolist()
    #: Затравка — море у берега: внутренние клетки моря закрыты и так, а в
    #: кучу их класть незачем.
    coast = np.zeros_like(sea)
    for dr, dc in OFFSETS:
        coast |= sea & ~grid.shift(sea, dr, dc)
    heap: list[tuple[float, int]] = []
    for flat in np.flatnonzero(coast.ravel()).tolist():
        filled[flat] = h[flat]
        heap.append((h[flat], flat))
    for flat in np.flatnonzero(sea_flat).tolist():
        filled[flat] = h[flat]
    heapq.heapify(heap)
    offsets = [(dr, dc) for dr, dc in OFFSETS]
    while heap:
        level, flat = heapq.heappop(heap)
        r, c = divmod(flat, cols)
        for dr, dc in offsets:
            rr = r + dr
            if rr < 0 or rr >= rows:
                continue
            n = rr * cols + (c + dc) % cols
            if closed[n]:
                continue
            closed[n] = True
            value = h[n]
            if value < level + FILL_EPS:
                value = level + FILL_EPS
            filled[n] = value
            heapq.heappush(heap, (value, n))
    out = np.array(filled, dtype=float).reshape(rows, cols)
    #: Клетка, до которой вода не дошла (нет моря вовсе — сухая планета), остаётся собой.
    return np.where(np.isinf(out), height, out)


def receivers(filled: np.ndarray, grid: Grid) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Приёмник каждой клетки, уклон к нему и расстояние до него."""
    rows, cols = filled.shape
    best_slope = np.zeros_like(filled)
    best_index = np.arange(rows * cols, dtype=np.int64).reshape(rows, cols)
    best_dist = np.full(filled.shape, grid.step_m)
    for k, (dr, dc) in enumerate(OFFSETS):
        dist = grid.distances[k][:, None]
        slope = (filled - grid.shift(filled, dr, dc)) / dist
        better = slope > best_slope
        best_slope = np.where(better, slope, best_slope)
        best_index = np.where(better, grid.neighbour_index(dr, dc), best_index)
        best_dist = np.where(better, dist, best_dist)
    return best_index.ravel(), best_slope, best_dist


def accumulate(receiver: np.ndarray, order: np.ndarray, area: np.ndarray) -> np.ndarray:
    """Площадь, стекающая через каждую клетку: своя плюс всё, что выше."""
    total = area.ravel().astype(float).tolist()
    recv = receiver.tolist()
    for i in order.tolist():
        j = recv[i]
        if j != i:
            total[j] += total[i]
    return np.array(total).reshape(area.shape)


def route(height: np.ndarray, sea: np.ndarray, grid: Grid) -> Flow:
    filled = fill(height, sea, grid)
    receiver, slope, distance = receivers(filled, grid)
    order = np.argsort(filled, axis=None)[::-1]
    area = np.repeat(grid.area_m2[:, None], grid.cols, axis=1)
    acc = accumulate(receiver, order, area)
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
    inflow = [0.0] * recv.__len__()
    src = source.ravel().tolist()
    kp = keep.ravel().tolist()
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
    shape = source.shape
    return np.array(settled).reshape(shape), np.array(passed).reshape(shape)
