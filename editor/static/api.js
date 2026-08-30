// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// The whole conversation with the server. Every failure arrives as an Error with
// the server's own words in it: the reasons are written for a human to read, and
// re-phrasing them here would only make them vaguer.

async function req(method, path, params, body) {
  const url = new URL(path, location.origin);
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null) url.searchParams.set(key, value);
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
  createMaterial: (data) => req('POST', '/api/material', null, { data }),
  updateMaterial: (name, data) => req('PUT', '/api/material', { name }, { data }),
  removeMaterial: (name) => req('DELETE', '/api/material', { name }),
  // Класс правится с двух сторон: со стороны класса — его состав, со стороны
  // вещи — какой класс она носит. Файл один и тот же, вопрос разный.
  putClass: (name, members, note, id) => req('PUT', '/api/class', { name }, { members, note, id }),
  dropClass: (name) => req('DELETE', '/api/class', { name }),
  classesOf: (name, classes) => req('PUT', '/api/classes', { name }, { classes }),
  // Типы зданий (D-218): живут в data/constants.yaml, а не в рецептах, но
  // тип — это состав, и правится он там же, где составы.
  createBuilding: (data) => req('POST', '/api/building', null, { data }),
  updateBuilding: (name, data) => req('PUT', '/api/building', { name }, { data }),
  removeBuilding: (name) => req('DELETE', '/api/building', { name }),
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
