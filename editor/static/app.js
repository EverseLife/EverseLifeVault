// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The glue: state, the list on the left, the graph in the middle, the form on
// the right, and the strip at the bottom where the vault's own check speaks.
//
// One rule holds the thing together: after every write the state is reloaded
// from the file and `tools/build.py --check` runs. The editor never claims a
// save is good -- the vault's own check says so, in its own words.

import { api } from './api.js';
import * as buildings from './buildings.js';
import { createConstantsTab } from './constantstab.js';
import { colourOf, KIND_COLOUR } from './graphview.js';
import { createGraph } from './graphview.js';
import { neighbourhood } from './layout.js';
import { createPanel } from './panel.js';
import { h, plural, things } from './ui.js';
import { createWorldTab } from './worldtab.js';

const TYPE_LABEL = {
  raw: 'сырьё',
  operation: 'операции',
  class: 'классы',
  station: 'станции',
  furniture: 'мебель',
  tool: 'инструменты',
  gear: 'снаряжение',
  vehicle: 'транспорт',
  material: 'материалы',
  consumable: 'расходники',
  money: 'монета',
};

const app = {
  state: null,
  nodes: new Map(),
  // «Руками» рецептом не делается, но половина лестницы начинается на нём.
  // Во вкладке станций это узел; в лестнице рецептов его нет.
  extra: new Map(),
  tab: 'recipes',
  selected: null,
  query: '',
  hidden: new Set(),
  keyOnly: false,
  // Режим свой у каждой вкладки: в рецептах чаще смотрят окрестность одной
  // вещи, в станциях — сперва всё дерево.
  mode: 'focus',
  modes: { recipes: 'focus', food: 'all', stations: 'all' },
  // Вкладка еды делится на три части, и прятать их — её собственный выбор:
  // фишки типов вкладки рецептов тут ни при чём.
  foodHidden: new Set(),
  back: 2,
  forward: 1,
  // Вкладка зданий выбирает не вещь вольта, а тип здания: имена из разных
  // пространств, и общий `selected` перепутал бы их между переключениями.
  building: null,
  footprint: 20,
  //: Вкладка мира выбирает узел, дорогу или карман — имена из своего
  //: пространства ключей, и с `selected` лестницы их путать нельзя.
  world: null,
  worldPick: null,
  worldGroup: null,
  //: Константы (D-065) — свой реестр и свой выбор: ключ константы не имя вещи.
  constants: null,
  constPick: null,
  constGroup: null,
  constForm: null,
};

// Количества на стрелках — свойство взгляда, а не выбор: на всей лестнице их
// сотни и они сливаются в шум, в окрестности одной вещи они и есть ответ.
const showsAmounts = () => app.mode === 'focus';
// Центр сетки: в фокусе колонки считаются от выбранной вещи, на всей лестнице —
// от голого сырья.
const centreOfGrid = () => (app.mode === 'focus' ? app.selected : null);

const dom = {
  list: document.getElementById('list'),
  board: document.getElementById('board'),
  graphWrap: document.getElementById('graph-wrap'),
  graph: document.getElementById('graph'),
  filters: document.getElementById('filters'),
  search: document.getElementById('search'),
  counts: document.getElementById('counts'),
  path: document.getElementById('source-path'),
  stale: document.getElementById('stale'),
  legend: document.getElementById('legend'),
  hint: document.getElementById('graph-hint'),
  consoleBox: document.getElementById('console'),
  consoleOut: document.getElementById('console-out'),
  consoleTitle: document.getElementById('console-title'),
  worldStage: document.getElementById('worldstage'),
};

const graph = createGraph(document.getElementById('graph'), {
  onSelect: (name) => select(name),
  onFocus: (name) => { select(name, { focus: true }); },
});

const panel = createPanel(document.getElementById('panel'), {
  getNode: (name) => app.nodes.get(name) || app.extra.get(name),
  vocabulary: () => app.state.vocabulary,
  // Кому нужен класс, видно только по операциям и станциям рецептов: в графе
  // такого ребра нет, потому что требование закрывается любым из состава.
  operations: () => app.state.operations,
  nodes: () => app.state.nodes,
  onSelect: (name) => select(name),
  //: Типы зданий живут в другом файле вольта (D-218), но правятся той же
  //: формой справа: панель спрашивает их у состояния, как и всё остальное.
  buildings: () => app.state.buildings || [],
  //: Языки игры и имена на них (D-251): форма показывает английское имя рядом
  //: с русским и спрашивает его у новой вещи.
  languages: () => app.state.languages || [],
  locales: () => app.state.locales || {},
  //: Где вещь может лежать для собирателя (D-254): закрытый список свойств узла.
  places: () => app.state.places || [],
  onWrite: afterWrite,
  onWriteBuilding: afterBuildingWrite,
  notify: (text, bad) => say(text, bad),
});

