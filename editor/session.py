# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""What every request handler needs: the files of the vault, one lock, the vault's own check.

The editor writes six files of `data/` now -- recipes, constants (D-218), the
world (D-243), the cultures (D-057), the small dictionaries and the locales
(D-251) -- and a handler that touches two of them must write both or neither.
The session knows where they lie; `store.commit` writes them under one stamp.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import constantsfile as consts
import ladder as model
import localefile as words
import plantsfile as plants_source
import store
import vaultfile as vault
import worldfile as worldsource


class Session:
    """Everything a request needs, and one lock so two saves never overlap."""

    def __init__(self, vault_root: Path):
        self.vault = vault_root
        self.data = vault_root / "data"
        self.source = self.data / "recipes.yaml"
        #: Building types live in the other data file (D-218): three maps that
        #: must agree, and the tool keeps them in step. The rest of the numbers
        #: are edited there one at a time.
        self.constants = self.data / "constants.yaml"
        #: The layout of the starting world (D-243): the third file the editor
        #: writes, and the only one that is not a ladder but a map.
        self.world = self.data / "world.yaml"
        #: The eight cultures (D-057, D-136): the fourth file that is a list
        #: of blocks, and the one the plant catalogue is generated from.
        self.plants = self.data / "plants.yaml"
        #: The small dictionaries and the names in the other languages (D-251):
        #: a thing is not made until it has its key and its name in each language.
        self.vocabulary = self.data / "vocabulary.yaml"
        self.locales_dir = self.data / words.LOCALES_DIR
        self.lock = threading.Lock()

    def open(self, text: str | None = None) -> tuple[vault.RecipesFile, model.Ladder]:
        file = vault.RecipesFile(self.source, text=text)
        derived, stale = model.load_derived(self.vault)
        ladder = model.Ladder(file, derived)
        ladder.stale = stale
        return file, ladder

    def open_constants(self, text: str | None = None) -> consts.ConstantsFile:
        return consts.ConstantsFile(self.constants, text=text)

    def open_world(self, text: str | None = None) -> worldsource.WorldFile:
        return worldsource.WorldFile(self.world, text=text)

    def open_plants(self, text: str | None = None) -> plants_source.PlantsFile:
        return plants_source.PlantsFile(self.plants, text=text)

    def open_vocabulary(self) -> words.VocabularyFile:
        return words.VocabularyFile(self.vocabulary)

    def languages(self) -> list[str]:
        """The languages of the game besides the vault's own, one file each."""
        if not self.locales_dir.is_dir():
            return []
        return sorted(path.stem for path in self.locales_dir.glob("*.yaml"))

    def open_locales(self) -> list[words.LocaleFile]:
        return [words.LocaleFile(self.locales_dir / f"{lang}.yaml") for lang in self.languages()]

    # -- the vault's own tools ----------------------------------------------

    def check(self) -> dict:
        """`tools/build.py --check`: the editor never declares an edit good, this does."""
        return self.run("tools/build.py", "--check")

    def run(self, *command: str) -> dict:
        """Run a vault tool and bring its words back as they were printed.

        Windows would hand the child a cp1251 pipe and the Russian output would
        come back as question marks, so the child is told to speak UTF-8.
        """
        argv = [sys.executable, *command]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        try:
            done = subprocess.run(
                argv, cwd=self.vault, capture_output=True, env=env, timeout=300, check=False
            )
        except FileNotFoundError as error:
            raise vault.VaultError(f"не удалось запустить: {' '.join(argv)} ({error})") from error
        text = (done.stdout + done.stderr).decode("utf-8", errors="replace").strip()
        return {"command": " ".join(argv), "code": done.returncode, "output": text}


# ------------------------------------------------------------------- helpers


def need(query: dict, key: str) -> str:
    values = query.get(key)
    if not values or not values[0]:
        raise vault.VaultError(f"не хватает параметра «{key}»")
    return values[0]


def name_writes(
    session: Session,
    domain: str,
    entry_id: str | None,
    names: dict[str, str] | None,
    *,
    gone: bool = False,
    was_id: str | None = None,
) -> list[store.Write]:
    """The locale files as they must be written for one thing, checked and not yet on disk.

    `names` is the name per language to write; None leaves the names as they
    are. `gone` takes the thing's name out of every language; `was_id` is the
    key the thing had before, when the key itself changed -- the name moves
    with it, because it hangs on the key (D-251).
    """
    writes: list[store.Write] = []
    if not entry_id and not was_id:
        return writes
    for file in session.open_locales():
        lines = list(file.lines)
        expect = file.doc
        step = file
        if was_id and was_id != entry_id and step.name(domain, was_id) is not None:
            lines = step.drop(domain, was_id)
            expect = step.expect(domain, was_id, None)
            step = words.LocaleFile(file.path, text="\n".join(lines), newline=file.newline)
        if gone:
            if entry_id and step.name(domain, entry_id) is not None:
                lines = step.drop(domain, entry_id)
                expect = step.expect(domain, entry_id, None)
        elif names is not None and entry_id:
            name = names.get(file.lang)
            if name and name != step.name(domain, entry_id):
                lines = step.put(domain, entry_id, name)
                expect = step.expect(domain, entry_id, name)
        if lines != file.lines:
            writes.append(store.prepare_doc(file.path, lines, expect, file.mtime, file.newline))
    return writes


def spoken_names(session: Session, domain: str, entry_id: str | None) -> dict[str, str]:
    """What each language calls a thing now -- for the form to show and to keep."""
    if not entry_id:
        return {}
    return {
        file.lang: name
        for file in session.open_locales()
        if (name := file.name(domain, entry_id)) is not None
    }
