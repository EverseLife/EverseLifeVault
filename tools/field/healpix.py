# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Равноплощадная сетка HEALPix (D-328, план ландшафта §4.1).

Сфера режется на двенадцать базовых граней, каждая — на `nside × nside`
клеток. Все `12 · nside²` клеток **точно равны по площади**, у полюса клетка
такая же, как на экваторе, и вырожденных клеток нет нигде.

Клетка адресуется тройкой `(грань, ix, iy)` и хранится плоско по правилу
`грань · nside² + iy · nside + ix`. Такая раскладка — не деталь: каждая грань
остаётся квадратом, поэтому растр остаётся двумерной текстурой, а выборка
между клетками внутри грани достаётся клиенту от железа даром (D-328).

**`nside` здесь — любое целое.** Классические формулы HEALPix пишут через
сдвиги битов, и оттого во всех библиотеках `nside` — степень двойки; но
степень двойки нужна не сетке, а её вложенной нумерации, которой мы не
пользуемся. Сдвиги заменены делением с остатком, и сетка становится ровно
такой дробности, какой просит вольт: `terrain.step_m` один на все планеты,
а `nside` у каждой свой (D-328).

Соседи строятся один раз геометрией, а не таблицей битовых хитростей: это и
проще, и проверяется тестом на взаимность — если Б сосед А, то и А сосед Б.
Подробности правила — у `neighbours`.
"""

from __future__ import annotations

import math

import numpy as np

#: Двенадцать базовых граней: номер кольца и номер по долготе (из статьи
#: Гурского и др.; те же таблицы, что во всех реализациях HEALPix).
JRLL = np.array([2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4])
JPLL = np.array([1, 3, 5, 7, 0, 2, 4, 6, 1, 3, 5, 7])

#: Граница между экваториальным поясом и полярными шапками по синусу широты.
POLAR_Z = 2.0 / 3.0

def npix(nside: int) -> int:
    """Сколько клеток на планете."""
    return 12 * int(nside) * int(nside)


def nside_for(radius_m: float, step_m: float) -> int:
    """Дробность планеты из общего шага вольта (D-328).

    Площадь клетки — площадь сферы, делённая на `12 nside²`, поэтому сторона
    равновеликого квадрата это `R √(π/3) / nside`. Отсюда и обратное.
    """
    return max(1, int(round(radius_m * math.sqrt(math.pi / 3.0) / step_m)))


def cell_area_m2(radius_m: float, nside: int) -> float:
    """Площадь клетки — одна и та же у всех клеток планеты."""
    return 4.0 * math.pi * radius_m * radius_m / npix(nside)


def cell_side_m(radius_m: float, nside: int) -> float:
    """Сторона равновеликого квадрата: чем клетка меряется в метрах."""
    return math.sqrt(cell_area_m2(radius_m, nside))


def ang2pix(nside: int, lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    """Клетка, в которую попадает точка. Широта и долгота — градусы."""
    face, ix, iy = ang2fxy(nside, lat_deg, lon_deg)
    return fxy2pix(nside, face, ix, iy)


def ang2fxy(
    nside: int, lat_deg: np.ndarray, lon_deg: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Грань и место в ней для точки сферы.

    Прямая проекция HEALPix: экваториальный пояс режется наклонными линиями
    (Ламберт), шапки — Коллиньоном. Границы клеток на стыке двух областей
    совпадают, поэтому шва нет.
    """
    nside = int(nside)
    #: Широта и долгота разлетаются по обычным правилам numpy: столбец широт
    #: на строку долгот — это сетка точек, а не ошибка формы.
    z, phi = np.broadcast_arrays(
        np.sin(np.radians(np.asarray(lat_deg, dtype=np.float64))),
        np.radians(np.asarray(lon_deg, dtype=np.float64)) % (2.0 * math.pi),
    )
    z = np.clip(z, -1.0, 1.0)
    za = np.abs(z)
    #: Долгота в четвертях круга: у HEALPix всё считается в них.
    tt = phi / (math.pi / 2.0)

    face = np.zeros(z.shape, dtype=np.int64)
    ix = np.zeros(z.shape, dtype=np.int64)
    iy = np.zeros(z.shape, dtype=np.int64)

    #: Экваториальный пояс: две системы наклонных линий, восходящая и
    #: нисходящая; по какую сторону от них лежит точка, та и грань.
    belt = za <= POLAR_Z
    if belt.any():
        temp1 = nside * (0.5 + tt[belt])
        temp2 = nside * (z[belt] * 0.75)
        jp = np.floor(temp1 - temp2).astype(np.int64)
        jm = np.floor(temp1 + temp2).astype(np.int64)
        ifp = jp // nside
        ifm = jm // nside
        same = ifp == ifm
        north = ifp < ifm
        f = np.where(same, (ifp & 3) + 4, np.where(north, ifp & 3, (ifm & 3) + 8))
        face[belt] = f
        ix[belt] = jm % nside
        iy[belt] = nside - (jp % nside) - 1

    #: Шапки: точка кладётся в ромб Коллиньона своей четверти.
    cap = ~belt
    if cap.any():
        ntt = np.minimum(3, tt[cap].astype(np.int64))
        tp = tt[cap] - ntt
        #: Ноль под корнем у самого полюса — там вся четверть одна клетка.
        tmp = nside * np.sqrt(np.maximum(0.0, 3.0 * (1.0 - za[cap])))
        jp = np.minimum((tp * tmp).astype(np.int64), nside - 1)
        jm = np.minimum(((1.0 - tp) * tmp).astype(np.int64), nside - 1)
        top = z[cap] >= 0
        face[cap] = np.where(top, ntt, ntt + 8)
        ix[cap] = np.where(top, nside - jm - 1, jp)
        iy[cap] = np.where(top, nside - jp - 1, jm)
    return face, ix, iy


