# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The handlers for `data/plants.yaml`: the cultures of Terra (D-057, D-136).

A culture is not only a block in its own file. Its name and its wild
ancestor's live in every language beside it (D-251, D-260), and the build
refuses a culture whose name some language does not know -- so both are asked
for in the same form and written under the same stamp, the way a thing's name
is. Undo takes them back together.

The numbers the cultures live by -- the moisture bands, the pests, the guard
of a treatment -- are not here: they are constants like every other number of
the game (D-065), and the tab shows them through the constants API rather
than keeping a second door to the same file.
"""

from __future__ import annotations

import ladder as model
import localefile as words
import plantsfile as plants_source
import store
from session import Session, name_writes, need, spoken_names

#: Where a culture's name lives in the locale files (D-251), and how the wild
#: ancestor's key is made from the culture's own (D-260).
PLANTS = "plants"
WILD = "_wild"
#: The class whose members may be fed to a growing bed (D-296, D-291).
FERTILIZER = "Удобрение"


def wild_id(plant_id: str) -> str:
    return f"{plant_id}{WILD}"


def plants(session: Session, _query: dict, _body: dict) -> dict:
    """The cultures, what may be written into them, and their names abroad.

    The palettes come with the list rather than being asked for separately:
    whoever opens a culture wants the fertilizers and the goods in front of
    them, and a second round trip would only make the tab open slower.
    """
    file = session.open_plants()
    _, ladder = session.open()
    rows = file.doc.get(plants_source.SECTION) or []
    return {
        "source": str(session.plants),
        "plants": rows,
        "stages": list(plants_source.STAGES),
        "palette": _palette(ladder),
        "names": {
            str(one.get("id")): {
                "name": spoken_names(session, PLANTS, str(one.get("id"))),
                "wild": spoken_names(session, PLANTS, wild_id(str(one.get("id")))),
            }
            for one in rows
        },
        "languages": session.languages(),
    }


def _palette(ladder: model.Ladder) -> dict:
    """What a culture may name: goods it yields and things it is fed with.

    The fertilizers come back as **ids**, not as names: the feeding table is
    read by the engine through the stable keys of D-251, and the form must
    offer exactly what the file holds.
    """
    goods = sorted(set(ladder.recipes) | set(ladder.materials) | set(ladder.op_outputs))
    fertilizers = sorted(
        {
            str(recipe["id"])
            for name in ladder.classes.get(FERTILIZER, [])
            if (recipe := ladder.recipes.get(name)) and recipe.get("id")
        }
    )
    return {"goods": goods, "fertilizers": fertilizers}


def plant_put(session: Session, query: dict, body: dict) -> dict:
    """Add or change one culture, with its names in every language.

    `fresh` is the "+ культура" button rather than the form of one already
    open: an id that is taken is a refusal, not a silent overwrite of somebody
    else's crop.
    """
    fresh = (query.get("fresh") or [""])[0] == "1"
    data = plants_source.clean_plant(body.get("data") or {})
    languages = session.languages()
    names = words.clean_names(body.get("names"), languages, data["name"])
    wild = words.clean_names(body.get("wild"), languages, data["wild_name"])
    was_id = (query.get("was") or [None])[0]
    with session.lock:
        file = session.open_plants()
        lines, doc = file.put_plant(data, fresh=fresh)
        writes = [
            store.prepare_doc(session.plants, lines, doc, file.mtime, file.newline),
            *name_writes(session, PLANTS, data["id"], names, was_id=was_id),
            *name_writes(
                session,
                PLANTS,
                wild_id(data["id"]),
                wild,
                was_id=wild_id(was_id) if was_id else None,
            ),
        ]
        store.commit(*writes)
    return {"saved": data["id"], "check": session.check()}


def plant_delete(session: Session, query: dict, _body: dict) -> dict:
    """Take a culture out, with its names in every language."""
    plant_id = need(query, "id")
    with session.lock:
        file = session.open_plants()
        lines, doc = file.drop_plant(plant_id)
        writes = [
            store.prepare_doc(session.plants, lines, doc, file.mtime, file.newline),
            *name_writes(session, PLANTS, plant_id, None, gone=True),
            *name_writes(session, PLANTS, wild_id(plant_id), None, gone=True),
        ]
        store.commit(*writes)
    return {"deleted": plant_id, "check": session.check()}


ROUTES = {
    ("GET", "/api/plants"): plants,
    ("PUT", "/api/plant"): plant_put,
    ("DELETE", "/api/plant"): plant_delete,
}
