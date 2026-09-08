# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""The handlers for the sky (D-289, D-316, D-319, D-320, D-322, D-324).

The numbers of space are scattered through `data/constants.yaml` by group --
a planet's two sizes sit under `planet`, the circle a hull moors on under
`orbit`, the height the camera changes bands at under `map`, the hours of a
climb under `ship` -- and nobody tuning the sky wants to walk four groups and
hold the arithmetic in their head. This gathers them and works the arithmetic
out loud.

**Everything here is derived, and nothing here is stored.** The editor writes
constants through the same handler the «Константы» tab uses; this endpoint
only reads them and says what they come to. The formulas mirror the engine's,
and each one names the function it mirrors -- if the two ever part, the engine
is right and this is the defect.
"""

from __future__ import annotations

import math

import vaultfile as vault
from session import Session

#: The groups a sky number can live in, and the keys of `map` and `ship` that
#: belong to the sky rather than to a map or a hull. A prefix alone would drag
#: in the whole of `ship`, most of which is a shipyard's business.
SKY_PREFIXES = ("planet.", "orbit.")
SKY_KEYS = (
    "map.sky_unit_km",
    "map.approach_km",
    "ship.ascent_hours",
    "ship.descent_hours",
    "ship.reference_ratio",
    "ship.min_thrust_ratio",
)

#: The density of the Earth, g/cm³: the one number here that is nature's and
#: not the vault's, and the scale every other density is read against.
EARTH_DENSITY = 5.514
HOURS_PER_DAY = 24.0


def _is_sky(key: str) -> bool:
    return key.startswith(SKY_PREFIXES) or key in SKY_KEYS


def space(session: Session, _query: dict, _body: dict) -> dict:
    """The sky's numbers, and every world worked out from them."""
    file = session.open_constants()
    groups = file.registry()
    entries: dict[str, object] = {}
    picked: list[dict] = []
    for group in groups:
        rows = [one for one in group["constants"] if _is_sky(one["key"])]
        if not rows:
            continue
        picked.append({**group, "constants": rows})
        for one in rows:
            entries[one["key"]] = one.get("value")
    return {
        "source": str(session.constants),
        "groups": picked,
        "worlds": _worlds(entries),
        "missing": [],
    }


def _number(entries: dict, key: str, fallback: float = 0.0) -> float:
    value = entries.get(key)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _table(entries: dict, key: str) -> dict:
    value = entries.get(key)
    return value if isinstance(value, dict) else {}


def _worlds(entries: dict) -> list[dict]:
    """Every world of the vault, with what its numbers come to.

    The order is the one the vault writes them in, so a table read here and a
    table read in `constants.yaml` are the same table.
    """
    mass = _table(entries, "planet.mass")
    radius = _table(entries, "planet.radius")
    land = _table(entries, "planet.land_area_share")
    earth_km = _number(entries, "planet.earth_radius_km", 6371.0)
    planet_mu = _number(entries, "orbit.planet_mu")
    body_scale = _number(entries, "orbit.body_radius")
    park_radii = _number(entries, "orbit.park_radii")
    capture_radii = _number(entries, "orbit.capture_radii")
    ascent = _number(entries, "ship.ascent_hours")
    descent = _number(entries, "ship.descent_hours")
    sky_unit_km = _number(entries, "map.sky_unit_km", 1.0)
    #: Where each world circles (D-271, in the vault since 2026-09-08). The
    #: **radius is not stored**: the year is the tuned number and the radius
    #: follows it by Kepler against Terra's pair -- `sky.circle_of`.
    periods = _table(entries, "orbit.period_days")
    phases = _table(entries, "orbit.phase")
    terra_days = _number(periods, "terra", 1.0)
    terra_orbit = _number(entries, "orbit.terra_radius")

    out: list[dict] = []
    for key in mass:
        m = _number(mass, key)
        r = _number(radius, key)
        if m <= 0 or r <= 0:
            raise vault.VaultError(f"у мира «{key}» масса или радиус не число больше нуля")
        share = _number(land, key)
        #: `engine.ship.physics.gravity`: the pull at the surface is the pair,
        #: never a number of its own (D-320).
        gravity = m / (r * r)
        density = EARTH_DENSITY * m / (r * r * r)
        #: `globe.radius_m`: the land one walks is a sphere of the area the
        #: vault gives it, and has nothing to do with the body above (D-324).
        land_radius_km = math.sqrt(share) * earth_km if share > 0 else 0.0
        land_area = 4 * math.pi * (land_radius_km**2)
        #: `sky._base._body_of` and `sky.park_of` / `sky.capture_of`.
        drawn = body_scale * r
        park = park_radii * drawn
        capture = capture_radii * drawn
        mu = planet_mu * m
        circle = math.sqrt(mu / park) if park > 0 else 0.0
        escape = (math.sqrt(2 * mu / park) - circle) if park > 0 else 0.0
        lap_hours = (2 * math.pi * park / circle) * HOURS_PER_DAY if circle > 0 else 0.0
        out.append(
            {
                "key": key,
                "mass": m,
                "radius": r,
                "body_km": r * earth_km,
                "gravity": gravity,
                "density": density,
                "land_share": share,
                "land_radius_km": land_radius_km,
                "land_area_km2": land_area,
                "equator_km": 2 * math.pi * land_radius_km,
                "drawn_units": drawn,
                #: How much larger than life the body is drawn (D-320's reason:
                #: a minute-stepped tick cannot hit a true-scale world).
                "drawn_times": (drawn * sky_unit_km / (r * earth_km)) if r > 0 else 0.0,
                "park_units": park,
                "capture_units": capture,
                "mu": mu,
                "circle_speed": circle,
                "escape_dv": escape,
                "lap_hours": lap_hours,
                "climb_hours": ascent * gravity,
                "fall_hours": descent * gravity,
                "period_days": _number(periods, key),
                "phase": _number(phases, key),
                "orbit_units": (
                    terra_orbit * (_number(periods, key) / terra_days) ** (2.0 / 3.0)
                    if terra_days > 0 and _number(periods, key) > 0
                    else 0.0
                ),
            }
        )
    return out


ROUTES = {("GET", "/api/space"): space}
