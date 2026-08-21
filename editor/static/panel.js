// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The right-hand panel: the form that writes a recipe, and everything the build
// derived from it.
//
// The split matters and the panel keeps it visible. White fields are authored --
// they end up in `data/recipes.yaml` as written. Grey figures underneath are
// derived by `tools/build.py` from labour (D-133) and are shown only so that the
// person editing sees what their change did to the numbers.

import { api } from './api.js';
import { colourOf } from './graphview.js';
import {
  ask, h, joinHours, num, plural, spellTime, splitHours, TIME_LABEL, TIME_PARTS,
} from './ui.js';

const KIND_TITLE = {
  station: 'рабочая станция',
  furniture: 'мебель',
  tool: 'инструмент',
  gear: 'снаряжение',
  vehicle: 'транспорт',
  material: 'материал',
  consumable: 'расходник',
  money: 'монета',
};

const FLAGS = [
  ['key', 'веха', 'ступень лестницы, в тексте набирается жирным'],
  ['mix', 'смесь', 'состав задан пропорцией, а не штуками (D-092)'],
  ['roles', 'роли', 'входы — это роли, а не точный состав (D-119). Только у блюд'],
  ['food', 'еда', 'годится в котёл и в рот'],
  ['hot', 'горячее', 'горячее блюдо'],
  ['edible', 'съедобное', 'идёт в котёл ролью, хотя само не блюдо: мука, масло (D-119)'],
];

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

// Поля материала (D-215): одна строка реестра — всё, что нужно новому сырью.
const MATERIAL_NUMBERS = [
  ['mass', 'масса, кг', 'кг за единицу (D-146). Основание всей системы масс'],
  ['rate', 'темп, ед./час', 'выход часа труда (D-133): относительная цена и вес жилы при разведке'],
  ['fuel', 'теплотворность', 'энергии с единицы. Есть число — материал жгут (D-215)'],
];

