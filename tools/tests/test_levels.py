# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Три уровня проверки: чем она падает, а чем только говорит.

Уровней стало три 2026-09-08, и повод был простой. Проверка находила
пятнадцать проблем, четырнадцать из них — расхождение **текста** с реестром:
документ называет константу, которую решением убрали. Движок документов не
читает, ломаться от такого нечему, а проверка была красной всегда — и,
красная всегда, перестала что-либо значить. Ровно об этом предупреждает
докстринг соседнего `test_refs`: «незелёную проверку перестают читать».

Поэтому: **проблема** роняет проверку, **предупреждение** говорит и не роняет,
**известное** ждёт решения по открытому вопросу. Что чем считается — решение,
а не мелочь реализации, и меняться оно будет; тесты здесь ровно для того,
чтобы менялось оно осознанно.
"""

from __future__ import annotations

import build


def test_a_problem_fails_the_check():
    said, code = build.verdict(["масса больше вошедшей материи"], [], strict=False)
    assert code == 1
    assert "проблемы" in said


def test_a_warning_speaks_and_does_not_fail():
    """Главное утверждение всей правки, и обратное ему держалось два месяца."""
    said, code = build.verdict([], [(build.REFS_GONE, "10-world/02-terra.md — map.nodes_terra")],
                               strict=False)
    assert code == 0
    assert "чистая" in said
    #: Молчать о нём тоже нельзя: расхождение живо, и счёт его видно.
    assert "1" in said


def test_strict_makes_a_warning_a_refusal():
    """Строгость не потеряна, а вынесена под флаг: CI вправе её включить."""
    _, code = build.verdict([], [(build.REFS_GONE, "что-то")], strict=True)
    assert code == 1


def test_a_problem_outranks_a_warning():
    said, code = build.verdict(["настоящая беда"], [(build.REFS_GONE, "мелочь")], strict=False)
    assert code == 1
    assert "предупрежд" not in said


def test_nothing_found_says_so_plainly():
    assert build.verdict([], [], strict=False) == ("проверка чистая", 0)


def test_findings_of_one_kind_come_together():
    """Пятнадцать строк подряд читать нельзя, а пять заголовков — можно."""
    grouped = build.by_kind([
        ("ссылки", "a.md — x"),
        ("веса", "«Лист» тяжелее состава"),
        ("ссылки", "b.md — y, z"),
    ])
    assert grouped == [
        ("ссылки", ["a.md — x", "b.md — y, z"]),
        ("веса", ["«Лист» тяжелее состава"]),
    ]


def test_the_order_of_kinds_is_the_order_they_were_found_in():
    """Не алфавит: первым читают то, что нашлось первым."""
    assert [kind for kind, _ in build.by_kind([("я", "1"), ("а", "2"), ("я", "3")])] == ["я", "а"]


def test_one_document_gives_one_line_however_many_names_it_dropped(monkeypatch, tmp_path):
    """План карты называл девять снятых констант — девятью строками.

    Девять строк об одном файле — это не девять находок, а одна, и читать её
    надо один раз. Проверка группировала бы их и сама, но заголовок семьи
    вместе с перечислением внутри строки короче вдвое.
    """
    page = tmp_path / "plan.md"
    page.write_text("`map.draw` и `map.drawn`, а ещё `craft.time_per_unit`", encoding="utf-8")
    monkeypatch.setattr(build, "documents", lambda: [(page, "90-production/plan.md")])
    monkeypatch.setattr(build, "flatten_constants", lambda _doc: {"craft.time_per_unit": 1, "map.x": 1})
    monkeypatch.setattr(build, "named_socket_keys", set)

    assert build.check_constant_refs({}) == ["90-production/plan.md — map.draw, map.drawn"]
