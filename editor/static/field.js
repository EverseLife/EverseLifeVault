// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// Как рисуется вкладка «Планеты»: карточки миров, пульт сборки и снимки.
//
// Ни одно число здесь не выводится: сервер отдаёт готовые
// (`api_field._worlds`), и считает он их не своей формулой, а той самой,
// которой строит поле — `tools/field/healpix`. Второй арифметики «сколько
// клеток у этой планеты» в проекте нет и заводить её незачем: она разошлась
// бы со сборщиком на первой же правке.

import { h, plural } from './ui.js';

const FRAME_WORDS = { planet: 'планета целиком', region: 'область', city: 'город' };
const LAYER_WORDS = {
  relief: 'рельеф', forms: 'формы', biomes: 'биомы', rock: 'порода', provinces: 'провинции',
};
const PLANET_WORDS = {
  terra: 'Терра', aquatica: 'Акватика', pyroxis: 'Пироксис', aurora: 'Аврора',
};

export function planetWord(id) {
  return PLANET_WORDS[id] || id;
}

export function spellSeconds(seconds) {
  const whole = Math.max(0, Math.round(Number(seconds) || 0));
  if (whole < 90) return `${whole} с`;
  const minutes = Math.round(whole / 60);
  if (minutes < 90) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  return `${hours} ч ${minutes - hours * 60} мин`;
}

function spellCells(count) {
  if (count >= 1e6) return `${(count / 1e6).toFixed(2)} млн`;
  if (count >= 1e3) return `${Math.round(count / 1e3)} тыс.`;
  return String(count);
}

