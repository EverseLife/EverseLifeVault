// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The form of one building type (D-218). Three maps of `constants.yaml`, a row
// of the small dictionary and a name per language (D-251) -- written together,
// because forgetting one of them is exactly the slip the form exists to prevent.

import { api } from './api.js';
import { actions, errorLine, fail, field, head, namesFields, touch } from './formkit.js';
import { ask, h, num, plural } from './ui.js';

// Два числа типа здания (D-218). Каждое — своя карта в data/constants.yaml, и
// правятся они вместе: тип, у которого есть состав и нет порчи, движок уронит
// на тике, а не в редакторе. Третьим было содержание — оно упразднено вместе с
// самой платой (D-219): за землю берёт земельный налог, за стены — порча.
const BUILDING_NUMBERS = [
  ['growth', 'этаж, ×', 'во сколько раз следующий этаж дороже предыдущего. '
    + 'У дерева вдвое, у металла на 13% — это и есть укрепление', 1, 'от 1'],
  ['decay', 'порча, %/сут', 'сколько состояния дом теряет за сутки. На нуле состояния '
    + 'он обрушается, так что отсюда и срок между ремонтами', 0, '0.5 — раз в полгода'],
];

export function createBuildingForm(root, deps) {
  let state = null;

  function openNew() {
    state = {
      original: null,
      isNew: true,
      building: { kind: '', id: '', per_m2: {}, growth: 1.5, decay: 0.3 },
      names: {},
      rows: [['', '']],
    };
    render();
  }

  function open(name) {
    const found = (deps.buildings() || []).find((row) => row.kind === name);
    if (!found) {
      root.replaceChildren(h('div', { class: 'empty err', text: `типа «${name}» нет в файле` }));
      return;
    }
    state = {
      original: name,
      isNew: false,
      building: structuredClone(found),
      names: { ...(found.names || {}) },
      //: Состав правится строками «материал — сколько», а не картой: пустая
      //: строка внизу и есть кнопка «добавить», и её не приходится искать.
      rows: Object.entries(found.per_m2 || {}).map(([part, amount]) => [part, String(amount)]),
    };
    state.rows.push(['', '']);
    render();
  }

  function render() {
    const building = state.building;
    const node = { type: 'station' };

    const setRow = (index, side) => (event) => {
      state.rows[index][side] = event.target.value;
      //: Последняя строка всегда пустая: заполнили её — снизу появляется новая.
      const last = state.rows[state.rows.length - 1];
      if (last[0].trim() || last[1].trim()) state.rows.push(['', '']);
      touch(root);
      if (side === 0) render();
    };

    const setNumber = (key) => (event) => {
      const value = event.target.value;
      building[key] = value === '' ? '' : Number(value);
      touch(root);
      //: Срок жизни выводится из порчи, и выводить его раз в перерисовку мало:
      //: правят как раз порчу, а читают как раз срок — они обязаны идти вместе.
      if (key === 'decay') {
        const line = root.querySelector('#building-life');
        if (line) line.textContent = lifeLine(building.decay);
      }
    };

    root.replaceChildren(
      head(node, state.isNew ? 'Новый тип здания' : state.original,
        { onRemove: state.isNew ? null : remove }),
      h('div', { class: 'form' },
        h('div', { class: 'note-line',
          text: 'тип здания (D-218) решает три вещи разом: из чего построено, во '
            + 'сколько раз дорожает следующий этаж и как быстро дом ветшает. '
            + 'Потолка высоты нет — за высоту платит смета.' }),

        field('название', h('input', {
          value: building.kind || '', autofocus: state.isNew,
          placeholder: 'кирпичный',
          title: state.isNew ? '' : 'имя типа записано у каждого уже стоящего дома: '
            + 'за переименованием должна пойти миграция движка',
          oninput: (event) => { building.kind = event.target.value; touch(root); },
        })),
        field('id', h('input', {
          class: 'mono', value: building.id || '', placeholder: 'brick',
          title: 'устойчивый ключ (D-251): английский snake_case, строка словаря building_kinds в data/vocabulary.yaml',
          oninput: (event) => { building.id = event.target.value; touch(root); },
        })),
        ...namesFields(state.names, deps.languages(), (lang, value) => { state.names[lang] = value; touch(root); }),

        h('fieldset', {},
          h('legend', { text: 'состав на м² пола первого этажа' }),
          h('div', { class: 'note-line',
            text: 'столько уходит на квадратный метр. Каждый следующий этаж '
              + 'дороже предыдущего — во столько раз, сколько стоит ниже' }),
          h('div', { class: 'inputs' }, state.rows.map(([part, amount], index) => h('div', { class: 'inp two' },
            h('input', {
              value: part, list: 'all-names', placeholder: 'материал',
              oninput: setRow(index, 0),
            }),
            h('input', {
              type: 'number', step: 'any', min: '0', value: amount,
              placeholder: 'ед. на м²', oninput: setRow(index, 1),
            }),
          ))),
        ),

        ...BUILDING_NUMBERS.map(([key, label, title, floor, hint]) => field(label,
          h('input', {
            type: 'number', step: 'any', min: String(floor),
            value: building[key] === '' ? '' : num(building[key]),
            title, placeholder: hint, oninput: setNumber(key),
          }), { title })),

        h('div', { class: 'note-line', id: 'building-life' }, lifeLine(building.decay)),

        errorLine(),
        actions(state.isNew ? 'Создать' : 'Сохранить', save,
          () => (state.isNew ? deps.clear() : open(state.original))),
        h('div', { class: 'note-line',
          text: 'правка уходит в data/constants.yaml сразу во все три карты '
            + 'типа — состав, этаж и порчу, — в словарь vocabulary.yaml и в имена '
            + 'на других языках. Числа доедут до игры сборкой вольта — кнопка «Собрать» наверху.' }),
      ),
    );
  }

  function lifeLine(decay) {
    const rate = Number(decay);
    if (!(rate > 0)) return 'порча не задана: дом стоял бы вечно';
    //: Состояние целого дома — сотня, та же шкала, что у инструмента.
    const days = Math.round(100 / rate);
    return `без ремонта дом простоит ${days} ${plural(days, 'сутки', 'суток', 'суток')} и обрушится`;
  }

  function collect() {
    const per = {};
    for (const [part, amount] of state.rows) {
      const name = (part || '').trim();
      if (!name) continue;
      per[name] = amount === '' ? '' : Number(amount);
    }
    return {
      kind: (state.building.kind || '').trim(),
      per_m2: per,
      growth: state.building.growth,
      decay: state.building.decay,
    };
  }

  async function save() {
    const data = collect();
    const body = { data, id: (state.building.id || '').trim(), names: state.names };
    try {
      const result = state.isNew
        ? await api.createBuilding(body)
        : await api.updateBuilding(state.original, body);
      deps.onWrite(result, data.kind);
    } catch (error) {
      fail(root, error, deps.notify);
    }
  }

  async function remove() {
    const answer = await ask({
      title: `Удалить тип «${state.original}»?`,
      body: 'Тип уйдёт из всех трёх карт сразу, из словаря и из имён на других языках. '
        + 'Дома, уже построенные из него, останутся в мире со своим именем типа — движок '
        + 'перестанет понимать, из чего они, пока их не переведут миграцией.',
      ok: 'Удалить',
    });
    if (!answer) return;
    try {
      deps.onWrite(await api.removeBuilding(state.original), null);
    } catch (error) {
      fail(root, error, deps.notify);
    }
  }

  return { open, openNew, save, get active() { return state !== null; }, drop: () => { state = null; } };
}
