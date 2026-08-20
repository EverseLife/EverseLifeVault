"""Сборка вольта: данные -> документы + артефакты для движка.

    python tools/build.py           собрать всё, показать предупреждения
    python tools/build.py --check   только проверить, ничего не писать; код возврата 1 при проблемах

Что делает:
  1. Читает data/*.yaml — единственные источники чисел, рецептов и законов
  2. Проверяет лестницу рецептов и дерево законов: циклы, тупики, битые ссылки
  3. Рендерит templates/*.tmpl -> готовые документы вольта
  4. Пишет build/constants.json, build/recipes.json и build/laws.json — их читает движок
  5. Собирает 90-production/03-status.md — индекс статусов всех документов
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    sys.exit("Нужен pyyaml:  python -m pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TEMPLATES = ROOT / "templates"
BUILD = ROOT / "build"

# Рабочие станции, которых нет и не должно быть в списке рецептов
VIRTUAL_STATIONS = {"Руками", "Стройка"}
# Разговорное название станции -> рецепт, которым она делается
STATION_ALIASES = {"Печь": "Плавильная печь"}

PREFIX_UNITS = {"×", "±", "до +", "до "}

# Тип рецепта -> как он называется в тексте (D-090)
KIND_LABEL = {
    "station": "рабочая станция",
    #: Мебель обустраивает здание, но станцией не является: на ней не работают.
    #: Кровать — гибернация, стеллаж — хранение
    "furniture": "мебель",
    "tool": "инструмент",
    "gear": "снаряжение",
    "vehicle": "транспорт",
    "material": "материал",
    "consumable": "расходник",
    "money": "монета",
}
# Типы, которые ничему дальше не обязаны: они и есть назначение (D-090)
SELF_SUFFICIENT_KINDS = set(KIND_LABEL) - {"material"}

GENERATED_WARNING = "<!-- СГЕНЕРИРОВАНО tools/build.py — правки в этом файле будут затёрты. Источник: {src} -->\n"


# ---------------------------------------------------------------- константы

def fmt_value(c: dict) -> str:
    if "formula" in c:
        return f"`{c['formula']}`"

    v = c.get("value")
    unit = c.get("unit", "")

    if isinstance(v, bool):
        return "да" if v else "нет"

    if isinstance(v, list):  # ступени качества
        return " · ".join(f"{t['from']}–{t['to']} {t['name']}" for t in v)

    if isinstance(v, dict):
        if "min" in v and "max" in v:
            body = f"{v['min']}–{v['max']}"
        elif unit == "×":  # карта модификаторов
            return " · ".join(f"{k} ×{val}" for k, val in v.items())
        else:  # карта величин: единица своя, и множителем она не является
            return " · ".join(f"{k} — {val} {unit}".rstrip() for k, val in v.items())
    else:
        body = str(v).replace("-", "−")

    if not unit:
        return body
    if unit in PREFIX_UNITS:
        return f"{unit}{body}"
    if unit.startswith("%"):  # «5%», «2% в сутки», «30% дохода»
        return f"{body}{unit}"
    return f"{body} {unit}"


def render_constants_group(group: dict) -> str:
    rows = ["| Константа | Значение | Смысл |", "|---|---|---|"]
    for c in group["constants"]:
        sense = c.get("note", "")
        if c.get("decision"):
            sense = f"{sense} ({c['decision']})" if sense else f"задано {c['decision']}"
        rows.append(f"| `{c['key']}` | {fmt_value(c)} | {sense} |")
    return "\n".join(rows)


def flatten_constants(doc: dict) -> dict:
    flat: dict[str, object] = {}
    for group in doc["groups"]:
        for c in group["constants"]:
            flat[c["key"]] = {"formula": c["formula"]} if "formula" in c else c.get("value")
    return flat


# ------------------------------------------------------------------ рецепты

def all_recipes(doc: dict):
    """Плоский обход: (уровень, секция|None, рецепт)."""
    for level in doc["levels"]:
        for rec in level.get("recipes", []):
            yield level, None, rec
        for section in level.get("sections", []):
            for rec in section["recipes"]:
                yield level, section, rec


def lower_first(s: str) -> str:
    """В перечислении входов с большой буквы идёт только первый — как в исходном тексте."""
    return s[:1].lower() + s[1:]


def fmt_qty(q: float) -> str:
    return f"{q:g}"


def render_recipe_table(recipes: list[dict], amounts: dict | None = None) -> str:
    show_station = any(r.get("station") != "Руками" for r in recipes)
    head = ["| Рецепт | Тип | Входы |", "|---|---|---|"]
    if show_station:
        head = ["| Рецепт | Тип | Входы | Станция |", "|---|---|---|---|"]

    rows = list(head)
    for r in recipes:
        name = r["name"]
        kind = r.get("kind", "material")
        if kind == "station" or r.get("key"):
            name = f"**{name}**"
        type_cell = KIND_LABEL[kind]
        if r.get("mix"):
            type_cell += " *(смесь)*"
        if r.get("roles"):
            type_cell += " *(роли)*"

        hl = set(r.get("highlight", []))
        qty = (amounts or {}).get(r["name"], {})
        parts = []
        for n, i in enumerate(r["inputs"]):
            label = i if n == 0 else lower_first(i)
            if i in hl:
                label = f"**{label}**"
            q = qty.get(i)
            if q:
                label += f" ×{fmt_qty(q)}"
            parts.append(label)
        inputs = ", ".join(parts)
        if r.get("amounts"):
            inputs += " *(количества заданы вручную)*"

        cells = [name, type_cell, inputs] + ([r.get("station", "—")] if show_station else [])
        if r.get("note"):
            cells[-1] += f" *({r['note']})*"
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def render_operations(doc: dict, op_amounts: dict | None = None) -> str:
    """Строка на каждый выход: количества у операции считаются по выходу.

    У плавки четыре металла с разной трудоёмкостью, и руды на них уходит
    по-разному — одной строкой на операцию это не показать.
    """
    rows = ["| Операция | Требует | Даёт | Расходует на единицу |", "|---|---|---|---|"]
    for op in doc["operations"]:
        req = ", ".join(q if n == 0 else lower_first(q) for n, q in enumerate(op["requires"]))
        for n, g in enumerate(op["gives"]):
            qty = (op_amounts or {}).get(g) or {}
            spent = ", ".join(
                (i if k == 0 else lower_first(i)) + f" ×{fmt_qty(q)}"
                for k, (i, q) in enumerate(qty.items())
            ) or "— *(берётся из мира)*"
            # где выход мельче входа, доля входа нечитаема: пишем как в жизни
            out_per_input = (op.get("yield") or {}).get(g)
            if out_per_input and len(qty) == 1:
                src = next(iter(qty))
                spent = f"1 {lower_first(src)} → {fmt_qty(out_per_input)} × {lower_first(g)}"
            rows.append(f"| {op['name'] if n == 0 else ''} | {req if n == 0 else ''} | {g} | {spent} |")
    return "\n".join(rows)


def render_totals(doc: dict) -> str:
    rows = ["| Уровень | Рецептов |", "|---|---|"]
    total = 0
    for level in doc["levels"]:
        n = sum(1 for _ in level.get("recipes", [])) + sum(
            len(s["recipes"]) for s in level.get("sections", [])
        )
        total += n
        rows.append(f"| У{level['id']} {level.get('short', level['title'].lower())} | {n} |")
    rows.append(f"| **Всего** | **{total}** |")
    return "\n".join(rows)


def compute_amounts(doc: dict, constants: dict) -> tuple[dict, dict, dict, list[str]]:
    """Количества входов выводятся из трудоёмкости, а не задаются руками (D-133).

    Правило одно: **час работы съедает `craft.input_labor_ratio` часов чужого
    труда**, разделённых между входами. Отсюда всё остальное:

        трудоёмкость сырья      = 1 / harvest.rates[сырьё]           (часов на единицу)
        трудоёмкость изделия    = craft.time_per_unit/60 + труд входов
        количество входа j      = вес_j × ratio × время_шага / трудоёмкость_j

    Рецепт вправе назвать количества сам полем `amounts` — это исключение,
    и оно должно быть осмысленным: расточительный передел, ритуальный расход,
    неудобное сырьё. Всё прочее считается.

    **Операции считаются тем же правилом**, и разница только в том, откуда
    берётся время шага: у рецепта оно растёт от глубины передела, у операции
    это `1 / harvest.rates[выход]` — темп, заданный по каждому продукту
    отдельно. Добывающие операции (рубка, добыча) не расходуют ничего: они
    берут материю из мира, и их трудоёмкость равна собственному времени.
    """
    flat = flatten_constants(constants)
    rates = flat.get("harvest.rates", {})
    ratio = flat.get("craft.input_labor_ratio", 1.0)
    base_step = flat.get("craft.time_per_unit", 6) / 60
    growth = flat.get("craft.time_growth_per_level", 1.6)
    cap = flat.get("craft.amount_cap", 10)

    recipes = {r["name"]: r for _, _, r in all_recipes(doc)}

    def canon(n: str) -> str:
        return synonyms.get(n, n)

    depth_cache: dict[str, int] = {}

    def depth_of(name: str, seen: frozenset = frozenset()) -> int:
        """Сколько переделов лежит под изделием.

        **Не уровень лестницы.** Уровень — это порядок открытия: хлеб стоит на
        четвёртом не потому, что печётся дольше верёвки, а потому что требует
        мельницы. Время изготовления растёт от собственной сложности вещи, и
        считать его от уровня было ошибкой — первый прогон дал обед дороже
        часа работы, то есть экономику, которая себя не кормит.
        """
        if name in depth_cache:
            return depth_cache[name]
        if name in seen or name not in recipes:
            return 0
        d = 1 + max((depth_of(canon(i), seen | {name}) for i in recipes[name]["inputs"]),
                    default=0)
        depth_cache[name] = d
        return d

    def step_of(name: str) -> float:
        """Собственное время изготовления единицы.

        По умолчанию растёт от глубины передела. Рецепт вправе назвать его сам
        полем `hours` — исключение того же рода, что и `amounts`: бывает работа,
        длинная не от сложности состава (выдержка, обжиг, брожение).
        Заданное время идёт и в количества: час работы съедает
        `craft.input_labor_ratio` часов чужого труда.
        """
        manual = (recipes.get(name) or {}).get("hours")
        if manual:
            return float(manual)
        return base_step * growth ** (depth_of(name) - 1)
    synonyms = {**STATION_ALIASES, **doc["meta"].get("synonyms", {})}
    bulk = {canon(name) for name in doc["meta"].get("bulk", [])}
    op_outputs = {g: op for op in doc["operations"] for g in op["gives"]}
    problems: list[str] = []

    labor: dict[str, float] = {}
    for name, rate in rates.items():
        labor[name] = 1 / rate if rate else 0.0
    # Собственное время операции на единицу выхода. Если темпа нет в реестре —
    # выводить нечего, и это дефект данных, а не повод угадать
    op_step: dict[str, float] = {}
    for g in op_outputs:
        if g in labor:
            op_step[g] = labor[g]
        else:
            problems.append(f"операция «{op_outputs[g]['name']}»: у выхода «{g}» нет темпа "
                            "в `harvest.rates` — ни время, ни количества не вывести")
            op_step[g] = 0.0
            labor[g] = 0.0

    for name, r in recipes.items():
        hours = r.get("hours")
        if hours is not None and (not isinstance(hours, (int, float)) or hours <= 0):
            problems.append(f"«{name}»: `hours` должно быть числом больше нуля, а не {hours!r}")

    amounts: dict[str, dict[str, float]] = {}
    op_amounts: dict[str, dict[str, float]] = {}

    def resolve(name: str, seen: frozenset = frozenset()) -> float:
        if name in labor:
            return labor[name]
        if name in seen:
            return 0.0
        r = recipes.get(name)
        if r is None:
            return 0.0
        inputs = [canon(i) for i in r["inputs"]]
        for i in inputs:
            resolve(i, seen | {name})
        own = amounts_for(name, r.get("amounts"), r.get("weights"), inputs, step_of(name))
        total = step_of(name) + sum(q * labor.get(i, 0.0) for i, q in own.items())
        labor[name] = total
        amounts[name] = own
        return total

    def resolve_op(g: str, seen: frozenset = frozenset()) -> float:
        """Трудоёмкость продукта операции: своё время плюс труд израсходованного.

        До этого продукт операции стоил только собственное время, и плавильщик
        получал слиток так, будто руда ему досталась даром. Отсюда же берётся
        главная строка лестницы: сколько руды уходит в слиток.
        """
        if g in op_amounts:
            return labor[g]
        op = op_outputs[g]
        consumes = [canon(i) for i in op.get("consumes", [])]
        if not consumes or g in seen:
            op_amounts[g] = {}
            return labor[g]
        for i in consumes:
            if i in op_outputs:
                resolve_op(i, seen | {g})
        manual = (op.get("amounts") or {}).get(g)
        # «Одно бревно -> пять досок»: выход мельче входа, и вывод из
        # трудоёмкости тут упирается в пол «меньше единицы не бывает»
        out_per_input = (op.get("yield") or {}).get(g)
        if manual is None and out_per_input:
            manual = {i: round(1 / float(out_per_input), 3) for i in consumes}
        own = amounts_for(g, manual, op.get("weights"), consumes, op_step[g])
        labor[g] = op_step[g] + sum(q * labor.get(i, 0.0) for i, q in own.items())
        op_amounts[g] = own
        return labor[g]

    def amounts_for(name: str, manual, weights, inputs: list[str], step: float) -> dict[str, float]:
        if manual:
            return {canon(k): float(v) for k, v in manual.items()}
        weights = weights or {}
        default_w = 1 / len(inputs) if inputs else 0
        out: dict[str, float] = {}
        for i in inputs:
            w = float(weights.get(i, default_w))
            li = labor.get(i, 0.0)
            if li <= 0:
                problems.append(f"«{name}»: у входа «{i}» нет трудоёмкости — "
                                "добавь его в `harvest.rates` или задай `amounts`")
                out[i] = 1.0
                continue
            # единицы меньше одной не бывает: рецепт не берёт «полбревна».
            # Сверху — потолок, иначе дешёвое сырьё уходит вёдрами
            q = w * ratio * step / li
            q = max(1.0, min(cap, q))
            if canon(i) not in bulk:
                # Штучное целое всегда (D-212): половины слитка не бывает ни в
                # руках, ни в составе. Округление здесь, а не проверкой после:
                # проверка сказала бы, что мир противоречив, и была бы права
                out[i] = float(max(1, round(q)))
            else:
                out[i] = round(q) if q >= 2 else round(q, 1)
        return out

    # Операции считаются первыми: их продукты — входы половины рецептов,
    # и к моменту сборки рецепта труд руды обязан уже сидеть в слитке
    for g in op_outputs:
        resolve_op(g)
    for name in recipes:
        resolve(name)
    return amounts, op_amounts, labor, problems


def with_seed_mass(mass: dict, plants: list[dict], constants: dict) -> dict[str, float]:
    """Добавить к массам семена культур (D-146).

    Семена описаны в `plants.yaml`, а не рецептом, и потому мимо `compute_mass`
    проходят. Вес у всех один — `farm.seed_mass`: семена мелкие, и разница
    между культурами для носимого несущественна. Без этого семенной фонд не
    весил бы ничего, а предел носимого имел бы дыру ровно там, где фермер.
    """
    за_семя = flatten_constants(constants).get("farm.seed_mass")
    if за_семя is None:  # pragma: no cover — величина обязана быть в вольте
        return dict(mass)
    итог = dict(mass)
    for plant in plants:
        итог.setdefault(plant["seed"], float(за_семя))
    return итог


def with_seed_bulk(bulk: list[str], plants: list[dict]) -> list[str]:
    """Добавить к весовому семена культур (D-212).

    Семена описаны в `plants.yaml`, а не рецептом, и в список весового руками
    их не впишешь: культура заводится там, и строка здесь про неё забылась бы.
    Сеются они нормой на квадратный метр — величиной заведомо дробной.
    """
    итог = list(bulk)
    for plant in plants:
        if plant["seed"] not in итог:
            итог.append(plant["seed"])
    return итог


def compute_mass(
    doc: dict, constants: dict, op_amounts: dict, amounts: dict | None = None
) -> tuple[dict[str, float], list[str]]:
    """Масса единицы каждого предмета, кг (D-146).

    **Масса задаётся, а не выводится** — в отличие от количеств (D-133) и
    урожайности (D-136), и на то есть причина, стоившая одной попытки.

    Вывести массу изделия из масс его входов не получается: количества входов
    заданы **трудом**, а не физическим составом. Час работы съедает час чужого
    труда, поэтому в кирку «входит» столько железа, сколько стоит её
    изготовление, — а не столько, сколько в ней есть. Сложение таких входов
    давало кирку в 18 кг, хлеб в 11 кг и золотую монету в 4.9 кг при заданном
    вольтом весе монеты в грамм.

    Поэтому здесь три источника, в порядке убывания точности:

    1. `mass:` у рецепта — там, где вес важен и известен;
    2. `meta.mass` — сырьё и то, что берётся из мира;
    3. `inventory.mass_by_kind` — умолчание по типу предмета. Грубое, но
       осмысленное: инструмент весит как инструмент, пока кто-то не уточнит.

    **Сверху всё это подрезано вошедшим веществом.** Материя при переделе не
    появляется: вещь не может весить больше, чем сумма масс её входов. Снизу
    ограничения нет — часть вещества уходит в отход, и монета в грамм из
    навески металла законна. Подрезка идёт по лестнице: подрезанная масса
    входа уменьшает потолок того, что из него делают.
    """
    meta = doc["meta"]
    synonyms = {**STATION_ALIASES, **meta.get("synonyms", {})}

    def canon(name: str) -> str:
        return synonyms.get(name, name)

    mass: dict[str, float] = {canon(k): float(v) for k, v in meta.get("mass", {}).items()}
    by_kind = flatten_constants(constants).get("inventory.mass_by_kind") or {}
    problems: list[str] = []

    for _, _, r in all_recipes(doc):
        имя = canon(r["name"])
        если_задано = r.get("mass")
        if если_задано is not None:
            mass[имя] = float(если_задано)
            continue
        if имя in mass:
            continue
        по_типу = by_kind.get(r.get("kind", "material"))
        if по_типу is None:
            problems.append(
                f"«{r['name']}»: массы нет — задай `mass:` у рецепта либо "
                f"умолчание для типа «{r.get('kind')}» в `inventory.mass_by_kind`"
            )
            continue
        mass[имя] = float(по_типу)

    #: Выходы операций — то, что берётся из мира или дробится из него. Их масса
    #: обязана быть задана руками: выводить её не из чего.
    for g in op_amounts:
        if canon(g) not in mass:
            problems.append(
                f"«{g}»: продукт операции без массы — задай его в `meta.mass` "
                "(D-146)"
            )

    recipes = {canon(r["name"]): r for _, _, r in all_recipes(doc)}
    capped: dict[str, float] = {}

    def limited(name: str, seen: frozenset = frozenset()) -> float:
        """Масса вещи, подрезанная тем, что в неё вошло."""
        name = canon(name)
        if name in capped:
            return capped[name]
        own = mass.get(name, 0.0)
        r = recipes.get(name)
        if r is None or name in seen:
            return own
        into = sum(
            float(q) * limited(i, seen | {name})
            for i, q in (amounts or {}).get(r["name"], {}).items()
        )
        # Пустой состав не подрезает: вещь без известных входов взвесить не по
        # чему, и нулём её делать нельзя
        capped[name] = min(own, into) if into > 0 else own
        return capped[name]

    for name in list(recipes):
        limited(name)
    mass.update(capped)
    return mass, problems


def check_recipes(doc: dict) -> tuple[list[str], list[str]]:
    """Проверяет то, что документ обещает словами.

    Возвращает (проблемы, известные). Известные — те, что уже записаны
    в known_issues со ссылкой на открытый вопрос: они не роняют сборку.
    """
    problems: list[str] = []

    meta = doc["meta"]
    recipes = {r["name"]: r for _, _, r in all_recipes(doc)}
    raw = set(meta["raw"])
    synonyms: dict[str, str] = {**STATION_ALIASES, **meta.get("synonyms", {})}
    tool_classes: dict[str, list[str]] = meta.get("tool_classes", {})
    op_outputs = {g for op in doc["operations"] for g in op["gives"]}

    def canon(name: str) -> str:
        return synonyms.get(name, name)

    def options(name: str) -> list[str]:
        """Чем можно закрыть требование: сам предмет либо любой из класса."""
        name = canon(name)
        return tool_classes.get(name, [name])

    known = set(recipes) | raw | op_outputs | VIRTUAL_STATIONS | set(tool_classes)

    # 1. неизвестные входы и рабочие станции
    for name, r in recipes.items():
        for i in r["inputs"]:
            if canon(i) not in known:
                problems.append(f"«{name}»: вход «{i}» не рецепт, не сырьё и не продукт операции")
        st = r.get("station")
        if st and canon(st) not in known:
            problems.append(f"«{name}»: рабочая станция «{st}» ничем не делается")
    for op in doc["operations"]:
        for q in op["requires"]:
            if canon(q) not in known:
                problems.append(f"операция «{op['name']}»: требует «{q}», которого никто не делает")
        for i in op.get("consumes", []):
            if canon(i) not in known:
                problems.append(f"операция «{op['name']}»: расходует «{i}», который не рецепт, "
                                "не сырьё и не продукт операции")

    # 1b. весовое (D-212): список обязан называть существующие вещи —
    #     опечатка сделала бы песок штучным молча
    for name in meta.get("bulk", []):
        if canon(name) not in known:
            problems.append(f"весовое «{name}»: такой вещи нет ни в рецептах, ни в сырье")

    # 1c. единицы измерения: тот же присмотр, что за весовым
    for name in (meta.get("units") or {}):
        if canon(name) not in known:
            problems.append(f"единица измерения у «{name}»: такой вещи нет")

    # 2. проходимость: можно ли собрать всё, начав с голого сырья.
    #    Заодно ловит любой цикл — зацикленное просто никогда не откроется.
    available = set(raw)
    while True:
        grew = False
        for op in doc["operations"]:
            need = list(op["requires"]) + list(op.get("consumes", []))
            if all(any(o in available for o in options(q)) for q in need):
                for g in op["gives"]:
                    if g not in available:
                        available.add(g)
                        grew = True
        for name, r in recipes.items():
            if name in available:
                continue
            st = canon(r.get("station", "Руками"))
            if st not in VIRTUAL_STATIONS and not any(o in available for o in options(st)):
                continue
            if all(any(o in available for o in options(i)) for i in r["inputs"]):
                available.add(name)
                grew = True
        if not grew:
            break

    #    Недостижимого обычно много, но первопричина одна: замкнутый круг.
    #    Показываем круг, а не сотню его жертв.
    unreachable = (set(recipes) | op_outputs) - available
    blocked_by: dict[str, set[str]] = {}
    for name in unreachable:
        need: set[str] = set()
        r = recipes.get(name)
        if r is not None:
            for i in list(r["inputs"]) + [r.get("station", "Руками")]:
                if canon(i) in VIRTUAL_STATIONS:
                    continue
                need.update(o for o in options(i) if o in unreachable)
        else:  # продукт операции: заблокирован её инструментом или сырьём
            for op in doc["operations"]:
                if name in op["gives"]:
                    for q in list(op["requires"]) + list(op.get("consumes", [])):
                        need.update(o for o in options(q) if o in unreachable)
        blocked_by[name] = need

    cycles: list[list[str]] = []
    seen: set[frozenset] = set()
    state: dict[str, int] = {}

    def walk(node: str, path: list[str]) -> None:
        state[node] = 1
        path.append(node)
        for nxt in sorted(blocked_by.get(node, ())):
            if state.get(nxt, 0) == 1:
                cycle = path[path.index(nxt):] + [nxt]
                if frozenset(cycle) not in seen:
                    seen.add(frozenset(cycle))
                    cycles.append(cycle)
            elif state.get(nxt, 0) == 0:
                walk(nxt, path)
        path.pop()
        state[node] = 2

    sys.setrecursionlimit(10000)
    for node in sorted(blocked_by):
        if state.get(node, 0) == 0:
            walk(node, [])

    in_cycles = {n for c in cycles for n in c}
    for cycle in cycles:
        problems.append("замкнутый круг: " + " → ".join(cycle))
    victims = sorted(unreachable - in_cycles)
    if victims:
        head = ", ".join(f"«{v}»" for v in victims[:6])
        tail = f" и ещё {len(victims) - 6}" if len(victims) > 6 else ""
        problems.append(f"следствие круга — недостижимо {len(victims)} позиций: {head}{tail}")

    # 3. тупики. Конечность выводится из типа: обязан идти дальше только материал.
    consumed = {canon(i) for r in recipes.values() for i in r["inputs"]}
    for op in doc["operations"]:
        for q in list(op["requires"]) + list(op.get("consumes", [])):
            consumed.update(options(q))
    used_as_station = set()
    for r in recipes.values():
        if r.get("station"):
            used_as_station.update(options(r["station"]))
    for name, r in recipes.items():
        kind = r.get("kind", "material")
        if kind not in KIND_LABEL:
            problems.append(f"«{name}»: неизвестный тип «{kind}»")
            continue
        if kind in SELF_SUFFICIENT_KINDS:
            continue
        if name in consumed or name in used_as_station:
            continue
        problems.append(f"тупик: материал «{name}» никуда не идёт — либо он расходник, либо не хватает рецепта")

    # 5. развести известное и новое
    excused_cycles = {frozenset(i["cycle"]): i["oq"] for i in doc.get("known_issues", []) if "cycle" in i}
    all_cycles_known = bool(cycles) and all(
        any(set(c) <= set(known) | {c[0]} for known in excused_cycles) for c in cycles
    )

    fresh, known_problems = [], []
    for p in problems:
        oq = None
        if p.startswith("замкнутый круг: "):
            members = frozenset(p.removeprefix("замкнутый круг: ").split(" → "))
            oq = next((v for k, v in excused_cycles.items() if members <= k), None)
        elif p.startswith("следствие круга") and all_cycles_known:
            oq = next(iter(excused_cycles.values()), None)
        (known_problems if oq else fresh).append(f"{p}  [{oq}]" if oq else p)
    return fresh, known_problems


def check_compositions(doc: dict, amounts: dict) -> list[str]:
    """Состав на одной рабочей станции называет ровно один рецепт (D-209).

    Изобретение узнаёт рецепт по составу с количествами на единицу выхода:
    игрок кладёт материалы, и движок ищет, что из них здесь получается. Два
    рецепта с одним и тем же составом на одной станции — неразрешимая
    неоднозначность, и она ловится здесь, а не в момент изобретения. Блюда и
    монета в изобретении не участвуют: у них своя дверь (котёл, чеканка).
    """
    synonyms: dict[str, str] = {**STATION_ALIASES, **doc["meta"].get("synonyms", {})}

    def canon(name: str) -> str:
        return synonyms.get(name, name)

    seen: dict[tuple, list[str]] = {}
    for _, _, r in all_recipes(doc):
        if r.get("roles") or r.get("kind") == "money":
            continue
        station = canon(r.get("station") or "Руками")
        composition = tuple(sorted(
            (canon(k), round(float(v), 3)) for k, v in amounts.get(r["name"], {}).items()
        ))
        seen.setdefault((station, composition), []).append(r["name"])

    problems: list[str] = []

    # Штучное считают штуками (D-212). Вывод даёт целые сам, но `amounts`
    # задаются руками — и «0.5 стали» в рецепте означает, что игроку придётся
    # положить полкуска стали, чего движок ему не позволит.
    bulk = {canon(name) for name in doc["meta"].get("bulk", [])}
    for _, _, r in all_recipes(doc):
        for item, quantity in amounts.get(r["name"], {}).items():
            if canon(item) in bulk or float(quantity).is_integer():
                continue
            problems.append(
                f"«{r['name']}»: «{item}» штучное, а требуется {fmt_qty(quantity)} — "
                "задай целое количество либо назови вещь весовой в `meta.bulk` (D-212)"
            )
    for op in doc["operations"]:
        for give, spent in (op.get("amounts") or {}).items():
            # Где выход мельче входа, дробь осмысленна: одно бревно даёт пять
            # досок, и «0.2 бревна на доску» — та же партия, записанная иначе
            if (op.get("yield") or {}).get(give):
                continue
            for item, quantity in spent.items():
                if canon(item) not in bulk and not float(quantity).is_integer():
                    problems.append(
                        f"операция «{op['name']}»: «{item}» штучное, а на {give} "
                        f"идёт {fmt_qty(quantity)} (D-212)"
                    )

    for (station, composition), names in sorted(seen.items()):
        if len(names) < 2:
            continue
        recipe = ", ".join(f"{k} {fmt_qty(v)}" for k, v in composition) or "пусто"
        problems.append(
            f"один состав — {len(names)} рецепта на станции «{station}» ({recipe}): "
            + ", ".join(f"«{n}»" for n in names)
            + " — задай количества руками, чтобы изобретение различало их (D-209)"
        )
    return problems


# ------------------------------------------------------------------ шаблоны

def render_template(text: str, resolve) -> str:
    return re.sub(r"\{\{([^}]+)\}\}", lambda m: resolve(m.group(1).strip()), text)


def build_constants() -> tuple[str, dict]:
    doc = yaml.safe_load((DATA / "constants.yaml").read_text(encoding="utf-8"))
    groups = {g["id"]: g for g in doc["groups"]}

    def resolve(token: str) -> str:
        kind, _, arg = token.partition(":")
        if kind == "constants":
            return render_constants_group(groups[arg])
        raise KeyError(f"неизвестный плейсхолдер {{{{{token}}}}}")

    tmpl = (TEMPLATES / "constants.md.tmpl").read_text(encoding="utf-8")
    return render_template(tmpl, resolve), doc


def build_recipes(constants: dict) -> tuple[str, dict, dict, dict, dict, dict, list[str]]:
    doc = yaml.safe_load((DATA / "recipes.yaml").read_text(encoding="utf-8"))
    levels = {str(l["id"]): l for l in doc["levels"]}
    amounts, op_amounts, labor, qty_problems = compute_amounts(doc, constants)
    #: Масса задаётся данными: вывести её из количеств нельзя, те заданы
    #: трудом, а не составом (D-146).
    mass, mass_problems = compute_mass(doc, constants, op_amounts, amounts)
    qty_problems = qty_problems + mass_problems

    def section_of(level_id: str, sec_id: str) -> dict:
        for s in levels[level_id].get("sections", []):
            if s["id"] == sec_id:
                return s
        raise KeyError(f"нет секции {sec_id} на уровне {level_id}")

    def level_count(level: dict) -> int:
        return len(level.get("recipes", [])) + sum(len(s["recipes"]) for s in level.get("sections", []))

    def resolve(token: str) -> str:
        parts = token.split(":")
        kind = parts[0]
        if kind == "recipes":
            what = parts[1]
            if what == "operations":
                return render_operations(doc, op_amounts)
            if what == "totals":
                return render_totals(doc)
            if what == "cut_candidates":
                return ", ".join(doc["cut_candidates"]).lower()
            if what == "level":
                return render_recipe_table(levels[parts[2]]["recipes"], amounts)
            if what == "section":
                return render_recipe_table(section_of(parts[2], parts[3])["recipes"], amounts)
        if kind == "count":
            if parts[1] == "operations":
                return str(len(doc["operations"]))
            if len(parts) == 3:
                return str(len(section_of(parts[1], parts[2])["recipes"]))
            return str(level_count(levels[parts[1]]))
        raise KeyError(f"неизвестный плейсхолдер {{{{{token}}}}}")

    tmpl = (TEMPLATES / "recipes-mvp.md.tmpl").read_text(encoding="utf-8")
    return render_template(tmpl, resolve), doc, amounts, op_amounts, labor, mass, qty_problems


# ----------------------------------------------------------------- культуры

def compute_plants(doc: dict, constants: dict, recipes_doc: dict) -> tuple[list[dict], list[str]]:
    """Урожайность выводится из трудоёмкости, а не задаётся (D-136).

    Час ухода за делянкой обязан стоить столько же, сколько час любого другого
    труда (И2). Значит культура за цикл должна дать ровно столько, сколько
    даёт `harvest.rates` её продукта за потраченные на неё часы:

        часы за цикл = (обход + уход × площадь)/60 × цикл + вспашка × площадь/60
        урожай с м²  = harvest.rates[продукт] × часы ÷ площадь

    Отсюда сама собой выходит честная связь: долгий цикл окупается большим
    урожаем, а быстрая репа берёт оборотом, а не разовым сбором.
    """
    flat = flatten_constants(constants)
    rates = flat.get("harvest.rates", {})
    area = doc["meta"].get("reference_area", 100)
    care = (3 * flat["farm.plot_overhead"] + flat["farm.care_time_per_m2"] * area) / 60
    plow = flat["farm.plow_time_per_m2"] * area / 60
    budget = flat.get("plant.trait_budget", 3.5)

    # Сколько рецептов потребляют продукт культуры. Отсюда правило:
    # **неприхотливость позволительна ровно настолько, насколько узок сбыт.**
    # Кострец растёт где угодно, потому что сено нужно одному корму; лён
    # капризен, потому что на волокне держится половина лёгкой промышленности
    demand: dict[str, int] = {}
    for _, _, r in all_recipes(recipes_doc):
        for i in r["inputs"]:
            demand[i] = demand.get(i, 0) + 1
    # нормируем по продуктам культур, а не по всему сырью: иначе вода,
    # входящая в десяток рецептов, растягивает шкалу и проверка теряет зубы
    plant_uses = [demand.get(x["gives"], 0) for x in doc["plants"]]
    max_demand = max(plant_uses) or 1

    problems: list[str] = []
    out: list[dict] = []
    for p in doc["plants"]:
        rate = rates.get(p["gives"])
        if not rate:
            problems.append(f"культура «{p['name']}»: продукт «{p['gives']}» "
                            "не описан в `harvest.rates` — урожайность не вывести")
            continue
        hours = care * p["cycle"] + plow
        total = rate * hours
        req, tr = p["requires"], p["traits"]

        # Щедрость культуры: чем выше, тем меньше она требует и больше прощает.
        # Правило D-057 — показатели и требования идут парой, поэтому сумма
        # достоинств ограничена. Культуры, хорошей во всём, быть не должно
        span = req["temp"]["max"] - req["temp"]["min"]
        virtues = {
            "быстрый цикл": max(0.0, (12 - p["cycle"]) / 10),
            "широкий диапазон температур": max(0.0, (span - 15) / 25),
            "нетребовательность к почве": max(0.0, (60 - req["fertility"]) / 50),
            "нетребовательность к воде": (3 - req["water"]) / 2,
            "выносливость": tr["hardiness"] / 5,
            "медленная порча": max(0.0, (1.6 - tr["spoilage_k"]) / 1.4),
            # ценность продукта достоинством НЕ считается: дорогое сырьё
            # означает меньший выход за час, и это уже учтено урожайностью
        }
        score = round(sum(virtues.values()), 2)
        uses = demand.get(p["gives"], 0)
        allowed = round(budget * (2 - uses / max_demand), 2)
        if score > allowed:
            top = ", ".join(k for k, v in sorted(virtues.items(), key=lambda x: -x[1])[:3])
            problems.append(
                f"культура «{p['name']}»: щедрость {score} при потолке {allowed} — "
                f"хороша во всём сразу ({top}) при сбыте в {uses} рецептах. "
                "Правило D-057 нарушено")

        out.append({
            "id": p["id"], "name": p["name"], "gives": p["gives"],
            # чем сеют: семена — предмет, отдельный от продукта (D-057)
            "seed": p["seed"],
            "byproduct": p.get("byproduct"), "cycle_days": p["cycle"],
            "yield_per_m2": round(total / area, 3),
            "yield_per_cycle": round(total, 1),
            "requires": req, "traits": tr,
            "restores_fertility": p.get("restores", 0),
            "generosity": score, "generosity_cap": allowed, "used_in_recipes": uses,
        })
    return out, problems


def render_plants(plants: list[dict]) -> str:
    rows = ["| Культура | Даёт | Цикл | Урожай с м² | Температура | Вода | Плодородие | Свет |",
            "|---|---|---|---|---|---|---|---|"]
    water = {1: "мало", 2: "средне", 3: "много"}
    light = {1: "терпит тень", 2: "среднее", 3: "любит свет"}
    for p in plants:
        r = p["requires"]
        extra = f" + {p['byproduct']}" if p["byproduct"] else ""
        rows.append(
            f"| **{p['name']}** | {p['gives']}{extra} | {p['cycle_days']} сут | "
            f"{p['yield_per_m2']:g} | {r['temp']['min']}…{r['temp']['max']} °C | "
            f"{water[r['water']]} | {r['fertility']} | {light[r['light']]} |")
    return "\n".join(rows)


def render_plant_traits(plants: list[dict]) -> str:
    rows = ["| Культура | Прощает ошибки | Болеет | Боится загущения | Порча урожая | Щедрость при её сбыте |",
            "|---|---|---|---|---|---|"]
    for p in plants:
        t = p["traits"]
        rows.append(
            f"| **{p['name']}** | {t['hardiness']}/5 | {t['disease_risk']}/5 | "
            f"{t['density_risk']}/5 | ×{t['spoilage_k']} | "
            f"{p['generosity']} из {p['generosity_cap']} |")
    return "\n".join(rows)


def build_plants(constants: dict, recipes_doc: dict) -> tuple[str, list[dict], list[str]]:
    doc = yaml.safe_load((DATA / "plants.yaml").read_text(encoding="utf-8"))
    plants, problems = compute_plants(doc, constants, recipes_doc)

    def resolve(token: str) -> str:
        _, _, what = token.partition(":")
        if what == "table":
            return render_plants(plants)
        if what == "traits":
            return render_plant_traits(plants)
        if what == "count":
            return str(len(plants))
        raise KeyError(f"неизвестный плейсхолдер {{{{{token}}}}}")

    tmpl = (TEMPLATES / "plant-catalog.md.tmpl").read_text(encoding="utf-8")
    return render_template(tmpl, resolve), plants, problems


# ------------------------------------------------------------------- законы

def render_charter(doc: dict) -> str:
    rows = ["| Вопрос | Варианты |", "|---|---|"]
    section = None
    for q in doc["charter"]:
        if q["section"] != section:
            section = q["section"]
            rows.append(f"| **{section}** | |")
        opts = []
        for o in q["options"]:
            label = o["label"]
            if o.get("default"):
                label = f"**{label}**"
            if o.get("param"):
                label += f" *({o['param']})*"
            if o.get("requires_option"):
                label += f" *(требует: {o['requires_option']})*"
            opts.append(label)
        question = q["question"]
        if q.get("requires"):
            dep = ", ".join(f"{k} = {' / '.join(v)}" for k, v in q["requires"].items())
            question += f" *(требует: {dep})*"
        rows.append(f"| {question}<br>`{q['id']}` | {' · '.join(opts)} |")
    return "\n".join(rows)


def render_law_list(items: list[dict], with_unit: bool) -> str:
    head = (["| Закон | Значение | По умолчанию | Смысл |", "|---|---|---|---|"] if with_unit
            else ["| Санкция | Что делает |", "|---|---|"])
    rows = list(head)
    for it in items:
        note = it.get("note", "")
        if it.get("decision"):
            note = f"{note} ({it['decision']})" if note else f"задано {it['decision']}"
        if with_unit:
            default = it.get("default", "—")
            rows.append(f"| **{it['name']}**<br>`{it['id']}` | {it.get('unit', '—')} | {default} | {note} |")
        else:
            rows.append(f"| **{it['name']}**<br>`{it['id']}` | {note} |")
    return "\n".join(rows)


def build_laws() -> tuple[str, dict]:
    doc = yaml.safe_load((DATA / "laws.yaml").read_text(encoding="utf-8"))

    def resolve(token: str) -> str:
        _, _, what = token.partition(":")
        if what == "charter":
            return render_charter(doc)
        if what == "code_laws":
            return render_law_list(doc["code_laws"], with_unit=True)
        if what == "sanctions":
            return render_law_list(doc["sanctions"], with_unit=False)
        if what == "totals":
            options = sum(len(q["options"]) for q in doc["charter"])
            return "\n".join([
                "| Слой | Сколько |",
                "|---|---|",
                f"| Вопросов устава | {len(doc['charter'])} |",
                f"| Вариантов ответа | {options} |",
                f"| Код-законов территории | {len(doc['code_laws'])} |",
                f"| Санкционных примитивов | {len(doc['sanctions'])} |",
            ])
        raise KeyError(f"неизвестный плейсхолдер {{{{{token}}}}}")

    tmpl = (TEMPLATES / "law-catalog.md.tmpl").read_text(encoding="utf-8")
    return render_template(tmpl, resolve), doc


def check_laws(doc: dict) -> list[str]:
    """Дерево устава должно быть связным: ссылки ведут в существующие вопросы."""
    problems: list[str] = []
    ids = {q["id"] for q in doc["charter"]}
    for q in doc["charter"]:
        for dep, values in (q.get("requires") or {}).items():
            if dep not in ids:
                problems.append(f"устав «{q['id']}»: требует вопрос «{dep}», которого нет")
                continue
            known = {o["id"] for o in next(x for x in doc["charter"] if x["id"] == dep)["options"]}
            for v in values:
                if v not in known:
                    problems.append(f"устав «{q['id']}»: у «{dep}» нет варианта «{v}»")
        for o in q["options"]:
            if o.get("requires_option") and o["requires_option"] not in ids:
                problems.append(f"устав «{q['id']}»: вариант «{o['id']}» ссылается на несуществующий «{o['requires_option']}»")
    return problems


# --------------------------------------------- ссылки на константы в текстах

CONST_REF = re.compile(r"`([a-z_]+\.[a-z_0-9]+)`")
# `recipes.json` и `plants.yaml` — имена файлов, а не константы
FILE_SUFFIXES = ("json", "yaml", "yml", "md", "py", "tmpl")


def check_constant_refs(constants_doc: dict) -> list[str]:
    """Документ не вправе обещать число, которого нет в реестре (D-065).

    Ловит обратную ошибку тоже: константу удалили решением, а текст на неё ссылается.
    """
    known = set(flatten_constants(constants_doc))
    problems: list[str] = []
    for path in sorted(ROOT.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        # Журнал решений — архив: замороженные и пересмотренные записи законно
        # ссылаются на константы, которых в реестре уже нет (например D-108).
        # Журнал решений — архив: замороженные записи законно ссылаются на
        # константы, которых в реестре уже нет. Отчёт симуляции — наоборот:
        # он существует ради того, чтобы называть недостающие величины.
        if rel.startswith((".obsidian/", "build/", "templates/", "editor/")) or rel in (
                "90-production/02-decision-log.md", "90-production/04-simulation.md"):
            continue
        for key in sorted(set(CONST_REF.findall(path.read_text(encoding="utf-8")))):
            if key.rsplit(".", 1)[-1] in FILE_SUFFIXES:
                continue
            if key not in known:
                problems.append(f"{rel}: ссылается на константу «{key}», которой нет в реестре")
    return problems


# ------------------------------------------------------------ индекс статусов

STATUS_ORDER = ["реализовано", "в реализации", "согласовано", "идея", "живой", "генерируется"]
STATUS_RULE = {
    "реализовано": "обязан совпадать с кодом",
    "в реализации": "обязан совпадать с кодом",
    "согласовано": "решение принято, кода ещё нет",
    "идея": "ни к чему не обязывает",
    "живой": "всегда актуален по построению",
    "генерируется": "не править руками",
}


def build_status_index() -> str:
    found: dict[str, list[tuple[str, str]]] = {s: [] for s in STATUS_ORDER}
    unknown: list[tuple[str, str]] = []

    for path in sorted(ROOT.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith((".obsidian/", "build/", "templates/", "editor/")) or rel in ("README.md", "CLAUDE.md", "MEMORY.md"):
            continue
        if rel == "90-production/03-status.md":
            continue
        head = path.read_text(encoding="utf-8").split("\n", 6)[:6]
        line = next((l for l in head if l.startswith("> **Статус:**")), None)
        title = next((l.lstrip("# ").strip() for l in head if l.startswith("# ")), rel)
        if line is None:
            unknown.append((rel, title))
            continue
        body = line.split("**Статус:**", 1)[1].strip()
        status = next((s for s in STATUS_ORDER if body.startswith(s)), None)
        if status is None:
            unknown.append((rel, title))
        else:
            found[status].append((rel, title))

    out = [
        "# Статусы документов",
        "",
        "> **Статус:** генерируется · **Источник:** шапки самих документов · сборка `python tools/build.py`",
        "",
        "Статус — это контракт синхронизации, а не украшение. Правило целиком — в [CLAUDE.md](../CLAUDE.md).",
        "",
    ]
    for s in STATUS_ORDER:
        items = found[s]
        out.append(f"## {s} — {STATUS_RULE[s]} ({len(items)})")
        out.append("")
        if not items:
            out.append("_пусто_")
        for rel, title in items:
            out.append(f"- [{title}]({relative_link(rel)})")
        out.append("")
    if unknown:
        out.append(f"## без распознанного статуса ({len(unknown)})")
        out.append("")
        for rel, title in unknown:
            out.append(f"- [{title}]({relative_link(rel)})")
        out.append("")
    return "\n".join(out)


def relative_link(rel: str) -> str:
    return "../" + rel if not rel.startswith("90-production/") else rel.split("/", 1)[1]


# ---------------------------------------------------------------------- main

def main() -> int:
    check_only = "--check" in sys.argv

    constants_md, constants_doc = build_constants()
    recipes_md, recipes_doc, amounts, op_amounts, labor, mass, qty_problems = build_recipes(constants_doc)
    harvest_rates = flatten_constants(constants_doc).get("harvest.rates", {})
    plants_md, plants, plant_problems = build_plants(constants_doc, recipes_doc)
    laws_md, laws_doc = build_laws()
    problems, known_problems = check_recipes(recipes_doc)
    problems += check_compositions(recipes_doc, amounts)
    problems += qty_problems
    problems += plant_problems
    problems += check_laws(laws_doc)
    problems += check_constant_refs(constants_doc)

    if known_problems:
        print(f"Известные расхождения, ждут решения по открытому вопросу ({len(known_problems)}):")
        for p in known_problems:
            print(f"  · {p}")
        print()

    if problems:
        print(f"НОВЫЕ проблемы ({len(problems)}):", file=sys.stderr)
        for p in problems:
            print(f"  · {p}", file=sys.stderr)
        print(file=sys.stderr)

    if check_only:
        print("проверка чистая" if not problems else "проверка нашла новые проблемы")
        return 1 if problems else 0

    BUILD.mkdir(exist_ok=True)
    written = []

    def write(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path.relative_to(ROOT).as_posix())

    write(ROOT / "30-economy" / "07-constants.md",
          GENERATED_WARNING.format(src="data/constants.yaml") + constants_md)
    write(ROOT / "20-systems" / "13-recipes-mvp.md",
          GENERATED_WARNING.format(src="data/recipes.yaml") + recipes_md)
    write(BUILD / "constants.json",
          json.dumps(flatten_constants(constants_doc), ensure_ascii=False, indent=2) + "\n")
    write(BUILD / "recipes.json", json.dumps(
        {
            # Движок читает только build/. Без этих двух карт он не ответит,
            # годится ли каменная кирка для операции «Добыча» и что «Печь» —
            # это «Плавильная печь»: в data/ они есть, а тут их не было
            "synonyms": {**STATION_ALIASES, **recipes_doc["meta"].get("synonyms", {})},
            "tool_classes": recipes_doc["meta"].get("tool_classes", {}),
            "operations": [
                {
                    "name": op["name"],
                    "requires": op["requires"],
                    "gives": op["gives"],
                    "consumes": op.get("consumes", []),
                    # где операция возможна: свойство узла (D-177). Пусто —
                    # операция не привязана к месту
                    "place": op.get("place"),
                    # количества и время — по каждому выходу отдельно
                    "amounts": {g: op_amounts.get(g, {}) for g in op["gives"]},
                    "hours_per_unit": {
                        g: round(1 / rate, 4)
                        for g in op["gives"]
                        if (rate := harvest_rates.get(g))
                    },
                    # сколько единиц выхода даёт одна единица входа, там где
                    # выход мельче входа. Обратная величина amounts, но движку
                    # партия задаётся именно так: распустить бревно, а не долю
                    "yield": op.get("yield", {}),
                    "manual_amounts": {
                        g: bool((op.get("amounts") or {}).get(g) or (op.get("yield") or {}).get(g))
                        for g in op["gives"]
                    },
                }
                for op in recipes_doc["operations"]
            ],
            "raw": recipes_doc["meta"]["raw"],
            # весовое: количество бывает дробным (D-212). Всё остальное
            # штучное — целое всегда, и половины слитка не бывает
            "bulk": sorted(with_seed_bulk(recipes_doc["meta"].get("bulk", []), plants)),
            # Единица измерения рядом с числом: «5 шт», «3 м». Только для показа
            # игроку — целость количества задаётся `bulk`, а не словом
            "units": dict(sorted((recipes_doc["meta"].get("units") or {}).items())),
            # что годится в котёл: движку нельзя гадать съедобность по имени
            "edible": recipes_doc["meta"].get("edible", []),
            # слоты снаряжения: в каждый надевается одна вещь (D-146)
            "gear_slots": recipes_doc["meta"].get("gear_slots", []),
            # масса единицы, кг. Задана данными: см. compute_mass. Семена
            # культур добавляются отдельно: они описаны в plants.yaml, а не
            # рецептом, и без этого проходили бы мимо предела носимого (D-146)
            "mass": {
                k: round(v, 3)
                for k, v in sorted(with_seed_mass(mass, plants, constants_doc).items())
            },
            "labor_hours": {k: round(v, 3) for k, v in sorted(labor.items())},
            "recipes": [
                {
                    "name": r["name"],
                    "level": lvl["id"],
                    "section": sec["id"] if sec else None,
                    "kind": r.get("kind", "material"),
                    "key": bool(r.get("key")),
                    "mix": bool(r.get("mix")),
                    "roles": bool(r.get("roles")),
                    # Съедобность и «горячее» — данные: движку нельзя гадать,
                    # что человек ест, по названию предмета (D-065 по духу).
                    "food": bool(r.get("food")),
                    "hot": bool(r.get("hot")),
                    # в какой слот надевается: у не-снаряжения пусто (D-146)
                    "slot": r.get("slot"),
                    # сколько килограммов вмещает как хранилище (D-181).
                    # Пусто — вещь не хранилище: движок не гадает по названию
                    "store": r.get("store"),
                    "inputs": r["inputs"],
                    "amounts": amounts.get(r["name"], {}),
                    "manual_amounts": bool(r.get("amounts")),
                    # Трудоёмкости здесь нет: она лежит одной картой ниже, и
                    # там же трудоёмкость сырья и продуктов операций. Второй
                    # экземпляр того же числа читать было некому
                    "station": r.get("station"),
                }
                for lvl, sec, r in all_recipes(recipes_doc)
            ],
        },
        ensure_ascii=False, indent=2) + "\n")
    write(ROOT / "20-systems" / "17-plant-catalog.md",
          GENERATED_WARNING.format(src="data/plants.yaml") + plants_md)
    write(BUILD / "plants.json",
          json.dumps({"plants": plants}, ensure_ascii=False, indent=2) + chr(10))
    write(ROOT / "40-society" / "07-law-catalog.md",
          GENERATED_WARNING.format(src="data/laws.yaml") + laws_md)
    write(BUILD / "laws.json", json.dumps(
        {k: laws_doc[k] for k in ("charter", "code_laws", "sanctions")},
        ensure_ascii=False, indent=2) + "\n")
    write(ROOT / "90-production" / "03-status.md", build_status_index())

    print("собрано:")
    for w in written:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
