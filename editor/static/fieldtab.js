// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// Вкладка «Планеты»: числа поля, сборка миров и то, что вышло.
//
// Своя вкладка, а не отбор во вкладке констант, по той же причине, что и у
// «Космоса»: настраивая землю, держат в голове не реестр, а **миры**, и
// вопрос звучит «что станет с Авророй, если взять шаг помельче», а не «в
// какой группе лежит terrain.step_m». Числа те же и правятся тем же путём
// (`constantForm` → `PUT /api/constant`); своё тут — отбор, арифметика,
// запуск конвейера и снимки.
//
// До этой вкладки поле строили из терминала: `python tools/landscape.py build
// --planet terra`. Терминал никуда не делся и остаётся главным — здесь просто
// видно, во что обойдётся правка, **до** того как её запустят на два часа.

import { api } from './api.js';
import { constantForm } from './constantform.js';
import * as constants from './constants.js';
import * as field from './field.js';
import { h, plural } from './ui.js';

//: Как часто спрашивать про идущую работу. Секунда: конвейер печатает строку
//: раз в десятки секунд, и чаще незачем, а реже — и полоса стоит мёртвой.
const POLL_MS = 1000;

export function createFieldTab(ctx) {
  const { app, dom, say, reportRun } = ctx;

  const view = {
    kind: 'build',
    planets: new Set(['terra']),
    seed: '', step: '', sea: '', seeds: '6',
    frame: 'planet', layer: 'relief',
  };
  let timer = null;

  const meta = {
    kind: 'map',
    placeholder: 'поиск: ключ, смысл, единица, значение',
    buttons: [],
  };

  async function load(keepPick = true) {
    app.field = await api.field();
    const keys = new Set(app.field.groups.flatMap((g) => g.constants.map((one) => one.key)));
    if (!keepPick || !keys.has(app.fieldPick)) app.fieldPick = null;
    if (!app.fieldPlanet) app.fieldPlanet = app.field.worlds[0]?.planet || 'terra';
    ctx.refresh();
    openForm();
    watch();
  }

  //: Пока работа идёт — спрашивать о ней; кончилась — перечитать состояние
  //: целиком, потому что вместе с полем поменялись и снимки, и вес файла.
  function watch() {
    const job = app.field?.job;
    if (!job || !job.running) {
      if (timer) { clearInterval(timer); timer = null; }
      return;
    }
    if (timer) return;
    timer = setInterval(async () => {
      try {
        const answer = await api.fieldJob();
        app.field.job = answer.job;
        if (answer.job && !answer.job.running) {
          clearInterval(timer);
          timer = null;
          say(answer.job.failed || 'сборка кончилась', Boolean(answer.job.failed));
          await load();
          return;
        }
        if (app.tab === 'field') draw();
      } catch (error) {
        clearInterval(timer);
        timer = null;
        say(String(error.message || error), true);
      }
    }, POLL_MS);
  }

  function renderFilters() {
    if (!app.field) return;
    const total = app.field.groups.reduce((sum, g) => sum + g.constants.length, 0);
    dom.filters.replaceChildren(h('span', {
      class: 'note-line',
      text: `${total} ${plural(total, 'число', 'числа', 'чисел')} земли`
        + ' · правятся здесь же, слева, и планеты пересчитаются после записи',
    }));
  }

  function renderList() {
    if (!app.field) return;
    constants.renderList(dom.list, app.field.groups, {
      selected: app.fieldPick,
      query: app.query,
      onSelect: (key) => select(key),
    });
  }

  function renderLegend() {
    const totals = app.field?.totals;
    dom.legend.replaceChildren(
      h('span', { text: 'клетка одна на все планеты (D-328): дробность каждой выводится из terrain.step_m' }),
      h('span', { text: '· nside целый, поэтому сторона клетки садится рядом с заданной, а не на неё' }),
      totals ? h('span', {
        text: `· всего ${(totals.cells / 1e6).toFixed(2)} млн клеток, ${totals.megabytes} МБ,`
          + ` около ${field.spellSeconds(totals.about_seconds)} на все четыре`,
      }) : null,
      h('span', { text: '· зерно и шаг в пульте примеряются на один прогон и в реестр не пишутся' }),
    );
  }

  function draw() {
    if (!app.field) return;
    dom.worldStage.replaceChildren();
    const box = h('div', { class: 'field-stage' });
    dom.worldStage.append(box);
    //: Без конвейера числа всё равно правятся — не выводится только то, во
    //: что они складываются. Сказать это словами, а не показать пустоту.
    if (app.field.missing) {
      box.append(h('p', { class: 'space-missing', text: app.field.missing }));
    }
    field.planetCards(box, app.field.worlds, {
      picked: app.fieldPlanet,
      onPick: (planet) => { app.fieldPlanet = planet; draw(); },
    });
    field.runPanel(box, app.field, view, tools);
    const world = app.field.worlds.find((one) => one.planet === app.fieldPlanet);
    if (world) {
      box.append(h('h4', { class: 'field-shots-head', text: `снимки: ${field.planetWord(world.planet)}` }));
      field.gallery(box, world, view, tools);
    }
  }

  function select(key) {
    app.fieldPick = key;
    renderList();
    dom.list.querySelector(`.row[data-name="${CSS.escape(key)}"]`)
      ?.scrollIntoView({ block: 'nearest' });
    openForm();
  }

  function openForm() {
    const host = document.getElementById('panel');
    if (!app.fieldPick) {
      app.fieldForm = null;
      host.replaceChildren(h('div', {
        class: 'empty',
        text: 'Выберите число слева — и карточки планет пересчитаются после записи.'
          + ' Поле от записи не пересобирается: это отдельная кнопка, и она стоит минут.',
      }));
      return;
    }
    app.fieldForm = constantForm(host, app.field, app.fieldPick, formTools);
  }

  const tools = {
    setKind: (kind) => { view.kind = kind; draw(); },
    togglePlanet: (planet) => {
      if (view.planets.has(planet)) view.planets.delete(planet);
      else view.planets.add(planet);
      draw();
    },
    setOverride: (name, value) => { view[name] = value; },
    setFrame: (frame) => { view.frame = frame; draw(); },
    setLayer: (layer) => { view.layer = layer; draw(); },
    start: async () => {
      try {
        const answer = await api.fieldRun({
          kind: view.kind,
          planets: [...view.planets],
          seed: view.seed || null,
          step: view.step || null,
          sea: view.sea || null,
          seeds: view.kind === 'scan' ? view.seeds || null : null,
        });
        app.field.job = answer.job;
        say(`пошла работа: ${view.kind}`, false);
        draw();
        watch();
      } catch (error) {
        say(String(error.message || error), true);
      }
    },
    stop: async () => {
      const answer = await api.fieldStop();
      app.field.job = answer.job;
      say('остановлено', true);
      draw();
    },
  };

  const formTools = {
    save: async (original, body) => {
      await afterWrite(await api.updateConstant(original, body), original);
    },
    remove: async (key) => { await afterWrite(await api.removeConstant(key), null); },
    clear: () => { app.fieldPick = null; renderList(); openForm(); },
    notify: (text, bad) => say(text, bad),
  };

  async function afterWrite(result, openKey) {
    app.fieldPick = openKey;
    //: Реестр перечитывается целиком: шаг сетки двигает дробность всех
    //: четырёх планет сразу, и одной карточкой тут не обойдёшься.
    await load();
    if (result && result.check) reportRun(result.check, 'проверка вольта');
    else say('записано', false, 'записано');
  }

  return {
    meta, load, renderFilters, renderList, renderLegend, draw, select, openForm,
    openNew: () => say('число земли заводится во вкладке «Константы»: там видно, к какой группе', true),
    enter: load,
    reopen: load,
    save: () => app.fieldForm?.save(),
  };
}
