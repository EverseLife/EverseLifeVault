# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Перепись форм и пять измерений разнообразия (план §4.1, §4.4).

* **доли** — сколько суши в каждой форме и сколько отдельных объектов
  (связных компонент) каждой формы на планете: есть ли на Терре хоть один
  каньон и одна дельта — это отсюда;
* **прогулка** — тысяча случайных маршрутов по 4 км, час хода: сколько раз
  по пути сменились форма и биом; планка — не меньше трёх смен формы в
  среднем и ни одного маршрута без единой;
* **соседство** — для тысячи случайных точек: сколько разных форм и есть
  ли вода в двух километрах вокруг, дневная разведка вокруг дома.

Всё — по растрам поля, без карты и без игры. Прогулка и соседство ходят
**по сфере** (D-328): шаг — столько-то метров в такую-то сторону, а не
столько-то индексов, — потому что у равноплощадной сетки индекс соседа сам
по себе ничего не говорит о том, где сосед лежит.
"""

from __future__ import annotations

import math

import numpy as np

from field import climate, forms, healpix
from field.grid import WAYS, Grid
from field.pipeline import WATER_LAND, Rasters

WALKS = 1000
WALK_M = 4_000.0
NEIGHBOURHOODS = 1000
NEIGHBOURHOOD_M = 2_000.0
#: Планка прогулки: смен формы за час хода в среднем.
WALK_BAR = 3.0


def components(mask: np.ndarray, grid: Grid) -> int:
    """Число связных компонент маски: метка — наименьший номер клетки
    компоненты, разносится волной со сжатием путей, так что и длинный
    хребет сходится за десятки шагов."""
    if not mask.any():
        return 0
    label = np.arange(grid.count, dtype=np.int64)
    for _ in range(10_000):
        before = label
        for k in range(WAYS):
            near = grid.shift(label, k)
            near_mask = grid.shift(mask, k)
            label = np.where(mask & near_mask, np.minimum(label, near), label)
        #: Сжатие до упора: метка метки, пока не перестанет меняться. Так
        #: волна идёт не по клетке за шаг, а по компоненте за несколько.
        for _ in range(64):
            jumped = label.ravel()[label]
            if np.array_equal(jumped, label):
                break
            label = jumped
        if np.array_equal(label, before):
            break
    return int(np.unique(label[mask]).size)


def shares(r: Rasters) -> dict[str, dict[str, float | int]]:
    #: Доля площади — это доля клеток: сетка равноплощадная (D-328).
    land_cells = float(r.land.sum())
    out: dict[str, dict[str, float | int]] = {}
    for key, _, _ in forms.FORMS:
        mask = r.form == forms.CODE[key]
        if key in ("sea",):
            continue
        share = float(mask.sum() / land_cells) if land_cells else 0.0
        out[key] = {"share": share, "objects": components(mask, r.grid) if mask.any() else 0}
    return out


def _sample_land(r: Rasters, rng: np.random.Generator, n: int) -> np.ndarray:
    land = np.flatnonzero(r.water == WATER_LAND)
    return rng.choice(land, size=min(n, land.size), replace=False)


def _disc(side_m: float, radius_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Пробы по кругу радиусом `radius_m`: кольцами через полклетки, и по
    кольцу — тоже через полклетки, чтобы ни одна клетка круга не осталась
    непроверенной. Круг по земле, а не квадрат по индексам."""
    grain = side_m / 2.0
    #: Середина всегда: круг мельче клетки — это сама клетка, а не пустота.
    spans, turns = [np.zeros(1)], [np.zeros(1)]
    reach = grain
    while reach <= radius_m + 1e-9:
        many = max(6, int(round(2.0 * math.pi * reach / grain)))
        spans.append(np.full(many, reach))
        turns.append(np.arange(many) * (2.0 * math.pi / many))
        reach += grain
    return np.concatenate(spans), np.concatenate(turns)


def walk_test(r: Rasters, rng: np.random.Generator) -> dict[str, float]:
    """Час хода по прямой: сколько раз сменились форма и биом.

    Прямая — дуга большого круга, и шаг по ней в полклетки: на сетке из
    ромбов шаг в целую клетку иногда перескакивал бы через соседа.
    """
    start = _sample_land(r, rng, WALKS)
    steps = max(2, int(round(2.0 * WALK_M / r.grid.side_m)))
    lat, lon = r.grid.lat[start], r.grid.lon[start]
    bearing = rng.uniform(0, 2 * math.pi, size=start.size)
    seen = np.zeros((2, start.size), dtype=np.int64)
    previous = np.stack([r.form[start], r.zonal[start]]).astype(np.int64)
    for k in range(1, steps + 1):
        at = r.grid.cell(
            *healpix.offset(lat, lon, r.grid.radius_m, WALK_M * k / steps, bearing)
        )
        now = np.stack([r.form[at], r.zonal[at]]).astype(np.int64)
        seen += now != previous
        previous = now
    return {
        "walks": int(start.size),
        "form_changes_mean": float(seen[0].mean()),
        "zonal_changes_mean": float(seen[1].mean()),
        "walks_without_change": int((seen[0] == 0).sum()),
        "bar": WALK_BAR,
    }


