# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Вес изделия выводится из входов (D-228).

Правило короткое, но у него три ветки — выведенное, заданное руками и
умолчание по типу, — и ошибка в любой из них стоит целой лестницы: вес
умножается вверх, и кривое число внизу двигает всё, что из него делается.
"""

from __future__ import annotations

import build


def constants(by_kind: dict | None = None) -> dict:
    """Реестр из одной величины: массы по типу — всё, что нужно расчёту."""
    return {
        "groups": [
            {
                "id": "inventory",
                "constants": [
                    {
                        "key": "inventory.mass_by_kind",
                        "value": by_kind if by_kind is not None else {"tool": 3, "material": 1},
                    }
                ],
            }
        ]
    }


def vault(*recipes: dict, materials: dict | None = None) -> dict:
    """Лестница в один уровень: рецепты подряд, сырьё — картой имя → масса."""
    return {
        "meta": {"mass": materials if materials is not None else {"Руда": 0.2}},
        "levels": [{"id": "1", "recipes": list(recipes)}],
    }


def test_mass_is_what_went_in():
    doc = vault({"name": "Слиток", "kind": "material", "inputs": ["Руда"]})
    mass, problems = build.compute_mass(doc, constants(), {}, {"Слиток": {"Руда": 3}})
    assert problems == []
    assert mass["Слиток"] == 0.6


def test_mass_climbs_the_ladder():
    """Вес идёт снизу вверх: сырьё → полуфабрикат → вещь."""
    doc = vault(
        {"name": "Слиток", "kind": "material", "inputs": ["Руда"]},
        {"name": "Кирка", "kind": "tool", "inputs": ["Слиток"]},
    )
    amounts = {"Слиток": {"Руда": 3}, "Кирка": {"Слиток": 2}}
    mass, problems = build.compute_mass(doc, constants(), {}, amounts)
    assert problems == []
    assert mass["Кирка"] == 1.2


def test_authored_mass_wins_over_the_count():
    """Заданное руками не пересчитывается: монета весит грамм, чего бы ни стоила."""
    doc = vault({"name": "Монета", "kind": "money", "mass": 0.001, "inputs": ["Руда"]})
    mass, problems = build.compute_mass(doc, constants(), {}, {"Монета": {"Руда": 3}})
    assert problems == []
    assert mass["Монета"] == 0.001


def test_authored_mass_above_the_matter_is_a_problem():
    """Материя при переделе не появляется (D-215): вещь тяжелее вошедшего — ошибка."""
    doc = vault({"name": "Кирка", "kind": "tool", "mass": 5, "inputs": ["Руда"]})
    mass, problems = build.compute_mass(doc, constants(), {}, {"Кирка": {"Руда": 3}})
    assert len(problems) == 1
    assert "больше вошедшей материи" in problems[0]
    assert mass["Кирка"] == 0.6


def test_kind_default_is_the_last_resort():
    """Входы ничего не весят — остаётся умолчание по типу, но не ноль."""
    doc = vault(
        {"name": "Кирка", "kind": "tool", "inputs": ["Энергия"]},
        materials={"Энергия": 0},
    )
    mass, problems = build.compute_mass(doc, constants(), {}, {"Кирка": {"Энергия": 5}})
    assert problems == []
    assert mass["Кирка"] == 3


def test_no_inputs_and_no_default_is_a_problem():
    doc = vault({"name": "Кирка", "kind": "tool", "inputs": []}, materials={})
    _, problems = build.compute_mass(doc, constants(by_kind={}), {}, {})
    assert len(problems) == 1
    assert "массы нет" in problems[0]


def test_the_weightless_is_named_once_however_many_use_it():
    """Жалоба на вещь — про вещь, а не про каждого, кто её потребляет."""
    doc = vault(
        {"name": "Пустышка", "kind": "material", "inputs": []},
        {"name": "Первый", "kind": "material", "inputs": ["Пустышка"]},
        {"name": "Второй", "kind": "material", "inputs": ["Пустышка"]},
        materials={},
    )
    amounts = {"Первый": {"Пустышка": 1}, "Второй": {"Пустышка": 1}}
    _, problems = build.compute_mass(doc, constants(by_kind={}), {}, amounts)
    assert len([problem for problem in problems if "Пустышка" in problem]) == 1


def test_operation_output_without_mass_is_a_problem():
    """Продукт операции берётся из мира: его вес обязан быть в реестре."""
    doc = vault(materials={})
    _, problems = build.compute_mass(doc, constants(), {"Щебень": {}}, {})
    assert len(problems) == 1
    assert "продукт операции без массы" in problems[0]


def test_a_circle_does_not_hang_the_count():
    """Круг ловит другая проверка; здесь он не должен уводить в бесконечность."""
    doc = vault(
        {"name": "Гвозди", "kind": "material", "inputs": ["Верстак"]},
        {"name": "Верстак", "kind": "station", "inputs": ["Гвозди"]},
    )
    amounts = {"Гвозди": {"Верстак": 1}, "Верстак": {"Гвозди": 10}}
    mass, _ = build.compute_mass(doc, constants({"material": 1, "station": 60}), {}, amounts)
    #: Какое именно число выйдет из круга, смысла не имеет — важно, что расчёт
    #: возвращается и отдаёт конечный вес обоим.
    assert mass["Гвозди"] == mass["Гвозди"] < float("inf")
    assert mass["Верстак"] == mass["Верстак"] < float("inf")


def test_report_names_the_pinned_and_the_counted():
    doc = vault(
        {"name": "Слиток", "kind": "material", "inputs": ["Руда"]},
        {"name": "Монета", "kind": "money", "mass": 0.001, "inputs": ["Руда"]},
    )
    amounts = {"Слиток": {"Руда": 3}, "Монета": {"Руда": 3}}
    mass, _ = build.compute_mass(doc, constants(), {}, amounts)
    report = "\n".join(build.mass_report(doc, amounts, mass))
    assert "выведено из входов — 1, задано вручную — 1" in report
    assert "· Слиток — 0.6 кг" in report
    assert "переопределён" in report
    assert "· Монета — задано 0.001 кг, из входов вышло бы 0.6 кг" in report
