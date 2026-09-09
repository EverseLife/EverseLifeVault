# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Отладочный рендер поля в PNG (план §4.4): линейка для глаза, не продукт.

CPU-растр отклонён для клиента (§15), здесь он инструмент разработки: тремя
кадрами — планета, область, город — и несколькими слоями — отмывка с
гипсометрией и водой, формы, породa, зональные биомы — судят, вышло ли
поле разнообразным, до того как хоть строчка уедет в игру.

PNG пишется своими руками через zlib: в среде сборки нет PIL, а формат
на одну картинку без сжатия хитростей умещается в тридцать строк.

Растр поля — плоский ряд равноплощадных клеток (D-328), и картинка из него
не вырезается, а **проецируется**: каждому пикселю кадра отвечает точка
сферы, а точке — клетка. Планета целиком идёт равнопромежуточной проекцией,
как и раньше; область и город — окном в честных метрах вокруг точки, севером
вверх, и потому больше не растягиваются к полюсу.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

from field import climate, forms, healpix
from field.grid import Grid
from field.pipeline import WATER_LAKE, WATER_RIVER, WATER_SEA, Rasters

#: Свет: с северо-запада, под 45°, и во сколько раз рельеф подчёркнут.
SUN_AZIMUTH_DEG = 315.0
SUN_ALTITUDE_DEG = 45.0
EXAGGERATION = 2.0
#: Гипсометрия суши: доли размаха и цвета.
HYPSO = (
    (0.00, (78, 130, 70)),
    (0.08, (120, 160, 80)),
    (0.20, (190, 185, 110)),
    (0.40, (170, 130, 80)),
    (0.65, (140, 110, 95)),
    (0.85, (200, 200, 200)),
    (1.00, (255, 255, 255)),
)
SEA_SHALLOW = (110, 160, 210)
SEA_DEEP = (20, 50, 110)
LAKE = (70, 140, 210)
RIVER = (40, 110, 200)
ICE = (235, 240, 250)

FORM_COLORS = {
    "sea": (30, 60, 120), "lake": (70, 140, 210), "plain": (170, 200, 140), "hills": (140, 170, 100),
    "valley": (110, 180, 120), "floodplain": (60, 160, 90), "delta": (40, 130, 90), "fan": (220, 200, 140),
    "ridge": (120, 90, 70), "plateau": (190, 160, 110), "canyon": (150, 40, 30), "cliff": (60, 30, 30),
    "scree": (150, 140, 130), "rift": (110, 60, 130), "volcano": (230, 60, 40), "glacial": (160, 200, 230),
    "fjord": (90, 150, 210), "ice": (235, 240, 250), "dunes": (240, 210, 120), "rocky_desert": (200, 160, 100),
    "coast_cliff": (90, 70, 60), "beach": (240, 230, 180),
}
ZONAL_COLORS = {
    "tundra": (200, 210, 200), "taiga": (40, 90, 70), "desert": (240, 210, 130), "semidesert": (210, 180, 110),
    "steppe": (200, 190, 90), "savanna": (190, 170, 60), "rainforest": (20, 100, 40), "woodland": (120, 150, 60),
    "forest": (60, 130, 60),
}
#: Класс без цвета и клетка вне таблицы — розовым, чтобы бросалось в глаза.
ZONAL_UNKNOWN = (255, 0, 255)


