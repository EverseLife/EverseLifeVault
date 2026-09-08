// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// Вкладка «Космос»: числа неба в одном месте и то, что из них выходит.
//
// Своя вкладка, а не фильтр вкладки констант, по той же причине, по какой у
// мира своя: настраивая небо, держат в голове не реестр, а **миры** — и
// вопрос звучит «что будет с Пироксисом, если поднять массу», а не «в какой
// группе лежит `planet.mass`». Числа те же и правятся тем же путём
// (`constantForm` → `PUT /api/constant`); своё тут — отбор и арифметика.
//
// Ничего не выводится в браузере: сервер отдаёт готовые числа формулами
// движка (`api_space`), и второй реализации не заводится.

import { api } from './api.js';
import { constantForm } from './constantform.js';
import * as constants from './constants.js';
import * as space from './space.js';
import { h, plural } from './ui.js';

export function createSpaceTab(ctx) {
  const { app, dom, say, reportRun } = ctx;

  const meta = {
    kind: 'map',
    placeholder: 'поиск: ключ, смысл, единица, значение',
    buttons: [],
  };

  async function load(keepPick = true) {
    app.space = await api.space();
    const keys = new Set(app.space.groups.flatMap((group) => group.constants.map((one) => one.key)));
    if (!keepPick || !keys.has(app.spacePick)) app.spacePick = null;
    ctx.refresh();
    openForm();
  }

  function renderFilters() {
    if (!app.space) return;
    const total = app.space.groups.reduce((sum, group) => sum + group.constants.length, 0);
    dom.filters.replaceChildren(h('span', {
      class: 'note-line',
      text: `${total} ${plural(total, 'число', 'числа', 'чисел')} неба из`
        + ` ${app.space.groups.length} ${plural(app.space.groups.length, 'группы', 'групп', 'групп')}`
        + ' · правятся здесь же, слева',
    }));
  }

  //: Список — те же константы, что и во вкладке констант, тем же рисовальщиком:
  //: у числа неба нет своего вида, и заводить ему второй было бы враньём.
  function renderList() {
    if (!app.space) return;
    constants.renderList(dom.list, app.space.groups, {
      selected: app.spacePick,
      query: app.query,
      onSelect: (key) => select(key),
    });
  }

  function renderLegend() {
    dom.legend.replaceChildren(
      h('span', { text: 'у мира два размера и они ни из чего друг друга не выводят (D-324)' }),
      h('span', { text: '· тело в небе — масса и радиус, доли Земли: из них тяжесть, плотность и тяготение' }),
      h('span', { text: '· земля под ногами — доля площади Земли: игровая условность ради тесноты' }),
      h('span', { text: '· сплошное кольцо — круг стоянки, пунктир — окно захвата, у каждого мира свой' }),
      h('span', { text: '· система сверху — орбиты в масштабе друг друга; линейка — тела в одном масштабе' }),
      h('span', { text: '· радиус орбиты в вольте не хранится: он следует из года по Кеплеру (D-271)' }),
    );
  }

  function draw() {
    if (!app.space) return;
    dom.worldStage.replaceChildren();
    const box = h('div', { class: 'space-stage' });
    dom.worldStage.append(box);
    //: Сперва линейка: единственное место, где миры сравниваются друг с
    //: другом, а не каждый сам с собой.
    const system = space.systemMap(app.space.worlds);
    if (system) {
      const band = h('div', { class: 'space-band' });
      band.append(h('h4', { text: 'система сверху: орбиты и фазы в час рождения мира' }), system);
      box.append(band);
    }
    const strip = h('div', { class: 'space-band' });
    strip.append(
      h('h4', { text: 'тела в одном масштабе' }),
      space.sizeStrip(app.space.worlds),
    );
    box.append(strip);
    const cards = h('div');
    box.append(cards);
    space.renderWorlds(cards, app.space.worlds, {
      selected: null,
      onSelect: null,
    });
    for (const gap of app.space.missing || []) {
      box.append(h('p', {
        class: 'space-missing',
        text: `${gap.what} здесь не показать: ${gap.why} (${gap.where})`,
      }));
    }
  }

  function select(key) {
    app.spacePick = key;
    renderList();
    const row = dom.list.querySelector(`.row[data-name="${CSS.escape(key)}"]`);
    row?.scrollIntoView({ block: 'nearest' });
    openForm();
  }

  function openForm() {
    const host = document.getElementById('panel');
    if (!app.spacePick) {
      app.spaceForm = null;
      host.replaceChildren(h('div', {
        class: 'empty',
        text: 'Выберите число неба слева — и карточки миров пересчитаются после записи.',
      }));
      return;
    }
    app.spaceForm = constantForm(host, app.space, app.spacePick, tools);
  }

  const tools = {
    save: async (original, body) => {
      await afterWrite(await api.updateConstant(original, body), original);
    },
    remove: async (key) => {
      await afterWrite(await api.removeConstant(key), null);
    },
    clear: () => { app.spacePick = null; renderList(); openForm(); },
    notify: (text, bad) => say(text, bad),
  };

  async function afterWrite(result, openKey) {
    app.spacePick = openKey;
    //: Реестр перечитывается целиком: у чисел неба соседи по всему файлу, и
    //: правка одного двигает выведенные числа всех.
    await load();
    if (result && result.check) reportRun(result.check, 'проверка вольта');
    else say('записано', false, 'записано');
  }

  return {
    meta, load, renderFilters, renderList, renderLegend, draw, select, openForm,
    openNew: () => say('число неба заводится во вкладке «Константы»: там видно, к какой группе', true),
    enter: load, reopen: load, save: () => app.spaceForm?.save(),
  };
}
