# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The relief preview: what the land would look like with these numbers.

The shape of a planet is the engine's arithmetic (`engine/terrain`,
`src/relief`, D-319, D-321, D-323) and it stays the engine's. Porting it here
would give the world two shapes — the one the editor draws and the one the
game builds — and the first change to either would part them silently. So the
editor **asks the engine**: `backend/tools/sketch.py` reads the vault's build,
puts the numbers being tried over it without writing anything, and prints the
field. This module runs that command and hands the answer on.

That makes the preview the one thing in the editor that needs a second
repository on the machine. It is optional and says so: without the engine the
panel explains what to set, and everything else in the tab goes on working.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import vaultfile as vault
from session import Session

#: Where the engine is, if it is anywhere. Told by the environment, or guessed
#: as the sibling checkout that every developer here has.
BACKEND_ENV = "EVERSELIFE_BACKEND"
#: How long a field may take to build. It is a second on this machine; the
#: bound is here so a wedged child cannot hold the editor's thread.
TIMEOUT_S = 60


def backend_path() -> Path | None:
    told = os.environ.get(BACKEND_ENV)
    if told:
        path = Path(told)
        return path if (path / "tools" / "sketch.py").exists() else None
    guess = Path(__file__).resolve().parent.parent.parent / "everselife" / "backend"
    return guess if (guess / "tools" / "sketch.py").exists() else None


def _python(backend: Path) -> str:
    """The engine's own interpreter where it has one: the field is numpy."""
    for candidate in (
        backend / ".venv" / "Scripts" / "python.exe",
        backend / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def terrain(session: Session, query: dict, _body: dict) -> dict:
    """The field of one planet, with any number of values tried over the build.

    `set` repeats: `?set=terrain.seed%3D17&set=terrain.detail_km%3D2`. Nothing
    is written -- that is the whole point of a preview, and saving is the
    ordinary constant form's business.
    """
    backend = backend_path()
    if backend is None:
        raise vault.VaultError(
            "превью рельефа считает движок, а он не найден: поставьте"
            f" переменную {BACKEND_ENV} на каталог backend соседнего репозитория"
        )
    planet = (query.get("planet") or ["terra"])[0]
    argv = [_python(backend), str(backend / "tools" / "sketch.py"), "--planet", planet]
    #: The build the editor itself is holding, so a rebuild of another vault
    #: worktree cannot change what this preview shows.
    argv += ["--build", str(session.vault / "build")]
    for one in query.get("set") or []:
        if one:
            argv += ["--set", one]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        done = subprocess.run(
            argv, cwd=backend, capture_output=True, env=env, timeout=TIMEOUT_S, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise vault.VaultError(f"движок не ответил: {error}") from error
    if done.returncode != 0:
        words = (done.stderr or done.stdout).decode("utf-8", errors="replace").strip()
        raise vault.VaultError(f"движок отказался считать рельеф: {words[-400:]}")
    try:
        return json.loads(done.stdout.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise vault.VaultError(f"движок ответил не полем: {error}") from error


def terrain_ready(_session: Session, _query: dict, _body: dict) -> dict:
    """Whether the preview can be drawn at all, and where the engine is."""
    backend = backend_path()
    return {
        "ready": backend is not None,
        "backend": str(backend) if backend else None,
        "variable": BACKEND_ENV,
    }


ROUTES = {
    ("GET", "/api/terrain"): terrain,
    ("GET", "/api/terrain/ready"): terrain_ready,
}
