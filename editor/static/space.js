// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// Как рисуется мир в небе: тело, круг стоянки, окно захвата — и что из его
// чисел выходит (D-320, D-324).
//
// Две картинки, и у каждой своя работа. **Линейка** ставит тела в один
// масштаб: только там видно, что Пироксис в одиннадцать раз шире Терры, а
// Акватика при нём — точка; это не дефект рисунка, а ответ. **Карточка**
// рисует один мир в его собственном масштабе — тело, круг стоянки, окно
// захвата: в общем масштабе кольца трёх миров из четырёх сошлись бы в
// пиксель. Отношение круга к телу у всех одно по построению
// (`orbit.park_radii`), и на карточке его видно.
//
// Чистое рисование: ни одного запроса, ни одной правки. Числа приходят
// готовыми с сервера (`api_space`), а он выводит их формулами движка.

const NS = 'http://www.w3.org/2000/svg';

//: Цвет мира — тот же, что у игры: планета узнаётся по нему раньше, чем по
//: подписи. Ключи вольта, не имена.
export const TINT = {
  terra: '#5b8dd9',
  pyroxis: '#d97a4a',
  aurora: '#8fd7e8',
  aquatica: '#4ab5a8',
};

export const NAMES = {
  terra: 'Терра',
  pyroxis: 'Пироксис',
  aurora: 'Аврора',
  aquatica: 'Акватика',
};

function svg(name, attrs = {}) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, String(value));
  }
  return node;
}

/** Число так, как его читают: значащие цифры, а не хвост из нулей. */
export function spell(value, digits = 2) {
  if (!Number.isFinite(value)) return '—';
  if (value === 0) return '0';
  const size = Math.abs(value);
  if (size >= 1e6) return `${(value / 1e6).toFixed(1)} млн`;
  if (size >= 1000) return Math.round(value).toLocaleString('ru');
  if (size >= 10) return value.toFixed(Math.min(digits, 1));
  if (size >= 0.01) return value.toFixed(digits);
  return value.toExponential(1);
}

/** Часы так, как о них говорят: минуты до часа, часы до суток, дальше сутки. */
export function spellHours(hours) {
  if (!Number.isFinite(hours) || hours <= 0) return '—';
  if (hours < 1) return `${Math.round(hours * 60)} мин`;
  if (hours < 48) return `${hours.toFixed(1)} ч`;
  return `${(hours / 24).toFixed(1)} сут`;
}

/**
 * Одна карточка мира: тело, круг стоянки, окно захвата — в масштабе этого
 * мира, и подпись под каждым кольцом.
 *
 * Окно захвата задаёт масштаб: оно самое широкое из трёх, и если бы масштаб
 * задавало тело, круг с окном уходили бы за край.
 */
export function worldCard(world, { selected = false, onSelect } = {}) {
  const side = 190;
  const mid = side / 2;
  const outer = world.capture_units || world.park_units || world.drawn_units || 1;
  //: Девять десятых половины стороны: окну нужен воздух, иначе оно ложится на
  //: рамку и читается обрезанным.
  const unit = (mid * 0.9) / outer;
  const tint = TINT[world.key] || '#8a93a6';
  const picture = svg('svg', {
    viewBox: `0 0 ${side} ${side}`,
    class: 'space-picture',
    role: 'img',
    'aria-label': `${NAMES[world.key] || world.key}: тело, круг стоянки, окно захвата`,
  });
  picture.append(
    svg('circle', {
      cx: mid, cy: mid, r: world.capture_units * unit,
      fill: 'none', stroke: tint, 'stroke-opacity': 0.35, 'stroke-dasharray': '3 4',
    }),
    svg('circle', {
      cx: mid, cy: mid, r: world.park_units * unit,
      fill: 'none', stroke: tint, 'stroke-opacity': 0.8,
    }),
    svg('circle', {
      cx: mid, cy: mid, r: Math.max(1.5, world.drawn_units * unit), fill: tint,
    }),
  );
  const rows = [
    ['масса', `${spell(world.mass)} ⊕`],
    ['радиус тела', `${spell(world.radius)} ⊕ · ${spell(world.body_km)} км`],
    ['тяжесть', `${spell(world.gravity)} g`],
    ['плотность', `${spell(world.density)} г/см³`],
    ['земля под ногами', `${spell(world.land_radius_km)} км · ${spell(world.land_area_km2)} км²`],
    ['экватор', `${spell(world.equator_km)} км`],
    ['круг стоянки', `${spell(world.park_units, 3)} ед. · оборот ${spellHours(world.lap_hours)}`],
    ['скорость круга', `${spell(world.circle_speed)} ед./сут`],
    ['уход с круга', `${spell(world.escape_dv)} Δv`],
    ['подъём · спуск', `${spellHours(world.climb_hours)} · ${spellHours(world.fall_hours)}`],
    ['орбита', `${spell(world.orbit_units)} ед. · год ${spell(world.period_days, 0)} сут`],
    ['нарисовано крупнее', `в ${spell(world.drawn_times, 0)} раз`],
  ];
  const card = document.createElement('div');
  card.className = `space-card${selected ? ' on' : ''}`;
  card.style.setProperty('--tint', tint);
  const title = document.createElement('h4');
  title.textContent = NAMES[world.key] || world.key;
  const table = document.createElement('dl');
  for (const [term, value] of rows) {
    const dt = document.createElement('dt');
    dt.textContent = term;
    const dd = document.createElement('dd');
    dd.textContent = value;
    table.append(dt, dd);
  }
  card.append(title, picture, table);
  if (onSelect) card.addEventListener('click', () => onSelect(world.key));
  return card;
}

