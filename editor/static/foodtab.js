// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The «Еда» tab (D-119): the kitchen apart from the ladder. Dishes, what goes
// into them, and the stations they are cooked on -- drawn together, because
// the kitchen is small and «из чего и на чём» is one question here.

import { KIND_COLOUR } from './graphview.js';
import { FOOD_PART, foodWorld, isDish, isEdible, listRow, nothingFound } from './ladderkit.js';
import { neighbourhood } from './layout.js';
import { h, plural, things } from './ui.js';

export function createFoodTab(ctx) {
  const { app, dom } = ctx;

  const meta = {
    kind: 'graph',
    sliders: true,
    placeholder: 'поиск: блюдо, продукт или станция',
    allLabel: 'Вся кухня',
    focusTitle: 'из чего блюдо и на чём его готовят',
    // Новая еда заводится блюдом или материалом со съедобностью; рецепт вообще
    // и класс — дело лестницы, на кухне им нечего делать.
    buttons: ['act-new-dish', 'act-new-material'],
  };

  const world = () => foodWorld(app.state, ctx.nodeOf);

  function inKitchen(name) {
    const node = ctx.nodeOf(name);
    if (!node) return false;
    if (isDish(node) || isEdible(node)) return true;
    return world().stations.some((item) => item.name === name);
  }

  // Вкладка еды делится на три части, и прятать их — её собственный выбор:
  // фишки типов вкладки рецептов тут ни при чём.
  function renderFilters() {
    const kitchen = world();
    const hot = kitchen.dishes.filter((node) => node.hot).length;
    dom.filters.replaceChildren(
      ...Object.entries(FOOD_PART).map(([part, label]) => h('button', {
        class: 'chip' + (app.foodHidden.has(part) ? '' : ' on'),
        text: `${label} ${kitchen[part].length}`,
        onclick: () => {
          if (app.foodHidden.has(part)) app.foodHidden.delete(part); else app.foodHidden.add(part);
          renderFilters();
          renderList();
          draw();
        },
      })),
      h('span', { class: 'note-line', text: `горячих блюд ${hot}` }),
    );
  }

  // Кухня в три группы: сперва блюда — ради них вкладка, — потом из чего они,
  // потом где. Поиск ищет по названию, по входам и по станции, как и в рецептах.
  function renderList() {
    const query = app.query.trim().toLowerCase();
    const kitchen = world();
    const fits = (node) => !query || [
      node.name,
      node.station || '',
      ...(node.inputs || []),
      ...(ctx.station(node.name)?.makes || []),
    ].join(' ').toLowerCase().includes(query);
    const edibleMakes = (name) => (ctx.station(name)?.makes || []).filter((made) => {
      const other = ctx.nodeOf(made);
      return other && (isDish(other) || isEdible(other));
    }).length;

    const out = [];
    for (const [part, label] of Object.entries(FOOD_PART)) {
      if (app.foodHidden.has(part)) continue;
      const rows = kitchen[part].filter(fits).sort((a, b) => a.name.localeCompare(b.name, 'ru'));
      if (!rows.length) continue;
      out.push(h('div', { class: 'group', text: label }));
      for (const node of rows) {
        out.push(listRow(node, node.name, { selected: app.selected, onSelect: ctx.select },
          node.hot ? h('span', { class: 'kbd', title: 'горячее блюдо', text: '♨' }) : null,
          node.roles
            ? h('span', { class: 'kbd', title: 'входы — роли, а не состав (D-119)', text: 'роли' })
            : null,
          h('span', {
            class: 'st',
            title: part === 'stations' ? 'сколько съедобного делают на станции' : '',
            text: part === 'stations'
              ? String(edibleMakes(node.name))
              : node.station || (node.type === 'raw' ? 'сырьё' : ''),
          }),
        ));
      }
    }
    if (!out.length) out.push(nothingFound());
    dom.list.replaceChildren(...out);
  }

  function renderLegend() {
    dom.legend.replaceChildren(
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.consumable}` }), 'блюдо'),
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.material}` }), 'съедобный продукт'),
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.raw}` }), 'съедобное сырьё'),
      h('span', {}, h('i', { style: `background:${KIND_COLOUR.station}` }), 'станция'),
      h('span', { text: '· сплошная стрелка — что кладут' }),
      h('span', { text: '· пунктир — на чём готовят' }),
      h('span', { text: '· ♨ — горячее: сытость отдаёт временем (D-119)' }),
      h('span', { text: '· роли — вход закрывается любым подходящим продуктом' }),
      h('span', { text: '· двойной щелчок — сделать центром' }),
    );
  }

  function picture() {
    const kitchen = world();
    const shown = Object.keys(FOOD_PART)
      .filter((part) => !app.foodHidden.has(part))
      .flatMap((part) => kitchen[part]);
    const names = new Set(shown.map((node) => node.name));
    const edges = app.state.edges.filter((edge) => (edge.rel === 'input' || edge.rel === 'station')
      && names.has(edge.from) && names.has(edge.to));

    let nodes;
    if (app.mode === 'all') {
      nodes = shown;
      const { dishes, edibles, stations } = kitchen;
      dom.hint.textContent = `${dishes.length} ${plural(dishes.length, 'блюдо', 'блюда', 'блюд')}`
        + ` · ${edibles.length} ${plural(edibles.length, 'съедобное', 'съедобных', 'съедобных')}`
        + ` · ${stations.length} ${plural(stations.length, 'станция', 'станции', 'станций')}`;
    } else if (!app.selected || !names.has(app.selected)) {
      nodes = [];
      dom.hint.textContent = 'выберите блюдо, продукт или станцию';
    } else {
      const near = neighbourhood(app.selected, edges, app.back, app.forward);
      nodes = shown.filter((node) => near.has(node.name));
      dom.hint.textContent = `${things(nodes.length)} вокруг «${app.selected}»`;
    }
    const kept = new Set(nodes.map((node) => node.name));
    return { nodes, edges: edges.filter((edge) => kept.has(edge.from) && kept.has(edge.to)) };
  }

  const draw = () => ctx.drawPicture(picture());

  // Блюдо рождается там же, где живут остальные: уровень, раздел и станция
  // берутся у выбранного блюда, а без выбора — у любого из файла. Очаг в коде
  // не назван: что считается очагом, решает вольт.
  function openNewDish() {
    const chosen = app.nodes.get(app.selected);
    const sample = (chosen && isDish(chosen)) ? chosen : app.state.nodes.find(isDish);
    ctx.panel.openNew({
      kind: 'consumable',
      flags: { food: true, roles: true },
      level: sample?.level,
      section: sample?.section,
      station: sample?.station,
    });
  }

  return { meta, renderFilters, renderList, renderLegend, draw, openNewDish, focusable: inKitchen };
}
