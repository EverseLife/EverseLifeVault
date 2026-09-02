// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The form of one constant (D-065): key, value in the shape it has, unit,
// meaning, decision. The value comes in seven shapes and the form shows the one
// the file has: a number as a number, a range as two numbers, a table as rows,
// and anything deeper as YAML -- because a table of tables is easier to read
// as the file writes it than as a form of forms.

import { isRange } from './constants.js';
import { actions, commentBlock, errorLine, fail, field, head, select, touch } from './formkit.js';
import { ask, h, num } from './ui.js';

const SHAPES = [
  ['number', 'число'],
  ['range', 'диапазон'],
  ['bool', 'да / нет'],
  ['string', 'слово'],
  ['table', 'таблица'],
  ['yaml', 'YAML'],
  ['formula', 'формула'],
];
const SHAPE_HINT = {
  number: 'одно число; единица — отдельным полем',
  range: 'от и до: {min, max}',
  bool: 'переключатель: true / false',
  string: 'слово, которое движок сравнивает как есть',
  table: 'ключ → число или слово, по строке на ключ',
  yaml: 'что угодно глубже таблицы — как пишет файл: вложенные карты, список записей',
  formula: 'не число, а правило пересчёта: движок считает его сам, файл держит текст',
};

export function shapeOf(entry) {
  if (entry.kind === 'formula') return 'formula';
  if (entry.kind === 'value_from') return 'value_from';
  const value = entry.value;
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'number') return 'number';
  if (typeof value === 'string') return 'string';
  if (isRange(value)) return 'range';
  if (value && typeof value === 'object' && !Array.isArray(value)
    && Object.values(value).every((one) => one === null || typeof one !== 'object')) return 'table';
  return 'yaml';
}

// -- YAML, the little that the form needs to show a value ----------------------

const RESERVED = new Set(['true', 'false', 'null', 'yes', 'no', 'on', 'off', '~', '']);
const NEEDS_QUOTES = /^[-?:,[\]{}#&*!|>'"%@`]|: | #|:$|^\s|\s$/;

function scalar(value) {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean' || typeof value === 'number') return String(value);
  const text = String(value);
  if (RESERVED.has(text.toLowerCase()) || /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(text)
    || NEEDS_QUOTES.test(text)) return JSON.stringify(text);
  return text;
}

function flow(value) {
  if (Array.isArray(value)) return `[${value.map(flow).join(', ')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.entries(value).map(([key, one]) => `${scalar(key)}: ${flow(one)}`).join(', ')}}`;
  }
  return scalar(value);
}

const isDeep = (value) => value && typeof value === 'object' && !Array.isArray(value)
  && Object.values(value).some((one) => one && typeof one === 'object' && !Array.isArray(one));

/** A value as the file would write it under `value:`, for the textarea. */
export function toYaml(value, indent = 0) {
  const pad = ' '.repeat(indent);
  if (Array.isArray(value)) {
    if (value.every((one) => !one || typeof one !== 'object')) return `${pad}${flow(value)}`;
    return value.map((one) => `${pad}- ${flow(one)}`).join('\n');
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).map(([key, one]) => {
      if (isDeep(one) || (Array.isArray(one) && one.some((item) => item && typeof item === 'object'))) {
        return `${pad}${scalar(key)}:\n${toYaml(one, indent + 2)}`;
      }
      return `${pad}${scalar(key)}: ${flow(one)}`;
    }).join('\n');
  }
  return `${pad}${scalar(value)}`;
}

// -- the form -----------------------------------------------------------------

/** What a value becomes when the person picks another shape for it. */
function convert(draft, shape) {
  const value = draft.value;
  const number = typeof value === 'number' ? value : Number(value) || 0;
  switch (shape) {
    case 'number': return isRange(value) ? value.min : number;
    case 'range': return isRange(value) ? value : { min: number, max: number };
    case 'bool': return !!value;
    case 'string': return typeof value === 'string' ? value : '';
    case 'table': return value && typeof value === 'object' && !Array.isArray(value) && !isRange(value) ? value : {};
    case 'yaml': return value;
    default: return value;
  }
}