// Две вкладки со своими файлами — мир (D-243) и константы (D-065) — живут в
// своих модулях и берут у страницы только общее: состояние, DOM, полосу внизу
// и «перерисуй всё про текущую вкладку».
const refresh = () => { renderFilters(); renderLegend(); renderList(); drawGraph(); };
const worldTab = createWorldTab({ app, dom, say, reportRun, refresh });
const constantsTab = createConstantsTab({ app, dom, say, reportRun, refresh, reload: () => load() });

// ------------------------------------------------------------------- loading

async function load(keepSelection = true) {
  const state = await api.state();
  app.state = state;
  app.nodes = new Map(state.nodes.map((node) => [node.name, node]));
  app.extra = new Map(state.stations
    .filter((station) => station.virtual)
    .map((station) => [station.name, { name: station.name, type: 'virtual', depth: station.depth }]));
  //: Имя каталога вольта, а не путь целиком: путь на три строки ломал шапку,
  //: а нужен он раз в жизни — и лежит в подсказке.
  dom.path.textContent = state.vault.split(/[\\/]/).filter(Boolean).pop() || state.vault;
  dom.path.title = `${state.vault}\nправятся data/recipes.yaml, constants.yaml, world.yaml, vocabulary.yaml, locales/*.yaml`;
  dom.stale.hidden = !state.stale;
  const { recipes, materials, classes, operations } = state.counts;
  dom.counts.textContent = `${recipes} ${plural(recipes, 'рецепт', 'рецепта', 'рецептов')}`
    + ` · ${materials} ${plural(materials, 'материал', 'материала', 'материалов')}`
    + ` · ${classes} ${plural(classes, 'класс', 'класса', 'классов')}`
    + ` · ${operations} ${plural(operations, 'операция', 'операции', 'операций')}`;
  document.getElementById('act-undo').disabled = !state.undo;

  let names = document.getElementById('all-names');
  if (!names) {
    names = h('datalist', { id: 'all-names' });
    document.body.append(names);
  }
  names.replaceChildren(...state.vocabulary.names.map((name) => h('option', { value: name })));

  //: Выбранный тип мог быть переименован или удалён чужой правкой: держаться
  //: за имя, которого в файле уже нет, значит показывать форму в никуда.
  const kinds = new Set((state.buildings || []).map((row) => row.kind));
  if (!keepSelection || !kinds.has(app.building)) app.building = null;

  renderFilters();
  renderLegend();
  renderList();
  if (!keepSelection || !known(app.selected)) app.selected = null;
  drawGraph();
}

function known(name) {
  return app.nodes.has(name) || app.extra.has(name);
}

function nodeOf(name) {
  return app.nodes.get(name) || app.extra.get(name);
}

function station(name) {
  return app.state.stations.find((item) => item.name === name);
}

// ---------------------------------------------------------------------- food

// Блюдо — то, что помечено `food` (D-119). Оно конечно: ни одно блюдо не
// входит ни в какой рецепт, поэтому вкладка «Рецепты» обходится без него.
const isDish = (node) => !!node.food;
// Съедобное — идёт в котёл ролью, но само не блюдо: мука, масло, соль, вода.
const isEdible = (node) => !!node.edible && !node.food;

const FOOD_PART = {
  dishes: 'блюда',
  edibles: 'съедобное',
  stations: 'станции еды',
};

// Кухня целиком: блюда, то, что в них кладут, и станции, на которых это
// делают. Станция попадает сюда по делу, а не по имени: верстак — станция
// еды, пока на нём солят мясо.
function foodWorld() {
  const dishes = app.state.nodes.filter(isDish);
  const edibles = app.state.nodes.filter(isEdible);
  const made = new Set([...dishes, ...edibles].map((node) => node.name));
  const stations = app.state.stations
    .filter((item) => item.makes.some((name) => made.has(name)))
    .map((item) => nodeOf(item.name) || { name: item.name, type: 'virtual', depth: 0 });
  return { dishes, edibles, stations };
}

