// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The «Мир» tab: the layout of the starting world as a map one can move (D-243).
//
// Everything else in this editor draws a ladder -- what is made of what. This
// one draws a **place**: nodes where they stand, roads between them with the
// seconds they cost, and what is in each node. So it has its own canvas rather
// than the ladder's grid, and its own form rather than the recipe panel.
//
// Two things it is careful about, and both are the reason it exists:
//
// * **the map it shows is the map the engine lays.** A node without a pinned
//   place is seated here by the same rule `engine/places.py` seats it by --
//   the same step, the same gap, the same golden angle, the same direction
//   read off the key. Drag a node and the place stops being computed and
//   becomes pinned in the file: from then on both agree by construction;
// * **a road is seconds, not a line.** The length is shown on the road and
//   edited on it: that is what a step in the city costs, and geography is the
//   whole economy (pillar P3).

import { h } from './ui.js';

// The engine's own numbers: a map laid here and a map laid there have to come
// out the same. Which pair seats a node depends on which map it is on. A
// **surface** is seated by the vault's since D-319 (`map.city_step_m`,
// `map.min_gap_m`), and they come with the layout. An **inside** -- the floors
// of a house, the rooms of a hull -- is seated by the engine's own
// (`runtime.MAP_STEP`, `MAP_MIN_GAP`), which say of themselves that they are
// not balance: nothing in the world is measured in them. That same pair stands
// in for a silent vault on a surface, where it is twenty times too wide -- and
// there `mapTrouble` says so out loud rather than let the map lie quietly.
const FLAT_STEP = 150;
const FLAT_GAP = 96;
const MAP_TURN = 2.399963229728653;
const MAP_RINGS = 6;
//: How the engine turns metres into degrees and back (`src/globe.py`): a
//: surface pins its nodes by latitude (D-319, D-324) while everything else in
//: the layout is metres from an anchor, and one flat map holds both only
//: through the planet's own radius.
const RAD = Math.PI / 180;
//: Откуда считают, когда считать не от чего: и движок ставит такой узел в
//: начало сферы (`places.ORIGIN_GEO`).
const ORIGIN = [0, 0];
//: Насколько высоко лезут по родителям в поисках того, у кого есть место.
//: Граница, а не число мира: она держит цикл в испорченном файле.
const CLIMB = 32;
const MAP_HASH_STEP = 31;
const MAP_HASH_SPAN = 65521;

//: Слоёв два (D-319): поверхность планеты целиком и нутро — этажи дома,
//: отсеки борта. Города среди них нет: город — это метка группы, а не
//: уровень карты, и движок с проверкой вольта знают ровно эти два.
const LAYERS = ['planet', 'location'];
//: Четыре, как их знает проверка вольта (`tools/world.WORLD_SURFACES`).
//: «Дикое» стояло только там: форма строила выбор из трёх, браузер отдавал
//: первый, и открытая дорога сохранялась тропой (2026-09-08).
const SURFACES = ['wild', 'trail', 'road', 'paved'];
const SURFACE_LABEL = {
  wild: 'дикое', trail: 'бездорожье', road: 'дорога', paved: 'мощёная',
};


const COLOUR = {
  //: Не слой, а метка: город — это узлы, чей родитель — узел города (D-319),
  //: и на одной карте поверхности их отличает цвет, а не отдельная карта.
  city: '#7aa2f7',
  planet: '#9ece6a',
  location: '#bb9af7',
  vein: '#e0af68',
  //: Наследие Предтеч (D-232): найдено, не сделано.
  relic: '#bb9af7',
};

/**
 * The colour a node is drawn in: whether it belongs to a city, then the level
 * it lives on.
 *
 * A city used to be a level and a map of its own; since D-319 the surface is
 * one map and a city is a **mark**. So what the split used to say — this node
 * is a city's, that one is wild — the colour says now, on the one map where
 * both stand. The city gate went with the split: a road out of the walls now
 * leaves from any node, and there is nothing left to paint red.
 */
function tintOf(node, nodes) {
  if (layerOf(node) === 'planet' && cityOf(node, nodes)) return COLOUR.city;
  return COLOUR[layerOf(node)] || COLOUR.planet;
}

/** The direction a node leans off its anchor -- read off the key, as the engine does. */
function directionOf(key) {
  let seed = 0;
  for (const letter of key) seed = (seed * MAP_HASH_STEP + letter.codePointAt(0)) % MAP_HASH_SPAN;
  return (seed / MAP_HASH_SPAN) * Math.PI * 2;
}

/**
 * Свободно ли место: не ближе зазора ни к кому из занятых.
 *
 * Меряется в **местных** метрах, а не в метрах кадра: восток кадра растянут
 * косинусами (см. `step`), и на Авроре, где города разъехались на тридцать
 * километров по широте, зазор в шесть метров кадра — это не шесть метров
 * земли. Движок меряет по большому кругу (`places._geo_free`), а у соседей в
 * нескольких метрах друг от друга это одно и то же.
 */
function free(spot, taken, gap, frame) {
  const k = frame && frame.origin && frame.radius > 0 ? eastScale(spot, frame) : 1;
  return taken.every(([x, y]) => Math.hypot((spot[0] - x) / k, spot[1] - y) >= gap);
}

/** A free seat on some ring round the centre -- `places._seat`, line for line. */
function seat(centre, taken, lean, { step: ring, gap }, frame) {
  const rings = taken.length + MAP_RINGS;
  for (let round = 1; round <= rings; round += 1) {
    const reach = ring * round;
    const seats = Math.max(1, Math.trunc((Math.PI * 2 * reach) / gap));
    for (let index = 0; index < seats; index += 1) {
      const angle = lean + MAP_TURN * index;
      //: Кольцо кладётся в метрах земли вокруг центра и переводится в кадр
      //: тем же ходом, что и пин: движок сажает узел на сфере, а не на
      //: плоскости, и растяжку востока надо учесть здесь тоже.
      const spot = step(centre, reach * Math.cos(angle), reach * Math.sin(angle), frame);
      if (free(spot, taken, gap, frame)) return spot;
    }
  }
  return step(centre, ring, 0, frame);
}

