// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The right-hand panel: the form that writes a recipe, and everything the build
// derived from it. The other forms -- material, class, building type -- live in
// their own files and are opened from here, so that Ctrl+S and «Сбросить» mean
// the same thing whatever is open.
//
// The split matters and the panel keeps it visible. White fields are authored --
// they end up in `data/recipes.yaml` as written. Grey figures underneath are
// derived by `tools/build.py` from labour (D-133) and are shown only so that the
// person editing sees what their change did to the numbers.

import { api } from './api.js';
import { createBuildingForm } from './buildingform.js';
import { createClassForm } from './classform.js';
import {
  actions, derivedBlock, errorLine, fail, field, head, namesFields, referencesBlock, select,
  sourceBlock, touch,
} from './formkit.js';
import { createMaterialForm } from './materialform.js';
import {
  ask, h, joinHours, num, plural, splitHours, TIME_LABEL, TIME_PARTS,
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
  ['liquid', 'жидкость', 'выход льётся в тару, а не в руки; не вошло — вылилось (D-230)'],
  ['powered', 'на электричестве', 'станок работает от питания: ручная партия берёт '
    + '`craft.powered_energy_per_hour` за час, без питания станок стоит (D-269)'],
  ['built', 'строится на месте', 'станция ставится стройплощадкой: выход партии встаёт на пол '
    + 'сразу и в руки не берётся (D-266)'],
];

//: What a container may hold (D-230): the one word the build accepts, or nothing.
const HOLDS = ['', 'жидкость'];

