# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Поле планеты: собрать, переписать формы, отрисовать (90-production/12).

    python tools/landscape.py build  --planet terra              поле в build/field/
    python tools/landscape.py build  --planet terra --step 250   другой шаг сетки, туда же
    python tools/landscape.py census --planet terra              перепись форм и прогулки
    python tools/landscape.py render --planet terra --out build/preview
    python tools/landscape.py all    --planet terra              всё разом

Числа мира — из build/constants.json (D-065): зерно, доля моря, размах,
шаг сетки, число плит. `--step`, `--seed` и итерации кладутся поверх на
время одного прогона и ничего не пишут в реестр: это линейка, которой
выбирают шаг и зерно до перезапуска мира (план §4.1, §4.4).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from field import census, pipeline, render, store  # noqa: E402

BUILD = ROOT / "build"
FIELD = BUILD / "field"
PREVIEW = BUILD / "preview"
PLANETS = ("terra", "aquatica", "pyroxis", "aurora")
#: Куда смотрят кадры области и города по умолчанию: столица Терры.
FOCUS = (41.0, 24.0)


def constants() -> dict:
    return json.loads((BUILD / "constants.json").read_text(encoding="utf-8"))


def provinces_of(planet: str) -> list[dict]:
    """Строки провинций планеты из сборки (`data/provinces.yaml`); без файла — ни одной."""
    path = BUILD / "provinces.json"
    if not path.exists():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get(planet) or [])