function inKitchen(name) {
  const node = nodeOf(name);
  if (!node) return false;
  if (isDish(node) || isEdible(node)) return true;
  return foodWorld().stations.some((item) => item.name === name);
}

// ---------------------------------------------------------------------- list

function typeOf(node) {
  return node.type === 'recipe' ? node.kind : node.type;
}

function renderFilters() {
  if (app.tab === 'world') {
    worldTab.renderFilters();
    return;
  }
  if (app.tab === 'constants') {
    constantsTab.renderFilters();
    return;
  }
  if (app.tab === 'buildings') {
    const rows = app.state.buildings || [];
    dom.filters.replaceChildren(h('span', {
      class: 'note-line',
      text: `${rows.length} ${plural(rows.length, 'тип', 'типа', 'типов')} зданий · `
        + 'состав, цена этажа и порча — у каждого свои',
    }));
    return;
  }
  if (app.tab === 'food') {
    const world = foodWorld();
    const hot = world.dishes.filter((node) => node.hot).length;
    dom.filters.replaceChildren(
      ...Object.entries(FOOD_PART).map(([part, label]) => h('button', {
        class: 'chip' + (app.foodHidden.has(part) ? '' : ' on'),
        text: `${label} ${world[part].length}`,
        onclick: () => {
          if (app.foodHidden.has(part)) app.foodHidden.delete(part); else app.foodHidden.add(part);
          renderFilters();
          renderList();
          drawGraph();
        },
      })),
      h('span', { class: 'note-line', text: `горячих блюд ${hot}` }),
    );
    return;
  }
  if (app.tab === 'stations') {
    // Фильтровать нечего: станции и так один тип. Вместо фишек — счёт.
    const idle = app.state.stations.filter((item) => !item.makes.length).length;
    dom.filters.replaceChildren(h('span', {
      class: 'note-line',
      text: `${app.state.stations.length} станций, из них ${idle} пока ничего не делают`,
    }));
    return;
  }
  const present = [...new Set(app.state.nodes.map(typeOf))];
  const order = Object.keys(TYPE_LABEL);
  present.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  dom.filters.replaceChildren(
    ...present.map((type) => h('button', {
      class: 'chip' + (app.hidden.has(type) ? '' : ' on'),
      style: `color:${KIND_COLOUR[type] || 'inherit'}`,
      text: TYPE_LABEL[type] || type,
      onclick: () => {
        if (app.hidden.has(type)) app.hidden.delete(type); else app.hidden.add(type);
        renderFilters();
        renderList();
        if (app.mode === 'all') drawGraph();
      },
    })),
    h('button', {
      class: 'chip' + (app.keyOnly ? ' on' : ''),
      text: '★ вехи',
      title: 'только ступени лестницы',
      onclick: () => { app.keyOnly = !app.keyOnly; renderFilters(); renderList(); },
    }),
  );
}

function matches(node) {
  // Блюда живут во вкладке «Еда», и только там.
  if (isDish(node)) return false;
  if (app.hidden.has(typeOf(node))) return false;
  if (app.keyOnly && !node.is_key) return false;
  const query = app.query.trim().toLowerCase();
  if (!query) return true;
  const haystack = [
    node.name,
    node.station || '',
    node.kind || node.type,
    ...(node.inputs || []),
    ...(node.operations || []),
  ].join(' ').toLowerCase();
  return haystack.includes(query);
}