export function createPanel(root, deps) {
  let state = null;
  let detail = null;

  const shared = {
    ...deps,
    clear,
    reopen: (name) => open(name),
    openNewClass: (defaults) => openNewClass(defaults),
  };
  const materials = createMaterialForm(root, shared);
  const classes = createClassForm(root, shared);
  const buildings = createBuildingForm(root, { ...shared, onWrite: deps.onWriteBuilding });

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
      state = { kind: 'class', original: name };
      classes.open(name, payload);
      return;
    }
    if (payload.material) {
      state = { kind: 'material', original: name };
      materials.open(name, payload);
      return;
    }
    if (!payload.editable) {
      state = { kind: 'info', original: name };
      renderInfo(payload, node);
      return;
    }
    state = {
      kind: 'recipe',
      original: name,
      isNew: false,
      level: payload.level,
      section: payload.section,
      data: structuredClone(payload.data),
      names: { ...(payload.names || {}) },
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
        id: '',
        kind: defaults.kind || 'material',
        inputs: defaults.inputs ? [...defaults.inputs] : [''],
        station: defaults.station || 'Верстак',
        // Флаги, с которыми вещь рождается: блюдо приходит сюда уже едой с
        // ролями, чтобы три галочки не ставились руками каждый раз.
        ...(defaults.flags || {}),
      },
      names: {},
      measure: { name: '', unit: '', mass: '', bulk: false, withMass: false },
      classes: { in: [], was: [] },
    };
    render();
  }

  function openNewClass(defaults = {}) {
    detail = null;
    state = { kind: 'class', original: null };
    classes.openNew(defaults);
  }

  function openNewMaterial() {
    detail = null;
    state = { kind: 'material', original: null };
    materials.openNew();
  }

  function openBuilding(name) {
    detail = null;
    state = { kind: 'building', original: name };
    buildings.open(name);
  }

  function openNewBuilding() {
    detail = null;
    state = { kind: 'building', original: null };
    buildings.openNew();
  }

  // -- the class of a thing ----------------------------------------------------

  /** The class this thing carries (one per thing, D-215), as written and as
   *  the form has it. Kept as a list for the save machinery. */
  function memberOf(name) {
    const vocab = deps.vocabulary();
    const inside = Object.entries(vocab.classes || {})
      .filter(([, members]) => members.includes(name))
      .map(([klass]) => klass);
    return { in: [...inside], was: [...inside] };
  }

  function classesChanged() {
    const chosen = state.classes;
    if (!chosen) return false;
    return !(chosen.in.length === chosen.was.length
      && chosen.in.every((klass) => chosen.was.includes(klass)));
  }

  // Класс живёт на строке вещи (`class:`), как и всё остальное, и по той же
  // причине стоит в форме: для того, кто правит кирку, «это кирка вообще» —
  // свойство вещи. Один селект, а не облако из полусотни фишек: у вещи один
  // класс (D-215), и выбирают его, а не собирают.
  function classesBlock() {
    const chosen = state.classes;
    if (!chosen) return null;
    const vocab = deps.vocabulary();
    const all = Object.keys(vocab.class_notes || vocab.classes || {})
      .sort((a, b) => a.localeCompare(b, 'ru'));
    const name = state.data?.name || state.original;
    const current = chosen.in[0] || '';
    return h('fieldset', {},
      h('legend', { text: 'класс вещи' }),
      field('класс', select(['', ...all], current, (value) => {
        chosen.in = value ? [value] : [];
        render();
      }, (klass) => (klass
        ? `${klass}${(vocab.class_notes || {})[klass] ? ` — ${vocab.class_notes[klass]}` : ''}`
        : '— без класса'))),
      current && (vocab.classes[current] || []).length
        ? h('div', { class: 'note-line', text: `в классе: ${vocab.classes[current].join(', ')}` })
        : null,
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
        h('span', {
          class: 'note-line',
          text: classesChanged() ? 'запишется вместе с рецептом' : 'требование «любой из класса» (D-215)',
        }),
      ),
    );
  }

  // -- read-only things ------------------------------------------------------

  function renderInfo(payload, node) {
    root.replaceChildren(
      head(node, payload.name),
      h('div', { class: 'form' },
        h('div', { class: 'note-line',
          text: node.type === 'virtual'
            ? 'рабочее место без рецепта: руки либо стройплощадка (D-216). Рецепта у него нет и быть не может'
            : 'вещь вольта без формы: правится в файле руками' }),
        referencesBlock(payload.references, deps.onSelect),
        sourceBlock(payload),
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
      touch(root);
    };
    const setNumber = (key) => (event) => {
      const value = event.target.value;
      if (value === '') delete data[key];
      else data[key] = Number(value);
      touch(root);
    };

    const levels = vocab.levels;
    const level = levels.find((item) => item.id === Number(state.level));

    const form = h('div', { class: 'form' },
      field('название', h('input', { value: data.name || '', oninput: set('name'), autofocus: state.isNew })),
      field('id', h('input', {
        class: 'mono', value: data.id || '', placeholder: 'iron_ore',
        title: 'устойчивый ключ (D-251): английский snake_case, идентичность '
          + 'вещи в коде и базе. Русское название — язык вольта и игрока; '
          + 'имена на других языках висят на ключе',
        oninput: set('id'),
      })),
      ...namesFields(state.names, deps.languages(), (lang, value) => { state.names[lang] = value; touch(root); }),
      field('тип', select(vocab.kinds, data.kind, (value) => { data.kind = value; touch(root); },
        (kind) => `${kind} — ${KIND_TITLE[kind] || ''}`)),
      field('станция', select(vocab.stations, data.station, (value) => { data.station = value; touch(root); })),
      field('место', h('div', { class: 'pair' },
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
            (value) => { state.section = value || null; touch(root); },
            (id) => (id ? (level.sections.find((s) => s.id === id)?.title || id) : '— без раздела'),
          )
          : h('span', { class: 'note-line', text: 'разделов нет' }),
      )),
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
                touch(root);
              },
            }),
            label,
          )),
        ),
        field('слот', select(['', ...vocab.slots], data.slot || '', (value) => {
          if (value) data.slot = value; else delete data.slot;
          touch(root);
        }, (slot) => slot || '— не надевается')),
        field('масса, кг', h('input', {
          type: 'number', step: 'any', min: '0', value: num(data.mass),
          placeholder: node.matter != null
            ? `из входов: ${num(node.matter)}`
            : (node.mass != null ? `выводится: ${num(node.mass)}` : 'выводится из входов'),
          title: 'масса единицы. Пусто — считается из входов (D-228): сколько '
            + 'вещества вошло, столько вещь и весит. Заданное здесь расчёт '
            + 'переопределяет и само не обновляется; больше вошедшего задать '
            + 'нельзя — материя при переделе не появляется',
          oninput: setNumber('mass'),
        })),
        timeField(data, node),
        field('вмещает, кг', h('div', { class: 'pair wide' },
          h('input', {
            type: 'number', step: 'any', min: '0', value: num(data.store),
            placeholder: 'только у хранилищ (D-181)', oninput: setNumber('store'),
          }),
          select(HOLDS, data.holds || '', (value) => {
            if (value) data.holds = value; else delete data.holds;
            touch(root);
          }, (holds) => (holds ? 'только жидкость' : 'всё, кроме жидкостей')),
        ), { title: 'хранилище (D-181). Тара для жидкостей — `holds: жидкость` (D-230): в неё идёт только жидкость' }),
        field('теплотворность', h('input', {
          type: 'number', step: 'any', min: '0', value: num(data.fuel),
          placeholder: 'пусто — не топливо',
          title: 'энергии с единицы (D-252): рукотворное топливо жгут в топливной станции, '
            + 'как уголь из реестра',
          oninput: setNumber('fuel'),
        })),
        field('пометка', h('input', { value: data.note || '', oninput: set('note'), placeholder: 'note' })),
        // Измерение стоит здесь же, хотя пишется в `meta`: для того, кто правит
        // вещь, «дробное» и «единица» — такие же её свойства, как масса, и
        // делить это на два окна значило бы объяснять читателю устройство файла.
        measureFields(),
      ),
      classesBlock(),
      node.is_class
        ? h('div', { class: 'note-line' },
          `«${state.original}» — ещё и класс вещей: `
          + `${(deps.vocabulary().classes || {})[state.original]?.join(', ') || ''}. `
          + 'На графе класс и вещь показаны одним узлом.')
        : null,
      errorLine(),
      actions(state.isNew ? 'Создать' : 'Сохранить', save,
        () => (state.isNew ? clear() : open(state.original))),
      state.isNew ? null : derivedBlock(detail, node),
      state.isNew ? null : referencesBlock(detail.references, deps.onSelect),
      state.isNew ? null : sourceBlock(detail),
    );

    root.replaceChildren(
      head(node, state.isNew ? 'Новый рецепт' : state.original, {
        onRemove: state.isNew ? null : remove,
        tag: node.depth != null ? `ступень ${node.depth}` : null,
      }),
      form,
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

    return field('время', h('div', { class: 'time' }, TIME_PARTS.map((part) => h('label', { class: 'unit' },
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
    ))), {
      title: 'собственное время изготовления единицы. Пусто — растёт от глубины '
        + 'передела (D-133). Заданное вручную идёт и в количества входов',
    });
  }

  // -- измерение -------------------------------------------------------------

  function measureFields() {
    const measure = state.measure;
    // «Дробное» стоит вплотную к единице не для красоты: вместе они и
    // читаются — «3 м» дробными, «5 шт» целыми, — а порознь спрашивают
    // дважды об одном.
    return field('единица', h('div', { class: 'unit-row' },
      h('input', {
        value: measure.unit, maxlength: 12,
        placeholder: measure.bulk ? 'без подписи' : 'шт.',
        title: 'дорисовывается рядом с числом: «5 шт», «3 м». Только для показа',
        oninput: (event) => { measure.unit = event.target.value; touch(root); },
      }),
      h('label', {
        title: 'весовое: количество бывает дробным (D-212). Штучное — всегда целое, '
          + 'половины слитка не бывает',
      },
      h('input', {
        type: 'checkbox',
        checked: measure.bulk,
        onchange: (event) => { measure.bulk = event.target.checked; render(); },
      }),
      'дробное'),
    ));
  }

  function measureState(name, node) {
    const vocab = deps.vocabulary();
    return {
      name,
      unit: (vocab.units || {})[name] ?? '',
      mass: (vocab.masses || {})[name] ?? '',
      bulk: !!node.bulk,
      withMass: false,
    };
  }

  function measureChanged() {
    const was = measureState(state.measure.name, deps.getNode(state.measure.name) || {});
    return was.unit !== state.measure.unit || was.bulk !== state.measure.bulk;
  }

  function measurePayload(name) {
    return { unit: state.measure.unit, bulk: state.measure.bulk, name };
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
            touch(root);
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
            touch(root);
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

  async function save() {
    const data = collect();
    const body = { data, level: state.level, section: state.section, names: state.names };
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
      fail(root, error, deps.notify);
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
        : 'Ни на что не ссылается. Строка будет вырезана из файла вместе с именами на других языках.',
      ok: 'Удалить',
      extra: detail.comment?.length ? 'удалить и комментарий над строкой' : null,
      extraChecked: true,
    });
    if (!answer) return;
    try {
      deps.onWrite(await api.remove(state.original, { with_comment: answer.extra }), null);
    } catch (error) {
      fail(root, error, deps.notify);
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
      if (state.kind === 'class') return classes.save();
      if (state.kind === 'material') return materials.save();
      if (state.kind === 'building') return buildings.save();
      if (state.kind === 'recipe') return save();
      return null;
    },
    get current() { return state?.original || null; },
  };
}