/**
 * The frame one group's map is drawn in: metres, and — for a surface — the
 * point they are counted from.
 *
 * A city is metres from its anchor and needs nothing else. A planet's surface
 * pins its nodes in degrees, and degrees are not a plane: the map counts them
 * as metres from the group's **first pinned node**, by the same arithmetic the
 * engine seats them with (`globe.offset`). Which node is first does not
 * matter to what is drawn — a different origin slides the whole picture — but
 * it has to be the same one every time, or a node would jump between renders.
 */
export function frameOf(nodes, group, world = {}) {
  const mine = nodes.filter((node) => groupOf(node, nodes) === group);
  const anchored = mine.find((node) => node.place && 'lat' in node.place);
  if (!anchored) return { origin: null, radius: 0 };
  const planet = group.startsWith('planet:') ? group.slice(7) : null;
  const radius = Number((world.radii || {})[planet]) || 0;
  return { origin: [anchored.place.lat, anchored.place.lon], radius };
}

/**
 * A pin as metres in the group's frame, whichever shape it is written in.
 *
 * `at` is what the metres are counted from, and it is the whole subtlety of
 * this map. A surface's metre pin is metres **from the node's anchor**
 * (`seed_world._pinned`): the file says "thirty east of the market", and a
 * chain of them walks out from the city's core one node at a time. Counted
 * from the frame's origin instead they come out tens of metres wrong on a
 * city fifty metres wide -- and the drag that writes them back then moves the
 * node for good. Degrees are counted from the frame's origin and from nothing
 * else, and inside a house the metres are the floor plan's own.
 *
 * `null` means the map cannot be drawn truthfully: degrees without the
 * planet's radius are not metres, and calling them zero would stack the whole
 * surface on one point (`mapTrouble` says which number is missing).
 */
export function pinMetres(place, frame, at = ORIGIN) {
  if (!place) return null;
  if (!('lat' in place)) return step(at, Number(place.x) || 0, Number(place.y) || 0, frame);
  if (!frame.origin || !(frame.radius > 0)) return null;
  const [lat0, lon0] = frame.origin;
  const north = (Number(place.lat) - lat0) * RAD * frame.radius;
  const east = (Number(place.lon) - lon0) * RAD * frame.radius * Math.cos(lat0 * RAD);
  return [east, north];
}

/**
 * Шаг на восток и на север от точки кадра — так же, как его делает
 * `globe.offset`.
 *
 * Север линеен: метр на север это метр широты, где угодно. Восток — нет: шаг
 * по долготе сжимается косинусом широты, и косинус тут **якоря**, а не начала
 * кадра. Считать по началу — незаметная ошибка на Терре, где начало кадра и
 * есть столица, и пять процентов на Авроре, чьи города стоят на других
 * широтах: узел, брошенный туда же, где стоял, записывается ближе к якорю, и
 * каждое сохранение подтягивает его ещё.
 */
function step(at, x, y, frame) {
  if (!frame || !frame.origin || !(frame.radius > 0)) return [at[0] + x, at[1] + y];
  return [at[0] + x * eastScale(at, frame), at[1] + y];
}

/** И обратно: место в кадре как метры от якоря, теми же косинусами. */
export function pinOffset(spot, at, frame) {
  const scale = frame.origin && frame.radius > 0 ? eastScale(at, frame) : 1;
  return { x: Math.round((spot[0] - at[0]) / scale), y: Math.round(spot[1] - at[1]) };
}

//: Во сколько единиц кадра ложится метр на восток у этой точки. Метр даёт
//: тем больше долготы, чем ближе точка к полюсу (`globe.offset` делит на
//: косинус её широты), а кадр переводит долготу обратно в метры уже по своей
//: широте — отсюда и отношение косинусов, и оно именно в эту сторону.
//: Широту точки даёт её север: север и есть широта, в метрах.
function eastScale(at, frame) {
  const lat = frame.origin[0] + (at[1] / frame.radius) / RAD;
  return Math.max(Math.cos(frame.origin[0] * RAD), 1e-9) / Math.max(Math.cos(lat * RAD), 1e-9);
}

/** And back: metres in the frame as the degrees the file keeps (`globe.offset`). */
export function pinDegrees([east, north], frame) {
  if (!frame.origin || !(frame.radius > 0)) return null;
  const [lat0, lon0] = frame.origin;
  const lat = lat0 + (north / frame.radius) / RAD;
  const lon = lon0 + (east / (frame.radius * Math.max(Math.cos(lat0 * RAD), 1e-9))) / RAD;
  return { lat: round6(lat), lon: round6(((lon + 180) % 360 + 360) % 360 - 180) };
}

const round6 = (value) => Math.round(value * 1e6) / 1e6;

/**
 * Where every node of one group stands: pinned places as they are, the rest
 * seated the way the engine would seat them.
 *
 * A group is one map (`places._group`): a planet's surface, one city's
 * built-up area, the rooms of one house. Nodes of other groups are not drawn.
 */
export function layout(nodes, group, world = {}) {
  return walk(nodes, group, world).places;
}

/**
 * Раскладка и то, **от чего** мерили каждый узел, — одним проходом.
 *
 * Оба ответа нужны: первый рисует карту, второй пишет пин, когда узел
 * перетащили. Считать их порознь однажды уже разошлось — подъём по якорям
 * повторялся дважды и в разных условиях, — а разойтись им нельзя: узел,
 * брошенный туда же, где стоял, обязан записаться тем же числом.
 */
