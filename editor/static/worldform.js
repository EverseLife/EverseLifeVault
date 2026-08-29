// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The right-hand form of the «Мир» tab: one node, one road, one pocket (D-243).
//
// Its own file rather than a wing of `panel.js`: what is edited here is not a
// recipe. A node has no composition, no labour and no mass -- it has a place, a
// area, properties of ground, machines standing in it, veins under it and
// things lying on it. Sharing a form with the ladder would have meant a form
// that fits neither.
//
// The rule the whole tab holds to: **the form writes the file and the vault's
// own check says whether it was right.** Nothing here declares an edit good.

import { h, num } from './ui.js';
import { BY_REACH, LAYERS, SURFACES, SURFACE_LABEL, spellSeconds } from './world.js';

const LAYER_LABEL = {
  planet: 'планета — город или отдельное место на её поверхности',
  city: 'застройка — узел внутри города',
  location: 'помещение — этаж, комната, отсек',
};

/**
 * The form for one node.
 *
 * `world` is the whole layout, because a node is never edited alone: its
 * parent and anchor are picked from what exists, and the roads leading to it
 * are edited here too -- a road belongs to both its ends and to neither.
 */
export function nodeForm(host, world, key, tools) {
  const node = world.nodes.find((one) => one.key === key);
  if (!node) return;
  const draft = structuredClone(node);
  const fields = {};

  const line = (label, control, hint) => h('label', { class: 'field' },
    h('span', { class: 'label', text: label }),
    control,
    hint ? h('span', { class: 'hint', text: hint }) : null);

  fields.name = h('input', { type: 'text', value: draft.name || '' });
  fields.area = h('input', { type: 'number', min: '1', step: '1', value: num(draft.area_m2) });
  fields.layer = h('select', {},
    ...LAYERS.map((one) => h('option', {
      value: one, selected: (draft.layer || 'city') === one, text: one,
    })));
  const keys = world.nodes.map((one) => one.key);
  const external = world.external || [];
  fields.parent = pick([...external, ...keys].filter((one) => one !== key), draft.parent, 'без группы');
  fields.anchor = pick(keys.filter((one) => one !== key), draft.anchor, 'без якоря');
  fields.city = h('input', { type: 'checkbox', checked: !!draft.city });

  const place = draft.place || null;
  fields.x = h('input', { type: 'number', step: '1', value: place ? num(place.x) : '' });
  fields.y = h('input', { type: 'number', step: '1', value: place ? num(place.y) : '' });

  const properties = propertyRows(draft.properties || {}, world.properties);
  const machines = machineRows(draft.machines || [], world.palette);
  const relics = relicRows(draft.relics || [], world.palette);
  const veins = veinRows(draft.veins || [], world.palette);
  const items = stockRows(draft.items || [], world.palette, { ensure: true });

  const collect = () => ({
    key,
    name: fields.name.value.trim(),
    layer: fields.layer.value,
    parent: fields.parent.value || null,
    anchor: fields.anchor.value || null,
    area_m2: Number(fields.area.value),
    place: fields.x.value === '' && fields.y.value === ''
      ? null : { x: Number(fields.x.value || 0), y: Number(fields.y.value || 0) },
    city: fields.city.checked,
    properties: properties.value(),
    machines: machines.value(),
    relics: relics.value().map((one) => one.class).filter(Boolean),
    veins: veins.value(),
    items: items.value(),
  });

  const roads = world.edges.filter((edge) => edge.a === key || edge.b === key);

  host.replaceChildren(h('div', { class: 'form world-form' },
    h('h3', {}, draft.name || key, h('span', { class: 'path', text: key })),

    //: Что догон подтягивает живому миру, а что достаётся только новому. Мир
    //: вечен и без вайпов (D-007): сид не переставляет уже стоящую землю и не
    //: перекладывает уже пройденную дорогу. Сказано прямо, иначе перетащенный
    //: узел выглядит переставленным и на альфе, а он там стоит где стоял.
    h('div', { class: 'note-line' },
      'догоном в уже живущий мир доедут только новые узлы, дороги, станки и '
      + 'помеченные «держать» запасы. Место, площадь, свойства, секунды и '
      + 'качество — раскладка нового мира: землю, которая уже стоит, сид не двигает'),

    line('название', fields.name),
    line('слой', fields.layer, LAYER_LABEL[fields.layer.value]),
    line('группа', fields.parent, 'чей это узел: планета, город, помещение'),
    line('площадь, м²', fields.area),
    line('якорь на карте', fields.anchor,
      'рядом с кем узел встаёт, если место не прибито (D-237)'),
    h('label', { class: 'field row' }, fields.city,
      h('span', { class: 'label', text: 'здесь основывается город' }),
      h('span', { class: 'hint', text: 'устав, казна и законы — дело движка (D-154)' })),
    h('div', { class: 'field' },
      h('span', { class: 'label', text: 'место на карте' }),
      h('div', { class: 'pair' }, fields.x, fields.y,
        h('button', {
          class: 'ghost', title: 'убрать прибитое место: узел снова сядет рядом с якорем',
          onclick: () => { fields.x.value = ''; fields.y.value = ''; },
          text: 'открепить',
        })),
      h('span', {
        class: 'hint',
        text: place ? 'прибито: узел стоит здесь и не двигается'
          : 'пусто — движок сажает узел сам, рядом с якорем',
      })),

    section('свойства места', properties.node,
      'земля узла и что она даёт. Список закрытый: движок читает эти и только эти'),
    section('станки', machines.node,
      'станции и мебель (D-106). Класс — «любая вещь класса» (D-215); собирается по рецепту (D-216)'),
    section('реликвии Предтеч', relics.node,
      'найдено, а не сделано (D-232): не снимается, не разбирается, второй такой не построить. '
      + 'Задаётся классом — ставится тот его член, что помечен реликвией'),
    section('жилы', veins.node, 'кладутся один раз, при создании узла: мир их вырабатывает сам (П2)'),
    section('что лежит', items.node,
      'вещи в контейнере узла. «держать» — докладывать догоном, если запас вышел'),

    h('div', { class: 'field' },
      h('span', { class: 'label', text: 'дороги' }),
      h('div', { class: 'roads' },
        ...roads.map((edge) => roadRow(edge, key, tools)),
        h('div', { class: 'hint', text: 'новая дорога — потянуть от узла к узлу на карте с Shift' })),
    ),

    h('div', { class: 'actions' },
      h('button', {
        class: 'primary', text: 'Сохранить',
        onclick: () => tools.saveNode(collect()),
      }),
      h('button', {
        class: 'danger', text: 'Удалить узел',
        onclick: () => tools.deleteNode(key),
      })),
  ));
}