export function constantForm(host, registry, key, tools, seed = null) {
  const found = registry.groups.flatMap((group) => group.constants.map((entry) => ({ ...entry, group: group.id })))
    .find((entry) => entry.key === key);
  const isNew = !found;
  const entry = found || {
    key: '', kind: 'value', value: 0, unit: '', note: '', decision: '', comment: [],
    group: seed?.group || registry.groups[0]?.id, ...(seed || {}),
  };
  const draft = {
    key: entry.key,
    shape: shapeOf(entry),
    value: entry.kind === 'value' ? entry.value : null,
    formula: entry.kind === 'formula' ? entry.value : '',
    valueFrom: entry.kind === 'value_from' ? entry.value : null,
    yaml: entry.kind === 'value' ? toYaml(entry.value) : '',
    unit: entry.unit || '',
    note: entry.note || '',
    decision: entry.decision || '',
    group: entry.group,
    after: seed?.after || '',
    rows: [],
  };
  if (draft.shape === 'table') draft.rows = [...Object.entries(draft.value).map(([name, one]) => [name, String(one)]), ['', '']];

  const group = () => registry.groups.find((one) => one.id === draft.group);

  function render() {
    const node = { type: entry.building ? 'station' : 'money' };
    host.replaceChildren(
      head(node, isNew ? 'Новая константа' : entry.key, {
        onRemove: isNew || entry.building ? null : remove,
        path: group()?.title || null,
      }),
      h('div', { class: 'form' },
        entry.building
          ? h('div', { class: 'note-line', text: 'карта типов зданий (D-218): правится во вкладке «Здания» — там три карты типа идут вместе' })
          : null,
        isNew ? field('группа', select(registry.groups.map((one) => one.id), draft.group, (value) => {
          draft.group = value;
          draft.after = '';
          render();
        }, (id) => `${registry.groups.find((one) => one.id === id)?.title || id} · ${id}`)) : null,
        isNew ? field('после', select(['', ...(group()?.constants.map((one) => one.key) || [])], draft.after,
          (value) => { draft.after = value; touch(host); },
          (value) => value || '— в конец группы')) : null,
        field('ключ', h('input', {
          class: 'mono', value: draft.key, placeholder: `${draft.group || 'craft'}.amount_cap`,
          disabled: !!entry.building, autofocus: isNew,
          title: 'пространство и имя через точку, строчная латиница. Движок достаёт число по этому ключу: '
            + 'переименование — правка кода',
          oninput: (event) => { draft.key = event.target.value; touch(host); },
        })),
        draft.shape === 'value_from'
          ? field('источник', h('input', { value: draft.valueFrom, disabled: true,
            title: 'таблица собирается сборкой из реестра материалов (D-215): править нужно материалы' }))
          : field('вид', select(SHAPES.map(([id]) => id), draft.shape, (value) => {
            if (value === 'formula') draft.formula = draft.formula || '';
            else draft.value = convert(draft, value);
            if (value === 'table') draft.rows = [...Object.entries(draft.value).map(([name, one]) => [name, String(one)]), ['', '']];
            if (value === 'yaml') draft.yaml = toYaml(draft.value);
            draft.shape = value;
            render();
          }, (id) => SHAPES.find(([one]) => one === id)[1]), { hint: SHAPE_HINT[draft.shape] }),
        valueControl(),
        field('единица', h('input', {
          value: draft.unit, placeholder: 'ед./час, %, кг, ×',
          oninput: (event) => { draft.unit = event.target.value; touch(host); },
        })),
        field('смысл', h('input', {
          value: draft.note, placeholder: 'что это число значит для человека',
          oninput: (event) => { draft.note = event.target.value; touch(host); },
        })),
        field('решение', h('input', {
          value: draft.decision, placeholder: 'D-065', class: 'mono',
          title: 'D-XXX, если число зафиксировано решением, а не подобрано',
          oninput: (event) => { draft.decision = event.target.value; touch(host); },
        })),
        !isNew && draft.key !== entry.key
          ? h('div', { class: 'note-line warn', text: 'ключ меняется: движок читает константу по ключу, за правкой вольта должна пойти правка кода' })
          : null,
        errorLine(),
        entry.building ? null : actions(isNew ? 'Создать' : 'Сохранить', save,
          () => (isNew ? tools.clear() : constantForm(host, registry, key, tools))),
        commentBlock(entry.comment),
        h('div', { class: 'note-line',
          text: 'константа применяется к миру сборкой вольта и деплоем, без выката версии (D-065). '
            + 'Комментарий над ключом правится в файле: он объясняет число, а не задаёт его' }),
      ),
    );
  }

  function valueControl() {
    switch (draft.shape) {
      case 'value_from':
        return null;
      case 'formula':
        return field('формула', h('input', {
          class: 'mono', value: draft.formula, placeholder: 'base_life * (0.5 + quality / 80)',
          oninput: (event) => { draft.formula = event.target.value; touch(host); },
        }));
      case 'number':
        return field('значение', h('input', {
          type: 'number', step: 'any', value: draft.value === null ? '' : num(draft.value),
          oninput: (event) => { draft.value = event.target.value === '' ? null : Number(event.target.value); touch(host); },
        }));
      case 'range':
        return field('от · до', h('div', { class: 'pair' },
          h('input', { type: 'number', step: 'any', value: num(draft.value?.min), placeholder: 'min',
            oninput: (event) => { draft.value = { ...draft.value, min: Number(event.target.value) }; touch(host); } }),
          h('input', { type: 'number', step: 'any', value: num(draft.value?.max), placeholder: 'max',
            oninput: (event) => { draft.value = { ...draft.value, max: Number(event.target.value) }; touch(host); } }),
        ));
      case 'bool':
        return field('значение', h('label', { class: 'tick' },
          h('input', { type: 'checkbox', checked: !!draft.value,
            onchange: (event) => { draft.value = event.target.checked; touch(host); } }),
          draft.value ? 'true' : 'false'));
      case 'string':
        return field('значение', h('input', {
          value: draft.value || '',
          oninput: (event) => { draft.value = event.target.value; touch(host); },
        }));
      case 'table':
        return h('fieldset', {},
          h('legend', { text: 'таблица' }),
          h('div', { class: 'inputs' }, draft.rows.map(([name, value], index) => h('div', { class: 'inp two' },
            h('input', { value: name, placeholder: 'ключ', list: 'all-names',
              oninput: (event) => { draft.rows[index][0] = event.target.value; growRows(); } }),
            h('input', { class: 'mono', value, placeholder: 'число или слово',
              oninput: (event) => { draft.rows[index][1] = event.target.value; growRows(); } }),
          ))),
          h('div', { class: 'note-line', text: 'последняя строка всегда пустая: заполнили — появится следующая. Пустой ключ — строка не пишется' }),
        );
      default:
        return field('значение', h('textarea', {
          class: 'mono yaml', rows: String(Math.min(16, Math.max(4, draft.yaml.split('\n').length + 1))),
          spellcheck: 'false',
          oninput: (event) => { draft.yaml = event.target.value; touch(host); },
        }, draft.yaml));
    }
  }

  function growRows() {
    touch(host);
    const last = draft.rows[draft.rows.length - 1];
    if (last[0].trim() || last[1].trim()) {
      draft.rows.push(['', '']);
      render();
    }
  }

  function collect() {
    const data = { key: draft.key.trim(), unit: draft.unit, note: draft.note, decision: draft.decision };
    switch (draft.shape) {
      case 'value_from': data.value_from = draft.valueFrom; break;
      case 'formula': data.formula = draft.formula; break;
      case 'yaml': data.value_yaml = draft.yaml; break;
      case 'table': {
        const table = {};
        for (const [name, value] of draft.rows) {
          if (!name.trim()) continue;
          const text = value.trim();
          table[name.trim()] = text !== '' && Number.isFinite(Number(text)) ? Number(text) : text;
        }
        data.value = table;
        break;
      }
      default: data.value = draft.value;
    }
    return data;
  }

  async function save() {
    try {
      const body = { data: collect() };
      if (isNew) {
        body.group = draft.group;
        body.after = draft.after || null;
      }
      await tools.save(isNew ? null : entry.key, body);
    } catch (error) {
      fail(host, error, tools.notify);
    }
  }

  async function remove() {
    const answer = await ask({
      title: `Удалить «${entry.key}»?`,
      body: 'Запись уйдёт из файла вместе с комментарием над ней. Документы вольта, которые '
        + 'ссылаются на ключ, проверка покажет; движок, если читает его, узнает при старте.',
      ok: 'Удалить',
    });
    if (!answer) return;
    try {
      await tools.remove(entry.key);
    } catch (error) {
      fail(host, error, tools.notify);
    }
  }

  render();
  return { save };
}
