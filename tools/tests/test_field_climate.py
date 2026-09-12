# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Климат поля: марш влаги по кольцам (90-production/12 §4, D-335 п. 7).

Что закреплено:

* обмен влагой между кольцами широты сохраняет сумму, расплывает всплеск
  на соседей и ничего не теряет на полюсах;
* марш этим обменом пользуется: кольцо суши между кольцами моря без обмена
  сохнет само по себе, с обменом его поят соседи.

На крошечной сетке, как и остальное поле (`test_field.py`).
"""

from __future__ import annotations

import numpy as np
import pytest

from field import climate
from field.grid import Grid


def test_moisture_mixes_across_rings() -> None:
    """Обмен влагой между кольцами (поле 13): сумма сохраняется, всплеск на
    одном кольце расплывается на соседей, и ничего не уходит за полюса."""
    spike = np.zeros(9)
    spike[4] = 1.0
    once = climate._mixed(spike, climate.MERIDIONAL_MIX)
    assert once.sum() == pytest.approx(1.0)
    assert once[4] == pytest.approx(1.0 - climate.MERIDIONAL_MIX)
    assert once[3] == once[5] == pytest.approx(0.5 * climate.MERIDIONAL_MIX)
    #: Полюс меняется с одним соседом и сам с собой: край не теряет влагу.
    edge = np.zeros(4)
    edge[0] = 1.0
    assert climate._mixed(edge, climate.MERIDIONAL_MIX).sum() == pytest.approx(1.0)
    #: Ровное поле ровным и остаётся.
    flat = np.full(7, 0.3)
    assert np.allclose(climate._mixed(flat, climate.MERIDIONAL_MIX), flat)


def test_the_march_trades_moisture_between_rings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Марш пользуется обменом: одно кольцо суши среди колец моря без обмена
    сохнет само по себе, с обменом его поят соседние кольца — осадки на
    нём выше, а море как не дождило, так и не дождит."""
    grid = Grid.of(99_600.0, 12_000.0)
    table, lengths = grid.rings
    ring = table.shape[0] // 2
    sea = np.ones(grid.count, dtype=bool)
    sea[table[ring, : lengths[ring]]] = False
    height = np.zeros(grid.count)
    dryness = np.ones(grid.count)

    share = climate.MERIDIONAL_MIX

    def marched(mix: float) -> np.ndarray:
        monkeypatch.setattr(climate, "MERIDIONAL_MIX", mix)
        return climate._march(grid, height, sea, 1, 1000.0, dryness)

    alone = marched(0.0)
    fed = marched(share)
    assert fed[~sea].mean() > alone[~sea].mean()
    assert np.all(fed[sea] == 0.0)
    assert np.all(alone[sea] == 0.0)