function section(title, body, hint) {
  return h('div', { class: 'field block' },
    h('span', { class: 'label', text: title }),
    hint ? h('span', { class: 'hint', text: hint }) : null,
    body);
}

function pick(values, chosen, empty) {
  return h('select', {},
    h('option', { value: '', text: empty, selected: !chosen }),
    ...values.map((one) => h('option', { value: one, selected: one === chosen, text: one })));
}

/**
 * A list of rows one can add to and take from.
 *
 * Every group in this form is one of these -- properties, machines, veins,
 * stocks -- and they differ only in what one row is.
 *
 * The render callback is handed the live list beside its own item: a property
 * row has to know which names the other rows already took, and reaching for
 * the returned object to find that out is a use before it exists.
 */
function rows(items, render, blank, label) {
  const box = h('div', { class: 'rows' });
  const state = items.map((item) => structuredClone(item));
  const draw = () => {
    box.replaceChildren(
      ...state.map((item, index) => h('div', { class: 'rowline' },
        render(item, index, draw, state),
        h('button', {
          class: 'ghost x', title: 'убрать', text: '×',
          onclick: () => { state.splice(index, 1); draw(); },
        }))),
      h('button', {
        class: 'ghost add', text: label,
        onclick: () => { state.push(structuredClone(blank)); draw(); },
      }),
    );
  };
  draw();
  return { node: box, value: () => state };
}