def fxy2pix(nside: int, face: np.ndarray, ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
    """Плоский номер клетки: грань, потом строка внутри грани, потом столбец."""
    nside = int(nside)
    return (face * nside + iy) * nside + ix


def pix2fxy(nside: int, pix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Обратно: из плоского номера в грань и место в ней."""
    nside = int(nside)
    pix = np.asarray(pix, dtype=np.int64)
    face, rest = np.divmod(pix, nside * nside)
    iy, ix = np.divmod(rest, nside)
    return face, ix, iy


def fxy2ang(
    nside: int, face: np.ndarray, ix: np.ndarray, iy: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Середина клетки: широта и долгота в градусах.

    Обратная проекция считается через номер кольца `jr` (сверху вниз) и
    номер в кольце `jp`: у HEALPix клетки лежат кольцами равной широты, и
    это же свойство сохраняет марш влаги по широтным поясам (§4.2).
    """
    nside = int(nside)
    face = np.asarray(face, dtype=np.int64)
    ix = np.asarray(ix, dtype=np.int64)
    iy = np.asarray(iy, dtype=np.int64)
    jr = JRLL[face] * nside - ix - iy - 1
    nl4 = 4 * nside
    three = 3.0 * nside * nside

    north = jr < nside
    south = jr > 3 * nside
    belt = ~(north | south)

    nr = np.where(north, jr, np.where(south, nl4 - jr, nside))
    z = np.where(
        north,
        1.0 - (jr.astype(np.float64) ** 2) / three,
        np.where(
            south,
            ((nl4 - jr).astype(np.float64) ** 2) / three - 1.0,
            (2 * nside - jr) * 2.0 / (3.0 * nside),
        ),
    )
    #: В экваториальном поясе кольца через одно сдвинуты на полклетки.
    kshift = np.where(belt, (jr - nside) & 1, 0)

    jp = (JPLL[face] * nr + ix - iy + 1 + kshift) // 2
    jp = np.where(jp > nl4, jp - nl4, jp)
    jp = np.where(jp < 1, jp + nl4, jp)
    phi = (jp - (kshift + 1) * 0.5) * (math.pi / 2.0) / nr
    lat = np.degrees(np.arcsin(np.clip(z, -1.0, 1.0)))
    lon = ((np.degrees(phi) + 180.0) % 360.0) - 180.0
    return lat, lon


def pix2ang(nside: int, pix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Середина клетки по плоскому номеру."""
    face, ix, iy = pix2fxy(nside, pix)
    return fxy2ang(nside, face, ix, iy)


def centres(nside: int) -> tuple[np.ndarray, np.ndarray]:
    """Середины всех клеток планеты, в порядке плоского номера."""
    return pix2ang(nside, np.arange(npix(nside), dtype=np.int64))


def _xyz(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Точки сферы единичного радиуса, столбцами."""
    rad = np.radians(lat)
    lam = np.radians(lon)
    return np.stack([np.cos(rad) * np.cos(lam), np.cos(rad) * np.sin(lam), np.sin(rad)])


def offset(
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    radius_m: float,
    span_m: np.ndarray | float,
    bearing: np.ndarray | float,
) -> tuple[np.ndarray, np.ndarray]:
    """Куда придёшь, пройдя `span_m` по дуге в направлении `bearing` (радианы
    от севера по часовой). Точка, длина и направление разлетаются по обычным
    правилам numpy: тысяча точек на триста проб вокруг каждой — один вызов.

    Точная формула большого круга, а не сдвиг широты и долготы: у полюса
    приближение делится на косинус широты и уводит шаг на другую сторону
    планеты. Шаг по сфере нужен всем, кто ходит по сетке HEALPix, — соседям,
    прыжковой заливке, прогулке переписи, — потому что клетка здесь ищется
    точкой, а не индексом.
    """
    span = np.asarray(span_m, dtype=np.float64) / float(radius_m)
    lat = np.radians(np.asarray(lat_deg, dtype=np.float64))
    lon = np.radians(np.asarray(lon_deg, dtype=np.float64))
    turn = np.asarray(bearing, dtype=np.float64)
    sin_span, cos_span = np.sin(span), np.cos(span)
    sin_lat, cos_lat = np.sin(lat), np.cos(lat)
    to_lat = np.arcsin(
        np.clip(sin_lat * cos_span + cos_lat * sin_span * np.cos(turn), -1.0, 1.0)
    )
    to_lon = lon + np.arctan2(
        np.sin(turn) * sin_span * cos_lat, cos_span - sin_lat * np.sin(to_lat)
    )
    return np.degrees(to_lat), ((np.degrees(to_lon) + 180.0) % 360.0) - 180.0


def pix2ring(nside: int, pix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Кольцо клетки (с севера, от нуля) и место в кольце по долготе.

    Клетки HEALPix лежат `4 nside - 1` кольцами равной широты. Это то самое
    свойство, ради которого сетка выбрана вместо икосферы: марш влаги идёт
    по широтным поясам (§4.2), и пояс должен быть замкнутым кольцом клеток,
    а не полосой, которую надо собирать поиском.
    """
    nside = int(nside)
    face, ix, iy = pix2fxy(nside, pix)
    jr = JRLL[face] * nside - ix - iy - 1
    north, south = jr < nside, jr > 3 * nside
    nr = np.where(north, jr, np.where(south, 4 * nside - jr, nside))
    kshift = np.where(north | south, 0, (jr - nside) & 1)
    jp = (JPLL[face] * nr + ix - iy + 1 + kshift) // 2
    return jr - 1, (jp - 1) % (4 * nr)


def ring_lengths(nside: int) -> np.ndarray:
    """Сколько клеток в каждом кольце, с севера на юг."""
    nside = int(nside)
    jr = np.arange(1, 4 * nside)
    nr = np.where(jr < nside, jr, np.where(jr > 3 * nside, 4 * nside - jr, nside))
    return 4 * nr


def ring_table(nside: int) -> tuple[np.ndarray, np.ndarray]:
    """Клетки колец по долготе: `(колец, 4 nside)` номеров и длины колец.

    Короткое кольцо в таблице повторяется: место `s` — это `s` по модулю
    длины кольца. Так шаг марша остаётся одним столбцом на все кольца
    сразу, а полярное кольцо из четырёх клеток просто обходится по кругу
    чаще — оно и по земле короче.
    """
    nside = int(nside)
    lengths = ring_lengths(nside)
    wide = int(lengths.max())
    ring, place = pix2ring(nside, np.arange(npix(nside), dtype=np.int64))
    out = np.zeros((len(lengths), wide), dtype=np.int64)
    out[ring, place] = np.arange(npix(nside), dtype=np.int64)
    #: Разложить короткие кольца по всей ширине: место `s` — по модулю длины.
    seats = np.arange(wide)[None, :] % lengths[:, None]
    return np.take_along_axis(out, seats, axis=1), lengths


#: Сколько сторон света опрашивается в поисках кандидатов и на каких радиусах
#: в долях стороны клетки: клетки HEALPix — ромбы, и восемь румбов по кругу
#: мимо них промахиваются. Шестнадцать на двух радиусах накрывают и рёбра, и
#: углы с запасом.
LOOKS = 16
REACHES = (1.0, 1.45)
#: Сколько ближайших берётся за соседей: у клетки HEALPix восемь соседей —
#: четыре через ребро и четыре через угол.
NEAR = 8
#: А мест под них отводится больше восьми. Объединение «восьми ближайших» с
#: обеих сторон изредка даёт девятого и десятого, и лучше отвести им место,
#: чем срезать: срез — это ровно та несимметрия, из-за которой вода утекала
#: бы в клетку, которая о ней не знает.
WAYS = 12


def neighbours(nside: int, radius_m: float) -> np.ndarray:
    """Соседи каждой клетки: массив `(WAYS, npix)` плоских номеров.

    Соседство здесь — **объединение восьми ближайших с обеих сторон**: пара
    считается соседями, если хоть одна из двух клеток числит другую среди
    своих восьми ближайших. Такое правило симметрично по построению, что и
    проверяет тест: несимметричная таблица сделала бы сток односторонним.

    Почему не порог по расстоянию, как просится: его **не существует**.
    Замер по сетке: восьмой сосед отстоит на 0,8–1,8 стороны клетки, а
    девятый — уже на 1,6–2,0, и эти два разброса перекрываются. Клетки
    HEALPix равны по площади, но не по форме, и у стыков базовых граней
    форма ведёт себя хуже всего.

    Почему не выкладки по граням, как в статье: они точны, но написаны
    сдвигами битов и таблицами обхода двенадцати граней, а проверить их
    можно только другой такой же реализацией. Геометрическое правило
    проверяется тем, что от него нужно, — взаимностью и близостью, — и
    работает при любом `nside` (D-328).

    Свободные места добиваются самой клеткой: вызывающий увидит себя и
    ничего не сделает, а обход по сторонам остаётся обходом.
    """
    count = npix(nside)
    lat, lon = centres(nside)
    side = cell_side_m(radius_m, nside)
    here = _xyz(lat, lon)

    seen: list[np.ndarray] = []
    for reach in REACHES:
        step = reach * side
        for k in range(LOOKS):
            turn = 2.0 * math.pi * k / LOOKS
            seen.append(ang2pix(nside, *offset(lat, lon, radius_m, step, turn)))

    mine = np.arange(count, dtype=np.int64)
    #: Кандидаты повторяются — тридцать два шага попадают в восемь клеток по
    #: многу раз, — и повторы надо снять **до** отбора ближайших, иначе
    #: «восемь ближайших» окажутся восемью копиями двух.
    src = np.repeat(mine, len(seen))
    dst = np.stack(seen, axis=1).reshape(-1)
    own = src != dst
    pairs = np.unique(src[own] * count + dst[own])
    src, dst = np.divmod(pairs, count)

    #: Из них — восемь ближайших каждой клетке.
    apart = -(here[:, src] * here[:, dst]).sum(axis=0)
    order = np.lexsort((apart, src))
    src, dst = src[order], dst[order]
    starts = np.searchsorted(src, mine)
    rank = np.arange(len(src)) - starts[src]
    near = rank < NEAR

    #: И объединение с обратной стороной — вот вся симметрия.
    both = np.unique(np.r_[src[near] * count + dst[near], dst[near] * count + src[near]])
    src, dst = np.divmod(both, count)

    #: По местам без цикла: пары уже отсортированы по хозяину, значит место
    #: каждой — это её номер минус номер первой пары того же хозяина.
    out = np.repeat(mine[None, :].astype(np.int32), WAYS, axis=0)
    starts = np.searchsorted(src, mine)
    seat = np.arange(len(src)) - starts[src]
    fits = seat < WAYS
    out[seat[fits], src[fits]] = dst[fits].astype(np.int32)
    return out
