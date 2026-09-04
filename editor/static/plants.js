// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The list of cultures on the left and the board in the middle (D-057, D-136).
//
// Доска — не украшение: восемь культур балансируются друг против друга, и
// правило «хорошей во всём не бывает» видно только тогда, когда все требования
// и весь характер стоят рядом в одной таблице. Форма правит одну культуру,
// доска показывает, что эта правка сделала с остальными.

import { h } from './ui.js';

//: Что вывела последняя сборка: щедрость культуры и её потолок (D-057).
//: Правило «хорошей во всём не бывает» меряется этим числом, и без него
//: доска показывала бы, чем культуры отличаются, но не тем, кто перебрал.
const DERIVED = [
  { id: 'yield', title: 'с м²', hint: 'выведено сборкой из часов ухода (D-136)', of: (d) => d.yield_per_m2 },
  { id: 'generosity', title: 'щедрость', hint: 'сумма достоинств культуры (D-057)', of: (d) => d.generosity },
  { id: 'cap', title: 'потолок', hint: 'сколько щедрости культуре позволено: выше — сборка откажет', of: (d) => d.generosity_cap },
];

/** The columns of the board: what a culture asks and what it forgives. */
export const COLUMNS = [
  { id: 'cycle', title: 'цикл', hint: 'суток здорового растения без подкормки', of: (p) => p.cycle },
  { id: 'temp', title: '°C', hint: 'полоса температуры',
    of: (p) => (p.requires?.temp ? `${p.requires.temp.min}…${p.requires.temp.max}` : '') },
  { id: 'water', title: 'вода', hint: 'потребность в воде, 1–3', of: (p) => p.requires?.water },
  { id: 'fertility', title: 'земля', hint: 'требуемое плодородие', of: (p) => p.requires?.fertility },
  { id: 'light', title: 'свет', hint: 'светолюбивость, 1–3', of: (p) => p.requires?.light },
  { id: 'hardiness', title: 'вынос.', hint: 'выносливость, 1–5', of: (p) => p.traits?.hardiness },
  { id: 'disease_risk', title: 'напасти', hint: 'боязнь напастей, 1–5 (D-299)', of: (p) => p.traits?.disease_risk },
  { id: 'density_risk', title: 'теснота', hint: 'боязнь загущения, 1–5 (D-297)', of: (p) => p.traits?.density_risk },
  { id: 'spoilage_k', title: 'порча', hint: 'множитель к сроку хранения', of: (p) => p.traits?.spoilage_k },
  { id: 'restores', title: 'вернёт', hint: 'сколько плодородия культура возвращает почве', of: (p) => p.restores ?? '' },
  { id: 'feeding', title: 'кормят', hint: 'сколько пар «фаза + удобрение» в таблице подкормки', of: (p) => (p.feeding || []).length || '' },
];

function matches(plant, needle) {
  if (!needle) return true;
  const said = [plant.id, plant.name, plant.wild_name, plant.gives, plant.seed, plant.byproduct, plant.note]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return said.includes(needle)
    || (plant.feeding || []).some((row) => String(row?.fertilizer || '').includes(needle));
}

export function renderList(root, plants, { selected, query, onSelect }) {
  const needle = (query || '').trim().toLowerCase();
  const rows = plants.filter((plant) => matches(plant, needle));
  const out = rows.map((plant) => h('div', {
    class: 'row' + (plant.id === selected ? ' sel' : ''),
    'data-name': plant.id,
    title: plant.note || '',
    onclick: () => onSelect(plant.id),
  },
  h('span', { class: 'dot', style: 'background:var(--kind-material)' }),
  h('span', { class: 'nm', text: plant.name }),
  h('span', { class: 'st mono', text: `${plant.cycle} сут` }),
  ));
  if (!out.length) out.push(h('div', { class: 'empty', text: 'ничего не нашлось' }));
  root.replaceChildren(...out);
}

export function renderBoard(root, plants, { selected, query, onSelect, derived = {} }) {
  const needle = (query || '').trim().toLowerCase();
  const shown = plants.filter((plant) => matches(plant, needle));
  const number = (value) => (typeof value === 'number' ? String(Math.round(value * 100) / 100) : '');
  const header = h('tr', {},
    h('th', { text: 'культура' }),
    ...COLUMNS.map((column) => h('th', { class: 'num', title: column.hint, text: column.title })),
    ...DERIVED.map((column) => h('th', { class: 'num dim', title: column.hint, text: column.title })),
    h('th', { text: 'даёт' }),
  );
  const body = shown.map((plant) => h('tr', {
    class: plant.id === selected ? 'sel' : '',
    'data-name': plant.id,
    onclick: () => onSelect(plant.id),
  },
  h('td', {}, h('span', { text: plant.name }), h('span', { class: 'tag mono', text: plant.id })),
  ...COLUMNS.map((column) => h('td', { class: 'num mono', text: String(column.of(plant) ?? '') })),
  ...DERIVED.map((column) => h('td', {
    class: 'num mono dim',
    text: number(column.of(derived[plant.id] || {})),
  })),
  h('td', { class: 'dim', text: plant.gives }),
  ));
  root.replaceChildren(
    h('div', { class: 'board-bar' },
      h('span', {
        class: 'note-line',
        text: `${shown.length} культур · три правых столбца выведены сборкой и не правятся: `
          + 'урожайность считается из часов ухода (D-136), щедрость против потолка — правило D-057',
      }),
    ),
    h('table', { class: 'board' }, h('thead', {}, header), h('tbody', {}, ...body)),
  );
}
