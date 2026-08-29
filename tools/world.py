# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Раскладка стартового мира: проверка и слепок для движка (D-243).

Отдельным модулем, а не разделом `build.py`: там уже без малого две тысячи
строк, и мир к остальному не относится. Рецепты, константы, законы и растения —
это **лестница**: числа, которые выводятся друг из друга. Мир — это **карта**:
узлы, рёбра и то, что в узлах стоит. Общего у них ровно один вход — реестр
вещей вольта, по которому проверяется, что в узел не поставили того, чего в
мире нет.

Что здесь делается:

* `check_world` — отказы **до движка**. Вещь не из вольта, станок без рецепта,
  класс без сборного члена, дорога за стены не от ворот (D-206), узел, до
  которого не ведёт ни одна дорога, две точки в одной клетке карты. Найденное
  здесь чинится правкой файла; найденное движком — упавшим деплоем;
* `build_world` — тот же файл с проставленными умолчаниями, в
  `build/world.json`. Его читает `src/seed_world.py` рядом с константами.

Правил мира тут нет и быть не может: как узел садится на карту, во сколько
секунд обходится даль, из чего собирается станок — это движок и вольт, каждый
своим документом.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

#: Слои, на которых сид раскладывает узлы (D-045). Космос не отсюда: планеты
#: и орбиты — правила движка, а не раскладка (10-world/06).
WORLD_LAYERS = ("planet", "city", "location")
WORLD_SURFACES = ("trail", "road", "paved")
#: Ключ узла космического слоя — это и есть планета (build/world.json).
WORLD_PLANETS = ("terra", "aquatica", "pyroxis", "aurora")
#: Свойства узла, на которые опираются проверки: дверь города (D-206) и
#: удалённость за стенами (D-180). Слова — данные мира, движок знает те же.
WORLD_EXIT = "выход"
WORLD_REACH = "даль"
#: Типы рецептов, которые ставятся в узел как «станок» (D-106).
WORLD_STANDING_KINDS = {"station", "furniture"}
#: Узлы, которые движок зовёт по имени: `src/seed.py` печатает в ядре первое
#: тело и ставит стакан на рынке. Переименовать их во вкладке «Мир» проверка
#: раньше пропускала — раскладка оставалась связной, — и падал деплой, `KeyError`
#: на середине создания мира. Список короткий намеренно: он не «что должно быть
#: в столице», а «на что в движке есть ссылка ключом».
WORLD_REQUIRED = ("terra.capital.core", "terra.capital.market")


