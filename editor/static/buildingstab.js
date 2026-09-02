// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The «Здания» tab's glue (D-218): a board instead of a graph, because the
// types make nothing out of each other -- they are compared.

import * as buildings from './buildings.js';
import { h, plural } from './ui.js';

export function createBuildingsTab(ctx) {
  const { app, dom, say, reportRun, panel } = ctx;

  const meta = {
    kind: 'board',
    placeholder: 'поиск: тип здания или материал в составе',
    buttons: ['act-new-building'],
  };

  function renderFilters() {
    const rows = app.state.buildings || [];
    dom.filters.replaceChildren(h('span', {
      class: 'note-line',
      text: `${rows.length} ${plural(rows.length, 'тип', 'типа', 'типов')} зданий · `
        + 'состав, цена этажа и порча — у каждого свои',
    }));
  }

  function renderList() {
    buildings.renderList(dom.list, app.state.buildings || [], {
      selected: app.building,
      query: app.query,
      onSelect: (kind) => select(kind),
    });
  }

  function renderLegend() {
    dom.legend.replaceChildren(
      h('span', { text: 'тип решает три вещи разом: из чего построено, во сколько раз '
        + 'дорожает следующий этаж и как быстро дом ветшает' }),
      h('span', { text: '· пятно ограничено участком, высота — нет' }),
      h('span', { text: '· правки уходят в data/constants.yaml, vocabulary.yaml и locales/' }),
    );
  }

  function draw() {
    buildings.renderBoard(dom.board, app.state.buildings || [], {
      selected: app.building,
      footprint: app.footprint,
      onFootprint: (value) => { app.footprint = value; draw(); },
    });
  }

  // Выбор типа здания идёт своим путём: у него нет узла в графе и нет строки в
  // словаре вольта — есть только имя в карте констант.
  function select(kind) {
    app.building = kind;
    renderList();
    draw();
    panel.openBuilding(kind);
  }

  /** The form on the right for what is picked, or nothing. */
  function reopen() {
    if (app.building) panel.openBuilding(app.building); else panel.clear();
  }

  function enter() {
    ctx.refresh();
    reopen();
  }

  function openNew() {
    app.building = null;
    renderList();
    panel.openNewBuilding();
  }

  async function afterWrite(result, openKind) {
    app.building = openKind || null;
    await ctx.reload();
    if (result && result.check) reportRun(result.check, 'проверка вольта');
    else say('записано', false, 'записано');
    renderList();
    draw();
    reopen();
  }

  return { meta, renderFilters, renderList, renderLegend, draw, select, enter, reopen, openNew, afterWrite };
}