function walk(nodes, group, world = {}) {
  const mine = nodes.filter((node) => groupOf(node, nodes) === group);
  const byKey = index(nodes);
  const frame = frameOf(nodes, group, world);
  const ring = seatingOf(world, group);
  const places = new Map();
  const bases = new Map();
  const taken = [];

  //: В порядке файла и по одному — так их кладёт и сид (`seed_world`), и
  //: порядок тут не украшение: узел отмеряется от места **якоря**, а место
  //: якоря к этой минуте уже есть — прибитое или посаженное. Раскладывать
  //: пины отдельно от посадки значило бы считать лавку от ядра, которому
  //: места ещё не нашли, и весь город уехал бы на смещение ядра.
  for (const node of mine) {
    const beside = besideSpot(node, byKey, places);
    //: Метры пина отмеряются от якоря только на поверхности: внутри дома
    //: они и есть план этажа, и считаются от его собственного начала.
    const measured = layerOf(node) === 'planet' && besideOf(node, byKey) !== null;
    if (measured) bases.set(node.key, beside);
    const from = measured ? beside : ORIGIN;
    const pinned = node.place ? pinMetres(node.place, frame, from) : null;
    const spot = pinned || (free(beside, taken, ring.gap, frame)
      ? beside
      : seat(beside, taken, directionOf(node.key), ring, frame));
    places.set(node.key, spot);
    taken.push(spot);
  }
  return { places, bases };
}

/**
 * The step and the gap the engine seats this map's nodes by.
 *
 * Not one pair but two, and which one is the map's own business: a surface is
 * the vault's since D-319, the inside of a house is the engine's own and is
 * not balance at all (`runtime.MAP_STEP`). Seating a floor plan by the
 * vault's seven metres would draw a tangle where the engine draws rooms.
 */
export function seatingOf(world = {}, group = 'planet:') {
  if (!String(group).startsWith('planet:')) return { step: FLAT_STEP, gap: FLAT_GAP };
  const seating = world.seating || {};
  return {
    step: Number(seating.step_m) > 0 ? Number(seating.step_m) : FLAT_STEP,
    gap: Number(seating.gap_m) > 0 ? Number(seating.gap_m) : FLAT_GAP,
  };
}

/**
 * Что мешает нарисовать эту группу правдиво — словами, или ничего.
 *
 * Карта редактора обещает совпасть с картой игры, и держится обещание на
 * числах вольта: шаг и зазор посадки (D-319) и радиус земли планеты (D-324).
 * Без них карта всё равно рисуется — но врёт, а молчаливая ложь тут хуже
 * пустого места: по этой картинке двигают узлы.
 */
export function mapTrouble(nodes, group, world = {}) {
  const seating = world.seating || {};
  const surface = String(group).startsWith('planet:');
  if (surface && !(Number(seating.step_m) > 0 && Number(seating.gap_m) > 0)) {
    return 'в вольте нет map.city_step_m или map.min_gap_m: узлы без пина рассажены '
      + 'запасными числами и стоят куда шире, чем встанут в игре';
  }
  if (!surface) return null;
  const frame = frameOf(nodes, group, world);
  if (frame.origin && !(frame.radius > 0)) {
    return 'у планеты нет радиуса земли (planet.land_area_share, planet.earth_radius_km): '
      + 'градусы не перевести в метры, и прибитые узлы рассажены как неприбитые';
  }
  if (!frame.origin) {
    //: Без единого градусного пина карте не за что зацепиться на глобусе:
    //: она рисуется плоско и сходится с игрой лишь до косинуса широты.
    //: Движок в этом случае отсчитает всё от нуля сферы.
    return 'на этой поверхности ни один узел не прибит к глобусу: карта плоская и '
      + 'сходится с игрой приблизительно — прибейте хотя бы один узел широтой';
  }
  return null;
}

//: Кого узлу назначили в соседи: якорь, а нет якоря — родителя. Так читает и
//: движок: `world.create_node` зовёт `places.assign(anchor or parent)`, и зал
//: без якоря садится у своего города, а не в начале карты.
function besideOf(node, byKey) {
  const named = node.anchor ? byKey.get(node.anchor) : null;
  return named || (node.parent ? byKey.get(node.parent) : null) || null;
}

/**
 * Место, от которого узел пляшет: и когда его метры отмеряют от якоря
 * (`seed_world._pinned`), и когда его сажает движок (`places._centre`).
 *
 * Это одна и та же точка, и в движке это тоже одна и та же лестница: якорь,
 * а нет якоря — родитель, и вверх по родителям до первого, кто сам где-то
 * стоит. Начало карты — ответ для того, кому стоять не рядом с кем.
 */
function besideSpot(node, byKey, places) {
  let cursor = besideOf(node, byKey);
  for (let step = 0; cursor && step < CLIMB; step += 1) {
    if (layerOf(cursor) === layerOf(node) && places.has(cursor.key)) {
      return places.get(cursor.key);
    }
    cursor = cursor.parent ? byKey.get(cursor.parent) : null;
  }
  return ORIGIN;
}

/**
 * Место, от которого отмеряются метры этого узла, — тем же ходом, каким их
 * считает `layout`. Этим и записывают: узел перетащили, из его места вычли
 * это, и в файл легло ровно то число, какое прочтёт сид.
 *
 * `null` — «мерить не от кого»: у узла нет соседа на этой карте, и место ему
 * пишут своими градусами.
 */
export function anchorAt(node, nodes, group, world = {}) {
  return walk(nodes, group, world).bases.get(node.key) || null;
}

//: Слой узла; молчание файла значит поверхность — так его читает и вольт
//: (`tools/world.py`: `node.get("layer", "planet")`).
const layerOf = (node) => node.layer || 'planet';

