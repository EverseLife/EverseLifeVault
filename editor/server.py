# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The local server of the recipe editor.

Standard library only, on purpose: the tool has to start in a fresh clone with
nothing but `pyyaml` -- the same single dependency the vault's own build has.
It binds to the loopback address and to nothing else: it writes files, and a tool
that writes files has no business listening on the network.

    python editor/server.py

The handlers live by subject -- `api_things` for the ladder, `api_buildings`
for the constants file, `api_world` for the map -- and this module is the
door: the state the page opens with, the vault's own tools, and the plumbing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import api_buildings
import api_world
import store
import vaultfile as vault
from api_buildings import (  # noqa: F401
    building_create,
    building_delete,
    building_update,
    constant_create,
    constant_delete,
    constant_update,
    constants,
)
from api_things import (  # noqa: F401 -- re-exported for the tests and the routes
    cost,
    create,
    delete,
    drop_class,
    material_create,
    material_delete,
    material_update,
    measure,
    membership,
    put_class,
    recipe,
    update,
)
from api_world import world  # noqa: F401
from session import Session  # noqa: F401 -- the tests build one from here

STATIC = Path(__file__).resolve().parent / "static"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}


# ------------------------------------------------------------------ handlers


def state(session: Session, _query: dict, _body: dict) -> dict:
    file, ladder = session.open()
    return {
        "vault": str(session.vault),
        "source": str(session.source),
        "stale": ladder.stale,
        "nodes": ladder.nodes(),
        "edges": ladder.edges(),
        "operations": [
            {
                "name": op["name"],
                "requires": op.get("requires") or [],
                "gives": op.get("gives") or [],
                "consumes": op.get("consumes") or [],
                "place": op.get("place"),
            }
            for op in ladder.operations
        ],
        "stations": ladder.stations(),
        #: Building types (D-218). Read from the constants file, not the recipe
        #: one -- but shown in the same window, because a type is a composition
        #: and a composition is what this tool is about.
        "buildings": api_buildings.buildings(session),
        "constants_source": str(session.constants),
        "vocabulary": ladder.vocabulary(),
        #: The other languages of the game (D-251): what each calls every
        #: thing, so the form shows the English name beside the Russian one
        #: and asks for it when a thing is new.
        "languages": session.languages(),
        "locales": {file.lang: file.doc for file in session.open_locales()},
        #: Where a thing may lie for the gatherer (D-254): the place properties
        #: the world's check accepts, the same closed list the «Мир» tab uses.
        "places": sorted(api_world.worldtool.WORLD_PROPERTIES),
        "counts": {
            "recipes": len(ladder.recipes),
            "raw": len(ladder.raw),
            "materials": len(ladder.materials),
            "classes": len(ladder.class_notes),
            "operations": len(ladder.operations),
        },
        "undo": (backup.name if (backup := store.last_backup()) else None),
    }


def undo(session: Session, _query: dict, _body: dict) -> dict:
    #: Which files are rolled back is decided by which edit was the newest, not
    #: by the tab in front of the person: the editor writes five of them, and
    #: one edit may have touched two. The backups' names say which.
    with session.lock:
        restored = store.undo(session.source)
    return {"restored": restored, "check": session.check()}


def check(session: Session, _query: dict, _body: dict) -> dict:
    return session.check()


def build(session: Session, _query: dict, _body: dict) -> dict:
    return session.run("tools/build.py")


def masses(session: Session, _query: dict, _body: dict) -> dict:
    """Recompute every item's mass out of its inputs and report (D-228).

    Writes nothing, and that is the point: mass is derived, and derived numbers
    are shown, never written back into the source (D-133). Written back, an
    auto mass would become an authored one on the next read and stop counting
    itself -- so the answer to "why is this one not moving" is the report,
    which names every item whose mass is pinned by hand.
    """
    return session.run("tools/build.py", "--masses")


