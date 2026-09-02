# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Fixtures for the editor's own tests.

The tests never touch the real vault: they copy the data files into a
temporary directory and edit the copies. What they check is exactly what the
editor promises -- that an edit changes one line and nothing else.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

EDITOR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EDITOR))

import server  # noqa: E402  -- the path has to be set first
import store  # noqa: E402
import vaultfile as vault  # noqa: E402


@pytest.fixture(scope="session")
def source() -> Path:
    try:
        return vault.vault_root() / "data" / "recipes.yaml"
    except vault.VaultError as error:
        pytest.skip(str(error))


@pytest.fixture
def recipes(tmp_path: Path, source: Path) -> Path:
    """A copy of the real recipe file, line endings and all."""
    target = tmp_path / "recipes.yaml"
    shutil.copy2(source, target)
    return target


@pytest.fixture
def constants(tmp_path: Path, source: Path) -> Path:
    """A copy of the real constants file: building types are edited there (D-218)."""
    target = tmp_path / "constants.yaml"
    shutil.copy2(source.parent / "constants.yaml", target)
    return target


@pytest.fixture
def world(tmp_path: Path, source: Path) -> Path:
    """A copy of the real world file: the starting world's layout (D-243)."""
    target = tmp_path / "world.yaml"
    shutil.copy2(source.parent / "world.yaml", target)
    return target


@pytest.fixture
def vocabulary(tmp_path: Path, source: Path) -> Path:
    """A copy of the small dictionaries: building types get their key there (D-251)."""
    target = tmp_path / "vocabulary.yaml"
    shutil.copy2(source.parent / "vocabulary.yaml", target)
    return target


@pytest.fixture
def locales_dir(tmp_path: Path, source: Path) -> Path:
    """A copy of every language's names: a new thing is named in each (D-251)."""
    target = tmp_path / "locales"
    target.mkdir()
    for path in (source.parent / "locales").glob("*.yaml"):
        shutil.copy2(path, target / path.name)
    return target


@pytest.fixture
def session(
    recipes: Path, constants: Path, world: Path, vocabulary: Path, locales_dir: Path,
    source: Path, monkeypatch,
) -> server.Session:
    """A session editing the copies, reading derived numbers from the real vault.

    `--check` is the vault's own build, and running it here would say nothing
    about the editor while costing a subprocess per test.
    """
    made = server.Session(source.parent.parent)
    made.source = recipes
    made.constants = constants
    made.world = world
    made.vocabulary = vocabulary
    made.locales_dir = locales_dir
    monkeypatch.setattr(server.Session, "check", lambda _self: None)
    return made


@pytest.fixture(autouse=True)
def backups_elsewhere(tmp_path: Path, monkeypatch) -> Path:
    """Backups of a test edit belong in the test's own directory."""
    place = tmp_path / "backups"
    monkeypatch.setattr(store, "BACKUPS", place)
    return place