/** Город ли этот узел, и чей он: город — метка группы, а не слой (D-319). */
export function cityOf(node, nodes) {
  const byKey = index(nodes);
  if (node.city) return node.key;
  const parent = byKey.get(node.parent);
  return parent && parent.city ? parent.key : null;
}

/**
 * Which map a node is drawn on: its planet's surface, or its parent's inside.
 *
 * The same rule as `places._group` in the engine, and it has to be: two maps
 * that disagree about which nodes share a surface would seat them by different
 * neighbours and come out different pictures of one world.
 */
export function groupOf(node, nodes) {
  if (layerOf(node) !== 'planet') return `${layerOf(node)}:${node.parent || ''}`;
  return `planet:${planetOf(node, index(nodes))}`;
}

//: The key index, remembered per array rather than rebuilt per node: `groupOf`
//: is asked once per node by the layout and once more by the list, and rebuilding
//: a map inside each call made that quietly quadratic.
const indexes = new WeakMap();

function index(nodes) {
  let byKey = indexes.get(nodes);
  if (!byKey) {
    byKey = new Map(nodes.map((one) => [one.key, one]));
    indexes.set(nodes, byKey);
  }
  return byKey;
}

/** The planet a node ends up on: climb the groups until one has no parent here. */
function planetOf(node, byKey) {
  let cursor = node;
  while (cursor && byKey.has(cursor.parent)) cursor = byKey.get(cursor.parent);
  //: The last parent is the planet itself -- it is `external` in the file and
  //: has no node of its own, because the engine lays the sky (D-243).
  return cursor ? cursor.parent || cursor.key : '';
}

/** The groups the world has, in the order they are worth opening. */
export function groups(nodes) {
  const seen = new Map();
  for (const node of nodes) {
    const group = groupOf(node, nodes);
    if (!seen.has(group)) seen.set(group, { group, members: [] });
    seen.get(group).members.push(node);
  }
  return [...seen.values()];
}

export function groupTitle(group, nodes) {
  const [layer, owner] = [group.slice(0, group.indexOf(':')), group.slice(group.indexOf(':') + 1)];
  if (layer === 'planet') return `Поверхность: ${owner || 'без планеты'}`;
  const parent = nodes.find((node) => node.key === owner);
  return `${parent ? parent.name : owner}: помещения`;
}

/**
 * The roads of one group's map, roads from outside it included.
 *
 * An edge is projected onto the layer it is looked at from, exactly as
 * `places.backfill` projects it (D-045): the road from the capital's gate to
 * the coal mine joins, on the planet's map, the **city** and the mine --
 * because on that map the whole city is one point. Drawn without this, a
 * planet's surface came out as loose dots with no ways at all, and the one
 * thing a map of a world is for is the ways.
 */
function project(world, nodes, group) {
  const byKey = index(world.nodes);
  const mine = new Set(nodes.map((node) => node.key));
  const layer = nodes.length ? layerOf(nodes[0]) : 'planet';
  const delegate = (key) => {
    let cursor = byKey.get(key);
    while (cursor && layerOf(cursor) !== layer) cursor = byKey.get(cursor.parent);
    return cursor && mine.has(cursor.key) ? cursor.key : null;
  };
  const seen = new Set();
  const roads = [];
  for (const edge of world.edges) {
    const a = delegate(edge.a);
    const b = delegate(edge.b);
    if (!a || !b || a === b) continue;
    const pair = [a, b].sort().join('|');
    //: Two roads out of one city to one field are one line here: on this map
    //: they leave from the same point and arrive at the same point.
    if (seen.has(pair)) continue;
    seen.add(pair);
    //: `own` says whether this line is the road itself or its shadow on a
    //: higher layer. Only the road itself is edited from the map.
    roads.push({ ...edge, from: a, to: b, own: a === edge.a && b === edge.b });
  }
  return roads;
}

// ------------------------------------------------------------------ the map

/**
 * Draw one group's map into `host`, and let it be moved.
 *
 * `onPlace` is called with the node and its new spot when a node is dragged:
 * a place given by hand is written into the file and stops being computed
 * (D-237 leaves that to whoever lays the world -- inside the game ground never
 * moves, and this is the tool that lays the ground).
 */
