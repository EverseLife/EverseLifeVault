# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The planets tab: the sizes it works out and the run it drives (D-328).

Two things are worth pinning here, and the field itself is neither -- the
field is the pipeline's and is tested in `tools/tests`. What is the editor's
is that the sizes it shows are the pipeline's own arithmetic rather than a
second copy of it, and that a run is one at a time, carries the numbers being
tried, and says what happened.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import time
from pathlib import Path

import api_field
import pytest
import server
import vaultfile as vault
from field import healpix


@pytest.fixture
def bare_vault(tmp_path: Path, session) -> Path:
    """A vault with nothing built in it but the pipeline's own arithmetic.

    The sizes are worked out by the `healpix` of **the vault being edited**
    (`api_field._healpix`), so a temporary vault has to have one: pointed at a
    directory without it, the tab correctly refuses to work anything out, and
    that is a different test than this one.
    """
    where = tmp_path / "tools" / "field"
    where.mkdir(parents=True)
    real = Path(healpix.__file__).parent
    for name in ("__init__.py", "healpix.py"):
        if (real / name).is_file():
            shutil.copy2(real / name, where / name)
    #: And a built registry newer than the source, so a run here is a run of
    #: the pipeline and not of the vault's own build first (`_stale_registry`).
    built = tmp_path / "build" / "constants.json"
    built.parent.mkdir(parents=True, exist_ok=True)
    built.write_text("{}", encoding="utf-8")
    session.vault = tmp_path
    return tmp_path


@pytest.fixture(autouse=True)
def no_job() -> None:
    """Each test starts with no run behind it: the job is a module singleton."""
    api_field._JOB = None
    yield
    job = api_field._JOB
    if job is not None and job.child is not None:
        job.child.kill()
    api_field._JOB = None


def test_a_vault_without_the_pipeline_says_so_and_still_shows_the_numbers(
    session, tmp_path: Path
) -> None:
    """No pipeline, no sizes -- and the numbers are still there to be edited.

    The editor rises on the standard library; the pipeline is numpy. What is
    lost without it is only what the numbers come to.
    """
    session.vault = tmp_path
    state = api_field.field_state(session, {}, {})
    assert state["worlds"] == [] and "конвейер" in state["missing"]
    assert state["groups"], "числа земли всё равно показываются и правятся"


def test_the_sizes_are_the_pipelines_own_arithmetic(session) -> None:
    """Every planet's drobnost is `healpix.nside_for`, not a copy of it.

    A second implementation of «how many cells is this planet» is the defect
    this test exists to prevent: it would agree on the day it was written and
    part from the builder on the first change to either.
    """
    state = api_field.field_state(session, {}, {})
    worlds = {one["planet"]: one for one in state["worlds"]}
    assert set(worlds) == set(api_field.PLANETS)

    entries = {
        one["key"]: one.get("value")
        for group in state["groups"]
        for one in group["constants"]
    }
    step = float(entries["terrain.step_m"])
    earth_km = float(entries["planet.earth_radius_km"])
    for planet, world in worlds.items():
        share = float(entries["planet.land_area_share"][planet])
        radius_m = math.sqrt(share) * earth_km * 1000.0
        assert world["nside"] == healpix.nside_for(radius_m, step)
        assert world["cells"] == healpix.npix(world["nside"])
        assert world["side_m"] == pytest.approx(
            healpix.cell_side_m(radius_m, world["nside"]), abs=0.01
        )
        #: The whole point of showing the miss: a step nobody looked at lands
        #: the cell far from what was asked for, and the tab has to say so.
        assert abs(world["miss"]) < 0.05, planet
    assert state["totals"]["cells"] == sum(one["cells"] for one in worlds.values())


def test_a_field_that_is_not_there_is_not_pretended_to_be(session, bare_vault: Path) -> None:
    """«Не собрано» is a state, not an empty картинка."""
    state = api_field.field_state(session, {}, {})
    for world in state["worlds"]:
        assert world["built"] == {"present": False}
        assert world["pictures"] == []


def test_a_built_field_is_read_out_of_its_own_passport(session, bare_vault: Path) -> None:
    """What the card says about a built planet comes from the file it was built into."""
    where = bare_vault / "build" / "field"
    where.mkdir(parents=True)
    (where / "terra.npz").write_bytes(b"x" * 2048)
    (where / "terra.json").write_text(
        json.dumps({
            "digest": "abc123",
            "land_share": 0.7,
            "height_max_m": 750.0,
            "grid": {"nside": 509, "cells": 3_108_972, "side_m": 50.02, "radius_m": 24_890.0},
            "params": {"seed": 17, "version": 5, "relief_m": 750.0},
        }),
        encoding="utf-8",
    )
    built = {one["planet"]: one["built"] for one in api_field.field_state(session, {}, {})["worlds"]}
    assert built["terra"]["present"] and built["terra"]["digest"] == "abc123"
    assert built["terra"]["nside"] == 509 and built["terra"]["seed"] == 17
    assert built["aurora"] == {"present": False}


