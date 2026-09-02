// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The «Рецепты» tab: the whole ladder as a graph, the list by levels, the
// chips that hide a type. Only «из чего делается» is drawn: on what station a
// thing is made is the «Станции» tab, and drawing both relations in one
// picture would be arguing with oneself.

import { KIND_COLOUR } from './graphview.js';
import { isDish, listRow, nothingFound, TYPE_LABEL, typeOf } from './ladderkit.js';
import { neighbourhood } from './layout.js';
import { h, things } from './ui.js';

export function createRecipesTab(ctx) {
  const { app, dom } = ctx;

  const meta = {
    kind: 'graph',
    sliders: true,
    placeholder: 'поиск: название, вход, станция',
    allLabel: 'Вся лестница',
    focusTitle: '',
    buttons: ['act-new', 'act-new-material', 'act-new-class'],
  };

  function renderFilters() {
    const present = [...new Set(app.state.nodes.map(typeOf))];
    const order = Object.keys(TYPE_LABEL);
    present.sort((a, b) => order.indexOf(a) - order.indexOf(b));
    dom.filters.replaceChildren(
      ...present.map((type) => h('button', {
        class: 'chip' + (app.hidden.has(type) ? '' : ' on'),
        style: `color:${KIND_COLOUR[type] || 'inherit'}`,
        text: TYPE_LABEL[type] || type,
        onclick: () => {
          if (app.hidden.has(type)) app.hidden.delete(type); else app.hidden.add(type);
          renderFilters();
          renderList();
          if (app.mode === 'all') draw();
        },
      })),
      h('button', {
        class: 'chip' + (app.keyOnly ? ' on' : ''),
        text: '★ вехи',
        title: 'только ступени лестницы',
        onclick: () => { app.keyOnly = !app.keyOnly; renderFilters(); renderList(); },
      }),
    );
  }

  function matches(node) {
    // Блюда живут во вкладке «Еда», и только там.
    if (isDish(node)) return false;
    if (app.hidden.has(typeOf(node))) return false;
    if (app.keyOnly && !node.is_key) return false;
    const query = app.query.trim().toLowerCase();
    if (!query) return true;
    const haystack = [
      node.name,
      node.station || '',
      node.kind || node.type,
      ...(node.inputs || []),
      ...(node.operations || []),
    ].join(' ').toLowerCase();
    return haystack.includes(query);
  }

  function renderList() {
    const visible = app.state.nodes.filter(matches);
    const groups = new Map();
    for (const node of visible) {
      const key = node.type === 'recipe' ? `L${String(node.level).padStart(2, '0')}` : `Z${node.type}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(node);
    }
    const levels = new Map(app.state.vocabulary.levels.map((level) => [level.id, level.title]));
    const title = (key) => (key.startsWith('L')
      ? `${Number(key.slice(1))}. ${levels.get(Number(key.slice(1))) || ''}`
      : TYPE_LABEL[key.slice(1)] || key.slice(1));

    const out = [];
    for (const key of [...groups.keys()].sort()) {
      out.push(h('div', { class: 'group', text: title(key) }));
      for (const node of groups.get(key).sort((a, b) => a.name.localeCompare(b.name, 'ru'))) {
        out.push(listRow(node, node.name, { selected: app.selected, onSelect: ctx.select },
          node.is_key ? h('span', { class: 'kbd', text: '★' }) : null,
          h('span', { class: 'st', text: node.station || (node.type === 'raw' ? 'сырьё' : '') }),
        ));
      }
    }
    if (!out.length) out.push(nothingFound());
    dom.list.replaceChildren(...out);
  }

  function renderLegend() {
    const present = [...new Set(app.state.nodes.map(typeOf))];
    dom.legend.replaceChildren(
      ...present.map((type) => h('span', {},
        h('i', { style: `background:${KIND_COLOUR[type] || '#888'}` }),
        TYPE_LABEL[type] || type,
      )),
      h('span', {}, h('i', { style: 'background:var(--warn);border-radius:50%' }), 'веха'),
      h('span', {
        text: app.mode === 'focus'
          ? '· колонки считаны от выбранной вещи: слева — из чего, справа — во что'
          : '· колонка — ступень лестницы от голого сырья',
      }),
      h('span', {
        text: app.mode === 'focus'
          ? '· число на стрелке — сколько идёт на единицу'
          : '· количества показываются в фокусе',
      }),
      h('span', { text: '· двойной щелчок — сделать центром' }),
    );
  }

  function picture() {
    const all = app.state.nodes;
    const edges = app.state.edges.filter((edge) => edge.rel === 'input');
    let nodes;
    if (app.mode === 'all') {
      const shown = new Set(
        all.filter((node) => !isDish(node) && !app.hidden.has(typeOf(node))).map((n) => n.name),
      );
      nodes = all.filter((node) => shown.has(node.name));
      dom.hint.textContent = things(nodes.length);
    } else if (!app.selected) {
      nodes = [];
      dom.hint.textContent = 'выберите вещь';
    } else {
      const near = neighbourhood(app.selected, edges, app.back, app.forward);
      // Окрестность муки тянет за собой хлеб, но хлеб — это вкладка «Еда».
      nodes = all.filter((node) => near.has(node.name) && !isDish(node));
      dom.hint.textContent = `${things(nodes.length)} вокруг «${app.selected}»`;
    }
    const names = new Set(nodes.map((node) => node.name));
    return { nodes, edges: edges.filter((edge) => names.has(edge.from) && names.has(edge.to)) };
  }

  const draw = () => ctx.drawPicture(picture());

  // Новый рецепт рождается там же, где стоит выбранный: уровень, раздел и
  // станция берутся у него.
  function openNew() {
    const node = app.nodes.get(app.selected);
    ctx.panel.openNew(node && node.type === 'recipe'
      ? { level: node.level, section: node.section, station: node.station }
      : {});
  }

  // Класс заводят не в пустоте, а когда у вещи появился второй вариант: то,
  // что выбрано сейчас, становится первым, чем класс закрывается.
  function openNewClass() {
    const node = app.nodes.get(app.selected);
    ctx.panel.openNewClass(node && node.type !== 'class' ? { members: [node.name] } : {});
  }

  return {
    meta, renderFilters, renderList, renderLegend, draw, openNew, openNewClass,
    focusable: () => true,
  };
}
