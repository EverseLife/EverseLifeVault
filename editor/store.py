# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Putting edited files on disk: the last check, the backup, the undo.

Every file the editor writes goes through here, whatever its shape -- the
recipes, the constants, the world, the small dictionaries, the locales. The
rule is one for all: the text is parsed back and compared with the document
the caller meant, the file must not have moved on disk while it was open, and
a copy of what was there is kept so that «Отменить правку» has something to
restore. An edit that touches two files is written under one stamp, and undo
takes both back together.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from vaultfile import VaultError, _comparable, _find_recipe

# Overridable because the editor also runs in a container, where the
# repository and the backups live on mounted volumes rather than beside the code.
# The server points this at the vault being edited (`server.main`).
BACKUPS = Path(
    os.environ.get("EVERSELIFE_EDITOR_BACKUPS") or Path(__file__).resolve().parent / "backups"
)

#: The time part of a backup's name, without a twin suffix.
STAMP = re.compile(r"^\d{8}-\d{6}-\d{3}")
#: The directory a data file may lie one level down in, and the mark of it in
#: a backup's name: `locales__en` is `data/locales/en.yaml`.
NESTED_DIR = "locales"
NESTED_MARK = f"{NESTED_DIR}__"


@dataclass(frozen=True)
class Write:
    """One file as it must be written: already checked, not yet on disk.

    An edit of the vault often touches more than one file -- a new recipe is a
    line in `recipes.yaml` and a name in every `locales/*.yaml` -- and the
    files must be checked all together before any of them is written: a
    refusal half-way would leave the vault in a state nobody meant.
    """

    path: Path
    text: str
    newline: str


def prepare(
    path: Path,
    lines: list[str],
    expect: dict,
    mtime: int | None = None,
    newline: str = "\n",
) -> Write:
    """The recipe file as it must be written, checked to have changed exactly as expected.

    `expect` is what the document must show for the touched name afterwards:
    `{"name": ..., "data": {...} | None}` -- None for a deletion. The check is
    what makes a line-level edit safe: a mistake in line arithmetic cannot pass it.
    """
    text, doc = _reread(path, lines, mtime)

    for gone in expect.get("absent") or []:
        if _find_recipe(doc, gone) is not None:
            raise VaultError(f"«{gone}» остался в файле после переименования")

    found = _find_recipe(doc, expect["name"])
    wanted = expect["data"]
    if wanted is None:
        if found is not None:
            raise VaultError(f"«{expect['name']}» остался в файле после удаления")
    else:
        if found is None:
            raise VaultError(f"«{expect['name']}» не появился в файле после записи")
        if _comparable(found) != _comparable(wanted):
            raise VaultError(f"записанное не совпало с задуманным: {found} != {wanted}")
    return Write(path, text, newline)


def prepare_doc(
    path: Path,
    lines: list[str],
    expect_doc: dict,
    mtime: int | None = None,
    newline: str = "\n",
) -> Write:
    """A file as it must be written, checked as a whole document against what was meant.

    Used where the edit is not one entry but a line inside `meta`, a block of
    the world or a constant: there is no single name to look up afterwards,
    so the entire parsed document is compared with the one the caller built by
    hand. Anything the line arithmetic touched besides the intended change
    shows up as a mismatch and stops the write.
    """
    text, doc = _reread(path, lines, mtime)
    if _comparable(doc) != _comparable(expect_doc):
        raise VaultError("после правки файл читается не так, как задумано — запись отменена")
    return Write(path, text, newline)


def commit(*writes: Write) -> list[Path]:
    """Put prepared files on disk, all under one stamp.

    One stamp for the whole edit is what lets «Отменить правку» take back the
    recipe line together with the English name that came with it: undo restores
    every backup of the newest stamp, not the newest file alone.

    Every file is checked before any is written; what this does not guard
    against is the disk failing between two writes -- and for that the backups
    of the same stamp are there.
    """
    stamp = new_stamp()
    backups = [_backup(write.path, stamp) for write in writes]
    for write in writes:
        write.path.write_text(write.text, encoding="utf-8", newline=write.newline)
    return backups


def save(
    path: Path,
    lines: list[str],
    expect: dict,
    mtime: int | None = None,
    newline: str = "\n",
) -> Path:
    """`prepare` and `commit` in one step, for an edit that touches one file."""
    return commit(prepare(path, lines, expect, mtime, newline))[0]


def save_doc(
    path: Path,
    lines: list[str],
    expect_doc: dict,
    mtime: int | None = None,
    newline: str = "\n",
) -> Path:
    """`prepare_doc` and `commit` in one step, for an edit that touches one file."""
    return commit(prepare_doc(path, lines, expect_doc, mtime, newline))[0]


def _reread(path: Path, lines: list[str], mtime: int | None) -> tuple[str, Any]:
    if mtime is not None and path.stat().st_mtime_ns != mtime:
        raise VaultError(
            "файл вольта изменился на диске, пока он был открыт в редакторе. "
            "Обновите страницу и повторите правку."
        )
    text = "\n".join(lines)
    try:
        return text, yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise VaultError(f"после правки файл перестал читаться: {error}") from error


