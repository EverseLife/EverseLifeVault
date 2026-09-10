# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Прибитые места раскладки мира против поля планет (90-production/12).

    python tools/pins.py            проверить: каждый `place: {lat, lon}` на суше?
    python tools/pins.py --fix      сдвинуть утонувшие на ближайшую сушу и записать

Поле теперь делает конвейер, а не шум, и место, прибитое под старое поле,
может оказаться в море. Сид игры кладёт такой узел с отказом, а не молча,
поэтому проверка живёт здесь, рядом со сборкой. Столица Терры особая: ей
нужна не ближайшая суша, а место под город (`landscape.best_site`) в
обитаемых широтах — так её и двигает `--fix`, и говорит об этом вслух.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from field import store  # noqa: E402
import landscape  # noqa: E402

WORLD = ROOT / "data" / "world.yaml"
FIELD = ROOT / "build" / "field"
CAPITAL = "terra.capital"
#: Столица не выше этой доли `map.city_lat_max` реестра: не на самом краю
#: обитаемых широт, а с запасом на город вокруг.
CAPITAL_LAT_SHARE = 0.8
#: Сколько раз перебирать выборку мест, прежде чем сдаться.
SITE_TRIES = 6


def pinned() -> list[dict]:
    doc = yaml.safe_load(WORLD.read_text(encoding="utf-8"))
    out = []
    for node in doc.get("nodes", []):
        place = node.get("place") or {}
        if "lat" in place and "lon" in place:
            out.append({"key": node["key"], "planet": node.get("planet", node["key"].split(".")[0]), "lat": float(place["lat"]), "lon": float(place["lon"])})
    return out


def main() -> int:
    fix = "--fix" in sys.argv
    text = WORLD.read_text(encoding="utf-8")
    problems = 0
    for pin in pinned():
        rasters = store.load(FIELD, pin["planet"])
        on_land = bool(rasters.land[int(rasters.grid.cell(pin["lat"], pin["lon"]))])
        print(f"{pin['key']}: {pin['lat']:.2f}, {pin['lon']:.2f} -> {'суша' if on_land else 'МОРЕ'}")
        if on_land:
            continue
        problems += 1
        if not fix:
            continue
        if pin["key"] == CAPITAL:
            lat_max = CAPITAL_LAT_SHARE * float(landscape.constants()["map.city_lat_max"])
            lat, lon = landscape.best_site(rasters)
            for k in range(SITE_TRIES):
                if abs(lat) <= lat_max:
                    break
                lat, lon = landscape.best_site(rasters, samples=3000 * (k + 2))
            else:
                raise SystemExit(f"{pin['key']}: лучшее место всё выше {lat_max:.0f}° — выбирать руками")
        else:
            lat, lon = landscape.nearest_land(rasters, pin["lat"], pin["lon"])
        old = f"place: {{lat: {pin['lat']}, lon: {pin['lon']}}}"
        new = f"place: {{lat: {lat:.2f}, lon: {lon:.2f}}}"
        assert old in text, f"не нашёл {old} в world.yaml"
        text = text.replace(old, new, 1)
        print(f"  -> {new}")
    if fix and problems:
        WORLD.write_text(text, encoding="utf-8")
        print(f"записано: {problems} мест сдвинуто")
    return 1 if problems and not fix else 0


if __name__ == "__main__":
    raise SystemExit(main())