/**
 * The ground's properties: **picked from a list, not typed** (D-243).
 *
 * A property is an ordinary key in a JSON map, and a typo in it breaks
 * nothing loudly -- it just means the engine will not find the property it
 * looks for. «плодородее» instead of «плодородия» is a field nothing grows on,
 * and the one who finds out is a player. So the name is a select over the
 * catalogue the vault's own check refuses by (`tools/world.WORLD_PROPERTIES`),
 * and the value is whatever shape that property takes -- a checkbox for a
 * flag, a number for a number, a select for a word out of a set.
 *
 * Every property carries its own line of explanation, because half of them do
 * not explain themselves: «даль» is not a distance in metres, and «выход» is
 * not a door out of a building.
 */
function propertyRows(properties, catalogue) {
  const known = catalogue || {};
  const start = Object.entries(properties).map(([name, value]) => ({ name, value }));

  const list = rows(start, (item, _index, redraw, all) => {
    const spec = known[item.name];
    const others = new Set(all.map((one) => one.name).filter((one) => one && one !== item.name));
    //: A property already on the node is not offered twice: a map has one
    //: value per key, and the second row would silently eat the first.
    const free = Object.keys(known).filter((one) => !others.has(one));
    return h('div', { class: 'prop' },
      h('select', {
        onchange: (event) => {
          item.name = event.target.value;
          item.value = blankFor(known[item.name]);
          redraw();
        },
      },
      h('option', { value: '', text: '— свойство —', selected: !item.name }),
      ...free.map((one) => h('option', { value: one, selected: one === item.name, text: one }))),
      valueField(item, spec, redraw),
      spec ? h('span', { class: 'hint', text: spec.hint }) : null);
  }, { name: '', value: '' }, '+ свойство');

  return {
    node: list.node,
    value: () => Object.fromEntries(list.value()
      .filter((item) => item.name)
      .map((item) => [item.name, item.value])),
  };
}

/** What a property holds before anybody has said anything about it. */
function blankFor(spec) {
  if (!spec) return '';
  if (spec.values === 'flag') return true;
  if (spec.values === 'number' || spec.values === 'percent') return 0;
  return Array.isArray(spec.values) ? spec.values[0] : '';
}

/** The value control, shaped by what the property actually takes. */
function valueField(item, spec, redraw) {
  if (!spec) return h('span', { class: 'hint', text: 'выберите свойство слева' });
  if (spec.values === 'flag') {
    return h('label', { class: 'tick' }, h('input', {
      type: 'checkbox', checked: item.value === true,
      onchange: (event) => { item.value = event.target.checked; redraw(); },
    }), item.value === true ? 'да' : 'нет');
  }
  if (spec.values === 'number' || spec.values === 'percent') {
    return h('input', {
      type: 'number',
      min: spec.values === 'percent' ? '0' : undefined,
      max: spec.values === 'percent' ? '100' : undefined,
      value: num(item.value),
      oninput: (event) => { item.value = Number(event.target.value); },
    });
  }
  if (Array.isArray(spec.values)) {
    return h('select', {
      onchange: (event) => { item.value = event.target.value; },
    }, ...spec.values.map((one) => h('option', {
      value: one, selected: one === item.value, text: one,
    })));
  }
  return h('input', {
    type: 'text', value: String(item.value ?? ''),
    oninput: (event) => { item.value = event.target.value; },
  });
}