# ------------------------------------------------------------------ backups


_last_stamp = ""


def new_stamp() -> str:
    """The time part of a backup's name: one per edit, shared by every file it writes.

    Two saves inside one millisecond used to land on the same name, and the
    second copy overwrote the first. On a fast machine that is not exotic:
    `undo` makes its own backup right before restoring, and a collision made
    it roll back to the very edit it was undoing. Now the stamp is what groups
    the files of one edit, so two edits must never share one: the clock is
    waited out until it moves.
    """
    global _last_stamp
    while True:
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}"
        if stamp > _last_stamp:
            _last_stamp = stamp
            return stamp
        time.sleep(0.001)


def _label(path: Path) -> str:
    """The file's own part of a backup's name.

    The file's name leads, because the editor writes more than one of them:
    recipes, constants (D-218), the world (D-243), the small dictionaries and
    the locales (D-251). Undo has to know which file a backup was of, and the
    name is where it says so. Every file lies in `data/` except the locales,
    one directory down -- so the label carries that directory when it is there.
    """
    if path.parent.name == NESTED_DIR:
        return f"{NESTED_MARK}{path.stem}"
    return path.stem


#: A backup's name read from the end: the label may itself hold a dash
#: (`locales__pt-BR`), the stamp never holds anything but digits.
_BACKUP_NAME = re.compile(r"^(?P<label>.+?)-(?P<stamp>\d{8}-\d{6}-\d{3}(?:-\d{2})?)$")


def _split(backup: Path) -> tuple[str, str]:
    """(label, stamp) of a backup's name; an unreadable name sorts first and is left alone."""
    found = _BACKUP_NAME.match(backup.stem)
    if not found:
        return backup.stem, ""
    return found.group("label"), found.group("stamp")


def _target(beside: Path, backup: Path) -> Path:
    """Where a backup goes back to: the data file its label names, next to `beside`."""
    label, _ = _split(backup)
    if label.startswith(NESTED_MARK):
        return beside.parent / NESTED_DIR / f"{label[len(NESTED_MARK):]}{beside.suffix}"
    return beside.with_name(f"{label}{beside.suffix}")


def _backup(path: Path, stamp: str | None = None) -> Path:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    base = f"{_label(path)}-{stamp or new_stamp()}"
    target = BACKUPS / f"{base}.yaml"
    twin = 0
    while target.exists():
        twin += 1
        target = BACKUPS / f"{base}-{twin:02d}.yaml"
    shutil.copy2(path, target)
    _trim_backups(_label(path))
    return target


def _trim_backups(label: str, keep: int = 40) -> None:
    """Each edited file keeps its own depth of history: they are edited apart."""
    saved = sorted(BACKUPS.glob(f"{label}-*.yaml"), key=_stamp_of)
    for old in saved[:-keep]:
        old.unlink(missing_ok=True)


def _stamp_of(path: Path) -> str:
    """The time part of a backup's name -- what follows the file's own label."""
    return _split(path)[1]


def _edit_of(path: Path) -> str:
    """The stamp without its twin suffix: what groups the files of one edit."""
    found = STAMP.match(_stamp_of(path))
    return found.group(0) if found else _stamp_of(path)


def last_backup() -> Path | None:
    """The newest backup of any file the editor writes.

    Sorted by the stamp inside the name and not by the whole name: two files
    sorted as text would put every `constants-*` before every `recipes-*`, and
    undo would walk back an edit made hours ago instead of the last one.
    """
    if not BACKUPS.exists():
        return None
    saved = sorted(BACKUPS.glob("*.yaml"), key=_stamp_of)
    return saved[-1] if saved else None


def undo(path: Path) -> list[str]:
    """Roll back the newest edit -- every file it wrote -- keeping the current state too.

    `path` says where the vault's data files lie, not which one to restore: the
    newest edit may have been to `constants.yaml` while the page was showing
    recipes, and undoing the wrong file would be worse than not undoing at all.
    An edit that wrote two files is taken back as two files: a recipe without
    its English name would be exactly the half-state the build refuses.
    """
    newest = last_backup()
    if newest is None:
        raise VaultError("отменять нечего: правок в этой копии ещё не было")
    edit = _edit_of(newest)
    pairs = [
        (backup, _target(path, backup))
        for backup in sorted(BACKUPS.glob("*.yaml"), key=_stamp_of)
        if _edit_of(backup) == edit
    ]
    for _, target in pairs:
        if not target.exists():
            raise VaultError(f"откатывать некуда: файла {target.name} нет рядом")
    #: Read before writing: what is being restored must not depend on the
    #: backup file surviving the backup that `undo` itself makes.
    restored = [(backup, target, backup.read_bytes()) for backup, target in pairs]
    stamp = new_stamp()
    for backup, target, data in restored:
        _backup(target, stamp)
        target.write_bytes(data)
        backup.unlink(missing_ok=True)
    return [backup.name for backup, _, _ in restored]
