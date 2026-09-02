// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The «Мир» tab's glue (D-243): what is loaded, what is picked, what is written.
//
// Раскладка стартового мира живёт в третьем файле вольта и читается своим
// запросом: она не лестница, у неё нет ни ступеней, ни составов, и класть её в
// общее состояние значило бы возить карту вместе с рецептами при каждой правке.
// Its own module for the same reason the map has its own canvas: nothing here
// is about recipes, and `app.js` only needs to know when to call it.

import { api } from './api.js';
import { ask, h } from './ui.js';
import * as worldmap from './world.js';
import * as worldform from './worldform.js';

/**
 * `ctx` is what the tab borrows from the page: the shared state, the DOM it
 * draws into, the strip that reports, and `refresh` -- the page's own
 * "redraw everything about the current tab".
 */
export function createWorldTab(ctx) {
  const { app, dom, say, reportRun } = ctx;

  const meta = {
    kind: 'map',
    placeholder: 'поиск: узел, станок, жила или вещь в нём',
    buttons: ['act-new-node'],
  };

  async function load(keepPick = true) {
    app.world = await api.world();
    const groups = worldmap.groups(app.world.nodes).map((one) => one.group);
    if (!groups.includes(app.worldGroup)) app.worldGroup = groups[0] || null;
    if (!keepPick || !known(app.worldPick)) app.worldPick = null;
    ctx.refresh();
    openForm();
  }

  function known(pick) {
    if (!pick) return false;
    if (pick.startsWith('pocket:')) return pick.slice(7) in (app.world.pockets || {});
    return app.world.nodes.some((node) => node.key === pick);
  }

  // Карта — своя у каждой группы: застройка одного города, поверхность одной
  // планеты, помещения одного дома. Их не смешивают: у двух планет нет общей
  // земли, и рисовать их вместе значило бы врать про расстояния.
  function renderFilters() {
    if (!app.world) return;
    dom.filters.replaceChildren(
      ...worldmap.groups(app.world.nodes).map(({ group, members }) => h('button', {
        class: 'chip' + (group === app.worldGroup ? ' on' : ''),
        text: `${worldmap.groupTitle(group, app.world.nodes)} · ${members.length}`,
        onclick: () => { app.worldGroup = group; renderFilters(); draw(); },
      })),
    );
  }

  function renderList() {
    if (!app.world) return;
    worldmap.renderList(dom.list, app.world, {
      selected: app.worldPick,
      query: app.query,
      onSelect: (key) => select(key),
    });
  }

  function renderLegend() {
    dom.legend.replaceChildren(
      h('span', {}, h('i', { style: `background:${worldmap.COLOUR.city}` }), 'застройка'),
      h('span', {}, h('i', { style: `background:${worldmap.COLOUR.planet}` }), 'на поверхности'),
      h('span', {}, h('i', { style: `background:${worldmap.COLOUR.exit}` }), 'ворота города'),
      h('span', {}, h('i', { style: `background:${worldmap.COLOUR.vein}; border-radius:50%` }), 'жила'),
      h('span', {}, h('i', { style: `background:${worldmap.COLOUR.relic}; border-radius:50%` }), 'реликвия Предтеч'),
      h('span', { text: '· число в кружке — сколько станков стоит' }),
      h('span', { text: '· пунктирный контур — место считает движок; сплошной — прибито в файле' }),
      h('span', { text: '· перетащить узел — прибить место (D-237)' }),
      h('span', { text: '· Shift + потянуть от узла к узлу — проложить дорогу' }),
    );
  }

  function draw() {
    if (!app.world || !app.worldGroup) return;
    worldmap.renderMap(dom.worldStage, app.world, {
      group: app.worldGroup,
      selected: app.worldPick,
      onSelect: (what) => { if (what.node) select(what.node); },
      onPlace: (key, spot) => pinPlace(key, spot),
      onConnect: (a, b) => connectNodes(a, b),
    });
  }

  function select(pick) {
    app.worldPick = pick;
    //: Выбор с карты может быть из другой группы — из списка выбирают откуда
    //: угодно, и карта должна показать ту, в которой узел стоит.
    const node = app.world.nodes.find((one) => one.key === pick);
    if (node) app.worldGroup = worldmap.groupOf(node, app.world.nodes);
    ctx.refresh();
    openForm();
  }

  function openForm() {
    const host = document.getElementById('panel');
    if (!app.worldPick) {
      host.replaceChildren(h('div', { class: 'empty', text: 'Выберите узел на карте или слева.' }));
      return;
    }
    if (app.worldPick.startsWith('pocket:')) {
      worldform.pocketForm(host, app.world, app.worldPick.slice(7), tools);
      return;
    }
    worldform.nodeForm(host, app.world, app.worldPick, tools);
  }

  // Новый узел заводится там же, где стоит выбранный: группа и якорь берутся у
  // него. Мир — граф, и узел без соседа в нём просто негде поставить.
  function openNew() {
    const node = app.world?.nodes.find((one) => one.key === app.worldPick);
    app.worldPick = null;
    renderList();
    worldform.newNodeForm(document.getElementById('panel'), app.world, tools, node
      ? { layer: node.layer || 'city', parent: node.parent, anchor: node.key }
      : {});
  }

  // Перетащенный узел получает прибитое место: с этой минуты его считает не
  // движок, а файл, и карта редактора и карта игры сходятся по построению.
  async function pinPlace(key, [x, y]) {
    const node = app.world.nodes.find((one) => one.key === key);
    if (!node) return;
    await write('место узла', () => api.putNode({ ...node, place: { x, y } }), key);
  }

  async function connectNodes(a, b) {
    const already = app.world.edges.some(
      (edge) => (edge.a === a && edge.b === b) || (edge.a === b && edge.b === a),
    );
    if (already) {
      say(`дорога ${a} — ${b} уже проложена`, true, 'дорога уже есть');
      return;
    }
    //: Мощёная и шаг города по умолчанию: внутри застройки так и есть, а
    //: длина за стены правится в форме, где рядом видно «даль» узла.
    await write('дорога', () => api.putEdge({ a, b, seconds: null, surface: 'paved' }), a);
  }

  const tools = {
    saveNode: async (data, options = {}) => {
      await write('узел мира', () => api.putNode(data, options.after, options.fresh), data.key);
    },
    deleteNode: async (key) => {
      const answer = await ask({
        title: `Удалить «${key}»?`,
        body: 'Узел уйдёт из файла вместе со всеми дорогами, которые к нему вели. '
          + 'На уже созданный мир это не влияет: сид не сносит того, что стоит (D-007).',
        ok: 'Удалить',
      });
      if (!answer) return;
      await write('узел мира', () => api.dropNode(key), null);
    },
    saveEdge: async (data) => {
      await write('дорога', () => api.putEdge(data), app.worldPick);
    },
    deleteEdge: async (a, b) => {
      await write('дорога', () => api.dropEdge(a, b), app.worldPick);
    },
    savePocket: async (owner, items) => {
      await write('карман', () => api.putPocket(owner, items),
        items.length ? `pocket:${owner}` : null);
    },
  };

  async function write(what, call, openPick) {
    try {
      const result = await call();
      app.worldPick = openPick;
      await load();
      if (result.check) reportRun(result.check, 'проверка вольта');
      else say('записано', false, 'записано');
    } catch (error) {
      say(error.message, true, `${what}: не вышло`);
    }
  }

  return {
    meta, load, renderFilters, renderList, renderLegend, draw, select, openForm, openNew,
    enter: load, reopen: load,
  };
}
