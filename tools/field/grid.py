# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Сетка поля: равноплощадные клетки HEALPix, шаг в метрах (план §4.1, D-328).

Клетки все одной площади и одного размера — у полюса такая же, как на
экваторе. Отсюда всё остальное устройство этого модуля:

* массив поля **плоский**, `(12 nside²,)`, а не «строки на столбцы»: у
  равноплощадной сетки нет ни строк, ни столбцов;
* сосед адресуется **номером стороны** `k`, а не сдвигом `(dr, dc)`:
  `shift(a, k)` — это выборка `a[near[k]]`, а не прокрутка массива;
* площадь клетки — **число**, а не столбик по широтам, и квантиль по
  площади становится обычным квантилем;
* полюс перестаёт быть особым случаем: сжатия по косинусу широты нет,
  вырожденных клеток нет, и полярной ряби, из-за которой сетку меняли,
  тоже нет (§4.9).

Шаг по сетке — шаг **по сфере**: пройти столько-то метров в таком-то
направлении и спросить, в какую клетку пришёл (`healpix.offset` и
`ang2pix`). Так ходят и заливка расстояний, и прогулка переписи, и это
дешевле таблиц: попадание точки в клетку у HEALPix — арифметика, а не поиск.

`step_m` здесь — то, что просит вольт (`terrain.step_m`), а `side_m` — то,
что получилось: дробность `nside` целая, и сторона клетки садится на
просимый шаг с точностью долей процента.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from field import healpix

#: Сколько мест отведено соседям клетки: восемь настоящих и запас на стыки
#: базовых граней (см. `healpix.neighbours`). Свободное место занято самой
#: клеткой, поэтому обход по сторонам можно писать без проверок: разность
#: со своим значением — ноль, и в выборе спуска такое место не участвует.
WAYS = healpix.WAYS
#: Стороны света, по которым идёт прыжковая заливка расстояний.
LOOKS = 8
#: Насколько далеко тянется вес при чтении с другой сетки, в сторонах её
#: клетки: ядро сглаживания вместо билинейки, которой на HEALPix нет.
SMOOTH_REACH = 1.5
#: По скольку клеток решаются веса производных за раз (см. `_fit`).
BLOCK = 1 << 16
#: Во сколько раз лапласиан меньше второй производной на квадрат стороны.
#: Это доля прежнего «среднего по восьми соседям минус своё» — так
#: коэффициент оплывания в эрозии остаётся тем же числом, что и был.
LAPLACE_SHARE = 3.0 / 8.0


