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
from field.forms import FORM_COLORS
from field.grid import Grid
from field.pipeline import FLUID_LAVA, WATER_LAKE, WATER_RIVER, WATER_SEA, Rasters

#: Свет: с северо-запада, под 45°, и во сколько раз рельеф подчёркнут.
SUN_AZIMUTH_DEG = 315.0
SUN_ALTITUDE_DEG = 45.0
EXAGGERATION = 2.0
#: Гипсометрия суши: доли размаха и цвета.
#: Шкала высот — **порода, а не покров** (владелец 2026-09-11). Была земной
#: гипсометрией: низина зелёная, потому что на Земле низины зелёные. Зелёный
#: цвет при этом означал высоту, а читался как жизнь — оттого Пироксис
#: выходил травянистым, а Аврора луговой. Теперь он идёт от почвы к камню и
#: снегу, а зелень кладётся поверх отдельным слоем по растру `plants`.
HYPSO = (
    (0.00, (150, 140, 115)),
    (0.08, (166, 152, 122)),
    (0.20, (186, 172, 134)),
    (0.40, (170, 130, 80)),
    (0.65, (140, 110, 95)),
    (0.85, (200, 200, 200)),
    (1.00, (255, 255, 255)),
)
#: Цвет самого густого покрова. Один на все планеты и на все слои: зелёный на
#: карте берётся отсюда и больше ниоткуда.
PLANTS = (56, 112, 52)
#: Шкала высот **земной** планеты — зелёная низина, бурый склон, снежная
#: вершина. На лавовой она врала громче всего, что есть в этих снимках:
#: владелец 2026-09-10 увидел на Пироксисе зелень и снег, а там ни травы,
#: ни снега нет и быть не может — это была шкала, а не поле. Базальтовая
#: идёт от свежего тёмного потока к пеплу и выгоревшей породе, и белого в
#: ней нет вовсе: снежная вершина при +100 °C — та же ложь, что и луг.
HYPSO_BASALT = (
    (0.00, (46, 38, 40)),
    (0.10, (72, 56, 52)),
    (0.28, (104, 74, 60)),
    (0.50, (132, 98, 74)),
    (0.72, (158, 126, 96)),
    (0.88, (186, 160, 132)),
    (1.00, (206, 186, 162)),
)
SEA_SHALLOW = (110, 160, 210)
SEA_DEEP = (20, 50, 110)
LAKE = (70, 140, 210)
RIVER = (40, 110, 200)
ICE = (235, 240, 250)
#: Лава: тот же растр воды, другое вещество (`Params.fluid`). Глубина светлеет,
#: а не темнеет — вода темнеет оттого, что свет в неё не доходит, а лава
#: светится сама, и раскрашенная по-морскому она читалась грязью.
LAVA_SHALLOW = (150, 45, 20)
LAVA_DEEP = (255, 190, 90)
LAVA_LAKE = (240, 140, 45)
LAVA_RIVER = (255, 165, 60)