#: Свойства места, какие движок читает, и что каждое значит (D-243).
#:
#: **Список закрытый, и это главное в нём.** Свойство узла — обычный ключ в
#: JSON, и опечатка в нём не ломает ни YAML, ни сборку: она просто значит, что
#: движок этого свойства не найдёт. «плодородее» вместо «плодородия» — поле,
#: на котором ничего не растёт, и узнаётся это игроком, а не проверкой. Отсюда
#: и таблица: новое свойство движка дописывается сюда одной строкой, как новый
#: тип здания в D-218, и с этой же строки редактор берёт подсказку.
#:
#: `values` — что свойство принимает: `flag` (да/нет), `number`, `percent`
#: (0..100) либо перечень слов. `where` — где свойство имеет смысл: пусто —
#: везде.
WORLD_PROPERTIES = {
    "лес": {
        "values": "flag",
        "hint": "на узле растёт лес: здесь рубят древесину, и с неё начинается "
                "вся лестница (D-196)",
    },
    "камни": {
        "values": "flag",
        "hint": "каменистая земля: камень собирается руками, без инструмента (D-196)",
    },
    "луг": {
        "values": "flag",
        "hint": "луг: здесь растёт дикий лён, и волокно начинается с него (D-196)",
    },
    "вода": {
        "values": ["река", "нет"],
        "hint": "река на узле: без неё не полить поле и не поставить водяное колесо",
    },
    "плодородие": {
        "values": "percent",
        "hint": "плодородие почвы, 0..100: во столько раз щедрее урожай на этом поле",
    },
    "участок": {
        "values": "flag",
        "hint": "свободный участок: город раздаёт такие жителям, и только на своей "
                "земле мастер ставит станок (D-089, D-150)",
    },
    "выход": {
        "values": "flag",
        "hint": "ворота города: единственный узел застройки, к которому можно "
                "привязать дорогу за стены (D-206). В городе он ровно один",
        "where": "city",
    },
    "даль": {
        "values": "number",
        "hint": "сколько колец за стенами: каждое следующее дороже предыдущего "
                "в travel.frontier_growth раз (D-180). Это и есть вся география",
        "where": "planet",
    },
    "предтечи": {
        "values": "flag",
        "hint": "наследие Предтеч: по этой метке движок узнаёт их машины и их "
                "города (D-028, D-232)",
    },
    "глубина": {
        "values": "number",
        "hint": "насколько вглубь от причала лежит помещение Предтеч: разведка "
                "идёт отсюда дальше (D-061, D-232)",
    },
    "мерзлота": {
        "values": "flag",
        "hint": "вечный холод: без обогрева тело здесь не живёт (D-231). "
                "Свойство планеты, а не узла",
    },
    "пекло": {
        "values": "flag",
        "hint": "жар: без защиты тело здесь не живёт (D-231). Свойство планеты",
    },
    "без воздуха": {
        "values": "flag",
        "hint": "дышать нечем: нужен запас кислорода (D-234). Свойство планеты",
    },
    "посадка везде": {
        "values": "flag",
        "hint": "корабль садится на любой узел поверхности, а не только на верфь "
                "(D-233). Свойство планеты, на которой не строят",
    },
    "наковальня": {
        "values": "flag",
        "hint": "единственное место планеты, которое извержение обходит стороной "
                "(D-197). На Пироксисе такое одно",
    },
    "город": {
        "values": "text",
        "hint": "чем город Предтеч был при них — одним словом: столица, цех, улей. "
                "Решает, что найдут разведчики в его комнатах (D-232)",
    },
}


def load_world_doc() -> dict:
    return yaml.safe_load((DATA / "world.yaml").read_text(encoding="utf-8"))


def planet_of(key: str, nodes: dict) -> str:
    """Планета, на которой в итоге стоит узел: подъём по группам до внешней.

    Внешний узел — сама планета: её кладёт движок (орбиты — правило, не
    раскладка), и в файле она объявлена одной строкой в `external`.
    """
    while key in nodes:
        key = nodes[key].get("parent")
    return key or ""


def _world_names(recipes_doc: dict, all_recipes):
    """Чем проверять раскладку: рецепты с типами, сырьё, продукты, классы."""
    meta = recipes_doc["meta"]
    recipes = {r["name"]: r.get("kind", "material") for _, _, r in all_recipes(recipes_doc)}
    raw = set(meta["raw"])
    op_outputs = {g for op in recipes_doc["operations"] for g in op["gives"]}
    classes: dict[str, list[str]] = meta.get("classes_map", {})
    relics = {m["name"] for m in meta.get("materials", []) if m.get("relic")}
    return recipes, raw, op_outputs, classes, relics


def _check_properties(key: str, properties: dict, layer: str) -> list[str]:
    """Свойства узла — по каталогу, и с проверенным значением.

    Опечатка в имени свойства проходит и YAML, и сборку, и отказывает только в
    движке — молча, тем, что искомого свойства там просто нет. Значение того же
    рода: «плодородие: очень» разберётся в строку, а `farm` ждёт число.
    """
    problems: list[str] = []
    for name, value in properties.items():
        known = WORLD_PROPERTIES.get(name)
        if known is None:
            near = [one for one in WORLD_PROPERTIES if one.startswith(str(name)[:3])]
            hint = f" — может быть, «{near[0]}»?" if near else ""
            problems.append(f"мир: у «{key}» свойство «{name}» движок не читает{hint}")
            continue
        wants = known["values"]
        if wants == "flag" and not isinstance(value, bool):
            problems.append(f"мир: у «{key}» свойство «{name}» — это да/нет, а не «{value}»")
        elif wants in ("number", "percent") and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            problems.append(f"мир: у «{key}» свойство «{name}» — это число, а не «{value}»")
        elif wants == "percent" and isinstance(value, (int, float)) and not 0 <= value <= 100:
            problems.append(f"мир: у «{key}» свойство «{name}» вне 0..100")
        elif isinstance(wants, list) and value not in wants:
            problems.append(
                f"мир: у «{key}» свойство «{name}» — одно из {', '.join(wants)}, а не «{value}»"
            )
        where = known.get("where")
        if where and where != layer:
            problems.append(
                f"мир: свойство «{name}» имеет смысл только на слое «{where}», "
                f"а «{key}» на «{layer}»"
            )
    return problems


