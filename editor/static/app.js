// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The glue: state, the tabs, the graph in the middle, the form on the right,
// and the strip at the bottom where the vault's own check speaks.
//
// One rule holds the thing together: after every write the state is reloaded
// from the file and `tools/build.py --check` runs. The editor never claims a
// save is good -- the vault's own check says so, in its own words.
//
// Each tab lives in its own module and answers the same five questions --
// what to show as filters, as the list, as the legend, on the canvas, and what
// to do when it is entered. What a tab needs from the page it gets in `ctx`.

import { api } from './api.js';
import { createBuildingsTab } from './buildingstab.js';
import { createConstantsTab } from './constantstab.js';
import { createFoodTab } from './foodtab.js';
import { createGraph } from './graphview.js';
import { createPanel } from './panel.js';
import { createRecipesTab } from './recipestab.js';
import { createStationsTab } from './stationstab.js';
import { h, plural } from './ui.js';
import { createWorldTab } from './worldtab.js';

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
  mode: document.getElementById('mode'),
};

//: Every «+ …» button of the header; a tab names the ones it shows.
const NEW_BUTTONS = [
  'act-new', 'act-new-dish', 'act-new-material', 'act-new-class',
  'act-new-building', 'act-new-constant', 'act-new-node',
];

const graph = createGraph(document.getElementById('graph'), {
  onSelect: (name) => select(name),
  onFocus: (name) => { select(name, { focus: true }); },
});

const panel = createPanel(document.getElementById('panel'), {
  getNode: (name) => nodeOf(name),
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
  onWriteBuilding: (result, kind) => tabs.buildings.afterWrite(result, kind),
  notify: (text, bad) => say(text, bad),
});

// Количества на стрелках — свойство взгляда, а не выбор: на всей лестнице их
// сотни и они сливаются в шум, в окрестности одной вещи они и есть ответ.
// Центр сетки: в фокусе колонки считаются от выбранной вещи, на всей
// лестнице — от голого сырья.
function drawPicture(picture) {
  graph.render(picture.nodes, picture.edges, {
    amounts: app.mode === 'focus',
    centre: app.mode === 'focus' ? app.selected : null,
  });
  graph.setSelected(app.selected);
  graph.fit();
}

const refresh = () => { renderFilters(); renderLegend(); renderList(); drawGraph(); };
const ctx = {
  app, dom, panel, say, reportRun, refresh, drawPicture, select, nodeOf, station,
  reload: () => load(),
};
const tabs = {
  recipes: createRecipesTab(ctx),
  food: createFoodTab(ctx),
  stations: createStationsTab(ctx),
  buildings: createBuildingsTab(ctx),
  constants: createConstantsTab(ctx),
  world: createWorldTab(ctx),
};
const current = () => tabs[app.tab];

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
  if (!keepSelection || !known(app.selected)) app.selected = null;
  refresh();
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

// --------------------------------------------------------------------- tabs

const renderFilters = () => current().renderFilters();
const renderList = () => current().renderList();
const renderLegend = () => current().renderLegend();
const drawGraph = () => current().draw();

function setMode(mode, redraw = true) {
  app.mode = mode;
  app.modes[app.tab] = mode;
  for (const button of dom.mode.children) {
    button.classList.toggle('on', button.dataset.mode === mode);
  }
  //: Легенда объясняет, что значит колонка, а значит она у режимов разная.
  renderLegend();
  if (redraw) drawGraph();
}

// Вкладка меняет только то, что нарисовано: выбранная вещь, панель справа и
// поиск переживают переключение. Со станции на её рецепт и обратно ходят часто.
function setTab(name) {
  app.tab = name;
  const tab = current();
  const { meta } = tab;
  for (const button of document.getElementById('tabs').children) {
    button.classList.toggle('on', button.dataset.tab === name);
  }
  // У лестницы граф, у зданий и констант доска, у мира карта — и по разным
  // причинам: типы зданий не делают друг друга, числа ничего не делают, а
  // мир — это карта, а не «из чего сделано». Каждому — свой холст на том же месте.
  //: Атрибутом, а не свойством: `hidden` есть у HTML-элементов, а граф — SVG,
  //: и `svg.hidden = true` заводил поле на объекте, не трогая разметку. Так
  //: под доской зданий и картой мира и просвечивал граф станций.
  const graphed = meta.kind === 'graph';
  dom.graph.toggleAttribute('hidden', !graphed);
  dom.board.hidden = meta.kind !== 'board';
  dom.worldStage.hidden = meta.kind !== 'map';
  dom.graphWrap.classList.toggle('boarded', meta.kind === 'board');
  dom.graphWrap.classList.toggle('mapped', meta.kind === 'map');
  dom.mode.hidden = !graphed;
  document.getElementById('act-fit').hidden = !graphed;
  for (const control of document.querySelectorAll('.recipes-only')) {
    control.hidden = !meta.sliders;
  }
  if (!graphed) dom.hint.textContent = '';
  for (const id of NEW_BUTTONS) {
    document.getElementById(id).hidden = !meta.buttons.includes(id);
  }
  dom.search.placeholder = meta.placeholder;

  if (!graphed) {
    Promise.resolve(tab.enter()).catch((error) => say(error.message, true, 'не удалось прочитать'));
    return;
  }
  dom.mode.querySelector('[data-mode="all"]').textContent = meta.allLabel;
  dom.mode.querySelector('[data-mode="focus"]').title = meta.focusTitle;
  // Фокусу нечего показывать, если выбранное — не из этой вкладки: окрестность
  // кирки на кухне пуста.
  if (!tab.focusable(app.selected)) app.modes[name] = 'all';
  setMode(app.modes[name], false);
  refresh();
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
    const tab = current();
    if (tab.reopen) await tab.reopen();
    else if (app.selected) panel.open(app.selected);
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

dom.mode.addEventListener('click', (event) => {
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

document.getElementById('act-new').addEventListener('click', () => tabs.recipes.openNew());
document.getElementById('act-new-class').addEventListener('click', () => tabs.recipes.openNewClass());
document.getElementById('act-new-material').addEventListener('click', () => panel.openNewMaterial());
document.getElementById('act-new-dish').addEventListener('click', () => tabs.food.openNewDish());
document.getElementById('act-new-node').addEventListener('click', () => tabs.world.openNew());
document.getElementById('act-new-building').addEventListener('click', () => tabs.buildings.openNew());
document.getElementById('act-new-constant').addEventListener('click', () => tabs.constants.openNew());

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
    if (app.tab === 'constants') tabs.constants.save();
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
