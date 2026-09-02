# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The names of things in the other languages, and the small dictionaries (D-251).

A new thing is not only a line in `recipes.yaml`. The build refuses to run
until the thing has a name in every language of the game (`check_locales` in
`tools/build.py`), and a building type is not only three maps in
`constants.yaml` but also a row of the small dictionary that gives it its key
(`check_ids`). Keeping several files in step is exactly the work a tool should
do instead of a person -- the same reason building types got a form -- so the
editor writes these two files together with the thing itself, under one stamp,
and undo takes them back together.

Both are edited the way every other file here is: one line at a time, the
comments around it left alone, and the whole document parsed back and compared
with what was meant before a byte is written (`store.prepare_doc`).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml
from vaultfile import VaultError, _scalar, render_entry, scan_entries

#: Where the languages lie inside `data/`, and the file per language.
LOCALES_DIR = "locales"
#: The order of keys in a small-dictionary row, as the file writes them.
VOCABULARY_KEY_ORDER = ("name", "id", "note")
#: The domain of the small dictionaries that names building types (D-218).
BUILDING_KINDS = "building_kinds"


def languages(data_dir: Path) -> list[str]:
    """The languages of the game besides the vault's own: one file each."""
    folder = data_dir / LOCALES_DIR
    if not folder.is_dir():
        return []
    return sorted(path.stem for path in folder.glob("*.yaml"))


class _BlockFile:
    """A YAML file of top-level blocks, read as text, as lines and as a document."""

    def __init__(self, path: Path, text: str | None = None, newline: str | None = None):
        raw = path.read_bytes()
        self.path = path
        self.newline = newline or ("\r\n" if b"\r\n" in raw else "\n")
        self.text = raw.decode("utf-8").replace("\r\n", "\n") if text is None else text
        self.mtime = path.stat().st_mtime_ns
        self.lines = self.text.split("\n")
        self.doc = yaml.safe_load(self.text) or {}

    def _span(self, domain: str) -> tuple[int, int, bool]:
        """`[start, end)` of one top-level block, and whether it is written inline.

        `start` is the line of the key itself. Trailing blank lines and the
        comments that introduce the next block are not part of this one.
        """
        header = re.compile(rf"^{re.escape(domain)}:\s*(.*)$")
        start = next((i for i, line in enumerate(self.lines) if header.match(line)), None)
        if start is None:
            raise VaultError(f"в {self.path.name} нет раздела «{domain}»")
        #: `goods: {}` is a value; `goods:  # words` is a comment, not one.
        rest = header.match(self.lines[start]).group(1).strip()
        inline = bool(rest) and not rest.startswith("#")
        end = start + 1
        while end < len(self.lines):
            line = self.lines[end]
            if line.strip() and not line.startswith(" "):
                break
            end += 1
        while end > start + 1 and (
            not self.lines[end - 1].strip() or self.lines[end - 1].lstrip().startswith("#")
        ):
            end -= 1
        return start, end, inline

    def _open_inline(self, lines: list[str], start: int) -> None:
        """`goods: {}` -- an empty block written inline. The first entry turns it
        into a real block, and the key loses its braces."""
        lines[start] = lines[start].split(":", 1)[0] + ":"

    def _close_empty(self, lines: list[str], start: int, end: int, empty: str) -> None:
        """The last entry is gone: a bare key would read as null, not as nothing."""
        body = lines[start + 1 : end]
        if not any(line.strip() and not line.lstrip().startswith("#") for line in body):
            lines[start] = lines[start].split(":", 1)[0] + f": {empty}"