export function renderMap(host, world, options) {
  const { group, selected, focus, onSelect, onPlace, onConnect } = options;
  const nodes = world.nodes.filter((node) => groupOf(node, world.nodes) === group);
  const places = layout(world.nodes, group, world);
  const roads = project(world, nodes, group);

  //: Рисуют в **метрах**, а масштаб держит окно (`view`), а не раскладка.
  //: Приведение всей группы к шестистам единицам — то, что было здесь до
  //: 2026-09-08, — делало зум бессмысленным: вместе с картой рос и кружок,
  //: и три города Авроры оставались тремя слипшимися пятнами, только крупнее.
  //: Заодно экран переворачивает север: у холста y растёт вниз.
  const screen = new Map([...places].map(([key, [x, y]]) => [key, [x, -y]]));

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'worldmap');
  const stage = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  svg.append(stage);

  const at = (key) => screen.get(key) || [0, 0];
  //: Что обязано остаться одного размера на любом отдалении: кружки, подписи,
  //: значки. Каждая метка помнит своё место в метрах, а `apply` переписывает
  //: ей `transform` — это единственное, что знает о зуме.
  const marks = [];
  const bounds = zoomBounds(screen);
  const view = viewOf(group, screen, bounds);
  let unit = 1;
  //: Заведён здесь, а не рядом с кнопками: `apply` его пишет, а `const` ниже
  //: по тексту — это не «undefined», а `ReferenceError` при первом же вызове.
  const readout = h('span', { class: 'scale' });

  function apply() {
    const box = svg.getBoundingClientRect();
    //: Панель бывает нулевой высоты — скрытая вкладка, не разложенное окно.
    //: Делить на такое нельзя, и рисовать по такому тоже: числа выходят
    //: бессмысленные, а карта потом остаётся с ними.
    const width = box.width || NOMINAL_PANE;
    const height = box.height || NOMINAL_PANE;
    unit = view.w / width;
    svg.setAttribute('viewBox', frameBox(view, width, height).join(' '));
    for (const mark of marks) {
      mark.el.setAttribute('transform', `translate(${mark.at[0]},${mark.at[1]}) scale(${unit})`);
      //: Подпись показывается, когда ей есть где лечь: на вписанной планете
      //: соседи стоят в паре пикселей, и все подписи ложатся одна на другую —
      //: получается не карта, а клубок букв. Место меряется в пикселях, потому
      //: что и буквы в пикселях: у узла — до ближайшего соседа, у дороги — её
      //: собственная длина.
      if (mark.room !== undefined) {
        //: Выбранный подписан всегда: два узла, сошедшихся в одну точку, иначе
        //: теряют имена на любом масштабе — а это ровно тот случай, когда имя
        //: и нужно, чтобы разобрать, который из них который.
        const tight = mark.room / unit < mark.needs && mark.key !== selected;
        (mark.label || mark.el).style.display = tight ? 'none' : '';
      }
    }
    readout.textContent = spellScale(unit);
  }

  /** Приблизить или отдалить, оставив точку `hold` там, где она была. */
  function zoom(width, hold) {
    Object.assign(view, recentre(view, width, hold, bounds));
    apply();
  }

  const centre = () => [view.cx, view.cy];

  /** Точка под курсором в метрах кадра. */
  function pointer(event) {
    const box = svg.getBoundingClientRect();
    if (!box.width || !box.height) return centre();  // pragma: панель не разложена
    return [
      view.cx + (event.clientX - box.left - box.width / 2) * unit,
      view.cy + (event.clientY - box.top - box.height / 2) * unit,
    ];
  }

  //: Который узел под точкой. Радиус в пикселях, а не в метрах: дорогу целят
  //: мышью, и промах на пять пикселей не должен терять жест — ни на городе в
  //: полсотни метров, ни на поверхности в шестьдесят километров.
  const under = (spot, exclude) => {
    const reach = HIT_PX * unit;
    for (const node of nodes) {
      if (node.key === exclude) continue;
      const [x, y] = at(node.key);
      if (Math.hypot(spot[0] - x, spot[1] - y) <= reach) return node.key;
    }
    return null;
  };

  for (const edge of roads) {
    const [ax, ay] = at(edge.from);
    const [bx, by] = at(edge.to);
    const line = svgEl('line', {
      x1: ax, y1: ay, x2: bx, y2: by,
      class: `road ${edge.surface || 'road'}${edge.own ? '' : ' shadow'}`,
    });
    //: A shadow is not a road one can edit: the road itself belongs to a node
    //: of another layer, and it is opened by opening that node.
    if (edge.own) line.addEventListener('click', () => onSelect({ node: edge.a }));
    stage.append(line);
    const label = svgEl('g', {});
    label.append(svgEl('text', {
      x: 0, y: -6, class: 'road-label',
      text: edge.own ? spellSeconds(edge.seconds) : `${edge.a} — ${edge.b}`,
    }));
    marks.push({
      el: label,
      at: [(ax + bx) / 2, (ay + by) / 2],
      room: Math.hypot(bx - ax, by - ay),
      needs: ROAD_LABEL_PX,
    });
    stage.append(label);
  }

  for (const node of nodes) {
    const box = svgEl('g', { class: 'node' + (node.key === selected ? ' on' : '') });
    const radius = node.city ? CITY_PX : NODE_PX;
    //: Всё внутри метки — в пикселях от её собственного нуля: место держит
    //: `transform`, размер — эти числа, и одно другого не касается.
    box.append(svgEl('circle', {
      cx: 0, cy: 0, r: radius,
      fill: tintOf(node, world.nodes),
      class: node.place ? 'pinned' : 'computed',
    }));
    if ((node.veins || []).length) {
      box.append(svgEl('circle', { cx: radius - 4, cy: -radius + 4, r: 5, fill: COLOUR.vein }));
    }
    //: Реликвии считаются наравне со станками: для того, кто смотрит на карту,
    //: ТЭЦ Предтеч в зале — такая же машина в узле, как печь в мастерской.
    //: Отличает их метка, а не счёт.
    const badge = (node.machines || []).length + (node.relics || []).length;
    if (badge) {
      box.append(svgEl('text', { x: 0, y: 5, class: 'node-badge', text: String(badge) }));
    }
    if ((node.relics || []).length) {
      box.append(svgEl('circle', {
        cx: -radius + 4, cy: -radius + 4, r: 5, fill: COLOUR.relic,
      }));
    }
    const name = svgEl('text', { x: 0, y: radius + 14, class: 'node-label', text: node.name });
    box.append(name);
    marks.push({
      el: box,
      at: at(node.key),
      key: node.key,
      label: name,
      room: nearest(at(node.key), nodes, at, node.key),
      needs: NODE_LABEL_PX,
    });
    stage.append(box);
    wireNode(box, node, {
      at, onSelect, onPlace, onConnect, svg, stage, under, unit: () => unit,
    });
  }

  // ---- панорама и зум -------------------------------------------------------

  //: Тянут по пустому месту — едет карта. Узел свой жест останавливает сам
  //: (`wireNode`), иначе одно движение и двигало бы, и панорамировало.
  svg.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    //: Захват — **не** здесь. При активном захвате мышиные события адресуются
    //: захватчику, а не настоящей цели, и `click` по дороге не доходил бы до
    //: неё: щёлкнуть по линии и открыть её форму стало бы нельзя. Захват
    //: берётся первым же движением за порог, когда это уже точно панорама.
    let last = { x: event.clientX, y: event.clientY };
    let panning = false;
    const mine = event.pointerId;

    const move = (ev) => {
      if (ev.pointerId !== mine) return;  //: второй палец ведёт свой жест
      if (!panning) {
        if (Math.hypot(ev.clientX - last.x, ev.clientY - last.y) < DRAG_SLOP) return;
        panning = true;
        svg.setPointerCapture(mine);
        svg.classList.add('panning');
      }
      //: От предыдущего события, а не от начала жеста: между ними мог
      //: провернуться зум, и метр в пикселе стал другим — считая от начала,
      //: карта прыгала бы на разницу.
      view.cx -= (ev.clientX - last.x) * unit;
      view.cy -= (ev.clientY - last.y) * unit;
      last = { x: ev.clientX, y: ev.clientY };
      apply();
    };
    const up = (ev) => {
      if (ev.pointerId !== mine) return;
      svg.removeEventListener('pointermove', move);
      svg.removeEventListener('pointerup', up);
      svg.removeEventListener('pointercancel', up);
      if (panning) svg.releasePointerCapture?.(mine);
      svg.classList.remove('panning');
    };
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerup', up);
    svg.addEventListener('pointercancel', up);
  });

  svg.addEventListener('wheel', (event) => {
    event.preventDefault();
    zoom(view.w * Math.exp(wheelPixels(event, svg) * WHEEL_RATE), pointer(event));
  }, { passive: false });

  const controls = h('div', { class: 'mapzoom' },
    h('button', { class: 'ghost', text: '−', title: 'отдалить', onclick: () => zoom(view.w * STEP, centre()) }),
    h('button', { class: 'ghost', text: '+', title: 'приблизить', onclick: () => zoom(view.w / STEP, centre()) }),
    h('button', {
      class: 'ghost', text: '⤢', title: 'вписать всю группу',
      onclick: () => { Object.assign(view, fitted(screen)); apply(); },
    }),
    readout,
  );

  host.replaceChildren(svg, controls);
  apply();
  //: Панель меняет размер — свернули колонку, дёрнули окно, — и метр в
  //: пикселе вместе с ней. Без этого метки остаются в старом масштабе:
  //: карта переезжает, а кружки нет.
  //:
  //: Наблюдатель один на модуль и переподключается: `renderMap` зовётся на
  //: каждый выбор узла, и заводить по наблюдателю на перерисовку значило бы
  //: копить их сотнями, каждый со своим замыканием на выброшенный холст.
  watch(svg, apply);
  //: `focus` — «покажи вот этот»: так вкладка говорит про выбор **из
  //: списка**. Выбор с карты сюда не приходит, и правильно: узел под курсором
  //: уже виден, и дёргать к нему карту значило бы отнимать у смотрящего
  //: масштаб, который он сам и выставил. Из списка же выбирают вслепую — там
  //: приехать к узлу и есть весь смысл жеста.
  if (focus && screen.has(focus)) {
    const [x, y] = screen.get(focus);
    view.cx = x;
    view.cy = y;
    //: И подводит, если стояли далеко: центрирование на шестидесяти
    //: километрах показало бы ту же пустоту, только посередине.
    view.w = Math.min(view.w, NEAR_SPAN);
    apply();
  }
  return { places };
}

