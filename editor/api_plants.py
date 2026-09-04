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

import json
from typing import Any

import ladder as model
import localefile as words
import plantsfile as plants_source
import store
from session import Session, names_writes, need, spoken_names
from vaultfile import VaultError

#: Where a culture's names live in the locale files (D-251): the culture and
#: its wild ancestor among the plants (D-260), the seed among the goods -- the
#: build derives `<id>_seeds` from the culture and then refuses a vault where
#: that has no name in some language (`seed_ids`, `check_locales`).
PLANTS = "plants"
GOODS = "goods"
WILD = "_wild"
SEEDS = "_seeds"
#: The class whose members may be fed to a growing bed (D-296, D-291), by the
#: stable key rather than by its Russian name: a class renamed in the vault
#: would otherwise empty the palette without a word (D-251).
FERTILIZER_ID = "fertilizer"
#: Where the stages of growth are written (D-296): the build reads them from
#: this constant, and so does the form.
STAGE_BOUNDS = "farm.stage_bounds"
#: The hours of labour every raw thing yields (D-136): a culture whose
#: produce is not in it has no derivable yield, and the build says so.
HARVEST_RATES = "harvest.rates"


def wild_id(plant_id: str) -> str:
    return f"{plant_id}{WILD}"


def seed_id(plant_id: str) -> str:
    """The seed's key, derived the way the build derives it (`seed_ids`)."""
    return f"{plant_id}{SEEDS}"


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
        "stages": list(_stages(session)),
        "palette": _palette(ladder, _reaped(session)),
        #: What the last build derived about each culture: the generosity
        #: and its ceiling (D-057) -- the number the rule "good at
        #: everything must not exist" is actually measured by. Read here
        #: rather than recomputed: the build is the authority (D-136).
        "derived": _derived(session),
        "names": {
            str(one.get("id")): {
                "name": spoken_names(session, PLANTS, str(one.get("id"))),
                "wild": spoken_names(session, PLANTS, wild_id(str(one.get("id")))),
                "seed": spoken_names(session, GOODS, seed_id(str(one.get("id")))),
            }
            for one in rows
        },
        "languages": session.languages(),
    }


def _stages(session: Session) -> tuple[str, ...]:
    """The stages of growth as the vault has them (D-296)."""
    return plants_source.stages_of(session.open_constants().value(STAGE_BOUNDS))


def _reaped(session: Session) -> list[str]:
    """What a culture may give: the raw things whose hour of labour is known.

    Read from the **built** constants, not from the source: `harvest.rates` is
    `value_from: materials` -- the build fills it from the material registry,
    and the file itself holds only that word. A vault never built yet gives
    nothing back, and then the form offers everything rather than nothing.
    """
    built = session.vault / "build" / "constants.json"
    if not built.is_file():
        return []
    try:
        rates = json.loads(built.read_text(encoding="utf-8")).get(HARVEST_RATES)
    except (OSError, json.JSONDecodeError):  # pragma: no cover -- a build half written
        return []
    return sorted(rates) if isinstance(rates, dict) else []


def _derived(session: Session) -> dict[str, dict]:
    """Generosity and its cap per culture, from the last build."""
    built = session.vault / "build" / "plants.json"
    if not built.is_file():
        return {}
    try:
        rows = json.loads(built.read_text(encoding="utf-8")).get("plants") or []
    except (OSError, json.JSONDecodeError):  # pragma: no cover -- half written
        return {}
    return {
        str(one.get("id")): {
            "generosity": one.get("generosity"),
            "generosity_cap": one.get("generosity_cap"),
            "yield_per_m2": one.get("yield_per_m2"),
        }
        for one in rows
        if one.get("id")
    }


def _palette(ladder: model.Ladder, reaped: list[str]) -> dict:
    """What a culture may name: goods it yields and things it is fed with.

    The produce is offered from `harvest.rates` rather than from everything
    the vault knows: a culture whose produce has no rate has no derivable
    yield (D-136), and a list of two hundred things would suggest a hundred
    and sixty the build refuses. The fertilizers come back as **ids**, not
    as names: the feeding table is read through the stable keys of D-251,
    and the form must offer exactly what the file holds.
    """
    goods = sorted(set(ladder.recipes) | set(ladder.materials) | set(ladder.op_outputs))
    klass = next(
        (name for name, key in ladder.class_ids.items() if key == FERTILIZER_ID), None
    )
    fertilizers = sorted(
        {
            str(recipe["id"])
            for name in (ladder.classes.get(klass) or [])
            if (recipe := ladder.recipes.get(name)) and recipe.get("id")
        }
    )
    return {"goods": goods, "reaped": reaped, "fertilizers": fertilizers}


