# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Сборка вольта: данные -> документы + артефакты для движка.

    python tools/build.py           собрать всё, показать предупреждения
    python tools/build.py --check   только проверить, ничего не писать; код возврата 1 при проблемах
    python tools/build.py --check --strict   ещё и предупреждения считать отказом
    python tools/build.py --masses  вес каждой вещи из входов и кто его переопределил (D-228)

Что делает:
  1. Читает data/*.yaml — единственные источники чисел, рецептов и законов
  2. Проверяет лестницу рецептов и дерево законов: циклы, тупики, битые ссылки
  3. Рендерит templates/*.tmpl -> готовые документы вольта
  4. Пишет build/constants.json, build/recipes.json и build/laws.json — их читает движок
  5. Собирает 90-production/03-status.md — индекс статусов всех документов
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    sys.exit("Нужен pyyaml:  python -m pip install pyyaml")

# Раскладка стартового мира (D-243): своя проверка и свой слепок. Отдельным
# модулем — это карта, а не лестница, и общего у них один реестр вещей.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import world as worldfile  # noqa: E402 -- путь надо задать раньше

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TEMPLATES = ROOT / "templates"
BUILD = ROOT / "build"

# Пустота на месте станции: «станок не нужен». Слово одно (D-216) — второе,
# «Стройка», было хвостом упразднённого типа «постройка» и вело себя точно так
# же, а знала о нём только половина системы.
VIRTUAL_STATIONS = {"Руками"}
# Разговорное название станции -> рецепт, которым она делается
STATION_ALIASES = {"Печь": "Плавильная печь"}

PREFIX_UNITS = {"×", "±", "до +", "до "}

# Знаков после запятой у массы. Килограмм с тремя знаками — это грамм:
# мельче монеты в вольте ничего нет, и округление до грамма не съедает
# ни одну вещь целиком.
ROUND_MASS = 3

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
        elif any(isinstance(x, dict) for x in v.values()):
            # Карта карт: у имени не число, а состав (`build.types`). В реестре
            # на константу отведена одна ячейка, поэтому состав разворачивается
            # строкой, а не вложенной таблицей
            return " · ".join(
                "**{}**: {}".format(k, ", ".join(f"{n} {q}" for n, q in x.items()))
                for k, x in v.items()
            )
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
        rows.append(f"| `{c['key']}` | {fmt_value(c)} | {one_line(sense)} |")
    return "\n".join(rows)


def one_line(said: str) -> str:
    """Заметку — в одну строку: строка таблицы переносов не терпит.

    Заметка ключа бывает в несколько абзацев — у тех, чьё число однажды
    пересматривали, там история пересмотра. В `constants.yaml` абзацы
    разделены пустой строкой, а в ячейке таблицы такая строка обрывает саму
    таблицу: всё после неё выпадает из разметки и читается сплошным текстом
    посреди списка констант. Абзац становится `<br><br>`, перенос внутри
    абзаца — пробелом.
    """
    return "<br><br>".join(
        " ".join(part.split()) for part in said.split("\n\n") if part.strip()
    )

def flatten_constants(doc: dict) -> dict:
    flat: dict[str, object] = {}
    for group in doc["groups"]:
        for c in group["constants"]:
            flat[c["key"]] = {"formula": c["formula"]} if "formula" in c else c.get("value")
    return flat


# ------------------------------------------------------- материалы и классы

def normalize_recipes(doc: dict) -> list[str]:
    """Реестр материалов и классы (D-215) -> прежние плоские представления.

    Источник — `meta.materials` (одна строка на вещь, которая не делается
    рецептом) и поле `class` у рецептов. Отсюда синтезируются `meta.mass`,
    `meta.bulk`, `meta.edible`, `meta.raw`, `meta.tool_classes` и карта
    `meta.classes_map`, которыми пользуется весь остальной код сборки:
    он написан про плоские списки, и переписывать его незачем.

    Заодно разворачивается `gives: {class: X}` у операций — так «Добыча»
    получает все ископаемые из реестра, и новая порода добывается без правки
    самой операции.
    """
    meta = doc["meta"]
    problems: list[str] = []

    declared: list[str] = []
    for c in meta.get("classes", []):
        name = c.get("name")
        if not name:
            problems.append("классы: запись без имени")
            continue
        if name in declared:
            problems.append(f"класс «{name}» объявлен дважды")
        declared.append(name)
    declared_set = set(declared)

    materials: list[dict] = meta.get("materials", [])
    material_names: set[str] = set()
    for m in materials:
        name = m.get("name")
        if not name:
            problems.append("материалы: запись без имени")
            continue
        if name in material_names:
            problems.append(f"материал «{name}» описан дважды")
        material_names.add(name)
        if not isinstance(m.get("mass"), (int, float)) or m["mass"] < 0:
            problems.append(f"материал «{name}»: `mass` обязана быть числом ≥ 0")
        cls = m.get("class")
        if cls is not None and cls not in declared_set:
            problems.append(f"материал «{name}»: класс «{cls}» не объявлен в meta.classes")
        rate = m.get("rate")
        if rate is not None and (not isinstance(rate, (int, float)) or rate <= 0):
            problems.append(f"материал «{name}»: `rate` обязан быть числом больше нуля")
        fuel = m.get("fuel")
        if fuel is not None and (not isinstance(fuel, (int, float)) or fuel <= 0):
            problems.append(f"материал «{name}»: `fuel` обязан быть числом больше нуля")
        relic = m.get("relic")
        if relic is not None and not isinstance(relic, bool):
            problems.append(f"материал «{name}»: `relic` — это true или ничего")
        forage = m.get("forage")
        if forage is not None:
            finds, handful = forage.get("finds"), forage.get("handful")
            if not isinstance(finds, (int, float)) or finds <= 0:
                problems.append(f"материал «{name}»: `forage.finds` обязан быть больше нуля")
            if not isinstance(handful, (int, float)) or handful < 1:
                problems.append(f"материал «{name}»: `forage.handful` меньше единицы не бывает")

    members: dict[str, list[str]] = {}
    for m in materials:
        if m.get("class") and m.get("name"):
            members.setdefault(m["class"], []).append(m["name"])
    recipe_kind: dict[str, str] = {}
    for _, _, r in all_recipes(doc):
        recipe_kind[r["name"]] = r.get("kind", "material")
        fuel = r.get("fuel")
        if fuel is not None and (not isinstance(fuel, (int, float)) or fuel <= 0):
            problems.append(f"«{r['name']}»: `fuel` обязан быть числом больше нуля")
        cls = r.get("class")
        if cls is None:
            continue
        if cls not in declared_set:
            problems.append(f"«{r['name']}»: класс «{cls}» не объявлен в meta.classes")
            continue
        members.setdefault(cls, []).append(r["name"])

    # Операции: класс вместо перечня выходов
    for op in doc["operations"]:
        gives = op.get("gives")
        if isinstance(gives, dict):
            cls = gives.get("class")
            expanded = members.get(cls, [])
            if cls not in declared_set:
                problems.append(f"операция «{op['name']}»: класс «{cls}» не объявлен")
            elif not expanded:
                problems.append(f"операция «{op['name']}»: класс «{cls}» пуст — давать нечего")
            op["gives"] = list(expanded)
            op["gives_class"] = cls

    # Плоские представления для остального кода сборки и для движка
    meta["classes_map"] = {cls: sorted(names) for cls, names in sorted(members.items())}
    meta["mass"] = {m["name"]: m["mass"] for m in materials if m.get("name")}
    meta["bulk"] = (
        [m["name"] for m in materials if m.get("bulk")]
        + [r["name"] for _, _, r in all_recipes(doc) if r.get("bulk")]
    )
    meta["edible"] = (
        [m["name"] for m in materials if m.get("edible")]
        + [r["name"] for _, _, r in all_recipes(doc) if r.get("edible")]
    )
    #: Жидкости (D-230): существуют только в таре. Один список для движка и
    #: клиента, как `bulk` — а не догадка по классу «Жидкость»
    meta["liquid"] = (
        [m["name"] for m in materials if m.get("liquid")]
        + [r["name"] for _, _, r in all_recipes(doc) if r.get("liquid")]
    )
    for _, _, r in all_recipes(doc):
        holds = r.get("holds")
        if holds is not None and holds != "жидкость":
            problems.append(f"«{r['name']}»: `holds` бывает только `жидкость`, а не «{holds}»")
        if holds is not None and not r.get("store"):
            problems.append(f"«{r['name']}»: `holds` без `store` — тара без объёма")
    #: Побочный выход рецепта (D-340): что ещё выходит из партии на единицу
    #: главного выхода, как `byproduct` у культуры. Своей строки рецепта у
    #: побочного нет — он описан в реестре материалов, там его масса.
    byproducts: set[str] = set()
    for _, _, r in all_recipes(doc):
        shed = r.get("byproduct")
        if shed is None:
            continue
        if not isinstance(shed, dict) or not shed:
            problems.append(f"«{r['name']}»: `byproduct` — карта «вещь: количество на единицу»")
            continue
        for name, per in shed.items():
            byproducts.add(name)
            if name not in material_names:
                problems.append(
                    f"«{r['name']}»: побочный выход «{name}» не описан в реестре материалов"
                )
            if not isinstance(per, (int, float)) or per <= 0:
                problems.append(f"«{r['name']}»: побочного «{name}» должно быть больше нуля")
    meta["byproducts"] = sorted(byproducts)
    #: Сбросной газ (D-340): жидкость, которая, не найдя тары, выпускается
    #: в пустоту или сжигается в факеле, а не льётся на пол. Признак вещи, а
    #: не имя (D-215): движок спрашивает флаг, и второй такой газ — строка
    #: данных. Два инварианта держат его честным: сбросным бывает только
    #: жидкое — твёрдое и так ложится рядом, — и жидкий побочный выход обязан
    #: быть сбросным: иначе партии некуда деть то, что не вошло в тару, кроме
    #: пола, а жидкость на полу не живёт (D-230).
    liquids = set(meta["liquid"])
    meta["vent"] = sorted(
        {m["name"] for m in materials if m.get("vent")}
        | {r["name"] for _, _, r in all_recipes(doc) if r.get("vent")}
    )
    for m in [*materials, *(r for _, _, r in all_recipes(doc))]:
        vent = m.get("vent")
        if vent is not None and not isinstance(vent, bool):
            problems.append(f"«{m.get('name')}»: `vent` — это true или ничего")
    for name in meta["vent"]:
        if name not in liquids:
            problems.append(f"«{name}»: `vent` бывает только у жидкости (`liquid: true`)")
    for name in sorted(byproducts & liquids):
        if name not in meta["vent"]:
            problems.append(
                f"«{name}»: жидкий побочный выход обязан быть сбросным газом (`vent: true`) — "
                "иначе то, что не вошло в тару, некуда деть"
            )
    #: Сырьё — то, что берётся из мира, а не переделывается: материал,
    #: который не является выходом расходующей операции. Рубка и добыча
    #: (consumes пуст) берут материю из мира — их выходы остаются сырьём.
    #: Побочный выход рецепта сырьём тоже не бывает: его делает партия.
    produced = {
        g
        for op in doc["operations"]
        if op.get("consumes")
        for g in (op["gives"] if isinstance(op["gives"], list) else [])
    } | byproducts
    meta["raw"] = [m["name"] for m in materials if m.get("name") and m["name"] not in produced]
    #: Прежний вид для клиента и движка: класс, все члены которого —
    #: инструменты. Общая карта классов лежит рядом в `classes_map`.
    meta["tool_classes"] = {
        cls: names
        for cls, names in meta["classes_map"].items()
        if names and all(recipe_kind.get(n) == "tool" for n in names)
    }
    return problems


def load_recipes_doc() -> tuple[dict, list[str]]:
    doc = yaml.safe_load((DATA / "recipes.yaml").read_text(encoding="utf-8"))
    return doc, normalize_recipes(doc)


#: Где лежит дикое семя (D-254). Слово места — из vocabulary.yaml, как у
#: всякого `place`; луг и есть то, с чего начинают восемь культур.
WILD_SEED_PLACE = "луг"


def wild_seed_finds(plants: list[dict], scale: float, handful: float) -> dict[str, dict]:
    """Дикие семена восьми культур: находка луга (D-254).

    Доля культуры НЕ ЗАДАЁТСЯ руками — она обратна требованию к плодородию,
    как урожайность выводится из темпа (D-136). Сорняк, которому хватает
    десяти единиц плодородия, попадается на лугу чаще сахарника, которому
    нужно семьдесят пять, и это единственное, что о дикой культуре нужно
    знать. Задан один общий темп `forage.wild_seeds` — остальное считается.
    """
    weights = {
        plant["seed"]: 1.0 / need
        for plant in plants
        if plant.get("seed") and (need := float(plant["requires"]["fertility"])) > 0
    }
    total = sum(weights.values())
    if not total:  # pragma: no cover -- культура без требования к плодородию
        return {}
    return {
        seed: {
            "finds": round(scale * weight / total, 4),
            "handful": handful,
            "place": WILD_SEED_PLACE,
        }
        for seed, weight in weights.items()
    }


def material_tables(
    doc: dict, plants: list[dict] | None = None, wild: dict[str, dict] | None = None
) -> dict[str, dict[str, float]]:
    """Таблицы констант, собираемые из реестра материалов (D-215).

    В `constants.yaml` эти ключи объявлены с `value_from` вместо `value`:
    смысл и единица живут в реестре констант, числа — в реестре материалов.

    Дикие семена приезжают сюда отдельным словарём (D-254): они товары, но
    живут не в реестре материалов, а в `plants.yaml`, — и в таблицах сбора
    им место рядом со льном, а не в собственной константе.
    """
    materials = doc["meta"].get("materials", [])
    forage = {m["name"]: m["forage"] for m in materials if m.get("forage")}
    forage |= wild or {}
    return {
        "harvest.rates": {
            m["name"]: m["rate"] for m in materials if m.get("rate")
        },
        "forage.finds": {
            name: entry["finds"] for name, entry in forage.items()
        },
        "forage.handful": {
            name: entry["handful"] for name, entry in forage.items()
        },
        #: Где вещь лежит (D-254). Только у привязанных: вещь без записи
        #: находится везде, и пустое место в таблице — это и есть «везде».
        "forage.place": {
            name: entry["place"] for name, entry in forage.items() if entry.get("place")
        },
        #: Горючее бывает и рукотворным (D-252): нефтяной кокс — рецепт, не
        #: сырьё, а жгут его той же топливной станцией. Потому `fuel`
        #: читается и из реестра материалов, и из рецептов.
        "energy.fuel_energy": {
            m["name"]: m["fuel"] for m in materials if m.get("fuel")
        } | {
            r["name"]: r["fuel"] for _, _, r in all_recipes(doc) if r.get("fuel")
        },
    }


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
        shed = r.get("byproduct") or {}
        if isinstance(shed, dict) and shed:
            inputs += " → побочно " + ", ".join(
                f"{lower_first(k)} ×{fmt_qty(v)}" for k, v in shed.items()
            )

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


def compute_amounts(doc: dict, constants: dict) -> tuple[dict, dict, dict, dict, list[str]]:
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
    #: Собственное время шага на единицу — отдельно от суммарной трудоёмкости:
    #: движок и редактор восстанавливали его вычитанием труда входов, и оба
    #: держали копию одной и той же формулы. Теперь оно едет готовым.
    steps = {name: step_of(name) for name in recipes}
    return amounts, op_amounts, labor, steps, problems


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
    """Масса единицы каждого предмета, кг (D-146, D-228).

    **Вес изделия выводится из входов**: сколько вещества вошло в единицу,
    столько она и весит. Материя при переделе не появляется — это и есть
    правило, из которого растёт вся система масс: она упирается в реестр
    материалов, где вес сырья задан руками, и дальше считается сама.

    Три источника, в порядке убывания приоритета:

    1. `mass:` у рецепта — вес, заданный вручную. Ставится там, где физический
       вес известен и с трудовым составом не совпадает: монета в грамм,
       буханка хлеба. Больше вошедшего — **ошибка сборки** (D-215): до этого
       Экзоскелет был объявлен в 35 кг, собирался в 13, и никто об этом не
       знал. Меньше — законно: часть вещества уходит в отход;
    2. вошедшее вещество — сумма масс входов с их количествами (D-228);
    3. `inventory.mass_by_kind` — умолчание по типу предмета. Последняя
       соломинка: остаётся тем, у кого входов с известным весом нет вовсе.

    Цена правила известна и записана в D-228: количества входов заданы
    **трудом**, а не физическим составом (D-133), поэтому в кирку «входит»
    столько железа, сколько стоит её изготовление. Вес, выведенный из таких
    количеств, местами врёт — там и ставится `mass:` руками.
    """
    meta = doc["meta"]
    synonyms = {**STATION_ALIASES, **meta.get("synonyms", {})}

    def canon(name: str) -> str:
        return synonyms.get(name, name)

    #: Реестр материалов: сырьё и продукты операций, вес которых задан руками.
    #: Выводить его не из чего — материя приходит из мира.
    mass: dict[str, float] = {canon(k): float(v) for k, v in meta.get("mass", {}).items()}
    by_kind = flatten_constants(constants).get("inventory.mass_by_kind") or {}
    problems: list[str] = []

    recipes = {canon(r["name"]): r for _, _, r in all_recipes(doc)}
    #: Заданное руками: у рецепта — полем, у материала, носящего то же имя, —
    #: строкой реестра. Подрезается вошедшим и то и другое, но ошибкой считается
    #: только заявка рецепта: строка реестра — основание системы масс, спорить
    #: с ней не о чем, и молчаливой подрезки ей достаточно.
    authored = {name: float(r["mass"]) for name, r in recipes.items() if r.get("mass") is not None}
    for name in recipes:
        if name not in authored and name in mass:
            authored[name] = mass[name]

    #: Выходы операций — то, что берётся из мира или дробится из него. Их масса
    #: обязана быть задана руками: выводить её не из чего.
    for give in op_amounts:
        if canon(give) not in mass:
            problems.append(
                f"«{give}»: продукт операции без массы — задай его в `meta.mass` "
                "(D-146)"
            )

    settled: dict[str, float] = {}

    def settle(name: str, seen: frozenset = frozenset()) -> float:
        """Вес вещи: вошедшее вещество, а где задано руками — заданное."""
        name = canon(name)
        if name in settled:
            return settled[name]
        recipe = recipes.get(name)
        if recipe is None:
            return mass.get(name, 0.0)
        #: Круг по лестнице проверка ловит отдельно и раньше; здесь он не
        #: должен уводить в бесконечность, и вес берётся заданный либо нулевой.
        if name in seen:
            return authored.get(name, 0.0)
        into = sum(
            float(quantity) * settle(item, seen | {name})
            for item, quantity in (amounts or {}).get(recipe["name"], {}).items()
        )
        #: Побочный выход уносит свою долю вошедшего (D-340): вода электролиза —
        #: это кислород и водород вместе, и главному выходу достаётся остаток.
        #: Побочного тяжелее вошедшего быть не может по тому же правилу.
        shed = sum(
            float(quantity) * settle(item, seen | {name})
            for item, quantity in (recipe.get("byproduct") or {}).items()
        )
        if shed > 0 and into > 0:
            if shed >= round(into, 6):
                problems.append(
                    f"«{recipe['name']}»: побочный выход {fmt_qty(round(shed, 3))} кг не меньше "
                    f"вошедшей материи {fmt_qty(round(into, 3))} кг — главному выходу не остаётся "
                    "веса: утяжели состав либо уменьши побочный (D-340)"
                )
            into = max(0.0, into - shed)
        own = authored.get(name)
        if own is not None:
            # Пустой состав не подрезает: вещь без известных входов взвесить не
            # по чему, и нулём её делать нельзя
            if into > 0 and own > round(into, 6) and recipe.get("mass") is not None:
                problems.append(
                    f"«{recipe['name']}»: масса {fmt_qty(own)} кг больше вошедшей материи "
                    f"{fmt_qty(round(into, 3))} кг — материя при переделе не появляется: "
                    "уменьши `mass:` либо утяжели состав (D-215)"
                )
            value = min(own, into) if into > 0 else own
        elif into > 0:
            value = into
        else:
            by_type = by_kind.get(recipe.get("kind", "material"))
            if by_type is None:
                problems.append(
                    f"«{recipe['name']}»: массы нет — входы ничего не весят, "
                    f"задай `mass:` у рецепта либо умолчание для типа "
                    f"«{recipe.get('kind')}» в `inventory.mass_by_kind`"
                )
                #: Ноль запоминается наравне с весом: иначе каждый потребитель
                #: пересчитает его заново, и жалоба напечатается по разу на них.
                settled[name] = 0.0
                return 0.0
            value = float(by_type)
        settled[name] = round(value, ROUND_MASS)
        return settled[name]

    for name in recipes:
        settle(name)
    mass.update(settled)
    return mass, problems


def mass_report(doc: dict, amounts: dict, mass: dict[str, float]) -> list[str]:
    """Что стало весом каждого предмета и что вес себе отстояло (D-228).

    Отчёт кнопки «Массы» в редакторе. Пишет, ничего не меняя: вес выводится
    сборкой, и записывать выведенное в источник нельзя — оно тут же стало бы
    заданным вручную и перестало считаться.
    """
    meta = doc["meta"]
    synonyms = {**STATION_ALIASES, **meta.get("synonyms", {})}

    def canon(name: str) -> str:
        return synonyms.get(name, name)

    derived: list[tuple[str, float]] = []
    pinned: list[tuple[str, float, float]] = []
    for _, _, recipe in all_recipes(doc):
        name = recipe["name"]
        into = sum(
            float(quantity) * mass.get(canon(item), 0.0)
            for item, quantity in (amounts.get(name) or {}).items()
        ) - sum(
            float(quantity) * mass.get(canon(item), 0.0)
            for item, quantity in (recipe.get("byproduct") or {}).items()
        )
        if recipe.get("mass") is None:
            derived.append((name, mass.get(canon(name), 0.0)))
        else:
            pinned.append((name, float(recipe["mass"]), round(into, ROUND_MASS)))

    lines = [
        f"Массы: выведено из входов — {len(derived)}, задано вручную — {len(pinned)}.",
        "",
        f"Выведено из входов ({len(derived)}):",
    ]
    lines += [f"  · {name} — {fmt_qty(value)} кг" for name, value in sorted(derived)]
    if pinned:
        lines += [
            "",
            f"ПРЕДУПРЕЖДЕНИЯ ({len(pinned)}): вес предмета не был обновлён "
            "автоматически, т.к. был переопределён. Уберите значение, и оно "
            "будет заполняться автоматически:",
        ]
        lines += [
            f"  · {name} — задано {fmt_qty(own)} кг"
            + (f", из входов вышло бы {fmt_qty(into)} кг" if into > 0 else ", входы ничего не весят")
            for name, own, into in sorted(pinned)
        ]
    return lines


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
    #: Требование закрывается любым членом класса (D-215): раньше так умели
    #: только инструменты (tool_classes), теперь — любой класс вещей.
    classes: dict[str, list[str]] = meta.get("classes_map") or meta.get("tool_classes", {})
    op_outputs = {g for op in doc["operations"] for g in op["gives"]}

    def canon(name: str) -> str:
        return synonyms.get(name, name)

    def options(name: str) -> list[str]:
        """Чем можно закрыть требование: сам предмет либо любой из класса."""
        name = canon(name)
        return classes.get(name, [name])

    #: Побочные выходы рецептов (D-340) сырьём не считаются, но существуют:
    #: их делает партия, и открываются они вместе со своим рецептом.
    byproducts = set(meta.get("byproducts", []))
    known = set(recipes) | raw | op_outputs | byproducts | VIRTUAL_STATIONS | set(classes)

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
                available.update(r.get("byproduct") or {})
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
    #: Буквально, а не через классы, и это не упущение: движок закрывает
    #: классом **инструмент** и поведение (D-215), а вход рецепта берёт по
    #: имени (`craft/_internal._stock`). Раскрыть здесь значило бы объявить
    #: связанным то, что игра не соберёт.
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
    #    Продукт операции — тот же материал (D-223): олово, которое плавят и не
    #    берут никуда, — такой же тупик, как сталь без потребителя. Раньше
    #    проверка смотрела только на рецепты, и олово с керамикой висели годами
    for g in sorted(op_outputs):
        if g in consumed or g in used_as_station:
            continue
        problems.append(f"тупик: продукт операции «{g}» никуда не идёт — не хватает рецепта")

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


def excuse_known(problems: list[str], recipes_doc: dict) -> tuple[list[str], list[str]]:
    """Развести найденное и записанное — вторая, общая форма known_issues.

    Циклы извиняются структурно в check_recipes; всему остальному — тупикам,
    двойникам составов — структурной формы нет, и запись `{problem, oq}`
    извиняет проблему по её началу, слово в слово как печатает сборка.
    Каждая запись обязана ссылаться на OQ: без вопроса это не «известное
    расхождение», а замалчивание.
    """
    excused = [
        (issue["problem"], issue["oq"])
        for issue in recipes_doc.get("known_issues") or []
        if "problem" in issue
    ]
    fresh: list[str] = []
    known: list[str] = []
    for problem in problems:
        oq = next((oq for prefix, oq in excused if problem.startswith(prefix)), None)
        (known if oq else fresh).append(f"{problem}  [{oq}]" if oq else problem)
    return fresh, known


def check_compositions(doc: dict, amounts: dict, batch_cap: float) -> list[str]:
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

    # Штучное считают штуками (D-212), но норма рецепта дробной быть вправе
    # (D-133): движок берёт целые куски **на партию**, а не на единицу. Десятая
    # слитка в монете значит слиток на десять монет — это законно и так и
    # задумано. Незаконна доля, которая не складывается в целое ни при какой
    # партии: с «0.3 слитка» игрок переплачивает всегда, сколько ни чекань.
    bulk = {canon(name) for name in doc["meta"].get("bulk", [])}
    for _, _, r in all_recipes(doc):
        for item, quantity in amounts.get(r["name"], {}).items():
            if canon(item) in bulk or float(quantity).is_integer():
                continue
            batch = 1 / float(quantity)
            if batch.is_integer() and batch <= batch_cap:
                continue
            problems.append(
                f"«{r['name']}»: «{item}» штучное, а требуется {fmt_qty(quantity)} — "
                "доля не складывается в целое разумной партией: задай целое "
                "количество, долю вида 1/N либо назови вещь весовой в "
                "`meta.bulk` (D-212, D-133)"
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


def build_constants(recipes_doc: dict) -> tuple[str, dict, list[str]]:
    doc = yaml.safe_load((DATA / "constants.yaml").read_text(encoding="utf-8"))
    problems: list[str] = []

    # Таблицы, ключуемые именами материалов, собираются из реестра (D-215):
    # запись в constants.yaml держит ключ, единицу и смысл (`value_from:
    # materials`), а числа лежат у самих материалов — один источник на вещь.
    # Дикие семена (D-254) считаются здесь же: `plants.yaml` читается сырым —
    # нужны только `seed` и требование к плодородию, а не выведенный каталог,
    # который сам ждёт готовых констант
    plants = yaml.safe_load((DATA / "plants.yaml").read_text(encoding="utf-8"))["plants"]
    plain = flatten_constants(doc)
    tables = material_tables(
        recipes_doc,
        plants,
        wild_seed_finds(
            plants,
            float(plain["forage.wild_seeds"]),
            #: Горсть дикого семени — ровно на одну минимальную делянку: норма
            #: высева на её площадь. Число не задаётся, потому что это не
            #: отдельное решение, а следствие двух уже принятых.
            float(plain["farm.seed_rate"]) * float(plain["farm.plot_min_area"]),
        ),
    )
    declared_keys = {c["key"] for g in doc["groups"] for c in g["constants"]}
    for group in doc["groups"]:
        for c in group["constants"]:
            source = c.get("value_from")
            if source is None:
                if c["key"] in tables:
                    problems.append(
                        f"константа «{c['key']}» задана значением в constants.yaml, "
                        "а числа для неё живут в реестре материалов — поставь "
                        "`value_from: materials` (D-215)"
                    )
                continue
            if source != "materials" or c["key"] not in tables:
                problems.append(
                    f"константа «{c['key']}»: `value_from: {source}` — сборка "
                    "умеет наполнять из материалов только "
                    + ", ".join(f"`{k}`" for k in sorted(tables))
                )
                continue
            c["value"] = tables[c["key"]]
    for key in tables:
        if key not in declared_keys:
            problems.append(
                f"таблица «{key}» собирается из реестра материалов, но в "
                "constants.yaml нет записи с `value_from: materials` — ключ, "
                "единица и смысл живут там"
            )

    # Именованные дубли темпа обязаны совпадать с реестром: два числа об одном
    # и том же врозь — это два источника истины
    flat = flatten_constants(doc)
    rates = tables.get("harvest.rates", {})
    for key, resource in (
        ("mining.iron_per_hour", "Железная руда"),
        ("mining.gold_per_hour", "Золотоносная порода"),
        ("mining.silver_per_hour", "Серебряная порода"),
    ):
        own, reg = flat.get(key), rates.get(resource)
        if own is not None and reg is not None and float(own) != float(reg):
            problems.append(
                f"«{key}» = {own} расходится с rate «{resource}» = {reg} "
                "в реестре материалов"
            )

    groups = {g["id"]: g for g in doc["groups"]}

    def resolve(token: str) -> str:
        kind, _, arg = token.partition(":")
        if kind == "constants":
            return render_constants_group(groups[arg])
        raise KeyError(f"неизвестный плейсхолдер {{{{{token}}}}}")

    tmpl = (TEMPLATES / "constants.md.tmpl").read_text(encoding="utf-8")
    return render_template(tmpl, resolve), doc, problems


def build_recipes(
    constants: dict, doc: dict
) -> tuple[str, dict, dict, dict, dict, dict, dict, list[str]]:
    levels = {str(l["id"]): l for l in doc["levels"]}
    amounts, op_amounts, labor, steps, qty_problems = compute_amounts(doc, constants)
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
    return render_template(tmpl, resolve), doc, amounts, op_amounts, labor, steps, mass, qty_problems


# ----------------------------------------------------------------- культуры

def compute_plants(doc: dict, constants: dict, recipes_doc: dict) -> tuple[list[dict], list[str]]:
    """Урожайность выводится из трудоёмкости, а не задаётся (D-136).

    Час ухода за делянкой обязан стоить столько же, сколько час любого другого
    труда (И2). Значит культура за цикл должна дать ровно столько, сколько
    даёт `harvest.rates` её продукта за потраченные на неё часы:

        действий за цикл = цикл / суток_в_полосе + цикл / суток_до_сорняка
                         + прореживание + подкормок
        часы за цикл     = (накладные + уход × площадь)/60 × действий + вспашка × площадь/60
        урожай с м²      = harvest.rates[продукт] × часы ÷ площадь

    Отсюда сама собой выходит честная связь: долгий цикл окупается большим
    урожаем, а быстрая репа берёт оборотом, а не разовым сбором.
    """
    flat = flatten_constants(constants)
    rates = flat.get("harvest.rates", {})
    area = doc["meta"].get("reference_area", 100)
    # Одно действие на опорном хозяйстве — три делянки на сотню метров (D-296)
    action = (3 * flat["farm.plot_overhead"] + flat["farm.care_time_per_m2"] * area) / 60
    plow = flat["farm.plow_time_per_m2"] * area / 60
    dry_rate = flat["farm.dry_rate"] / 100
    drink = flat["farm.water_by_need"]
    bands = flat["farm.moisture_by_need"]
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
        req, tr = p["requires"], p["traits"]
        # Действий за цикл — из самой модели ухода (D-296): поливов столько,
        # сколько раз влага уйдёт из полосы при опорном климате (без реки и
        # дождя, farm.dry_temp_ref) — экспонента с жаждой культуры; подкормок —
        # по строкам таблицы. Суточной нормы нет: сколько просит земля
        need = str(req["water"])
        band = bands[need]
        leave_days = math.log(band["max"] / band["min"]) / (dry_rate * float(drink[need]))
        waterings = p["cycle"] / leave_days
        # Прополок за цикл (D-297): сорняк доходит до порога видимости за
        # weed_seen / (weed_per_day × плодородие нормы / 100) суток — на земле,
        # какую культура просит. Прореживание — одно, и только там, где оно
        # окупается: risk/5 × crowd_penalty > thin_loss
        weed_days = flat["farm.weed_seen"] / (
            flat["farm.weed_per_day"] * max(req["fertility"], 1) / 100
        )
        weedings = p["cycle"] / weed_days
        thinnings = (
            1 if tr["density_risk"] / 5 * flat["farm.crowd_penalty"] > flat["farm.thin_loss"] else 0
        )
        actions = waterings + weedings + thinnings + len(p.get("feeding") or [])
        hours = action * actions + plow
        total = rate * hours

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

        #: Абзац говорит характером, а не величинами (D-311): всё, что можно
        #: перенастроить, говорит собранная часть, и абзац с величиной внутри
        #: пережил бы перенастройку ложью.
        problems.extend(check_care_note(p["name"], p.get("care_note") or ""))

        out.append({
            "id": p["id"], "name": p["name"], "gives": p["gives"],
            # дикий предок — отдельный сорт со своим именем (D-260)
            "wild_name": p.get("wild_name"),
            # чем сеют: семена — предмет, отдельный от продукта (D-057)
            "seed": p["seed"],
            "byproduct": p.get("byproduct"), "cycle_days": p["cycle"],
            "yield_per_m2": round(total / area, 3),
            "waterings_per_cycle": round(waterings, 1),
            "weedings_per_cycle": round(weedings, 1),
            "thinnings_per_cycle": thinnings,
            "actions_per_cycle": round(actions, 1),
            "yield_per_cycle": round(total, 1),
            "requires": req, "traits": tr,
            "restores_fertility": p.get("restores", 0),
            # подкормка растущего по фазам — знание, скрытое от игрока (D-296)
            "feeding": p.get("feeding") or [],
            # написанный абзац, если он есть (D-311): движку нужен сам факт —
            # слово он берёт по ключу на языке читателя, как всякое имя вольта
            "care_note": p.get("care_note"),
            "generosity": score, "generosity_cap": allowed, "used_in_recipes": uses,
        })
    return out, problems


def render_plants(plants: list[dict]) -> str:
    rows = ["| Культура | Даёт | Цикл | Действий за цикл | Урожай с м² | Температура | Вода | Плодородие | Свет |",
            "|---|---|---|---|---|---|---|---|---|"]
    water = {1: "мало", 2: "средне", 3: "много"}
    light = {1: "терпит тень", 2: "среднее", 3: "любит свет"}
    for p in plants:
        r = p["requires"]
        extra = f" + {p['byproduct']}" if p["byproduct"] else ""
        rows.append(
            f"| **{p['name']}** | {p['gives']}{extra} | {p['cycle_days']} сут | "
            f"{p['actions_per_cycle']:g} | {p['yield_per_m2']:g} | {r['temp']['min']}…{r['temp']['max']} °C | "
            f"{water[r['water']]} | {r['fertility']} | {light[r['light']]} |")
    return "\n".join(rows)


def render_plant_care(plants: list[dict]) -> str:
    """Написанные абзацы (D-311) — на той же странице, что и числа.

    Кто крутит выносливость и цикл, видит рядом прозу, которую эта правка
    может состарить: проверка ловит цифру и сравнение, а всё прочее ловит
    только глаз, и ему надо на что смотреть.
    """
    said = [p for p in plants if p.get("care_note")]
    if not said:
        return "_ни у одной культуры пока не написан_"
    rows = ["| Культура | Абзац |", "|---|---|"]
    rows.extend(f"| **{p['name']}** | {p['care_note']} |" for p in said)
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


#: Фазы роста (D-296): всходы — от нуля, границы остальных — `farm.stage_bounds`.
STAGE_WORDS = {"sprout": "всходы", "leaf": "лист", "bloom": "цветение", "fill": "налив"}


def fertilizer_names(recipes_doc: dict) -> dict[str, str]:
    """id → имя для вещей класса «Удобрение»: список класса ведётся именами,
    а `plants.yaml` зовёт удобрение устойчивым ключом (D-251, D-291)."""
    members = set(recipes_doc["meta"].get("classes_map", {}).get("Удобрение", []))
    return {r["id"]: r["name"] for _, _, r in all_recipes(recipes_doc)
            if r.get("id") and r.get("name") in members}


def check_feeding(doc: dict, constants: dict, recipes_doc: dict) -> list[str]:
    """Подкормка по фазам (D-296): фаза из закрытого списка, удобрение — вещь
    класса «Удобрение», ускорение — положительное число."""
    flat = flatten_constants(constants)
    stages = ("sprout", *(flat.get("farm.stage_bounds") or {}).keys())
    known = fertilizer_names(recipes_doc)
    problems: list[str] = []
    for p in doc["plants"]:
        for row in p.get("feeding") or []:
            where = f"культура «{p['name']}», подкормка {row}"
            if row.get("stage") not in stages:
                problems.append(f"{where}: фаза не из {list(stages)}")
            if row.get("fertilizer") not in known:
                problems.append(f"{where}: «{row.get('fertilizer')}» — не вещь класса «Удобрение»")
            growth = row.get("growth")
            if not isinstance(growth, (int, float)) or growth <= 0:
                problems.append(f"{where}: ускорение должно быть положительным числом")
    return problems


def render_plant_feeding(plants: list[dict], recipes_doc: dict) -> str:
    names = fertilizer_names(recipes_doc)
    rows = ["| Культура | Фаза | Удобрение | Быстрее до конца фазы |", "|---|---|---|---|"]
    for p in plants:
        feeding = p.get("feeding") or []
        if not feeding:
            rows.append(f"| **{p['name']}** | — | не кормят: любое удобрение — ожог | — |")
            continue
        for n, row in enumerate(feeding):
            head = f"**{p['name']}**" if n == 0 else ""
            rows.append(f"| {head} | {STAGE_WORDS.get(row['stage'], row['stage'])} | "
                        f"{names.get(row['fertilizer'], row['fertilizer'])} | +{row['growth']:g} % |")
    return "\n".join(rows)


#: Слова, которыми абзац сравнивает культуру с остальными. Это те же
#: перенастраиваемые величины, только незаметные проверке на цифру: «мягче
#: всех» переживёт правку выносливости ложью ровно так же, как «выносливость 4»,
#: и вдобавок проверить его нечем — сравнение верно или нет только вместе со
#: всей таблицей. Абзац рассказывает про свою культуру и ни с кем её не мерит.
CARE_COMPARISONS = (
    "всех", "прочих", "прочими", "остальных", "любой другой", "всякой другой",
    "всякого другого", "than any", "than the", "than another", "of them all",
    "most gently", "the most",
)


def check_care_note(name: str, said: str) -> list[str]:
    """Написанный абзац культуры на любом языке (D-311)."""
    problems: list[str] = []
    if any(ch.isdigit() for ch in said):
        problems.append(
            f"культура «{name}»: в написанном абзаце есть число — "
            "числа говорит собранная часть текста, абзац говорит характером (D-311)")
    low = said.lower()
    for word in CARE_COMPARISONS:
        if word in low:
            problems.append(
                f"культура «{name}»: в написанном абзаце сравнение «{word}» — "
                "абзац говорит про свою культуру и ни с кем её не мерит (D-311)")
            break
    return problems


def build_plants(constants: dict, recipes_doc: dict) -> tuple[str, list[dict], list[str]]:
    doc = yaml.safe_load((DATA / "plants.yaml").read_text(encoding="utf-8"))
    plants, problems = compute_plants(doc, constants, recipes_doc)
    problems += check_feeding(doc, constants, recipes_doc)

    def resolve(token: str) -> str:
        _, _, what = token.partition(":")
        if what == "table":
            return render_plants(plants)
        if what == "traits":
            return render_plant_traits(plants)
        if what == "care":
            return render_plant_care(plants)
        if what == "feeding":
            return render_plant_feeding(plants, recipes_doc)
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
    """Дерево устава должно быть связным: ссылки ведут в существующие вопросы.

    И вариант код-закона — ключ, а не слово: движок сравнивает с ним, а язык
    показа приходит оверлеем. Умолчание обязано быть одним из вариантов,
    иначе новый город заводится со значением, которого нет в списке.
    """
    problems: list[str] = []
    for law in doc.get("code_laws", []):
        options = law.get("options") or []
        seen: set[str] = set()
        for option in options:
            key = option.get("id", "")
            if not ID_RE.match(str(key)):
                problems.append(
                    f"код-закон «{law['id']}»: вариант «{key}» — не snake_case ASCII"
                )
            if key in seen:
                problems.append(f"код-закон «{law['id']}»: вариант «{key}» повторяется")
            seen.add(key)
            if not str(option.get("label", "")).strip():
                problems.append(f"код-закон «{law['id']}»: у варианта «{key}» нет имени показа")
        if options and law.get("default") not in seen:
            problems.append(
                f"код-закон «{law['id']}»: умолчание «{law.get('default')}» "
                "не входит в его варианты"
            )
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
#: Реестр ключей сокета: команд и событий. Он и так исключён из проверки —
#: документ целиком состоит из таких имён, — и потому годится в источник:
#: что названо здесь, то ключ, а не величина.
SOCKET_KEYS_DOC = "90-production/08-session-protocol.md"


def socket_keys(protocol: str) -> set[str]:
    """Имена, которые протокол сессии называет ключами сокета (D-226).

    Точка в них разделяет не пространство и величину, а команду или вид
    события: `ship.orbit` — приказ рулевому, `mining.swing` — взмах в забое.
    Пространства у них общие с реестром величин — «ship», «bank», «market», —
    и без этого списка проверка объявляла бы пропавшей константой каждое
    названное действие. Список не пишется руками: он читается из самого
    протокола, и новая команда попадает в него вместе со своей записью там.
    """
    return set(CONST_REF.findall(protocol))


def named_socket_keys() -> set[str]:
    """То же, прочитанное из протокола на диске."""
    doc = ROOT / SOCKET_KEYS_DOC
    if not doc.exists():  # pragma: no cover -- документ на месте с D-226
        return set()
    return socket_keys(doc.read_text(encoding="utf-8"))


def missing_constant(
    key: str, known: set[str], namespaces: set[str], keys_of_socket: set[str]
) -> bool:
    """Обещает ли эта ссылка величину, которой в реестре нет.

    Три имени с точкой из четырёх — не величина, и каждое отсеивается своим
    признаком:

    * **имя файла**: `recipes.json`, `plants.yaml` — по расширению;
    * **чужое пространство**: `everse.life` — домен, а не величина. Имя
      проверяется, только если его пространство есть в реестре, и опечатка
      внутри живого пространства (`craft.time_per_unitt`) ловится по-прежнему;
    * **ключ сокета**: `ship.orbit` — приказ рулевому. Он живёт в протоколе
      сессии, а не в реестре констант, и назвать его в реестре действий или в
      словаре законно.
    """
    if key.rsplit(".", 1)[-1] in FILE_SUFFIXES:
        return False
    if key.split(".", 1)[0] not in namespaces:
        return False
    if key in keys_of_socket:
        return False
    return key not in known


def check_constant_refs(constants_doc: dict) -> list[str]:
    """Документ не вправе обещать число, которого нет в реестре (D-065).

    Ловит обратную ошибку тоже: константу удалили решением, а текст на неё
    ссылается. Это **предупреждение**, а не проблема (см. `main`): движок
    документов не читает, и чинится такое строкой текста.

    Одна строка на документ, а не на ссылку: план карты называл девять снятых
    констант девятью строками, и вся проверка тонула в одном файле.
    """
    known = set(flatten_constants(constants_doc))
    namespaces = {key.split(".", 1)[0] for key in known}
    keys_of_socket = named_socket_keys()
    problems: list[str] = []
    for path, rel in vault_pages():
        # Журнал решений — архив: замороженные и пересмотренные записи законно
        # ссылаются на константы, которых в реестре уже нет (например D-108).
        # Отчёт симуляции — наоборот: он существует ради того, чтобы называть
        # недостающие величины. Протокол сессии — третий случай: точка в нём
        # разделяет не пространство и величину, а вид события журнала
        # (`chat.said`, `mining.swing`; их реестр — `EventKind` движка) либо
        # ключ сокета. Реестр констант таких имён не знает и знать не должен,
        # а пространства у них общие с ним — «bank», «craft», «market», — и
        # проверка объявляла пропавшей константой каждое названное событие.
        # Ревью кода — четвёртый случай той же природы, что протокол сессии:
        # документ про код и состоит из имён кода. `ledger.post`, `body.stamina`,
        # `market.reserve`, `bank.view` — методы, поля и команды сокета, а
        # пространства у них общие с реестром величин. Переписать два десятка
        # ссылок ради проверки значило бы испортить сам документ.
        #
        # Пятого исключения-документа нет и не будет: реестр действий и словарь
        # называют и величины, и команды вперемешку, и вычеркнуть их целиком
        # значило бы перестать проверять сорок настоящих ссылок ради двух
        # ненастоящих. Там работает `socket_keys` — исключение по имени, а не
        # по документу.
        #: README редактора здесь наравне с прочими: это документ вольта про
        #: вольт, и величины он называет живые — проверено, когда его вернули
        #: в обход (`vault_pages`).
        if rel in (
                "90-production/02-decision-log.md", "90-production/04-simulation.md",
                "90-production/08-session-protocol.md",
                "90-production/09-code-review-2026-08-23.md"):
            continue
        gone = [
            key
            for key in sorted(set(CONST_REF.findall(path.read_text(encoding="utf-8"))))
            if missing_constant(key, known, namespaces, keys_of_socket)
        ]
        if gone:
            problems.append(f"{rel} — {', '.join(gone)}")
    return problems


BUILDING_MAPS = (
    "build.types",
    "build.floor_growth_by_type",
    "build.decay_by_type",
)


def check_biome_figure(constants_doc: dict) -> list[str]:
    """У каждого биома есть знак растительности, зерно и доли меток, и лишних нет (D-331).

    Клиент рисует биом без записи в `biome.figure` ничем и не жалуется
    (`figures.ts`: нет знака — нет фигуры), без записи в `biome.grain` —
    зерном по умолчанию (`grain.GRAIN_FALLBACK`), а реестр движка проверяет
    только слова (`registry_map.BIOME_FIGURE`, `BIOME_GRAIN`): пропущенный
    биом узнали бы по пустой карте. Сверяются три карты по биомам —
    `biome.figure`, `biome.grain` и `biome.marks` — со словарём `biome.names`.
    """
    flat = flatten_constants(constants_doc)
    names = flat.get("biome.names")
    if not isinstance(names, dict):
        return ["biome.names: нет словаря биомов"]
    problems: list[str] = []
    for key in ("biome.figure", "biome.grain", "biome.marks"):
        table = flat.get(key)
        if not isinstance(table, dict):
            problems.append(f"{key}: нет карты по биомам")
            continue
        for biome in sorted(set(names) - set(table)):
            problems.append(f"{key}: нет записи для биома «{biome}»")
        for biome in sorted(set(table) - set(names)):
            problems.append(f"{key}: биом «{biome}», которого нет в biome.names")
    return problems


def check_building_types(constants_doc: dict, recipes_doc: dict) -> list[str]:
    """Тип здания живёт в трёх картах, и они обязаны совпадать (D-218, D-219).

    Состав, рост этажа и порча задаются по отдельности — добавить тип в одну
    карту и забыть про две остальные слишком легко, а движок узнает об этом на
    тике, спустя часы. Здесь же — и состав: имя материала с опечаткой пройдёт и
    YAML, и сборку, и откажет только в момент стройки.
    """
    flat = flatten_constants(constants_doc)
    composition = flat.get(BUILDING_MAPS[0])
    if not isinstance(composition, dict):
        return [f"{BUILDING_MAPS[0]}: нет карты типов зданий"]

    problems: list[str] = []
    for key in BUILDING_MAPS[1:]:
        values = flat.get(key)
        if not isinstance(values, dict):
            problems.append(f"{key}: нет карты по типам зданий")
            continue
        for missing in composition.keys() - values.keys():
            problems.append(f"{key}: нет значения для типа «{missing}»")
        for extra in values.keys() - composition.keys():
            problems.append(f"{key}: тип «{extra}» есть здесь, но не в {BUILDING_MAPS[0]}")

    known = {rec["name"] for _, _, rec in all_recipes(recipes_doc)}
    known |= {m["name"] for m in (recipes_doc["meta"].get("materials") or [])}
    known |= {g["name"] for g in (recipes_doc["meta"].get("operations") or [])}
    for kind, parts in composition.items():
        if not isinstance(parts, dict) or not parts:
            problems.append(f"{BUILDING_MAPS[0]}: у типа «{kind}» пустой состав")
            continue
        for name, amount in parts.items():
            if known and name not in known:
                problems.append(
                    f"{BUILDING_MAPS[0]}: у типа «{kind}» материала «{name}» нет в вольте"
                )
            if not isinstance(amount, (int, float)) or amount <= 0:
                problems.append(
                    f"{BUILDING_MAPS[0]}: у типа «{kind}» расход «{name}» не больше нуля"
                )
    return problems


#: Таблицы констант, чьи ключи — вещи одного класса (D-291): у каждого члена
#: класса есть строка, у каждой строки — член. Поведение у класса, число — у
#: вещи; расхождение между ними движок заметил бы только на команде игрока
CLASS_ROW_TABLES = (
    ("farm.fertilizer_recovery", ("Удобрение",)),
    #: Длина защиты — по вещи, а классов у неё четыре (D-299): строка
    #: обязана быть у каждого средства любого из них, и каждая строка —
    #: стоять за средством, иначе таблица разойдётся с рецептами молча
    ("farm.protect_days", ("Фунгицид", "Акарицид", "Инсектицид", "Бактерицид")),
)

#: Таблицы, чьи ЗНАЧЕНИЯ — идентификаторы классов вещей (D-299): связка
#: «напасть → чем гасят» живёт в данных, и класс, которого нет, оставил бы
#: напасть без средства — движок узнал бы об этом на команде игрока
CLASS_VALUE_TABLES = (
    "farm.pest_cure",
)

#: Таблицы, ключуемые классами вещей (D-215, D-291): ключ, которого нет среди
#: объявленных классов, не совпал бы ни с одной стоящей вещью и молча
#: выпал бы из механики. `transport.*` сюда не входят: там рядом с классами
#: стоят слова без класса («судно»), и это законно до их появления
CLASS_KEYED_TABLES = (
    "chat.leak_location_modifier",
)


def check_class_tables(constants_doc: dict, recipes_doc: dict) -> list[str]:
    """Класс вещи и таблица по вещи обязаны совпадать (D-291)."""
    flat = flatten_constants(constants_doc)
    classes: dict[str, list[str]] = recipes_doc["meta"].get("classes_map") or {}
    declared = {c.get("name") for c in recipes_doc["meta"].get("classes", [])}
    problems: list[str] = []
    ids = {c.get("id") for c in recipes_doc["meta"].get("classes", [])}
    for key, group in CLASS_ROW_TABLES:
        rows = flat.get(key)
        named = "», «".join(group)
        if not isinstance(rows, dict):
            problems.append(f"{key}: нет таблицы по вещам класса «{named}»")
            continue
        members = {thing for cls in group for thing in classes.get(cls, [])}
        for missing in sorted(members - rows.keys()):
            problems.append(f"{key}: у «{missing}» класса «{named}» нет строки")
        for extra in sorted(rows.keys() - members):
            problems.append(f"{key}: «{extra}» есть в таблице, но не в классе «{named}»")
    for key in CLASS_VALUE_TABLES:
        rows = flat.get(key)
        if not isinstance(rows, dict):
            problems.append(f"{key}: нет таблицы со значениями-классами")
            continue
        for word in sorted(set(map(str, rows.values())) - ids):
            problems.append(f"{key}: «{word}» — не объявленный класс вещей")
    for key in CLASS_KEYED_TABLES:
        rows = flat.get(key)
        if not isinstance(rows, dict):
            problems.append(f"{key}: нет таблицы по классам")
            continue
        for word in sorted(rows.keys() - declared):
            problems.append(f"{key}: «{word}» — не объявленный класс вещей")
    return problems


# ---------------------------------------------------- устойчивые ключи (D-251)

#: Английский snake_case: то, что живёт в коде, в базе и в проводе после
#: волны II. Русское имя остаётся языком вольта и игрока.
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def load_vocabulary() -> dict:
    """Малые словари (data/vocabulary.yaml): слоты, тиры, типы зданий,
    свойства узлов, планеты, виртуальные станции. Слова-идентификаторы,
    у которых нет собственной записи в recipes.yaml."""
    path = DATA / "vocabulary.yaml"
    if not path.exists():
        sys.exit(
            f"нет {path.relative_to(ROOT).as_posix()}: малые словари D-251 "
            "живут отдельным файлом, без него ключи не сходятся"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


#: Языки, кроме языка вольта. Вольт пишется по-русски, и русское имя лежит
#: рядом с самим объектом; перевод — оверлей поверх идентификаторов.
LOCALES_DIR = DATA / "locales"


def load_locales() -> dict[str, dict]:
    """Оверлеи имён по языкам: `data/locales/<язык>.yaml` -> домен -> id -> имя.

    Файлов может не быть вовсе — тогда язык у мира один, и это законное
    состояние вольта до волны V. А вот неполный файл законным состоянием не
    является: язык, у которого имя есть не у всякой вещи, показывает игроку
    `iron_ore` посреди фразы. Полноту проверяет `check_locales`.
    """
    out: dict[str, dict] = {}
    for path in sorted(LOCALES_DIR.glob("*.yaml")):
        out[path.stem] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return out


def check_locales(renames: dict, locales: dict[str, dict]) -> list[str]:
    """У каждого id — имя в каждом языке, и ни одного лишнего.

    Лишнее не менее важно недостающего: имя, оставшееся от переименованной
    вещи, читается как опечатка в словаре и живёт годами, потому что его никто
    не показывает.
    """
    problems: list[str] = []
    known = {domain: set(table) for domain, table in renames["names_ru"].items()}
    for lang, overlay in sorted(locales.items()):
        #: Написанный абзац проверяется на каждом языке (D-311): по-английски
        #: «the most gently» врёт ровно так же, как «мягче всех».
        for key, said in sorted((overlay.get("plant_care") or {}).items()):
            problems.extend(
                problem.replace("культура", f"культура ({lang})")
                for problem in check_care_note(key, str(said))
            )
        for domain, ids in sorted(known.items()):
            said = set(overlay.get(domain, {}))
            for key in sorted(ids - said):
                problems.append(f"locales/{lang}.yaml: нет имени для «{key}» ({domain})")
            for key in sorted(said - ids):
                problems.append(f"locales/{lang}.yaml: имя для «{key}» ({domain}), которого нет")
        for domain in sorted(set(overlay) - set(known)):
            problems.append(f"locales/{lang}.yaml: домен «{domain}», которого нет в ключах")
    return problems


def check_ids(
    recipes_doc: dict,
    vocabulary: dict,
    constants_doc: dict,
    world_doc: dict,
    plants: list[dict] = (),
) -> list[str]:
    """Каждому имени — ключ (D-251), и ровно один.

    Пространств три: товары (материалы + рецепты — как сегодня одно имя не
    может быть и тем и другим), классы, операции. Словари vocabulary.yaml —
    каждый своё пространство. Совпадение ключа МЕЖДУ пространствами законно:
    класс «Топор» и рецепт «Топор» делят и русское слово, и `axe`.
    """
    problems: list[str] = []

    def need(entry: dict, domain: str, seen: dict[str, str]) -> None:
        name = entry.get("name", "?")
        entry_id = entry.get("id")
        if not entry_id:
            problems.append(f"{domain}: у «{name}» нет id (D-251)")
            return
        if not ID_RE.match(str(entry_id)):
            problems.append(f"{domain}: id «{entry_id}» у «{name}» — не snake_case ASCII")
            return
        if entry_id in seen and seen[entry_id] != name:
            problems.append(f"{domain}: id «{entry_id}» занят и «{seen[entry_id]}», и «{name}»")
        seen[entry_id] = name

    #: Дизъюнктность имён — пришпилена, а не предположена: build_renames
    #: собирает goods по имени, и одно имя на материал и рецепт молча
    #: перезаписало бы таблицу миграции волны II.
    material_names = [m["name"] for m in recipes_doc["meta"].get("materials", [])]
    recipe_names = [r["name"] for _, _, r in all_recipes(recipes_doc)]
    for name in sorted(set(material_names) & set(recipe_names)):
        problems.append(
            f"«{name}» — и материал, и рецепт: пространство товаров одно, "
            "и имя в нём живёт один раз"
        )
    for domain, names in (("материалы", material_names), ("рецепты", recipe_names)):
        counted = Counter(names)
        for name in sorted(n for n, k in counted.items() if k > 1):
            problems.append(f"{domain}: имя «{name}» встречается больше одного раза")

    goods_seen: dict[str, str] = {}
    for material in recipes_doc["meta"].get("materials", []):
        need(material, "материал", goods_seen)
    for _, _, recipe in all_recipes(recipes_doc):
        need(recipe, "рецепт", goods_seen)
    #: Семена культур делят пространство товаров: их id выводится из id
    #: культуры, и коллизия с рукописным id — та же ошибка, что и любая другая.
    for seed_name, seed_id in seed_ids(list(plants)).items():
        need({"name": seed_name, "id": seed_id}, "семя", goods_seen)
    class_seen: dict[str, str] = {}
    for cls in recipes_doc["meta"].get("classes", []):
        need(cls, "класс", class_seen)
    op_seen: dict[str, str] = {}
    for op in recipes_doc["operations"]:
        need(op, "операция", op_seen)

    vocab_maps: dict[str, dict[str, str]] = {}
    for domain, rows in vocabulary.items():
        seen: dict[str, str] = {}
        for row in rows or []:
            need(row, f"vocabulary.{domain}", seen)
        vocab_maps[domain] = {
            row["name"]: row["id"] for row in rows or [] if row.get("id")
        }

    # Покрытие: слово, употреблённое данными, обязано быть объявлено.
    def covered(words, domain: str, where: str) -> None:
        table = vocab_maps.get(domain, {})
        for word in words:
            if word not in table:
                problems.append(
                    f"vocabulary.yaml: «{word}» ({where}) не объявлено в {domain}"
                )

    flat = flatten_constants(constants_doc)
    covered(recipes_doc["meta"].get("gear_slots", []), "slots", "gear_slots")
    covered(
        [tier["name"] for tier in flat.get("quality.tiers", [])],
        "tiers", "quality.tiers",
    )
    covered(sorted(flat.get("build.types", {})), "building_kinds", "build.types")
    covered(sorted(flat.get("wear.environment_k", {})), "planets", "wear.environment_k")
    properties: set[str] = set()
    for node in world_doc.get("nodes", []):
        properties |= set((node.get("properties") or {}).keys())
    for op in recipes_doc["operations"]:
        if op.get("place"):
            properties.add(op["place"])
    #: Место находки — то же слово и та же проверка, что у операции (D-254).
    for m in recipes_doc["meta"].get("materials", []):
        if (found := m.get("forage")) and found.get("place"):
            properties.add(found["place"])
    properties.add(WILD_SEED_PLACE)
    covered(sorted(properties), "node_properties", "properties узлов и place операций")
    covered(sorted(VIRTUAL_STATIONS), "virtual_stations", "виртуальные станции")
    return problems


def seed_ids(plants: list[dict]) -> dict[str, str]:
    """Семена культур — тоже товары (item.type_key), но живут в plants.yaml.

    Свой id семени не пишется руками: он выводится из id культуры —
    `spelt` -> `spelt_seeds`. Одно правило вместо восьми строк, и новая
    культура получает ключ семени бесплатно.
    """
    return {
        plant["seed"]: f"{plant['id']}_seeds"
        for plant in plants
        if plant.get("seed") and plant.get("id")
    }


def load_facets() -> tuple[dict[str, list[dict]], list[str]]:
    """`data/facets.yaml`: биом -> строки фацетов (план ландшафта §6).

    Проверяется то, что ломает выбор фацета или подпись на карте: id в
    snake_case и единственный на весь вольт, имя не длиннее подписи, доли
    биома в сумме сто, коробка `where` внутри нуля и единицы, метки и
    множители — числа. Файла может не быть — тогда фацетов нет, и это
    законно до волны 7.
    """
    path = DATA / "facets.yaml"
    if not path.exists():
        return {}, []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    table = doc.get("facets") or {}
    problems: list[str] = []
    seen: set[str] = set()
    out: dict[str, list[dict]] = {}
    for biome, rows in table.items():
        out[biome] = []
        for row in rows or []:
            fid = str(row.get("id", ""))
            if not re.fullmatch(r"[a-z][a-z0-9_]*", fid):
                problems.append(f"facets.yaml: id «{fid}» ({biome}) не snake_case")
            if fid in seen:
                problems.append(f"facets.yaml: id «{fid}» встречается дважды")
            seen.add(fid)
            name = str(row.get("name") or "")
            if not name:
                problems.append(f"facets.yaml: у «{fid}» нет имени")
            elif len(name) > FACET_NAME_LIMIT:
                problems.append(
                    f"facets.yaml: имя «{name}» длиннее {FACET_NAME_LIMIT} знаков — не ляжет подписью"
                )
            if not isinstance(row.get("share"), (int, float)):
                problems.append(f"facets.yaml: у «{fid}» нет доли share")
            for key in ("vein_k", "reach_k", "swing_k"):
                if not isinstance(row.get(key), (int, float)) or float(row[key]) <= 0:
                    problems.append(f"facets.yaml: у «{fid}» нет положительного {key}")
            where = row.get("where") or {}
            for axis in FACET_AXES:
                span = where.get(axis)
                if (
                    not isinstance(span, list)
                    or len(span) != 2
                    or not all(isinstance(v, (int, float)) for v in span)
                    or not 0 <= span[0] < span[1] <= 1
                ):
                    problems.append(f"facets.yaml: у «{fid}» ось {axis} не отрезок внутри 0…1")
            marks = row.get("marks") or {}
            for mark in ("woods", "stones", "meadow"):
                share = marks.get(mark)
                if not isinstance(share, (int, float)) or not 0 <= float(share) <= FACET_SHARE_FULL:
                    problems.append(f"facets.yaml: у «{fid}» метка {mark} не доля 0…100")
            out[biome].append(row)
        total = sum(float(row.get("share") or 0) for row in out[biome])
        if out[biome] and round(total, 3) != FACET_SHARE_FULL:
            problems.append(f"facets.yaml: доли биома «{biome}» дают {total:g}, а не 100")
    return out, problems


#: Имя фацета ложится подписью на карту (словарь 10-world/08).
FACET_NAME_LIMIT = 18
#: Доли фацетов биома в сумме, и потолок доли метки, в процентах.
FACET_SHARE_FULL = 100
FACET_AXES = ("slope", "wet", "high")


def check_facets(constants: dict, facets: dict[str, list[dict]]) -> list[str]:
    """Фацеты стоят под биомами реестра, и у каждого биома они есть: узел
    биома без фацетов остался бы без лица (план §6)."""
    if not facets:
        return []
    names = constants.get("biome.names") or {}
    problems = [
        f"facets.yaml: биом «{biome}», которого нет в biome.names"
        for biome in facets
        if biome not in names
    ]
    problems += [
        f"biome.names: у биома «{biome}» нет ни одного фацета в facets.yaml"
        for biome in names
        if not facets.get(biome)
    ]
    axes = constants.get("biome.facet_axes") or {}
    problems += [
        f"biome.facet_axes: нет положительной оси {axis}"
        for axis in ("wave_m", "slope_full", "wet_km", "patch_km", "soft_edge", "favour_k")
        if not isinstance(axes.get(axis), (int, float)) or float(axes[axis]) <= 0
    ]
    return problems


def load_provinces() -> tuple[dict[str, list[dict]], list[str]]:
    """`data/provinces.yaml`: планета -> строки провинций (план ландшафта §7).

    Проверяется то, что ломает сборку поля или имя на карте: id в snake_case
    и единственный на весь вольт, имя, числа сдвигов. Файла может не быть —
    тогда провинций нет, и это законно до волны 3.
    """
    path = DATA / "provinces.yaml"
    if not path.exists():
        return {}, []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    table = doc.get("provinces") or {}
    problems: list[str] = []
    seen: set[str] = set()
    out: dict[str, list[dict]] = {}
    for planet, rows in table.items():
        out[planet] = []
        for row in rows or []:
            pid = str(row.get("id", ""))
            if not re.fullmatch(r"[a-z][a-z0-9_]*", pid):
                problems.append(f"provinces.yaml: id «{pid}» ({planet}) не snake_case")
            if pid in seen:
                problems.append(f"provinces.yaml: id «{pid}» встречается дважды")
            seen.add(pid)
            if not row.get("name"):
                problems.append(f"provinces.yaml: у «{pid}» нет имени")
            for key in ("rain_shift", "temp_shift_c", "vein_k"):
                if not isinstance(row.get(key), (int, float)):
                    problems.append(f"provinces.yaml: у «{pid}» нет числа {key}")
            if not isinstance(row.get("favours") or [], list):
                problems.append(f"provinces.yaml: `favours` у «{pid}» не список")
            out[planet].append(row)
    return out, problems


def check_favours(provinces: dict[str, list[dict]], facets: dict[str, list[dict]]) -> list[str]:
    """`favours` провинции называет фацеты, которые здесь чаще обычного
    (план §7, волна 8): ключа, которого нет в `facets.yaml`, быть не может —
    он бы молча ничего не делал."""
    known = {str(row.get("id")) for rows in facets.values() for row in rows or []}
    if not known:
        return []
    return [
        f"provinces.yaml: «{row['id']}» любит фацет «{fid}», которого нет в facets.yaml"
        for rows in provinces.values()
        for row in rows or []
        for fid in (row.get("favours") or [])
        if str(fid) not in known
    ]


def build_renames(
    recipes_doc: dict,
    vocabulary: dict,
    plants: list[dict] = (),
    locales: dict[str, dict] | None = None,
    code_laws: list[dict] = (),
    provinces: dict[str, list[dict]] | None = None,
    facets: dict[str, list[dict]] | None = None,
    biomes: dict[str, str] | None = None,
) -> dict:
    """build/renames.json — таблица соответствий «русское имя -> id».

    Единственный источник для миграции базы (волна II), скрипта переименования
    тестов и переходных синонимов движка. `names_ru` — обратные карты: по ним
    клиент и APS показывают русское имя, пока локалей ещё нет (волна III).
    """
    #: .get и фильтр: пропуск id — проблема из check_ids, здесь не роняем.
    goods: dict[str, str] = dict(seed_ids(plants))
    for material in recipes_doc["meta"].get("materials", []):
        if material.get("id"):
            goods[material["name"]] = material["id"]
    for _, _, recipe in all_recipes(recipes_doc):
        if recipe.get("id"):
            goods[recipe["name"]] = recipe["id"]
    out: dict[str, dict] = {
        "goods": goods,
        "classes": {
            c["name"]: c["id"]
            for c in recipes_doc["meta"].get("classes", [])
            if c.get("id")
        },
        "operations": {
            op["name"]: op["id"]
            for op in recipes_doc["operations"]
            if op.get("id")
        },
    }
    #: Культуры (D-057): у сорта своё имя, и оно показывается игроку —
    #: «Полба», а не `spelt`. Отдельный домен, а не товары: продукт культуры
    #: («Зерно») и сама культура — разные вещи с разными именами.
    out["plants"] = {
        plant["name"]: plant["id"] for plant in plants if plant.get("id") and plant.get("name")
    }
    #: Дикий предок (D-260): свой сорт — своё имя, id выводится из id культуры.
    out["plants"].update({
        plant["wild_name"]: f"{plant['id']}_wild"
        for plant in plants
        if plant.get("id") and plant.get("wild_name")
    })
    #: Код-законы: у закона есть имя показа («Налог с продажи»), и по проводу
    #: оно ездит ключом, как всякое имя вольта. Домен свой: ключи законов
    #: короткие и общего вида (`access`, `salary`, `toll`), и общая с товарами
    #: таблица однажды молча отдала бы одно вместо другого.
    out["laws"] = {
        law["name"]: law["id"] for law in code_laws if law.get("id") and law.get("name")
    }
    for domain, rows in vocabulary.items():
        out[domain] = {row["name"]: row["id"] for row in rows or []}
    #: Провинции (план ландшафта §7): имя области на карте и в сводке едет
    #: ключом, как всякое имя вольта; свой домен, потому что «Рудный кряж» —
    #: не товар и не закон.
    out["provinces"] = {
        row["name"]: row["id"]
        for rows in (provinces or {}).values()
        for row in rows
        if row.get("id") and row.get("name")
    }
    #: Фацеты (план ландшафта §6): имя грани биома на карте и в окне узла.
    #: Свой домен рядом с провинциями — «Опушка» не товар и не область.
    out["facets"] = {
        row["name"]: row["id"]
        for rows in (facets or {}).values()
        for row in rows
        if row.get("id") and row.get("name")
    }
    #: Биомы (дополнение к D-331): слово биома в легенде карты и о найденном
    #: узле. Само слово живёт константой `biome.names` (D-321), домен здесь —
    #: чтобы у него был второй язык: клиент читал константу и по-английски
    #: показывал «Тайга».
    out["biomes"] = {name: bid for bid, name in (biomes or {}).items() if bid and name}
    out["names_ru"] = {
        domain: {v: k for k, v in table.items()} for domain, table in out.items()
    }
    #: Поля код-закона — единица и пояснение — только в именах, не в карте
    #: переименований: по ним не мигрируют, и обратная карта «текст -> id»
    #: схлопнула бы одинаковые значения («ТК» стоит единицей у трёх законов).
    #: Закон без единицы в домен не попадает — и второго языка с него не
    #: требуют.
    #: Написанный абзац культуры (D-311): не имя, а текст, и потому — только в
    #: именах, как пояснение код-закона. Культура без абзаца в домен не
    #: попадает, и второго языка с неё не требуют.
    out["names_ru"]["plant_care"] = {
        plant["id"]: plant["care_note"]
        for plant in plants
        if plant.get("id") and plant.get("care_note")
    }
    out["names_ru"]["law_units"] = {
        law["id"]: law["unit"] for law in code_laws if law.get("id") and law.get("unit")
    }
    out["names_ru"]["law_notes"] = {
        law["id"]: law["note"] for law in code_laws if law.get("id") and law.get("note")
    }
    #: Вариант выбора у код-закона: ключ едет по проводу, слово живёт здесь.
    #: Ключ домена составной — «закон.вариант», — потому что `citizens` стоит
    #: вариантом у двух законов сразу и по-русски читается по-разному:
    #: «гражданам» печатает город, «граждане» занимают участки.
    out["names_ru"]["law_options"] = {
        f"{law['id']}.{option['id']}": option["label"]
        for law in code_laws
        for option in (law.get("options") or [])
        if law.get("id") and option.get("id") and option.get("label")
    }
    #: Второй язык и дальше — оверлеем по id, а не обращением карты имён:
    #: у русского имя первично и id выведен из него, у остальных наоборот.
    for lang, overlay in sorted((locales or {}).items()):
        out[f"names_{lang}"] = {
            domain: dict(table) for domain, table in sorted(overlay.items())
        }
    return out


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


#: Каталоги, которых в вольте как бы нет: рабочее дерево git внутри вольта —
#: это второй его экземпляр, и обход документов находил в нём всё по второму
#: разу. Индекс статусов удваивался, а проверка ссылок печатала шесть десятков
#: повторов поверх настоящих пяти проблем — то есть переставала что-либо
#: значить. Обход по всему корню сам по себе верен: вольт и есть корень.
NOT_THE_VAULT = (".claude/", ".git/", ".venv/", "node_modules/")


def documents():
    """Документы вольта: все `*.md`, кроме лежащих в чужой копии."""
    for path in sorted(ROOT.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(NOT_THE_VAULT):
            continue
        yield path, rel



#: Реестры, по которым сверяются названные записи. Журнал — единственный
#: источник решений, два файла вопросов — единственный источник вопросов.
DECISION_LOG = "90-production/02-decision-log.md"
QUESTION_REGISTRIES = ("00-core/02-open-questions.md", "00-core/04-closed-questions.md")

#: Ссылка одного документа на другой: [текст](путь.md), при желании с якорем.
#: Внешние адреса пропускаются — `(?!\w+:)` отсекает `https:` и прочие схемы:
#: живость чужого сайта вольту не проверить, да и не его это дело. Проверяется
#: только `.md`: ссылок на `data/*.yaml` и `tools/*.py` в вольте три десятка,
#: все живые, и звать их сюда — отдельная работа со своими краями (цель вне
#: вольта, звёздочка в пути); граница названа тут нарочно, чтобы её не искали.
DOC_LINK = re.compile(r"\]\((?!\w+:)([^)#\s]+\.md)(?:#[^)]*)?\)")
DECISION_REF = re.compile(r"\bD-\d+\b")
QUESTION_REF = re.compile(r"\bOQ-\d+\b")
#: Огороженный блок и код-спан: то, что в них написано, — пример, а не ссылка.
#: Абзац, объясняющий эту самую семью, привёл в спане `[текст](путь.md)` — и
#: единственным живым предупреждением уровня, заведённого ради читаемых
#: предупреждений, оказалось ложное, в его же документации.
FENCED = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
CODE_SPAN = re.compile(r"`[^`\n]*`")
#: Вопросы, снятые до того, как завёлся реестр закрытых: журнал называет их
#: по праву — это архив, и переписать историю ради зелёной проверки нельзя.
#: Списком, а не вычерком всего журнала: в нём номера решений ссылаются друг
#: на друга сотнями раз, и опечатка `D-137`→`D-173` уводит в чужое решение.
ARCHIVED_QUESTIONS = frozenset({"OQ-020", "OQ-021", "OQ-027", "OQ-102"})


def prose(text: str) -> str:
    """Текст без кода: пример в кавычках — не ссылка и не номер решения."""
    return CODE_SPAN.sub(" ", FENCED.sub(" ", text))


def vault_pages():
    """Документы, за которые вольт отвечает содержанием.

    Отсеивается только то, что вольт не писал: настройки Obsidian и кеш
    pytest. Всё остальное — да, включая README, CLAUDE.md и README редактора:
    последний называет три десятка решений и ссылается на те же документы, и
    исключать его значило бы не проверять файл, где номера решений встречаются
    чаще, чем где-либо после журнала.

    Статусов это не касается — там свой, более узкий список: у README
    инструмента статуса нет и быть не должно (см. `statuses`).
    """
    for path, rel in documents():
        if rel.startswith((".obsidian/", ".pytest_cache/")):
            continue
        yield path, rel


def check_doc_links() -> list[str]:
    """Ссылка одного документа на другой обязана вести в живой файл.

    Предупреждение, а не проблема: движок документов не читает, и битая
    ссылка не ломает ни сборку, ни игру. Ломает она другое — чтение вольта, а
    вольт затем и существует, чтобы его читали. Переименованный документ
    оставляет за собой десяток ссылок в никуда, и находит их сегодня только
    тот, кто по ним пошёл.
    """
    problems: list[str] = []
    for path, rel in vault_pages():
        gone = sorted(
            {
                target
                for target in DOC_LINK.findall(prose(path.read_text(encoding="utf-8")))
                if not (path.parent / target).exists()
            }
        )
        if gone:
            problems.append(f"{rel} — {', '.join(gone)}")
    return problems


def known_records() -> tuple[set[str], set[str]]:
    """Что вольт объявил: решения журнала и вопросы обоих реестров."""
    #: Отсутствующий реестр — не повод ронять сборку трейсбеком: семья эта
    #: текстовая, и переименованный файл найдётся проверкой ссылок словами.
    #: Тот же приём, что у `named_socket_keys`.
    def read(name: str) -> str:
        path = ROOT / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    decisions = set(re.findall(r"^### (D-\d+)", read(DECISION_LOG), re.MULTILINE))
    questions: set[str] = set()
    for name in QUESTION_REGISTRIES:
        questions |= set(re.findall(r"\|\s*(OQ-\d+)\s*\|", read(name)))
    return decisions, questions


def check_named_records() -> list[str]:
    """Названное решение и названный вопрос обязаны существовать.

    «D-137» и «OQ-104» — несущие ссылки: по ним ходят и человек, и следующая
    сессия. Опечатка в номере ведёт в чужое решение, а номер, взятый заранее и
    не записанный, — в пустоту; и то и другое молча, потому что номер выглядит
    ссылкой независимо от того, есть ли за ним запись.

    Журнал решений из проверки исключён, и по той же причине, по какой он
    исключён из сверки констант: это архив. Он законно называет вопросы,
    снятые до того, как завёлся реестр закрытых, — OQ-020, OQ-021, OQ-027
    сняты решением, OQ-102 «закрыт вопросом, а не ответом».
    """
    decisions, questions = known_records()
    problems: list[str] = []
    for path, rel in vault_pages():
        text = prose(path.read_text(encoding="utf-8"))
        #: Журнал прощается только вопросам, и только названным поимённо:
        #: решения в нём проверяются наравне со всеми.
        excused = ARCHIVED_QUESTIONS if rel == DECISION_LOG else frozenset()
        gone = sorted(set(DECISION_REF.findall(text)) - decisions)
        gone += sorted(set(QUESTION_REF.findall(text)) - questions - excused)
        if gone:
            problems.append(f"{rel} — {', '.join(gone)}")
    return problems


def check_statuses() -> list[str]:
    """У документа обязан быть статус, и притом один из шести.

    Статус — контракт синхронизации: «реализовано» обязывает совпадать с
    кодом, «идея» не обязывает ни к чему. Документ без него выпадает из этого
    контракта целиком — сверять его не с чем, и незаметно: индекс статусов
    собирает такие в отдельный список внизу, куда никто не смотрит.
    """
    _, unknown = statuses()
    return [f"{rel} — {title}" for rel, title in unknown]


def statuses() -> tuple[dict[str, list[tuple[str, str]]], list[tuple[str, str]]]:
    """Статус каждого документа по его собственной шапке: узнанные и нет.

    Одним ходом для двух читателей — индекса, который их печатает, и проверки,
    которая ругается на неузнанные. Два обхода разошлись бы на первой же
    правке списка исключений.
    """
    found: dict[str, list[tuple[str, str]]] = {s: [] for s in STATUS_ORDER}
    unknown: list[tuple[str, str]] = []

    for path, rel in vault_pages():
        # Служебные документы корня и README редактора статуса не имеют и в
        # индексе не нужны: они не про игру, а про то, как с репозиторием и с
        # инструментом обращаться.
        if rel.startswith(("build/", "templates/", "editor/")) or rel in (
            "README.md", "CLAUDE.md", "MEMORY.md", "CLA.md", "CONTENT-LICENSE.md"
        ):
            continue
        if rel == "90-production/03-status.md":
            continue
        # Двенадцать строк, а не шесть: над заголовком документа стоит ещё
        # комментарий с лицензией (tools/spdx.py), и в шести строках шапка
        # «> **Статус:**» помещалась впритык — у сгенерированных не помещалась вовсе.
        head = path.read_text(encoding="utf-8").split("\n", 12)[:12]
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
    return found, unknown


def build_status_index() -> str:
    found, unknown = statuses()
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

#: Заголовок для каждой семьи предупреждений: их группируют по нему, а не
#: по тексту находки. Семья известна на месте вызова, и знать её там дешевле,
#: чем разбирать потом готовую строку.
REFS_GONE = "документ ссылается на снятую константу"
LINKS_DEAD = "ссылка ведёт в никуда"
RECORDS_UNKNOWN = "названо решение или вопрос, которого нет"
STATUS_MISSING = "документ без распознанного статуса"
FIELD_STALE = "поле планеты собрано под другие числа"

def check_zonal(constants: dict) -> list[str]:
    """`biome.zonal` покрывает плоскость без дыр и без наложений (план §5):
    точка без класса — узел без биома, точка с двумя — порядок строк
    становится той же ложью, что порядок веток `if`. Нижний край строки
    входит, верхний — нет, кроме верхнего края плоскости. Плоскость —
    шкала `site.rain_range` и температуры от самого холодного края строк
    до самого тёплого; строки обязаны дотянуться до `site.temp_range` с
    запасом вниз на высоту, глубину материка и местный шум — столько
    поле отнимает у холодного края (`tools/field/climate.py`). Ключи
    `biome.azonal` — формы конвейера (`tools/field/forms.py`), пока
    таблица форм живёт в коде."""
    table = constants.get("biome.zonal")
    if not isinstance(table, dict):
        return []
    names = constants.get("biome.names") or {}
    problems: list[str] = []
    rows = []
    for label, row in table.items():
        try:
            biome = str(row["biome"])
            t0, t1 = (float(v) for v in row["temp"])
            r0, r1 = (float(v) for v in row["rain"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"biome.zonal: строка «{label}» не {{biome, temp: [a, b], rain: [a, b]}}")
            continue
        if biome not in names:
            problems.append(f"biome.zonal: «{label}» называет биом «{biome}», которого нет в biome.names")
        if t0 >= t1 or r0 >= r1:
            problems.append(f"biome.zonal: у «{label}» пустой прямоугольник")
        rows.append((label, t0, t1, r0, r1))
    from field import forms  # noqa: PLC0415 -- сборка не зависит от конвейера иначе

    known_forms = {key for key, _, _ in forms.FORMS}
    for form, biome in (constants.get("biome.azonal") or {}).items():
        if biome not in names:
            problems.append(f"biome.azonal: форма «{form}» ведёт в биом «{biome}», которого нет в biome.names")
        if form not in known_forms:
            problems.append(f"biome.azonal: формы «{form}» нет в таблице форм конвейера")
    if problems or not rows:
        return problems
    rain_range = constants.get("site.rain_range") or {}
    rain_lo, rain_hi = int(rain_range.get("min", 0)), int(rain_range.get("max", 100))
    temp_lo, temp_hi = int(min(r[1] for r in rows)), int(max(r[2] for r in rows))
    margin = sum(float(constants.get(key) or 0.0) for key in ("terrain.lapse_c", "terrain.continental_c", "terrain.climate_noise_c"))
    #: Края — **самой холодной и самой жаркой планеты**, а не шкалы узла. Пока
    #: пара краёв была одна на четыре мира, `site.temp_range` и была этой
    #: мерой; с D-329 у каждой планеты своя, и таблица, дотянутая до Терры,
    #: молча прижимала Пироксис при +120 °C к жаркому поясу — то есть растила
    #: на нём саванну. Проверка обязана мерить то же, что мерит поле.
    ends = constants.get("terrain.temp_range") or {"terra": constants.get("site.temp_range") or {}}
    coldest = min(float((one or {}).get("min", 0.0)) for one in ends.values())
    hottest = max(float((one or {}).get("max", 0.0)) for one in ends.values())
    if temp_lo > coldest - margin:
        problems.append(f"biome.zonal: холодный край строк {temp_lo} °C, а поле опускается до {coldest - margin:.0f} °C")
    if temp_hi < hottest:
        problems.append(f"biome.zonal: тёплый край строк {temp_hi} °C, а поле поднимается до {hottest:.0f} °C")
    gaps: list[str] = []
    overlaps: list[str] = []
    for t in range(temp_lo, temp_hi + 1):
        for r in range(rain_lo, rain_hi + 1):
            hits = [
                label
                for label, t0, t1, r0, r1 in rows
                if (t0 <= t < t1 or (t == temp_hi and t1 >= t))
                and (r0 <= r < r1 or (r == rain_hi and r1 >= r))
            ]
            if not hits and len(gaps) < 5:
                gaps.append(f"{t} °C, осадки {r}")
            if len(hits) > 1 and len(overlaps) < 5:
                overlaps.append(f"{t} °C, осадки {r}: {', '.join(hits)}")
    if gaps:
        problems.append("biome.zonal: без класса — " + "; ".join(gaps) + " …")
    if overlaps:
        problems.append("biome.zonal: два класса — " + "; ".join(overlaps) + " …")
    return problems


def check_field_freshness(constants: dict) -> list[str]:
    """Поле в `build/field/` — производное реестра (план ландшафта §4.8): его
    паспорт несёт хеш параметров, и поле, собранное под другие зерно, шаг или
    уровень моря, обманет и картинку, и движок.

    **Проблема, а не предупреждение.** Предупреждением это стояло, пока поле
    в игру не приезжало: ломалась одна линейка. Теперь движок сверяет паспорт
    сам и **отказывается поднимать планету** (`field._check_passport`,
    `FieldStale`), и разойтись стороны могут только так: вольт говорит
    «проверка прошла», а сервер не встаёт. Ровно это и случилось 2026-09-11 —
    `terrain.version` подняли до 8, три планеты остались седьмой версии, и
    двадцать девять тестов покраснели при зелёной сборке вольта.

    Без numpy — молчит: сборка без него обходится."""
    field_dir = BUILD / "field"
    if not field_dir.exists():
        return []
    try:
        from field.pipeline import Params  # noqa: PLC0415 -- только при наличии поля
    except ImportError:
        return []
    found = []
    #: Строки провинций входят в хеш (план §7): без них реестр «давал» другой
    #: хеш каждой планете с провинциями, и предупреждение не гасло никогда.
    provinces, _ = load_provinces()
    for passport in sorted(field_dir.glob("*.json")):
        planet = passport.stem
        try:
            meta = json.loads(passport.read_text(encoding="utf-8"))
            expected = Params.from_constants(constants, planet, provinces.get(planet)).digest()
        except (KeyError, ValueError, TypeError) as why:
            found.append(
                f"{planet}: паспорт не читается ({why}); "
                f"пересобери: python tools/landscape.py build --planet {planet}"
            )
            continue
        if meta.get("digest") != expected:
            found.append(
                f"{planet}: в паспорте {meta.get('digest')}, реестр даёт {expected}; "
                f"пересобери: python tools/landscape.py build --planet {planet}"
            )
    return found


def by_kind(found: list[tuple[str, str]]) -> list[tuple[str, list[str]]]:
    """Находки по семьям, в порядке первого появления семьи."""
    out: dict[str, list[str]] = {}
    for kind, text in found:
        out.setdefault(kind, []).append(text)
    return list(out.items())


def verdict(problems: list, warnings: list, strict: bool) -> tuple[str, int]:
    """Последнее слово проверки и код возврата: что сказать и чем выйти.

    Отдельной функцией потому, что это и есть весь новый контракт: чем
    проверка падает, а чем только говорит. Спрятанное в `main` правило
    проверить нечем — а проверять его надо, потому что менять его будут.
    """
    if problems:
        return "проверка нашла новые проблемы", 1
    if warnings and strict:
        return f"предупреждений {len(warnings)} — с --strict это отказ", 1
    if warnings:
        return f"проверка чистая; предупреждений {len(warnings)}", 0
    return "проверка чистая", 0


def main() -> int:
    check_only = "--check" in sys.argv
    masses_only = "--masses" in sys.argv
    #: Уровней три, а не два, и делит их один вопрос: что сломается.
    #:
    #: **Проблема** ломает игру или сборку — её читает движок: неизвестный
    #: вход, круг в лестнице, имя без перевода, вес больше вошедшей материи.
    #: Такая роняет проверку.
    #:
    #: **Предупреждение** значит, что вольт разошёлся сам с собой: документ
    #: обещает число, которого в реестре уже нет. Обманет оно читателя, а не
    #: движок — документов он не читает. Ронять этим сборку значит приучать
    #: на неё не смотреть: на 2026-09-08 таких строк было четырнадцать из
    #: пятнадцати, проверка была красной всегда, и красной её перестали
    #: читать — ровно то, о чём предупреждает докстринг `tools/tests/test_refs`.
    #: Кому нужна прежняя строгость — `--strict`.
    #:
    #: **Известное** — расхождение, за которым стоит открытый вопрос: решение
    #: ещё не принято, и чинить нечего, пока его нет.
    strict = "--strict" in sys.argv
    if strict and not check_only:
        #: Строгость — про вердикт, а вердикт выносит только `--check`: сборка
        #: пишет файлы и выходит нулём даже с проблемами. Молча проглоченный
        #: флаг строгости хуже отсутствующего, поэтому отказ, а не совет.
        print("--strict имеет смысл только с --check: сборка вердикта не выносит",
              file=sys.stderr)
        return 2

    # Реестр материалов читается первым: из него наполняются таблицы констант
    recipes_doc, registry_problems = load_recipes_doc()
    constants_md, constants_doc, constant_problems = build_constants(recipes_doc)
    recipes_md, recipes_doc, amounts, op_amounts, labor, steps, mass, qty_problems = (
        build_recipes(constants_doc, recipes_doc)
    )

    # Отчёт о массах: что вывелось из входов и что вес себе отстояло (D-228).
    # Ничего не пишет — вес и так выводится каждой сборкой, а показать надо
    # именно переопределённое: оно молча остаётся при старом числе.
    if masses_only:
        for line in mass_report(recipes_doc, amounts, mass):
            print(line)
        if qty_problems:
            print()
            print(f"Проблемы ({len(qty_problems)}):", file=sys.stderr)
            for problem in qty_problems:
                print(f"  · {problem}", file=sys.stderr)
        return 1 if qty_problems else 0
    harvest_rates = flatten_constants(constants_doc).get("harvest.rates", {})
    plants_md, plants, plant_problems = build_plants(constants_doc, recipes_doc)
    laws_md, laws_doc = build_laws()
    problems = registry_problems + constant_problems
    fresh, known_problems = check_recipes(recipes_doc)
    problems += fresh
    problems += check_compositions(
        recipes_doc, amounts, flatten_constants(constants_doc).get("craft.amount_cap", 10)
    )
    problems += qty_problems
    problems += plant_problems
    problems += check_laws(laws_doc)
    #: Уровень предупреждений — про **вольт как текст**: сюда идёт всё, что
    #: обманет читателя и не тронет игру. Семей четыре, и разъезжаются они
    #: по-разному, но чинятся одинаково — строкой в документе.
    warnings = [(REFS_GONE, one) for one in check_constant_refs(constants_doc)]
    warnings += [(LINKS_DEAD, one) for one in check_doc_links()]
    warnings += [(RECORDS_UNKNOWN, one) for one in check_named_records()]
    warnings += [(STATUS_MISSING, one) for one in check_statuses()]
    #: Поле под другими числами — отказ движка, а не кривая картинка:
    #: сверяется он тем же хешем и планету не поднимает.
    problems += [
        f"{FIELD_STALE}: {one}"
        for one in check_field_freshness(flatten_constants(constants_doc))
    ]
    problems += check_building_types(constants_doc, recipes_doc)
    problems += check_biome_figure(constants_doc)
    problems += check_class_tables(constants_doc, recipes_doc)
    world_doc = worldfile.load_world_doc()
    problems += worldfile.check_world(world_doc, recipes_doc, all_recipes)
    #: Зазор между узлами: обещание движка, которого прибитый пин не
    #: касается (`seed_world._pinned` кладёт узел, куда сказано). Числа
    #: для этого — радиус земли планеты и `map.min_gap_m`, оба из реестра.
    problems += worldfile.check_spacing(world_doc, flatten_constants(constants_doc))
    vocabulary = load_vocabulary()
    problems += check_ids(recipes_doc, vocabulary, constants_doc, world_doc, plants)
    provinces_doc, province_problems = load_provinces()
    problems += province_problems
    facets_doc, facet_problems = load_facets()
    problems += facet_problems
    problems += check_facets(flatten_constants(constants_doc), facets_doc)
    problems += check_favours(provinces_doc, facets_doc)
    problems += check_zonal(flatten_constants(constants_doc))
    #: Полнота второго языка (волна V). Проверяется здесь, а не в движке:
    #: имена — данные вольта, и язык с дырой должен ронять сборку вольта, а не
    #: показывать игроку `iron_ore` в готовой игре.
    locales = load_locales()
    problems += check_locales(
        build_renames(
            recipes_doc, vocabulary, plants, code_laws=laws_doc["code_laws"],
            provinces=provinces_doc,
            facets=facets_doc,
            biomes=flatten_constants(constants_doc).get("biome.names", {}),
        ),
        locales,
    )
    problems, excused_problems = excuse_known(problems, recipes_doc)
    known_problems += excused_problems

    if problems:
        print(f"НОВЫЕ проблемы ({len(problems)}):", file=sys.stderr)
        for p in problems:
            print(f"  · {p}", file=sys.stderr)
        print(file=sys.stderr)

    if warnings:
        print(f"Предупреждения ({len(warnings)}) — вольт расходится сам с собой;"
              " игру это не ломает:")
        for kind, items in by_kind(warnings):
            print(f"  {kind} ({len(items)}):")
            for item in items:
                print(f"    · {item}")
        print()

    if known_problems:
        print(f"Известные расхождения, ждут решения по открытому вопросу ({len(known_problems)}):")
        for p in known_problems:
            print(f"  · {p}")
        print()

    if check_only:
        said, code = verdict(problems, warnings, strict)
        print(said)
        return code

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
            # Классы вещей (D-215): класс -> члены. Поведение движка привязано
            # к классу, а не к имени. tool_classes — производное представление
            # (классы, целиком состоящие из инструментов) для клиента
            "classes": recipes_doc["meta"].get("classes_map", {}),
            # Устойчивые ключи классов (D-251): класс -> id. Члены в "classes"
            # остаются именами — движок волны I читает их как читал
            "class_ids": {
                c["name"]: c["id"]
                for c in recipes_doc["meta"].get("classes", [])
                if c.get("id")
            },
            "tool_classes": recipes_doc["meta"].get("tool_classes", {}),
            # Реестр материалов (D-215): всё, что не делается рецептом, одной
            # записью — класс, масса, весовое, съедобность, темп, находка, топливо
            "materials": [
                {
                    "name": m["name"],
                    # устойчивый ключ (D-251): будущая идентичность вещи.
                    # .get: пропуск id — проблема из check_ids, а не трейсбек
                    # посреди записи build/ (полусобранное состояние хуже)
                    "id": m.get("id"),
                    "class": m.get("class"),
                    "mass": m.get("mass", 0.0),
                    "bulk": bool(m.get("bulk")),
                    "edible": bool(m.get("edible")),
                    "rate": m.get("rate"),
                    "forage": m.get("forage"),
                    # Реликвия (D-232): вещь Предтеч, которую нашли, а не
                    # сделали. Не снимается, не разбирается, не поднимается
                    "relic": bool(m.get("relic")),
                    "fuel": m.get("fuel"),
                }
                for m in recipes_doc["meta"].get("materials", [])
            ],
            "operations": [
                {
                    "name": op["name"],
                    "id": op.get("id"),
                    "requires": op["requires"],
                    "gives": op["gives"],
                    # класс, которым перечень выходов был задан (пусто — задан
                    # перечнем). Новый материал класса попадает сюда сборкой
                    "gives_class": op.get("gives_class"),
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
            # жидкости (D-230): только в таре с `holds: жидкость`
            "liquid": sorted(recipes_doc["meta"].get("liquid", [])),
            # сбросной газ (D-340): не найдя тары, выпускается в пустоту или
            # сжигается в факеле узла, а в воздух не выходит никогда
            "vent": recipes_doc["meta"].get("vent", []),
            # слоты снаряжения: в каждый надевается одна вещь (D-146)
            "gear_slots": recipes_doc["meta"].get("gear_slots", []),
            # масса единицы, кг. Задана данными: см. compute_mass. Семена
            # культур добавляются отдельно: они описаны в plants.yaml, а не
            # рецептом, и без этого проходили бы мимо предела носимого (D-146)
            "mass": {
                k: round(v, ROUND_MASS)
                for k, v in sorted(with_seed_mass(mass, plants, constants_doc).items())
            },
            "labor_hours": {k: round(v, 3) for k, v in sorted(labor.items())},
            # Собственное время шага на единицу, часов: раньше движок и
            # редактор восстанавливали его вычитанием труда входов из
            # labor_hours — две копии одной формулы (D-215)
            "step_hours": {k: round(v, 4) for k, v in sorted(steps.items())},
            "recipes": [
                {
                    "name": r["name"],
                    "id": r.get("id"),
                    "level": lvl["id"],
                    "section": sec["id"] if sec else None,
                    "kind": r.get("kind", "material"),
                    # класс вещи (D-215): поведение движка привязано к нему
                    "class": r.get("class"),
                    "key": bool(r.get("key")),
                    # строится на месте (D-268): не берётся в руки, а выход
                    # партии встаёт на пол сразу
                    "built": bool(r.get("built")),
                    # на электричестве (D-269): ручная партия берёт ток из
                    # сети или из аккумуляторов рядом, без питания стоит
                    "powered": bool(r.get("powered")),
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
                    # что принимает как хранилище (D-230): `жидкость` — тара,
                    # и только жидкости; пусто — всё, кроме жидкостей
                    "holds": r.get("holds"),
                    "inputs": r["inputs"],
                    "amounts": amounts.get(r["name"], {}),
                    "manual_amounts": bool(r.get("amounts")),
                    # побочный выход на единицу главного (D-340): водород
                    # электролиза. Пусто — у партии один выход
                    "byproduct": {
                        k: float(v) for k, v in (r.get("byproduct") or {}).items()
                    },
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
    write(BUILD / "plants.json", json.dumps(
        {
            "plants": [
                # seed_id (D-251): семя — товар, его ключ выводится из id
                # культуры. Добавочно: прочие поля как были
                {**plant, "seed_id": f"{plant['id']}_seeds"}
                for plant in plants
            ]
        },
        ensure_ascii=False, indent=2) + chr(10))
    write(ROOT / "40-society" / "07-law-catalog.md",
          GENERATED_WARNING.format(src="data/laws.yaml") + laws_md)
    write(BUILD / "laws.json", json.dumps(
        {k: laws_doc[k] for k in ("charter", "code_laws", "sanctions")},
        ensure_ascii=False, indent=2) + "\n")
    write(BUILD / "world.json",
          json.dumps(worldfile.build_world(world_doc), ensure_ascii=False, indent=2) + "\n")
    write(BUILD / "renames.json",
          json.dumps(build_renames(recipes_doc, vocabulary, plants, locales,
                                   code_laws=laws_doc["code_laws"],
                                   provinces=provinces_doc, facets=facets_doc,
                                   biomes=flatten_constants(constants_doc).get("biome.names", {})),
                     ensure_ascii=False, indent=2) + "\n")
    #: Провинции (план ландшафта §7): конвейер поля читает отсюда, сколько
    #: областей резать на планете и чем каждая сдвигает климат.
    write(BUILD / "provinces.json",
          json.dumps(provinces_doc, ensure_ascii=False, indent=2) + "\n")
    write(BUILD / "facets.json",
          json.dumps({"facets": facets_doc}, ensure_ascii=False, indent=2) + "\n")
    write(ROOT / "90-production" / "03-status.md", build_status_index())

    print("собрано:")
    for w in written:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
