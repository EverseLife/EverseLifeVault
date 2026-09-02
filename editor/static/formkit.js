// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The pieces every form of the right-hand panel is built of: the head with the
// thing's colour and its delete button, a select, the error line, and the
// blocks that show what the build derived and where a thing is used.
//
// One module rather than a wing of `panel.js`, because five forms share them --
// recipe, material, class, building type, constant -- and each lives in its
// own file so that none of them grows past reading in one sitting.

import { colourOf } from './graphview.js';
import { h, num, spellTime } from './ui.js';

/** The head of a form: colour dot, title, an optional tag, the delete button. */
export function head(node, title, { onRemove = null, tag = null, path = null } = {}) {
  return h('div', { class: 'panel-head' },
    h('span', {
      class: 'dot',
      style: `width:9px;height:9px;border-radius:50%;background:${colourOf(node)}`,
    }),
    h('h2', { text: title }),
    path ? h('span', { class: 'tag mono', text: path }) : null,
    tag ? h('span', { class: 'tag', text: tag }) : null,
    // Удаление стоит у названия, а не под формой: оно про вещь целиком, а не
    // про то, что в форме набрано, и его не ищут среди «Сохранить».
    onRemove
      ? h('button', { class: 'danger', onclick: onRemove, text: 'Удалить', title: 'вырезать из файла' })
      : null,
  );
}

export function select(values, current, onchange, label = (value) => value) {
  const box = h('select', { onchange: (event) => onchange(event.target.value) });
  for (const value of values) {
    box.append(h('option', { value, selected: String(value) === String(current) }, label(value)));
  }
  return box;
}

/** A labelled row of the form: label on the left, the control on the right. */
export function field(label, control, { title = null, hint = null } = {}) {
  return h('div', { class: 'field' },
    h('label', { text: label, title }),
    control,
    hint ? h('span', { class: 'hint', text: hint }) : null,
  );
}

/** Clear the error line: the person is typing again. */
export function touch(root) {
  const error = root.querySelector('#panel-error');
  if (error) error.textContent = '';
}

/** Show a refusal where the person is looking: under the form, or in the strip. */
export function fail(root, error, notify) {
  const box = root.querySelector('#panel-error');
  if (box) box.textContent = error.message;
  else notify(error.message, true);
}

export const errorLine = () => h('div', { class: 'err', id: 'panel-error' });

/** The two buttons every form ends with. */
export function actions(primary, onPrimary, onReset, { resetTitle = 'вернуть поля к тому, что записано в вольте' } = {}) {
  return h('div', { class: 'panel-actions' },
    h('button', { class: 'primary', onclick: onPrimary, text: primary }),
    h('button', { onclick: onReset, text: 'Сбросить', title: resetTitle }),
  );
}

// Имя на каждом языке игры (D-251): русское — в самой вещи, остальные —
// оверлеем по id. Сборка не соберётся, пока имени нет на каждом языке, поэтому
// поле стоит рядом с названием и обязательно.
export function namesFields(names, languages, onchange) {
  return languages.map((lang) => field(`название (${lang})`,
    h('input', {
      value: names[lang] || '',
      placeholder: lang === 'en' ? 'Steel pickaxe' : '',
      title: `имя на языке «${lang}» (D-251): пишется в data/locales/${lang}.yaml по id вещи. `
        + 'Без него сборка вольта откажет',
      oninput: (event) => onchange(lang, event.target.value),
    }),
  ));
}

export function derivedBlock(payload, node) {
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

export function referencesBlock(references, onSelect) {
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
      h('div', { class: 'refs' }, items.map((item) => h('button', {
        class: 'ref', text: item, onclick: () => onSelect(item),
      }))),
    )),
  );
}

export function sourceBlock(payload) {
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

/** The comment above an entry, as the file has it: half of what it says. */
export function commentBlock(comment) {
  if (!comment?.length) return null;
  return h('fieldset', {},
    h('legend', { text: 'комментарий в файле' }),
    h('pre', { class: 'src' }, h('span', { class: 'cmt', text: comment.join('\n') })),
  );
}
