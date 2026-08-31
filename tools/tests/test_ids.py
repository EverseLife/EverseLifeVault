# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Устойчивые ключи (D-251): у каждого имени — ровно один id.

Правило трёхчастное: ключ обязателен, он snake_case ASCII, и он уникален в
своём пространстве (товары, классы, операции — раздельно; словари
vocabulary.yaml — каждый своё). Совпадение МЕЖДУ пространствами законно:
класс «Топор» и рецепт «Топор» делят один ключ. Таблица renames — единственный
источник соответствий для миграции волны II, и её обратные карты обязаны
сходиться с прямыми.
"""

from __future__ import annotations

import build


def doc(materials=(), recipes=(), classes=(), operations=(), gear_slots=()) -> dict:
    return {
        "meta": {
            "classes": list(classes),
            "materials": list(materials),
            "gear_slots": list(gear_slots),
        },
        "operations": list(operations),
        "levels": [{"id": 1, "recipes": list(recipes)}],
    }


EMPTY_CONSTANTS = {"groups": []}
EMPTY_WORLD: dict = {"nodes": []}
#: Виртуальные станции существуют в любом вольте (VIRTUAL_STATIONS в сборке),
#: и покрытие требует их объявления даже в синтетическом документе.
BASE_VOCAB = {"virtual_stations": [{"name": name, "id": "by_hand"}
                                   for name in sorted(build.VIRTUAL_STATIONS)]}


def problems(recipes_doc, vocabulary=None) -> list[str]:
    return build.check_ids(
        recipes_doc, {**BASE_VOCAB, **(vocabulary or {})}, EMPTY_CONSTANTS, EMPTY_WORLD
    )


def test_a_thing_without_an_id_is_reported():
    found = problems(doc(materials=[{"name": "Алмаз"}]))
    assert any("Алмаз" in p and "D-251" in p for p in found)


def test_a_non_snake_case_id_is_reported():
    for bad in ("Diamond", "алмаз", "1diamond", "dia-mond"):
        found = problems(doc(materials=[{"name": "Алмаз", "id": bad}]))
        assert any("snake_case" in p for p in found), bad


def test_a_good_id_passes():
    assert problems(doc(materials=[{"name": "Алмаз", "id": "diamond"}])) == []


def test_a_name_cannot_be_both_material_and_recipe():
    """renames собирает товары по имени: одно имя на двоих молча перезаписало
    бы таблицу миграции, поэтому дизъюнктность пришпилена проверкой."""
    found = problems(doc(
        materials=[{"name": "Алмаз", "id": "diamond"}],
        recipes=[{"name": "Алмаз", "id": "cut_diamond"}],
    ))
    assert any("и материал, и рецепт" in p for p in found)


def test_a_name_listed_twice_is_reported():
    found = problems(doc(materials=[
        {"name": "Алмаз", "id": "diamond"},
        {"name": "Алмаз", "id": "diamond_again"},
    ]))
    assert any("больше одного раза" in p for p in found)


def test_goods_share_one_namespace():
    """Материал и рецепт — одно пространство товаров: один ключ на двоих — ошибка."""
    found = problems(doc(
        materials=[{"name": "Алмаз", "id": "diamond"}],
        recipes=[{"name": "Огранённый алмаз", "id": "diamond"}],
    ))
    assert any("занят" in p for p in found)


def test_namespaces_do_not_collide():
    """Класс «Топор» и рецепт «Топор» делят ключ axe — это законно."""
    found = problems(doc(
        classes=[{"name": "Топор", "id": "axe"}],
        recipes=[{"name": "Топор", "id": "axe"}],
    ))
    assert found == []


def test_a_used_word_must_be_declared_in_vocabulary():
    found = problems(doc(gear_slots=["спина"]))
    assert any("спина" in p and "slots" in p for p in found)
    clean = problems(
        doc(gear_slots=["спина"]),
        vocabulary={"slots": [{"name": "спина", "id": "back"}]},
    )
    assert clean == []


def test_renames_carries_every_namespace_and_its_inverse():
    recipes_doc = doc(
        materials=[{"name": "Алмаз", "id": "diamond"}],
        recipes=[{"name": "Кольцо", "id": "ring"}],
        classes=[{"name": "Украшение", "id": "jewelry"}],
        operations=[{"name": "Огранка", "id": "cutting"}],
    )
    vocabulary = {"slots": [{"name": "спина", "id": "back"}]}
    renames = build.build_renames(recipes_doc, vocabulary)
    assert renames["goods"] == {"Алмаз": "diamond", "Кольцо": "ring"}
    assert renames["classes"] == {"Украшение": "jewelry"}
    assert renames["operations"] == {"Огранка": "cutting"}
    assert renames["slots"] == {"спина": "back"}
    for domain, table in renames.items():
        if domain == "names_ru":
            continue
        assert renames["names_ru"][domain] == {v: k for k, v in table.items()}


def test_seed_ids_derive_from_the_plant_and_share_the_goods_namespace():
    plants = [{"id": "spelt", "seed": "Семена полбы"}]
    renames = build.build_renames(
        doc(materials=[{"name": "Зерно", "id": "grain"}]), {}, plants,
    )
    assert renames["goods"]["Семена полбы"] == "spelt_seeds"
    taken = problems(
        doc(materials=[{"name": "Не семя", "id": "spelt_seeds"}]),
    )
    assert taken == [], "без культур коллизии нет"
    clash = build.check_ids(
        doc(materials=[{"name": "Не семя", "id": "spelt_seeds"}]),
        BASE_VOCAB, EMPTY_CONSTANTS, EMPTY_WORLD, plants,
    )
    assert any("занят" in p for p in clash)


def test_the_real_vault_is_fully_keyed():
    """Не правило, а данные: живой вольт обязан проходить собственную проверку.

    Дубль `--check` намеренно точечный: тест падает на первом же новом имени
    без ключа, не дожидаясь CI.
    """
    recipes_doc, _ = build.load_recipes_doc()
    constants_docs = build.yaml.safe_load(
        (build.DATA / "constants.yaml").read_text(encoding="utf-8")
    )
    world_doc = build.yaml.safe_load(
        (build.DATA / "world.yaml").read_text(encoding="utf-8")
    )
    found = build.check_ids(
        recipes_doc, build.load_vocabulary(), constants_docs, world_doc
    )
    assert found == []
