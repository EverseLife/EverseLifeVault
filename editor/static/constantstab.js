// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The «Константы» tab's glue (D-065): the registry, the pick, the writes.
//
// Реестр чисел читается своим запросом: он не лестница, у него нет ни ступеней,
// ни составов, и возить четыре сотни записей с каждым состоянием значило бы
// платить за них на каждой правке рецепта.

import { api } from './api.js';
import { constantForm } from './constantform.js';
import * as constants from './constants.js';
import { h, plural } from './ui.js';

export function createConstantsTab(ctx) {
  const { app, dom, say, reportRun } = ctx;

  const meta = {
    kind: 'board',
    placeholder: 'поиск: ключ, смысл, единица, значение',
    buttons: ['act-new-constant'],
  };

  async function load(keepPick = true) {
    app.constants = await api.constants();
    const groups = app.constants.groups;
    const keys = new Set(groups.flatMap((group) => group.constants.map((entry) => entry.key)));
    if (!keepPick || !keys.has(app.constPick)) app.constPick = null;
    if (!groups.some((group) => group.id === app.constGroup)) app.constGroup = groups[0]?.id || null;
    ctx.refresh();
    openForm();
  }

  function renderFilters() {
    const groups = app.constants?.groups || [];
    const total = groups.reduce((sum, group) => sum + group.constants.length, 0);
    dom.filters.replaceChildren(h('span', {
      class: 'note-line',
      text: `${total} констант в ${groups.length} ${plural(groups.length, 'группе', 'группах', 'группах')} · `
        + 'поиск ищет по ключу, смыслу, единице и значению',
    }));
  }

  function renderList() {
    if (!app.constants) return;
    constants.renderList(dom.list, app.constants.groups, {
      selected: app.constPick,
      query: app.query,
      onSelect: (key) => select(key),
    });
  }

  function renderLegend() {
    dom.legend.replaceChildren(
      h('span', { text: 'ни одно число игры не зашито в код (D-065): движок читает их отсюда по ключу' }),
      h('span', { text: '· число, диапазон, таблица, формула — у каждого своя форма' }),
      h('span', { text: '· карты типов зданий правятся во вкладке «Здания»' }),
      h('span', { text: '· комментарий над ключом — в файле, руками' }),
    );
  }

  function draw() {
    if (!app.constants) return;
    constants.renderBoard(dom.board, app.constants.groups, {
      selected: app.constPick,
      query: app.query,
      group: app.constGroup,
      onSelect: (key) => select(key),
    });
  }

  function select(key) {
    app.constPick = key;
    const group = app.constants.groups.find((one) => one.constants.some((entry) => entry.key === key));
    if (group) app.constGroup = group.id;
    renderList();
    const row = dom.list.querySelector(`.row[data-name="${CSS.escape(key)}"]`);
    row?.scrollIntoView({ block: 'nearest' });
    draw();
    openForm();
  }

  function openForm() {
    const host = document.getElementById('panel');
    if (!app.constPick) {
      app.constForm = null;
      host.replaceChildren(h('div', { class: 'empty', text: 'Выберите константу слева или в таблице.' }));
      return;
    }
    app.constForm = constantForm(host, app.constants, app.constPick, tools);
  }

  // Новая константа заводится в группе выбранной и сразу после неё: числа
  // читаются соседями, и «в конец файла» — не место.
  function openNew() {
    if (!app.constants) return;
    const after = app.constPick;
    app.constPick = null;
    renderList();
    app.constForm = constantForm(document.getElementById('panel'), app.constants, null, tools,
      { group: app.constGroup, after });
  }

  const tools = {
    save: async (original, body) => {
      const result = original === null
        ? await api.createConstant(body)
        : await api.updateConstant(original, body);
      await afterWrite(result, result.saved || original);
    },
    remove: async (key) => {
      await afterWrite(await api.removeConstant(key), null);
    },
    clear: () => { app.constPick = null; renderList(); openForm(); },
    notify: (text, bad) => say(text, bad),
  };

  async function afterWrite(result, openKey) {
    app.constPick = openKey;
    await ctx.reload();
    await load();
    if (result && result.check) reportRun(result.check, 'проверка вольта');
    else say('записано', false, 'записано');
  }

  return {
    meta, load, renderFilters, renderList, renderLegend, draw, select, openForm, openNew,
    enter: load, reopen: load, save: () => app.constForm?.save(),
  };
}
