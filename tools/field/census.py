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

Всё — по растрам поля, без карты и без игры.
"""

from __future__ import annotations

import math

import numpy as np

from field import climate, forms
from field.grid import OFFSETS, Grid
from field.pipeline import WATER_LAND, Rasters

WALKS = 1000
WALK_M = 4_000.0
NEIGHBOURHOODS = 1000
NEIGHBOURHOOD_M = 2_000.0
#: Планка прогулки: смен формы за час хода в среднем.
WALK_BAR = 3.0


def components(mask: np.ndarray, grid: Grid) -> int:
    """Число связных компонент маски (восемь соседей, заворот по долготе):
    метка — наименьший плоский индекс компоненты, разносится волной со
    сжатием путей, так что и длинный хребет сходится за десятки шагов."""
    if not mask.any():
        return 0
    flat = np.arange(mask.size, dtype=np.int64).reshape(mask.shape)
    label = np.where(mask, flat, flat)
    for _ in range(10_000):
        before = label
        for dr, dc in OFFSETS:
            near = grid.shift(label, dr, dc)
            near_mask = grid.shift(mask, dr, dc)
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
    area = np.repeat(r.grid.area_m2[:, None], r.grid.cols, axis=1)
    land_area = float(area[r.land].sum())
    out: dict[str, dict[str, float | int]] = {}
    for key, _, _ in forms.FORMS:
        mask = r.form == forms.CODE[key]
        if key in ("sea",):
            continue
        share = float(area[mask].sum() / land_area) if land_area else 0.0
        out[key] = {"share": share, "objects": components(mask, r.grid) if mask.any() else 0}
    return out


def _sample_land(r: Rasters, rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    land = np.flatnonzero(r.water == WATER_LAND)
    pick = rng.choice(land, size=min(n, land.size), replace=False)
    return pick // r.grid.cols, pick % r.grid.cols


def walk_test(r: Rasters, rng: np.random.Generator) -> dict[str, float]:
    rows, cols = _sample_land(r, rng, WALKS)
    steps = max(2, int(round(WALK_M / r.grid.step_m)))
    form_changes, zonal_changes, still = [], [], 0
    for row, col in zip(rows.tolist(), cols.tolist()):
        bearing = rng.uniform(0, 2 * math.pi)
        dr, dc = math.cos(bearing), math.sin(bearing)
        seen_f, seen_z, prev_f, prev_z = 0, 0, int(r.form[row, col]), int(r.zonal[row, col])
        for k in range(1, steps + 1):
            rr = int(np.clip(round(row + dr * k), 0, r.grid.rows - 1))
            cc = int(round(col + dc * k)) % r.grid.cols
            f, z = int(r.form[rr, cc]), int(r.zonal[rr, cc])
            if f != prev_f:
                seen_f += 1
                prev_f = f
            if z != prev_z:
                seen_z += 1
                prev_z = z
        form_changes.append(seen_f)
        zonal_changes.append(seen_z)
        still += seen_f == 0
    return {
        "walks": len(form_changes),
        "form_changes_mean": float(np.mean(form_changes)),
        "zonal_changes_mean": float(np.mean(zonal_changes)),
        "walks_without_change": still,
        "bar": WALK_BAR,
    }


def neighbourhood_test(r: Rasters, rng: np.random.Generator) -> dict[str, float]:
    rows, cols = _sample_land(r, rng, NEIGHBOURHOODS)
    radius = max(1, int(round(NEIGHBOURHOOD_M / r.grid.step_m)))
    offsets = [(dr, dc) for dr in range(-radius, radius + 1) for dc in range(-radius, radius + 1) if dr * dr + dc * dc <= radius * radius]
    distinct, watered = [], 0
    for row, col in zip(rows.tolist(), cols.tolist()):
        rr = np.clip(row + np.array([o[0] for o in offsets]), 0, r.grid.rows - 1)
        cc = (col + np.array([o[1] for o in offsets])) % r.grid.cols
        block_forms = r.form[rr, cc]
        block_water = r.water[rr, cc]
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
    area = np.repeat(r.grid.area_m2[:, None], r.grid.cols, axis=1)
    zonal_share = {
        name: float(area[(r.zonal == code) & r.land].sum() / max(area[r.land].sum(), 1.0))
        for code, name in enumerate(climate.zonal_names(r.params.zonal))
    }
    counted = shares(r)
    return {
        "planet": r.params.planet,
        "step_m": r.grid.step_m,
        "cells": int(r.grid.rows * r.grid.cols),
        "land_share": r.land_share(),
        "height_max_m": float(r.height_m.max()),
        "forms": counted,
        "missing_forms": [key for key, v in counted.items() if v["objects"] == 0 and key != "lake"],
        "zonal": zonal_share,
        "provinces": {
            "count": len(r.provinces),
            "mean_area_km2": (
                float(area[r.land].sum() / 1e6 / len(r.provinces)) if r.provinces else 0.0
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
