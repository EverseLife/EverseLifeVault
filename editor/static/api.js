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
  putClass: (name, members, note) => req('PUT', '/api/class', { name }, { members, note }),
  dropClass: (name) => req('DELETE', '/api/class', { name }),
  classesOf: (name, classes) => req('PUT', '/api/classes', { name }, { classes }),
  check: () => req('POST', '/api/check'),
  build: () => req('POST', '/api/build'),
  undo: () => req('POST', '/api/undo'),
};
