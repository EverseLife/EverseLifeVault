// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The form of one material (D-215): one row of the registry is all a thing
// without a recipe needs to exist -- plus its name in every language (D-251).

import { api } from './api.js';
import {
  actions, derivedBlock, errorLine, fail, field, head, namesFields, referencesBlock, select,
  sourceBlock, touch,
} from './formkit.js';
import { ask, h, num } from './ui.js';

// Поля материала (D-215): одна строка реестра — всё, что нужно новому сырью.
const MATERIAL_NUMBERS = [
  ['mass', 'масса, кг', 'кг за единицу (D-146). Основание всей системы масс'],
  ['rate', 'темп, ед./час', 'выход часа труда (D-133): относительная цена и вес жилы при разведке'],
  ['fuel', 'теплотворность', 'энергии с единицы. Есть число — материал жгут (D-215)'],
];

const MATERIAL_FLAGS = [
  ['bulk', 'дробное', 'весовое: количество бывает дробным (D-212)'],
  ['liquid', 'жидкость', 'существует только в таре с holds: жидкость — в руках и на полу не лежит (D-230)'],
  ['edible', 'съедобное', 'идёт в котёл (D-119)'],
  ['relic', 'реликвия', 'найдено, а не сделано: не снимается, не разбирается, не поднимается (D-232)'],
];

export function createMaterialForm(root, deps) {
  let state = null;
  let detail = null;

  function openNew() {
    detail = null;
    state = {
      original: null,
      isNew: true,
      material: { name: '', id: '', mass: 1, bulk: true },
      names: {},
    };
    render();
  }

  function open(name, payload) {
    detail = payload;
    state = {
      original: name,
      isNew: false,
      material: structuredClone(payload.material),
      names: { ...(payload.names || {}) },
    };
    render();
  }

  function render() {
    const material = state.material;
    const node = deps.getNode(state.original) || { type: 'raw' };
    const vocab = deps.vocabulary();
    const classNames = Object.keys(vocab.class_notes || {})
      .sort((a, b) => a.localeCompare(b, 'ru'));
    const forage = material.forage || {};

    const setNumber = (key) => (event) => {
      const value = event.target.value;
      if (value === '') delete material[key];
      else material[key] = Number(value);
      touch(root);
    };
    const setForage = (key, asNumber) => (event) => {
      const value = event.target.value;
      const next = { ...(material.forage || {}) };
      if (value === '') delete next[key];
      else next[key] = asNumber ? Number(value) : value;
      if (Object.keys(next).length) material.forage = next;
      else delete material.forage;
      touch(root);
    };

    root.replaceChildren(
      head(node, state.isNew ? 'Новый материал' : state.original,
        { onRemove: state.isNew ? null : remove, tag: node.depth != null ? `ступень ${node.depth}` : null }),
      h('div', { class: 'form' },
        h('div', { class: 'note-line',
          text: 'материал — вещь без рецепта (D-215): одна строка реестра, и она '
            + 'существует. «Ископаемое» с темпом уже находится разведкой и '
            + 'добывается киркой — без единой правки кода.' }),
        state.isNew
          ? field('название', h('input', {
            value: material.name || '', autofocus: true,
            placeholder: 'Алмаз',
            oninput: (event) => { material.name = event.target.value; touch(root); },
          }))
          : field('название', h('input', {
            value: material.name || '', disabled: true,
            title: 'материал не переименовывается формой: на имя ссылаются рецепты, операции и мир. '
              + 'Переименование — отдельный осознанный шаг в файле',
          })),
        field('id', h('input', {
          class: 'mono', value: material.id || '', placeholder: 'diamond',
          title: 'устойчивый ключ (D-251): английский snake_case, идентичность '
            + 'вещи в коде и базе. Имена на других языках висят на нём',
          oninput: (event) => {
            if (event.target.value) material.id = event.target.value;
            else delete material.id;
            touch(root);
          },
        })),
        ...namesFields(state.names, deps.languages(), (lang, value) => { state.names[lang] = value; touch(root); }),
        field('класс', select(['', ...classNames], material.class || '', (value) => {
          if (value) material.class = value; else delete material.class;
          render();
        }, (klass) => (klass
          ? `${klass}${(vocab.class_notes || {})[klass] ? ` — ${vocab.class_notes[klass]}` : ''}`
          : '— без класса'))),
        ...MATERIAL_NUMBERS.map(([key, label, title]) => field(label,
          h('input', {
            type: 'number', step: 'any', min: '0', value: num(material[key]),
            title,
            placeholder: key === 'mass' ? 'обязательна, можно 0' : 'пусто — нет',
            oninput: setNumber(key),
          }), { title })),
        h('fieldset', {},
          h('legend', { text: 'собирательство (D-210)' }),
          h('div', { class: 'note-line',
            text: 'есть числа — вещь лежит на поверхности и находится поиском; «где» — свойство узла (D-254), пусто — везде' }),
          field('находок в час', h('input', {
            type: 'number', step: 'any', min: '0', value: num(forage.finds),
            placeholder: 'на forage.reference_area', oninput: setForage('finds', true),
          })),
          field('горсть, ед.', h('input', {
            type: 'number', step: 'any', min: '1', value: num(forage.handful),
            placeholder: 'единиц за находку', oninput: setForage('handful', true),
          })),
          field('где лежит', select(['', ...(deps.places() || [])], forage.place || '',
            (value) => setForage('place', false)({ target: { value } }),
            (place) => place || '— везде')),
        ),
        h('div', { class: 'flags' },
          MATERIAL_FLAGS.map(([key, label, title]) => h('label', { title },
            h('input', {
              type: 'checkbox', checked: !!material[key],
              onchange: (event) => {
                if (event.target.checked) material[key] = true;
                else delete material[key];
                touch(root);
              },
            }),
            label)),
        ),
        errorLine(),
        actions(state.isNew ? 'Создать' : 'Сохранить', save,
          () => (state.isNew ? deps.clear() : deps.reopen(state.original))),
        state.isNew ? null : derivedBlock(detail, node),
        state.isNew ? null : referencesBlock(detail?.references, deps.onSelect),
        state.isNew ? null : sourceBlock(detail),
      ),
    );
  }

  async function save() {
    const material = { ...state.material };
    material.name = (material.name || '').trim();
    try {
      const body = { data: material, names: state.names };
      const result = state.isNew
        ? await api.createMaterial(body)
        : await api.updateMaterial(state.original, body);
      deps.onWrite(result, material.name);
    } catch (error) {
      fail(root, error, deps.notify);
    }
  }

  async function remove() {
    const answer = await ask({
      title: `Удалить материал «${state.original}»?`,
      body: 'Строка реестра и имена на других языках будут вырезаны. Материал, на который '
        + 'ссылаются рецепты или операции, сервер удалить откажется.',
      ok: 'Удалить',
    });
    if (!answer) return;
    try {
      deps.onWrite(await api.removeMaterial(state.original), null);
    } catch (error) {
      fail(root, error, deps.notify);
    }
  }

  return { open, openNew, save };
}
