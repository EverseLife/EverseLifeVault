# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Известные расхождения (known_issues), общая форма `{problem, oq}`.

Запись извиняет проблему по её началу — слово в слово, как печатает сборка, —
и подписывает её номером открытого вопроса. Всё, что записью не покрыто,
остаётся свежей проблемой и роняет `--check`.
"""

from __future__ import annotations

import build

ISSUES = {"known_issues": [
    {"problem": "тупик: материал «Алмаз» никуда не идёт", "oq": "OQ-900"},
]}


def test_a_recorded_problem_is_excused_and_signed():
    fresh, known = build.excuse_known(
        ["тупик: материал «Алмаз» никуда не идёт — либо он расходник, либо не хватает рецепта"],
        ISSUES,
    )
    assert fresh == []
    assert known == [
        "тупик: материал «Алмаз» никуда не идёт — либо он расходник, "
        "либо не хватает рецепта  [OQ-900]"
    ]


def test_an_unrecorded_problem_stays_fresh():
    fresh, known = build.excuse_known(
        ["тупик: материал «Рубин» никуда не идёт — либо он расходник, либо не хватает рецепта"],
        ISSUES,
    )
    assert known == []
    assert len(fresh) == 1 and "Рубин" in fresh[0]


def test_cycle_entries_are_not_this_form():
    """Запись про цикл живёт в check_recipes: здесь она никого не извиняет."""
    fresh, known = build.excuse_known(
        ["тупик: материал «Алмаз» никуда не идёт"],
        {"known_issues": [{"cycle": ["А", "Б"], "oq": "OQ-901"}]},
    )
    assert known == [] and len(fresh) == 1
