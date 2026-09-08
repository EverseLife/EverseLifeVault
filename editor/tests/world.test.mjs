// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// Арифметика карты «Мира» — та половина редактора, что не трогает окно.
//
// Она стоит тестов больше всего остального: карта обещает совпасть с картой
// игры, обещание держится на одних числах с движком, и **разойтись они могут
// молча** — картинка рисуется в обоих случаях, а расходятся они на метрах,
// которых на глаз не видно. Дважды уже расходились: пин отсчитывался не от
// якоря, а от начала кадра (десятки метров на городе в полсотни), и восток
// мерился косинусом начала кадра вместо косинуса якоря (пять процентов на
// Авроре, и каждое сохранение уводило узел дальше).
//
// Узлы здесь выдуманы. Тест, привязанный к столице Терры, начнёт падать в
// день, когда столицу переложат, — и это будет не находка, а помеха.
//
// Запускается вместе со всем остальным: `tests/test_meta.py` зовёт
// `node --test` и пропускает набор, если node на машине нет.

import assert from 'node:assert/strict';
import { test } from 'node:test';

import * as map from '../static/world.js';

//: Земля радиусом в сто километров — примерно Терра после D-324. Точное
//: число неважно: важно, что метр и градус связаны через него.
const RADIUS = 99546.875;
const WORLD = { radii: { terra: RADIUS }, seating: { step_m: 7, gap_m: 6 } };
const GROUP = 'planet:terra';

/** Узлы одной поверхности: ядро в градусах, остальное метрами от соседей. */
function surface(extra = []) {
  return [
    { key: 'terra', layer: 'planet' },
    { key: 'terra.town', parent: 'terra', place: { lat: 40, lon: 20 }, city: true },
    { key: 'terra.town.core', parent: 'terra.town', anchor: 'terra.town', place: { x: 0, y: 0 } },
    { key: 'terra.town.shop', parent: 'terra.town', anchor: 'terra.town.core', place: { x: 30, y: -12 } },
    { key: 'terra.town.pit', parent: 'terra.town', anchor: 'terra.town.shop', place: { x: -78, y: -49 } },
    ...extra,
  ];
}

const at = (places, key) => places.get(key).map((one) => Math.round(one * 1e6) / 1e6);

test('метровый пин отсчитывается от якоря, а не от начала кадра', () => {
  const nodes = surface();
  const places = map.layout(nodes, GROUP, WORLD);
  //: Цепочка: лавка от ядра, карьер от лавки. Сложение по цепочке — это и
  //: есть то, что делает сид, кладя узлы один за другим.
  assert.deepEqual(at(places, 'terra.town.core'), [0, 0]);
  const shop = at(places, 'terra.town.shop');
  const pit = at(places, 'terra.town.pit');
  assert.equal(Math.round(shop[1]), -12);
  assert.equal(Math.round(pit[1]), -61);
  //: Восток складывается почти как север — почти, потому что косинус широты
  //: у якоря свой; на тридцати метрах разница исчезающая, и она проверяется
  //: отдельным тестом ниже.
  assert.ok(Math.abs(shop[0] - 30) < 0.01, `лавка на востоке: ${shop[0]}`);
  assert.ok(Math.abs(pit[0] - (30 - 78)) < 0.01, `карьер на востоке: ${pit[0]}`);
});

test('шаг на восток меряется косинусом широты якоря, как globe.offset', () => {
  //: Город на другой широте: там метр на восток — другая доля градуса, и
  //: карта обязана мерить его так же, как движок.
  const far = [
    { key: 'terra.south', parent: 'terra', place: { lat: -20, lon: 20 }, city: true },
    { key: 'terra.south.hall', parent: 'terra.south', anchor: 'terra.south', place: { x: 1000, y: 0 } },
  ];
  const places = map.layout(surface(far), GROUP, WORLD);
  const hall = places.get('terra.south.hall');
  const town = places.get('terra.south');
  //: Что сделал бы `globe.offset`: тысяча метров на восток от широты −20 —
  //: это столько-то долготы, а кадр меряет долготу по своей широте 40.
  const rad = Math.PI / 180;
  const dLon = 1000 / (RADIUS * Math.cos(-20 * rad));
  const expected = town[0] + dLon * RADIUS * Math.cos(40 * rad);
  assert.ok(
    Math.abs(hall[0] - expected) < 1e-6,
    `зал на востоке ${hall[0]}, а движок кладёт ${expected}`,
  );
  //: И это не то же самое, что считать по началу кадра: разница заметна.
  assert.ok(Math.abs(hall[0] - (town[0] + 1000)) > 40, 'подмена косинуса прошла бы незаметно');
});

