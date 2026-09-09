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

from field import climate, forms
from field.grid import Grid
from field.pipeline import Params, Rasters


#: Сколько точек кладётся в пробу проекции: край, полюс, стык граней и
#: полсотни случайных — довольно, чтобы разошедшаяся проекция не прошла.
PROBES = 64


def _probe(grid: Grid) -> dict:
    """Точки и их клетки, как их видит сборка."""
    rng = np.random.default_rng(17)
    lat = np.r_[
        np.degrees(np.arcsin(rng.uniform(-1.0, 1.0, PROBES))),
        [-90.0, 90.0, 0.0, 0.0, 41.81031, -41.81031, 66.44354, -66.44354],
    ]
    lon = np.r_[
        rng.uniform(-180.0, 180.0, PROBES),
        [0.0, 0.0, -180.0, 180.0, 45.0, -45.0, 135.0, -135.0],
    ]
    return {
        "lat": [float(v) for v in lat],
        "lon": [float(v) for v in lon],
        "cell": [int(v) for v in grid.cell(lat, lon)],
    }


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
        flow_km2=r.flow_km2.astype(np.float32),
        wet_m=np.clip(r.wet_m, 0, 65535).astype(np.uint16),
        river_m=np.clip(r.river_m, 0, 65535).astype(np.uint16),
        sea_m=np.clip(r.sea_m, 0, 65535).astype(np.uint16),
        temperature_c=np.clip(np.round(r.temperature_c), -128, 127).astype(np.int8),
        rain=np.round(r.rain * 255).astype(np.uint8),
        plate=r.plate.astype(np.int16),
        deposit_m=r.deposit_m.astype(np.float32),
        uplift=np.round(r.uplift * 255).astype(np.uint8),
        ice=r.ice.astype(np.uint8),
        province=r.province.astype(np.uint8),
    )
    meta = {
        "params": asdict(r.params),
        "digest": r.params.digest(),
        #: Сетка HEALPix (D-328): дробность и радиус задают её целиком —
        #: клеток `12 nside²`, и все одной стороны.
        "grid": {
            "kind": "healpix",
            "nside": r.grid.nside,
            "cells": r.grid.count,
            "step_m": r.grid.step_m,
            "side_m": round(r.grid.side_m, 3),
            "radius_m": r.grid.radius_m,
        },
        "land_share": round(r.land_share(), 4),
        "height_max_m": round(float(r.height_m.max()), 1),
        #: Смысл кодов растров — в паспорте, а не только в коде: файл поля
        #: читается сам по себе. Таблица форм переедет в данные вольта (D-251).
        "forms": [{"id": key, "ru": ru, "en": en} for key, ru, en in forms.FORMS],
        "water": ["land", "sea", "lake", "river"],
        #: Растр `zonal` в файл не пишется: игра читает `biome.zonal` сама.
        "zonal": climate.zonal_names(r.params.zonal),
        #: Проба проекции: несколько точек и клетки, в которые они попали
        #: **у сборки**. Сетка HEALPix живёт в двух местах — здесь и в
        #: движке, — и разойтись они могут молча: мир поедет на километры,
        #: и никто не упадёт. Движок сверяет пробу при чтении файла и
        #: отказывается стартовать, а не читает мир не там (D-328).
        "probe": _probe(r.grid),
        #: Провинции планеты в порядке кодов растра `province` (план §7):
        #: имена — по id из renames вольта (D-251), здесь только числа.
        "provinces": [
            {
                "id": row["id"],
                "rain_shift": row["rain_shift"],
                "temp_shift_c": row["temp_shift_c"],
                "vein_k": row["vein_k"],
                "favours": list(row.get("favours") or ()),
            }
            for row in r.provinces
        ],
    }
    passport.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return arrays, passport


def load(directory: Path, planet: str) -> Rasters:
    meta = json.loads((directory / f"{planet}.json").read_text(encoding="utf-8"))
    raw = dict(meta["params"])
    #: JSON не знает кортежей: строки провинций возвращаются тем же кортежем,
    #: каким они были в параметрах, иначе паспорт не равен сам себе. Список
    #: любимых фацетов внутри строки — тот же случай (план §7, волна 8).
    raw["provinces"] = tuple(
        {**row, "favours": tuple(row.get("favours") or ())}
        for row in raw.get("provinces", [])
    )
    raw["zones"] = tuple(raw.get("zones", []))
    raw["rain_range"] = tuple(raw.get("rain_range", (0.0, 100.0)))
    params = Params(**raw)
    grid = Grid.of(params.radius_m, params.step_m)
    with np.load(directory / f"{planet}.npz") as z:
        temperature = z["temperature_c"].astype(float)
        rain01 = z["rain"].astype(float) / 255.0
        return Rasters(
            params=params,
            grid=grid,
            height_m=z["height_m"].astype(float),
            water=z["water"],
            form=z["form"],
            hardness=z["hardness"].astype(float) / 255.0,
            area_km2=z["area_km2"].astype(float),
            flow_km2=(
                z["flow_km2"].astype(float)
                if "flow_km2" in z
                else np.zeros(z["water"].shape)
            ),
            wet_m=z["wet_m"].astype(float),
            river_m=z["river_m"].astype(float),
            temperature_c=temperature,
            rain=rain01,
            zonal=climate.zonal(temperature, rain01, params.zonal, params.rain_range),
            sea_m=z["sea_m"].astype(float),
            plate=z["plate"],
            deposit_m=z["deposit_m"].astype(float),
            uplift=z["uplift"].astype(float) / 255.0,
            ice=z["ice"].astype(bool),
            province=z["province"] if "province" in z else np.zeros(z["water"].shape, dtype=np.uint8),
            provinces=[
                {**row, "favours": tuple(row.get("favours") or ())}
                for row in meta.get("provinces", [])
            ],
        )
