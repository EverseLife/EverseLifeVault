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
import { terrainPanel } from './terrainpanel.js';

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

  // Карта — своя у каждой группы: **вся** поверхность одной планеты, города
  // на ней в том числе (D-319), и помещения одного дома. Их не смешивают: у
  // двух планет нет общей земли, и рисовать их вместе значило бы врать про
  // расстояния; а у города и дикой земли она общая, и делить их было бы такой
  // же ложью — редактор делил их до 2026-09-08.
  function renderFilters() {
    if (!app.world) return;
    dom.filters.replaceChildren(
      ...worldmap.groups(app.world.nodes).map(({ group, members }) => h('button', {
        class: 'chip' + (group === app.worldGroup && !app.worldTerrain ? ' on' : ''),
        text: `${worldmap.groupTitle(group, app.world.nodes)} · ${members.length}`,
        onclick: () => {
          app.worldGroup = group;
          app.worldTerrain = false;
          renderFilters();
          draw();
          openForm();
        },
      })),
      //: Рельеф — не группа узлов, а то, на чём они стоят: своя фишка, и
      //: открывается он в той же колонке, где формы (D-319, D-323).
      h('button', {
        class: 'chip' + (app.worldTerrain ? ' on' : ''),
        title: 'зерно и числа генерации: примерить и посмотреть, прежде чем записать',
        text: 'Рельеф ⛰',
        onclick: () => { app.worldTerrain = true; renderFilters(); openForm(); },
      }),
    );
  }

  //: Узел, к которому карта должна приехать: ставится выбором **из списка** и
  //: гаснет первой же отрисовкой. Выбор с карты его не ставит — там узел уже
  //: под курсором, и везти к нему карту значило бы сбивать масштаб, который
  //: смотрящий выставил сам.
  let focus = null;

  function renderList() {
    if (!app.world) return;
    worldmap.renderList(dom.list, app.world, {
      selected: app.worldPick,
      query: app.query,
      onSelect: (key) => { focus = key; select(key); },
    });
  }

  function renderLegend() {
    dom.legend.replaceChildren(
      h('span', {}, h('i', { style: `background:${worldmap.COLOUR.city}` }), 'узел города'),
      h('span', {}, h('i', { style: `background:${worldmap.COLOUR.planet}` }), 'дикая земля'),
      h('span', {}, h('i', { style: `background:${worldmap.COLOUR.vein}; border-radius:50%` }), 'жила'),
      h('span', {}, h('i', { style: `background:${worldmap.COLOUR.relic}; border-radius:50%` }), 'реликвия Предтеч'),
      h('span', { text: '· число в кружке — сколько станков стоит' }),
      h('span', { text: '· пунктирный контур — место считает движок; сплошной — прибито в файле' }),
      h('span', { text: '· север вверху; перетащить узел — прибить место (D-237)' }),
      h('span', { text: '· Shift + потянуть от узла к узлу — проложить дорогу' }),
      //: Чего карте не хватает, чтобы не врать. Пусто — обычный день; строка
      //: здесь значит, что картинка разошлась с игрой, и молчать об этом
      //: нельзя: по ней двигают узлы.
      ...trouble() ? [h('span', { class: 'bad', text: `· ${trouble()}` })] : [],
    );
  }

  const trouble = () => (app.world && app.worldGroup
    ? worldmap.mapTrouble(app.world.nodes, app.worldGroup, app.world)
    : null);

  function draw() {
    if (!app.world || !app.worldGroup) return;
    worldmap.renderMap(dom.worldStage, app.world, {
      group: app.worldGroup,
      selected: app.worldPick,
      focus: takeFocus(),
      onSelect: (what) => { if (what.node) select(what.node); },
      onPlace: (key, spot) => pinPlace(key, spot),
      onConnect: (a, b) => connectNodes(a, b),
    });
  }

  //: Один раз: приехали — и дальше карта стоит, где стоит.
  function takeFocus() {
    const one = focus;
    focus = null;
    return one;
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
    if (app.worldTerrain) {
      void openTerrain(host);
      return;
    }
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

  //: Числа рельефа читаются реестром при открытии панели, а не возятся с
  //: раскладкой: их девять, а карту открывают ради узлов.
  async function openTerrain(host) {
    host.replaceChildren(h('div', { class: 'empty', text: 'читаю числа рельефа…' }));
    let registry;
    try {
      registry = await api.constants();
    } catch (error) {
      host.replaceChildren(h('div', { class: 'empty', text: String(error.message || error) }));
      return;
    }
    const constants = {};
    for (const group of registry.groups) {
      for (const one of group.constants) constants[one.key] = one.value;
    }
    const planet = app.worldGroup?.startsWith('planet:') ? app.worldGroup.slice(7) : 'terra';
    terrainPanel(host, {
      constants,
      planet,
      tools: {
        save: async (key, value) => {
          const entry = registry.groups
            .flatMap((group) => group.constants)
            .find((one) => one.key === key);
          if (!entry) throw new Error(`нет такой константы: ${key}`);
          const result = await api.updateConstant(key, { data: { ...entry, value } });
          if (result && result.check) reportRun(result.check, 'проверка вольта');
        },
        notify: (text, bad) => say(text, bad),
      },
    });
  }

  // Новый узел заводится там же, где стоит выбранный: группа и якорь берутся у
  // него. Мир — граф, и узел без соседа в нём просто негде поставить.
  function openNew() {
    const node = app.world?.nodes.find((one) => one.key === app.worldPick);
    app.worldPick = null;
    renderList();
    worldform.newNodeForm(document.getElementById('panel'), app.world, tools, node
      ? { layer: node.layer || 'planet', parent: node.parent, anchor: node.key }
      : {});
  }

  // Перетащенный узел получает прибитое место: с этой минуты его считает не
  // движок, а файл, и карта редактора и карта игры сходятся по построению.
  //
  // В какой форме — решает не редактор, а узел. Карта считает в метрах обе
  // формы (`world.pinMetres`), но узел поверхности прибит **градусами**
  // (D-319, D-324), и записать ему метры значило бы переехать его на другую
  // планету: метры отсчитываются от якоря, а градусы — от нуля сферы. Узел,
  // у которого пина ещё нет, получает ту форму, какая у него есть от чего:
  // есть якорь — метры от него, нет — свои градусы. Так и лежит в файле
  // столица: ядро в градусах, лавки метрами от ядра, и город переезжает
  // целиком, когда переезжает ядро.
  async function pinPlace(key, [x, y]) {
    const node = app.world.nodes.find((one) => one.key === key);
    if (!node) return;
    const frame = worldmap.frameOf(app.world.nodes, app.worldGroup, app.world);
    const beside = worldmap.anchorAt(node, app.world.nodes, app.worldGroup, app.world);
    //: Градусы бывают только на поверхности: у комнаты широты нет, и метры
    //: её пола отсчитываются от начала своего плана, а не от соседа.
    const surface = (node.layer || 'planet') === 'planet';
    const geographic = node.place ? 'lat' in node.place : surface && !beside;
    let place;
    if (geographic) {
      place = worldmap.pinDegrees([x, y], frame);
      if (!place) {
        say('у планеты нет радиуса земли в вольте — место в градусах не посчитать', true);
        return;
      }
    } else {
      //: Метры пишутся от якоря, а не от начала карты: сид прочтёт их именно
      //: так (`seed_world._pinned`), и разница — это весь город.
      place = worldmap.pinOffset([x, y], beside || [0, 0], frame);
    }
    await write('место узла', () => api.putNode({ ...node, place }), key);
  }

  async function connectNodes(a, b) {
    const already = app.world.edges.some(
      (edge) => (edge.a === a && edge.b === b) || (edge.a === b && edge.b === a),
    );
    if (already) {
      say(`дорога ${a} — ${b} уже проложена`, true, 'дорога уже есть');
      return;
    }
    //: Мощёная и без секунд: время такой дороги идёт из расстояния между
    //: узлами (D-319), а задать его числом можно в форме дороги.
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
      //: Пустой список — это «убрать карман», и уносит он всё снаряжение
      //: стартовой личности разом. Удаление узла спрашивало, а это нет, и
      //: одного случайного нажатия хватало, чтобы двенадцать строк ушли
      //: молча (2026-09-08).
      if (!items.length) {
        const had = (app.world?.pockets || {})[owner] || [];
        const answer = await ask({
          title: `Убрать карман «${owner}»?`,
          body: had.length
            ? `Из файла уйдут все ${had.length} строк снаряжения этой личности. `
              + 'На уже созданный мир это не влияет: сид не отнимает того, что выдал (D-007).'
            : 'Карман и так пуст.',
          ok: 'Убрать',
        });
        if (!answer) return;
      }
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