test('брошенный туда же, где стоял, записывается тем же числом', () => {
  //: Единственное свойство, ради которого всё это считается дважды: карта
  //: читает пин и карта его пишет, и два хода обязаны сойтись — иначе узел
  //: уезжает на каждом сохранении, ничего не говоря.
  const nodes = surface([
    { key: 'terra.south', parent: 'terra', place: { lat: -20, lon: 20 }, city: true },
    { key: 'terra.south.hall', parent: 'terra.south', anchor: 'terra.south', place: { x: 1000, y: -400 } },
  ]);
  const places = map.layout(nodes, GROUP, WORLD);
  const frame = map.frameOf(nodes, GROUP, WORLD);
  for (const key of ['terra.town.shop', 'terra.town.pit', 'terra.south.hall']) {
    const node = nodes.find((one) => one.key === key);
    const base = map.anchorAt(node, nodes, GROUP, WORLD);
    assert.ok(base, `${key}: мерить не от чего`);
    assert.deepEqual(map.pinOffset(places.get(key), base, frame), node.place, key);
  }
});

test('градусный пин читается и пишется без потери места', () => {
  const nodes = surface();
  const frame = map.frameOf(nodes, GROUP, WORLD);
  const spot = map.pinMetres({ lat: 40.5, lon: 20.25 }, frame);
  const back = map.pinDegrees(spot, frame);
  assert.ok(Math.abs(back.lat - 40.5) < 1e-6, `широта вернулась ${back.lat}`);
  assert.ok(Math.abs(back.lon - 20.25) < 1e-6, `долгота вернулась ${back.lon}`);
});

test('узлу нутра якорь не нужен: метры пола — свои', () => {
  const nodes = [
    { key: 'ship', layer: 'planet' },
    { key: 'ship.hold', layer: 'location', parent: 'ship', place: { x: 40, y: 10 } },
    { key: 'ship.cabin', layer: 'location', parent: 'ship', anchor: 'ship.hold', place: { x: -20, y: 5 } },
  ];
  const places = map.layout(nodes, 'location:ship', {});
  //: Ни один не сдвинут якорем: внутри дома пин абсолютен, так его читает и
  //: `_pinned`, у которого метры нутра идут мимо глобуса.
  assert.deepEqual(places.get('ship.hold'), [40, 10]);
  assert.deepEqual(places.get('ship.cabin'), [-20, 5]);
  //: И мерить такому узлу не от кого — место ему пишут как есть.
  assert.equal(map.anchorAt(nodes[2], nodes, 'location:ship', {}), null);
});

test('нутро сажают числами движка, поверхность — числами вольта', () => {
  //: `runtime.MAP_STEP` о себе говорит прямо: это не баланс, поверхность им
  //: не меряется. Посадить план этажа семью метрами вольта значило бы
  //: нарисовать клубок там, где движок рисует комнаты.
  assert.deepEqual(map.seatingOf(WORLD, GROUP), { step: 7, gap: 6 });
  assert.deepEqual(map.seatingOf(WORLD, 'location:ship'), { step: 150, gap: 96 });
});

test('карта говорит, когда рисует неправду', () => {
  const nodes = surface();
  assert.equal(map.mapTrouble(nodes, GROUP, WORLD), null);
  //: Молчащий вольт — сломанный вольт: запасная пара рисует город в двадцать
  //: раз шире, и промолчать об этом хуже, чем не нарисовать.
  assert.match(map.mapTrouble(nodes, GROUP, { radii: WORLD.radii }), /map\.city_step_m/);
  assert.match(
    map.mapTrouble(nodes, GROUP, { seating: WORLD.seating }),
    /radius|радиус/,
  );
});

test('окно открывается в метрах и вмещает всю группу', () => {
  //: Раньше раскладка приводилась к шестистам условным единицам, и окно было
  //: у всех групп одно. Теперь масштаб — свойство окна, а не раскладки, и это
  //: то, без чего зум ничего не меняет: у города окно в десятки метров, у
  //: поверхности планеты — в десятки километров, и метка на обоих одна.
  const town = new Map([['a', [0, 0]], ['b', [30, -12]], ['c', [-78, -49]]]);
  const got = map.fitted(town);
  assert.ok(got.w > 108 && got.w < 160, `город шириной ${got.w} м`);
  assert.equal(Math.round(got.cx), -24);

  const planet = new Map([['x', [0, 0]], ['y', [46000, 27000]]]);
  assert.ok(map.fitted(planet).w > 46000, 'поверхность планеты — своим размахом');
});

