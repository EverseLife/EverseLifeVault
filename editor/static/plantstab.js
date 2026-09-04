// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The «Растения» tab's glue (D-057, D-105, D-136): the cultures, the numbers
// they live by, the writes.
//
// Культуры читаются своим запросом: они не лестница, у них нет ни ступеней, ни
// составов. А числа земледелия приходят из реестра констант — те же `farm.*`,
// что и во вкладке «Константы», и вторая дверь к тому же файлу тут была бы
// лишней. Стоят они рядом с культурами потому, что балансируются вместе:
// полоса влаги культуры бессмысленна без `farm.dry_rate`, а `farm.pest_*` —
// без боязни напастей сорта.

import { api } from './api.js';
import { constantForm } from './constantform.js';
import { plantForm } from './plantform.js';
import * as plants from './plants.js';
import { h } from './ui.js';

//: Которые группы констант правит эта вкладка: земледелие и то, что сборка
//: считает от него — часы уборки и полевой автомат.
const GROUPS = ['farm', 'harvest', 'agro'];

export function createPlantsTab(ctx) {
  const { app, dom, say, reportRun } = ctx;

  const meta = {
    kind: 'board',
    placeholder: 'поиск: культура, что даёт, чем кормят, число',
    buttons: ['act-new-plant'],
  };

  async function load(keepPick = true) {
    const [payload, registry] = await Promise.all([api.plants(), api.constants()]);
    app.plants = payload;
    app.plantNumbers = {
      groups: (registry.groups || []).filter((group) => GROUPS.includes(group.id)),
    };
    const ids = new Set((payload.plants || []).map((one) => one.id));
    const keys = new Set(app.plantNumbers.groups.flatMap((g) => g.constants.map((one) => one.key)));
    if (!keepPick || !(ids.has(app.plantPick) || keys.has(app.plantPick))) {
      app.plantPick = payload.plants?.[0]?.id || null;
    }
    ctx.refresh();
    openForm();
  }

  const isNumber = (pick) => typeof pick === 'string' && pick.includes('.');

  function renderFilters() {
    if (!app.plants) return;
    const count = (app.plants.plants || []).length;
    dom.filters.replaceChildren(h('span', {
      class: 'note-line',
      text: `${count} культур · требования и характер идут парой: хорошей во всём быть не должно (D-057)`,
    }));
  }

  function renderList() {
    if (!app.plants) return;
    plants.renderList(dom.list, app.plants.plants || [], {
      selected: app.plantPick,
      query: app.query,
      onSelect: (id) => select(id),
    });
    //: Числа земледелия — той же колонкой под культурами: их правят в том же
    //: заходе, и уводить за ними в другую вкладку значит терять место.
    const needle = (app.query || '').trim().toLowerCase();
    for (const group of app.plantNumbers?.groups || []) {
      const rows = group.constants.filter(
        (one) => !needle
          || one.key.toLowerCase().includes(needle)
          || (one.note || '').toLowerCase().includes(needle),
      );
      if (!rows.length) continue;
      dom.list.append(h('div', { class: 'group', text: `${group.title} · ${group.id}` }));
      for (const entry of rows) {
        dom.list.append(h('div', {
          class: 'row' + (entry.key === app.plantPick ? ' sel' : ''),
          'data-name': entry.key,
          title: entry.note || '',
          onclick: () => select(entry.key),
        },
        h('span', { class: 'dot', style: 'background:var(--kind-money)' }),
        h('span', { class: 'nm mono', text: entry.key.slice(entry.key.indexOf('.') + 1) }),
        h('span', { class: 'st', text: String(entry.value ?? '') }),
        ));
      }
    }
  }

  function renderLegend() {
    dom.legend.replaceChildren(
      h('span', { text: 'культура задаёт требования и характер; урожайность выводит сборка из часов ухода (D-136)' }),
      h('span', { text: '· полоса влаги — из «воды» культуры через farm.moisture_by_need (D-296)' }),
      h('span', { text: '· подкормка — пара «фаза + удобрение»: всё, чего нет в таблице, жжёт' }),
      h('span', { text: '· имена на всех языках правятся здесь же: без них сборка не соберётся (D-251)' }),
      h('span', { text: '· числа земледелия — те же константы, что во вкладке «Константы»' }),
    );
  }

  function draw() {
    if (!app.plants) return;
    plants.renderBoard(dom.board, app.plants.plants || [], {
      selected: app.plantPick,
      query: app.query,
      onSelect: (id) => select(id),
    });
  }

  function select(pick) {
    app.plantPick = pick;
    renderList();
    const row = dom.list.querySelector(`.row[data-name="${CSS.escape(pick)}"]`);
    row?.scrollIntoView({ block: 'nearest' });
    draw();
    openForm();
  }

  function openForm() {
    const host = document.getElementById('panel');
    if (!app.plants || !app.plantPick) {
      host.replaceChildren(h('div', { class: 'empty', text: 'Выберите культуру слева или в таблице.' }));
      return;
    }
    if (isNumber(app.plantPick)) {
      app.constForm = constantForm(host, app.plantNumbers, app.plantPick, numberTools);
      return;
    }
    app.constForm = null;
    plantForm(host, app.plants, app.plantPick, tools);
  }

  function openNew() {
    app.plantPick = null;
    renderList();
    app.constForm = null;
    plantForm(document.getElementById('panel'), app.plants, null, tools, { fresh: true });
  }

  const tools = {
    save: async (original, body, options = {}) => {
      const result = await api.putPlant(body, { fresh: options.fresh, was: original });
      await afterWrite(result, result.saved);
    },
    remove: async (id) => {
      await afterWrite(await api.dropPlant(id), null);
    },
    notify: (text, bad) => say(text, bad),
  };

  //: Число правится той же формой, что и во вкладке «Константы»: одна форма на
  //: один файл, иначе два места разошлись бы в том, что считают допустимым.
  const numberTools = {
    save: async (original, body) => {
      const result = original === null
        ? await api.createConstant(body)
        : await api.updateConstant(original, body);
      await afterWrite(result, result.saved || original);
    },
    remove: async (key) => {
      await afterWrite(await api.removeConstant(key), null);
    },
    clear: () => { app.plantPick = null; renderList(); openForm(); },
    notify: (text, bad) => say(text, bad),
  };

  async function afterWrite(result, openKey) {
    app.plantPick = openKey;
    await load();
    if (result && result.check) reportRun(result.check, 'проверка вольта');
    else say('записано', false, 'записано');
  }

  return {
    meta, load, renderFilters, renderList, renderLegend, draw, select, openForm, openNew,
    enter: load, reopen: load, save: () => app.constForm?.save(),
  };
}