//: Размеры метки в **пикселях**: они и есть то, ради чего зум имеет смысл.
//: Раньше это были единицы кадра, то есть метры, и кружок узла на Авроре
//: выходил радиусом в два километра при зазоре между узлами в семь метров.
const NODE_PX = 20;
const CITY_PX = 26;
//: Радиус попадания: щедрый, потому что дорогу целят мышью.
const HIT_PX = 34;
//: Сколько пикселей должно быть до соседа, чтобы подпись узла имела смысл, и
//: какой длины должна быть дорога, чтобы подписывать её секунды.
const NODE_LABEL_PX = 46;
const ROAD_LABEL_PX = 76;
//: Ширина панели, когда её нет: скрытая вкладка отдаёт нулевой прямоугольник,
//: и всё, что из него посчитано, — бессмыслица, которая потом остаётся в окне.
const NOMINAL_PANE = 800;
//: Во сколько раз кнопка меняет ширину окна, и насколько круто колесо. Круче,
//: чем кажется разумным, и нарочно: от всей Авроры (шестьдесят километров) до
//: города, где узлы стоят в семи метрах, — три порядка, и мелкий шаг
//: превращал бы дорогу туда в три десятка щелчков.
const STEP = 1.6;
const WHEEL_RATE = 0.0035;
//: Насколько близко подводит карта к узлу, выбранному из списка, если он был
//: за краем: сотня метров — это город целиком и окрестности узла в поле.
const NEAR_SPAN = 200;
//: Запас вокруг вписанной группы: подписи стоят под узлами и вылезают за них.
const FIT_MARGIN = 1.35;
//: Ширина окна для группы из одного узла — вписывать нечего, а показать надо.
const LONE_SPAN = 200;

/**
 * Окно карты — центр и ширина в метрах, своё у каждой группы.
 *
 * Помнится между перерисовками, и это не удобство, а условие: выбор узла
 * перерисовывает карту целиком, и без памяти каждый клик возвращал бы её к
 * вписанному виду — то есть зум держался бы ровно до первого клика.
 */
const views = new Map();

function viewOf(group, screen, bounds) {
  const kept = views.get(group);
  //: Запомненное окно принимается не на веру: раскладка между перерисовками
  //: могла разъехаться, а испорченное место один раз пущенное в окно осталось
  //: бы в нём навсегда — `fitted` даст NaN, границы NaN не поправят, и вернуть
  //: карту можно было бы только перезагрузкой страницы.
  if (kept && sane(kept, bounds)) return kept;
  const fresh = fitted(screen);
  views.set(group, fresh);
  return fresh;
}

