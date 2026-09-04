// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The form of one culture (D-057, D-105, D-136): what it asks of a place, what
// it forgives, and what it is fed in which stage (D-296).
//
// Урожайность формой не правится и полем не показана: её выводит сборка из
// часов ухода за цикл (D-136). Поле, которое нельзя записать, в форме не стоит
// — иначе первый же, кто его наберёт, решит, что оно куда-то ушло.
//
// Имя культуры и имя дикого предка спрашиваются на каждом языке (D-251, D-260):
// сборка не примет культуру, которой какой-то язык не знает, и потому оба поля
// стоят рядом с названием, а не «потом».

import { actions, errorLine, fail, field, head, select, touch } from './formkit.js';
import { ask, h } from './ui.js';

const STAGE_WORDS = {
  sprout: 'всходы',
  leaf: 'лист',
  bloom: 'цветение',
  fill: 'налив',
};

const clone = (value) => JSON.parse(JSON.stringify(value ?? null));

function draftOf(plant, names) {
  return {
    id: plant.id || '',
    name: plant.name || '',
    wild_name: plant.wild_name || '',
    seed: plant.seed || '',
    gives: plant.gives || '',
    byproduct: plant.byproduct || '',
    cycle: plant.cycle ?? 6,
    requires: clone(plant.requires) || { temp: { min: 0, max: 25 }, water: 2, fertility: 40, light: 2 },
    traits: clone(plant.traits) || { hardiness: 3, disease_risk: 3, density_risk: 3, spoilage_k: 1 },
    restores: plant.restores ?? '',
    feeding: clone(plant.feeding) || [],
    note: plant.note || '',
    names: { ...(names?.name || {}) },
    wild: { ...(names?.wild || {}) },
  };
}

/**
 * `payload` is what `/api/plants` answered: the cultures, the palettes and the
 * names abroad. `tools` is the tab's own save / remove / notify.
 */