function machineRows(machines, palette) {
  const list = rows(machines, (item, _index, redraw) => {
    const byClass = !!item.class || item.class === '';
    const names = byClass ? palette.classes : palette.machines;
    return h('div', { class: 'pair wide' },
      h('select', {
        //: Switching between a thing and a class redraws the row: the
        //: completion list behind the field is the other one now, and offering
        //: machines where a class is wanted is worse than no list at all.
        onchange: (event) => {
          const wanted = event.target.value === 'class';
          const was = item.name || item.class || '';
          if (wanted) { item.class = was; delete item.name; } else { item.name = was; delete item.class; }
          redraw();
        },
      },
      h('option', { value: 'name', selected: !byClass, text: 'вещь' }),
      h('option', { value: 'class', selected: byClass, text: 'класс' })),
      withList(h('input', {
        type: 'text', value: item.name || item.class || '', placeholder: byClass ? 'класс' : 'станция',
        oninput: (event) => {
          if (byClass) item.class = event.target.value; else item.name = event.target.value;
        },
      }), names),
      h('input', {
        type: 'number', min: '1', max: '100', value: num(item.quality), placeholder: 'качество',
        oninput: (event) => { item.quality = Number(event.target.value); },
      }));
  }, { name: '', quality: 60 }, '+ станок');
  return list;
}

/**
 * Relics are a list of **classes**, not of things (D-215, D-232).
 *
 * Behaviour binds to the class -- a Forerunner plant heats exactly like a
 * built one -- and which member of it the world actually finds is the vault's
 * business, not the layout's.
 */
function relicRows(relics, palette) {
  const list = rows(relics.map((one) => ({ class: one })), (item) => withList(h('input', {
    type: 'text', value: item.class || '', placeholder: 'класс реликвии',
    oninput: (event) => { item.class = event.target.value; },
  }), palette.relics), { class: '' }, '+ реликвия');
  return list;
}


function veinRows(veins, palette) {
  return rows(veins, (item) => h('div', { class: 'pair wide' },
    withList(h('input', {
      type: 'text', value: item.resource || '', placeholder: 'вид',
      oninput: (event) => { item.resource = event.target.value; },
    }), palette.raw),
    h('input', {
      type: 'number', min: '1', max: '100', value: num(item.richness), placeholder: 'богатство',
      oninput: (event) => { item.richness = Number(event.target.value); },
    }),
    h('input', {
      type: 'number', min: '1', step: '100', value: num(item.remaining), placeholder: 'запас',
      oninput: (event) => { item.remaining = Number(event.target.value); },
    })), { resource: '', richness: 50, remaining: 10000 }, '+ жила');
}

export function stockRows(items, palette, options = {}) {
  return rows(items, (item) => h('div', { class: 'stock' },
    withList(h('input', {
      type: 'text', value: item.name || '', placeholder: 'вещь',
      oninput: (event) => { item.name = event.target.value; },
    }), palette.things),
    h('input', {
      type: 'number', min: '0', step: 'any', value: num(item.amount ?? 1), placeholder: 'сколько',
      oninput: (event) => { item.amount = Number(event.target.value); },
    }),
    h('input', {
      type: 'number', min: '1', max: '100', value: num(item.quality), placeholder: 'качество',
      oninput: (event) => { item.quality = Number(event.target.value); },
    }),
    options.ensure ? h('label', { class: 'tick', title: 'докладывать догоном, если запас вышел' },
      h('input', {
        type: 'checkbox', checked: !!item.ensure,
        onchange: (event) => { item.ensure = event.target.checked; },
      }), 'держать') : null,
    //: The ground is not an optional field: matter never arrives in the world
    //: anonymously (pillar P1), and the journal says so in these words.
    h('input', {
      class: 'origin', type: 'text', value: item.origin || '', placeholder: 'основание: откуда вещь',
      oninput: (event) => { item.origin = event.target.value; },
    })), { name: '', amount: 1, quality: 55, origin: '' }, '+ вещь');
}

function withList(input, values) {
  if (!values || !values.length) return input;
  const id = `list-${Math.random().toString(36).slice(2, 9)}`;
  input.setAttribute('list', id);
  const list = h('datalist', { id }, ...values.map((one) => h('option', { value: one })));
  return h('span', { class: 'withlist' }, input, list);
}

