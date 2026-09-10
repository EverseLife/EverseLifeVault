# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The planets: the numbers that shape a field, the building of it, and what came out.

Four things live here that used to live only in a terminal: the numbers of
`terrain.*` gathered in one place with the arithmetic they imply worked out
loud, the running of `tools/landscape.py`, the progress of a run while it
runs, and the pictures it leaves in `build/preview`.

**The arithmetic is imported, not mirrored.** `api_space` copies the engine's
formulas because the engine is a second repository and cannot be imported;
here the pipeline is the vault's own `tools/field/`, in this very checkout, so
the sizes come from `healpix.nside_for` and its neighbours themselves. A
second implementation of «how many cells is this planet» is exactly the thing
that would part from the builder on its first change.

**One run at a time, and it belongs to the vault.** A field build is minutes
of numpy and gigabytes of memory; two at once would fight for both, and both
write `build/field/`. So the job is a module-level singleton, and starting a
second one is refused rather than queued -- a queue would hide from the person
that the first is still going.

The page asks for progress on a timer. That is the game's forbidden pattern
(D-226) and it is right to be forbidden there: the game's server has a socket
and speaks first. This has neither, it is a dev tool on the loopback, and the
alternative -- a long-poll on a `ThreadingHTTPServer` -- would hold a thread
per open tab for the length of a two-hour build.
"""

from __future__ import annotations

import atexit
import importlib.util
import json
import math
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import vaultfile as vault
from session import Session

#: The pipeline, borrowed for its arithmetic -- **out of the vault being
#: edited**, not out of the checkout the editor's own code sits in. Normally
#: they are the same directory; pointed at a worktree by `EVERSELIFE_VAULT`
#: (which is how a branch of the vault is edited, and what the tests do) they
#: are not, and then the sizes shown would be one `healpix` while the field is
#: built by another -- the very «two implementations» this import exists to
#: avoid, only spread across trees instead of files. Loaded by file, so two
#: vaults in one process each get their own.
_HEALPIX: dict[Path, object] = {}
_HEALPIX_LOCK = threading.Lock()


def _healpix(vault_root: Path):
    """`tools/field/healpix` of this vault, or a refusal naming what is missing.

    **Lazily**, and this is not tidiness. The editor starts on the standard
    library and `pyyaml` and says so at the top of `server.py`; the pipeline is
    numpy. Imported at the top, one missing wheel would stop the whole tool --
    recipes, buildings, cultures, everything -- over a tab about planets. So
    the sizes are asked for when they are wanted, and a vault without numpy
    shows the numbers and says plainly that it cannot work them out. It could
    not build a field either.
    """
    tools = (vault_root / "tools").resolve()
    with _HEALPIX_LOCK:
        held = _HEALPIX.get(tools)
        if held is not None:
            return held
        if not (tools / "field" / "healpix.py").is_file():
            raise vault.VaultError(f"в этом вольте нет конвейера поля: {tools / 'field'}")
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        try:
            spec = importlib.util.spec_from_file_location(
                f"field_healpix_{abs(hash(tools))}", tools / "field" / "healpix.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as error:  # numpy missing looks many ways
            raise vault.VaultError(
                f"размеры планет считает конвейер вольта, а он не поднялся: {error}."
                " Поставьте numpy — им же собираются и поля"
            ) from error
        _HEALPIX[tools] = module
        return module


#: Which constants shape a field. Everything under `terrain.` does by
#: definition; the two of `planet.` are what the radius is made of, and
#: without them the tab could show the numbers but not the planets.
FIELD_PREFIXES = ("terrain.",)
FIELD_KEYS = ("planet.land_area_share", "planet.earth_radius_km")
#: What the pictures are drawn for, in the order a person looks at them.
PLANETS = ("terra", "aquatica", "pyroxis", "aurora")
LAYERS = ("relief", "forms", "biomes", "rock", "provinces")
FRAMES = ("planet", "region", "city")
#: Bytes a cell takes **in memory**, where the server holds the field: the
#: sum of the store's dtypes, and the same on every planet because they are
#: fixed. Not what the file weighs -- `np.savez_compressed` gets that down to
#: about a third, and the card shows the file's own size beside this one.
BYTES_PER_CELL = 32
#: Seconds a million cells takes to build, measured on this machine at the
#: fifty-metre step. A guess by its nature -- it is shown as «about».
SECONDS_PER_MILLION = 51.0


def _is_field(key: str) -> bool:
    return key.startswith(FIELD_PREFIXES) or key in FIELD_KEYS


# ------------------------------------------------------------------- the job


@dataclass
class Job:
    """One run of the vault's landscape tool and everything said about it."""

    kind: str
    planets: list[str]
    argv_extra: list[str]
    #: Whether the vault itself is built first: see `_stale_registry`.
    rebuild: bool = False
    began: float = field(default_factory=time.time)
    lines: list[str] = field(default_factory=list)
    #: Which planet is being worked on and what its last printed stage was.
    at: str = ""
    stage: str = ""
    done: list[str] = field(default_factory=list)
    failed: str = ""
    ended: float = 0.0
    stopping: bool = False
    child: subprocess.Popen | None = None

    def state(self) -> dict:
        return {
            "kind": self.kind,
            "planets": self.planets,
            "rebuild": self.rebuild,
            "at": self.at,
            "stage": self.stage,
            "done": list(self.done),
            "failed": self.failed,
            "running": self.ended == 0.0,
            "seconds": round((self.ended or time.time()) - self.began, 1),
            "lines": list(self.lines),
        }


