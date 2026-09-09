# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Поле — файл в сборке вольта (план §4.8): растры в `.npz`, паспорт в `.json`.

Сервер читает файл, а не считает: эрозия на плавающей точке не повторяется
бит в бит между машинами, и артефакт — единственная правда о форме мира.
Паспорт несёт параметры, версию алгоритма и хеш параметров: по нему сборка
узнаёт, что поле устарело и его надо пересчитать.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from field.grid import Grid
from field.pipeline import Params, Rasters


def save(r: Rasters, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    arrays = directory / f"{r.params.planet}.npz"
    passport = directory / f"{r.params.planet}.json"
    np.savez_compressed(
        arrays,
        height_m=r.height_m.astype(np.float32),
        water=r.water.astype(np.uint8),
        form=r.form.astype(np.uint8),
        hardness=np.round(r.hardness * 255).astype(np.uint8),
        area_km2=r.area_km2.astype(np.float32),
        wet_m=np.clip(r.wet_m, 0, 65535).astype(np.uint16),
        river_m=np.clip(r.river_m, 0, 65535).astype(np.uint16),
        temperature_c=np.clip(np.round(r.temperature_c), -128, 127).astype(np.int8),
        rain=np.round(r.rain * 255).astype(np.uint8),
        zonal=r.zonal.astype(np.uint8),
        plate=r.plate.astype(np.int16),
        deposit_m=r.deposit_m.astype(np.float32),
        uplift=np.round(r.uplift * 255).astype(np.uint8),
        ice=r.ice.astype(np.uint8),
    )
    meta = {
        "params": asdict(r.params),
        "digest": r.params.digest(),
        "grid": {"rows": r.grid.rows, "cols": r.grid.cols, "step_m": r.grid.step_m, "radius_m": r.grid.radius_m},
        "land_share": round(r.land_share(), 4),
        "height_max_m": round(float(r.height_m.max()), 1),
    }
    passport.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return arrays, passport


def load(directory: Path, planet: str) -> Rasters:
    meta = json.loads((directory / f"{planet}.json").read_text(encoding="utf-8"))
    params = Params(**meta["params"])
    grid = Grid.of(params.radius_m, params.step_m)
    with np.load(directory / f"{planet}.npz") as z:
        return Rasters(
            params=params,
            grid=grid,
            height_m=z["height_m"].astype(float),
            water=z["water"],
            form=z["form"],
            hardness=z["hardness"].astype(float) / 255.0,
            area_km2=z["area_km2"].astype(float),
            wet_m=z["wet_m"].astype(float),
            river_m=z["river_m"].astype(float),
            temperature_c=z["temperature_c"].astype(float),
            rain=z["rain"].astype(float) / 255.0,
            zonal=z["zonal"],
            plate=z["plate"],
            deposit_m=z["deposit_m"].astype(float),
            uplift=z["uplift"].astype(float) / 255.0,
            ice=z["ice"].astype(bool),
        )