ROUTES = {
    ("GET", "/api/state"): state,
    ("GET", "/api/recipe"): recipe,
    ("GET", "/api/cost"): cost,
    ("POST", "/api/recipe"): create,
    ("PUT", "/api/recipe"): update,
    ("DELETE", "/api/recipe"): delete,
    ("POST", "/api/material"): material_create,
    ("PUT", "/api/material"): material_update,
    ("DELETE", "/api/material"): material_delete,
    ("PUT", "/api/measure"): measure,
    ("PUT", "/api/class"): put_class,
    ("DELETE", "/api/class"): drop_class,
    ("PUT", "/api/classes"): membership,
    **api_buildings.ROUTES,
    **api_world.ROUTES,
    ("POST", "/api/masses"): masses,
    ("POST", "/api/check"): check,
    ("POST", "/api/build"): build,
    ("POST", "/api/undo"): undo,
}


# -------------------------------------------------------------------- server


class Handler(BaseHTTPRequestHandler):
    session: Session

    protocol_version = "HTTP/1.1"
    server_version = "vault-editor"

    def do_GET(self) -> None:  # noqa: N802 -- the name is the stdlib's
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._api("GET", parsed)
            return
        self._static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        self._api("POST", urlparse(self.path))

    def do_PUT(self) -> None:  # noqa: N802
        self._api("PUT", urlparse(self.path))

    def do_DELETE(self) -> None:  # noqa: N802
        self._api("DELETE", urlparse(self.path))

    def log_message(self, fmt: str, *args: Any) -> None:
        if "500" in str(args) or "400" in str(args):
            super().log_message(fmt, *args)

    # -- plumbing ----------------------------------------------------------

    def _api(self, method: str, parsed) -> None:
        route = ROUTES.get((method, parsed.path))
        if route is None:
            self._send(404, {"error": f"нет такого адреса: {method} {parsed.path}"})
            return
        try:
            body = self._body()
            payload = route(self.session, parse_qs(parsed.query), body)
            self._send(200, payload)
        except vault.VaultError as error:
            self._send(400, {"error": str(error)})
        except Exception as error:  # noqa: BLE001 -- a dev tool reports, not dies
            import traceback

            self._send(500, {"error": f"{type(error).__name__}: {error}",
                             "trace": traceback.format_exc()})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def _static(self, path: str) -> None:
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC / name).resolve()
        if not target.is_file() or STATIC.resolve() not in target.parents:
            self._send(404, {"error": f"нет файла: {name}"})
            return
        payload = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "text/plain"))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Редактор рецептов вольта Everse.Life")
    port = int(os.environ.get("EVERSELIFE_EDITOR_PORT", 8765))
    parser.add_argument("--port", type=int, default=port)
    parser.add_argument("--vault", default=None, help="путь к вольту гейм-дизайна")
    # Loopback by default: the tool writes files. Inside a container the loop is
    # its own and unreachable from outside, so the image starts the server on
    # 0.0.0.0 -- the boundary there is the port mapping, not the address.
    parser.add_argument(
        "--host",
        default=os.environ.get("EVERSELIFE_EDITOR_HOST", "127.0.0.1"),
        help="адрес, на котором слушать (по умолчанию только петля)",
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if args.vault:
        os.environ["EVERSELIFE_VAULT"] = args.vault
    try:
        root = vault.vault_root()
    except vault.VaultError as error:
        print(error, file=sys.stderr)
        return 1

    #: Backups belong to the vault being edited, not to the copy of the code
    #: doing the editing: two editors pointed at two vaults from one checkout
    #: would otherwise share one history, and one's undo would eat the other's.
    if not os.environ.get("EVERSELIFE_EDITOR_BACKUPS"):
        store.BACKUPS = root / "editor" / "backups"

    Handler.session = Session(root)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host  # noqa: S104
    url = f"http://{shown}:{args.port}/"
    print(f"Редактор рецептов: {url}")
    print(f"Вольт: {root}")
    print(
        "Правятся data/recipes.yaml, constants.yaml, world.yaml, vocabulary.yaml и locales/. "
        "Ctrl+C — выход."
    )
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nВыход.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