function renderList() {
  if (app.tab === 'world') {
    worldTab.renderList();
    return;
  }
  if (app.tab === 'constants') {
    constantsTab.renderList();
    return;
  }
  if (app.tab === 'buildings') {
    buildings.renderList(dom.list, app.state.buildings || [], {
      selected: app.building,
      query: app.query,
      onSelect: (kind) => selectBuilding(kind),
    });
    return;
  }
  if (app.tab === 'stations') {
    renderStationList();
    return;
  }
  if (app.tab === 'food') {
    renderFoodList();
    return;
  }
  const visible = app.state.nodes.filter(matches);
  const groups = new Map();
  for (const node of visible) {
    const key = node.type === 'recipe' ? `L${String(node.level).padStart(2, '0')}` : `Z${node.type}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(node);
  }
  const levels = new Map(app.state.vocabulary.levels.map((level) => [level.id, level.title]));
  const title = (key) => (key.startsWith('L')
    ? `${Number(key.slice(1))}. ${levels.get(Number(key.slice(1))) || ''}`
    : TYPE_LABEL[key.slice(1)] || key.slice(1));

  const out = [];
  for (const key of [...groups.keys()].sort()) {
    out.push(h('div', { class: 'group', text: title(key) }));
    for (const node of groups.get(key).sort((a, b) => a.name.localeCompare(b.name, 'ru'))) {
      out.push(h('div', {
        class: 'row' + (node.name === app.selected ? ' sel' : ''),
        'data-name': node.name,
        onclick: () => select(node.name),
        ondblclick: () => select(node.name, { focus: true }),
      },
      h('span', { class: 'dot', style: `background:${colourOf(node)}` }),
      h('span', { class: 'nm', text: node.name }),
      node.is_key ? h('span', { class: 'kbd', text: '★' }) : null,
      h('span', { class: 'st', text: node.station || (node.type === 'raw' ? 'сырьё' : '') }),
      ));
    }
  }
  if (!out.length) out.push(h('div', { class: 'empty', text: 'ничего не нашлось' }));
  dom.list.replaceChildren(...out);
}

// Кухня в три группы: сперва блюда — ради них вкладка, — потом из чего они,
// потом где. Поиск ищет по названию, по входам и по станции, как и в рецептах.
function renderFoodList() {
  const query = app.query.trim().toLowerCase();
  const world = foodWorld();
  const fits = (node) => !query || [
    node.name,
    node.station || '',
    ...(node.inputs || []),
    ...(station(node.name)?.makes || []),
  ].join(' ').toLowerCase().includes(query);
  const edibleMakes = (name) => (station(name)?.makes || []).filter((made) => {
    const other = nodeOf(made);
    return other && (isDish(other) || isEdible(other));
  }).length;

  const out = [];
  for (const [part, label] of Object.entries(FOOD_PART)) {
    if (app.foodHidden.has(part)) continue;
    const rows = world[part].filter(fits).sort((a, b) => a.name.localeCompare(b.name, 'ru'));
    if (!rows.length) continue;
    out.push(h('div', { class: 'group', text: label }));
    for (const node of rows) {
      out.push(h('div', {
        class: 'row' + (node.name === app.selected ? ' sel' : ''),
        'data-name': node.name,
        onclick: () => select(node.name),
        ondblclick: () => select(node.name, { focus: true }),
      },
      h('span', { class: 'dot', style: `background:${colourOf(node)}` }),
      h('span', { class: 'nm', text: node.name }),
      node.hot ? h('span', { class: 'kbd', title: 'горячее блюдо', text: '♨' }) : null,
      node.roles ? h('span', { class: 'kbd', title: 'входы — роли, а не состав (D-119)', text: 'роли' }) : null,
      h('span', {
        class: 'st',
        title: part === 'stations' ? 'сколько съедобного делают на станции' : '',
        text: part === 'stations'
          ? String(edibleMakes(node.name))
          : node.station || (node.type === 'raw' ? 'сырьё' : ''),
      }),
      ));
    }
  }
  if (!out.length) out.push(h('div', { class: 'empty', text: 'ничего не нашлось' }));
  dom.list.replaceChildren(...out);
}

// Станции идут по ступеням, а не по алфавиту: список читается как порядок, в
// котором город их себе ставит.
function renderStationList() {
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
    const node = nodeOf(item.name) || { type: 'virtual' };
    out.push(h('div', {
      class: 'row' + (item.name === app.selected ? ' sel' : ''),
      'data-name': item.name,
      onclick: () => select(item.name),
      ondblclick: () => select(item.name, { focus: true }),
    },
    h('span', { class: 'dot', style: `background:${colourOf(node)}` }),
    h('span', { class: 'nm', text: item.name }),
    h('span', {
      class: 'st',
      title: 'рецептов на этой станции · где она сама стоит входом',
      text: item.makes.length
        ? `${item.makes.length}${item.inputs_to.length ? ` · ↑${item.inputs_to.length}` : ''}`
        : '—',
    }),
    ));
  }
  if (!out.length) out.push(h('div', { class: 'empty', text: 'ничего не нашлось' }));
  dom.list.replaceChildren(...out);
}

function renderLegend() {
  if (app.tab === 'world') {
    worldTab.renderLegend();
    return;
  }
  if (app.tab === 'buildings') {
    dom.legend.replaceChildren(
      h('span', { text: 'тип решает три вещи разом: из чего построено, во сколько раз '
        + 'дорожает следующий этаж и как быстро дом ветшает' }),
      h('span', { text: '· пятно ограничено участком, высота — нет' }),
      h('span', { text: '· правки уходят в data/constants.yaml, vocabulary.yaml и locales/' }),
    );
    return;
  }
  if (app.tab === 'constants') {
    constantsTab.renderLegend();
    return;
  }
  if (app.tab === 'food') {
    dom.legend.replaceChildren(
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.consumable}` }), 'блюдо'),
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.material}` }), 'съедобный продукт'),
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.raw}` }), 'съедобное сырьё'),
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.station}` }), 'станция'),
      h('span', { text: '· сплошная стрелка — что кладут' }),
      h('span', { text: '· пунктир — на чём готовят' }),
      h('span', { text: '· ♨ — горячее: сытость отдаёт временем (D-119)' }),
      h('span', { text: '· роли — вход закрывается любым подходящим продуктом' }),
      h('span', { text: '· двойной щелчок — сделать центром' }),
    );
    return;
  }
  if (app.tab === 'stations') {
    dom.legend.replaceChildren(
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.station}` }), 'станция'),
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.virtual}` }), 'руками и стройка'),
      h('span', { text: '· сплошная стрелка — на чём станция собирается' }),
      h('span', { text: '· пунктир — что на ней делают' }),
      h('span', { text: '· точки — станция входит в состав' }),
      h('span', { text: '· двойной щелчок — раскрыть одну станцию' }),
    );
    return;
  }
  const present = [...new Set(app.state.nodes.map(typeOf))];
  dom.legend.replaceChildren(
    ...present.map((type) => h('span', {},
      h('i', { style: `background:${KIND_COLOUR[type] || '#888'}` }),
      TYPE_LABEL[type] || type,
    )),
    h('span', {}, h('i', { style: 'background:var(--warn);border-radius:50%' }), 'веха'),
    h('span', {
      text: app.mode === 'focus'
        ? '· колонки считаны от выбранной вещи: слева — из чего, справа — во что'
        : '· колонка — ступень лестницы от голого сырья',
    }),
    h('span', {
      text: app.mode === 'focus'
        ? '· число на стрелке — сколько идёт на единицу'
        : '· количества показываются в фокусе',
    }),
    h('span', { text: '· двойной щелчок — сделать центром' }),
  );
}

// --------------------------------------------------------------------- graph

function drawGraph() {
  if (app.tab === 'world') {
    worldTab.draw();
    return;
  }
  if (app.tab === 'constants') {
    constantsTab.draw();
    return;
  }
  if (app.tab === 'buildings') {
    buildings.renderBoard(dom.board, app.state.buildings || [], {
      selected: app.building,
      footprint: app.footprint,
      onFootprint: (value) => { app.footprint = value; drawGraph(); },
    });
    return;
  }
  const picture = app.tab === 'stations' ? stationPicture()
    : app.tab === 'food' ? foodPicture() : recipePicture();
  graph.render(picture.nodes, picture.edges, {
    amounts: showsAmounts(),
    centre: centreOfGrid(),
  });
  graph.setSelected(app.selected);
  graph.fit();
}

// Дерево станций (D-106): верстак собирается руками, всё остальное — на
// верстаке или глубже. Плюс станции, которые входят в другие станции деталью.
function stationPicture() {
  const list = app.state.stations;
  const node = (name) => nodeOf(name) || { name, type: 'virtual', depth: 0 };

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

  const chosen = station(app.selected);
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

// Кухня на графе: состав и станция вместе. В лестнице рецептов эти два
// отношения разведены по вкладкам, а здесь их мало, и вопрос «из чего и на
// чём» — один вопрос.
function foodPicture() {
  const world = foodWorld();
  const shown = Object.keys(FOOD_PART)
    .filter((part) => !app.foodHidden.has(part))
    .flatMap((part) => world[part]);
  const names = new Set(shown.map((node) => node.name));
  const edges = app.state.edges.filter((edge) => (edge.rel === 'input' || edge.rel === 'station')
    && names.has(edge.from) && names.has(edge.to));

  let nodes;
  if (app.mode === 'all') {
    nodes = shown;
    const { dishes, edibles, stations } = world;
    dom.hint.textContent = `${dishes.length} ${plural(dishes.length, 'блюдо', 'блюда', 'блюд')}`
      + ` · ${edibles.length} ${plural(edibles.length, 'съедобное', 'съедобных', 'съедобных')}`
      + ` · ${stations.length} ${plural(stations.length, 'станция', 'станции', 'станций')}`;
  } else if (!app.selected || !names.has(app.selected)) {
    nodes = [];
    dom.hint.textContent = 'выберите блюдо, продукт или станцию';
  } else {
    const near = neighbourhood(app.selected, edges, app.back, app.forward);
    nodes = shown.filter((node) => near.has(node.name));
    dom.hint.textContent = `${things(nodes.length)} вокруг «${app.selected}»`;
  }
  const kept = new Set(nodes.map((node) => node.name));
  return { nodes, edges: edges.filter((edge) => kept.has(edge.from) && kept.has(edge.to)) };
}

function recipePicture() {
  const all = app.state.nodes;
  // Только «из чего делается»: на какой станции — это вкладка «Станции», и
  // рисовать оба отношения одной картинкой значило бы спорить с самим собой.
  const edges = app.state.edges.filter((edge) => edge.rel === 'input');
  let nodes;
  if (app.mode === 'all') {
    const shown = new Set(all.filter((node) => !isDish(node) && !app.hidden.has(typeOf(node))).map((n) => n.name));
    nodes = all.filter((node) => shown.has(node.name));
    dom.hint.textContent = things(nodes.length);
  } else if (!app.selected) {
    nodes = [];
    dom.hint.textContent = 'выберите вещь';
  } else {
    const near = neighbourhood(app.selected, edges, app.back, app.forward);
    // Окрестность муки тянет за собой хлеб, но хлеб — это вкладка «Еда».
    nodes = all.filter((node) => near.has(node.name) && !isDish(node));
    dom.hint.textContent = `${things(nodes.length)} вокруг «${app.selected}»`;
  }
  const names = new Set(nodes.map((node) => node.name));
  return { nodes, edges: edges.filter((edge) => names.has(edge.from) && names.has(edge.to)) };
}

function setMode(mode, redraw = true) {
  app.mode = mode;
  app.modes[app.tab] = mode;
  for (const button of document.getElementById('mode').children) {
    button.classList.toggle('on', button.dataset.mode === mode);
  }
  //: Легенда объясняет, что значит колонка, а значит она у режимов разная.
  renderLegend();
  if (redraw) drawGraph();
}

// Вкладка меняет только то, что нарисовано: выбранная вещь, панель справа и
// поиск переживают переключение. Со станции на её рецепт и обратно ходят часто.
function setTab(tab) {
  app.tab = tab;
  for (const button of document.getElementById('tabs').children) {
    button.classList.toggle('on', button.dataset.tab === tab);
  }
  const houses = tab === 'buildings';
  const numbers = tab === 'constants';
  const ground = tab === 'world';
  const boarded = houses || numbers;
  // Ни у зданий, ни у констант, ни у мира нет графа лестницы, и по разным
  // причинам: типы зданий не делают друг друга, числа ничего не делают, а
  // мир — это карта, а не «из чего сделано». Каждому — свой холст на том же месте.
  //: Атрибутом, а не свойством: `hidden` есть у HTML-элементов, а граф — SVG,
  //: и `svg.hidden = true` заводил поле на объекте, не трогая разметку. Так
  //: под доской зданий и картой мира и просвечивал граф станций.
  dom.graph.toggleAttribute('hidden', boarded || ground);
  dom.board.hidden = !boarded;
  dom.worldStage.hidden = !ground;
  dom.graphWrap.classList.toggle('boarded', boarded);
  dom.graphWrap.classList.toggle('mapped', ground);
  document.getElementById('mode').hidden = boarded || ground;
  document.getElementById('act-fit').hidden = boarded || ground;
  for (const control of document.querySelectorAll('.recipes-only')) {
    control.hidden = tab !== 'recipes' && tab !== 'food';
  }
  if (boarded || ground) dom.hint.textContent = '';
  const kitchen = tab === 'food';
  // Новая еда заводится блюдом или материалом со съедобностью; рецепт вообще
  // и класс — дело лестницы, на кухне им нечего делать.
  document.getElementById('act-new').hidden = boarded || kitchen || ground;
  document.getElementById('act-new-class').hidden = boarded || kitchen || ground;
  document.getElementById('act-new-material').hidden = boarded || ground;
  document.getElementById('act-new-dish').hidden = !kitchen;
  document.getElementById('act-new-building').hidden = !houses;
  document.getElementById('act-new-constant').hidden = !numbers;
  document.getElementById('act-new-node').hidden = !ground;
  if (ground) {
    dom.search.placeholder = 'поиск: узел, станок, жила или вещь в нём';
    worldTab.load().catch((error) => say(error.message, true, 'не удалось прочитать мир'));
    return;
  }
  if (numbers) {
    dom.search.placeholder = 'поиск: ключ, смысл, единица, значение';
    constantsTab.load().catch((error) => say(error.message, true, 'не удалось прочитать константы'));
    return;
  }
  if (houses) {
    dom.search.placeholder = 'поиск: тип здания или материал в составе';
    renderFilters();
    renderLegend();
    renderList();
    drawGraph();
    if (app.building) panel.openBuilding(app.building); else panel.clear();
    return;
  }
  const modes = document.getElementById('mode');
  modes.querySelector('[data-mode="all"]').textContent = tab === 'stations'
    ? 'Все станции' : kitchen ? 'Вся кухня' : 'Вся лестница';
  modes.querySelector('[data-mode="focus"]').title = tab === 'stations'
    ? 'что делают на выбранной станции и куда она входит'
    : kitchen ? 'из чего блюдо и на чём его готовят' : '';
  dom.search.placeholder = tab === 'stations'
    ? 'поиск: станция или что на ней делают'
    : kitchen ? 'поиск: блюдо, продукт или станция'
      : 'поиск: название, вход, станция';
  // Фокусу нечего показывать, если выбранное — не станция.
  if (tab === 'stations' && !station(app.selected)) app.modes.stations = 'all';
  // И если выбранное — не еда: окрестность кирки на кухне пуста.
  if (kitchen && !inKitchen(app.selected)) app.modes.food = 'all';
  setMode(app.modes[tab], false);
  renderFilters();
  renderLegend();
  renderList();
  drawGraph();
}

// Выбор типа здания идёт своим путём: у него нет узла в графе и нет строки в
// словаре вольта — есть только имя в карте констант.
function selectBuilding(kind) {
  app.building = kind;
  renderList();
  drawGraph();
  panel.openBuilding(kind);
}

async function afterBuildingWrite(result, openKind) {
  app.building = openKind || null;
  await load();
  if (result && result.check) reportRun(result.check, 'проверка вольта');
  else say('записано', false, 'записано');
  renderList();
  drawGraph();
  if (app.building) panel.openBuilding(app.building); else panel.clear();
}


function select(name, { focus = false } = {}) {
  if (!known(name)) return;
  // «Сделать центром» на общей лестнице означает уйти в фокус вокруг вещи:
  // иначе двойной щелчок там не делает ничего.
  if (focus && app.mode !== 'focus') setMode('focus', false);
  const refocus = focus || app.mode === 'focus';
  app.selected = name;
  for (const row of dom.list.querySelectorAll('.row')) {
    row.classList.toggle('sel', row.dataset.name === name);
  }
  const row = dom.list.querySelector(`.row[data-name="${CSS.escape(name)}"]`);
  row?.scrollIntoView({ block: 'nearest' });
  panel.open(name);
  if (refocus) drawGraph();
  else {
    graph.setSelected(name);
    graph.centreOn(name);
  }
}

// ------------------------------------------------------------------- console

function say(text, bad = false, title = null) {
  dom.consoleOut.textContent = text || '';
  dom.consoleTitle.textContent = title || (bad ? 'проверка нашла новые проблемы' : 'готово');
  dom.consoleTitle.className = bad ? 'bad' : 'ok';
  dom.consoleBox.classList.remove('folded');
}

function reportRun(result, what) {
  const bad = result.code !== 0;
  //: Сборка пишет файлы и выходит нулём даже с проблемами — заголовок «чисто»
  //: над списком проблем врал бы. Слова проверки ищутся в её же выводе.
  const complained = /НОВЫЕ проблемы/.test(result.output || '');
  say(result.output || '(без вывода)', bad || complained,
    `${what}: ${bad ? 'проблемы' : complained ? 'сделано, но проверка нашла проблемы' : 'чисто'}`);
}

async function afterWrite(result, openName) {
  await load();
  if (result.check) reportRun(result.check, 'проверка вольта');
  else say('записано', false, 'записано');
  if (openName) select(openName);
  else panel.clear();
}

async function run(what, call, button) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = '…';
  try {
    const result = await call();
    if (result.check) reportRun(result.check, what);
    else if (result.output !== undefined) reportRun(result, what);
    else say(JSON.stringify(result), false, what);
    await load();
    //: Откат и сборка меняют не только лестницу: вкладка перечитывает своё.
    if (app.tab === 'constants') await constantsTab.load();
    else if (app.tab === 'world') await worldTab.load();
    else if (app.tab === 'buildings') {
      if (app.building) panel.openBuilding(app.building); else panel.clear();
    } else if (app.selected) panel.open(app.selected);
  } catch (error) {
    say(error.message, true, `${what}: не вышло`);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

// -------------------------------------------------------------------- wiring

dom.search.addEventListener('input', (event) => {
  app.query = event.target.value;
  renderList();
});

document.getElementById('mode').addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (button) setMode(button.dataset.mode);
});

document.getElementById('tabs').addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (button) setTab(button.dataset.tab);
});

for (const [id, key] of [['depth-in', 'back'], ['depth-out', 'forward']]) {
  const input = document.getElementById(id);
  const output = document.getElementById(`${id}-out`);
  input.addEventListener('input', () => {
    app[key] = Number(input.value);
    output.textContent = input.value;
    if (app.mode === 'focus') drawGraph();
  });
}

document.getElementById('act-fit').addEventListener('click', () => graph.fit());

document.getElementById('act-new').addEventListener('click', () => {
  const node = app.nodes.get(app.selected);
  panel.openNew(node && node.type === 'recipe'
    ? { level: node.level, section: node.section, station: node.station }
    : {});
});

// Класс заводят не в пустоте, а когда у вещи появился второй вариант: то, что
// выбрано сейчас, становится первым, чем класс закрывается.
document.getElementById('act-new-class').addEventListener('click', () => {
  const node = app.nodes.get(app.selected);
  panel.openNewClass(node && node.type !== 'class' ? { members: [node.name] } : {});
});

document.getElementById('act-new-material').addEventListener('click', () => {
  panel.openNewMaterial();
});

// Блюдо рождается там же, где живут остальные: уровень, раздел и станция
// берутся у выбранного блюда, а без выбора — у любого из файла. Очаг в коде
// не назван: что считается очагом, решает вольт.
document.getElementById('act-new-dish').addEventListener('click', () => {
  const chosen = app.nodes.get(app.selected);
  const sample = (chosen && isDish(chosen)) ? chosen : app.state.nodes.find(isDish);
  panel.openNew({
    kind: 'consumable',
    flags: { food: true, roles: true },
    level: sample?.level,
    section: sample?.section,
    station: sample?.station,
  });
});

document.getElementById('act-new-node').addEventListener('click', () => worldTab.openNew());

document.getElementById('act-new-building').addEventListener('click', () => {
  app.building = null;
  renderList();
  panel.openNewBuilding();
});

document.getElementById('act-new-constant').addEventListener('click', () => constantsTab.openNew());

document.getElementById('act-masses').addEventListener('click', (event) => {
  run('расчёт масс', api.masses, event.target);
});
document.getElementById('act-check').addEventListener('click', (event) => {
  run('проверка вольта', api.check, event.target);
});
document.getElementById('act-build').addEventListener('click', (event) => {
  run('сборка вольта', api.build, event.target);
});
document.getElementById('act-undo').addEventListener('click', (event) => {
  run('откат последней правки', api.undo, event.target);
});

document.getElementById('console-toggle').addEventListener('click', (event) => {
  const folded = dom.consoleBox.classList.toggle('folded');
  event.target.textContent = folded ? 'развернуть' : 'свернуть';
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'f' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    dom.search.focus();
    dom.search.select();
  }
  if (event.key === 's' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    if (app.tab === 'constants') constantsTab.save();
    else panel.save();
  }
  //: Ctrl+Z в поле ввода — отмена набора, как везде; вне поля — откат правки.
  const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName);
  if (event.key === 'z' && (event.ctrlKey || event.metaKey) && !typing) {
    event.preventDefault();
    const button = document.getElementById('act-undo');
    if (!button.disabled) run('откат последней правки', api.undo, button);
  }
});

window.addEventListener('resize', () => graph.fit());

load(false)
  .then(() => say('файл прочитан, правки пока не было', false, 'готово'))
  .catch((error) => say(error.message, true, 'не удалось прочитать вольт'));
