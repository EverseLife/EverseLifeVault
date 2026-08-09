"""Сборка вольта: данные -> документы + артефакты для движка.

    python tools/build.py           собрать всё, показать предупреждения
    python tools/build.py --check   только проверить, ничего не писать; код возврата 1 при проблемах

Что делает:
  1. Читает data/constants.yaml и data/recipes.yaml — единственные источники чисел и рецептов
  2. Проверяет лестницу рецептов: циклы, тупики, неизвестные входы и станки
  3. Рендерит templates/*.tmpl -> готовые документы вольта
  4. Пишет build/constants.json и build/recipes.json — их читает движок
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

# Станки, которых нет и не должно быть в списке рецептов
VIRTUAL_STATIONS = {"Руками", "Стройка"}
# Разговорное название станка -> рецепт, которым он делается
STATION_ALIASES = {"Печь": "Плавильная печь"}

PREFIX_UNITS = {"×", "±", "до +", "до "}

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
        else:  # карта модификаторов
            return " · ".join(f"{k} ×{val}" for k, val in v.items())
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


def render_recipe_table(recipes: list[dict]) -> str:
    show_station = any(r.get("station") != "Руками" for r in recipes)
    head = ["| Рецепт | Входы |", "|---|---|"]
    if show_station:
        head = ["| Рецепт | Входы | Станок |", "|---|---|---|"]

    rows = list(head)
    for r in recipes:
        name = r["name"]
        kind = r.get("kind")
        if kind in ("station", "building", "key"):
            name = f"**{name}**"
        if kind == "station":
            name += " *(станок)*"
        elif kind == "building":
            name += " *(постройка)*"

        hl = set(r.get("highlight", []))
        inputs = ", ".join(
            f"**{x}**" if i in hl else x
            for n, i in enumerate(r["inputs"])
            for x in [i if n == 0 else lower_first(i)]
        )

        cells = [name, inputs] + ([r.get("station", "—")] if show_station else [])
        if r.get("note"):
            cells[-1] += f" *({r['note']})*"
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def render_operations(doc: dict) -> str:
    rows = ["| Операция | Требует | Даёт |", "|---|---|---|"]
    for op in doc["operations"]:
        req = ", ".join(q if n == 0 else lower_first(q) for n, q in enumerate(op["requires"]))
        gives = ", ".join(g if n == 0 else lower_first(g) for n, g in enumerate(op["gives"]))
        rows.append(f"| {op['name']} | {req} | {gives} |")
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

    # 1. неизвестные входы и станки
    for name, r in recipes.items():
        for i in r["inputs"]:
            if canon(i) not in known:
                problems.append(f"«{name}»: вход «{i}» не рецепт, не сырьё и не продукт операции")
        st = r.get("station")
        if st and canon(st) not in known:
            problems.append(f"«{name}»: станок «{st}» ничем не делается")
    for op in doc["operations"]:
        for q in op["requires"]:
            if canon(q) not in known:
                problems.append(f"операция «{op['name']}»: требует «{q}», которого никто не делает")

    # 2. проходимость: можно ли собрать всё, начав с голого сырья.
    #    Заодно ловит любой цикл — зацикленное просто никогда не откроется.
    available = set(raw)
    while True:
        grew = False
        for op in doc["operations"]:
            if all(any(o in available for o in options(q)) for q in op["requires"]):
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
        else:  # продукт операции: заблокирован её инструментом
            for op in doc["operations"]:
                if name in op["gives"]:
                    for q in op["requires"]:
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

    # 3. тупики. Станки и постройки освобождены: они и есть назначение.
    consumed = {canon(i) for r in recipes.values() for i in r["inputs"]}
    for op in doc["operations"]:
        for q in op["requires"]:
            consumed.update(options(q))
    used_as_station = set()
    for r in recipes.values():
        if r.get("station"):
            used_as_station.update(options(r["station"]))
    terminal = set(doc.get("terminal", []))
    for name, r in recipes.items():
        if r.get("kind") in ("station", "building"):
            continue
        if name in consumed or name in used_as_station or name in terminal:
            continue
        problems.append(f"тупик: «{name}» никуда не идёт и не помечен как конечный (terminal)")

    # 4. мусор в terminal
    for name in sorted(terminal - set(recipes) - raw - op_outputs):
        problems.append(f"в terminal перечислено «{name}», но такого рецепта нет")

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


def build_recipes() -> tuple[str, dict]:
    doc = yaml.safe_load((DATA / "recipes.yaml").read_text(encoding="utf-8"))
    levels = {str(l["id"]): l for l in doc["levels"]}

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
                return render_operations(doc)
            if what == "totals":
                return render_totals(doc)
            if what == "cut_candidates":
                return ", ".join(doc["cut_candidates"]).lower()
            if what == "level":
                return render_recipe_table(levels[parts[2]]["recipes"])
            if what == "section":
                return render_recipe_table(section_of(parts[2], parts[3])["recipes"])
        if kind == "count":
            if parts[1] == "operations":
                return str(len(doc["operations"]))
            if len(parts) == 3:
                return str(len(section_of(parts[1], parts[2])["recipes"]))
            return str(level_count(levels[parts[1]]))
        raise KeyError(f"неизвестный плейсхолдер {{{{{token}}}}}")

    tmpl = (TEMPLATES / "recipes-mvp.md.tmpl").read_text(encoding="utf-8")
    return render_template(tmpl, resolve), doc


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
        if rel.startswith((".obsidian/", "build/", "templates/")) or rel in ("README.md", "CLAUDE.md", "MEMORY.md"):
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
    recipes_md, recipes_doc = build_recipes()
    problems, known_problems = check_recipes(recipes_doc)

    if known_problems:
        print(f"Известные расхождения, ждут решения по открытому вопросу ({len(known_problems)}):")
        for p in known_problems:
            print(f"  · {p}")
        print()

    if problems:
        print(f"НОВЫЕ проблемы в лестнице рецептов ({len(problems)}):", file=sys.stderr)
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
            "operations": recipes_doc["operations"],
            "raw": recipes_doc["meta"]["raw"],
            "recipes": [
                {
                    "name": r["name"],
                    "level": lvl["id"],
                    "section": sec["id"] if sec else None,
                    "kind": r.get("kind", "item"),
                    "inputs": r["inputs"],
                    "station": r.get("station"),
                }
                for lvl, sec, r in all_recipes(recipes_doc)
            ],
        },
        ensure_ascii=False, indent=2) + "\n")
    write(ROOT / "90-production" / "03-status.md", build_status_index())

    print("собрано:")
    for w in written:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
