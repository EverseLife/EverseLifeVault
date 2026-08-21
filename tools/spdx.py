# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Заголовок лицензии в каждом файле вольта: проверить или проставить.

    python tools/spdx.py            # проверка — её гоняет CI
    python tools/spdx.py --apply    # проставить недостающее
    python tools/spdx.py --list     # что покрыто и по какой политике

В вольте две лицензии, и это не небрежность, а устройство проекта:

* **код** (`tools/`, `editor/`) — под AGPL-3.0-only, как движок;
* **содержимое** (документы гейм-дизайна, `data/*.yaml`, шаблоны) — все права
  защищены, см. `CONTENT-LICENSE.md`.

Числа, рецепты и законы — это то, ради чего покупают коммерческую лицензию, и
свободной лицензии на них нет. Заголовок в файле нужен именно поэтому: документ,
уехавший из репозитория, увозит ответ с собой, а `LICENSE` в корне не уезжает.

Простановка идемпотентна и никогда не встаёт впереди того, что обязано идти
первым: шебанга, доктайпа, BOM. Файл с чужим копирайтом не трогается вовсе.
Сгенерированное (`build/*.json`, документы с пометкой сборщика) пропускается:
заголовок там ставит `tools/build.py`, иначе следующая сборка его затрёт.
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

HOLDER = "Nurlan Urazkulov"
CODE = "AGPL-3.0-only"
#: Своя лицензия по правилам SPDX для нестандартных: см. CONTENT-LICENSE.md.
CONTENT = "LicenseRef-EverseLife-Content"

SPDX = re.compile(r"SPDX-License-Identifier:\s*(\S+)")
#: Год — файла, а не сегодняшний: проверка на текущий год превращала бы каждый
#: январь в диф по всему репозиторию.
COPYRIGHT = re.compile(r"Copyright \(C\) \d{4} " + re.escape(HOLDER))

#: Что под какой лицензией. Шаблоны — для `git ls-files`, поэтому ничего
#: неотслеживаемого и ничего игнорируемого сюда не попадает.
POLICIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("код", CODE, (
        "tools/*.py",
        "editor/*.py",
        "editor/static/*.js",
        "editor/static/*.css",
        "editor/static/*.html",
    )),
    ("содержимое", CONTENT, (
        "*.md",
        "data/*.yaml",
        "templates/*.tmpl",
    )),
]

#: Что не помечается и почему. Спорный файл дописывается сюда, а не спорит с
#: проверкой.
EXCLUDED = (
    "build/",  # собирается tools/build.py; в JSON нет комментариев
    ".obsidian/",  # настройки Obsidian, не наши
    ".github/",  # конфигурация, не исходник
    "LICENSE",
    "CONTENT-LICENSE.md",
    "CLA.md",
)

#: Пометка сборщика первой строкой документа.
GENERATED_MARK = "СГЕНЕРИРОВАНО"

#: Документы, которые собираются кодом и пометки не несут. Списком, а не по
#: статусу в шапке: шаблоны несут ту же шапку, что и документ из них, и по
#: статусу неотличимы — а шаблон как раз пометить надо, его заголовок и уезжает
#: в готовый документ. Появится новый сгенерированный — проверка скажет, и он
#: дописывается сюда.
GENERATED_FILES = (
    "90-production/03-status.md",
    "90-production/04-simulation.md",
)

#: Как язык пишет комментарий. Заголовок вставляется целыми строками.
STYLES: dict[str, list[str]] = {
    ".py": ["# {spdx}", "# {copy}"],
    ".yaml": ["# {spdx}", "# {copy}"],
    ".js": ["// {spdx}", "// {copy}"],
    ".css": ["/* {spdx}", "   {copy} */"],
    ".html": ["<!--", "{spdx}", "{copy}", "-->"],
    #: В документах и шаблонах — HTML-комментарий: в Obsidian и на GitHub он не
    #: виден, а в тексте стоит первым.
    ".md": ["<!-- {spdx}", "     {copy} -->"],
    ".tmpl": ["<!-- {spdx}", "     {copy} -->"],
}

BOM = "﻿"
#: Глубже этого заголовком уже не считается, и файл, цитирующий строку в теле,
#: проверку не пройдёт.
HEAD_LINES = 15


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(out.stdout.strip())


def tracked(root: Path, patterns: tuple[str, ...]) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", *patterns], capture_output=True, text=True, check=True, cwd=root
    )
    return [line for line in out.stdout.splitlines() if line]