const sane = (view, bounds) => (
  Number.isFinite(view.cx) && Number.isFinite(view.cy)
  && view.w >= bounds.min && view.w <= bounds.max
);

/**
 * Кадр `viewBox` из окна и размеров панели.
 *
 * Кадр повторяет пропорции панели нарочно: тогда метр в пикселе — одно число
 * на обе стороны, а не два, зависящих от `preserveAspectRatio`, и всё, что
 * из него считается — размер метки, порог подписи, шаг панорамы, — считается
 * одинаково по горизонтали и по вертикали.
 */
export function frameBox(view, width, height) {
  const unit = view.w / width;
  const tall = height * unit;
  return [view.cx - view.w / 2, view.cy - tall / 2, view.w, tall];
}

/**
 * Окно после зума: ширина новая, а точка `hold` остаётся там же, где была.
 *
 * Без удержания зум уводит карту: колесо над узлом должно приближать **к
 * узлу**, а не к центру экрана. Границы применяются до подсчёта отношения —
 * иначе на упоре карта продолжала бы ползти, меняя центр при неменяющейся
 * ширине.
 */
export function recentre(view, width, hold, bounds) {
  const wide = Math.min(Math.max(width, bounds.min), bounds.max);
  const k = wide / view.w;
  return {
    cx: hold[0] + (view.cx - hold[0]) * k,
    cy: hold[1] + (view.cy - hold[1]) * k,
    w: wide,
  };
}

/**
 * Прокрутка колеса в пикселях, какой бы мерой её ни прислали.
 *
 * `deltaMode` бывает трёх родов, и в Firefox обычное колесо приходит
 * **строками** (`deltaY` около трёх), а не пикселями: без приведения тот же
 * щелчок оказывался в сорок раз слабее, и дорога от планеты до города
 * растягивалась с двух десятков щелчков до семисот.
 */
export function wheelPixels(event, svg) {
  if (event.deltaMode === 1) return event.deltaY * LINE_PX;
  if (event.deltaMode === 2) return event.deltaY * ((svg && svg.clientHeight) || NOMINAL_PANE);
  return event.deltaY;
}

//: Высота строки, когда колесо меряет ими.
const LINE_PX = 16;

//: Наблюдатель за размером панели — один на модуль. Держать его на модуле, а
//: не на карте, — единственный способ не копить их по одному на перерисовку.
let size = null;

function watch(svg, apply) {
  if (typeof ResizeObserver !== 'function') return;  // pragma: старый браузер
  if (!size) size = new ResizeObserver((entries) => entries.forEach((one) => one.target.__apply?.()));
  svg.__apply = apply;
  size.disconnect();
  size.observe(svg);
}

/** До ближайшего соседа по карте, в метрах: столько места у подписи. */
function nearest(spot, nodes, at, exclude) {
  let best = Infinity;
  for (const node of nodes) {
    if (node.key === exclude) continue;
    const [x, y] = at(node.key);
    best = Math.min(best, Math.hypot(spot[0] - x, spot[1] - y));
  }
  return best;
}

/** Окно, в которое помещается вся группа. */
export function fitted(screen) {
  const points = [...screen.values()];
  if (!points.length) return { cx: 0, cy: 0, w: LONE_SPAN };
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const span = Math.max(maxX - minX, maxY - minY);
  return {
    cx: (minX + maxX) / 2,
    cy: (minY + maxY) / 2,
    w: span > 0 ? span * FIT_MARGIN : LONE_SPAN,
  };
}

/**
 * Докуда пускают зум. Внутрь — до пары метров: зазор посадки в городе семь
 * (`map.min_gap_m`), и разглядывать надо именно его. Наружу — втрое шире
 * группы: дальше смотреть не на что, а уехать в пустоту легко.
 */
function zoomBounds(screen) {
  const whole = fitted(screen).w;
  return { min: 2, max: Math.max(whole * 3, LONE_SPAN) };
}

/** Масштаб словами: сколько метров лежит в экранном пикселе. */
export function spellScale(unit) {
  if (unit >= 1000) return `в пикселе ${Math.round(unit / 100) / 10} км`;
  if (unit >= 1) return `в пикселе ${Math.round(unit)} м`;
  if (unit >= 0.01) return `в пикселе ${Math.round(unit * 100)} см`;
  return `в пикселе ${Math.round(unit * 1000)} мм`;
}

//: How far the pointer must travel before it is a drag and not a click. Below
//: it every selecting click would nudge the node a pixel and pin it for ever.
const DRAG_SLOP = 4;

/**
 * Dragging: plain moves the node, with Shift held it draws a road to another.
 *
 * Three things here are not decoration, and each was a bug first:
 *
 * * **the gesture is captured on the node**, not listened for on the canvas.
 *   A pointer that leaves the circle -- which every drag does immediately --
 *   stops sending events to it otherwise, and the drag dies on the first
 *   millimetre;
 * * **selection happens on release, not on press.** Selecting redraws the
 *   whole map, and a redraw replaces this very `<svg>`: pressing a node used
 *   to detach the element the rest of the gesture was hanging on, so nothing
 *   moved and nothing said why;
 * * **the point is asked of the SVG itself** (`getScreenCTM`). The canvas
 *   letterboxes its viewBox to fit the pane, so pixels and user units differ
 *   by a factor **and** an offset, and arithmetic on the bounding rectangle
 *   got both wrong the moment the map was not exactly the pane's shape.
 */
