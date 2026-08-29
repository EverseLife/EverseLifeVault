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

// The engine's own numbers (`src/runtime.py`): a map laid here and a map laid
// there have to come out the same, so these are copied rather than invented.
const MAP_STEP = 150;
const MAP_MIN_GAP = 96;
const MAP_TURN = 2.399963229728653;
const MAP_RINGS = 6;
const MAP_HASH_STEP = 31;
const MAP_HASH_SPAN = 65521;

const LAYERS = ['planet', 'city', 'location'];
const SURFACES = ['trail', 'road', 'paved'];
const SURFACE_LABEL = { trail: 'бездорожье', road: 'дорога', paved: 'мощёная' };
// A road's length: the two answers that are not a number, and why.
const BY_REACH = 'reach';

const COLOUR = {
  city: '#7aa2f7',
  planet: '#9ece6a',
  location: '#bb9af7',
  vein: '#e0af68',
  exit: '#f7768e',
  //: Наследие Предтеч (D-232): найдено, не сделано.
  relic: '#bb9af7',
};

/** The direction a node leans off its anchor -- read off the key, as the engine does. */
function directionOf(key) {
  let seed = 0;
  for (const letter of key) seed = (seed * MAP_HASH_STEP + letter.codePointAt(0)) % MAP_HASH_SPAN;
  return (seed / MAP_HASH_SPAN) * Math.PI * 2;
}

function free(spot, taken) {
  return taken.every(([x, y]) => Math.hypot(spot[0] - x, spot[1] - y) >= MAP_MIN_GAP);
}

/** A free seat on some ring round the centre -- `places._seat`, line for line. */
function seat(centre, taken, lean) {
  const rings = taken.length + MAP_RINGS;
  for (let ring = 1; ring <= rings; ring += 1) {
    const radius = MAP_STEP * ring;
    const seats = Math.max(1, Math.trunc((Math.PI * 2 * radius) / MAP_MIN_GAP));
    for (let index = 0; index < seats; index += 1) {
      const angle = lean + MAP_TURN * index;
      const spot = [centre[0] + radius * Math.cos(angle), centre[1] + radius * Math.sin(angle)];
      if (free(spot, taken)) return spot;
    }
  }
  return [centre[0] + MAP_STEP, centre[1]];
}

/**
 * Where every node of one group stands: pinned places as they are, the rest
 * seated the way the engine would seat them.
 *
 * A group is one map (`places._group`): a planet's surface, one city's
 * built-up area, the rooms of one house. Nodes of other groups are not drawn.
 */
export function layout(nodes, group) {
  const mine = nodes.filter((node) => groupOf(node, nodes) === group);
  const byKey = index(nodes);
  const places = new Map();
  const taken = [];
  for (const node of mine) {
    if (!node.place) continue;
    places.set(node.key, [node.place.x, node.place.y]);
    taken.push([node.place.x, node.place.y]);
  }
  for (const node of mine) {
    if (places.has(node.key)) continue;
    const centre = centreFor(node, byKey, places, nodes);
    const spot = free(centre, taken) ? centre : seat(centre, taken, directionOf(node.key));
    places.set(node.key, spot);
    taken.push(spot);
  }
  return places;
}

/** What the node is laid beside, climbed to its own layer -- `places._centre`. */
function centreFor(node, byKey, places, nodes) {
  let cursor = node.anchor ? byKey.get(node.anchor) : null;
  while (cursor) {
    if (layerOf(cursor) === layerOf(node)) return places.get(cursor.key) || [0, 0];
    cursor = cursor.parent ? byKey.get(cursor.parent) : null;
  }
  return [0, 0];
}

