// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The «Станции» tab: the tree of assembly (D-106) -- the workbench is made by
// hand, everything else on the workbench or deeper -- plus the stations that go
// into other stations as parts.

import { KIND_COLOUR } from './graphview.js';
import { listRow, nothingFound } from './ladderkit.js';
import { h, plural } from './ui.js';

export function createStationsTab(ctx) {
  const { app, dom } = ctx;

  const meta = {
    kind: 'graph',
    sliders: false,
    placeholder: 'поиск: станция или что на ней делают',
    allLabel: 'Все станции',
    focusTitle: 'что делают на выбранной станции и куда она входит',
    buttons: ['act-new-material'],
  };

  const node = (name) => ctx.nodeOf(name) || { name, type: 'virtual', depth: 0 };

  function renderFilters() {
    // Фильтровать нечего: станции и так один тип. Вместо фишек — счёт.
    const idle = app.state.stations.filter((item) => !item.makes.length).length;
    dom.filters.replaceChildren(h('span', {
      class: 'note-line',
      text: `${app.state.stations.length} станций, из них ${idle} пока ничего не делают`,
    }));
  }

  // Станции идут по ступеням, а не по алфавиту: список читается как порядок, в
  // котором город их себе ставит.
  function renderList() {
    const query = app.query.trim().toLowerCase();
    const visible = app.state.stations.filter((item) => !query
      || [item.name, item.parent || '', ...item.makes].join(' ').toLowerCase().includes(query));

    const out = [];
    let rung = null;
    for (const item of visible) {
      if (item.depth !== rung) {
        rung = item.depth;
        out.push(h('div', {
          class: 'group',
          text: item.virtual ? 'без станции' : `ступень ${rung ?? '—'}`,
        }));
      }
      out.push(listRow(node(item.name), item.name, { selected: app.selected, onSelect: ctx.select },
        h('span', {
          class: 'st',
          title: 'рецептов на этой станции · где она сама стоит входом',
          text: item.makes.length
            ? `${item.makes.length}${item.inputs_to.length ? ` · ↑${item.inputs_to.length}` : ''}`
            : '—',
        }),
      ));
    }
    if (!out.length) out.push(nothingFound());
    dom.list.replaceChildren(...out);
  }

  function renderLegend() {
    dom.legend.replaceChildren(
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.station}` }), 'станция'),
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.virtual}` }), 'руками и стройка'),
      h('span', { text: '· сплошная стрелка — на чём станция собирается' }),
      h('span', { text: '· пунктир — что на ней делают' }),
      h('span', { text: '· точки — станция входит в состав' }),
      h('span', { text: '· двойной щелчок — раскрыть одну станцию' }),
    );
  }

  function picture() {
    const list = app.state.stations;
    if (app.mode === 'all') {
      const nodes = list.map((item) => node(item.name));
      const shown = new Set(nodes.map((item) => item.name));
      const edges = [];
      for (const item of list) {
        if (item.parent && shown.has(item.parent)) {
          edges.push({ from: item.parent, to: item.name, rel: 'station', via: 'собирается на' });
        }
        for (const target of item.inputs_to) {
          if (shown.has(target)) {
            edges.push({ from: item.name, to: target, rel: 'part', via: 'входит в' });
          }
        }
      }
      dom.hint.textContent = `${list.length} станций`;
      return { nodes, edges };
    }

    const chosen = ctx.station(app.selected);
    if (!chosen) {
      dom.hint.textContent = 'выберите станцию';
      return { nodes: [], edges: [] };
    }
    const edges = [];
    const names = new Set([chosen.name]);
    if (chosen.parent) {
      names.add(chosen.parent);
      edges.push({ from: chosen.parent, to: chosen.name, rel: 'station', via: 'собирается на' });
    }
    for (const made of chosen.makes) {
      names.add(made);
      edges.push({ from: chosen.name, to: made, rel: 'made', via: 'делается здесь' });
    }
    for (const target of chosen.inputs_to) {
      names.add(target);
      edges.push({ from: chosen.name, to: target, rel: 'part', via: 'входит в' });
    }
    dom.hint.textContent = `«${chosen.name}»: ${chosen.makes.length} `
      + `${plural(chosen.makes.length, 'рецепт', 'рецепта', 'рецептов')}`
      + (chosen.operations.length ? `, операций ${chosen.operations.length}` : '');
    return { nodes: [...names].map(node), edges };
  }

  const draw = () => ctx.drawPicture(picture());

  // Фокусу нечего показывать, если выбранное — не станция.
  return { meta, renderFilters, renderList, renderLegend, draw, focusable: (name) => !!ctx.station(name) };
}