export function plantForm(host, payload, plantId, tools, { fresh = false } = {}) {
  const plant = fresh ? {} : (payload.plants || []).find((one) => one.id === plantId) || {};
  const isNew = fresh || !plant.id;
  const draft = draftOf(plant, (payload.names || {})[plant.id]);
  const languages = payload.languages || [];
  const stages = payload.stages || Object.keys(STAGE_WORDS);
  const fertilizers = payload.palette?.fertilizers || [];

  const number = (value, whole = false) => {
    const said = Number(value);
    if (!Number.isFinite(said)) return value;
    return whole ? Math.round(said) : said;
  };

  function numberField(label, get, set, options = {}) {
    return field(label, h('input', {
      type: 'number',
      class: 'num',
      value: get(),
      step: options.step || 1,
      min: options.min,
      max: options.max,
      oninput: (event) => { set(number(event.target.value, options.whole)); touch(host); },
    }), { title: options.title, hint: options.hint });
  }

  function textField(label, key, options = {}) {
    return field(label, h('input', {
      value: draft[key],
      placeholder: options.placeholder || '',
      list: options.list,
      autofocus: options.autofocus,
      oninput: (event) => { draft[key] = event.target.value; touch(host); },
    }), { title: options.title, hint: options.hint });
  }

  function namesBlock(title, bag, hint) {
    return languages.map((lang) => field(`${title} (${lang})`, h('input', {
      value: bag[lang] || '',
      oninput: (event) => { bag[lang] = event.target.value; touch(host); },
    }), { hint: lang === languages[0] ? hint : null }));
  }

  function feedingBlock() {
    const rows = draft.feeding.map((row, index) => h('div', { class: 'row-edit' },
      select(stages, row.stage, (value) => { row.stage = value; touch(host); },
        (id) => STAGE_WORDS[id] || id),
      select(fertilizers.length ? fertilizers : [row.fertilizer], row.fertilizer,
        (value) => { row.fertilizer = value; touch(host); }),
      h('input', {
        type: 'number', class: 'num', value: row.growth, min: 1, step: 5,
        title: 'на столько процентов быстрее растёт до конца фазы',
        oninput: (event) => { row.growth = number(event.target.value); touch(host); },
      }),
      h('button', {
        class: 'quiet', text: '×', title: 'убрать строку',
        onclick: () => { draft.feeding.splice(index, 1); render(); },
      }),
    ));
    return h('div', { class: 'block' },
      h('div', { class: 'block-head' },
        h('span', { text: 'подкормка растущего' }),
        h('button', {
          class: 'quiet',
          text: '+ строка',
          title: 'фаза, удобрение и на сколько процентов оно ускоряет рост до конца фазы (D-296)',
          onclick: () => {
            draft.feeding.push({ stage: stages[0], fertilizer: fertilizers[0] || '', growth: 50 });
            render();
          },
        }),
      ),
      ...(rows.length
        ? rows
        : [h('div', { class: 'note-line', text: 'не кормят вовсе: любое удобрение — ожог (D-296)' })]),
    );
  }

  function render() {
    host.replaceChildren(
      head({ type: 'material' }, isNew ? 'Новая культура' : draft.name, {
        onRemove: isNew ? null : remove,
        path: 'data/plants.yaml',
        tag: draft.id || null,
      }),
      h('div', { class: 'form' },
        field('идентификатор', h('input', {
          class: 'mono', value: draft.id, placeholder: 'spelt', autofocus: isNew,
          title: 'устойчивый ключ D-251: движок, база и провод знают культуру по нему',
          oninput: (event) => { draft.id = event.target.value; touch(host); },
        })),
        textField('название', 'name', { placeholder: 'Полба', title: 'по-русски: язык вольта' }),
        ...namesBlock('название', draft.names, 'сборка не примет культуру без имени на каждом языке'),
        textField('дикий предок', 'wild_name', {
          placeholder: 'Дикая полба',
          title: 'отдельный сорт и второй родитель при скрещивании (D-260)',
        }),
        ...namesBlock('дикий предок', draft.wild, null),
        textField('семена', 'seed', { placeholder: 'Семена полбы', list: 'plant-goods' }),
        textField('даёт', 'gives', { placeholder: 'Зерно', list: 'plant-goods' }),
        textField('побочно', 'byproduct', { placeholder: 'Солома', list: 'plant-goods', hint: 'если есть' }),
        numberField('цикл, суток', () => draft.cycle, (value) => { draft.cycle = value; },
          { min: 1, title: 'номинал здорового растения без подкормки (D-296): не расписание' }),

        h('div', { class: 'block' },
          h('div', { class: 'block-head' }, h('span', { text: 'что нужно от места' })),
          h('div', { class: 'row-edit' },
            numberField('°C от', () => draft.requires.temp.min, (value) => { draft.requires.temp.min = value; }),
            numberField('до', () => draft.requires.temp.max, (value) => { draft.requires.temp.max = value; }),
          ),
          numberField('вода 1–3', () => draft.requires.water, (value) => { draft.requires.water = value; },
            { min: 1, max: 3, whole: true, title: 'полоса влаги выводится отсюда: farm.moisture_by_need' }),
          numberField('плодородие', () => draft.requires.fertility, (value) => { draft.requires.fertility = value; },
            { min: 0, max: 100 }),
          numberField('свет 1–3', () => draft.requires.light, (value) => { draft.requires.light = value; },
            { min: 1, max: 3, whole: true, title: 'калитка посева по свету узла (D-261)' }),
        ),

        h('div', { class: 'block' },
          h('div', { class: 'block-head' }, h('span', { text: 'характер' })),
          numberField('выносливость 1–5', () => draft.traits.hardiness, (value) => { draft.traits.hardiness = value; },
            { min: 1, max: 5, whole: true, title: 'гасит долю стресса от влаги вне полосы (D-261)' }),
          numberField('боязнь напастей 1–5', () => draft.traits.disease_risk,
            (value) => { draft.traits.disease_risk = value; },
            { min: 1, max: 5, whole: true, title: 'множитель давления напастей (D-299)' }),
          numberField('боязнь тесноты 1–5', () => draft.traits.density_risk,
            (value) => { draft.traits.density_risk = value; },
            { min: 1, max: 5, whole: true, title: 'штраф непрореженного стенда на уборке (D-297)' }),
          numberField('порча ×', () => draft.traits.spoilage_k, (value) => { draft.traits.spoilage_k = value; },
            { min: 0.1, step: 0.1, title: 'множитель к spoilage.food_base для урожая' }),
          numberField('вернёт плодородия, %', () => draft.restores,
            (value) => { draft.restores = value === '' ? '' : value; },
            { min: 0, max: 100, hint: 'только бобовые: пусто — ничего не возвращает' }),
        ),

        feedingBlock(),

        field('заметка', h('textarea', {
          rows: 2, value: draft.note,
          oninput: (event) => { draft.note = event.target.value; touch(host); },
        }), { hint: 'строка каталога: чем культура держится в игре' }),

        h('datalist', { id: 'plant-goods' },
          ...(payload.palette?.goods || []).map((one) => h('option', { value: one })),
        ),
        errorLine(),
        actions(isNew ? 'Завести' : 'Сохранить', save, () => render()),
      ),
    );
  }

  function body() {
    const data = {
      id: draft.id.trim(),
      name: draft.name.trim(),
      wild_name: draft.wild_name.trim(),
      seed: draft.seed.trim(),
      gives: draft.gives.trim(),
      byproduct: draft.byproduct.trim(),
      cycle: draft.cycle,
      requires: draft.requires,
      traits: draft.traits,
      feeding: draft.feeding,
      note: draft.note.trim(),
    };
    if (draft.restores !== '' && draft.restores !== null) data.restores = draft.restores;
    return { data, names: draft.names, wild: draft.wild };
  }

  async function save() {
    try {
      await tools.save(isNew ? null : plant.id, body(), { fresh: isNew });
    } catch (error) {
      fail(host, error, tools.notify);
    }
  }

  async function remove() {
    const yes = await ask({
      title: `Удалить «${draft.name}»?`,
      body: 'Культура уйдёт из файла вместе с именами на всех языках. '
        + 'Семена и урожай в рецептах останутся: их убирают отдельно.',
      ok: 'Удалить',
    });
    if (!yes) return;
    try {
      await tools.remove(plant.id);
    } catch (error) {
      fail(host, error, tools.notify);
    }
  }

  render();
  return { save, render };
}
