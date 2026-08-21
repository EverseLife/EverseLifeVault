// Типы зданий (D-218): список слева и доска посередине.
//
// Графа у этой вкладки нет и быть не может: типы ничем друг друга не делают,
// между ними нет рёбер — их сравнивают. Поэтому на месте графа таблица, и она
// отвечает ровно на те вопросы, ради которых тип и правят: во что обойдётся
// метр, во сколько раз дорожает этаж и сколько дом простоит без ремонта.
//
// Смета здесь считается той же формулой, что в движке (`build.cost_per_area`):
// состав × пятно × Σ по этажам ростᶰ⁻¹. Это не вторая реализация правила, а
// предпросмотр — правило живёт в вольте, и сюда оно приходит числами.

import { h, num } from './ui.js';

// Состояние целого дома. Величина представления, не баланс: движок берёт её
// той же (`units.SCALE_MAX`), и от неё считается срок жизни без ремонта.
const FULL_CONDITION = 100;

// Этажности, на которых смету и смотрят: от сарая до башни, которую никто не
// построит. Двадцатый этаж стоит в ряду именно затем, чтобы было видно, почему.
const FLOORS_SHOWN = [1, 2, 3, 5, 10, 20];

/** Во сколько раз дом в N этажей дороже одноэтажного того же пятна. */
export function heightFactor(growth, floors) {
  let total = 0;
  for (let floor = 1; floor <= floors; floor += 1) total += growth ** (floor - 1);
  return total;
}

/** Смета: сколько чего уходит на дом такого пятна и такой высоты. */
export function bill(row, footprint, floors) {
  const factor = footprint * heightFactor(Number(row.growth) || 1, floors);
  return Object.fromEntries(
    Object.entries(row.per_m2 || {}).map(([name, per]) => [name, Number(per) * factor]),
  );
}

/** Сколько суток дом простоит без ремонта. Пусто — не ветшает вовсе. */
export function lifetime(decay) {
  const rate = Number(decay);
  return rate > 0 ? Math.round(FULL_CONDITION / rate) : null;
}

/** Состав одной строкой: «камень 15, раствор 5». */
export function spell(per) {
  return Object.entries(per || {})
    .map(([name, amount]) => `${name.toLowerCase()} ${num(amount)}`)
    .join(', ');
}

// ---------------------------------------------------------------------- список

export function renderList(root, rows, { selected, query, onSelect }) {
  // Файл констант мог не прочитаться — тогда вместо типов приходит причина.
  // Список обязан сказать её словами, а не показать строку без названия.
  if (rows.length === 1 && rows[0] && rows[0].error) {
    root.replaceChildren(h('div', { class: 'empty err', text: rows[0].error }));
    return;
  }
  const needle = (query || '').trim().toLowerCase();
  const visible = rows.filter((row) => !needle
    || [row.kind, ...Object.keys(row.per_m2 || {})].join(' ').toLowerCase().includes(needle));

  const out = [h('div', { class: 'group', text: 'от дешёвого к дорогому' })];
  for (const row of visible) {
    out.push(h('div', {
      class: 'row' + (row.kind === selected ? ' sel' : ''),
      'data-name': row.kind,
      onclick: () => onSelect(row.kind),
    },
    h('span', { class: 'dot', style: 'background:var(--kind-station)' }),
    h('span', { class: 'nm', text: row.kind }),
    h('span', {
      class: 'st',
      title: 'рост цены этажа · порча в сутки',
      text: `×${num(row.growth)} · ${num(row.decay)}%`,
    })));
  }
  if (visible.length === 0) out.push(h('div', { class: 'empty', text: 'ничего не нашлось' }));
  root.replaceChildren(...out);
}

// ----------------------------------------------------------------------- доска

export function renderBoard(root, rows, { selected, footprint, onFootprint }) {
  if (!rows.length) {
    root.replaceChildren(h('div', { class: 'empty', text: 'типов зданий в файле нет' }));
    return;
  }
  if (rows[0] && rows[0].error) {
    root.replaceChildren(h('div', { class: 'empty err', text: rows[0].error }));
    return;
  }
  const chosen = rows.find((row) => row.kind === selected) || null;
  const area = Number(footprint) || 1;

  root.replaceChildren(
    h('div', { class: 'board-bar' },
      h('label', { class: 'ctl' }, 'пятно, м²',
        h('input', {
          type: 'number', min: '1', step: '1', value: String(area),
          title: 'площадь одного этажа: смета считается от неё',
          oninput: (event) => onFootprint(Number(event.target.value) || 1),
        })),
      h('span', { class: 'note-line',
        text: 'смета = состав × пятно × сумма по этажам. Потолка высоты нет ни у '
          + 'одного типа — отказывает цена, а не правило' }),
    ),

    h('table', { class: 'board-table' },
      h('thead', {}, h('tr', {},
        h('th', { text: 'тип' }),
        h('th', { text: 'на м² пола' }),
        h('th', { class: 'rt', title: 'во столько раз следующий этаж дороже предыдущего', text: 'этаж' }),
        h('th', { class: 'rt', title: 'процентов состояния в сутки', text: 'порча' }),
        h('th', { class: 'rt', title: 'через столько суток дом обрушится, если не чинить', text: 'без ремонта' }),
      )),
      h('tbody', {}, ...rows.map((row) => {
        const days = lifetime(row.decay);
        return h('tr', { class: row.kind === selected ? 'on' : '' },
          h('td', { class: 'nm', text: row.kind }),
          h('td', { class: 'mut', text: spell(row.per_m2) }),
          h('td', { class: 'rt', text: `×${num(row.growth)}` }),
          h('td', { class: 'rt', text: `${num(row.decay)}%` }),
          h('td', { class: 'rt', text: days === null ? 'вечно' : `${days} сут.` }),
        );
      })),
    ),

    chosen ? billTable(chosen, area) : h('div', {
      class: 'note-line',
      text: 'выберите тип слева — покажу, во что обойдётся дом такого пятна по этажам',
    }),
  );
}

function billTable(row, footprint) {
  const names = Object.keys(row.per_m2 || {});
  return h('div', { class: 'board-bill' },
    h('div', { class: 'group', text: `смета: ${row.kind}, пятно ${num(footprint)} м²` }),
    h('table', { class: 'board-table' },
      h('thead', {}, h('tr', {},
        h('th', { text: 'этажей' }),
        h('th', { class: 'rt', text: 'жилой, м²' }),
        ...names.map((name) => h('th', { class: 'rt', text: name })),
      )),
      h('tbody', {}, ...FLOORS_SHOWN.map((floors) => {
        const lot = bill(row, footprint, floors);
        return h('tr', {},
          h('td', { class: 'nm', text: String(floors) }),
          h('td', { class: 'rt mut', text: num(footprint * floors) }),
          ...names.map((name) => h('td', { class: 'rt', text: big(lot[name]) })),
        );
      })),
    ),
    h('div', { class: 'note-line',
      text: 'двадцатиэтажный дом в таблице стоит не для того, чтобы его строили, '
        + 'а чтобы было видно, во что обходится дешёвый материал на высоте' }),
  );
}

// Числа сметы уходят в миллионы, и «524287500» глазом не читается.
function big(value) {
  const amount = Math.ceil(Number(value) || 0);
  return amount.toLocaleString('ru-RU');
}