test('группе из одного узла окно всё равно достаётся', () => {
  //: Размах ноль — вписывать нечего, а показать надо: без этого окно выходило
  //: нулевой ширины, и `viewBox` с нулём не рисует ничего вовсе.
  const lone = map.fitted(new Map([['one', [500, -300]]]));
  assert.ok(lone.w > 0, 'ширина есть');
  assert.deepEqual([lone.cx, lone.cy], [500, -300]);
  assert.deepEqual(map.fitted(new Map()), { cx: 0, cy: 0, w: lone.w });
});

test('масштаб называется той мерой, какой его читают', () => {
  //: Двести десять метров в пикселе и четырнадцать сантиметров — оба конца
  //: одной карты, и «0.14 м» на одном конце читается не лучше, чем «210000 мм»
  //: на другом.
  assert.match(map.spellScale(210), /210 м/);
  assert.match(map.spellScale(2100), /2\.1 км/);
  assert.match(map.spellScale(0.14), /14 см/);
  assert.match(map.spellScale(0.002), /2 мм/);
});

test('кадр повторяет пропорции панели, а не подгоняется браузером', () => {
  //: Одно число «метров в пикселе» на обе стороны — на нём стоит всё
  //: остальное: размер метки, порог подписи, шаг панорамы. Разойдись
  //: горизонталь с вертикалью, и метка на широкой панели стала бы овалом.
  const view = { cx: 100, cy: -50, w: 200 };
  const [x, y, w, h] = map.frameBox(view, 400, 300);
  assert.equal(w, 200);
  assert.equal(h, 150, 'высота кадра — из пропорций панели');
  assert.equal(w / 400, h / 300, 'метр в пикселе один на обе стороны');
  assert.equal(x + w / 2, view.cx);
  assert.equal(y + h / 2, view.cy);
});

test('зум держит точку под курсором на месте', () => {
  //: Иначе колесо над узлом приближает не к узлу, а к центру экрана — и
  //: чтобы разглядеть край карты, пришлось бы чередовать зум с панорамой.
  const view = { cx: 0, cy: 0, w: 1000 };
  const bounds = { min: 2, max: 1e6 };
  const hold = [400, -200];
  const got = map.recentre(view, 250, hold, bounds);
  assert.equal(got.w, 250);
  //: Точка `hold` отстояла от центра на 400 при ширине 1000 — то есть на
  //: 0.4 ширины; после сужения вчетверо она обязана отстоять на те же 0.4.
  assert.equal((hold[0] - got.cx) / got.w, (hold[0] - view.cx) / view.w);
  assert.equal((hold[1] - got.cy) / got.w, (hold[1] - view.cy) / view.w);
});

test('на упоре зума карта перестаёт ползти, а не ползёт молча', () => {
  //: Границы применяются до подсчёта отношения. Иначе на упоре ширина уже не
  //: менялась бы, а центр продолжал ехать к точке — карта уползала бы от
  //: каждого лишнего щелчка колеса.
  const bounds = { min: 50, max: 400 };
  const view = { cx: 0, cy: 0, w: 50 };
  const same = map.recentre(view, 10, [100, 0], bounds);
  assert.deepEqual(same, { cx: 0, cy: 0, w: 50 });
  assert.equal(map.recentre({ cx: 0, cy: 0, w: 400 }, 9000, [0, 0], bounds).w, 400);
});

test('колесо приводится к пикселям, какой бы мерой ни пришло', () => {
  //: В Firefox обычное колесо приходит строками, и без приведения тот же
  //: щелчок оказывался в сорок раз слабее обещанного.
  const svg = { clientHeight: 600 };
  assert.equal(map.wheelPixels({ deltaY: 100, deltaMode: 0 }, svg), 100);
  assert.equal(map.wheelPixels({ deltaY: 3, deltaMode: 1 }, svg), 48);
  assert.equal(map.wheelPixels({ deltaY: 1, deltaMode: 2 }, svg), 600);
});