@dataclass(frozen=True)
class Grid:
    radius_m: float
    step_m: float
    nside: int

    @classmethod
    def of(cls, radius_m: float, step_m: float) -> Grid:
        """Сетка, у которой клетка — `step_m` на сторону **везде**."""
        return cls(
            radius_m=float(radius_m),
            step_m=float(step_m),
            nside=healpix.nside_for(radius_m, step_m),
        )

    @property
    def count(self) -> int:
        """Клеток на планете."""
        return healpix.npix(self.nside)

    @property
    def side_m(self) -> float:
        """Сторона клетки, метры: одна на всю планету."""
        return healpix.cell_side_m(self.radius_m, self.nside)

    @property
    def area_m2(self) -> float:
        """Площадь клетки, м². Число, а не массив: сетка равноплощадная."""
        return healpix.cell_area_m2(self.radius_m, self.nside)

    @cached_property
    def _centres(self) -> tuple[np.ndarray, np.ndarray]:
        return healpix.centres(self.nside)

    @property
    def lat(self) -> np.ndarray:
        """Широта середины каждой клетки, градусы."""
        return self._centres[0]

    @property
    def lon(self) -> np.ndarray:
        return self._centres[1]

    @cached_property
    def xyz(self) -> np.ndarray:
        """Единичные векторы центров клеток, (count, 3)."""
        return healpix._xyz(self.lat, self.lon).T.copy()

    @cached_property
    def near(self) -> np.ndarray:
        """Соседи каждой клетки: (WAYS, count) номеров клеток."""
        return healpix.neighbours(self.nside, self.radius_m)

    @cached_property
    def ways(self) -> np.ndarray:
        """Сколько у клетки настоящих соседей: свободные места заняты ею самой."""
        return (self.near != np.arange(self.count, dtype=np.int32)).sum(axis=0)

    @cached_property
    def distances(self) -> np.ndarray:
        """Расстояние до каждого места соседа, (WAYS, count), метры.

        У свободного места — сторона клетки, а не ноль: делить на него всё
        равно придётся, а разность значений там нулевая, и на выбор спуска
        такое место не влияет.
        """
        here = self.xyz
        out = np.empty((WAYS, self.count), dtype=np.float64)
        for k in range(WAYS):
            cos = np.clip((here * here[self.near[k]]).sum(axis=1), -1.0, 1.0)
            out[k] = np.arccos(cos) * self.radius_m
        return np.where(out > 0.0, out, self.side_m)

    @cached_property
    def _fit(self) -> np.ndarray:
        """Веса производных: (3, WAYS, count) — восток, север и кривизна.

        У квадратной сетки производная бралась разностью соседей по строке и
        по столбцу. Здесь строк нет: по разностям с соседями решается
        **парабола** — наименьшие квадраты по пяти членам `u, v, u²/2, uv,
        v²/2` в касательной плоскости, — и от неё берутся наклон и лапласиан.

        Парабола, а не плоскость, потому что у **части** клеток соседей не
        восемь, а девять: на стыках базовых граней. Несимметричный набор
        соседей ловит кривизну поля в наклон, и плоскость давала на этих
        клетках до 4 % ошибки при верных долях процента у всех остальных —
        то есть шов по рёбрам граней, ровно такой же природы, как полярная
        рябь, от которой ушли (D-328). Парабола кривизну снимает, и ошибка
        падает до тысячных долей везде.

        Лапласиан выражен в тех же долях, что и прежнее «среднее по соседям
        минус своё» (`3/8` квадрата стороны на вторую производную), чтобы
        коэффициент оплывания в эрозии остался тем же числом.

        Веса зависят только от геометрии, поэтому решаются один раз на
        сетку. Решается блоками: пятёрка на пятёрку в каждой клетке — это
        сто пятьдесят мегабайт на Терре, если делать всё разом.
        """
        count, side = self.count, self.side_m
        lat, lon = np.radians(self.lat), np.radians(self.lon)
        east = np.stack([-np.sin(lon), np.cos(lon), np.zeros(count)], axis=1)
        north = np.stack(
            [-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)], axis=1
        )
        out = np.empty((3, WAYS, count), dtype=np.float32)
        for low in range(0, count, BLOCK):
            high = min(count, low + BLOCK)
            here = self.xyz[low:high]
            u = np.empty((WAYS, high - low))
            v = np.empty((WAYS, high - low))
            for k in range(WAYS):
                #: Свободное место соседа — сама клетка: смещение ноль, и в
                #: наименьших квадратах оно не участвует.
                apart = (self.xyz[self.near[k, low:high]] - here) * self.radius_m
                u[k] = (apart * east[low:high]).sum(axis=1) / side
                v[k] = (apart * north[low:high]).sum(axis=1) / side
            basis = np.stack([u, v, 0.5 * u * u, u * v, 0.5 * v * v])
            moment = np.einsum("ikn,jkn->nij", basis, basis) + np.eye(5) * 1e-9
            weight = np.einsum("nji,ikn->jkn", np.linalg.inv(moment), basis)
            out[0, :, low:high] = weight[0] / side
            out[1, :, low:high] = weight[1] / side
            out[2, :, low:high] = LAPLACE_SHARE * (weight[2] + weight[4])
        return out

    @cached_property
    def rings(self) -> tuple[np.ndarray, np.ndarray]:
        """Клетки колец равной широты по долготе и длины колец (§4.2)."""
        return healpix.ring_table(self.nside)

    def shift(self, a: np.ndarray, k: int) -> np.ndarray:
        """Массив, в котором в клетке стоит значение её соседа со стороны `k`."""
        return a[self.near[k]]

    def neighbour_index(self, k: int) -> np.ndarray:
        """Номер соседа со стороны `k` для каждой клетки."""
        return self.near[k]

    def cell(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """Клетка, в которую попадает точка."""
        return healpix.ang2pix(self.nside, np.asarray(lat), np.asarray(lon))

    def cells_for_metres(self, metres: float) -> int:
        return max(1, int(round(metres / self.side_m)))

    def hop(self, metres: float, bearing: float) -> np.ndarray:
        """Клетка, в которую придёшь из каждой клетки, пройдя `metres` по дуге."""
        return healpix.ang2pix(
            self.nside, *healpix.offset(self.lat, self.lon, self.radius_m, metres, bearing)
        )

    def _metres_to(self, index: np.ndarray) -> np.ndarray:
        valid = index >= 0
        seeds = self.xyz[np.clip(index, 0, None)]
        cos = np.clip((self.xyz * seeds).sum(axis=1), -1.0, 1.0)
        return np.where(valid, np.arccos(cos) * self.radius_m, np.inf)

    def nearest(
        self, source: np.ndarray, max_cells: float | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """Для каждой клетки — ближайшая клетка-источник и расстояние до неё
        по дуге, метры. Без источника вовсе — -1 и бесконечность.

        Прыжковая заливка: шаги по степеням двойки, восемь сторон света,
        логарифм проходов вместо волны по клетке. Прыжок здесь — не сдвиг
        индекса, а шаг по сфере: `2^n` сторон клетки в заданном направлении.
        Поэтому лестница начинается с той длины, до которой ответ нужен, —
        дальше него всё равно обрезано, и незачем обходить планету.
        """
        flat = np.arange(self.count, dtype=np.int64)
        best = np.where(np.asarray(source).ravel(), flat, -1)
        best_m = self._metres_to(best)
        reach = math.pi * self.radius_m / self.side_m if max_cells is None else float(max_cells)
        step = 1 << max(1, int(reach)).bit_length()
        while step >= 1:
            for k in range(LOOKS):
                candidate = best[self.hop(step * self.side_m, 2.0 * math.pi * k / LOOKS)]
                metres = self._metres_to(candidate)
                better = metres < best_m
                best = np.where(better, candidate, best)
                best_m = np.where(better, metres, best_m)
            step //= 2
        return best, best_m

    def dilate_distance(self, mask: np.ndarray, max_cells: int) -> np.ndarray:
        """Расстояние в клетках (по дуге, делённое на сторону) до ближайшей
        клетки маски, не дальше `max_cells`."""
        _, metres = self.nearest(mask, max_cells)
        return np.minimum(metres / self.side_m, float(max_cells))

    def spread(
        self, value: np.ndarray, source: np.ndarray, max_cells: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Значение ближайшей клетки-источника в каждой клетке и расстояние
        до неё в клетках. Где источников нет в `max_cells` — ноль и `max_cells`."""
        best, metres = self.nearest(source, max_cells)
        cells = metres / self.side_m
        within = (best >= 0) & (cells <= max_cells)
        carried = np.where(within, np.asarray(value).ravel()[np.clip(best, 0, None)], 0.0)
        return carried, np.minimum(np.where(best >= 0, cells, np.inf), float(max_cells))

    def laplacian(self, a: np.ndarray) -> np.ndarray:
        """Безразмерная кривизна в тех же долях, в каких её брала прежняя
        сетка средним по восьми соседям минус своё (см. `_fit`)."""
        fit = self._fit
        out = np.zeros(self.count)
        for k in range(WAYS):
            out += fit[2, k] * (a[self.near[k]] - a)
        return out

    def gradient(self, a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Производные по востоку и по северу, на метр."""
        fit = self._fit
        east = np.zeros(self.count)
        north = np.zeros(self.count)
        for k in range(WAYS):
            rise = a[self.near[k]] - a
            east += fit[0, k] * rise
            north += fit[1, k] * rise
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
            for k in range(WAYS):
                t = np.maximum(t, top[self.near[k]])
                b = np.minimum(b, bottom[self.near[k]])
            top, bottom = t, b
        return top - bottom

    def resample_from(self, a: np.ndarray, other: Grid) -> np.ndarray:
        """Массив другой сетки, прочитанный в центрах клеток этой.

        Билинейки на HEALPix нет — нет и четырёх углов вокруг точки, — и её
        место занимает вес по расстоянию: клетка чужой сетки, в которую
        точка попала, и её соседи, с весом, спадающим до нуля на
        `SMOOTH_REACH` её сторон. Это то же самое сглаживание, что даёт
        билинейка, и оно не знает про направления осей.
        """
        a = np.asarray(a, dtype=float).ravel()
        home = other.cell(self.lat, self.lon)
        span = SMOOTH_REACH * other.side_m
        cos = np.clip((self.xyz * other.xyz[home]).sum(axis=1), -1.0, 1.0)
        weight = np.maximum(1.0 - np.arccos(cos) * self.radius_m / span, 0.0) ** 2
        #: Своя клетка весит хоть сколько-то даже на самом краю ядра.
        weight = np.maximum(weight, 1e-6)
        total = weight * a[home]
        for k in range(WAYS):
            beside = other.near[k][home]
            cos = np.clip((self.xyz * other.xyz[beside]).sum(axis=1), -1.0, 1.0)
            w = np.maximum(1.0 - np.arccos(cos) * self.radius_m / span, 0.0) ** 2
            #: Свободное место соседа — это сама клетка, и второй раз она не считается.
            w = np.where(beside == home, 0.0, w)
            total += w * a[beside]
            weight += w
        return total / weight