_JOB: Job | None = None
_JOB_LOCK = threading.Lock()
#: The mark a run leaves in the vault while it goes. The in-process singleton
#: is not enough: the child outlives the editor -- Ctrl+C on the tool leaves
#: `landscape.py` grinding, and a restarted editor sees no job and would
#: cheerfully start a second one into the same files. `store.save` writes
#: straight to `build/field/<planet>.npz` with no temporary and no rename, and
#: that directory is committed and shared with every worktree and with the
#: game's test fixtures. The same collision comes of an editor beside a
#: terminal, or two editors on one vault.
LOCK_NAME = ".building.json"


def _lock_path(session: Session) -> Path:
    return session.vault / "build" / "field" / LOCK_NAME


def _take_lock(session: Session, job: Job, force: bool) -> None:
    """Claim the vault's field directory, or say who is holding it."""
    path = _lock_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    if force and path.exists():
        path.unlink()
    try:
        with path.open("x", encoding="utf-8") as file:
            json.dump(
                {"pid": os.getpid(), "kind": job.kind, "planets": job.planets,
                 "began": int(job.began)},
                file, ensure_ascii=False,
            )
    except FileExistsError as error:
        try:
            held = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            held = {}
        old = int(time.time() - (held.get("began") or 0))
        raise vault.VaultError(
            f"поле этого вольта уже строит процесс {held.get('pid', '?')}"
            f" ({held.get('kind', '?')} над {', '.join(held.get('planets') or ['?'])},"
            f" {old // 60} мин назад). Если он умер, снимите отметку:"
            f" удалите {path} или запустите ещё раз с «снять чужую отметку»"
        ) from error


def _drop_lock(session: Session) -> None:
    path = _lock_path(session)
    try:
        path.unlink()
    except OSError:
        pass


@atexit.register
def _kill_the_child() -> None:
    """The editor is going: the field builder does not outlive it.

    A daemon thread dies with the interpreter, but the process it started does
    not -- that is what leaves a grinding `landscape.py` behind a Ctrl+C.
    """
    job = _JOB
    if job is None or job.ended != 0.0:
        return
    job.stopping = True
    child = job.child
    if child is not None:
        child.kill()


def _python(vault_root: Path | None = None) -> str:
    """The interpreter that has numpy.

    The one running the editor where it has it, and otherwise the vault's own
    `.venv` -- an editor started on a bare python can still drive a build, the
    same way `api_terrain` finds the engine's interpreter rather than giving up.
    """
    if vault_root is not None:
        for candidate in (
            vault_root / ".venv" / "Scripts" / "python.exe",
            vault_root / ".venv" / "bin" / "python",
        ):
            if candidate.exists():
                return str(candidate)
    return sys.executable


def _stale_registry(session: Session) -> bool:
    """Whether `data/constants.yaml` is newer than the `build/constants.json`.

    The tab works its numbers out of the **source** file, because that is what
    it edits; `landscape.py` reads the **built** registry (`landscape.constants`).
    Between the two lies every number written and not yet built, and a run
    started there would quietly build the old world while the cards showed the
    new one -- the worst kind of failure, because it looks like an answer.
    """
    built = session.vault / "build" / "constants.json"
    if not built.is_file():
        return True
    return session.constants.stat().st_mtime > built.stat().st_mtime