def check_world(doc: dict, recipes_doc: dict, all_recipes) -> list[str]:
    """Раскладка обязана сходиться до движка: тот падает на первом же узле.

    Проверяется то же, обо что сид ломался руками: вещь, которой нет в вольте
    (D-215), станок без рецепта (D-216), дорога за стены не от ворот (D-206),
    остров, до которого не дойти. Найденное здесь — правка файла; найденное
    движком — упавший деплой.
    """
    problems: list[str] = []
    recipes, raw, op_outputs, classes, relics = _world_names(recipes_doc, all_recipes)
    known = set(recipes) | raw | op_outputs

    external = doc.get("external") or []
    for key in external:
        if key not in WORLD_PLANETS:
            problems.append(f"мир: внешний узел «{key}» — не планета")

    nodes: dict[str, dict] = {}
    for node in doc.get("nodes") or []:
        key = node.get("key")
        if not key or not isinstance(key, str):
            problems.append("мир: узел без ключа")
            continue
        if key in nodes or key in external:
            problems.append(f"мир: ключ «{key}» встречается дважды")
            continue
        if not node.get("name"):
            problems.append(f"мир: узел «{key}» без имени")
        parent = node.get("parent")
        #: Родитель раньше ребёнка: движок кладёт узлы в порядке файла.
        if parent not in nodes and parent not in external:
            problems.append(f"мир: у «{key}» родитель «{parent}» не объявлен выше")
        anchor = node.get("anchor")
        if anchor is not None and anchor not in nodes:
            problems.append(f"мир: у «{key}» якорь «{anchor}» не объявлен выше")
        layer = node.get("layer", "city")
        if layer not in WORLD_LAYERS:
            problems.append(f"мир: у «{key}» слой «{layer}» — не из {WORLD_LAYERS}")
        area = node.get("area_m2")
        if not isinstance(area, (int, float)) or area <= 0:
            problems.append(f"мир: у «{key}» площадь не больше нуля")
        if node.get("city") and layer != "planet":
            problems.append(f"мир: город «{key}» — не узел слоя planet")
        properties = node.get("properties") or {}
        if not isinstance(properties, dict):
            problems.append(f"мир: у «{key}» свойства — не словарь")
            properties = {}
        problems += _check_properties(key, properties, layer)

        for machine in node.get("machines") or []:
            name, cls = machine.get("name"), machine.get("class")
            if bool(name) == bool(cls):
                problems.append(f"мир: станок в «{key}» задаётся либо именем, либо классом")
                continue
            quality = machine.get("quality")
            if not isinstance(quality, (int, float)) or not 0 <= quality <= 100:
                problems.append(f"мир: у станка «{name or cls}» в «{key}» качество не 0..100")
            if name is not None:
                if recipes.get(name) not in WORLD_STANDING_KINDS:
                    problems.append(
                        f"мир: «{name}» в «{key}» — не станция и не мебель по рецепту"
                    )
            else:
                #: **Тем же выбором, что и движок** (`seed_world.one_of` →
                #: `catalog.made_of_class`): реликвии из класса выкинуты, из
                #: остальных берётся первый. Проверять «хоть один член —
                #: станция» значило бы принимать класс, из которого движок
                #: возьмёт не станцию, и падать уже на создании мира.
                made = [member for member in classes.get(cls, []) if member not in relics]
                if not made:
                    problems.append(
                        f"мир: класс «{cls}» в «{key}» пуст — некого собрать по рецепту"
                    )
                elif recipes.get(made[0]) not in WORLD_STANDING_KINDS:
                    problems.append(
                        f"мир: из класса «{cls}» в «{key}» движок возьмёт «{made[0]}», "
                        "а это не станция и не мебель"
                    )
        for cls in node.get("relics") or []:
            if not any(member in relics for member in classes.get(cls, [])):
                problems.append(f"мир: у класса «{cls}» в «{key}» нет реликвии в реестре")
        for vein in node.get("veins") or []:
            resource = vein.get("resource")
            if resource not in raw:
                problems.append(f"мир: жила «{resource}» в «{key}» — не сырьё реестра")
            richness = vein.get("richness")
            if not isinstance(richness, (int, float)) or not 0 <= richness <= 100:
                problems.append(f"мир: у жилы «{resource}» в «{key}» богатство не 0..100")
            remaining = vein.get("remaining")
            if not isinstance(remaining, (int, float)) or remaining <= 0:
                problems.append(f"мир: у жилы «{resource}» в «{key}» пустой запас")
        problems += _check_world_items(node.get("items") or [], f"в «{key}»", known)
        nodes[key] = {**node, "layer": layer, "properties": properties}

    for owner, grants in (doc.get("pockets") or {}).items():
        problems += _check_world_items(grants or [], f"в кармане «{owner}»", known)

    for key in WORLD_REQUIRED:
        if key not in nodes:
            problems.append(
                f"мир: узел «{key}» назван в движке по ключу — без него сид падает на создании мира"
            )

    problems += _check_world_edges(doc, nodes)
    return problems