/**
 * Все тела в **одном** масштабе, в ряд: это единственная картинка, где миры
 * сравниваются между собой.
 *
 * Карточки ниже показывают у каждого мира одно и то же отношение круга к телу
 * — оно у всех одно по построению (`orbit.park_radii`), — а чем миры друг от
 * друга отличаются, видно только здесь. Масштаб задаёт самое большое тело, и
 * если оно на два порядка шире прочих, то прочие и будут точками: это не
 * дефект рисунка, это ответ.
 */
export function sizeStrip(worlds) {
  const height = 120;
  const widest = Math.max(...worlds.map((one) => one.radius), 1e-9);
  //: Ряд считается заранее: каждому миру — колонка шириной с его тело или с
  //: его подпись, смотря что шире. По диаметру одному ряд бы сошёлся, а
  //: подписи наехали бы друг на друга: Аврора рядом с Пироксисом — точка, а
  //: слово под ней всё той же длины.
  const gap = 14;
  const label = 76;
  const unit = (height * 0.42) / widest;
  const spans = worlds.map((one) => Math.max(1.5, one.radius * unit));
  const columns = spans.map((r) => Math.max(2 * r, label) + gap);
  const width = columns.reduce((sum, one) => sum + one, gap);
  const picture = svg('svg', {
    viewBox: `0 0 ${width} ${height}`,
    class: 'space-strip',
    role: 'img',
    'aria-label': 'тела миров в одном масштабе',
  });
  let x = gap;
  worlds.forEach((one, index) => {
    const r = spans[index];
    const middle = x + (columns[index] - gap) / 2;
    const tint = TINT[one.key] || '#8a93a6';
    picture.append(
      svg('circle', { cx: middle, cy: height / 2 - 8, r, fill: tint }),
      Object.assign(svg('text', {
        x: middle, y: height - 14, 'text-anchor': 'middle', fill: tint, 'font-size': 11,
      }), { textContent: NAMES[one.key] || one.key }),
      Object.assign(svg('text', {
        x: middle, y: height - 2, 'text-anchor': 'middle', fill: '#8a93a6', 'font-size': 10,
      }), { textContent: `${spell(one.radius)} ⊕` }),
    );
    x += columns[index];
  });
  return picture;
}

/**
 * Система сверху: звезда, четыре круга и планеты на своих фазах.
 *
 * Орбиты в масштабе друг друга — они одного порядка и рядом помещаются, в
 * отличие от самих тел. Планета рисуется меткой, а не телом: в масштабе
 * системы даже Пироксис меньше пикселя, и метка тут честнее.
 */
export function systemMap(worlds) {
  const circled = worlds.filter((one) => one.orbit_units > 0);
  if (!circled.length) return null;
  const side = 340;
  const mid = side / 2;
  const widest = Math.max(...circled.map((one) => one.orbit_units));
  const unit = (mid * 0.88) / widest;
  const picture = svg('svg', {
    viewBox: `0 0 ${side} ${side}`,
    class: 'space-system',
    role: 'img',
    'aria-label': 'система сверху: орбиты и планеты на своих фазах',
  });
  //: Звезда: не в масштабе и не притворяется им — точка, вокруг которой всё.
  picture.append(svg('circle', { cx: mid, cy: mid, r: 5, fill: '#e8c45a' }));
  for (const one of circled) {
    const tint = TINT[one.key] || '#8a93a6';
    const radius = one.orbit_units * unit;
    picture.append(svg('circle', {
      cx: mid, cy: mid, r: radius,
      fill: 'none', stroke: tint, 'stroke-opacity': 0.3,
    }));
    //: Фаза — радианы от оси, как их читает движок (`astro.place`).
    const x = mid + radius * Math.cos(one.phase);
    const y = mid - radius * Math.sin(one.phase);
    picture.append(
      svg('circle', { cx: x, cy: y, r: 5, fill: tint }),
      Object.assign(svg('text', {
        x, y: y - 9, 'text-anchor': 'middle', fill: tint, 'font-size': 10,
      }), { textContent: NAMES[one.key] || one.key }),
      Object.assign(svg('text', {
        x, y: y + 17, 'text-anchor': 'middle', fill: '#8a93a6', 'font-size': 9,
      }), { textContent: `${spell(one.orbit_units)} ед. · ${spell(one.period_days, 0)} сут` }),
    );
  }
  return picture;
}

/** Все миры вольта разом, каждый своей карточкой. */
export function renderWorlds(root, worlds, { selected, onSelect } = {}) {
  const box = document.createElement('div');
  box.className = 'space-worlds';
  box.append(...worlds.map((world) => worldCard(world, {
    selected: world.key === selected,
    onSelect,
  })));
  root.replaceChildren(box);
  return box;
}
