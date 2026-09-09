# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Сетка поля: шаг в метрах, число клеток от радиуса планеты (план §4.1).

Строки — широта, столбцы — долгота, клетка — квадрат `step_m` на экваторе.
По долготе сетка замкнута (`np.roll`), по широте край повторяет себя: через
полюс ничего не течёт. Расстояние до восточного соседа сжимается косинусом
широты — этим и лечится половина полюсных артефактов (§4.9); вторая половина,
заморозка выше линии льда, — дело эрозии.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np

#: Восемь соседей клетки: (сдвиг по строке, сдвиг по столбцу).
OFFSETS: tuple[tuple[int, int], ...] = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)
#: Ниже этой доли шага ширина клетки не опускается: у самого полюса клетка
#: вырождается в ноль, и уклон к соседу стал бы бесконечным.
DX_FLOOR = 0.02


@dataclass(frozen=True)
class Grid:
    radius_m: float
    step_m: float
    rows: int
    cols: int

    @classmethod
    def of(cls, radius_m: float, step_m: float) -> Grid:
        """Сетка, у которой клетка на экваторе — `step_m`, столбцов вдвое больше строк."""
        rows = max(4, int(round(math.pi * radius_m / step_m)))
        return cls(radius_m=float(radius_m), step_m=float(step_m), rows=rows, cols=2 * rows)

    @cached_property
    def lat(self) -> np.ndarray:
        """Широта середины каждой строки, с юга на север, градусы."""
        return -90.0 + (np.arange(self.rows) + 0.5) * (180.0 / self.rows)

    @cached_property
    def lon(self) -> np.ndarray:
        return -180.0 + (np.arange(self.cols) + 0.5) * (360.0 / self.cols)

    @cached_property
    def lat2d(self) -> np.ndarray:
        return np.repeat(self.lat[:, None], self.cols, axis=1)

    @cached_property
    def lon2d(self) -> np.ndarray:
        return np.repeat(self.lon[None, :], self.rows, axis=0)

    @cached_property
    def xyz(self) -> np.ndarray:
        """Единичные векторы центров клеток, (rows, cols, 3)."""
        phi, lam = np.radians(self.lat2d), np.radians(self.lon2d)
        return np.stack(
            [np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)], axis=-1
        )

    @cached_property
    def dx(self) -> np.ndarray:
        """Ширина клетки в каждой строке, метры: шаг на косинус широты, не ниже пола."""
        return np.maximum(self.step_m * np.cos(np.radians(self.lat)), self.step_m * DX_FLOOR)

    @property
    def dy(self) -> float:
        return self.step_m

    @cached_property
    def area_m2(self) -> np.ndarray:
        """Площадь клетки в каждой строке, м²."""
        return self.dx * self.dy

    @cached_property
    def distances(self) -> np.ndarray:
        """Расстояние до каждого из восьми соседей по строкам, (8, rows), метры."""
        out = np.empty((len(OFFSETS), self.rows))
        for k, (dr, dc) in enumerate(OFFSETS):
            out[k] = np.hypot(dc * self.dx, dr * self.dy)
        return out

    def shift(self, a: np.ndarray, dr: int, dc: int) -> np.ndarray:
        """Массив, в котором в клетке (r, c) стоит значение из (r + dr, c + dc).

        По долготе с заворотом, по широте край повторяет сам себя.
        """
        out = np.roll(a, -dc, axis=1) if dc else a
        if dr > 0:
            out = np.concatenate([out[dr:], np.repeat(out[-1:], dr, axis=0)], axis=0)
        elif dr < 0:
            out = np.concatenate([np.repeat(out[:1], -dr, axis=0), out[:dr]], axis=0)
        return out

    def neighbour_index(self, dr: int, dc: int) -> np.ndarray:
        """Плоский индекс соседа (r + dr, c + dc) для каждой клетки; за краем — своя строка."""
        r = np.clip(np.arange(self.rows)[:, None] + dr, 0, self.rows - 1)
        c = (np.arange(self.cols)[None, :] + dc) % self.cols
        return (r * self.cols + c).astype(np.int64)

    def cell(self, lat: float, lon: float) -> tuple[int, int]:
        row = int((lat + 90.0) / (180.0 / self.rows))
        col = int((lon + 180.0) / (360.0 / self.cols))
        return min(self.rows - 1, max(0, row)), col % self.cols

    def cells_for_metres(self, metres: float) -> int:
        return max(1, int(round(metres / self.step_m)))

    def dilate_distance(self, mask: np.ndarray, max_cells: int) -> np.ndarray:
        """Расстояние в клетках до ближайшей клетки маски, не дальше `max_cells`
        (дальше — `max_cells`). Шаг по диагонали считается за один: для
        метров это грубо, для «рядом ли вода» — довольно."""
        dist = np.where(mask, 0.0, np.inf)
        for k in range(1, max_cells + 1):
            reached = np.zeros(mask.shape, dtype=bool)
            for dr, dc in OFFSETS:
                reached |= self.shift(dist, dr, dc) < k
            dist = np.where(np.isinf(dist) & reached, float(k), dist)
        return np.where(np.isinf(dist), float(max_cells), dist)

    def spread(self, value: np.ndarray, source: np.ndarray, max_cells: int) -> tuple[np.ndarray, np.ndarray]:
        """Значение ближайшей клетки-источника, разнесённое по сетке волной,
        и расстояние до неё в клетках. Где источников нет в `max_cells` —
        ноль и `max_cells`."""
        dist = np.where(source, 0.0, np.inf)
        carried = np.where(source, value, 0.0)
        for k in range(1, max_cells + 1):
            for dr, dc in OFFSETS:
                near = self.shift(dist, dr, dc) == k - 1
                take = np.isinf(dist) & near
                if take.any():
                    carried = np.where(take, self.shift(carried, dr, dc), carried)
                    dist = np.where(take, float(k), dist)
        return carried, np.where(np.isinf(dist), float(max_cells), dist)

    def laplacian(self, a: np.ndarray) -> np.ndarray:
        """Среднее по восьми соседям минус своё: безразмерная кривизна."""
        total = np.zeros_like(a)
        for dr, dc in OFFSETS:
            total += self.shift(a, dr, dc)
        return total / len(OFFSETS) - a

    def gradient(self, a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Производные по востоку и по северу, на метр."""
        east = (self.shift(a, 0, 1) - self.shift(a, 0, -1)) / (2.0 * self.dx[:, None])
        north = (self.shift(a, 1, 0) - self.shift(a, -1, 0)) / (2.0 * self.dy)
        return east, north

    def slope(self, a: np.ndarray) -> np.ndarray:
        """Крутизна: модуль градиента, м/м."""
        east, north = self.gradient(a)
        return np.hypot(east, north)

    def local_range(self, a: np.ndarray, cells: int) -> np.ndarray:
        """Размах значений в окне ±cells: местный рельеф."""
        top, bottom = a.copy(), a.copy()
        for _ in range(cells):
            t, b = top.copy(), bottom.copy()
            for dr, dc in OFFSETS:
                t = np.maximum(t, self.shift(top, dr, dc))
                b = np.minimum(b, self.shift(bottom, dr, dc))
            top, bottom = t, b
        return top - bottom

    def resample_from(self, a: np.ndarray, other: Grid) -> np.ndarray:
        """Массив другой сетки, прочитанный билинейно в центрах клеток этой."""
        fi = (self.lat + 90.0) / (180.0 / other.rows) - 0.5
        fj = (self.lon + 180.0) / (360.0 / other.cols) - 0.5
        i0 = np.clip(np.floor(fi).astype(int), 0, other.rows - 1)
        i1 = np.clip(i0 + 1, 0, other.rows - 1)
        ti = np.clip(fi - i0, 0.0, 1.0)
        j0 = np.floor(fj).astype(int) % other.cols
        j1 = (j0 + 1) % other.cols
        tj = (fj - np.floor(fj))
        top = a[i0][:, j0] * (1 - tj)[None, :] + a[i0][:, j1] * tj[None, :]
        bottom = a[i1][:, j0] * (1 - tj)[None, :] + a[i1][:, j1] * tj[None, :]
        return top * (1 - ti)[:, None] + bottom * ti[:, None]