def _check_world_items(items: list, where: str, known: set) -> list[str]:
    problems = []
    for item in items:
        name = item.get("name")
        if name not in known:
            problems.append(f"мир: вещь «{name}» {where} не известна вольту")
        amount = item.get("amount", 1)
        if not isinstance(amount, (int, float)) or amount <= 0:
            problems.append(f"мир: у «{name}» {where} количество не больше нуля")
        quality = item.get("quality")
        if not isinstance(quality, (int, float)) or not 0 <= quality <= 100:
            problems.append(f"мир: у «{name}» {where} качество не 0..100")
        if not item.get("origin"):
            #: Материя не приходит в мир безымянно (столп П1).
            problems.append(f"мир: у «{name}» {where} нет основания (origin)")
    return problems


def _check_world_edges(doc: dict, nodes: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    seen_pairs: set[frozenset] = set()
    walkable: dict[str, set[str]] = {}
    for edge in doc.get("edges") or []:
        a, b = edge.get("a"), edge.get("b")
        if a not in nodes or b not in nodes:
            problems.append(f"мир: ребро {a} — {b} упирается в неизвестный узел")
            continue
        if a == b:
            problems.append(f"мир: ребро {a} — само в себя")
            continue
        pair = frozenset((a, b))
        if pair in seen_pairs:
            problems.append(f"мир: ребро {a} — {b} проложено дважды")
        seen_pairs.add(pair)
        surface = edge.get("surface", "road")
        if surface not in WORLD_SURFACES:
            problems.append(f"мир: у ребра {a} — {b} покрытие «{surface}» не из {WORLD_SURFACES}")
        seconds = edge.get("seconds")
        if seconds == "reach":
            reaches = [(nodes[end].get("properties") or {}).get(WORLD_REACH, 0) for end in (a, b)]
            if not any(isinstance(r, (int, float)) and r > 0 for r in reaches):
                problems.append(f"мир: у ребра {a} — {b} длина «по дали», а дали нет ни у конца")
        elif seconds is not None and (not isinstance(seconds, (int, float)) or seconds <= 0):
            problems.append(f"мир: у ребра {a} — {b} секунды не больше нуля")
        walkable.setdefault(a, set()).add(b)
        walkable.setdefault(b, set()).add(a)
        #: Дорога за стены начинается у двери города (D-206): ребро из
        #: городской застройки наружу — только от узла с «выход».
        for end, other in ((a, b), (b, a)):
            end_node, other_node = nodes[end], nodes[other]
            if end_node["layer"] != "city" or other_node.get("parent") == end_node.get("parent"):
                continue
            if not (end_node.get("properties") or {}).get(WORLD_EXIT):
                problems.append(
                    f"мир: дорога {end} — {other} выходит из застройки не через ворота (D-206)"
                )

    #: Тупик ловится здесь, а не игроком: до листа должна вести хоть одна
    #: дорога. Хоть одна, а не «весь мир одной компонентой» — **связность
    #: целого графа здесь неверна как правило**: на другую планету летят, а не
    #: идут (D-201), и три города Предтеч на Авроре дорогами между собой не
    #: соединены намеренно (D-232) — к каждому подходят кораблём, а остальное
    #: открывает разведка. Требовать одной компоненты значило бы требовать
    #: невозможного и приучать пропускать эту строку глазами.
    #:
    #: Узел с детьми освобождён: на нём не стоят, он делегат своей группы на
    #: верхнем слое (D-045), и дорога ведёт к его листьям, а не к нему.
    parents = {node.get("parent") for node in nodes.values()}
    for key in nodes:
        if key in parents or walkable.get(key):
            continue
        problems.append(f"мир: до «{key}» не ведёт ни одна дорога — туда не попасть")

    #: Прибитые места (D-237): узел не двигается, поэтому два узла в одной
    #: точке останутся друг на друге навсегда. Сравниваются внутри группы —
    #: у двух планет общей земли нет, и одинаковые координаты там ничего не
    #: значат.
    places: dict[tuple, str] = {}
    for key, node in nodes.items():
        place = node.get("place")
        if place is None:
            continue
        if not isinstance(place, dict) or not all(
            isinstance(place.get(axis), (int, float)) for axis in ("x", "y")
        ):
            problems.append(f"мир: у «{key}» место на карте — не пара чисел x, y")
            continue
        x, y = float(place["x"]), float(place["y"])
        spot = (node.get("parent"), x, y)
        if spot in places:
            problems.append(
                f"мир: «{key}» стоит на карте там же, где «{places[spot]}» — точка ({x:g}, {y:g})"
            )
        places[spot] = key
    return problems


def build_world(doc: dict) -> dict:
    """Слепок раскладки для движка: те же данные с проставленными умолчаниями."""

    by_key = {node["key"]: node for node in doc.get("nodes") or []}
    return {
        "nodes": [
            {
                "key": node["key"],
                "name": node["name"],
                "layer": node.get("layer", "city"),
                "planet": planet_of(node["key"], by_key),
                "parent": node.get("parent"),
                "anchor": node.get("anchor"),
                "area_m2": node["area_m2"],
                "place": node.get("place"),
                "city": bool(node.get("city")),
                "properties": node.get("properties") or {},
                "machines": [
                    {
                        "name": machine.get("name"),
                        "class": machine.get("class"),
                        "quality": machine["quality"],
                    }
                    for machine in node.get("machines") or []
                ],
                "relics": node.get("relics") or [],
                "veins": node.get("veins") or [],
                "items": _world_items(node.get("items") or []),
            }
            for node in doc.get("nodes") or []
        ],
        "edges": [
            {
                "a": edge["a"],
                "b": edge["b"],
                "seconds": edge.get("seconds"),
                "surface": edge.get("surface", "road"),
            }
            for edge in doc.get("edges") or []
        ],
        "pockets": {
            owner: _world_items(grants or [])
            for owner, grants in (doc.get("pockets") or {}).items()
        },
    }


def _world_items(items: list) -> list[dict]:
    return [
        {
            "name": item["name"],
            "amount": item.get("amount", 1),
            "quality": item["quality"],
            "ensure": bool(item.get("ensure")),
            "origin": item["origin"],
        }
        for item in items
    ]