def test_the_numbers_being_tried_reach_the_tool_and_are_not_written(
    session, monkeypatch
) -> None:
    """Seed and step go to the child as flags; the registry is untouched.

    They are tried, not saved (plan §4.1, §4.4). A run that quietly wrote them
    would turn «what would this look like» into «this is now the world».
    """
    seen: list[list[str]] = []
    was = session.constants.read_text(encoding="utf-8")

    class Child:
        returncode = 0
        stdout = iter(["[ 0.0 s] grid nside 8\n", "[ 1.0 s] written\n"])

        def wait(self) -> None:
            return None

    def fake_popen(argv, **_kwargs):
        seen.append(argv)
        return Child()

    monkeypatch.setattr(api_field.subprocess, "Popen", fake_popen)
    api_field.field_build(session, {}, {"planets": ["pyroxis"], "seed": "17", "step": "60"})
    _wait()

    argv = seen[0]
    assert argv[argv.index("--planet") + 1] == "pyroxis"
    assert argv[argv.index("--seed") + 1] == "17"
    assert argv[argv.index("--step") + 1] == "60"
    assert session.constants.read_text(encoding="utf-8") == was
    job = api_field.field_job(session, {}, {})["job"]
    assert job["done"] == ["pyroxis"] and not job["running"] and not job["failed"]
    #: The stage is the last thing the tool printed, with its stamp taken off.
    assert job["stage"] == "готово"


def test_two_runs_at_once_are_refused_rather_than_queued(session, monkeypatch) -> None:
    """A build is minutes and gigabytes; a queue would hide the wait."""
    class Child:
        returncode = 0

        def __init__(self) -> None:
            self.stdout = self._lines()

        def _lines(self):
            time.sleep(0.4)
            yield "[ 0.0 s] grid\n"

        def wait(self) -> None:
            return None

    monkeypatch.setattr(api_field.subprocess, "Popen", lambda *a, **k: Child())
    api_field.field_build(session, {}, {"planets": ["terra"]})
    with pytest.raises(vault.VaultError, match="уже идёт"):
        api_field.field_build(session, {}, {"planets": ["aurora"]})
    _wait()


def test_a_child_that_fails_stops_the_walk_and_names_the_planet(session, monkeypatch) -> None:
    """The second planet is not built on the ruins of the first."""
    class Child:
        returncode = 3

        def __init__(self) -> None:
            self.stdout = iter(["[ 0.0 s] grid\n"])

        def wait(self) -> None:
            return None

    monkeypatch.setattr(api_field.subprocess, "Popen", lambda *a, **k: Child())
    api_field.field_build(session, {}, {"planets": ["terra", "aurora"]})
    _wait()
    job = api_field.field_job(session, {}, {})["job"]
    assert job["failed"].startswith("terra:") and job["done"] == []


def test_an_unknown_planet_or_job_is_refused_by_name(session) -> None:
    with pytest.raises(vault.VaultError, match="нет такой планеты: mars"):
        api_field.field_build(session, {}, {"planets": ["mars"]})
    with pytest.raises(vault.VaultError, match="нет такой работы"):
        api_field.field_build(session, {}, {"kind": "wipe", "planets": ["terra"]})


def test_the_log_can_be_asked_for_from_where_the_page_left_off(session, monkeypatch) -> None:
    """A two-hour build prints thousands of lines; the page asks for the new ones."""
    class Child:
        returncode = 0

        def __init__(self) -> None:
            self.stdout = iter([f"line {k}\n" for k in range(5)])

        def wait(self) -> None:
            return None

    monkeypatch.setattr(api_field.subprocess, "Popen", lambda *a, **k: Child())
    api_field.field_build(session, {}, {"planets": ["terra"]})
    _wait()
    whole = api_field.field_job(session, {}, {})["job"]
    assert whole["total"] == len(whole["lines"])
    tail = api_field.field_job(session, {"since": [str(whole["total"] - 2)]}, {})["job"]
    assert tail["lines"] == whole["lines"][-2:]
    assert tail["total"] == whole["total"]


def _wait(seconds: float = 5.0) -> None:
    """Until the run's own thread has finished with it."""
    until = time.time() + seconds
    while time.time() < until:
        job = api_field._JOB
        if job is not None and job.ended != 0.0:
            return
        time.sleep(0.02)
    raise AssertionError("работа не кончилась")