def _run_job(session: Session, job: Job) -> None:
    """Walk the planets, one child at a time, keeping every line it prints."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    #: The vault is built first when the registry is newer than the build.
    #: Said out loud in the log rather than done quietly: it writes the vault's
    #: documents, and that is the «Собрать» button's doing, not a side effect
    #: of asking for a planet.
    if job.rebuild:
        job.stage = "сборка вольта"
        job.lines.append("$ вольт: реестр новее сборки, собираю его первым")
        done = subprocess.run(
            [_python(), str(session.vault / "tools" / "build.py")],
            cwd=session.vault, capture_output=True, env=env, check=False,
        )
        job.lines.extend(
            (done.stderr + done.stdout).decode("utf-8", errors="replace").strip().splitlines()
        )
        if done.returncode != 0:
            job.failed = f"вольт не собрался: код {done.returncode}"
            job.at = ""
            job.stage = "отказ"
            _drop_lock(session)
            job.ended = time.time()
            return
    for planet in job.planets:
        if job.stopping:
            break
        job.at = planet
        job.stage = "запуск"
        argv = [
            _python(),
            "-u",
            str(session.vault / "tools" / "landscape.py"),
            job.kind,
            "--planet",
            planet,
            *job.argv_extra,
        ]
        job.lines.append(f"$ {planet}: {job.kind} {' '.join(job.argv_extra)}".rstrip())
        try:
            child = subprocess.Popen(
                argv,
                cwd=session.vault,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except OSError as error:
            job.failed = f"{planet}: не запустился ({error})"
            break
        job.child = child
        #: The stop may have arrived while the child was being started: between
        #: the check above and this line there is a process launch, and a run
        #: told to stop must not go on to finish a planet.
        if job.stopping:
            child.kill()
        assert child.stdout is not None
        for line in child.stdout:
            said = line.rstrip()
            if said:
                job.lines.append(said)
                #: The tool prints «[ 155.4 s] plates: ...»; the stage is what
                #: follows the stamp, and it is what a progress line wants.
                job.stage = said.split("]", 1)[-1].strip() or said
        child.wait()
        job.child = None
        #: A killed child returns a code, and a stop is not a failure: reported
        #: as one, the person who pressed «Остановить» is told the build broke.
        if child.returncode != 0 and not job.stopping:
            job.failed = f"{planet}: вышел с кодом {child.returncode}"
            break
        if job.stopping:
            break
        job.done.append(planet)
    job.at = ""
    job.stage = "остановлено" if job.stopping else ("отказ" if job.failed else "готово")
    #: The mark goes **before** the run is called over. `ended` is what every
    #: reader watches for, and between it and the mark's removal a next run
    #: would be refused by a run that has already finished.
    _drop_lock(session)
    job.ended = time.time()


def field_build(session: Session, _query: dict, body: dict) -> dict:
    """Start a run of the landscape tool over one or more planets."""
    global _JOB
    kind = str(body.get("kind") or "build")
    if kind not in ("build", "census", "render", "all", "scan"):
        raise vault.VaultError(f"нет такой работы: {kind}")
    planets = [str(one) for one in (body.get("planets") or ["terra"])]
    unknown = [one for one in planets if one not in PLANETS]
    if unknown:
        raise vault.VaultError(f"нет такой планеты: {', '.join(unknown)}")
    extra: list[str] = []
    for name, flag in (("seed", "--seed"), ("step", "--step"), ("sea", "--sea"),
                       ("seeds", "--seeds"), ("focus", "--focus")):
        value = body.get(name)
        if value not in (None, ""):
            extra += [flag, str(value)]
    #: A run of `build` or `all` reads the built registry; the others only
    #: read a field that is already there and cannot be caught out by it.
    rebuild = kind in ("build", "all", "scan") and _stale_registry(session)
    with _JOB_LOCK:
        if _JOB is not None and _JOB.ended == 0.0:
            raise vault.VaultError(
                f"уже идёт работа: {_JOB.kind} над «{_JOB.at or '…'}»."
                " Дождитесь её или остановите."
            )
        job = Job(kind=kind, planets=planets, argv_extra=extra, rebuild=rebuild)
        _take_lock(session, job, bool(body.get("force")))
        _JOB = job
        threading.Thread(target=_run_job, args=(session, job), daemon=True).start()
    return {"job": job.state()}


def field_job(_session: Session, query: dict, _body: dict) -> dict:
    """What the run has said so far. `since` skips the lines already shown."""
    if _JOB is None:
        return {"job": None}
    state = _JOB.state()
    try:
        since = int((query.get("since") or ["0"])[0])
    except ValueError:
        since = 0
    state["total"] = len(state["lines"])
    state["since"] = max(0, since)
    state["lines"] = state["lines"][state["since"]:]
    return {"job": state}


def field_stop(_session: Session, _query: dict, _body: dict) -> dict:
    """Ask the run to stop: the child dies, the walk over the planets ends."""
    if _JOB is None or _JOB.ended != 0.0:
        return {"job": _JOB.state() if _JOB else None}
    _JOB.stopping = True
    child = _JOB.child
    if child is not None:
        child.kill()
    return {"job": _JOB.state()}


# ----------------------------------------------------------------- the state


def _number(entries: dict, key: str, fallback: float = 0.0) -> float:
    try:
        return float(entries.get(key))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _built(session: Session, planet: str) -> dict:
    """What lies in `build/field` for this planet, if anything does."""
    passport = session.vault / "build" / "field" / f"{planet}.json"
    data = session.vault / "build" / "field" / f"{planet}.npz"
    if not passport.is_file() or not data.is_file():
        return {"present": False}
    try:
        said = json.loads(passport.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"present": False, "unreadable": str(error)}
    grid = said.get("grid") or {}
    params = said.get("params") or {}
    return {
        "present": True,
        "digest": said.get("digest"),
        "nside": grid.get("nside"),
        "cells": grid.get("cells"),
        "side_m": grid.get("side_m"),
        "radius_m": grid.get("radius_m"),
        "seed": params.get("seed"),
        "version": params.get("version"),
        "relief_m": params.get("relief_m"),
        "land_share": said.get("land_share"),
        "height_max_m": said.get("height_max_m"),
        "megabytes": round(data.stat().st_size / 2**20, 1),
        "written": int(data.stat().st_mtime),
    }


def _pictures(session: Session, planet: str) -> list[dict]:
    """Which of the fifteen frames of this planet are drawn and lying ready."""
    out: list[dict] = []
    where = session.vault / "build" / "preview"
    for frame in FRAMES:
        for layer in LAYERS:
            name = f"{planet}_{frame}_{layer}.png"
            path = where / name
            if path.is_file():
                out.append({
                    "frame": frame,
                    "layer": layer,
                    "url": f"/preview/{name}",
                    "written": int(path.stat().st_mtime),
                })
    return out


def _worlds(session: Session, entries: dict) -> list[dict]:
    """Every planet worked out from the numbers as they stand in the file."""
    healpix = _healpix(session.vault)
    earth_km = _number(entries, "planet.earth_radius_km", 6371.0)
    step = _number(entries, "terrain.step_m", 50.0)
    shares = entries.get("planet.land_area_share")
    shares = shares if isinstance(shares, dict) else {}
    out: list[dict] = []
    for planet in PLANETS:
        share = float(shares.get(planet) or 0.0)
        radius_m = math.sqrt(share) * earth_km * 1000.0 if share > 0 else 0.0
        nside = healpix.nside_for(radius_m, step) if radius_m > 0 and step > 0 else 0
        cells = healpix.npix(nside) if nside else 0
        side = healpix.cell_side_m(radius_m, nside) if nside else 0.0
        out.append({
            "planet": planet,
            "share": share,
            "radius_km": round(radius_m / 1000.0, 2),
            "equator_km": round(2 * math.pi * radius_m / 1000.0, 1),
            "area_km2": round(4 * math.pi * radius_m**2 / 1e6),
            "nside": nside,
            "cells": cells,
            "side_m": round(side, 2),
            #: What the cell misses the asked-for step by: `nside` is whole, so
            #: it never lands on it exactly, and a big miss means the step was
            #: chosen without looking.
            "miss": round(side / step - 1.0, 4) if step else 0.0,
            "megabytes": round(cells * BYTES_PER_CELL / 2**20, 1),
            "about_seconds": round(cells / 1e6 * SECONDS_PER_MILLION),
            "horizon_m": round(math.sqrt(2.0 * (2 * radius_m + 2.0))) if radius_m else 0,
            "built": _built(session, planet),
            "pictures": _pictures(session, planet),
        })
    return out


def field_state(session: Session, _query: dict, _body: dict) -> dict:
    """The numbers that shape a field, the planets they come to, and the run."""
    file = session.open_constants()
    picked: list[dict] = []
    entries: dict[str, object] = {}
    for group in file.registry():
        rows = [one for one in group["constants"] if _is_field(one["key"])]
        if not rows:
            continue
        picked.append({**group, "constants": rows})
        for one in rows:
            entries[one["key"]] = one.get("value")
    try:
        worlds = _worlds(session, entries)
        missing = ""
    except vault.VaultError as error:
        #: The numbers are still worth showing and still worth editing: what
        #: is lost without the pipeline is only what it would come to.
        worlds, missing = [], str(error)
    return {
        "source": str(session.constants),
        "groups": picked,
        "worlds": worlds,
        "missing": missing,
        "layers": list(LAYERS),
        "frames": list(FRAMES),
        #: Whether a run would build what the cards show, or the world the
        #: registry was last built into. The tab says so before the button.
        "stale": _stale_registry(session),
        "totals": {
            "cells": sum(one["cells"] for one in worlds),
            "megabytes": round(sum(one["megabytes"] for one in worlds), 1),
            "about_seconds": sum(one["about_seconds"] for one in worlds),
        },
        "job": _JOB.state() if _JOB else None,
    }


ROUTES = {
    ("GET", "/api/field"): field_state,
    ("POST", "/api/field/run"): field_build,
    ("GET", "/api/field/job"): field_job,
    ("POST", "/api/field/stop"): field_stop,
}
