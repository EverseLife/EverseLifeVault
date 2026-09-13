# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Сбросной газ (D-340): признак вещи и два его инварианта.

`vent` бывает только у жидкости, и жидкий побочный выход рецепта обязан его
нести: иначе то, что не вошло в тару, партии некуда деть, кроме пола, а
жидкость на полу не живёт (D-230).
"""

from __future__ import annotations

import build


def vault(gas: dict, *, byproduct: bool = True) -> dict:
    """Один газ в реестре материалов и рецепт, который его даёт побочным выходом."""
    recipe = {"name": "Кислород", "kind": "material", "liquid": True, "inputs": ["Вода"]}
    if byproduct:
        recipe["byproduct"] = {gas["name"]: 2}
    return {
        "meta": {
            "classes": [{"name": "Жидкость", "id": "liquid"}],
            "materials": [
                {"name": "Вода", "class": "Жидкость", "mass": 0.2, "liquid": True},
                {"class": "Жидкость", "mass": 0.125, **gas},
            ],
        },
        "operations": [],
        "levels": [{"id": "1", "recipes": [recipe]}],
    }


def test_a_liquid_vent_byproduct_is_listed():
    doc = vault({"name": "Водород", "liquid": True, "vent": True})
    problems = build.normalize_recipes(doc)
    assert problems == []
    assert doc["meta"]["vent"] == ["Водород"]


def test_a_liquid_byproduct_that_is_not_vent_fails_the_build():
    problems = build.normalize_recipes(vault({"name": "Водород", "liquid": True}))
    assert any("обязан быть сбросным газом" in one for one in problems)


def test_vent_is_only_for_a_liquid():
    problems = build.normalize_recipes(
        vault({"name": "Сажа", "vent": True}, byproduct=False)
    )
    assert any("бывает только у жидкости" in one for one in problems)