function wireNode(box, node, tools) {
  const { at, onSelect, onPlace, onConnect, svg, stage, unit } = tools;
  box.dataset.key = node.key;

  const point = (event) => {
    const matrix = svg.getScreenCTM();
    if (!matrix) return at(node.key);  // pragma: the canvas is not laid out yet
    const seat = svg.createSVGPoint();
    seat.x = event.clientX;
    seat.y = event.clientY;
    const there = seat.matrixTransform(matrix.inverse());
    return [there.x, there.y];
  };

  box.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    //: Дальше жест не идёт: по холсту тем же нажатием тянут панораму, и без
    //: этой строки одно движение и двигало бы узел, и везло карту под ним.
    event.stopPropagation();
    box.setPointerCapture(event.pointerId);

    const drawing = event.shiftKey;
    const start = at(node.key);
    const from = point(event);
    const rubber = drawing
      ? stage.appendChild(svgEl('line', {
        x1: start[0], y1: start[1], x2: start[0], y2: start[1], class: 'rubber',
      }))
      : null;
    let moved = false;
    let spot = start;
    //: Метка нарисована в пикселях и стоит на `transform`: сдвигая её, надо
    //: писать transform целиком, вместе с масштабом, иначе узел на время
    //: перетаскивания вырастет до размеров в метрах.
    const seat = (place) => `translate(${place[0]},${place[1]}) scale(${unit()})`;

    const move = (ev) => {
      const now = point(ev);
      //: Порог — в пикселях: на поверхности планеты четыре метра неразличимы
      //: глазом, а в городе четыре метра — половина квартала.
      if (!moved && Math.hypot(now[0] - from[0], now[1] - from[1]) < DRAG_SLOP * unit()) return;
      moved = true;
      //: The node follows the pointer by how far the pointer went, not by
      //: where it is: grabbing a circle by its edge must not snap its centre
      //: under the cursor.
      spot = [start[0] + (now[0] - from[0]), start[1] + (now[1] - from[1])];
      if (rubber) {
        rubber.setAttribute('x2', now[0]);
        rubber.setAttribute('y2', now[1]);
      } else {
        box.setAttribute('transform', seat(spot));
      }
    };

    const up = (ev) => {
      box.removeEventListener('pointermove', move);
      box.removeEventListener('pointerup', up);
      box.removeEventListener('pointercancel', up);
      box.releasePointerCapture?.(event.pointerId);
      rubber?.remove();
      if (!moved || ev.type === 'pointercancel') {
        //: A press that went nowhere is a click: open the node. Done here and
        //: not on `pointerdown`, because opening it redraws the map.
        box.setAttribute('transform', seat(start));
        onSelect({ node: node.key });
        return;
      }
      if (drawing) {
        //: Whose circle the road was dropped on, asked of the places rather
        //: than of the event's target: the rubber line lies under the pointer
        //: and would answer for itself.
        const other = tools.under(point(ev), node.key);
        if (other) onConnect(node.key, other);
        else onSelect({ node: node.key });
      } else {
        box.setAttribute('transform', seat(spot));
        //: Рисуют уже в метрах, переводить нечего — только вернуть север:
        //: у холста y растёт вниз, а место в файле считается вверх.
        onPlace(node.key, [spot[0], -spot[1]]);
      }
    };

    box.addEventListener('pointermove', move);
    box.addEventListener('pointerup', up);
    box.addEventListener('pointercancel', up);
  });
}


function svgEl(tag, attrs) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'text') node.textContent = value;
    else if (key === 'class') node.setAttribute('class', value);
    else node.setAttribute(key, value);
  }
  return node;
}

/**
 * A road's length in words: what the file means, not what it says.
 *
 * Empty is not "the city's step" any more: D-319 took that number away, and
 * an edge without seconds now costs whatever the walk between the two places
 * costs -- geography, not a constant.
 */
export function spellSeconds(seconds) {
  if (seconds == null || seconds === '') return 'по расстоянию';
  const number = Number(seconds);
  if (number >= 60) {
    const minutes = Math.floor(number / 60);
    const rest = Math.round(number - minutes * 60);
    return rest ? `${minutes} мин ${rest} с` : `${minutes} мин`;
  }
  return `${number} с`;
}

// -------------------------------------------------------------------- list

export function renderList(host, world, options) {
  const { selected, query, onSelect } = options;
  const needle = (query || '').trim().toLowerCase();
  const matches = (node) => !needle || [
    node.key,
    node.name,
    ...(node.machines || []).map((one) => one.name || one.class),
    ...(node.veins || []).map((one) => one.resource),
    ...(node.items || []).map((one) => one.name),
  ].join(' ').toLowerCase().includes(needle);

  const out = [];
  for (const { group, members } of groups(world.nodes)) {
    const shown = members.filter(matches);
    if (!shown.length) continue;
    out.push(h('div', { class: 'group', text: groupTitle(group, world.nodes) }));
    for (const node of shown) {
      out.push(h('button', {
        class: 'row' + (node.key === selected ? ' on' : ''),
        onclick: () => onSelect(node.key),
      },
      h('span', { class: 'name', text: node.name }),
      h('span', { class: 'tag', text: node.key })));
    }
  }
  const pockets = Object.keys(world.pockets || {});
  if (pockets.length && !needle) {
    out.push(h('div', { class: 'group', text: 'карманы основателей' }));
    for (const owner of pockets) {
      out.push(h('button', {
        class: 'row' + (`pocket:${owner}` === selected ? ' on' : ''),
        onclick: () => onSelect(`pocket:${owner}`),
      },
      h('span', { class: 'name', text: owner }),
      h('span', { class: 'tag', text: `${world.pockets[owner].length} вещей` })));
    }
  }
  if (!out.length) out.push(h('div', { class: 'empty', text: 'ничего не нашлось' }));
  host.replaceChildren(...out);
}

export { LAYERS, SURFACES, SURFACE_LABEL, COLOUR };
