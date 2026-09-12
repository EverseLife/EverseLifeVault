# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Сток: куда течёт каждая клетка, сколько площади через неё проходит, где вода.

Три шага, как в любой гидрологии на сетке:

1. **Заливка** (priority flood): впадины поднимаются до уровня своего слива,
   чтобы у каждой клетки суши был путь к морю. Поднятое — озеро.
2. **Приёмник**: из соседей тот, к которому круче всего вниз по залитому
   рельефу; у моря и у дна озера приёмник — сама клетка.
3. **Накопление**: клетки перебираются сверху вниз, и каждая отдаёт свою
   площадь приёмнику. Где площади много — река; река сливается с рекой
   сама собой, без единой нитки, нарисованной рукой.
4. **Захват** (только у последнего стока конвейера, `CAPTURE_*`): русло в
   нескольких клетках от русла крупнее и ниже отдаёт ему воду, а перемычка
   между ними прорезается. Спуск по самому крутому уклону сам этого не
   делает: он ведёт вниз по склону, а не вбок.

Заливка и накопление — циклы на Python: у них есть порядок, который numpy
не выражает. Это цена одной сборки вольта, не старта сервера (план §4.8).

На равноплощадной сетке (D-328) сосед — номер стороны, а не сдвиг индекса,
и площадь клетки — одно число на планету: сток больше не идёт по узким
полярным клеткам иначе, чем по экваториальным.
"""

from __future__ import annotations

import array
import heapq
from dataclasses import dataclass

import numpy as np

from field.grid import WAYS, Grid

#: Насколько залитая клетка выше своего слива: чтобы по плоскому дну озера
#: вода всё-таки шла к выходу, а не стояла.
FILL_EPS = 0.01
#: Озеро — где заливка подняла клетку выше этого, метры.
LAKE_DEPTH_M = 3.0
#: Предвзятость выбора спуска: во столько раз уклон в глазах клетки может
#: быть больше или меньше честного.
WOBBLE = 0.6
#: Захват русла: русло отдаёт воду более крупному руслу, которое течёт не
#: дальше `terrain.capture_reach_m` от него (реестр; конвейер переводит в
#: клетки) и **ниже** его. Спуск по
#: самому крутому уклону кладёт на ровный склон **параллельные** русла: у
#: каждой клетки честный спуск — вниз по склону, а не вбок, и два ручья идут
#: в ногу, разделённые гребнем в метр-другой, которого ни один не режет
#: (эрозия режет только под руслом). Так на Терре две реки по 20 и 60 км²
#: шли в 130–250 м друг от друга последние полкилометра и впадали в один
#: залив двумя устьями (владелец 2026-09-11: «реки не сливаются, хотя там
#: логично что они сливаются»).
#:
#: Настоящая река такой гребень прорывает — подмывом или перехватом, — и
#: здесь это отдельный ход после спуска: перемычка между руслами
#: прорезается до уровня, спадающего от меньшего русла к большему, и
#: меньшее течёт по ней. Берёт **ниже** и **крупнее**: ниже — потому что
#: вода не идёт вверх, и это же держит сток без колец (каждое звено, старое
#: или новое, строго ниже предыдущего по залитой высоте); крупнее — чтобы у
#: двух русел был один ответ, кто в кого, иначе они менялись бы водой на
#: каждом шаге и сплетались в косу. Слияние только с соседом (как стояло
#: сперва) не сводило ничего: параллельные русла держат две-пять клеток
#: между собой, а не одну.
#:
#: Два прохода: слившись, русло встаёт рядом с третьим, которому раньше
#: было не с чем сливаться; и русло, потерявшее воду, само стало меньше
#: соседей и само идёт к ним. Число проходов — сходимость, процесс; а вот
#: досягаемость — ручка географии, и живёт она в реестре.
CAPTURE_PASSES = 2


def _jitter(grid: Grid, salt: int = 0) -> np.ndarray:
    """Число в [-1, 1] на клетку, одно и то же на любой машине: хеш индекса."""
    flat = np.arange(grid.count, dtype=np.int64)
    h = (flat * 2654435761 + 97 + salt * 40503) & 0xFFFFFFFF
    h = (h ^ (h >> 15)) * 2246822519 & 0xFFFFFFFF
    return h / float(0x100000000) * 2.0 - 1.0


def _ways(grid: Grid) -> array.array:
    """Соседи всех клеток одним плоским рядом целых для циклов на Python.

    Не `tolist()`: девять миллионов объектов `int` на Терре — это треть
    гигабайта, а `array` держит их четырьмя байтами и делает целое только
    на чтении.
    """
    flat = array.array("i")
    assert flat.itemsize == 4, "тип 'i' обязан быть четырёхбайтным"
    flat.frombytes(np.ascontiguousarray(grid.near.T, dtype=np.int32).tobytes())
    return flat


@dataclass(frozen=True)
class Flow:
    filled: np.ndarray  # залитая высота, м
    receiver: np.ndarray  # номер клетки-приёмника
    order: np.ndarray  # номера клеток сверху вниз
    slope: np.ndarray  # уклон к приёмнику, м/м
    distance: np.ndarray  # расстояние до приёмника, м
    area_m2: np.ndarray  # накопленная площадь, м²
    lake: np.ndarray  # bool: клетка суши под водой озера


def fill(height: np.ndarray, sea: np.ndarray, grid: Grid) -> np.ndarray:
    """Priority flood: высоты, у которых у каждой клетки суши есть спуск к морю."""
    count = grid.count
    h = height.ravel().tolist()
    sea_flat = np.asarray(sea).ravel()
    filled = [float("inf")] * count
    #: Списки, не массивы: цикл ниже трогает по одной клетке, и индексация
    #: numpy поштучно в разы дороже списка.
    closed = sea_flat.tolist()
    #: Затравка — море у берега: внутренние клетки моря закрыты и так, а в
    #: кучу их класть незачем.
    coast = np.zeros(count, dtype=bool)
    for k in range(WAYS):
        coast |= sea_flat & ~sea_flat[grid.near[k]]
    heap: list[tuple[float, int]] = []
    for flat in np.flatnonzero(coast).tolist():
        filled[flat] = h[flat]
        heap.append((h[flat], flat))
    for flat in np.flatnonzero(sea_flat).tolist():
        filled[flat] = h[flat]
    heapq.heapify(heap)
    ways = _ways(grid)
    while heap:
        level, flat = heapq.heappop(heap)
        #: Свободное место соседа — сама клетка, а она к этому мигу закрыта.
        for n in ways[flat * WAYS : flat * WAYS + WAYS]:
            if closed[n]:
                continue
            closed[n] = True
            value = h[n]
            if value < level + FILL_EPS:
                value = level + FILL_EPS
            filled[n] = value
            heapq.heappush(heap, (value, n))
    out = np.array(filled, dtype=float)
    #: Клетка, до которой вода не дошла (нет моря вовсе — сухая планета), остаётся собой.
    return np.where(np.isinf(out), np.asarray(height).ravel(), out)


def receivers(
    filled: np.ndarray,
    grid: Grid,
    wobble: float = 0.0,
    pull: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Приёмник каждой клетки, уклон к нему и расстояние до него.

    Приёмник всегда ниже — среди соседей выбирается спуск. Какой из
    спусков, решает уклон, помноженный на `1 ± wobble` от хеша клетки и
    стороны: на гладком склоне честно самый крутой — одна и та же прямая
    через всю гору, а чуть предвзятый выбор ломает её в русло, которое
    вьётся. Уклон возвращается честный.

    `pull` — множитель очка соседа, если кому-то нужен предвзятый спуск;
    сам конвейер его не подаёт: тяга к соседу с большей водой параллельные
    русла не сводит, они на одной высоте (см. `CAPTURE_*`).
    """
    count = grid.count
    best_score = np.zeros(count)
    best_slope = np.zeros(count)
    best_index = np.arange(count, dtype=np.int64)
    best_dist = np.full(count, grid.side_m)
    for k in range(WAYS):
        dist = grid.distances[k]
        slope = (filled - filled[grid.near[k]]) / dist
        score = slope * (1.0 + wobble * _jitter(grid, k)) if wobble else slope
        if pull is not None:
            score = score * pull[grid.near[k]]
        better = (slope > 0.0) & (score > best_score)
        best_score = np.where(better, score, best_score)
        best_slope = np.where(better, slope, best_slope)
        best_index = np.where(better, grid.near[k], best_index)
        best_dist = np.where(better, dist, best_dist)
    return best_index, best_slope, best_dist


