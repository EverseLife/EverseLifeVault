# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Формы рельефа: класс места по процессу, который его сделал (план §4.3).

Растр формы — то, чего у поля не было вовсе: не «высота 0.7», а «каньон»,
«конус выноса», «дюны». Его читают перепись (§4.4), рендер (§9.6) и, когда
поле приедет в игру, азональный слой биомов (§5) и правило обрыва (§8.2).

Правила — пороги по уклону, местному размаху, стоку, осадку, породе и
климату, в порядке приоритета: вода, ледниковые формы, вулкан, каньон, обрыв,
осыпь, дельта, берег, конус, пойма, долина, хребет, плато, рифт, холмы, лёд,
дюны, каменистая пустыня, равнина. Пороги — в долях размаха, где это высота, и
в м/м, где это уклон: одни и те же на любой планете и любой сетке.

Лёд стоит **низко** — сразу над сушью и над равниной. Он вещество, а не форма:
наверху он забирал всё, до чего дотянулся мороз, и планета, у которой мёрзнет
вся суша, выходила белым шаром без единой черты. Ледниковая долина и фьорд —
другое дело: это формы, вырезанные льдом, и они остаются вверху.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from field.grid import WAYS, Grid

#: Коды форм. Порядок кодов — не приоритет, приоритет ниже в `classify`.
FORMS: tuple[tuple[str, str, str], ...] = (
    ("sea", "Море", "Sea"),
    ("lake", "Озеро", "Lake"),
    ("plain", "Равнина", "Plain"),
    ("hills", "Холмы", "Hills"),
    ("valley", "Долина", "Valley"),
    ("floodplain", "Пойма", "Floodplain"),
    ("delta", "Дельта", "Delta"),
    ("fan", "Конус выноса", "Alluvial fan"),
    ("ridge", "Хребет", "Ridge"),
    ("plateau", "Плато", "Plateau"),
    ("canyon", "Каньон", "Canyon"),
    ("cliff", "Обрыв", "Cliff"),
    ("scree", "Осыпь", "Scree"),
    ("rift", "Рифт", "Rift"),
    ("volcano", "Вулкан", "Volcano"),
    ("glacial", "Ледниковая долина", "Glacial valley"),
    ("fjord", "Фьорд", "Fjord"),
    ("ice", "Лёд", "Ice"),
    ("dunes", "Дюны", "Dunes"),
    ("rocky_desert", "Каменистая пустыня", "Rocky desert"),
    ("coast_cliff", "Скальный берег", "Sea cliff"),
    ("beach", "Пляж", "Beach"),
)
#: Легенда по процессу: цвет у формы один на все планеты, иначе «равнина» на
#: двух снимках была бы разной. Зелени в ней больше нет — она означала бы
#: жизнь там, где сказано про форму (владелец 2026-09-11); равнина, долина и
#: пойма разведены по светлоте и теплоте тона, а не по хлорофиллу.
FORM_COLORS = {
    "sea": (30, 60, 120), "lake": (70, 140, 210), "plain": (198, 186, 158), "hills": (172, 156, 126),
    "valley": (186, 176, 152), "floodplain": (150, 146, 124), "delta": (130, 128, 108), "fan": (220, 200, 140),
    "ridge": (120, 90, 70), "plateau": (190, 160, 110), "canyon": (150, 40, 30), "cliff": (60, 30, 30),
    "scree": (150, 140, 130), "rift": (110, 60, 130), "volcano": (230, 60, 40), "glacial": (160, 200, 230),
    "fjord": (90, 150, 210), "ice": (235, 240, 250), "dunes": (240, 210, 120), "rocky_desert": (200, 160, 100),
    "coast_cliff": (90, 70, 60), "beach": (240, 230, 180),
}

CODE = {key: i for i, (key, _, _) in enumerate(FORMS)}
NAMES_RU = {key: ru for key, ru, _ in FORMS}
NAMES_EN = {key: en for key, _, en in FORMS}
WATER = (CODE["sea"], CODE["lake"])

#: Пороги. Высоты — доли размаха рельефа, уклоны — м/м, окно — доля радиуса.
WINDOW_R = 0.01
#: Обрыв — твёрдая порода выше угла естественного откоса (план §4.3): порог
#: — та же граница осыпания, что у эрозии (`erosion.SLIDE_*`), в этой доле.
#: Мягкая порода такого склона не держит и обрывом не бывает.
CLIFF_SHARE = 0.85
SLIDE_BASE, SLIDE_PER_HARDNESS = 0.35, 1.2
CANYON_RELIEF = 0.07
CANYON_DROP = 0.05
CANYON_HARDNESS = 0.6
CANYON_WALL_SLOPE = 0.22
RIDGE_RELIEF = 0.06
RIDGE_TOP = 0.65
PLATEAU_HEIGHT = 0.3
PLATEAU_SLOPE = 0.04
PLATEAU_RELIEF = 0.035
HILLS_RELIEF = 0.02
VALLEY_RELIEF = 0.025
VALLEY_SLOPE = 0.06
FLOOD_DEPOSIT = 0.004
FLOOD_SLOPE = 0.012
FLOOD_HEIGHT = 0.2
FAN_DEPOSIT = 0.003
FAN_SLOPE = (0.012, 0.08)
DELTA_DEPOSIT = 0.006
COAST_R = 0.01
COAST_CLIFF_SLOPE = 0.15
COAST_CLIFF_HARDNESS = 0.88
RIFT_SHARE = 0.4
VOLCANO_SHARE = 0.35
DRY_RAIN = 0.15
DUNE_HARDNESS = 0.5
DUNE_SLOPE = 0.04
GLACIAL_AREA_M2 = 2.0e7
GLACIAL_RELIEF = 0.03