def plant_put(session: Session, query: dict, body: dict) -> dict:
    """Add or change one culture, with its names in every language.

    `fresh` is the "+ культура" button rather than the form of one already
    open: an id that is taken is a refusal, not a silent overwrite of somebody
    else's crop.
    """
    fresh = (query.get("fresh") or [""])[0] == "1"
    was_id = (query.get("was") or [None])[0]
    data = plants_source.clean_plant(body.get("data") or {}, stages=_stages(session))
    if was_id and was_id != data["id"]:
        #: The same rule the material registry lives by: an id is what the
        #: engine, the base and the wire know a culture by (D-251), and a
        #: form that renamed it would leave two cultures and one name.
        raise VaultError(
            "культура не переименовывается формой: на идентификатор ссылаются "
            "семена, сорта и сохранённые делянки. Переименование — отдельный шаг."
        )
    #: A new culture must be named in every language -- the build refuses the
    #: rest, and the person should learn it here rather than a check later. A
    #: form that sent no names at all means "leave the names as they are": that
    #: is how a thing's registry row behaves, and a culture is no different.
    #: What the build would refuse anyway, refused here -- while the person
    #: is still at the field rather than a check later.
    _, ladder = session.open()
    reaped = _reaped(session)
    if reaped and data["gives"] not in reaped:
        raise VaultError(
            f"«{data['gives']}» нет в `harvest.rates`: без часа труда урожайность не вывести (D-136)"
        )
    fertilizers = set(_palette(ladder, reaped)["fertilizers"])
    for row in data["feeding"]:
        if fertilizers and row["fertilizer"] not in fertilizers:
            raise VaultError(f"«{row['fertilizer']}» — не вещь класса «Удобрение» (D-291)")
    languages = session.languages()
    names = _named(body.get("names"), languages, data["name"], fresh)
    wild = _named(body.get("wild"), languages, data["wild_name"], fresh)
    seed = _named(body.get("seed"), languages, data["seed"], fresh)
    with session.lock:
        file = session.open_plants()
        lines, doc = file.put_plant(data, fresh=fresh, stages=_stages(session))
        writes = [
            store.prepare_doc(session.plants, lines, doc, file.mtime, file.newline),
            #: All three names in one write per file: they lie side by side,
            #: and separate writes would land one on top of another.
            *names_writes(
                session,
                [
                    (PLANTS, data["id"], names, False, None),
                    (PLANTS, wild_id(data["id"]), wild, False, None),
                    (GOODS, seed_id(data["id"]), seed, False, None),
                ],
            ),
        ]
        store.commit(*writes)
    return {"saved": data["id"], "check": session.check()}


def _named(given: Any, languages: list[str], what: str, fresh: bool) -> dict[str, str] | None:
    if given is None and not fresh:
        return None
    return words.clean_names(given, languages, what)


def plant_delete(session: Session, query: dict, _body: dict) -> dict:
    """Take a culture out, with its names in every language."""
    plant_id = need(query, "id")
    with session.lock:
        file = session.open_plants()
        lines, doc = file.drop_plant(plant_id)
        writes = [
            store.prepare_doc(session.plants, lines, doc, file.mtime, file.newline),
            *names_writes(
                session,
                [
                    (PLANTS, plant_id, None, True, None),
                    (PLANTS, wild_id(plant_id), None, True, None),
                    (GOODS, seed_id(plant_id), None, True, None),
                ],
            ),
        ]
        store.commit(*writes)
    return {"deleted": plant_id, "check": session.check()}


ROUTES = {
    ("GET", "/api/plants"): plants,
    ("PUT", "/api/plant"): plant_put,
    ("DELETE", "/api/plant"): plant_delete,
}
