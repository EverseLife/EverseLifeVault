# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Ссылка на константу в тексте: что проверяется, а что нет (D-065).

Имя с точкой в обратных кавычках бывает четырёх родов, и только один из них —
величина. Проверка обязана ловить опечатку в живом имени и обязана молчать про
три остальных: имя файла, чужое пространство и ключ сокета. Молчание тут не
поблажка, а условие: заругавшись на команду, проверка перестаёт быть зелёной,
а незелёную проверку перестают читать.
"""

from __future__ import annotations

import build

KNOWN = {"craft.time_per_unit", "ship.ascent_hours", "coin.default_fineness"}
NAMESPACES = {key.split(".", 1)[0] for key in KNOWN}
SOCKET = {"ship.orbit", "mining.swing"}


def missing(key: str) -> bool:
    return build.missing_constant(key, KNOWN, NAMESPACES, SOCKET)


def test_a_named_constant_is_not_a_problem():
    assert not missing("craft.time_per_unit")


def test_a_typo_inside_a_live_namespace_is_caught():
    """То, ради чего проверка существует: обещание величины, которой нет."""
    assert missing("craft.time_per_unitt")


def test_a_constant_removed_by_decision_is_caught():
    """Обратная ошибка: ключ убрали из реестра, а текст его всё ещё называет."""
    assert missing("coin.gold_per_coin")


def test_a_file_name_is_not_a_constant():
    assert not missing("recipes.json")
    assert not missing("plants.yaml")


def test_a_foreign_namespace_is_not_checked():
    """`everse.life` — домен, а не величина, и таких имён в текстах много."""
    assert not missing("everse.life")


def test_a_socket_key_is_not_a_constant():
    """Приказ рулевому живёт в протоколе сессии, а не в реестре величин.

    Пространство у него общее с реестром — `ship.ascent_hours` рядом настоящая
    константа, — так что отсеять его по пространству нельзя, только по имени.
    """
    assert not missing("ship.orbit")
    assert missing("ship.orbitt"), "опечатка в приказе — не ключ и не величина"


def test_the_keys_are_read_from_the_protocol_itself():
    """Список не пишется руками: новая команда приезжает со своей записью."""
    assert build.socket_keys(
        "Команда `ship.orbit` в ответ шлёт `ship.view`, событие — `mining.swing`."
    ) == {"ship.orbit", "ship.view", "mining.swing"}


def test_the_real_protocol_names_the_ship_orders():
    """Связь с настоящим документом: без неё правило верно, но ни к чему не привязано."""
    assert {"ship.orbit", "ship.cancel"} <= build.named_socket_keys()
