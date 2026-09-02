// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// Константы (D-065): список слева и доска посередине.
//
// Графа у этой вкладки нет: числа ничего друг из друга не делают. Слева —
// реестр целиком, группа за группой, с коротким значением у каждого ключа;
// посередине — таблица одной группы (или всего, что нашёл поиск), потому что
// число читается рядом с соседями по группе: `mine.sign_bands` понятен только
// рядом с `mine.sign_noise`.

import { h, num } from './ui.js';

/** Короткая запись значения для списка и таблицы. */
export function spellValue(entry) {
  if (entry.kind === 'formula') return `= ${entry.value}`;
  if (entry.kind === 'value_from') return `из реестра: ${entry.value}`;
  const value = entry.value;
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'да' : 'нет';
  if (typeof value === 'number') return num(value);
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return `список · ${value.length}`;
  if (isRange(value)) return `${num(value.min)} … ${num(value.max)}`;
  const keys = Object.keys(value);
  return `${keys.length} ${keys.length === 1 ? 'строка' : keys.length < 5 ? 'строки' : 'строк'}`;
}

export function isRange(value) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === 2 && 'min' in value && 'max' in value;
}

/** Поиск ищет по ключу, единице, пояснению, решению и по самому значению. */
export function matches(entry, needle) {
  if (!needle) return true;
  const haystack = [
    entry.key, entry.unit || '', entry.note || '', entry.decision || '',
    typeof entry.value === 'object' ? JSON.stringify(entry.value) : String(entry.value ?? ''),
  ].join(' ').toLowerCase();
  return haystack.includes(needle);
}

// ---------------------------------------------------------------------- список

export function renderList(root, groups, { selected, query, onSelect }) {
  const needle = (query || '').trim().toLowerCase();
  const out = [];
  for (const group of groups) {
    const rows = group.constants.filter((entry) => matches(entry, needle));
    if (!rows.length) continue;
    out.push(h('div', { class: 'group', text: `${group.title} · ${group.id}`, title: group.id }));
    for (const entry of rows) {
      out.push(h('div', {
        class: 'row' + (entry.key === selected ? ' sel' : ''),
        'data-name': entry.key,
        title: entry.note || '',
        onclick: () => onSelect(entry.key),
      },
      h('span', { class: 'dot', style: `background:${entry.building ? 'var(--kind-station)' : 'var(--kind-money)'}` }),
      h('span', { class: 'nm mono', text: entry.key.slice(entry.key.indexOf('.') + 1) }),
      h('span', { class: 'st', text: `${spellValue(entry)}${entry.unit && typeof entry.value === 'number' ? ` ${entry.unit}` : ''}` }),
      ));
    }
  }
  if (!out.length) out.push(h('div', { class: 'empty', text: 'ничего не нашлось' }));
  root.replaceChildren(...out);
}

// ----------------------------------------------------------------------- доска

export function renderBoard(root, groups, { selected, query, group, onSelect }) {
  const needle = (query || '').trim().toLowerCase();
  // Без поиска — одна группа: та, в которой стоит выбранное. С поиском — всё,
  // что нашлось, с заголовками групп внутри таблицы.
  const shown = needle
    ? groups.map((one) => ({ ...one, constants: one.constants.filter((entry) => matches(entry, needle)) }))
      .filter((one) => one.constants.length)
    : groups.filter((one) => one.id === group);
  const total = shown.reduce((sum, one) => sum + one.constants.length, 0);

  root.replaceChildren(
    h('div', { class: 'board-bar' },
      h('span', { class: 'note-line',
        text: needle
          ? `нашлось ${total}: ${shown.map((one) => one.title).join(', ')}`
          : (shown[0] ? `${shown[0].title} · ${shown[0].id} · ${total}` : 'выберите группу слева') }),
      h('span', { class: 'spacer' }),
      h('span', { class: 'note-line', text: 'правки уходят в data/constants.yaml; до игры числа доедут сборкой' }),
    ),
    h('table', { class: 'board-table consts' },
      h('thead', {}, h('tr', {},
        h('th', { text: 'ключ' }),
        h('th', { class: 'rt', text: 'значение' }),
        h('th', { text: 'единица' }),
        h('th', { text: 'смысл' }),
        h('th', { text: 'решение' }),
      )),
      h('tbody', {}, ...shown.flatMap((one) => [
        needle ? h('tr', { class: 'grp' }, h('td', { colspan: '5', text: `${one.title} · ${one.id}` })) : null,
        ...one.constants.map((entry) => h('tr', {
          class: entry.key === selected ? 'on' : '',
          onclick: () => onSelect(entry.key),
        },
        h('td', { class: 'nm mono', text: entry.key }),
        h('td', { class: 'rt', text: spellValue(entry), title: typeof entry.value === 'object' ? JSON.stringify(entry.value) : '' }),
        h('td', { class: 'mut', text: entry.unit || '' }),
        h('td', { class: 'mut note', text: entry.note || '' }),
        h('td', { class: 'mut', text: entry.decision || '' }),
        )),
      ])),
    ),
  );
}
