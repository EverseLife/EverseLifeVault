# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Вольт как текст: ссылки, названные записи, статусы.

Три семьи предупреждений (D-325 завёл уровень, эти три его населили). Общее у
них одно: движок про них не знает и сломаться от них не может — ломается
чтение. А вольт затем и написан, чтобы его читали, и все три расходятся
**молча**: переименованный документ оставляет ссылки в никуда, номер решения
выглядит ссылкой независимо от того, есть ли за ним запись, а документ без
статуса выпадает из контракта синхронизации целиком.

Проверки ходят по настоящему дереву, поэтому здесь у каждой своё маленькое:
тест на живом вольте проверял бы не правило, а сегодняшнее состояние текстов.
"""

from __future__ import annotations

from pathlib import Path

import build


def pages(tmp_path: Path, files: dict[str, str]) -> list[tuple[Path, str]]:
    """Крошечный вольт на диске и обход по нему, как его отдаёт `documents`."""
    out = []
    #: В порядке имени, как отдаёт настоящий `documents`: порядок находок —
    #: часть ответа, и подделка, отдающая их вразнобой, проверяла бы не то.
    for rel, text in sorted(files.items()):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        out.append((path, rel))
    return out


# --- ссылки ------------------------------------------------------------------


def test_a_link_to_a_missing_document_is_found(monkeypatch, tmp_path: Path) -> None:
    """То, ради чего проверка есть: документ переименовали, ссылки остались."""
    walk = pages(tmp_path, {
        "10-world/01-a.md": "см. [Б](02-b.md) и [В](../20-systems/03-c.md)",
        "10-world/02-b.md": "я на месте",
    })
    monkeypatch.setattr(build, "documents", lambda: walk)
    assert build.check_doc_links() == ["10-world/01-a.md — ../20-systems/03-c.md"]


def test_a_live_link_with_an_anchor_is_not_a_finding(monkeypatch, tmp_path: Path) -> None:
    """Якорь — часть ссылки, а не часть имени файла."""
    walk = pages(tmp_path, {
        "a.md": "[к разделу](b.md#заголовок)",
        "b.md": "# заголовок",
    })
    monkeypatch.setattr(build, "documents", lambda: walk)
    assert build.check_doc_links() == []


def test_an_outside_address_is_not_checked(monkeypatch, tmp_path: Path) -> None:
    """Живость чужого сайта вольту не проверить, и не его это дело."""
    walk = pages(tmp_path, {"a.md": "[CLA](https://example.invalid/blob/main/CLA.md)"})
    monkeypatch.setattr(build, "documents", lambda: walk)
    assert build.check_doc_links() == []


def test_only_what_the_vault_did_not_write_is_spared(monkeypatch, tmp_path: Path) -> None:
    """Отсеивается не «служебное», а чужое: настройки Obsidian и кеш pytest.

    README редактора отсеивать нельзя, хотя соблазн был: это документ вольта
    про вольт, и решений он называет три десятка — больше, чем любой файл
    после журнала. Исключив его, проверка не смотрела бы туда, где ссылок
    гуще всего.
    """
    walk = pages(tmp_path, {
        ".pytest_cache/README.md": "[нет](никуда.md)",
        ".obsidian/notes.md": "[нет](никуда.md)",
        "editor/README.md": "[нет](никуда.md)",
    })
    monkeypatch.setattr(build, "documents", lambda: walk)
    assert build.check_doc_links() == ["editor/README.md — никуда.md"]


# --- названные решения и вопросы ---------------------------------------------


def test_a_decision_or_question_that_does_not_exist_is_found(monkeypatch, tmp_path: Path) -> None:
    """Номер выглядит ссылкой, есть за ним запись или нет.

    Оба рода в одной строке: читателю важен документ, а не то, спутали в нём
    решение или вопрос.
    """
    walk = pages(tmp_path, {"20-systems/01-x.md": "стоит на D-007 и D-999, закрывает OQ-042"})
    monkeypatch.setattr(build, "documents", lambda: walk)
    monkeypatch.setattr(build, "known_records", lambda: ({"D-007"}, {"OQ-104"}))
    assert build.check_named_records() == ["20-systems/01-x.md — D-999, OQ-042"]


def test_the_log_is_forgiven_four_questions_and_not_its_decisions(
    monkeypatch, tmp_path: Path
) -> None:
    """Журнал — архив, но прощение у него поимённое и только вопросам.

    Он законно называет вопросы, снятые до того, как завёлся реестр закрытых:
    OQ-020, OQ-021 и OQ-027 сняты решением, OQ-102 «закрыт вопросом, а не
    ответом». Заругаться на них значило бы требовать переписать историю.

    А вот решения в нём проверяются наравне со всеми, и это важнее прощения:
    номера решений ссылаются друг на друга в этом файле сотнями раз, и
    опечатка `D-137`→`D-173` уводит читателя в чужое решение. Вычеркнуть
    журнал целиком значило бы снять проверку там, где она нужнее всего.
    """
    walk = pages(tmp_path, {
        build.DECISION_LOG: "Сняты OQ-020 и OQ-021; стоит на D-001, правит D-999",
    })
    monkeypatch.setattr(build, "documents", lambda: walk)
    monkeypatch.setattr(build, "known_records", lambda: ({"D-001"}, set()))
    assert build.check_named_records() == [f"{build.DECISION_LOG} — D-999"]


def test_the_registries_are_read_as_the_only_source(monkeypatch, tmp_path: Path) -> None:
    """Решение — заголовок журнала, вопрос — строка одного из двух реестров.

    Не всякое вхождение «D-320» в тексте: журнал ссылается на решения сотнями
    раз, и считать источником упоминание значило бы объявить существующим
    любой номер, который кто-то написал.
    """
    monkeypatch.setattr(build, "ROOT", tmp_path)
    (tmp_path / "90-production").mkdir(parents=True)
    (tmp_path / "00-core").mkdir(parents=True)
    (tmp_path / build.DECISION_LOG).write_text(
        "### D-001 · Первое\n\nтут названо D-777, но своей записи у него нет\n",
        encoding="utf-8",
    )
    (tmp_path / build.QUESTION_REGISTRIES[0]).write_text(
        "| OQ-104 | P2 | **Вопрос** | текст |\n", encoding="utf-8"
    )
    (tmp_path / build.QUESTION_REGISTRIES[1]).write_text(
        "| OQ-100 | Старое | Решено | D-001 |\n", encoding="utf-8"
    )
    assert build.known_records() == ({"D-001"}, {"OQ-104", "OQ-100"})


# --- статусы -----------------------------------------------------------------


def test_a_status_outside_the_six_is_not_a_status(monkeypatch, tmp_path: Path) -> None:
    """Статус — контракт синхронизации, и он закрытый список.

    «программа принята решением D-319» читается человеком, но не обязывает ни
    к чему: сверять такой документ не с чем, и молчал об этом только индекс,
    складывая такие в список внизу, куда никто не смотрит.
    """
    walk = pages(tmp_path, {
        "10-world/01-a.md": "# А\n\n> **Статус:** реализовано\n",
        "90-production/11-plan.md": "# План\n\n> **Статус:** программа принята решением D-319\n",
        "10-world/02-b.md": "# Б\n\nбез шапки вовсе\n",
    })
    monkeypatch.setattr(build, "documents", lambda: walk)
    assert build.check_statuses() == [
        "10-world/02-b.md — Б",
        "90-production/11-plan.md — План",
    ]


def test_the_index_itself_and_the_service_documents_are_spared(
    monkeypatch, tmp_path: Path
) -> None:
    """Индекс генерируется из этих же шапок, а README — не про игру."""
    walk = pages(tmp_path, {
        "90-production/03-status.md": "# Статусы\n\nбез шапки\n",
        "README.md": "# Вольт\n\nбез шапки\n",
        "CLAUDE.md": "# Правила\n\nбез шапки\n",
    })
    monkeypatch.setattr(build, "documents", lambda: walk)
    assert build.check_statuses() == []


def test_an_example_in_a_code_span_is_not_a_link(monkeypatch, tmp_path: Path) -> None:
    """Пример в кавычках — пример.

    Первым на это наступил абзац, объясняющий саму эту семью: он приводил
    `[текст](путь.md)` как образец, и единственным живым предупреждением
    уровня, заведённого ради читаемых предупреждений, оказалось ложное — в его
    же документации. Огороженный блок — тот же случай.
    """
    walk = pages(tmp_path, {
        "CLAUDE.md": "семья ловит `[текст](путь.md)` — ссылку на файл, которого нет",
        "b.md": "```\nсм. [пример](никуда.md)\n```\n",
    })
    monkeypatch.setattr(build, "documents", lambda: walk)
    assert build.check_doc_links() == []


def test_the_index_and_the_check_walk_together(monkeypatch, tmp_path: Path) -> None:
    """Смысл вынесенной `statuses`: два обхода не могут разъехаться.

    Разъедутся они молча — индекс покажет документ без статуса, проверка о нём
    не скажет, и наоборот. Тест сверяет их на одном дереве, поэтому падает
    ровно в тот день, когда список исключений правят в одном месте из двух.
    """
    walk = pages(tmp_path, {
        "10-world/01-a.md": "# А\n\n> **Статус:** идея\n",
        "10-world/02-b.md": "# Б\n\nбез шапки\n",
        "editor/README.md": "# Редактор\n\nбез шапки, и правильно\n",
    })
    monkeypatch.setattr(build, "documents", lambda: walk)
    index = build.build_status_index()
    named = [one.split(" — ")[1] for one in build.check_statuses()]
    assert named == ["Б"]
    assert "без распознанного статуса (1)" in index
    for title in named:
        assert f"[{title}](" in index