ZONAL_COLORS = {
    "tundra": (200, 210, 200), "taiga": (40, 90, 70), "desert": (240, 210, 130), "semidesert": (210, 180, 110),
    "steppe": (200, 190, 90), "savanna": (190, 170, 60), "rainforest": (20, 100, 40), "woodland": (120, 150, 60),
    "forest": (60, 130, 60),
    #: Мёртвые края таблицы (D-329): холоднее тундры и жарче пустыни ничего
    #: не растёт. Без них слой рисовал бы их розовым «класса нет».
    "ice": (235, 240, 250), "cinder": (60, 50, 55),
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


def _fluid_colours(r: Rasters) -> tuple[tuple, tuple, tuple, tuple]:
    """Мелко, глубоко, озеро, река — в цветах того, что на этой планете течёт."""
    if r.params.fluid == FLUID_LAVA:
        return LAVA_SHALLOW, LAVA_DEEP, LAVA_LAKE, LAVA_RIVER
    return SEA_SHALLOW, SEA_DEEP, LAKE, RIVER


def _greened(r: Rasters, rgb: np.ndarray) -> np.ndarray:
    """Покров поверх породы: доля растра `plants` подмешивает зелень.

    Не подкраска, а слой. Земля под ним остаётся своего цвета, и на планете
    без покрова его просто нет — ни оговорки, ни ветки про планету.
    """
    share = np.clip(r.plants, 0.0, 1.0)[..., None]
    return rgb * (1.0 - share) + np.array(PLANTS) * share


def layer_relief(r: Rasters) -> np.ndarray:
    share = np.clip(r.height_m / r.params.relief_m, 0.0, 1.0)
    rgb = _greened(r, _ramp(share, HYPSO_BASALT if r.params.fluid == FLUID_LAVA else HYPSO))
    shade = hillshade(r.grid, r.height_m)
    rgb = rgb * (0.45 + 0.55 * shade)[..., None]
    depth = np.clip(-r.height_m / 2000.0, 0.0, 1.0)
    shallow, deep, lake, river = _fluid_colours(r)
    sea = np.array(shallow) * (1 - depth)[..., None] + np.array(deep) * depth[..., None]
    rgb = np.where((r.water == WATER_SEA)[..., None], sea, rgb)
    rgb = np.where((r.water == WATER_LAKE)[..., None], np.array(lake), rgb)
    rgb = np.where((r.water == WATER_RIVER)[..., None], np.array(river), rgb)
    rgb = np.where(r.ice[..., None], np.array(ICE) * (0.6 + 0.4 * shade)[..., None], rgb)
    return rgb


def layer_forms(r: Rasters) -> np.ndarray:
    table = np.array([FORM_COLORS[key] for key, _, _ in forms.FORMS], dtype=float)
    #: Слой форм — легенда по процессу, и цвет в ней у формы один на все
    #: планеты: иначе «равнина» на двух снимках была бы разной. Море и озеро
    #: — исключение, и не ради красоты: форма у них одна, а **вещество**
    #: разное, и синее море на лавовой планете говорит неправду о том, что в
    #: нём (владелец 2026-09-10). Поток лавы формы не имеет вовсе — он суша,
    #: залитая расплавом, — и красится тут же, по растру воды.
    rgb = table[r.form]
    if r.params.fluid == FLUID_LAVA:
        _, deep, lake, river = _fluid_colours(r)
        #: По растру воды, а не по коду формы. Лавовый поток формы не имеет
        #: вовсе — он суша, залитая расплавом, — а лавовое озеро формы `lake`
        #: не получает: её ставит `flow.lake`, которого на планете без воды
        #: нет. Красить таблицу форм было мёртвой строкой: кода `lake` в
        #: паспорте Пироксиса просто не появляется, и озёра выходили цветом
        #: суши.
        rgb = np.where((r.water == WATER_SEA)[..., None], np.array(deep), rgb)
        rgb = np.where((r.water == WATER_LAKE)[..., None], np.array(lake), rgb)
        rgb = np.where((r.water == WATER_RIVER)[..., None], np.array(river), rgb)
    shade = hillshade(r.grid, r.height_m)
    return rgb * (0.6 + 0.4 * shade)[..., None]


def layer_zonal(r: Rasters) -> np.ndarray:
    names = climate.zonal_names(r.params.zonal)
    table = np.array([ZONAL_COLORS.get(name, ZONAL_UNKNOWN) for name in names] + [ZONAL_UNKNOWN], dtype=float)
    rgb = table[np.minimum(r.zonal, len(names))]
    _, deep, lake, _ = _fluid_colours(r)
    rgb = np.where((r.water == WATER_SEA)[..., None], np.array(deep), rgb)
    rgb = np.where((r.water == WATER_LAKE)[..., None], np.array(lake), rgb)
    #: Припай — тоже лёд: с этой волны растр покрывает и морскую воду
    #: холоднее `terrain.ice_c`, и синее море Авроры под ним было бы
    #: неправдой при −25 °C на экваторе.
    rgb = np.where(r.ice[..., None], np.array(ICE), rgb)
    shade = hillshade(r.grid, r.height_m)
    return rgb * (0.65 + 0.35 * shade)[..., None]


def layer_hardness(r: Rasters) -> np.ndarray:
    """Твёрдость породы — **везде**, дно океана в том числе.

    Море закрывалось плоской синей заливкой, и слой породы обрывался на
    берегу: у планеты будто не было дна (владелец 2026-09-11: «а почему на
    слое „порода“ мы не показываем породу в океане»). Порода там есть и
    всегда была — плиты строятся по всему шару, — прятал её только рисунок.
    Вода теперь лишь притеняет: под ней видно тот же камень, на полтона
    темнее и с синевой, чтобы берег читался.
    """
    grey = (60 + 190 * (r.hardness - 0.25) / 0.75)[..., None] * np.ones(3)
    under = grey * 0.82 + np.array([0.0, 10.0, 38.0])
    return np.where((r.water == WATER_SEA)[..., None], under, grey)


def layer_plants(r: Rasters) -> np.ndarray:
    """Один покров и ничего кроме: сколько земли под зеленью.

    Слой заведён вместе с растром (владелец 2026-09-11). На нём и видно, чего
    стоит симуляция: где зелень стоит стеной, где её нет вовсе и где она
    тянется ниткой вдоль реки по сухой степи.
    """
    bare = np.array([170.0, 160.0, 140.0])
    share = np.clip(r.plants, 0.0, 1.0)[..., None]
    rgb = bare * (1.0 - share) + np.array(PLANTS) * share
    #: Вода — водой, и река тоже: покрова на ней нет по определению, и без
    #: этой строки русло выходило цветом голой земли — бледной ниткой поперёк
    #: зелени, то есть ровно наоборот тому, что вокруг него растёт.
    _, deep, lake, river = _fluid_colours(r)
    rgb = np.where((r.water == WATER_SEA)[..., None], np.array(deep), rgb)
    rgb = np.where((r.water == WATER_LAKE)[..., None], np.array(lake), rgb)
    rgb = np.where((r.water == WATER_RIVER)[..., None], np.array(river), rgb)
    rgb = np.where(r.ice[..., None], np.array(ICE), rgb)
    shade = hillshade(r.grid, r.height_m)
    return rgb * (0.65 + 0.35 * shade)[..., None]


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
    "plants": layer_plants,
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


#: Ширина и высота двух ближних кадров в долях радиуса планеты, а не в
#: метрах. Метрами это было 60 x 40 км и 6 x 4 км, и держалось, пока у Терры
#: было 99,5 км радиуса: доли взяты ровно те. При ужатии планет кадр области
#: в шестьдесят километров оказался бы шире самой планеты, и «окно вокруг
#: точки в честных метрах» нарисовало бы землю по нескольку раз.
REGION_R, REGION_TALL_R = 0.603, 0.402
CITY_R, CITY_TALL_R = 0.0603, 0.0402


def render_all(r: Rasters, out: Path, focus: tuple[float, float], planet_width: int = 1400) -> list[Path]:
    """Три кадра на каждый слой: планета целиком, область и город — в долях радиуса."""
    written: list[Path] = []
    name = r.params.planet
    radius = r.grid.radius_m
    for layer, paint in LAYERS.items():
        cell_rgb = paint(r)
        frames = (
            ("planet", globe(cell_rgb, r.grid, planet_width)),
            ("region", frame(cell_rgb, r.grid, focus, REGION_R * radius, REGION_TALL_R * radius, 900)),
            ("city", frame(cell_rgb, r.grid, focus, CITY_R * radius, CITY_TALL_R * radius, 900)),
        )
        for kind, image in frames:
            path = out / f"{name}_{kind}_{layer}.png"
            png(to_bytes(image), path)
            written.append(path)
    return written