@dataclass(frozen=True)
class Inputs:
    height_m: np.ndarray
    sea: np.ndarray
    lake: np.ndarray
    river: np.ndarray
    area_m2: np.ndarray
    hardness: np.ndarray
    deposit_m: np.ndarray
    rift: np.ndarray
    volcano: np.ndarray
    ice: np.ndarray
    rain01: np.ndarray
    relief_m: float


def classify(grid: Grid, i: Inputs) -> np.ndarray:
    h = i.height_m / i.relief_m
    land = ~i.sea
    slope = grid.slope(i.height_m)
    window = grid.cells_for_metres(WINDOW_R * grid.radius_m)
    local = grid.local_range(i.height_m, window) / i.relief_m
    top = i.height_m.copy()
    bottom = i.height_m.copy()
    for _ in range(window):
        t, b = top.copy(), bottom.copy()
        for k in range(WAYS):
            t = np.maximum(t, grid.shift(top, k))
            b = np.minimum(b, grid.shift(bottom, k))
        top, bottom = t, b
    above_floor = (i.height_m - bottom) / i.relief_m
    below_top = (top - i.height_m) / i.relief_m
    deposit = i.deposit_m / i.relief_m
    coast_cells = grid.cells_for_metres(COAST_R * grid.radius_m)
    near_sea = grid.dilate_distance(i.sea, coast_cells) < coast_cells
    near_sea &= land

    form = np.full(h.shape, CODE["plain"], dtype=np.uint8)
    done = np.zeros(h.shape, dtype=bool)

    def put(key: str, mask: np.ndarray) -> None:
        nonlocal form, done
        hit = mask & ~done
        form[hit] = CODE[key]
        done |= hit

    put("sea", i.sea)
    put("lake", i.lake)
    trough = i.ice & (i.area_m2 >= GLACIAL_AREA_M2) & (local >= GLACIAL_RELIEF)
    put("fjord", trough & near_sea)
    put("glacial", trough)
    put("volcano", i.volcano >= VOLCANO_SHARE)
    canyon_floor = (
        i.river & (local >= CANYON_RELIEF) & (below_top >= CANYON_DROP) & (i.hardness >= CANYON_HARDNESS)
    )
    wall = np.zeros_like(canyon_floor)
    for k in range(WAYS):
        wall |= grid.shift(canyon_floor, k)
    put("canyon", canyon_floor | (wall & (slope >= CANYON_WALL_SLOPE)))
    cliff = slope >= CLIFF_SHARE * (SLIDE_BASE + SLIDE_PER_HARDNESS * i.hardness)
    put("cliff", cliff)
    under = np.zeros_like(cliff)
    for k in range(WAYS):
        under |= grid.shift(cliff, k) & (grid.shift(i.height_m, k) > i.height_m)
    put("scree", under & land)
    put("delta", near_sea & (deposit >= DELTA_DEPOSIT) & i.river)
    put("coast_cliff", near_sea & ((slope >= COAST_CLIFF_SLOPE) | (i.hardness >= COAST_CLIFF_HARDNESS)))
    put("beach", near_sea)
    steep_near = grid.dilate_distance(local >= RIDGE_RELIEF, window * 3) < window * 3
    put("fan", (deposit >= FAN_DEPOSIT) & (slope >= FAN_SLOPE[0]) & (slope < FAN_SLOPE[1]) & steep_near)
    put("floodplain", (deposit >= FLOOD_DEPOSIT) & (slope < FLOOD_SLOPE) & (h < FLOOD_HEIGHT))
    put("valley", i.river & (local >= VALLEY_RELIEF) & (slope < VALLEY_SLOPE))
    put("ridge", (local >= RIDGE_RELIEF) & (above_floor >= RIDGE_TOP * local))
    put("plateau", (h >= PLATEAU_HEIGHT) & (slope < PLATEAU_SLOPE) & (local < PLATEAU_RELIEF))
    put("rift", (i.rift >= RIFT_SHARE) & (above_floor < 0.3 * np.maximum(local, 1e-9)))
    #: Холмы остаются холмами и в пустыне: сушь — форма только ровной земли.
    put("hills", local >= HILLS_RELIEF)
    #: Лёд — **вещество, а не форма**, и стоит он поэтому здесь, а не третьим
    #: сверху (владелец, 2026-09-10). Наверху он забирал всё, до чего дотянулся
    #: мороз: на Авроре, где мёрзнет вся суша, карта была бы белым шаром без
    #: хребтов, каньонов и плато — ни глазом различить место, ни разведке. Внизу
    #: он остаётся тем, что и есть: покровом над землёй, у которой своей формы
    #: нет. Игру это не трогает — биом читает растр `ice`, а не форму, — но
    #: карта под ним снова читается.
    put("ice", i.ice)
    dry = i.rain01 < DRY_RAIN
    put("dunes", dry & (i.hardness < DUNE_HARDNESS) & (slope < DUNE_SLOPE))
    put("rocky_desert", dry)
    return form
