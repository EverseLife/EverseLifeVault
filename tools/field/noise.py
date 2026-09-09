# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Шум на сфере: значение по решётке в трёх координатах, октавами.

Та же конструкция, что у поля игры до этого плана (`src/relief.py`): точки
берутся через x, y, z, а не через широту и долготу, поэтому у шума нет ни шва
на антимеридиане, ни полюса. Тот же целочисленный хеш — одно и то же на любой
машине. Здесь он служит не рельефом, а зерном: искривляет границы плит,
разнообразит породу и кладёт мелочь под сетку.
"""

from __future__ import annotations

import numpy as np

PERSISTENCE = 0.5
ROUGHNESS = 2.0


def _hash3(seed: int, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    h = (
        x.astype(np.int64) * 374761393
        + y.astype(np.int64) * 668265263
        + z.astype(np.int64) * 2147483647
        + int(seed) * 1274126177
    ) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    h = (h ^ (h >> 16)) & 0xFFFFFFFF
    return h / float(0x100000000)


def _smooth(t: np.ndarray) -> np.ndarray:
    return t * t * (3.0 - 2.0 * t)


def _value_noise(seed: int, px: np.ndarray, py: np.ndarray, pz: np.ndarray) -> np.ndarray:
    x0, y0, z0 = np.floor(px), np.floor(py), np.floor(pz)
    fx, fy, fz = _smooth(px - x0), _smooth(py - y0), _smooth(pz - z0)
    out = np.zeros_like(px)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                corner = _hash3(seed, x0 + dx, y0 + dy, z0 + dz)
                weight = (fx if dx else 1 - fx) * (fy if dy else 1 - fy) * (fz if dz else 1 - fz)
                out = out + corner * weight
    return out


def fractal(seed: int, xyz: np.ndarray, lattice: float, octaves: int) -> np.ndarray:
    """Шум в [0, 1] в точках единичной сферы `xyz` (..., 3): первая октава
    кладёт `lattice` клеток решётки поперёк диаметра, каждая следующая вдвое мельче."""
    x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
    total = np.zeros(x.shape, dtype=float)
    amplitude, frequency, norm = 1.0, float(lattice), 0.0
    for octave in range(octaves):
        shift = octave * 17.0
        total += amplitude * _value_noise(
            seed + octave, x * frequency + shift, y * frequency + shift, z * frequency + shift
        )
        norm += amplitude
        amplitude *= PERSISTENCE
        frequency *= ROUGHNESS
    return total / norm


def centred(seed: int, xyz: np.ndarray, lattice: float, octaves: int) -> np.ndarray:
    """Тот же шум, но в [-1, 1]."""
    return (fractal(seed, xyz, lattice, octaves) - 0.5) * 2.0


def ridged(seed: int, xyz: np.ndarray, lattice: float, octaves: int) -> np.ndarray:
    """Гребенчатый шум в [0, 1]: острые хребты вместо круглых бугров — таким
    ложится мелочь на твёрдой породе."""
    return 1.0 - np.abs(centred(seed, xyz, lattice, octaves))


def lattice_for(radius_m: float, feature_m: float) -> float:
    """Частота шума, у которого длина волны первой октавы — `feature_m`."""
    return 2.0 * radius_m / feature_m