def png(rgb: np.ndarray, path: Path) -> None:
    """Массив (h, w, 3) uint8 в файл PNG."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    )


def hillshade(grid: Grid, height_m: np.ndarray) -> np.ndarray:
    east, north = grid.gradient(height_m * EXAGGERATION)
    nx, ny, nz = -east, -north, np.ones_like(east)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    az, alt = np.radians(SUN_AZIMUTH_DEG), np.radians(SUN_ALTITUDE_DEG)
    lx, ly, lz = np.cos(alt) * np.sin(az), np.cos(alt) * np.cos(az), np.sin(alt)
    return np.clip((nx * lx + ny * ly + nz * lz) / norm, 0.0, 1.0)


def _ramp(value: np.ndarray, stops: tuple) -> np.ndarray:
    out = np.zeros(value.shape + (3,), dtype=float)
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        t = np.clip((value - a) / max(b - a, 1e-9), 0.0, 1.0)
        inside = (value >= a) & (value <= b)
        for k in range(3):
            out[..., k] = np.where(inside, ca[k] + (cb[k] - ca[k]) * t, out[..., k])
    return out


def layer_relief(r: Rasters) -> np.ndarray:
    share = np.clip(r.height_m / r.params.relief_m, 0.0, 1.0)
    rgb = _ramp(share, HYPSO)
    shade = hillshade(r.grid, r.height_m)
    rgb = rgb * (0.45 + 0.55 * shade)[..., None]
    depth = np.clip(-r.height_m / 2000.0, 0.0, 1.0)
    sea = np.array(SEA_SHALLOW) * (1 - depth)[..., None] + np.array(SEA_DEEP) * depth[..., None]
    rgb = np.where((r.water == WATER_SEA)[..., None], sea, rgb)
    rgb = np.where((r.water == WATER_LAKE)[..., None], np.array(LAKE), rgb)
    rgb = np.where((r.water == WATER_RIVER)[..., None], np.array(RIVER), rgb)
    rgb = np.where((r.ice & (r.water != WATER_SEA))[..., None], np.array(ICE) * (0.6 + 0.4 * shade)[..., None], rgb)
    return rgb


def layer_forms(r: Rasters) -> np.ndarray:
    table = np.array([FORM_COLORS[key] for key, _, _ in forms.FORMS], dtype=float)
    rgb = table[r.form]
    shade = hillshade(r.grid, r.height_m)
    return rgb * (0.6 + 0.4 * shade)[..., None]


def layer_zonal(r: Rasters) -> np.ndarray:
    names = climate.zonal_names(r.params.zonal)
    table = np.array([ZONAL_COLORS.get(name, ZONAL_UNKNOWN) for name in names] + [ZONAL_UNKNOWN], dtype=float)
    rgb = table[np.minimum(r.zonal, len(names))]
    rgb = np.where((r.water == WATER_SEA)[..., None], np.array(FORM_COLORS["sea"]), rgb)
    rgb = np.where((r.water == WATER_LAKE)[..., None], np.array(LAKE), rgb)
    rgb = np.where((r.ice & (r.water != WATER_SEA))[..., None], np.array(ICE), rgb)
    shade = hillshade(r.grid, r.height_m)
    return rgb * (0.65 + 0.35 * shade)[..., None]


def layer_hardness(r: Rasters) -> np.ndarray:
    grey = (60 + 190 * (r.hardness - 0.25) / 0.75)[..., None] * np.ones(3)
    return np.where((r.water == WATER_SEA)[..., None], np.array(FORM_COLORS["sea"]), grey)


def layer_provinces(r: Rasters) -> np.ndarray:
    """Каждой провинции свой цвет по её коду, море тёмным, рельеф отмывкой."""
    codes = np.arange(int(r.province.max()) + 1)
    hue = (codes * 0.618033988749895) % 1.0
    palette = np.stack([_hue_to_rgb(h) for h in hue]) * 255.0
    palette[0] = FORM_COLORS["sea"]
    rgb = palette[r.province]
    shade = hillshade(r.grid, r.height_m)
    return rgb * (0.6 + 0.4 * shade)[..., None]


def _hue_to_rgb(h: float) -> np.ndarray:
    """Мягкие цвета одной насыщенности по кругу оттенков."""
    k = np.array([0.0, 1.0 / 3.0, 2.0 / 3.0])
    return 0.45 + 0.4 * np.clip(np.abs(((h + k) % 1.0) * 6.0 - 3.0) - 1.0, 0.0, 1.0)


LAYERS = {
    "relief": layer_relief,
    "forms": layer_forms,
    "biomes": layer_zonal,
    "rock": layer_hardness,
    "provinces": layer_provinces,
}


def globe(cell_rgb: np.ndarray, grid: Grid, wide: int) -> np.ndarray:
    """Планета целиком: равнопромежуточная проекция, север вверху."""
    tall = max(1, wide // 2)
    lon = -180.0 + (np.arange(wide) + 0.5) * (360.0 / wide)
    lat = 90.0 - (np.arange(tall) + 0.5) * (180.0 / tall)
    return cell_rgb[grid.cell(lat[:, None], lon[None, :])]


def frame(
    cell_rgb: np.ndarray, grid: Grid, at: tuple[float, float], width_m: float, height_m: float, wide: int
) -> np.ndarray:
    """Окно вокруг точки в честных метрах, север вверху.

    Пиксель — точка на сфере в стольких-то метрах и такую-то сторону от
    середины кадра, а не смещение по индексам: на равноплощадной сетке у
    индекса нет направления, а у метров и румба — есть, и одно и то же окно
    в 60 км на экваторе и у полюса выходит одним и тем же куском земли.
    """
    tall = max(1, int(round(wide * height_m / width_m)))
    east = ((np.arange(wide) + 0.5) / wide - 0.5) * width_m
    north = (0.5 - (np.arange(tall) + 0.5) / tall) * height_m
    span = np.hypot(east[None, :], north[:, None])
    bearing = np.arctan2(east[None, :], north[:, None])
    lat, lon = healpix.offset(at[0], at[1], grid.radius_m, span, bearing)
    return cell_rgb[grid.cell(lat, lon)]


def to_bytes(rgb: np.ndarray) -> np.ndarray:
    return np.clip(np.round(rgb), 0, 255).astype(np.uint8)


def render_all(r: Rasters, out: Path, focus: tuple[float, float], planet_width: int = 1400) -> list[Path]:
    """Три кадра на каждый слой: планета целиком, область в 60 км, город в 6 км."""
    written: list[Path] = []
    name = r.params.planet
    for layer, paint in LAYERS.items():
        cell_rgb = paint(r)
        frames = (
            ("planet", globe(cell_rgb, r.grid, planet_width)),
            ("region", frame(cell_rgb, r.grid, focus, 60_000.0, 40_000.0, 900)),
            ("city", frame(cell_rgb, r.grid, focus, 6_000.0, 4_000.0, 900)),
        )
        for kind, image in frames:
            path = out / f"{name}_{kind}_{layer}.png"
            png(to_bytes(image), path)
            written.append(path)
    return written