def neighbourhood_test(r: Rasters, rng: np.random.Generator) -> dict[str, float]:
    """Дневная разведка вокруг дома: сколько форм и есть ли вода в круге."""
    start = _sample_land(r, rng, NEIGHBOURHOODS)
    spans, turns = _disc(r.grid.side_m, NEIGHBOURHOOD_M)
    lat, lon = r.grid.lat[start][:, None], r.grid.lon[start][:, None]
    around = r.grid.cell(
        *healpix.offset(lat, lon, r.grid.radius_m, spans[None, :], turns[None, :])
    )
    distinct, watered = [], 0
    for row in range(start.size):
        block = np.unique(around[row])
        block_forms = r.form[block]
        block_water = r.water[block]
        distinct.append(int(np.unique(block_forms[block_water == WATER_LAND]).size))
        watered += bool((block_water != WATER_LAND).any())
    counts = np.bincount(distinct, minlength=4)
    return {
        "points": len(distinct),
        "forms_mean": float(np.mean(distinct)),
        "one_or_two_forms_share": float((np.array(distinct) <= 2).mean()),
        "with_water_share": watered / max(1, len(distinct)),
        "histogram": counts.tolist(),
    }


def report(r: Rasters, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    land_cells = max(float(r.land.sum()), 1.0)
    zonal_share = {
        name: float(((r.zonal == code) & r.land).sum() / land_cells)
        for code, name in enumerate(climate.zonal_names(r.params.zonal))
    }
    counted = shares(r)
    return {
        "planet": r.params.planet,
        "step_m": r.grid.side_m,
        "cells": int(r.grid.count),
        "land_share": r.land_share(),
        "height_max_m": float(r.height_m.max()),
        "forms": counted,
        "missing_forms": [key for key, v in counted.items() if v["objects"] == 0 and key != "lake"],
        "zonal": zonal_share,
        "provinces": {
            "count": len(r.provinces),
            "mean_area_km2": (
                float(land_cells * r.grid.area_m2 / 1e6 / len(r.provinces))
                if r.provinces
                else 0.0
            ),
            "unassigned_land_share": float((r.province[r.land] == 0).mean()) if r.provinces else 1.0,
        },
        "rain_quantiles": [round(float(q), 3) for q in np.quantile(r.rain[r.land], (0.1, 0.25, 0.5, 0.75, 0.9))],
        "temperature_quantiles": [round(float(q), 1) for q in np.quantile(r.temperature_c[r.land], (0.1, 0.25, 0.5, 0.75, 0.9))],
        "walk": walk_test(r, rng),
        "neighbourhood": neighbourhood_test(r, rng),
    }


def markdown(rep: dict) -> str:
    lines = [
        f"### {rep['planet']} — шаг {rep['step_m']:.0f} м, клеток {rep['cells']:,}, суши {rep['land_share']:.2f}, высшая точка {rep['height_max_m']:.0f} м",
        "",
        "| форма | доля суши | объектов |",
        "|---|---|---|",
    ]
    for key, v in rep["forms"].items():
        lines.append(f"| {forms.NAMES_RU[key]} | {100 * v['share']:.1f} % | {v['objects']} |")
    lines.append("")
    if rep["missing_forms"]:
        lines.append("**Нет на планете:** " + ", ".join(forms.NAMES_RU[k] for k in rep["missing_forms"]))
        lines.append("")
    w = rep["walk"]
    lines.append(
        f"**Прогулка** ({w['walks']} маршрутов по 4 км): смен формы {w['form_changes_mean']:.2f} в среднем "
        f"(планка {w['bar']:.0f}), смен биома {w['zonal_changes_mean']:.2f}, без единой смены — {w['walks_without_change']}"
    )
    n = rep["neighbourhood"]
    lines.append(
        f"**Соседство** ({n['points']} точек, 2 км вокруг): форм {n['forms_mean']:.2f} в среднем, "
        f"одна-две формы у {100 * n['one_or_two_forms_share']:.0f} %, вода рядом у {100 * n['with_water_share']:.0f} %"
    )
    lines.append("")
    lines.append("Зональные (`biome.zonal`): " + ", ".join(f"{k} {100 * v:.0f} %" for k, v in rep["zonal"].items() if v > 0.001))
    pr = rep["provinces"]
    lines.append(
        f"**Провинции**: {pr['count']}, в среднем {pr['mean_area_km2']:.0f} км² суши на каждую, "
        f"без провинции {100 * pr['unassigned_land_share']:.1f} % суши"
    )
    lines.append(
        f"Осадки суши по квантилям 10/25/50/75/90: {rep['rain_quantiles']}; "
        f"температура: {rep['temperature_quantiles']}"
    )
    return "\n".join(lines) + "\n"
