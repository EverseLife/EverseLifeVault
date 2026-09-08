// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// Панель рельефа во вкладке «Мир»: числа генерации слева, поле справа,
// пересчёт на лету (D-319, D-321, D-323).
//
// Правило одно и оно объясняет всю форму: **числа примеряют, прежде чем
// записать**. Крутнуть зерно и посмотреть — не правка вольта, и файла она не
// трогает; поле для примерки считает движок с этими числами поверх сборки
// (`api_terrain`). Кнопка «записать» — уже правка, и идёт она тем же путём,
// что и любая константа, через проверку вольта.

import { api } from './api.js';
import * as terrain from './terrain.js';
import { h } from './ui.js';

//: Числа, которыми лепят планету, в порядке от общего к частному. Таблицы
//: (доля моря, число рек) правятся по своей планете: у Пироксиса воды нет
//: вовсе, и общее число тут ничего не значит.
const KNOBS = [
  { key: 'terrain.seed', label: 'зерно мира', step: 1, hint: 'одно число — четыре разных мира' },
  { key: 'terrain.sea_share', label: 'доля моря', step: 0.05, table: true, max: 1 },
  { key: 'terrain.mountain_share', label: 'доля гор', step: 0.01, max: 1, hint: 'от суши' },
  { key: 'terrain.rivers', label: 'рек', step: 1, table: true },
  { key: 'terrain.detail_km', label: 'масштаб местного поля, км', step: 0.5 },
  { key: 'terrain.detail_seed', label: 'зерно местного поля', step: 1 },
  { key: 'terrain.detail_amplitude', label: 'сила местного поля', step: 0.05, max: 1 },
  { key: 'terrain.peak_share', label: 'доля вершин', step: 0.01, max: 1 },
  { key: 'terrain.basin_share', label: 'доля впадин', step: 0.01, max: 1, hint: 'из них озёра' },
];

const PLANETS = [
  ['terra', 'Терра'],
  ['pyroxis', 'Пироксис'],
  ['aurora', 'Аврора'],
  ['aquatica', 'Акватика'],
];

//: Сколько ждать после последнего нажатия, прежде чем звать движок. Поле —
//: секунда счёта, и считать его на каждую цифру, набранную в поле ввода,
//: значит греть машину зря.
const SETTLE_MS = 320;

/**
 * Панель целиком. `tools` — то, чем она пишет и говорит: `save(key, value)`
 * кладёт константу через обычную форму вольта, `notify` — строка внизу.
 */
export function terrainPanel(host, { constants, planet = 'terra', tools }) {
  const draft = new Map();
  let field = null;
  let timer = 0;
  let planetKey = planet;

  const canvas = h('canvas', { class: 'terrain-canvas', width: 720, height: 360 });
  const note = h('p', { class: 'note-line', text: 'поле считает движок…' });
  const summary = h('dl', { class: 'terrain-summary' });
  const rows = h('div', { class: 'terrain-knobs' });

  function valueOf(key) {
    if (draft.has(key)) return draft.get(key);
    return constants[key];
  }

  //: Что примеряется: только те числа, которые отличаются от файла. Пустой
  //: список — поле сборки, ровно то, что построит игра.
  function overrides() {
    return [...draft].map(([key, value]) => `${key}=${JSON.stringify(value)}`);
  }

  function setValue(key, value) {
    draft.set(key, value);
    renderKnobs();
    schedule();
  }

  function schedule() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => { timer = 0; void reload(); }, SETTLE_MS);
  }

  async function reload() {
    note.textContent = 'поле считает движок…';
    try {
      field = await api.terrain(planetKey, overrides());
    } catch (error) {
      field = null;
      note.textContent = String(error.message || error);
      note.classList.add('bad');
      return;
    }
    note.classList.remove('bad');
    note.textContent = draft.size
      ? `примеряется ${draft.size} ${draft.size === 1 ? 'число' : 'числа'} — в файл не записано`
      : 'числа из файла: это и есть та планета, которую построит игра';
    terrain.draw(canvas, field);
    renderSummary();
  }

  function renderSummary() {
    if (!field) { summary.replaceChildren(); return; }
    const got = terrain.summary(field);
    const rowsOf = [
      ['море', `${(got.seaShare * 100).toFixed(1)} %`],
      ['горы от суши', `${(got.mountainShare * 100).toFixed(1)} %`],
      ['озёра', got.wet ? String(got.lakes) : 'нет воды'],
      ['реки', String(got.rivers)],
    ];
    summary.replaceChildren(...rowsOf.flatMap(([term, value]) => [
      h('dt', { text: term }), h('dd', { text: value }),
    ]));
  }

  function renderKnobs() {
    rows.replaceChildren(...KNOBS.flatMap((knob) => {
      const value = valueOf(knob.key);
      if (knob.table) {
        const table = value && typeof value === 'object' ? value : {};
        const own = table[planetKey];
        return [numberRow(knob, own, (next) => {
          setValue(knob.key, { ...table, [planetKey]: next });
        }, `${knob.label} · ${planetName(planetKey)}`)];
      }
      return [numberRow(knob, value, (next) => setValue(knob.key, next), knob.label)];
    }));
  }

  function numberRow(knob, value, onInput, label) {
    const input = h('input', {
      type: 'number',
      step: String(knob.step ?? 'any'),
      value: value === undefined || value === null ? '' : String(value),
      onchange: () => {
        const next = Number(input.value);
        if (Number.isFinite(next)) onInput(next);
      },
    });
    const changed = draft.has(knob.key);
    return h('label', { class: `terrain-knob${changed ? ' changed' : ''}` },
      h('span', { class: 'label', text: label }),
      input,
      h('span', { class: 'hint', text: knob.hint || '' }));
  }

  const planetName = (key) => (PLANETS.find(([one]) => one === key) || [key, key])[1];

  const picker = h('div', { class: 'terrain-planets' }, ...PLANETS.map(([key, name]) => h('button', {
    class: 'chip' + (key === planetKey ? ' on' : ''),
    text: name,
    onclick: () => { planetKey = key; renderKnobs(); renderPicker(); void reload(); },
  })));

  function renderPicker() {
    [...picker.children].forEach((button, index) => {
      button.classList.toggle('on', PLANETS[index][0] === planetKey);
    });
  }

  const save = h('button', {
    class: 'primary',
    text: 'записать примеренное',
    onclick: async () => {
      if (!draft.size) { tools.notify('менять нечего: числа те же, что в файле', true); return; }
      for (const [key, value] of [...draft]) {
        await tools.save(key, value);
      }
      draft.clear();
      renderKnobs();
      await reload();
    },
  });

  const reset = h('button', {
    class: 'ghost',
    text: 'вернуть файловые',
    onclick: () => { draft.clear(); renderKnobs(); void reload(); },
  });

  host.replaceChildren(h('div', { class: 'terrain-panel' },
    h('h3', { text: 'Рельеф планеты' }),
    h('p', { class: 'note-line' },
      'числа примеряют, а потом записывают: поле для примерки считает движок '
      + 'теми же формулами, что построят мир (D-319, D-321, D-323)'),
    picker,
    canvas,
    note,
    summary,
    rows,
    h('div', { class: 'row' }, save, reset),
  ));
  renderKnobs();
  void reload();
  return { reload };
}
