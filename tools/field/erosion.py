# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Эрозия: вода режет, склон оплывает, осадок ложится, недра поднимают (план §4.2).

Каждая итерация — четыре процесса над высотой в метрах:

* **речной срез** — сила потока: площадь стока в корне на уклон, делённое на
  твёрдость породы. Много воды на крутом и мягком — глубоко; в твёрдом —
  узко, и это каньон;
* **осадок** — срезанное едет вниз по стоку и оседает там, где уклон падает
  ниже порога: пойма, конус выноса у горного фронта, дельта в море; море и
  озеро берут всё;
* **склон** — диффузия: мягкая порода оплывает в холмы, твёрдая держит
  обрыв, пока уклон не перевалит за свой предел, — тогда сыплется;
* **поднятие** — хребет растёт на всю эрозию, иначе река срезала бы его
  дочиста и остались бы одни холмы.

Лёд — там, где средняя температура ниже линии льда: вода режет вполсилы,
склон оплывает втрое шире, и долина из V становится корытом.

Коэффициенты здесь — шаг процесса на итерацию в долях размаха рельефа:
это математика конвейера, а не баланс мира, потому и не в реестре.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from field import hydro
from field.grid import Grid

#: Площадь стока, при которой сила потока равна единице, м².
AREA_REF_M2 = 1.0e8
#: Показатели силы потока: корень из площади, уклон линейно.
AREA_EXP = 0.5
SLOPE_EXP = 1.0
#: Срез за итерацию при единичной силе, в долях размаха.
INCISION = 0.06
#: Не больше этой доли перепада до приёмника снимается за раз: устойчивость.
INCISION_CAP = 0.6
#: Уклон, ниже которого осадок оседает целиком; выше — едет дальше.
DEPOSIT_SLOPE = 0.015
DEPOSIT_SHARE = 0.7
#: Потолок отложения за итерацию, доли размаха.
DEPOSIT_CAP = 0.012
#: Диффузия склона за итерацию на клетке `DIFFUSION_STEP_M`, делится на
#: твёрдость. Оплывание — дело сотен метров, а не километров: на клетке
#: крупнее оно слабеет квадратом шага, иначе грубая сетка замыла бы долины,
#: которые сама же прорезала.
DIFFUSION = 0.03
DIFFUSION_STEP_M = 500.0
#: Предел уклона, за которым склон сыплется: мягкий 35°, твёрдый под 57°.
SLIDE_BASE, SLIDE_PER_HARDNESS = 0.35, 1.2
SLIDE_DIFFUSION = 0.35
#: Поднятие за итерацию при единичной скорости, доли размаха.
UPLIFT = 0.012
#: Лёд (план §4.9): выше линии льда вода не режет вовсе — там шапка, — а
#: лёд выпахивает: оплывание втрое сильнее, и долина из V становится корытом.
ICE_INCISION = 0.0
ICE_DIFFUSION = 3.0
#: Дельта поднимается над уровнем моря не выше этого, метры.
DELTA_RISE_M = 2.0


@dataclass(frozen=True)
class Eroded:
    height: np.ndarray
    deposit: np.ndarray  # сколько метров осадка легло за всё время
    flow: hydro.Flow
    ice: np.ndarray  # bool


def erode(
    height: np.ndarray,
    sea: np.ndarray,
    grid: Grid,
    *,
    hardness: np.ndarray,
    uplift: np.ndarray,
    relief_m: float,
    iterations: int,
    temperature: "callable",
    ice_c: float,
) -> Eroded:
    """`temperature(height_m) -> °C` по клеткам: лёд считается заново каждую
    итерацию, потому что гора, которую срезали, теплеет."""
    h = height.astype(float).copy()
    deposit = np.zeros_like(h)
    #: Площадь клетки — число: сетка равноплощадная (D-328).
    area = grid.area_m2
    land = ~sea
    flow = hydro.route(h, sea, grid)
    ice = np.zeros_like(sea)
    for _ in range(max(0, int(iterations))):
        flow = hydro.route(h, sea, grid)
        ice = (temperature(h) < ice_c) & land
        power = (flow.area_m2 / AREA_REF_M2) ** AREA_EXP * flow.slope**SLOPE_EXP
        cut = INCISION * relief_m * power / hardness
        cut = np.where(ice, cut * ICE_INCISION, cut)
        cut = np.minimum(cut, INCISION_CAP * flow.slope * flow.distance)
        cut = np.where(land & ~flow.lake, cut, 0.0)
        #: Берег режется до кромки воды, не ниже: клетка суши остаётся сушей.
        cut = np.minimum(cut, np.clip(h, 0.0, None))
        h -= cut

        keep = np.clip(1.0 - flow.slope / DEPOSIT_SLOPE, 0.0, 1.0) * DEPOSIT_SHARE
        keep = np.where(sea | flow.lake, 1.0, keep)
        settled, _ = hydro.downstream(flow, cut * area, keep)
        laid = np.minimum(settled / area, DEPOSIT_CAP * relief_m)
        #: Дельта: море у устья заполняется до кромки и становится сушей.
        laid = np.where(sea, np.minimum(laid, np.maximum(DELTA_RISE_M - h, 0.0)), laid)
        h += laid
        deposit += laid

        slope = grid.slope(h)
        limit = SLIDE_BASE + SLIDE_PER_HARDNESS * hardness
        scale = (DIFFUSION_STEP_M / grid.side_m) ** 2
        kd = DIFFUSION * scale / hardness + np.where(slope > limit, SLIDE_DIFFUSION, 0.0)
        kd = np.where(ice, kd * ICE_DIFFUSION, kd)
        h = np.where(land, h + kd * grid.laplacian(h), h)

        h = np.where(land, h + UPLIFT * relief_m * uplift, h)
        h = np.where(land, np.maximum(h, 0.0), h)
    flow = hydro.route(h, sea, grid)
    ice = (temperature(h) < ice_c) & land
    return Eroded(height=h, deposit=deposit, flow=flow, ice=ice)