def accumulate(receiver: np.ndarray, order: np.ndarray, area: np.ndarray) -> np.ndarray:
    """Площадь, стекающая через каждую клетку: своя плюс всё, что выше."""
    total = area.astype(float).tolist()
    recv = receiver.tolist()
    for i in order.tolist():
        j = recv[i]
        if j != i:
            total[j] += total[i]
    return np.array(total)


def widths(
    flow: Flow,
    river: np.ndarray,
    *,
    narrow_m: float,
    wide_m: float,
    merge: float,
) -> np.ndarray:
    """Ширина русла в каждой клетке реки, метры.

    **Слияние берёт долю суммы, а не сумму** (владелец 2026-09-11: «если две
    реки вливаются в одну, то ширина получившейся — сумма ширин входящих на
    0,5»). Прежде ширина бралась у расхода по закону `k·√A`, и две равные
    реки давали в полтора раза более широкую; теперь они дают ровно такую же.

    Две оговорки, обе нужны, иначе правило само себя съедает.

    * **Русло не сужается.** У клетки реки впадающая чаще всего одна, и
      половина от одной ширины — это половина реки на каждом шаге вниз:
      правило, взятое буквально, свело бы всякую реку к нулю через десяток
      клеток. Поэтому берётся то, что больше, — самая широкая из впадающих
      или доля их суммы. Для двух равных это и есть доля суммы, как сказано;
      для магистрали, в которую впал ручей, — сама магистраль.
    * **Пол.** Исток начинается с `narrow_m`, и уже этого лента не бывает.

    Что из правила выходит на деле, стоит сказать прямо: слияний по три и
    больше в одной клетке мало, а слияния по два ширину не меняют вовсе, —
    значит река почти всюду одной ширины, и это осознанный выбор владельца, а
    не побочный эффект.
    """
    count = river.size
    width = np.zeros(count)
    #: Сумма ширин впадающих и самая широкая из них — накапливаются, пока
    #: обход идёт сверху вниз, и к своей клетке приходят готовыми.
    carried = np.zeros(count)
    biggest = np.zeros(count)
    recv = flow.receiver.tolist()
    wet = river.tolist()
    total = carried.tolist()
    top = biggest.tolist()
    out = width.tolist()
    for i in flow.order.tolist():
        if not wet[i]:
            continue
        w = max(narrow_m, top[i], merge * total[i])
        w = min(w, wide_m)
        out[i] = w
        j = recv[i]
        if j != i:
            total[j] += w
            top[j] = max(top[j], w)
    return np.array(out)