function ago(stamp) {
  if (!stamp) return '';
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - stamp));
  if (seconds < 90) return 'только что';
  if (seconds < 3600) return `${Math.round(seconds / 60)} мин назад`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} ч назад`;
  return `${Math.round(seconds / 86400)} сут назад`;
}

//: Собрано ли поле под нынешние числа. Сверяется не хеш паспорта — его считает
//: сборка вольта, — а те немногие величины, что видно отсюда: дробность и
//: размах. Совпали они — поле хотя бы той же формы; разошлись — оно наверняка
//: не то, и это надо сказать до того, как человек станет смотреть картинки.
export function freshness(world) {
  const built = world.built || {};
  if (!built.present) return { state: 'none', word: 'не собрано' };
  if (built.nside !== world.nside) {
    return { state: 'stale', word: `собрано при nside ${built.nside}, теперь ${world.nside}` };
  }
  return { state: 'ok', word: `собрано ${ago(built.written)}` };
}

//: Показывают ли снимки то поле, которое лежит рядом. Своя проверка, потому
//: что снимки живут отдельной жизнью: поле пересобирают, а нарисовать
//: забывают, и галерея молча показывает прежний мир под свежей карточкой —
//: хуже, чем пустое место, потому что похоже на ответ.
export function picturesFresh(world) {
  const built = world.built || {};
  const shots = world.pictures || [];
  if (!shots.length || !built.present) return null;
  const drawn = Math.max(...shots.map((one) => one.written || 0));
  return drawn >= (built.written || 0)
    ? { state: 'ok', word: `нарисовано ${ago(drawn)}` }
    : { state: 'stale', word: `сняты до этого поля, ${ago(drawn)} — нажмите «нарисовать»` };
}

export function planetCards(host, worlds, { picked, onPick }) {
  const box = h('div', { class: 'field-cards' });
  for (const world of worlds) {
    const built = world.built || {};
    const fresh = freshness(world);
    const card = h('button', {
      class: `field-card ${picked === world.planet ? 'on' : ''} fresh-${fresh.state}`,
      type: 'button',
      onclick: () => onPick(world.planet),
    });
    card.append(
      h('div', { class: 'field-card-head' },
        h('b', { text: planetWord(world.planet) }),
        h('span', { class: `field-fresh fresh-${fresh.state}`, text: fresh.word })),
      h('div', { class: 'field-card-grid' },
        cell('радиус', `${world.radius_km} км`),
        cell('экватор', `${world.equator_km} км`),
        cell('площадь', `${world.area_km2.toLocaleString('ru')} км²`),
        cell('nside', String(world.nside)),
        cell('клеток', spellCells(world.cells)),
        cell('сторона', `${world.side_m} м`, `промах от заданного шага ${(world.miss * 100).toFixed(2)} %`),
        cell('в памяти', `${world.megabytes} МБ`, 'сколько поле займёт у сервера; файл втрое легче — он сжат'),
        cell('сборка', `~${spellSeconds(world.about_seconds)}`),
        cell('горизонт', `${world.horizon_m} м`, 'с глаза в два метра над уровнем моря')),
    );
    const shots = picturesFresh(world);
    if (shots && shots.state === 'stale') {
      card.append(h('div', { class: 'field-fresh fresh-stale', text: 'снимки старше поля' }));
    }
    if (built.present) {
      card.append(h('div', {
        class: 'field-card-built',
        text: `суши ${Math.round((built.land_share || 0) * 100)} %`
          + ` · выше всего ${Math.round(built.height_max_m || 0)} м`
          + ` · зерно ${built.seed} · версия ${built.version} · файл ${built.megabytes} МБ`,
      }));
    }
    box.append(card);
  }
  host.append(box);
  return box;
}

function cell(name, value, title) {
  return h('div', { class: 'field-cell', title: title || null },
    h('span', { class: 'field-cell-name', text: name }),
    h('b', { text: value }));
}

//: Пульт: что запускать, над чем и с какими числами поверх реестра. Зерно и
//: шаг здесь именно **поверх**: их пробуют, а не записывают (план §4.1, §4.4),
//: и записываются они формой константы слева, как всё остальное.
export function runPanel(host, state, view, tools) {
  const job = state.job;
  const running = Boolean(job && job.running);
  const box = h('div', { class: 'field-run' });

  const kinds = [
    ['build', 'собрать поле', 'полный конвейер: плиты, сток, эрозия, климат, формы'],
    ['render', 'нарисовать', 'пятнадцать снимков на планету из уже собранного поля'],
    ['census', 'перепись', 'что вышло: формы, прогулка, соседство, провинции'],
    ['all', 'всё разом', 'собрать, переписать и нарисовать'],
    ['scan', 'перебрать зёрна', 'по строке на зерно: чем выбирают зерно мира'],
  ];
  const kindBox = h('div', { class: 'seg field-kinds' });
  for (const [id, word, why] of kinds) {
    kindBox.append(h('button', {
      type: 'button',
      class: view.kind === id ? 'on' : '',
      title: why,
      disabled: running || null,
      onclick: () => tools.setKind(id),
    }, word));
  }

  const whoBox = h('div', { class: 'field-who' });
  for (const world of state.worlds) {
    const on = view.planets.has(world.planet);
    whoBox.append(h('label', { class: `field-who-one ${on ? 'on' : ''}` },
      h('input', {
        type: 'checkbox',
        checked: on || null,
        disabled: running || null,
        onchange: () => tools.togglePlanet(world.planet),
      }),
      planetWord(world.planet)));
  }

  const overrides = h('div', { class: 'field-overrides' },
    field('зерно', 'seed', view.seed, 'terrain.seed на один прогон; пусто — как в реестре'),
    field('шаг, м', 'step', view.step, 'terrain.step_m на один прогон'),
    field('море, доля', 'sea', view.sea, 'terrain.sea_share на один прогон'),
    view.kind === 'scan' ? field('зёрен', 'seeds', view.seeds, 'сколько зёрен подряд перебрать') : null,
  );
  function field(word, name, value, why) {
    return h('label', { class: 'field-override', title: why },
      word,
      h('input', {
        type: 'text', value: value ?? '', disabled: running || null,
        oninput: (event) => tools.setOverride(name, event.target.value),
      }));
  }

  const chosen = state.worlds.filter((one) => view.planets.has(one.planet));
  const cells = chosen.reduce((sum, one) => sum + one.cells, 0);
  const seconds = chosen.reduce((sum, one) => sum + one.about_seconds, 0);
  const actions = h('div', { class: 'field-actions' },
    h('button', {
      class: 'primary', type: 'button', disabled: running || !chosen.length || null,
      onclick: () => tools.start(),
    }, running ? 'идёт…' : 'Запустить'),
    running ? h('button', { class: 'danger', type: 'button', onclick: () => tools.stop() }, 'Остановить') : null,
    h('span', {
      class: 'note-line',
      text: chosen.length
        ? `${chosen.length} ${plural(chosen.length, 'планета', 'планеты', 'планет')}`
          + ` · ${spellCells(cells)} ${plural(cells, 'клетка', 'клетки', 'клеток')}`
          + (view.kind === 'build' || view.kind === 'all' ? ` · около ${spellSeconds(seconds)}` : '')
        : 'выберите хотя бы одну планету',
    }),
  );

  box.append(
    h('h4', { text: 'сборка' }),
    kindBox, whoBox, overrides,
    //: Конвейер читает собранный реестр, а карточки — исходный файл. Между
    //: ними лежит всё записанное и ещё не собранное, и запуск построил бы
    //: прежний мир, показывая новый. Вольт соберётся первым шагом, и об этом
    //: сказано здесь, до кнопки, а не в журнале после неё.
    state.stale ? h('p', {
      class: 'field-said warn',
      text: 'реестр новее сборки вольта — соберу вольт первым шагом, иначе поле вышло бы по прежним числам',
    }) : null,
    actions,
    progress(job),
  );
  host.append(box);
  return box;
}

function progress(job) {
  const box = h('div', { class: 'field-progress' });
  if (!job) {
    box.append(h('p', { class: 'note-line', text: 'ничего ещё не запускали в этом сеансе' }));
    return box;
  }
  const done = new Set(job.done);
  const bar = h('div', { class: 'field-bar' });
  for (const planet of job.planets) {
    const state = done.has(planet) ? 'done'
      : job.at === planet ? 'now'
      : job.failed && job.at === planet ? 'bad' : 'wait';
    bar.append(h('span', { class: `field-bar-one ${state}`, text: planetWord(planet) }));
  }
  box.append(bar);
  box.append(h('p', {
    class: job.failed ? 'field-said bad' : 'field-said',
    text: job.failed
      ? job.failed
      : job.running
        ? `${planetWord(job.at) || '…'}: ${job.stage || 'запуск'} · ${spellSeconds(job.seconds)}`
        : `${job.stage} · ${spellSeconds(job.seconds)}`,
  }));
  const log = h('pre', { class: 'field-log' });
  log.textContent = job.lines.join('\n');
  box.append(log);
  //: Хвост, а не голова: смотрят на то, что происходит сейчас.
  requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
  return box;
}

//: Снимки: пятнадцать на планету — три кадра на каждый из пяти слоёв.
//: Показывается один, а не все сразу: пятнадцать картинок по девятьсот
//: пикселей — это экран, по которому нечего искать.
export function gallery(host, world, view, tools) {
  const box = h('div', { class: 'field-gallery' });
  const shots = world.pictures || [];
  if (!shots.length) {
    box.append(h('p', {
      class: 'note-line',
      text: `снимков ${planetWord(world.planet)} нет: нажмите «нарисовать» — конвейер положит их в build/preview`,
    }));
    host.append(box);
    return box;
  }
  const frames = h('div', { class: 'seg' });
  for (const frame of ['planet', 'region', 'city']) {
    if (!shots.some((one) => one.frame === frame)) continue;
    frames.append(h('button', {
      type: 'button', class: view.frame === frame ? 'on' : '',
      onclick: () => tools.setFrame(frame),
    }, FRAME_WORDS[frame]));
  }
  const layers = h('div', { class: 'seg' });
  for (const layer of ['relief', 'forms', 'biomes', 'rock', 'provinces']) {
    if (!shots.some((one) => one.layer === layer)) continue;
    layers.append(h('button', {
      type: 'button', class: view.layer === layer ? 'on' : '',
      onclick: () => tools.setLayer(layer),
    }, LAYER_WORDS[layer]));
  }
  const shot = shots.find((one) => one.frame === view.frame && one.layer === view.layer)
    || shots[0];
  const state = picturesFresh(world) || { state: 'ok', word: `нарисовано ${ago(shot.written)}` };
  box.append(
    h('div', { class: 'field-gallery-bar' }, frames, layers,
      h('span', {
        class: state.state === 'stale' ? 'field-said warn' : 'note-line',
        text: state.word,
      })),
    //: Метка времени в адресе: картинку перерисовывают на том же имени, и без
    //: неё браузер показывал бы прошлый мир после каждой пересборки.
    h('img', { class: 'field-shot', src: `${shot.url}?t=${shot.written}`, alt: '' }),
  );
  host.append(box);
  return box;
}
