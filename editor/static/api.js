// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The whole conversation with the server. Every failure arrives as an Error with
// the server's own words in it: the reasons are written for a human to read, and
// re-phrasing them here would only make them vaguer.

async function req(method, path, params, body) {
  const url = new URL(path, location.origin);
  //: Пары, а не только словарь: одному имени бывает несколько значений —
  //: превью рельефа примеряет сразу несколько чисел (`?set=…&set=…`), а из
  //: словаря второе такое просто выпало бы.
  const pairs = Array.isArray(params) ? params : Object.entries(params || {});
  for (const [key, value] of pairs) {
    if (value !== undefined && value !== null) url.searchParams.append(key, value);
  }
  const response = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let payload;
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(text || `${method} ${path}: ${response.status}`);
  }
  if (!response.ok) throw new Error(payload.error || `${method} ${path}: ${response.status}`);
  return payload;
}

export const api = {
  state: () => req('GET', '/api/state'),
  recipe: (name) => req('GET', '/api/recipe', { name }),
  cost: (name, quantity) => req('GET', '/api/cost', { name, quantity }),
  create: (body) => req('POST', '/api/recipe', null, body),
  update: (name, body) => req('PUT', '/api/recipe', { name }, body),
  remove: (name, body) => req('DELETE', '/api/recipe', { name }, body),
  measure: (name, body) => req('PUT', '/api/measure', { name }, body),
  // Реестр материалов (D-215): одна строка — всё, что нужно новому сырью.
  createMaterial: (body) => req('POST', '/api/material', null, body),
  updateMaterial: (name, body) => req('PUT', '/api/material', { name }, body),
  removeMaterial: (name) => req('DELETE', '/api/material', { name }),
  // Класс правится с двух сторон: со стороны класса — его состав, со стороны
  // вещи — какой класс она носит. Файл один и тот же, вопрос разный.
  putClass: (name, body) => req('PUT', '/api/class', { name }, body),
  dropClass: (name) => req('DELETE', '/api/class', { name }),
  classesOf: (name, classes) => req('PUT', '/api/classes', { name }, { classes }),
  // Типы зданий (D-218): живут в data/constants.yaml, а не в рецептах, но
  // тип — это состав, и правится он там же, где составы. Тело несёт и ключ с
  // именами (D-251): словарь и локали пишутся той же правкой.
  createBuilding: (body) => req('POST', '/api/building', null, body),
  updateBuilding: (name, body) => req('PUT', '/api/building', { name }, body),
  removeBuilding: (name) => req('DELETE', '/api/building', { name }),
  // Константы (D-065): реестр целиком и одна запись за раз.
  constants: () => req('GET', '/api/constants'),
  // Небо (D-320, D-324): те же константы, отобранные по смыслу, и
  // выведенные из них числа каждого мира. Только чтение — правки идут
  // через `updateConstant`, тем же путём, что и во вкладке констант.
  space: () => req('GET', '/api/space'),
  // Поле планет (D-328, план ландшафта 90-production/12): те же константы,
  // отобранные по смыслу, выведенные из них размеры каждой планеты и то, что
  // лежит собранным в build/field. Запуск конвейера — своим адресом: он идёт
  // минутами, поэтому не ответ, а работа, у которой спрашивают, как она.
  field: () => req('GET', '/api/field'),
  fieldRun: (body) => req('POST', '/api/field/run', null, body),
  fieldJob: (since = 0) => req('GET', '/api/field/job', { since: String(since) }),
  fieldStop: () => req('POST', '/api/field/stop'),
  createConstant: (body) => req('POST', '/api/constant', null, body),
  updateConstant: (key, body) => req('PUT', '/api/constant', { key }, body),
  removeConstant: (key) => req('DELETE', '/api/constant', { key }, { with_comment: true }),
  // Культуры Терры (D-057, D-136): свой файл вольта и свои имена на языках —
  // культуры, дикого предка и семени.
  plants: () => req('GET', '/api/plants'),
  putPlant: (body, { fresh = false, was = null } = {}) =>
    req('PUT', '/api/plant', { fresh: fresh ? '1' : null, was }, body),
  dropPlant: (id) => req('DELETE', '/api/plant', { id }),

  // Раскладка стартового мира (D-243): узлы, дороги и карманы живут в
  // data/world.yaml, и правятся картой, а не формой рецепта.
  world: () => req('GET', '/api/world'),
  putNode: (data, after, fresh) => req('PUT', '/api/world/node', { after, fresh: fresh ? '1' : null }, data),
  dropNode: (key) => req('DELETE', '/api/world/node', { key }),
  putEdge: (data) => req('PUT', '/api/world/edge', null, data),
  dropEdge: (a, b) => req('DELETE', '/api/world/edge', { a, b }),
  putPocket: (owner, items) => req('PUT', '/api/world/pocket', { owner }, { items }),
  // Массы (D-228): вес выводится из входов, и отчёт показывает, что вывелось
  // и что осталось при заданном вручную. Ничего не пишет.
  masses: () => req('POST', '/api/masses'),
  check: () => req('POST', '/api/check'),
  build: () => req('POST', '/api/build'),
  undo: () => req('POST', '/api/undo'),
};