export function createPanel(root, deps) {
  let state = null;
  let detail = null;

  function clear() {
    state = null;
    detail = null;
    root.replaceChildren(h('div', { class: 'empty', text: 'Выберите вещь слева или на графе.' }));
  }

  async function open(name) {
    let payload;
    try {
      payload = await api.recipe(name);
    } catch (error) {
      root.replaceChildren(h('div', { class: 'empty err', text: error.message }));
      return;
    }
    detail = payload;
    const node = deps.getNode(name) || {};
    if (node.type === 'class') {
      state = { kind: 'class', original: name, isNew: false, klass: classState(name) };
      renderClass();
      return;
    }
    if (payload.material) {
      state = {
        kind: 'material',
        original: name,
        isNew: false,
        material: structuredClone(payload.material),
        classes: memberOf(name),
      };
      renderMaterial();
      return;
    }
    if (!payload.editable) {
      state = {
        kind: 'info',
        original: name,
        isNew: false,
        readOnly: true,
        measure: measureState(name, node),
        classes: memberOf(name),
      };
      renderInfo(payload);
      return;
    }
    state = {
      kind: 'recipe',
      original: name,
      isNew: false,
      level: payload.level,
      section: payload.section,
      data: structuredClone(payload.data),
      measure: measureState(name, node),
      classes: memberOf(name),
    };
    render();
  }

  // Where a new recipe lands when nothing else says: the level of the thing
  // being looked at, and -- on a level split into sections -- its first section,
  // because such a level keeps no list of its own.
  function placeIn(levelId, section) {
    const levels = deps.vocabulary().levels;
    const level = levels.find((item) => item.id === Number(levelId)) || levels[0];
    if (section && level.sections.some((item) => item.id === section)) return [level.id, section];
    if (!level.plain && level.sections.length) return [level.id, level.sections[0].id];
    return [level.id, null];
  }

  function openNew(defaults = {}) {
    const levels = deps.vocabulary().levels;
    const [level, section] = placeIn(defaults.level ?? levels[0]?.id, defaults.section);
    detail = null;
    state = {
      kind: 'recipe',
      original: null,
      isNew: true,
      level,
      section,
      data: {
        name: '',
        kind: 'material',
        inputs: defaults.inputs ? [...defaults.inputs] : [''],
        station: defaults.station || 'Верстак',
      },
      measure: { name: '', unit: '', mass: '', bulk: false, withMass: false },
      classes: { in: [], was: [] },
    };
    render();
  }

  // -- tool classes ----------------------------------------------------------

  /** A new class, with the thing being looked at already in it: a class is
   *  never made in the abstract -- it is made when a second pickaxe appears. */
  function openNewClass(defaults = {}) {
    detail = null;
    state = {
      kind: 'class',
      original: null,
      isNew: true,
      klass: { name: '', members: defaults.members?.length ? [...defaults.members] : [''] },
    };
    renderClass();
  }

  function classState(name) {
    const members = (deps.vocabulary().classes || {})[name] || [];
    const note = (deps.vocabulary().class_notes || {})[name] || '';
    return { name, note, members: [...members] };
  }

  /** The class this thing carries (one per thing, D-215), as written and as
   *  the form has it. Kept as a list for the chip machinery. */
  function memberOf(name) {
    const classes = deps.vocabulary().classes || {};
    const inside = Object.entries(classes)
      .filter(([, members]) => members.includes(name))
      .map(([klass]) => klass)
      .sort((a, b) => a.localeCompare(b, 'ru'));
    return { in: [...inside], was: [...inside] };
  }

  function classesChanged() {
    const chosen = state.classes;
    if (!chosen) return false;
    const same = chosen.in.length === chosen.was.length
      && chosen.in.every((klass) => chosen.was.includes(klass));
    return !same;
  }

  /** Who asks for this class. Empty here is the whole story of «Утвари»:
   *  a class nothing requires hangs on the ladder on its own. */
  function classDemand(name) {
    if (!name) return [];
    const operations = (deps.operations() || [])
      .filter((op) => (op.requires || []).includes(name))
      .map((op) => op.name);
    const stations = (deps.nodes() || [])
      .filter((node) => node.station === name)
      .map((node) => node.name);
    return [...operations, ...stations];
  }

  function classesBlock() {
    const chosen = state.classes;
    if (!chosen) return null;
    const vocab = deps.vocabulary();
    const all = Object.keys(vocab.class_notes || vocab.classes || {})
      .sort((a, b) => a.localeCompare(b, 'ru'));
    const name = state.data?.name || state.original;
    return h('fieldset', {},
      h('legend', { text: 'класс вещи' }),
      all.length
        ? h('div', { class: 'refs' }, all.map((klass) => h('button', {
          class: 'chip' + (chosen.in.includes(klass) ? ' on' : ''),
          title: `${(vocab.class_notes || {})[klass] || klass}`
            + `${(vocab.classes[klass] || []).length ? ` · ${(vocab.classes[klass] || []).join(', ')}` : ''}`,
          text: klass,
          onclick: () => {
            //: У вещи один класс (D-215): выбор нового снимает прежний.
            chosen.in = chosen.in.includes(klass) ? [] : [klass];
            if (state.kind === 'recipe') render(); else renderInfo(detail);
          },
        })))
        : h('div', { class: 'note-line', text: 'классов в вольте пока нет' }),
      h('div', { class: 'panel-actions' },
        h('button', {
          text: '+ класс',
          title: name
            ? `завести новый класс, закрываемый вещью «${name}»`
            : 'сперва назовите вещь',
          disabled: !name,
          onclick: () => openNewClass({ members: [name] }),
        }),
        h('div', { class: 'spacer' }),
        state.kind === 'recipe'
          ? h('span', {
            class: 'note-line',
            text: classesChanged() ? 'запишется вместе с рецептом' : 'требование «любой из класса»',
          })
          : h('button', {
            text: 'Записать',
            disabled: !classesChanged(),
            onclick: (event) => saveClasses(event.target),
          }),
      ),
    );
  }

  function renderClass() {
    const klass = state.klass;
    const node = deps.getNode(state.original) || {};
    const demand = classDemand(state.original);
    const rows = klass.members.map((member, index) => h('div', { class: 'inp cls' },
      h('input', {
        value: member,
        list: 'all-names',
        placeholder: 'чем закрывается',
        oninput: (event) => { klass.members[index] = event.target.value; touch(); },
      }),
      h('button', {
        class: 'del', text: '×', title: 'убрать из класса',
        onclick: () => { klass.members.splice(index, 1); renderClass(); },
      }),
    ));

    root.replaceChildren(
      head(state.isNew ? 'Новый класс' : state.original, node.type ? node : { type: 'class' },
        { onRemove: state.isNew ? null : removeClass }),
      h('div', { class: 'form' },
        h('div', { class: 'note-line',
          text: 'класс вещей (D-215) — «любая из кирок», «любая кровать»: поведение '
            + 'движка и требования привязаны к классу, а не к имени вещи.' }),
        h('div', { class: 'field' },
          h('label', { text: 'название' }),
          state.isNew
            ? h('input', {
              value: klass.name, autofocus: true, list: 'all-names',
              placeholder: 'Кирка, Кровать, Ископаемое',
              oninput: (event) => { klass.name = event.target.value; touch(); },
            })
            : h('input', {
              value: klass.name, disabled: true,
              title: 'переименование класса здесь не делается: на имя завязано '
                + 'поведение движка и требования операций. Заведите новый, '
                + 'перенесите состав, старый удалите',
            }),
        ),
        h('div', { class: 'field' },
          h('label', { text: 'пояснение' }),
          h('input', {
            value: klass.note || '',
            placeholder: 'зачем класс существует; «поведение: …» — если его знает движок',
            oninput: (event) => { klass.note = event.target.value; touch(); },
          }),
        ),
        h('fieldset', {},
          h('legend', { text: 'чем закрывается' }),
          h('div', { class: 'inputs' }, rows),
          h('div', { class: 'panel-actions' },
            h('button', {
              text: '+ вещь',
              onclick: () => { klass.members.push(''); renderClass(); },
            }),
            h('div', { class: 'spacer' }),
            h('span', {
              class: 'note-line',
              text: 'годится любая из перечисленных',
            }),
          ),
        ),
        h('div', { class: 'note-line', id: 'class-demand' },
          state.isNew
            ? 'новый класс никто пока не требует — впишите его в требования операции '
              + 'либо в станцию рецепта, иначе он повиснет сам по себе'
            : (demand.length
              ? `требуется здесь: ${demand.join(', ')}`
              : 'класс никто не требует: ни операция, ни станция рецепта. '
                + 'На лестнице он висит сам по себе — закрыт снизу, не спрошен сверху'),
        ),
        h('div', { class: 'err', id: 'panel-error' }),
        h('div', { class: 'panel-actions' },
          h('button', {
            class: 'primary', onclick: saveClass, text: state.isNew ? 'Создать' : 'Записать',
          }),
          h('button', {
            onclick: () => (state.isNew ? clear() : open(state.original)),
            text: 'Сбросить',
          }),
        ),
        state.isNew ? null : referencesBlock(detail?.references),
      ),
    );
  }

  async function saveClass() {
    const klass = state.klass;
    const name = (klass.name || '').trim();
    const members = klass.members.map((item) => item.trim()).filter(Boolean);
    try {
      const result = await api.putClass(name, members, (klass.note || '').trim());
      if (result.warning) deps.notify(result.warning, false);
      deps.onWrite(result, name);
    } catch (error) {
      fail(error);
    }
  }

  async function removeClass() {
    const demand = classDemand(state.original);
    const answer = await ask({
      title: `Удалить класс «${state.original}»?`,
      body: demand.length
        ? `Его требуют: ${demand.join(', ')}. После удаления требование останется `
          + 'без класса, и проверка вольта покажет разрыв.'
        : 'Ничто его не требует. Вещи, которыми он закрывался, останутся на месте — '
          + 'исчезнет только строка класса.',
      ok: 'Удалить',
    });
    if (!answer) return;
    try {
      deps.onWrite(await api.dropClass(state.original), null);
    } catch (error) {
      fail(error);
    }
  }

  async function saveClasses(button) {
    button.disabled = true;
    try {
      deps.onWrite(await api.classesOf(state.original, state.classes.in), state.original);
    } catch (error) {
      fail(error);
      button.disabled = false;
    }
  }

  // -- materials (D-215) -----------------------------------------------------

  function openNewMaterial() {
    detail = null;
    state = {
      kind: 'material',
      original: null,
      isNew: true,
      material: { name: '', mass: 1, bulk: true },
      classes: { in: [], was: [] },
    };
    renderMaterial();
  }

  function renderMaterial() {
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
      touch();
    };
    const setForage = (key) => (event) => {
      const value = event.target.value;
      const next = { ...(material.forage || {}) };
      if (value === '') delete next[key];
      else next[key] = Number(value);
      if (Object.keys(next).length) material.forage = next;
      else delete material.forage;
      touch();
    };

    root.replaceChildren(
      head(state.isNew ? 'Новый материал' : state.original, node,
        { onRemove: state.isNew ? null : removeMaterial }),
      h('div', { class: 'form' },
        h('div', { class: 'note-line',
          text: 'материал — вещь без рецепта (D-215): одна строка реестра, и она '
            + 'существует. «Ископаемое» с темпом уже находится разведкой и '
            + 'добывается киркой — без единой правки кода.' }),
        state.isNew
          ? h('div', { class: 'field' },
            h('label', { text: 'название' }),
            h('input', {
              value: material.name || '', autofocus: true,
              placeholder: 'Алмаз',
              oninput: (event) => { material.name = event.target.value; touch(); },
            }))
          : null,
        h('div', { class: 'field' },
          h('label', { text: 'класс' }),
          select(['', ...classNames], material.class || '', (value) => {
            if (value) material.class = value; else delete material.class;
            renderMaterial();
          }, (klass) => (klass
            ? `${klass}${(vocab.class_notes || {})[klass] ? ` — ${vocab.class_notes[klass]}` : ''}`
            : '— без класса')),
        ),
        ...MATERIAL_NUMBERS.map(([key, label, title]) => h('div', { class: 'field' },
          h('label', { text: label, title }),
          h('input', {
            type: 'number', step: 'any', min: '0', value: num(material[key]),
            title,
            placeholder: key === 'mass' ? 'обязательна, можно 0' : 'пусто — нет',
            oninput: setNumber(key),
          }),
        )),
        h('fieldset', {},
          h('legend', { text: 'собирательство (D-210)' }),
          h('div', { class: 'note-line',
            text: 'есть числа — вещь лежит на поверхности и находится поиском' }),
          h('div', { class: 'field' },
            h('label', { text: 'находок в час' }),
            h('input', {
              type: 'number', step: 'any', min: '0', value: num(forage.finds),
              placeholder: 'на forage.reference_area', oninput: setForage('finds'),
            }),
          ),
          h('div', { class: 'field' },
            h('label', { text: 'горсть, ед.' }),
            h('input', {
              type: 'number', step: 'any', min: '1', value: num(forage.handful),
              placeholder: 'единиц за находку', oninput: setForage('handful'),
            }),
          ),
        ),
        h('div', { class: 'flags' },
          h('label', { title: 'весовое: количество бывает дробным (D-212)' },
            h('input', {
              type: 'checkbox', checked: !!material.bulk,
              onchange: (event) => {
                if (event.target.checked) material.bulk = true;
                else delete material.bulk;
                touch();
              },
            }),
            'дробное'),
          h('label', { title: 'идёт в котёл (D-119)' },
            h('input', {
              type: 'checkbox', checked: !!material.edible,
              onchange: (event) => {
                if (event.target.checked) material.edible = true;
                else delete material.edible;
                touch();
              },
            }),
            'съедобное'),
        ),
        h('div', { class: 'err', id: 'panel-error' }),
        h('div', { class: 'panel-actions' },
          h('button', {
            class: 'primary', onclick: saveMaterial,
            text: state.isNew ? 'Создать' : 'Сохранить',
          }),
          h('button', {
            onclick: () => (state.isNew ? clear() : open(state.original)),
            text: 'Сбросить',
          }),
        ),
        state.isNew ? null : derivedBlock(detail, node),
        state.isNew ? null : referencesBlock(detail?.references),
        state.isNew ? null : sourceBlock(detail),
      ),
    );
  }

  async function saveMaterial() {
    const material = { ...state.material };
    material.name = (material.name || '').trim();
    try {
      const result = state.isNew
        ? await api.createMaterial(material)
        : await api.updateMaterial(state.original, material);
      deps.onWrite(result, material.name);
    } catch (error) {
      fail(error);
    }
  }

  async function removeMaterial() {
    const answer = await ask({
      title: `Удалить материал «${state.original}»?`,
      body: 'Строка реестра будет вырезана. Материал, на который ссылаются '
        + 'рецепты или операции, сервер удалить откажется.',
      ok: 'Удалить',
    });
    if (!answer) return;
    try {
      deps.onWrite(await api.removeMaterial(state.original), null);
    } catch (error) {
      fail(error);
    }
  }

  // -- building types (D-218) -------------------------------------------------

  function openNewBuilding() {
    detail = null;
    state = {
      kind: 'building',
      original: null,
      isNew: true,
      building: { kind: '', per_m2: {}, growth: 1.5, decay: 0.3 },
      rows: [['', '']],
    };
    renderBuilding();
  }

  function openBuilding(name) {
    const found = (deps.buildings() || []).find((row) => row.kind === name);
    if (!found) {
      root.replaceChildren(h('div', { class: 'empty err', text: `типа «${name}» нет в файле` }));
      return;
    }
    detail = null;
    state = {
      kind: 'building',
      original: name,
      isNew: false,
      building: structuredClone(found),
      //: Состав правится строками «материал — сколько», а не картой: пустая
      //: строка внизу и есть кнопка «добавить», и её не приходится искать.
      rows: Object.entries(found.per_m2 || {}).map(([part, amount]) => [part, String(amount)]),
    };
    state.rows.push(['', '']);
    renderBuilding();
  }

  function renderBuilding() {
    const building = state.building;
    const node = { type: 'station' };

    const setRow = (index, side) => (event) => {
      state.rows[index][side] = event.target.value;
      //: Последняя строка всегда пустая: заполнили её — снизу появляется новая.
      const last = state.rows[state.rows.length - 1];
      if (last[0].trim() || last[1].trim()) state.rows.push(['', '']);
      touch();
      if (side === 0) renderBuilding();
    };

    const setNumber = (key) => (event) => {
      const value = event.target.value;
      building[key] = value === '' ? '' : Number(value);
      touch();
      //: Срок жизни выводится из порчи, и выводить его раз в перерисовку мало:
      //: правят как раз порчу, а читают как раз срок — они обязаны идти вместе.
      if (key === 'decay') {
        const line = root.querySelector('#building-life');
        if (line) line.textContent = lifeLine(building.decay);
      }
    };

    root.replaceChildren(
      head(state.isNew ? 'Новый тип здания' : state.original, node,
        { onRemove: state.isNew ? null : removeBuilding }),
      h('div', { class: 'form' },
        h('div', { class: 'note-line',
          text: 'тип здания (D-218) решает три вещи разом: из чего построено, во '
            + 'сколько раз дорожает следующий этаж и как быстро дом ветшает. '
            + 'Потолка высоты нет — за высоту платит смета.' }),

        h('div', { class: 'field' },
          h('label', { text: 'название' }),
          h('input', {
            value: building.kind || '', autofocus: state.isNew,
            placeholder: 'кирпичный',
            oninput: (event) => { building.kind = event.target.value; touch(); },
          })),

        h('fieldset', {},
          h('legend', { text: 'состав на м² пола первого этажа' }),
          h('div', { class: 'note-line',
            text: 'столько уходит на квадратный метр. Каждый следующий этаж '
              + 'дороже предыдущего — во столько раз, сколько стоит ниже' }),
          ...state.rows.map(([part, amount], index) => h('div', { class: 'field' },
            h('input', {
              value: part, list: 'all-names', placeholder: 'материал',
              oninput: setRow(index, 0),
            }),
            h('input', {
              type: 'number', step: 'any', min: '0', value: amount,
              placeholder: 'ед. на м²', oninput: setRow(index, 1),
            }),
          )),
        ),

        ...BUILDING_NUMBERS.map(([key, label, title, floor, hint]) => h('div', { class: 'field' },
          h('label', { text: label, title }),
          h('input', {
            type: 'number', step: 'any', min: String(floor),
            value: building[key] === '' ? '' : num(building[key]),
            title, placeholder: hint, oninput: setNumber(key),
          }),
        )),

        h('div', { class: 'note-line', id: 'building-life' },
          lifeLine(building.decay)),

        h('div', { class: 'err', id: 'panel-error' }),
        h('div', { class: 'panel-actions' },
          h('button', {
            class: 'primary', onclick: saveBuilding,
            text: state.isNew ? 'Создать' : 'Сохранить',
          }),
          h('button', {
            onclick: () => (state.isNew ? clear() : openBuilding(state.original)),
            text: 'Сбросить',
          }),
        ),
        h('div', { class: 'note-line',
          text: 'правка уходит в data/constants.yaml сразу во все три карты '
            + 'типа: состав, этаж и порчу. Числа доедут до игры сборкой вольта '
            + '— кнопка «Собрать» наверху.' }),
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

  function collectBuilding() {
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

  async function saveBuilding() {
    const data = collectBuilding();
    try {
      const result = state.isNew
        ? await api.createBuilding(data)
        : await api.updateBuilding(state.original, data);
      deps.onWriteBuilding(result, data.kind);
    } catch (error) {
      fail(error);
    }
  }

  async function removeBuilding() {
    const answer = await ask({
      title: `Удалить тип «${state.original}»?`,
      body: 'Тип уйдёт из всех трёх карт сразу. Дома, уже построенные из '
        + 'него, останутся в мире со своим именем типа — движок перестанет '
        + 'понимать, из чего они, пока их не переведут миграцией.',
      ok: 'Удалить',
    });
    if (!answer) return;
    try {
      deps.onWriteBuilding(await api.removeBuilding(state.original), null);
    } catch (error) {
      fail(error);
    }
  }

  // -- read-only things ------------------------------------------------------

  function renderInfo(payload) {
    const node = deps.getNode(payload.name) || {};
    const what = {
      raw: 'сырьё — берётся из мира, ничем не изготавливается',
      operation: 'продукт операции — делается без рецепта',
      virtual: 'рабочее место без рецепта: руки либо стройплощадка. '
        + 'Рецепта у него нет и быть не может',
    }[node.type] || 'вещь вольта';

    root.replaceChildren(
      head(payload.name, node),
      h('div', { class: 'form' },
        h('div', { class: 'note-line', text: what }),
        node.type === 'operation' && node.operations
          ? h('div', { class: 'note-line', text: `операции: ${node.operations.join(', ')}` })
          : null,
        h('fieldset', {},
          h('legend', { text: 'измерение' }),
          measureFields(),
          h('div', { class: 'panel-actions' },
            h('button', { text: 'Записать', onclick: (event) => saveMeasure(event.target) }),
            h('div', { class: 'spacer' }),
            h('span', { class: 'note-line', id: 'panel-error' }),
          ),
        ),
        node.type === 'virtual' ? null : classesBlock(),
        derivedBlock(payload, node),
        referencesBlock(payload.references),
        h('div', { class: 'note-line' },
          'Сырьё и операции правятся в файле руками: формы у них нет, '
          + 'потому что их немного и каждая строка там объясняется комментарием.'),
      ),
    );
  }

  // -- the form --------------------------------------------------------------

  function render() {
    const vocab = deps.vocabulary();
    const data = state.data;
    const node = deps.getNode(state.original) || {};
    const derived = detail?.derived?.amounts || {};

    const set = (key) => (event) => {
      const value = event.target.value;
      if (value === '') delete data[key];
      else data[key] = value;
      touch();
    };
    const setNumber = (key) => (event) => {
      const value = event.target.value;
      if (value === '') delete data[key];
      else data[key] = Number(value);
      touch();
    };

    const levels = vocab.levels;
    const level = levels.find((item) => item.id === Number(state.level));

    const form = h('div', { class: 'form' },
      h('div', { class: 'field' },
        h('label', { text: 'название' }),
        h('input', { value: data.name || '', oninput: set('name'), autofocus: state.isNew }),
      ),
      h('div', { class: 'field' },
        h('label', { text: 'тип' }),
        select(vocab.kinds, data.kind, (value) => { data.kind = value; touch(); },
          (kind) => `${kind} — ${KIND_TITLE[kind] || ''}`),
      ),
      h('div', { class: 'field' },
        h('label', { text: 'станция' }),
        select(vocab.stations, data.station, (value) => { data.station = value; touch(); }),
      ),
      h('div', { class: 'field' },
        h('label', { text: 'место' }),
        h('div', { class: 'pair' },
          select(levels.map((item) => String(item.id)), String(state.level), (value) => {
            [state.level, state.section] = placeIn(value, null);
            render();
          }, (id) => {
            const found = levels.find((item) => String(item.id) === id);
            return `${id}. ${found ? found.title : ''}`;
          }),
          level && level.sections.length
            ? select(
              [...(level.plain ? [''] : []), ...level.sections.map((s) => s.id)],
              state.section || '',
              (value) => { state.section = value || null; touch(); },
              (id) => (id ? (level.sections.find((s) => s.id === id)?.title || id) : '— без раздела'),
            )
            : h('span', { class: 'note-line', text: 'разделов нет' }),
        ),
      ),
      inputsBlock(data, derived),
      h('fieldset', {},
        h('legend', { text: 'свойства' }),
        h('div', { class: 'flags' },
          FLAGS.map(([key, label, title]) => h('label', { title },
            h('input', {
              type: 'checkbox',
              checked: !!data[key],
              onchange: (event) => {
                if (event.target.checked) data[key] = true;
                else delete data[key];
                touch();
              },
            }),
            label,
          )),
        ),
        h('div', { class: 'field', style: 'margin-top:8px' },
          h('label', { text: 'слот' }),
          select(['', ...vocab.slots], data.slot || '', (value) => {
            if (value) data.slot = value; else delete data.slot;
            touch();
          }, (slot) => slot || '— не надевается'),
        ),
        h('div', { class: 'field' },
          h('label', { text: 'масса, кг' }),
          h('input', {
            type: 'number', step: 'any', min: '0', value: num(data.mass),
            placeholder: node.matter != null
              ? `не больше вошедшего: ${num(node.matter)}`
              : (node.mass != null ? `выводится: ${num(node.mass)}` : 'выводится сборкой'),
            title: 'масса единицы. Пусто — берётся от вошедшего вещества либо от '
              + 'умолчания по типу. Больше вошедшего задать нельзя: материя при '
              + 'переделе не появляется',
            oninput: setNumber('mass'),
          }),
        ),
        timeField(data, node),
        h('div', { class: 'field' },
          h('label', { text: 'вмещает, кг' }),
          h('input', {
            type: 'number', step: 'any', min: '0', value: num(data.store),
            placeholder: 'только у хранилищ (D-181)', oninput: setNumber('store'),
          }),
        ),
        h('div', { class: 'field' },
          h('label', { text: 'пометка' }),
          h('input', { value: data.note || '', oninput: set('note'), placeholder: 'note' }),
        ),
        // Измерение стоит здесь же, хотя пишется в `meta`: для того, кто правит
        // вещь, «дробное» и «единица» — такие же её свойства, как масса, и
        // делить это на два окна значило бы объяснять читателю устройство файла.
        measureFields(),
      ),
      // Класс живёт в `meta`, как и измерение, и по той же причине стоит здесь:
      // для того, кто правит кирку, «это кирка вообще» — свойство вещи, а не
      // устройство файла. Пишется одной кнопкой вместе с рецептом.
      classesBlock(),
      node.is_class
        ? h('div', { class: 'note-line' },
          `«${state.original}» — ещё и класс вещей: `
          + `${(deps.vocabulary().classes || {})[state.original]?.join(', ') || ''}. `
          + 'На графе класс и вещь показаны одним узлом.')
        : null,
      h('div', { class: 'err', id: 'panel-error' }),
      h('div', { class: 'panel-actions' },
        h('button', { class: 'primary', onclick: save, text: state.isNew ? 'Создать' : 'Сохранить' }),
        h('button', {
          onclick: () => (state.isNew ? clear() : open(state.original)),
          text: 'Сбросить',
          title: 'вернуть поля к тому, что записано в вольте',
        }),
      ),
      state.isNew ? null : derivedBlock(detail, node),
      state.isNew ? null : referencesBlock(detail.references),
      state.isNew ? null : sourceBlock(detail),
    );

    root.replaceChildren(
      head(state.isNew ? 'Новый рецепт' : state.original, node, { removable: !state.isNew }),
      form,
    );
  }

  function touch() {
    const error = root.querySelector('#panel-error');
    if (error) error.textContent = '';
  }

  // -- pieces ----------------------------------------------------------------

  function head(title, node, { removable = false, onRemove = null } = {}) {
    const drop = onRemove || (removable ? remove : null);
    return h('div', { class: 'panel-head' },
      h('span', {
        class: 'dot',
        style: `width:9px;height:9px;border-radius:50%;background:${colourOf(node)}`,
      }),
      h('h2', { text: title }),
      node.depth != null ? h('span', { class: 'tag', text: `ступень ${node.depth}` }) : null,
      // Удаление стоит у названия, а не под формой: оно про вещь целиком, а не
      // про то, что в форме набрано, и его не ищут среди «Сохранить».
      drop
        ? h('button', { class: 'danger', onclick: drop, text: 'Удалить', title: 'вырезать строку из файла' })
        : null,
    );
  }

  // -- время -----------------------------------------------------------------

  function timeField(data, node) {
    // Часы, минуты, секунды — всегда все три, даже если время в секундах: клетка
    // на своём месте читается быстрее, чем подпись, которая переезжает. В файл
    // уезжают часы: там их считает сборка.
    const derivedHours = node.step_hours;
    const split = splitHours(data.hours ?? 0);
    const hint = splitHours(derivedHours ?? 0);

    return h('div', { class: 'field' },
      h('label', {
        text: 'время',
        title: 'собственное время изготовления единицы. Пусто — растёт от глубины '
          + 'передела (D-133). Заданное вручную идёт и в количества входов',
      }),
      h('div', { class: 'time' }, TIME_PARTS.map((part) => h('label', { class: 'unit' },
        h('input', {
          type: 'number', min: '0', step: '1',
          value: data.hours == null ? '' : String(split[part]),
          placeholder: derivedHours != null ? String(hint[part]) : '0',
          onchange: (event) => {
            const typed = { ...split, [part]: Number(event.target.value || 0) };
            const total = joinHours(typed);
            if (total > 0) data.hours = Number(total.toFixed(6));
            else delete data.hours;
            render();
          },
        }),
        TIME_LABEL[part],
      ))),
    );
  }

  // -- измерение -------------------------------------------------------------

  function bulkFlag() {
    const measure = state.measure;
    return h('label', {
      title: 'весовое: количество бывает дробным (D-212). Штучное — всегда целое, '
        + 'половины слитка не бывает',
    },
    h('input', {
      type: 'checkbox',
      checked: measure.bulk,
      onchange: (event) => { measure.bulk = event.target.checked; render(); },
    }),
    'дробное');
  }

  function measureFields() {
    const measure = state.measure;
    const node = deps.getNode(measure.name) || {};
    return h('div', {},
      measure.withMass
        ? h('div', { class: 'field' },
          h('label', { text: 'масса, кг' }),
          h('input', {
            type: 'number', step: 'any', min: '0', value: num(measure.mass),
            placeholder: node.mass != null
              ? `в прошлой сборке: ${num(node.mass)}` : 'задаётся руками: выводить не из чего',
            title: 'масса единицы. У сырья и продуктов операций она основание всей '
              + 'системы масс: изделие не тяжелее того, что в него вошло',
            oninput: (event) => { measure.mass = event.target.value; touch(); },
          }),
        )
        : null,
      // «Дробное» стоит вплотную к единице не для красоты: вместе они и
      // читаются — «3 м» дробными, «5 шт» целыми, — а порознь спрашивают
      // дважды об одном.
      h('div', { class: 'field' },
        h('label', { text: 'единица' }),
        h('div', { class: 'unit-row' },
          h('input', {
            value: measure.unit, maxlength: 12,
            placeholder: measure.bulk ? 'без подписи' : 'шт.',
            title: 'дорисовывается рядом с числом: «5 шт», «3 м». Только для показа',
            oninput: (event) => { measure.unit = event.target.value; touch(); },
          }),
          bulkFlag(),
        ),
      ),
    );
  }

  function measureState(name, node) {
    const vocab = deps.vocabulary();
    return {
      name,
      unit: (vocab.units || {})[name] ?? '',
      mass: (vocab.masses || {})[name] ?? '',
      bulk: !!node.bulk,
      withMass: node.type === 'raw' || node.type === 'operation',
    };
  }

  function measureChanged() {
    const was = measureState(state.measure.name, deps.getNode(state.measure.name) || {});
    return was.unit !== state.measure.unit
      || was.bulk !== state.measure.bulk
      || String(was.mass) !== String(state.measure.mass);
  }

  function measurePayload(name) {
    const body = { unit: state.measure.unit, bulk: state.measure.bulk, name };
    if (state.measure.withMass) {
      body.mass = state.measure.mass === '' ? null : Number(state.measure.mass);
    }
    return body;
  }

  function inputsBlock(data, derived) {
    const rows = (data.inputs || []).map((initial, index) => {
      // The row is tied to its position, not to the name it had when drawn: the
      // name field is edited in place, and a quantity typed afterwards must land
      // on the new name, not on the one that was there a keystroke ago.
      const at = () => data.inputs[index];
      const amount = data.amounts?.[initial];
      return h('div', { class: 'inp' },
        h('input', {
          value: initial, list: 'all-names', placeholder: 'вход',
          oninput: (event) => {
            const was = at();
            const next = event.target.value;
            if (data.amounts && was in data.amounts) {
              data.amounts[next] = data.amounts[was];
              delete data.amounts[was];
            }
            if (data.highlight?.includes(was)) {
              data.highlight[data.highlight.indexOf(was)] = next;
            }
            data.inputs[index] = next;
            touch();
          },
        }),
        h('input', {
          type: 'number', step: 'any', min: '0', value: num(amount),
          placeholder: derived[initial] != null ? num(derived[initial]) : 'выв.',
          title: 'количество вручную — исключение (D-133). Пусто — выводится из трудоёмкости',
          oninput: (event) => {
            const value = event.target.value;
            data.amounts = data.amounts || {};
            if (value === '') delete data.amounts[at()];
            else data.amounts[at()] = Number(value);
            if (!Object.keys(data.amounts).length) delete data.amounts;
            touch();
          },
        }),
        h('button', {
          class: 'star' + (data.highlight?.includes(initial) ? ' on' : ''),
          title: 'узкое место ветки: в тексте набирается жирным',
          text: '★',
          onclick: () => {
            data.highlight = data.highlight || [];
            const found = data.highlight.indexOf(at());
            if (found >= 0) data.highlight.splice(found, 1);
            else data.highlight.push(at());
            if (!data.highlight.length) delete data.highlight;
            render();
          },
        }),
        h('button', {
          class: 'del', text: '×', title: 'убрать вход',
          onclick: () => {
            const gone = at();
            data.inputs.splice(index, 1);
            if (data.amounts) delete data.amounts[gone];
            if (data.highlight) data.highlight = data.highlight.filter((item) => item !== gone);
            render();
          },
        }),
      );
    });

    return h('fieldset', {},
      h('legend', { text: 'из чего делается' }),
      h('div', { class: 'inputs' }, rows),
      h('div', { class: 'panel-actions' },
        h('button', {
          text: '+ вход',
          onclick: () => { data.inputs = [...(data.inputs || []), '']; render(); },
        }),
        h('div', { class: 'spacer' }),
        h('span', {
          class: 'note-line',
          text: data.amounts ? 'количества заданы вручную' : 'количества выводит сборка',
        }),
      ),
    );
  }

  function derivedBlock(payload, node) {
    const cost = payload?.cost;
    const rows = [];
    if (node.labor_hours != null) rows.push(['труд', spellTime(node.labor_hours)]);
    if (node.step_hours != null) rows.push(['своё время', spellTime(node.step_hours)]);
    if (node.mass != null) rows.push(['масса', `${num(node.mass)} кг`]);
    if (payload?.derived?.amounts) {
      for (const [item, value] of Object.entries(payload.derived.amounts)) {
        rows.push([`· ${item}`, num(value)]);
      }
    }
    const totals = cost && Object.entries(cost.totals || {});
    return h('fieldset', {},
      h('legend', { text: 'выведено сборкой' }),
      h('div', { class: 'derived' },
        rows.length
          ? h('table', {}, rows.map(([left, right]) => h('tr', {},
            h('td', { class: left.startsWith('·') ? 'muted' : '', text: left }),
            h('td', { text: right }),
          )))
          : h('div', { class: 'muted', text: 'сборка ещё не считала эту вещь' }),
        totals && totals.length
          ? h('details', { style: 'margin-top:6px' },
            h('summary', { text: `в сырье: ${num(cost.mass)} кг` }),
            h('table', {}, totals.map(([item, value]) => h('tr', {},
              h('td', { class: 'muted', text: item }),
              h('td', { text: num(value) }),
            ))))
          : null,
      ),
    );
  }

  function referencesBlock(references) {
    if (!references) return null;
    const groups = [
      ['входит в', references.inputs],
      ['станция для', references.stations],
      ['в операциях', references.operations],
      ['в классах', references.classes],
      ['в списках', references.lists],
    ].filter(([, items]) => items && items.length);
    if (!groups.length) {
      return h('fieldset', {},
        h('legend', { text: 'где используется' }),
        h('div', { class: 'note-line', text: 'нигде: тупик лестницы либо конечная вещь' }));
    }
    return h('fieldset', {},
      h('legend', { text: 'где используется' }),
      groups.map(([title, items]) => h('div', { style: 'margin-bottom:6px' },
        h('div', { class: 'note-line', text: `${title} (${items.length})` }),
        h('div', { class: 'refs' }, items.map((item) => refButton(item))),
      )),
    );
  }

  function refButton(name) {
    return h('button', { class: 'ref', text: name, onclick: () => deps.onSelect(name) });
  }

  function sourceBlock(payload) {
    if (!payload?.source) return null;
    return h('fieldset', {},
      h('legend', { text: 'строка в файле' }),
      h('pre', { class: 'src' },
        payload.comment?.length
          ? h('span', { class: 'cmt', text: `${payload.comment.join('\n')}\n` })
          : null,
        payload.source),
    );
  }

  function select(values, current, onchange, label = (value) => value) {
    const box = h('select', { onchange: (event) => onchange(event.target.value) });
    for (const value of values) {
      box.append(h('option', { value, selected: String(value) === String(current) }, label(value)));
    }
    return box;
  }

  // -- writing ---------------------------------------------------------------

  function collect() {
    const data = { ...state.data };
    data.name = (data.name || '').trim();
    data.inputs = (data.inputs || []).map((item) => item.trim()).filter(Boolean);
    if (data.amounts) {
      data.amounts = Object.fromEntries(
        Object.entries(data.amounts).filter(([key]) => data.inputs.includes(key)),
      );
      if (!Object.keys(data.amounts).length) delete data.amounts;
    }
    if (data.highlight) {
      data.highlight = data.highlight.filter((item) => data.inputs.includes(item));
      if (!data.highlight.length) delete data.highlight;
    }
    return data;
  }

  function fail(error) {
    const box = root.querySelector('#panel-error');
    if (box) box.textContent = error.message;
    else deps.notify(error.message, true);
  }

  async function save() {
    const data = collect();
    const body = { data, level: state.level, section: state.section };
    try {
      if (state.isNew) {
        const made = await api.create(body);
        deps.onWrite(await alsoClasses(await alsoMeasure(made, data.name), data.name), data.name);
        return;
      }
      if (data.name !== state.original) {
        const references = detail.references || {};
        const count = Object.values(references).reduce((sum, list) => sum + list.length, 0);
        if (count) {
          const answer = await ask({
            title: `Переименовать «${state.original}» → «${data.name}»`,
            body: `Старое название упоминается в ${count} ${plural(count, 'месте', 'местах', 'местах')}: `
              + `${[...references.inputs, ...references.stations, ...references.operations]
                .slice(0, 8).join(', ')}${count > 8 ? ' и других' : ''}. `
              + 'Без обновления ссылок лестница развалится, и проверка это покажет.',
            ok: 'Переименовать',
            danger: false,
            extra: 'обновить ссылки во всём файле',
            extraChecked: true,
          });
          if (!answer) return;
          body.rename_refs = answer.extra;
        }
      }
      const saved = await api.update(state.original, body);
      deps.onWrite(await alsoClasses(await alsoMeasure(saved, data.name), data.name), data.name);
    } catch (error) {
      fail(error);
    }
  }

  /** Дописать измерение, если его трогали. Порядок важен: сперва строка
   *  рецепта — она может отказать по составу, — и только потом `meta`. */
  async function alsoMeasure(result, name) {
    if (!measureChanged()) return result;
    return api.measure(name, measurePayload(name));
  }

  /** И классы — той же очередью и по той же причине. */
  async function alsoClasses(result, name) {
    if (!classesChanged()) return result;
    return api.classesOf(name, state.classes.in);
  }

  async function saveMeasure(button) {
    button.disabled = true;
    try {
      deps.onWrite(await api.measure(state.measure.name, measurePayload(state.measure.name)),
        state.measure.name);
    } catch (error) {
      fail(error);
      button.disabled = false;
    }
  }

  async function remove() {
    const references = detail.references || {};
    const used = [...references.inputs, ...references.stations, ...references.operations];
    const answer = await ask({
      title: `Удалить «${state.original}»?`,
      body: used.length
        ? `Вещь используется в ${used.length} ${plural(used.length, 'месте', 'местах', 'местах')}: `
          + `${used.slice(0, 10).join(', ')}`
          + `${used.length > 10 ? ' и других' : ''}. После удаления они останутся без входа, `
          + 'и проверка покажет разрыв.'
        : 'Ни на что не ссылается. Строка будет вырезана из файла.',
      ok: 'Удалить',
      extra: detail.comment?.length ? 'удалить и комментарий над строкой' : null,
      extraChecked: true,
    });
    if (!answer) return;
    try {
      deps.onWrite(await api.remove(state.original, { with_comment: answer.extra }), null);
    } catch (error) {
      fail(error);
    }
  }

  return {
    open,
    openNew,
    openNewClass,
    openNewMaterial,
    openBuilding,
    openNewBuilding,
    clear,
    //: Ctrl+S пишет то, что открыто: рецепт, класс, материал или тип здания.
    save: () => {
      if (!state) return null;
      if (state.kind === 'class') return saveClass();
      if (state.kind === 'material') return saveMaterial();
      if (state.kind === 'building') return saveBuilding();
      return save();
    },
    get current() { return state?.original || null; },
  };
}