def test_a_run_marks_the_vault_so_a_second_process_cannot_start_another(
    session, bare_vault: Path, monkeypatch
) -> None:
    """The singleton is inside one process; the child outlives it.

    Ctrl+C on the editor leaves `landscape.py` grinding, and a restarted editor
    would see no job and start a second one into the same files -- `store.save`
    writes straight to `build/field/<planet>.npz`, with no temporary and no
    rename, and that directory is committed and shared with every worktree.
    """
    class Child:
        returncode = 0

        def __init__(self) -> None:
            self.stdout = iter(["[ 0.0 s] grid\n"])

        def wait(self) -> None:
            return None

    monkeypatch.setattr(api_field.subprocess, "Popen", lambda *a, **k: Child())
    api_field.field_build(session, {}, {"planets": ["terra"]})
    _wait()
    #: The mark goes when the run does.
    assert not api_field._lock_path(session).exists()

    #: And a mark left by somebody else stops a run before it starts.
    api_field._lock_path(session).write_text(
        json.dumps({"pid": 4242, "kind": "build", "planets": ["aurora"], "began": 0}),
        encoding="utf-8",
    )
    api_field._JOB = None
    with pytest.raises(vault.VaultError, match="4242"):
        api_field.field_build(session, {}, {"planets": ["terra"]})
    #: Unless it is said to be stale, and then it is taken over rather than
    #: worked around by hand.
    api_field.field_build(session, {}, {"planets": ["terra"], "force": True})
    _wait()


def test_stopping_a_run_is_not_a_failure(session, bare_vault: Path, monkeypatch) -> None:
    """A killed child returns a code, and «Остановить» must not read as «отказ»."""
    class Child:
        returncode = -9

        def __init__(self) -> None:
            self.stdout = iter(["[ 0.0 s] grid\n"])
            self.killed = False

        def kill(self) -> None:
            self.killed = True

        def wait(self) -> None:
            return None

    monkeypatch.setattr(api_field.subprocess, "Popen", lambda *a, **k: Child())
    job = api_field.Job(kind="build", planets=["terra"], argv_extra=[])
    job.stopping = True
    api_field._JOB = job
    api_field._take_lock(session, job, False)
    api_field._run_job(session, job)
    assert job.failed == "" and job.stage == "остановлено"
    assert job.done == []


def test_a_registry_newer_than_the_build_is_built_first(
    session, bare_vault: Path, monkeypatch
) -> None:
    """The tab reads the source file; the pipeline reads the built registry.

    Between them lies every number written and not yet built. A run started
    there would quietly build the old world while the cards showed the new one
    -- the worst kind of failure, because it looks like an answer.
    """
    #: The source is newer than the build, which is what writing a constant
    #: leaves behind. Set by hand rather than by touching: two writes a
    #: millisecond apart are the same stamp on this filesystem, and the test
    #: would pass or fail by the weather.
    built = bare_vault / "build" / "constants.json"
    built.write_text("{}", encoding="utf-8")
    old = session.constants.stat().st_mtime - 60
    os.utime(built, (old, old))
    assert api_field._stale_registry(session)
    assert api_field.field_state(session, {}, {})["stale"] is True

    ran: list[list[str]] = []

    class Built:
        returncode = 0
        stdout = b"reg\n"
        stderr = b""

    class Child:
        returncode = 0

        def __init__(self) -> None:
            self.stdout = iter(["[ 0.0 s] grid\n"])

        def wait(self) -> None:
            return None

    monkeypatch.setattr(
        api_field.subprocess, "run", lambda argv, **k: (ran.append(argv), Built())[1]
    )
    monkeypatch.setattr(api_field.subprocess, "Popen", lambda *a, **k: Child())
    answer = api_field.field_build(session, {}, {"planets": ["terra"]})
    assert answer["job"]["rebuild"] is True
    _wait()
    assert ran and ran[0][-1].endswith("build.py")
    #: And said out loud rather than done quietly: it writes the vault's own
    #: documents, and that is the «Собрать» button's doing.
    lines = api_field.field_job(session, {}, {})["job"]["lines"]
    assert any("реестр новее сборки" in line for line in lines)

    #: A render reads a field that is already there and cannot be caught out.
    api_field._JOB = None
    answer = api_field.field_build(session, {}, {"kind": "render", "planets": ["terra"]})
    assert answer["job"]["rebuild"] is False
    _wait()


def test_a_picture_can_only_be_named_a_picture() -> None:
    """The name is judged before it becomes a path, and the judge is a pattern.

    Not a containment test after the join: on Windows `Path("build/preview") /
    "//host/share/a.png"` **is** that UNC path, and resolving it dials the host
    -- measured at twenty-one seconds of an editor thread spent opening an SMB
    connection somebody else chose, and on a reachable host the developer's own
    hash handed over. A browser sends that URL from any page.
    """
    assert server.PREVIEW_NAME.fullmatch("terra_planet_relief.png")
    for bad in (
        "../../data/recipes.yaml",
        "../../../Windows/win.ini",
        "//host/share/a.png",
        "/host/share/a.png",
        "C:/Windows/win.ini",
        "a/b.png",
        "a\\b.png",
        "..%2f..%2fa.png",
        "Terra.PNG",
        "terra.png.exe",
        "",
    ):
        assert not server.PREVIEW_NAME.fullmatch(bad), bad