const layerOf = (node) => node.layer || 'city';

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
  return `${parent ? parent.name : owner}: ${layer === 'city' ? 'застройка' : 'помещения'}`;
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
  const layer = nodes.length ? layerOf(nodes[0]) : 'city';
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
  const { group, selected, onSelect, onPlace, onConnect } = options;
  const nodes = world.nodes.filter((node) => groupOf(node, world.nodes) === group);
  const places = layout(world.nodes, group);
  const roads = project(world, nodes, group);

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'worldmap');
  const stage = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  svg.append(stage);
  host.replaceChildren(svg);

  const at = (key) => places.get(key) || [0, 0];
  const drawn = new Map();
  //: Which node a point falls on. A generous radius: dropping a road is aimed
  //: with a mouse, and missing by five pixels should not lose the gesture.
  const under = (spot, exclude) => {
    for (const node of nodes) {
      if (node.key === exclude) continue;
      const [x, y] = at(node.key);
      if (Math.hypot(spot[0] - x, spot[1] - y) <= 34) return node.key;
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
    stage.append(svgEl('text', {
      x: (ax + bx) / 2, y: (ay + by) / 2 - 6, class: 'road-label',
      text: edge.own ? spellSeconds(edge.seconds) : `${edge.a} — ${edge.b}`,
    }));
  }

  for (const node of nodes) {
    const [x, y] = at(node.key);
    const box = svgEl('g', { class: 'node' + (node.key === selected ? ' on' : '') });
    const radius = node.city ? 26 : 20;
    box.append(svgEl('circle', {
      cx: x, cy: y, r: radius,
      fill: node.properties?.['выход'] ? COLOUR.exit : COLOUR[layerOf(node)] || COLOUR.city,
      class: node.place ? 'pinned' : 'computed',
    }));
    if ((node.veins || []).length) {
      box.append(svgEl('circle', { cx: x + radius - 4, cy: y - radius + 4, r: 5, fill: COLOUR.vein }));
    }
    //: Реликвии считаются наравне со станками: для того, кто смотрит на карту,
    //: ТЭЦ Предтеч в зале — такая же машина в узле, как печь в мастерской.
    //: Отличает их метка, а не счёт.
    const badge = (node.machines || []).length + (node.relics || []).length;
    if (badge) {
      box.append(svgEl('text', { x, y: y + 5, class: 'node-badge', text: String(badge) }));
    }
    if ((node.relics || []).length) {
      box.append(svgEl('circle', {
        cx: x - radius + 4, cy: y - radius + 4, r: 5, fill: COLOUR.relic,
      }));
    }
    box.append(svgEl('text', { x, y: y + radius + 14, class: 'node-label', text: node.name }));
    drawn.set(node.key, box);
    stage.append(box);
    wireNode(box, node, { at, onSelect, onPlace, onConnect, svg, stage, under });
  }

  fit(svg, places);
  return { places };
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
  const { at, onSelect, onPlace, onConnect, svg, stage } = tools;
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

    const move = (ev) => {
      const now = point(ev);
      if (!moved && Math.hypot(now[0] - from[0], now[1] - from[1]) < DRAG_SLOP) return;
      moved = true;
      //: The node follows the pointer by how far the pointer went, not by
      //: where it is: grabbing a circle by its edge must not snap its centre
      //: under the cursor.
      spot = [start[0] + (now[0] - from[0]), start[1] + (now[1] - from[1])];
      if (rubber) {
        rubber.setAttribute('x2', now[0]);
        rubber.setAttribute('y2', now[1]);
      } else {
        box.setAttribute('transform', `translate(${spot[0] - start[0]},${spot[1] - start[1]})`);
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
        box.removeAttribute('transform');
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
        box.removeAttribute('transform');
        onPlace(node.key, [Math.round(spot[0]), Math.round(spot[1])]);
      }
    };

    box.addEventListener('pointermove', move);
    box.addEventListener('pointerup', up);
    box.addEventListener('pointercancel', up);
  });
}

/** Frame the whole group, with room for the labels under the nodes. */
function fit(svg, places) {
  const points = [...places.values()];
  if (!points.length) return;
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const pad = 90;
  const minX = Math.min(...xs) - pad;
  const minY = Math.min(...ys) - pad;
  const width = Math.max(...xs) - minX + pad;
  const height = Math.max(...ys) - minY + pad;
  svg.setAttribute('viewBox', `${minX} ${minY} ${width} ${height}`);
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

/** A road's length in words: what the file means, not what it says. */
export function spellSeconds(seconds) {
  if (seconds === BY_REACH) return 'по дали';
  if (seconds == null || seconds === '') return 'шаг города';
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

export { LAYERS, SURFACES, SURFACE_LABEL, BY_REACH, COLOUR };