def capture(
    filled: np.ndarray,
    grid: Grid,
    receiver: np.ndarray,
    slope: np.ndarray,
    distance: np.ndarray,
    area: np.ndarray,
    sea: np.ndarray,
    threshold_m2: float,
    reach_cells: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Один проход захвата (`CAPTURE_*`): каждое русло — клетка, через
    которую идёт не меньше `threshold_m2` меры `area` — ищет в `reach_cells`
    шагах по суше русло крупнее и ниже себя; берёт ближайшее кольцо, а в
    нём крупнейшее. Перемычка прорезается: залитая высота её клеток
    опускается до прямой от русла к руслу, и каждая клетка пути течёт в
    следующую. `area` — та мера, которой конвейер решает реку: расход, а не
    площадь, иначе захват резал бы гребни под русла, которых рекой не будет.

    Возвращает залитую высоту (прорезанную), приёмник, уклон, расстояние и
    сколько русел сменили приёмник. Кольцо невозможно: звено идёт строго
    вниз по залитой высоте, старое (спуск) и новое (прямая вниз к цели), а
    у клетки перемычки, чья высота опущена, доноры остались выше прежней.
    """
    count = grid.count
    flat = np.arange(count)
    dry = ~np.asarray(sea)
    river = (area >= threshold_m2) & dry & (receiver != flat)
    #: Списки, не массивы: ход ниже трогает по одной клетке, а поштучная
    #: индексация numpy в разы дороже списка.
    level = filled.tolist()
    recv = receiver.tolist()
    size = area.tolist()
    wet = river.tolist()
    land = dry.tolist()
    ways = _ways(grid)
    dist_k = grid.distances
    new_slope = slope.tolist()
    new_dist = distance.tolist()
    moved = 0
    far = 2 * reach_cells
    #: Сверху вниз. Мера `size` внутри прохода не пересчитывается: старое
    #: продолжение захваченного русла в этом же проходе ещё числится
    #: крупным, и нижнее русло может отдать воду ему; следующий проход, с
    #: пересчитанной мерой, это разбирает (`CAPTURE_PASSES`).
    for c in np.flatnonzero(river)[np.argsort(filled[river])[::-1]].tolist():
        if recv[c] == c:
            continue
        own_level = level[c]
        own_size = size[c]
        #: Куда русло и так придёт в ближайшие шаги: туда захват не нужен.
        ahead = set()
        j = c
        for _ in range(far):
            j = recv[j]
            ahead.add(j)
        parent = {c: -1}
        frontier = [c]
        target = -1
        best = 0.0
        for _ in range(reach_cells):
            reached = []
            for p in frontier:
                for n in ways[p * WAYS : p * WAYS + WAYS]:
                    if n == p or n in parent or not land[n]:
                        continue
                    parent[n] = p
                    reached.append(n)
                    if wet[n] and size[n] > own_size and level[n] < own_level and n not in ahead and size[n] > best:
                        target = n
                        best = size[n]
            if target >= 0:
                break
            frontier = reached
        if target < 0:
            continue
        path = [target]
        while path[-1] != c:
            path.append(parent[path[-1]])
        path.reverse()
        steps = len(path) - 1
        #: Перемычка должна лечь строго вниз к цели, на `FILL_EPS` за шаг:
        #: и от самого русла до цели должно хватать перепада на все шаги —
        #: на залитом дне устья уровни идут ступенями по `FILL_EPS`, и цель
        #: на одну ступень ниже в трёх шагах недостижима без подъёма, — и
        #: клетка пути, лежащая ниже своей ступени, — впадина, через
        #: которую прямой дороги нет.
        floor = level[target]
        if own_level - floor <= FILL_EPS * steps:
            continue
        if any(level[p] <= floor + FILL_EPS * (steps - i) for i, p in enumerate(path[1:-1], start=1)):
            continue
        cut = [own_level]
        for i, p in enumerate(path[1:-1], start=1):
            straight = own_level + (floor - own_level) * i / steps
            cut.append(min(level[p], straight, cut[-1] - FILL_EPS))
        cut.append(floor)
        for i in range(steps):
            p, q = path[i], path[i + 1]
            level[p] = cut[i]
            recv[p] = q
            k = ways[p * WAYS : p * WAYS + WAYS].index(q)
            d = float(dist_k[k, p])
            new_dist[p] = d
            new_slope[p] = (cut[i] - cut[i + 1]) / d
        moved += 1
    return (
        np.array(level),
        np.array(recv, dtype=receiver.dtype),
        np.array(new_slope),
        np.array(new_dist),
        moved,
    )


def route(
    height: np.ndarray,
    sea: np.ndarray,
    grid: Grid,
    capture_m2: float | None = None,
    capture_reach_cells: int = 0,
    capture_yield: np.ndarray | None = None,
) -> Flow:
    """Сток по высотам. С `capture_m2` — порогом русла, м² — после спуска
    идёт захват (`capture`): параллельные русла сливаются, а залитая высота
    в `Flow.filled` несёт прорезанные перемычки. Русло для захвата мерится
    тем же, чем конвейер мерит реку: `capture_yield` — отдача клетки, доля
    (`yield_share`), и порог сравнивается с площадью, взвешенной ею; без
    `capture_yield` — с голой площадью. `Flow.area_m2` при этом остаётся
    площадью: ею живёт эрозия. Эрозия зовёт без захвата: она режет долины
    под руслами, какие есть, а захват — последнее слово конвейера над
    готовым рельефом."""
    filled = fill(height, sea, grid)
    own = np.full(grid.count, grid.area_m2)
    receiver, slope, distance = receivers(filled, grid, WOBBLE)
    order = np.argsort(filled)[::-1]
    acc = accumulate(receiver, order, own)
    if capture_m2 is not None and capture_reach_cells > 0:
        weight = own if capture_yield is None else own * np.asarray(capture_yield, dtype=float)
        measure = acc if capture_yield is None else accumulate(receiver, order, weight)
        for _ in range(CAPTURE_PASSES):
            filled, receiver, slope, distance, moved = capture(
                filled, grid, receiver, slope, distance, measure, sea, capture_m2, capture_reach_cells
            )
            if not moved:
                break
            #: Порядок по высоте остаётся верным: каждое звено, старое или
            #: новое, строго ниже предыдущего по залитой высоте.
            order = np.argsort(filled)[::-1]
            acc = accumulate(receiver, order, own)
            measure = acc if capture_yield is None else accumulate(receiver, order, weight)
    lake = (filled - height > LAKE_DEPTH_M) & ~sea
    return Flow(
        filled=filled,
        receiver=receiver,
        order=order,
        slope=slope,
        distance=distance,
        area_m2=acc,
        lake=lake,
    )


#: Сколько раз ломаная русла сглаживается (`smooth_channel`), прежде чем
#: по ней считать ленту. Русло шагает по клеткам — по осям и диагоналям
#: решётки, — и лента, считанная от такой ломаной, на ближних кадрах шла
#: трубой с прямыми коленами (владелец 2026-09-12: «реки выглядят
#: странно»). Точка клетки русла сдвигается к середине между главным
#: притоком и приёмником на четверть с каждой стороны; два раунда
#: расходят угол в девяносто градусов в дугу радиусом около клетки, а
#: прямой плёс не трогают. Клетки русла остаются клетками: сглажена
#: только линия, по которой меряется лента.
CHANNEL_SMOOTH = 2


def smooth_channel(
    grid: Grid,
    river: np.ndarray,
    receiver: np.ndarray,
    carried: np.ndarray,
    rounds: int = CHANNEL_SMOOTH,
) -> np.ndarray:
    """Точки ломаной русла на единичном шаре, сглаженные (`CHANNEL_SMOOTH`):
    у клетки реки — её середина, сдвинутая к середине между её главным
    притоком (тем из соседей-рек, что течёт в неё с наибольшим расходом) и
    её приёмником; у прочих клеток — их середины как есть. Исток без притока
    и устье без приёмника-реки тянутся только к той стороне, что есть."""
    river = np.asarray(river, dtype=bool)
    carried = np.asarray(carried, dtype=float)
    cells = np.arange(grid.count)
    main = np.full(grid.count, -1, dtype=np.int64)
    best = np.full(grid.count, -np.inf)
    for k in range(WAYS):
        n = grid.near[k]
        feeds = river & river[n] & (receiver[n] == cells)
        better = feeds & (carried[n] > best)
        main = np.where(better, n, main)
        best = np.where(better, carried[n], best)
    has_up = main >= 0
    has_down = river & (receiver != cells) & river[receiver]
    up_w = np.where(has_up, 0.25, 0.0)[:, None]
    down_w = np.where(has_down, 0.25, 0.0)[:, None]
    points = np.asarray(grid.xyz, dtype=float).copy()
    for _ in range(rounds):
        moved = (
            points * (1.0 - up_w - down_w)
            + points[np.maximum(main, 0)] * up_w
            + points[receiver] * down_w
        )
        moved = moved / np.linalg.norm(moved, axis=1, keepdims=True)
        points = np.where(river[:, None], moved, points)
    return points


def channel_distance(
    grid: Grid,
    river: np.ndarray,
    receiver: np.ndarray,
    reach_cells: int,
    points: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Ближайшая клетка русла и расстояние до **линии** русла, метры.

    `points` — где стоят вершины ломаной, если не в серединах клеток
    (`smooth_channel`); расстояние всегда меряется от середины клетки.

    Русло — ломаная через середины клеток реки, звено — от клетки к её
    приёмнику. Расстояние до ближайшей **клетки** русла (`grid.nearest`)
    врёт рядом с руслом, идущим по диагонали сетки: боковая клетка стоит
    в полуклетке от линии (35 м при клетке 50), а до ближайшей середины
    клетки русла ей 50, — и лента, записанная по такому расстоянию, на
    диагональных плёсах выходила вдвое уже, а между клетками русла
    пережималась в чётки. Считается по хорде на единичном шаре: на
    десятках метров дуга и хорда — одно.

    Проверяются звенья ближайшей клетки русла — вниз, к её приёмнику, и
    вверх, от каждого её притока-соседа: ближайшая точка ломаной лежит на
    одном из них, кроме углов ломаной, где разница — доли метра. Со
    сглаженными вершинами (`points`) ближайшая **клетка** по-прежнему ищется
    по серединам, а её вершина ушла до трети клетки: во внутренних углах
    лестницы ошибка односторонняя — зазор завышен, лента уже — и до пятой
    доли клетки; конвейер держит клетку русла на линии (`pipeline`, пол
    меры), остальное — цена дуги вместо колена.
    """
    source, _ = grid.nearest(river, reach_cells)
    found = source >= 0
    seat = np.maximum(source, 0)
    line = grid.xyz if points is None else np.asarray(points, dtype=float)
    p = grid.xyz
    a = line[seat]

    def to_segment(b_index: np.ndarray, live: np.ndarray) -> np.ndarray:
        b = line[b_index]
        ab = b - a
        along = (ab * ab).sum(axis=1)
        t = np.where(along > 0.0, ((p - a) * ab).sum(axis=1) / np.maximum(along, 1e-30), 0.0)
        t = np.clip(t, 0.0, 1.0)
        foot = a + ab * t[:, None]
        chord = np.sqrt(((p - foot) ** 2).sum(axis=1))
        return np.where(live, chord, np.inf)

    #: Звено вниз: приёмник ближайшей клетки русла, если он не она сама.
    down = receiver[seat]
    best = to_segment(down, found & (down != seat))
    #: Звенья вверх: соседи ближайшей клетки, что текут в неё и сами русло.
    for k in range(WAYS):
        n = grid.near[k][seat]
        best = np.minimum(best, to_segment(n, found & (n != seat) & (receiver[n] == seat) & river[n]))
    #: Без звеньев (одинокая клетка русла) — до самой клетки.
    best = np.minimum(best, np.where(found, np.sqrt(((p - a) ** 2).sum(axis=1)), np.inf))
    return source, best * grid.radius_m


def discharge(flow: Flow, grid: Grid, yield_: np.ndarray, land: np.ndarray) -> np.ndarray:
    """Сколько жидкости идёт через клетку, в м² водосбора: сток, взвешенный
    тем, сколько её отдаёт каждая клетка.

    `area_m2` — геометрия: сколько земли выше по склону, и она одна на любой
    планете. Ею живёт эрозия, ею режутся долины и каньоны, и это правильно:
    русло вырезано формой земли, а не сегодняшней погодой. Но **река** — это
    не водосбор, это вода в нём, и раньше её решала одна площадь. Отсюда
    брались реки там, где в них не втекает ничего: на Пироксисе 2.7 % клеток
    были реками при нулевых осадках, на Авроре 2.6 % — и на Терре русла шли
    по пустыням, потому что пустыня тоже собирает площадь.

    `yield_` — отдача клетки, доля: у воды это осадки, у лавы — вулканы и
    рифты, у промёрзшей планеты ноль. Она **нормируется на среднее по суше**,
    и в этом весь смысл: порог реки остаётся площадью водосбора и означает то
    же, что означал, а планета сравнивается сама с собой. Мир ровной влажности
    получает ровно прежние реки; сухой — реки только там, где ему мокрее
    обычного; мир, не отдающий ничего, не получает ни одной.
    """
    return accumulate(flow.receiver, flow.order, yield_share(yield_, land) * grid.area_m2)


def yield_share(yield_: np.ndarray, land: np.ndarray) -> np.ndarray:
    """Отдача клетки, нормированная на среднее по суше: чем `discharge`
    взвешивает площадь, и чем `route` мерит русло для захвата — одна мера
    на оба, иначе захват резал бы гребни под русла, которых рекой не будет.
    """
    land = np.asarray(land)
    if not land.any():
        return np.zeros(land.size)
    mean = float(np.asarray(yield_)[land].mean())
    if mean <= 0.0:
        #: Планете нечем течь: ни рек, ни озёр. Не край случая, а Аврора —
        #: вода там есть, но вся она лёд.
        #:
        #: Ноль тут **выводится, а не выпадает**, и это важно: нормировка на
        #: среднее делает меру относительной, и будь у промёрзшей планеты
        #: хоть одна отдающая клетка, её доля подскочила бы до числа клеток
        #: суши — то есть одна оттаявшая клетка родила бы полноводную реку.
        #: Держит от этого не удача, а арифметика: отдаёт лишь клетка теплее
        #: `terrain.ice_c`, а тёплый край Авроры (−25 °C) ниже него, так что
        #: маска пуста на всей планете при любом зерне. Поднимут её края
        #: выше −8 °C — правило кончится, и кончится оно резко.
        return np.zeros(land.size)
    return np.where(land, np.asarray(yield_, dtype=float) / mean, 0.0)


def downstream(
    flow: Flow, source: np.ndarray, keep: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Провести `source` (объём на клетку) вниз по стоку: в каждой клетке
    оседает доля `keep` того, что через неё прошло, остальное идёт дальше.
    Возвращает осевшее и прошедшее насквозь."""
    recv = flow.receiver.tolist()
    inflow = [0.0] * len(recv)
    src = np.broadcast_to(source, (len(recv),)).tolist()
    kp = np.broadcast_to(keep, (len(recv),)).tolist()
    settled = [0.0] * len(recv)
    passed = [0.0] * len(recv)
    for i in flow.order.tolist():
        total = src[i] + inflow[i]
        stay = total * kp[i]
        settled[i] = stay
        through = total - stay
        passed[i] = through
        j = recv[i]
        if j != i:
            inflow[j] += through
    return np.array(settled), np.array(passed)
