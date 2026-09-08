# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The relief preview: the editor asks the engine, and never guesses (D-319).

Two things are worth pinning, and neither is the field itself -- the field is
the engine's and is tested there. What is the editor's is **where the answer
comes from**: that the numbers being tried are passed through untouched, and
that a missing engine is said out loud rather than drawn wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import api_terrain
import pytest
import vaultfile as vault


class FakeSession:
    """Only what the handler touches: where the vault is."""

    def __init__(self, root: Path) -> None:
        self.vault = root


def test_without_the_engine_the_preview_says_so(monkeypatch, tmp_path: Path) -> None:
    """A refusal that names the variable to set, not an empty picture.

    The preview is the one thing here that needs a second repository on the
    machine. Everything else in the tab goes on working without it, so the
    answer has to be a sentence rather than a blank canvas.
    """
    monkeypatch.setattr(api_terrain, "backend_path", lambda: None)
    ready = api_terrain.terrain_ready(FakeSession(tmp_path), {}, {})
    assert ready == {"ready": False, "backend": None, "variable": "EVERSELIFE_BACKEND"}
    with pytest.raises(vault.VaultError, match="EVERSELIFE_BACKEND"):
        api_terrain.terrain(FakeSession(tmp_path), {}, {})


def test_the_numbers_being_tried_reach_the_engine_as_they_were(
    monkeypatch, tmp_path: Path
) -> None:
    """`set` repeats, and every one of them is handed on.

    The whole point of a preview is trying a number **before** writing it, so
    a `set` swallowed on the way would show the planet the file already has
    and say nothing -- the worst of the possible failures, because it looks
    like an answer.
    """
    seen: dict = {}

    class Done:
        returncode = 0
        stdout = json.dumps({"rows": 1}).encode()
        stderr = b""

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["cwd"] = kwargs.get("cwd")
        return Done()

    backend = tmp_path / "backend"
    (backend / "tools").mkdir(parents=True)
    (backend / "tools" / "sketch.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(api_terrain, "backend_path", lambda: backend)
    monkeypatch.setattr(api_terrain.subprocess, "run", fake_run)

    got = api_terrain.terrain(
        FakeSession(tmp_path),
        {"planet": ["pyroxis"], "set": ["terrain.seed=17", "terrain.detail_km=2"]},
        {},
    )
    assert got == {"rows": 1}
    assert seen["cwd"] == backend
    argv = seen["argv"]
    assert argv[2:4] == ["--planet", "pyroxis"]
    assert argv.count("--set") == 2
    assert "terrain.seed=17" in argv and "terrain.detail_km=2" in argv
    #: The build the editor is holding, not whichever one the engine would
    #: find by itself: another worktree's rebuild must not change this picture.
    assert argv[argv.index("--build") + 1] == str(tmp_path / "build")


def test_an_engine_that_fails_is_quoted_rather_than_swallowed(
    monkeypatch, tmp_path: Path
) -> None:
    class Done:
        returncode = 2
        stdout = b""
        stderr = "нет такой планеты: mars".encode()

    backend = tmp_path / "backend"
    (backend / "tools").mkdir(parents=True)
    (backend / "tools" / "sketch.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(api_terrain, "backend_path", lambda: backend)
    monkeypatch.setattr(api_terrain.subprocess, "run", lambda *a, **k: Done())

    with pytest.raises(vault.VaultError, match="нет такой планеты"):
        api_terrain.terrain(FakeSession(tmp_path), {"planet": ["mars"]}, {})
