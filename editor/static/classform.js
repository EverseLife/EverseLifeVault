// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The form of one thing class (D-215), seen from the class's side: what it is
// closed by, who asks for it, and its name in every language (D-251).

import { api } from './api.js';
import { actions, errorLine, fail, field, head, namesFields, referencesBlock, touch } from './formkit.js';
import { ask, h } from './ui.js';

export function createClassForm(root, deps) {
  let state = null;
  let detail = null;

  /** A new class, with the thing being looked at already in it: a class is
   *  never made in the abstract -- it is made when a second pickaxe appears. */
  function openNew(defaults = {}) {
    detail = null;
    state = {
      original: null,
      isNew: true,
      klass: { name: '', id: '', note: '', members: defaults.members?.length ? [...defaults.members] : [''] },
      names: {},
    };
    render();
  }

  function open(name, payload) {
    detail = payload;
    const vocab = deps.vocabulary();
    const id = (vocab.class_ids || {})[name] || '';
    state = {
      original: name,
      isNew: false,
      klass: {
        name,
        id,
        note: (vocab.class_notes || {})[name] || '',
        members: [...((vocab.classes || {})[name] || [])],
      },
      names: { ...((deps.locales() || {}) && classNames(deps.locales(), id)) },
    };
    render();
  }

  function classNames(locales, id) {
    const out = {};
    for (const [lang, overlay] of Object.entries(locales || {})) {
      if (overlay?.classes?.[id]) out[lang] = overlay.classes[id];
    }
    return out;
  }

  /** Who asks for this class. Empty here is the whole story of «Утвари»:
   *  a class nothing requires hangs on the ladder on its own. */
  function demandOf(name) {
    if (!name) return [];
    const operations = (deps.operations() || [])
      .filter((op) => (op.requires || []).includes(name))
      .map((op) => op.name);
    const stations = (deps.nodes() || [])
      .filter((node) => node.station === name)
      .map((node) => node.name);
    return [...operations, ...stations];
  }

  function render() {
    const klass = state.klass;
    const node = deps.getNode(state.original) || {};
    const demand = demandOf(state.original);
    const rows = klass.members.map((member, index) => h('div', { class: 'inp cls' },
      h('input', {
        value: member,
        list: 'all-names',
        placeholder: 'чем закрывается',
        oninput: (event) => { klass.members[index] = event.target.value; touch(root); },
      }),
      h('button', {
        class: 'del', text: '×', title: 'убрать из класса',
        onclick: () => { klass.members.splice(index, 1); render(); },
      }),
    ));

    root.replaceChildren(
      head(node.type ? node : { type: 'class' }, state.isNew ? 'Новый класс' : state.original,
        { onRemove: state.isNew ? null : remove }),
      h('div', { class: 'form' },
        h('div', { class: 'note-line',
          text: 'класс вещей (D-215) — «любая из кирок», «любая кровать»: поведение '
            + 'движка и требования привязаны к классу, а не к имени вещи.' }),
        field('название', state.isNew
          ? h('input', {
            value: klass.name, autofocus: true, list: 'all-names',
            placeholder: 'Кирка, Кровать, Ископаемое',
            oninput: (event) => { klass.name = event.target.value; touch(root); },
          })
          : h('input', {
            value: klass.name, disabled: true,
            title: 'переименование класса здесь не делается: на имя завязано '
              + 'поведение движка и требования операций. Заведите новый, '
              + 'перенесите состав, старый удалите',
          })),
        field('id', state.isNew
          ? h('input', {
            class: 'mono', value: klass.id || '', placeholder: 'pickaxe',
            title: 'устойчивый ключ класса (D-251): английский snake_case',
            oninput: (event) => { klass.id = event.target.value; touch(root); },
          })
          : h('input', {
            class: 'mono', value: klass.id || '', disabled: true,
            title: 'ключ класса — идентичность для движка; здесь не меняется',
          })),
        ...namesFields(state.names, deps.languages(), (lang, value) => { state.names[lang] = value; touch(root); }),
        field('пояснение', h('input', {
          value: klass.note || '',
          placeholder: 'зачем класс существует; «поведение: …» — если его знает движок',
          oninput: (event) => { klass.note = event.target.value; touch(root); },
        })),
        h('fieldset', {},
          h('legend', { text: 'чем закрывается' }),
          h('div', { class: 'inputs' }, rows),
          h('div', { class: 'panel-actions' },
            h('button', {
              text: '+ вещь',
              onclick: () => { klass.members.push(''); render(); },
            }),
            h('div', { class: 'spacer' }),
            h('span', { class: 'note-line', text: 'годится любая из перечисленных' }),
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
        errorLine(),
        actions(state.isNew ? 'Создать' : 'Записать', save,
          () => (state.isNew ? deps.clear() : deps.reopen(state.original))),
        state.isNew ? null : referencesBlock(detail?.references, deps.onSelect),
      ),
    );
  }

  async function save() {
    const klass = state.klass;
    const name = (klass.name || '').trim();
    const members = klass.members.map((item) => item.trim()).filter(Boolean);
    try {
      const result = await api.putClass(name, {
        members, note: (klass.note || '').trim(), id: (klass.id || '').trim(), names: state.names,
      });
      if (result.warning) deps.notify(result.warning, false);
      deps.onWrite(result, name);
    } catch (error) {
      fail(root, error, deps.notify);
    }
  }

  async function remove() {
    const demand = demandOf(state.original);
    const answer = await ask({
      title: `Удалить класс «${state.original}»?`,
      body: demand.length
        ? `Его требуют: ${demand.join(', ')}. После удаления требование останется `
          + 'без класса, и проверка вольта покажет разрыв.'
        : 'Ничто его не требует. Вещи, которыми он закрывался, останутся на месте — '
          + 'исчезнет только строка класса и его имена на других языках.',
      ok: 'Удалить',
    });
    if (!answer) return;
    try {
      deps.onWrite(await api.dropClass(state.original), null);
    } catch (error) {
      fail(root, error, deps.notify);
    }
  }

  return { open, openNew, save };
}
