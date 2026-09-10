// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// Та половина вкладки «Планеты», что не трогает окно: чем число планетное,
// чьё оно и как названо.
//
// Тесты тут по одной причине: **линза деградирует молча**. Планетное число
// узнаётся тем, что все ключи его таблицы — планеты, а список планет задан
// дважды: `PLANETS` в `api_field.py` и `PLANET_WORDS` в `field.js`. Заведут
// пятый мир, допишут в питон и забудут в js — и `planet.land_area_share`
// снова станет «5 строк», одинаковыми для всех пяти; строка над списком
// скажет «у всех планет общие», карточки будут на месте, ошибки не будет.
// Ровно это правка и чинила, и ровно это некому заметить.
//
// Запускается вместе со всем остальным: `tests/test_meta.py` зовёт
// `node --test` по каталогу и пропускает набор, если node на машине нет.

import assert from 'node:assert/strict';
import { test } from 'node:test';

import * as field from '../static/field.js';

const value = (v) => ({ key: 'terrain.x', kind: 'value', value: v, unit: '' });

test('планетное число — то, у которого все ключи планеты', () => {
  assert.equal(field.perPlanet(value({ terra: 0.3, aquatica: 0.9, pyroxis: 0, aurora: 0 })), true);
  //: Хватает и одной: у планетного числа мир может быть назван не всякий.
  assert.equal(field.perPlanet(value({ terra: 0.3 })), true);
  //: А это — таблица про другое (`terrain.wind_belts`), и планетной не станет.
  assert.equal(field.perPlanet(value({ trade_lat: 30, westerly_lat: 60 })), false);
  assert.equal(field.perPlanet(value({ terra: 1, trade_lat: 30 })), false);
});

test('обычное число планетным не бывает', () => {
  for (const one of [50, 0, 'слово', true, null, [1, 2], {}]) {
    assert.equal(field.perPlanet(value(one)), false, String(one));
  }
  //: Формула и ссылка на реестр — не значение вовсе.
  assert.equal(field.perPlanet({ key: 'a', kind: 'formula', value: 'x * 2' }), false);
  assert.equal(field.perPlanet({ key: 'a', kind: 'value_from', value: 'materials' }), false);
});

test('в строке списка стоит число выбранной планеты и её имя', () => {
  const sea = { ...value({ terra: 0.3, aquatica: 0.9 }), unit: 'доля поверхности' };
  assert.equal(field.spellForPlanet(sea, 'terra'), '0.3 · Терра');
  assert.equal(field.spellForPlanet(sea, 'aquatica'), '0.9 · Акватика');
  //: Планета без строки в таблице — прочерк, а не «undefined» и не ноль.
  assert.equal(field.spellForPlanet(sea, 'pyroxis'), '— · Пироксис');
});

test('доля суши не округляется в ноль', () => {
  //: `num` режет до тысячных, а доли площади Земли — это 1.5e-05: округлив,
  //: список показал бы «0» у всех четырёх и снова не отзывался бы на выбор.
  const share = value({ terra: 1.52587890625e-5, aurora: 3.0517578125e-5 });
  assert.equal(field.spellForPlanet(share, 'terra'), '1.526e-5 · Терра');
  assert.equal(field.spellForPlanet(share, 'aurora'), '3.052e-5 · Аврора');
});

test('общее число рисуется как везде, с единицей', () => {
  const relief = { key: 'terrain.relief_m', kind: 'value', value: 750, unit: 'м' };
  assert.equal(field.spellForPlanet(relief, 'aurora'), '750 м');
});

test('свежесть поля судит дробность, а не одно наличие файла', () => {
  const world = { nside: 509, built: { present: true, nside: 509, written: Date.now() / 1000 } };
  assert.equal(field.freshness(world).state, 'ok');
  assert.equal(field.freshness({ ...world, nside: 720 }).state, 'stale');
  assert.equal(field.freshness({ nside: 509, built: { present: false } }).state, 'none');
});

test('снимки старше поля названы старыми', () => {
  const built = { present: true, nside: 509, written: 1000 };
  assert.equal(field.picturesFresh({ nside: 509, built, pictures: [{ written: 1200 }] }).state, 'ok');
  assert.equal(field.picturesFresh({ nside: 509, built, pictures: [{ written: 900 }] }).state, 'stale');
  //: Снимков нет вовсе — сказать нечего, и галерея скажет это сама.
  assert.equal(field.picturesFresh({ nside: 509, built, pictures: [] }), null);
});