def covered(root: Path) -> dict[str, str]:
    """`{путь: ожидаемый идентификатор}`. Код выигрывает у содержимого."""

    found: dict[str, str] = {}
    for _, identifier, patterns in reversed(POLICIES):
        for name in tracked(root, patterns):
            if name.startswith(EXCLUDED) or name in EXCLUDED:
                continue
            if Path(name).suffix not in STYLES:
                continue
            found[name] = identifier
    return dict(sorted(found.items()))


def split_keepends(text: str) -> list[str]:
    """Резать только по переводам строк — `splitlines` рвёт ещё и по подаче формы."""

    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def verdict(root: Path, name: str, expected: str) -> str:
    """`ok` | `missing` | `foreign` | `generated` | `wrong:<что стоит>`."""

    text = (root / name).read_bytes().decode("utf-8").removeprefix(BOM)
    head = "\n".join(text.splitlines()[:HEAD_LINES])
    if name in GENERATED_FILES or GENERATED_MARK in head.split("\n")[0]:
        return "generated"
    found = SPDX.search(head)
    if found and COPYRIGHT.search(head):
        return "ok" if found.group(1) == expected else "wrong:" + found.group(1)
    if "Copyright" in head and HOLDER not in head:
        return "foreign"
    return "missing"


def stamp(path: Path, identifier: str, year: int) -> None:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    bom = ""
    if text.startswith(BOM):
        bom, text = BOM, text[1:]

    #: Перевод строки — тот, что уже в файле, иначе в нём заведётся два вида
    #: сразу и диф будет про переводы строк, а не про лицензию.
    crlf = raw.count(b"\r\n")
    newline = "\r\n" if crlf > raw.count(b"\n") - crlf else "\n"

    lines = split_keepends(text)
    #: Что обязано остаться первой строкой: шебанг или доктайп.
    at = 0
    if lines and (lines[0].startswith("#!") or lines[0].lstrip().lower().startswith("<!doctype")):
        at = 1

    header = [
        line.format(
            spdx="SPDX-License-Identifier: " + identifier,
            copy="Copyright (C) {} {}".format(year, HOLDER),
        )
        + newline
        for line in STYLES[path.suffix]
    ]
    #: Пустая строка между заголовком и текстом, если её там ещё нет.
    if at < len(lines) and lines[at].strip():
        header.append(newline)

    path.write_bytes((bom + "".join(lines[:at] + header + lines[at:])).encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="проставить недостающее")
    parser.add_argument("--list", action="store_true", help="показать покрытие")
    args = parser.parse_args()

    root = repo_root()
    files = covered(root)

    if args.list:
        for name, identifier in files.items():
            print(f"{identifier:<32} {name}")
        print(f"\nвсего {len(files)}; не помечается: {', '.join(EXCLUDED)}", file=sys.stderr)
        return 0

    missing, wrong, foreign, generated = [], [], [], []
    for name, identifier in files.items():
        answer = verdict(root, name, identifier)
        if answer == "missing":
            missing.append((name, identifier))
        elif answer.startswith("wrong:"):
            wrong.append((name, identifier, answer.split(":", 1)[1]))
        elif answer == "foreign":
            foreign.append(name)
        elif answer == "generated":
            generated.append(name)

    for name in foreign:
        print(f"spdx: {name} — чужой копирайт, не трогаем")
    for name in generated:
        print(f"spdx: {name} — собирается tools/build.py, заголовок ставит он")

    #: Неверный идентификатор — не то же, что его отсутствие: файл переехал
    #: между политиками, и это решение человека, а не скрипта.
    if wrong:
        print(f"\nspdx: не тот идентификатор в {len(wrong)} файлах:", file=sys.stderr)
        for name, expected, actual in wrong:
            print(f"  {name}: стоит {actual}, ожидается {expected}", file=sys.stderr)
        print("\nspdx: поправить руками или перенести файл в tools/spdx.py", file=sys.stderr)
        return 1

    if not missing:
        print(f"spdx: заголовок на месте, {len(files)} файлов")
        return 0

    if args.apply:
        year = datetime.date.today().year
        for name, identifier in missing:
            stamp(root / name, identifier, year)
        print(f"spdx: заголовок добавлен в {len(missing)} файлов")
        return 0

    print(f"\nspdx: нет заголовка лицензии в {len(missing)} файлах:", file=sys.stderr)
    for name, identifier in missing:
        print(f"  {identifier:<32} {name}", file=sys.stderr)
    print("\nspdx: чинится командой `python tools/spdx.py --apply`", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