def shown(path: Path) -> str:
    """Путь от корня вольта, если он внутри, иначе как есть."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def params_for(args: argparse.Namespace) -> pipeline.Params:
    overrides = {}
    if args.step:
        overrides["step_m"] = float(args.step)
    if args.seed is not None:
        overrides["seed"] = int(args.seed)
    if args.sea is not None:
        overrides["sea_share"] = float(args.sea)
    if args.coarse_iter is not None:
        overrides["coarse_iterations"] = int(args.coarse_iter)
    if args.fine_iter is not None:
        overrides["fine_iterations"] = int(args.fine_iter)
    return pipeline.Params.from_constants(
        constants(), args.planet, provinces_of(args.planet), **overrides
    )


def do_build(args: argparse.Namespace) -> pipeline.Rasters:
    params = params_for(args)
    started = time.perf_counter()

    def log(line: str) -> None:
        print(f"[{time.perf_counter() - started:6.1f} s] {line}", flush=True)

    rasters = pipeline.build(params, log)
    arrays, passport = store.save(rasters, Path(args.field).resolve())
    log(f"written {shown(arrays)} ({arrays.stat().st_size // 1024} KB), {passport.name}")
    return rasters


def do_census(args: argparse.Namespace, rasters: pipeline.Rasters | None = None) -> None:
    rasters = rasters or store.load(Path(args.field).resolve(), args.planet)
    rep = census.report(rasters)
    print(census.markdown(rep))
    if args.json:
        target = Path(args.json).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def do_render(args: argparse.Namespace, rasters: pipeline.Rasters | None = None) -> None:
    rasters = rasters or store.load(Path(args.field).resolve(), args.planet)
    if args.focus:
        lat, lon = (float(x) for x in args.focus.split(","))
        lat, lon = nearest_land(rasters, lat, lon)
    else:
        lat, lon = best_site(rasters)
    print(f"focus {lat:.2f}, {lon:.2f}")
    for path in render.render_all(rasters, Path(args.out).resolve(), (lat, lon)):
        print(shown(path))


def best_site(rasters: pipeline.Rasters, samples: int = 3000) -> tuple[float, float]:
    """Где поселенец поставил бы город: умеренно, вода рядом, форм вокруг
    много (план §9.8). Лучшая из случайной выборки клеток суши по этой мере."""
    grid = rasters.grid
    rng = np.random.default_rng(0)
    land = np.flatnonzero(rasters.water == pipeline.WATER_LAND)
    pick = rng.choice(land, size=min(samples, land.size), replace=False)
    radius = grid.cells_for_metres(3000.0)
    offsets = [(dr, dc) for dr in range(-radius, radius + 1) for dc in range(-radius, radius + 1) if dr * dr + dc * dc <= radius * radius]
    drs = np.array([o[0] for o in offsets])
    dcs = np.array([o[1] for o in offsets])
    best, best_score = (0, 0), -1e9
    for flat in pick.tolist():
        row, col = divmod(flat, grid.cols)
        rr = np.clip(row + drs, 0, grid.rows - 1)
        cc = (col + dcs) % grid.cols
        block_forms = rasters.form[rr, cc]
        block_water = rasters.water[rr, cc]
        distinct = np.unique(block_forms[block_water == pipeline.WATER_LAND]).size
        water = float((block_water != pipeline.WATER_LAND).mean())
        warmth = float(rasters.temperature_c[row, col])
        score = distinct + 4.0 * min(water, 0.25) - abs(warmth - 14.0) / 4.0 - 3.0 * float(rasters.ice[row, col])
        if score > best_score:
            best, best_score = (row, col), score
    return float(grid.lat[best[0]]), float(grid.lon[best[1]])


def nearest_land(rasters: pipeline.Rasters, lat: float, lon: float) -> tuple[float, float]:
    """Точка кадра, сдвинутая на ближайшую сушу: новое поле не обязано
    класть сушу туда, где стояла столица старого."""
    grid = rasters.grid
    row, col = grid.cell(lat, lon)
    if rasters.land[row, col]:
        return lat, lon
    land_rows, land_cols = np.nonzero(rasters.land)
    dlat = np.radians(grid.lat[land_rows] - lat)
    dlon = np.radians(((grid.lon[land_cols] - lon + 180.0) % 360.0) - 180.0) * np.cos(np.radians(lat))
    best = int(np.argmin(dlat * dlat + dlon * dlon))
    return float(grid.lat[land_rows[best]]), float(grid.lon[land_cols[best]])


def do_scan(args: argparse.Namespace) -> None:
    """Несколько зёрен подряд, по строке на каждое: чем выбирают зерно (план §4.4)."""
    base = params_for(args)
    print("seed | land | T50 | rain50 | ice | desert | missing | walk | hood | water")
    for k in range(int(args.seeds)):
        params = pipeline.Params(**{**base.__dict__, "seed": base.seed + k * 1000})
        rasters = pipeline.build(params)
        rep = census.report(rasters)
        ice = rep["forms"]["ice"]["share"]
        desert = rep["forms"]["rocky_desert"]["share"] + rep["forms"]["dunes"]["share"]
        print(
            f"{params.seed} | {rep['land_share']:.2f} | {rep['temperature_quantiles'][2]:5.1f} | "
            f"{rep['rain_quantiles'][2]:.2f} | {100 * ice:4.0f} % | {100 * desert:4.0f} % | "
            f"{len(rep['missing_forms'])} | {rep['walk']['form_changes_mean']:.2f} | "
            f"{rep['neighbourhood']['forms_mean']:.2f} | {100 * rep['neighbourhood']['with_water_share']:.0f} %",
            flush=True,
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("build", "census", "render", "all", "scan"))
    ap.add_argument("--seeds", type=int, default=6, help="сколько зёрен перебрать в scan")
    ap.add_argument("--planet", choices=PLANETS, default="terra")
    ap.add_argument("--step", type=float, help="шаг сетки в метрах поверх terrain.step_m")
    ap.add_argument("--seed", type=int, help="зерно поверх terrain.seed (уже своё для планеты)")
    ap.add_argument("--sea", type=float, help="доля моря поверх terrain.sea_share, на один прогон")
    ap.add_argument("--coarse-iter", type=int)
    ap.add_argument("--fine-iter", type=int)
    ap.add_argument("--field", default=str(FIELD), help="куда класть и откуда читать поле")
    ap.add_argument("--out", default=str(PREVIEW), help="куда класть картинки")
    ap.add_argument("--focus", help="широта,долгота кадров области и города; без него — лучшее место под город")
    ap.add_argument("--json", help="перепись ещё и в этот файл")
    args = ap.parse_args()
    if args.command == "build":
        do_build(args)
    elif args.command == "census":
        do_census(args)
    elif args.command == "render":
        do_render(args)
    elif args.command == "scan":
        do_scan(args)
    else:
        rasters = do_build(args)
        do_census(args, rasters)
        do_render(args, rasters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