function roadRow(edge, key, tools) {
  const other = edge.a === key ? edge.b : edge.a;
  const seconds = h('input', {
    type: 'text', value: edge.seconds == null ? '' : String(edge.seconds),
    placeholder: 'шаг города',
    title: 'число секунд, «reach» — по дали узла (D-180), пусто — шаг города',
  });
  const surface = h('select', {}, ...SURFACES.map((one) => h('option', {
    value: one, selected: (edge.surface || 'road') === one, text: SURFACE_LABEL[one],
  })));
  return h('div', { class: 'rowline road' },
    h('span', { class: 'to', text: `→ ${other}` }),
    seconds, surface,
    h('span', { class: 'hint', text: spellSeconds(edge.seconds) }),
    h('button', {
      class: 'ghost', text: '✓', title: 'сохранить дорогу',
      onclick: () => tools.saveEdge({
        a: edge.a,
        b: edge.b,
        seconds: seconds.value.trim() === '' ? null
          : seconds.value.trim() === BY_REACH ? BY_REACH : Number(seconds.value),
        surface: surface.value,
      }),
    }),
    h('button', {
      class: 'ghost x', text: '×', title: 'убрать дорогу',
      onclick: () => tools.deleteEdge(edge.a, edge.b),
    }));
}

/** The form for a new node: the same fields, empty, and a key to be typed. */
export function newNodeForm(host, world, tools, seed = {}) {
  const fields = {
    key: h('input', { type: 'text', placeholder: 'terra.capital.market', value: seed.key || '' }),
    name: h('input', { type: 'text', placeholder: 'Рынок' }),
    layer: h('select', {}, ...LAYERS.map((one) => h('option', {
      value: one, selected: (seed.layer || 'city') === one, text: one,
    }))),
    area: h('input', { type: 'number', min: '1', value: '200' }),
  };
  const keys = world.nodes.map((one) => one.key);
  fields.parent = pick([...(world.external || []), ...keys], seed.parent, 'без группы');
  fields.anchor = pick(keys, seed.anchor, 'без якоря');

  host.replaceChildren(h('div', { class: 'form world-form' },
    h('h3', { text: 'Новый узел' }),
    h('div', { class: 'hint', text: 'ключ — латиницей через точку, и он не меняется: '
      + 'по нему мир узнаёт узел вечно (D-007)' }),
    h('label', { class: 'field' }, h('span', { class: 'label', text: 'ключ' }), fields.key),
    h('label', { class: 'field' }, h('span', { class: 'label', text: 'название' }), fields.name),
    h('label', { class: 'field' }, h('span', { class: 'label', text: 'слой' }), fields.layer),
    h('label', { class: 'field' }, h('span', { class: 'label', text: 'группа' }), fields.parent),
    h('label', { class: 'field' }, h('span', { class: 'label', text: 'якорь' }), fields.anchor),
    h('label', { class: 'field' }, h('span', { class: 'label', text: 'площадь, м²' }), fields.area),
    h('div', { class: 'actions' }, h('button', {
      class: 'primary', text: 'Завести',
      onclick: () => tools.saveNode({
        key: fields.key.value.trim(),
        name: fields.name.value.trim(),
        layer: fields.layer.value,
        parent: fields.parent.value || null,
        anchor: fields.anchor.value || null,
        area_m2: Number(fields.area.value),
      }, { after: fields.anchor.value || null, fresh: true }),
    })),
  ));
}

/** The form for one starting pocket: what an identity carries from day one. */
export function pocketForm(host, world, owner, tools) {
  const items = stockRows(world.pockets[owner] || [], world.palette);
  host.replaceChildren(h('div', { class: 'form world-form' },
    h('h3', {}, `Карман: ${owner}`),
    h('div', { class: 'hint', text: 'снаряжение стартовой личности. Сама личность — почта, '
      + 'пароль, роль основателя — остаётся у движка (D-187)' }),
    section('что несёт', items.node, null),
    h('div', { class: 'actions' },
      h('button', {
        class: 'primary', text: 'Сохранить',
        onclick: () => tools.savePocket(owner, items.value()),
      }),
      h('button', {
        class: 'danger', text: 'Убрать карман',
        onclick: () => tools.savePocket(owner, []),
      })),
  ));
}
