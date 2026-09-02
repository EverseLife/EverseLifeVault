// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// What the three tabs of the ladder -- recipes, food, stations -- share: the
// names of node types, the test for a dish, the row of the list on the left.

import { colourOf } from './graphview.js';
import { h } from './ui.js';

export const TYPE_LABEL = {
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

export const typeOf = (node) => (node.type === 'recipe' ? node.kind : node.type);

// Блюдо — то, что помечено `food` (D-119). Оно конечно: ни одно блюдо не
// входит ни в какой рецепт, поэтому вкладка «Рецепты» обходится без него.
export const isDish = (node) => !!node.food;
// Съедобное — идёт в котёл ролью, но само не блюдо: мука, масло, соль, вода.
export const isEdible = (node) => !!node.edible && !node.food;

export const FOOD_PART = {
  dishes: 'блюда',
  edibles: 'съедобное',
  stations: 'станции еды',
};

// Кухня целиком: блюда, то, что в них кладут, и станции, на которых это
// делают. Станция попадает сюда по делу, а не по имени: верстак — станция
// еды, пока на нём солят мясо.
export function foodWorld(state, nodeOf) {
  const dishes = state.nodes.filter(isDish);
  const edibles = state.nodes.filter(isEdible);
  const made = new Set([...dishes, ...edibles].map((node) => node.name));
  const stations = state.stations
    .filter((item) => item.makes.some((name) => made.has(name)))
    .map((item) => nodeOf(item.name) || { name: item.name, type: 'virtual', depth: 0 });
  return { dishes, edibles, stations };
}

/** One row of the list: colour dot, name, whatever the tab adds on the right. */
export function listRow(node, name, { selected, onSelect }, ...cells) {
  return h('div', {
    class: 'row' + (name === selected ? ' sel' : ''),
    'data-name': name,
    onclick: () => onSelect(name),
    ondblclick: () => onSelect(name, { focus: true }),
  },
  h('span', { class: 'dot', style: `background:${colourOf(node)}` }),
  h('span', { class: 'nm', text: name }),
  ...cells);
}

export const nothingFound = () => h('div', { class: 'empty', text: 'ничего не нашлось' });
