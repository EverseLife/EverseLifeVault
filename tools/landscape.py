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
    if args.coarse_iter is not None:
        overrides["coarse_iterations"] = int(args.coarse_iter)
    if args.fine_iter is not None:
        overrides["fine_iterations"] = int(args.fine_iter)
    return pipeline.Params.from_constants(constants(), args.planet, **overrides)


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
        Path(args.json).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def do_render(args: argparse.Namespace, rasters: pipeline.Rasters | None = None) -> None:
    rasters = rasters or store.load(Path(args.field).resolve(), args.planet)
    lat, lon = (float(x) for x in args.focus.split(","))
    for path in render.render_all(rasters, Path(args.out).resolve(), (lat, lon)):
        print(shown(path))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("build", "census", "render", "all"))
    ap.add_argument("--planet", choices=PLANETS, default="terra")
    ap.add_argument("--step", type=float, help="шаг сетки в метрах поверх terrain.step_m")
    ap.add_argument("--seed", type=int, help="зерно поверх terrain.seed (уже своё для планеты)")
    ap.add_argument("--coarse-iter", type=int)
    ap.add_argument("--fine-iter", type=int)
    ap.add_argument("--field", default=str(FIELD), help="куда класть и откуда читать поле")
    ap.add_argument("--out", default=str(PREVIEW), help="куда класть картинки")
    ap.add_argument("--focus", default=f"{FOCUS[0]},{FOCUS[1]}", help="широта,долгота кадров области и города")
    ap.add_argument("--json", help="перепись ещё и в этот файл")
    args = ap.parse_args()
    if args.command == "build":
        do_build(args)
    elif args.command == "census":
        do_census(args)
    elif args.command == "render":
        do_render(args)
    else:
        rasters = do_build(args)
        do_census(args, rasters)
        do_render(args, rasters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