class LocaleFile(_BlockFile):
    """`data/locales/<lang>.yaml`: `domain -> id -> name`, one line per name.

    The ids of a domain are kept in alphabetical order, as the file has them:
    a name dropped at the end of a block would be found by nobody reading it.
    """

    ENTRY = re.compile(r"^  ([A-Za-z0-9_]+):\s*(.*)$")

    @property
    def lang(self) -> str:
        return self.path.stem

    def name(self, domain: str, entry_id: str) -> str | None:
        return (self.doc.get(domain) or {}).get(entry_id)

    def _entries(self, start: int, end: int) -> list[tuple[int, str]]:
        found = []
        for index in range(start + 1, end):
            match = self.ENTRY.match(self.lines[index])
            if match:
                found.append((index, match.group(1)))
        return found

    def put(self, domain: str, entry_id: str, name: str) -> list[str]:
        """Set one name, in place or in alphabetical order among the others."""
        if not name or not name.strip():
            raise VaultError(f"у «{entry_id}» должно быть имя на языке {self.lang}")
        start, end, inline = self._span(domain)
        line = f"  {entry_id}: {_scalar(name.strip())}"
        lines = list(self.lines)
        if inline:
            self._open_inline(lines, start)
            return lines[: start + 1] + [line] + lines[start + 1 :]
        entries = self._entries(start, end)
        found = [index for index, key in entries if key == entry_id]
        if found:
            lines[found[0]] = line
            return lines
        seat = next((index for index, key in entries if key > entry_id), end)
        return lines[:seat] + [line] + lines[seat:]

    def drop(self, domain: str, entry_id: str) -> list[str]:
        start, end, _ = self._span(domain)
        found = [index for index, key in self._entries(start, end) if key == entry_id]
        if not found:
            raise VaultError(f"в {self.path.name} нет имени для «{entry_id}» ({domain})")
        lines = list(self.lines)
        for index in reversed(found):
            del lines[index]
        self._close_empty(lines, start, end - len(found), "{}")
        return lines

    def expect(self, domain: str, entry_id: str, name: str | None) -> dict:
        """The document as it must read after `put` (a name) or `drop` (None)."""
        doc = copy.deepcopy(self.doc)
        table = dict(doc.get(domain) or {})
        if name is None:
            table.pop(entry_id, None)
        else:
            table[entry_id] = name.strip()
        doc[domain] = table
        return doc


class VocabularyFile(_BlockFile):
    """`data/vocabulary.yaml`: the small dictionaries, one `- {name, id}` row per word."""

    def rows(self, domain: str) -> list[dict]:
        return list(self.doc.get(domain) or [])

    def row(self, domain: str, name: str) -> dict | None:
        return next((row for row in self.rows(domain) if row.get("name") == name), None)

    def _entries(self, start: int, end: int) -> list:
        return [entry for entry in scan_entries(self.lines) if start < entry.start < end]

    def put(self, domain: str, data: dict, original: str | None = None) -> list[str]:
        """Write one row: over the row named `original`, or after the last one."""
        start, end, inline = self._span(domain)
        lines = list(self.lines)
        if inline:
            self._open_inline(lines, start)
            line = render_entry(data, 2, VOCABULARY_KEY_ORDER)
            return lines[: start + 1] + [line] + lines[start + 1 :]
        entries = self._entries(start, end)
        found = next((entry for entry in entries if entry.name == original), None)
        if original is not None and found is None:
            raise VaultError(f"в {self.path.name} нет слова «{original}» ({domain})")
        if found is not None:
            line = render_entry(data, found.indent, VOCABULARY_KEY_ORDER)
            return lines[: found.start] + [line] + lines[found.end + 1 :]
        indent = entries[-1].indent if entries else 2
        line = render_entry(data, indent, VOCABULARY_KEY_ORDER)
        seat = entries[-1].end + 1 if entries else end
        return lines[:seat] + [line] + lines[seat:]

    def drop(self, domain: str, name: str) -> list[str]:
        start, end, _ = self._span(domain)
        found = next((entry for entry in self._entries(start, end) if entry.name == name), None)
        if found is None:
            raise VaultError(f"в {self.path.name} нет слова «{name}» ({domain})")
        lines = self.lines[: found.start] + self.lines[found.end + 1 :]
        self._close_empty(lines, start, end - (found.end - found.start + 1), "[]")
        return lines

    def expect(self, domain: str, data: dict | None, original: str | None = None) -> dict:
        """The document as it must read after `put` (a row) or `drop` (None)."""
        doc = copy.deepcopy(self.doc)
        rows = list(doc.get(domain) or [])
        at = next((i for i, row in enumerate(rows) if row.get("name") == original), None)
        if data is None:
            if at is not None:
                del rows[at]
        elif at is not None:
            rows[at] = data
        else:
            rows.append(data)
        doc[domain] = rows
        return doc


def clean_names(given: Any, langs: list[str], what: str) -> dict[str, str]:
    """The names a form sent, one per language of the game, or a refusal.

    A missing language is refused here rather than by the build later: the
    build would refuse anyway, and the person would learn it a check later,
    with the recipe already written.
    """
    names = given if isinstance(given, dict) else {}
    out: dict[str, str] = {}
    for lang in langs:
        name = str(names.get(lang) or "").strip()
        if not name:
            raise VaultError(
                f"у «{what}» нет имени на языке «{lang}» — сборка не соберётся, "
                "пока имени нет на каждом языке (D-251)"
            )
        out[lang] = name
    return out
