// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nurlan Urazkulov

// Рельеф планеты как картинка: море, суша, горы, озёра и реки (D-319, D-321,
// D-323).
//
// Поле считает **движок** и только он (`api_terrain` → `tools/sketch.py`):
// перенести сюда шум значило бы завести миру две формы — ту, что показывает
// редактор, и ту, что строит игра, — и разошлись бы они на первой же правке.
// Здесь остаётся рисование: сетка широт и долгот, залитая цветом по высоте.
//
// Чистое: ни одного запроса, ни одной правки. На вход — то, что отдал движок.

const SEA = '#1d3a5c';
const DEEP = '#14263c';
const LAND = '#3f5a3a';
const HIGH = '#6b7f52';
const MOUNTAIN = '#8f8b7a';
const LAKE = '#2f6f9e';
const RIVER = '#4aa3d9';

/** Цвет клетки по её высоте: море глубиной, суша подъёмом, вершины камнем. */
export function tone(height, { sea_level: sea, mountain_level: mountain }) {
  if (height < sea) {
    //: Глубина — доля от уровня моря до нуля: мелководье светлее.
    const depth = sea > 0 ? Math.max(0, Math.min(1, (sea - height) / sea)) : 0;
    return mix(SEA, DEEP, depth);
  }
  if (height >= mountain) return MOUNTAIN;
  const span = Math.max(1e-9, mountain - sea);
  return mix(LAND, HIGH, (height - sea) / span);
}

function mix(from, to, share) {
  const a = hex(from);
  const b = hex(to);
  const k = Math.max(0, Math.min(1, share));
  const out = a.map((one, index) => Math.round(one + (b[index] - one) * k));
  return `rgb(${out.join(',')})`;
}

function hex(colour) {
  return [1, 3, 5].map((at) => parseInt(colour.slice(at, at + 2), 16));
}

/**
 * Поле на канву: одна клетка сетки — один прямоугольник.
 *
 * Равнопромежуточная проекция, как у таблицы: строка — широта, столбец —
 * долгота. Это не глобус и не притворяется им — по такой карте сверяют, где
 * море и где горы, а круглую землю показывает игра.
 */
export function draw(canvas, field, { rivers = true, lakes = true } = {}) {
  const { rows, cols, grid } = field;
  const width = canvas.width;
  const height = canvas.height;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, width, height);
  const cellW = width / cols;
  const cellH = height / rows;
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      ctx.fillStyle = tone(grid[row][col], field);
      //: Клетки кладутся с нахлёстом в пиксель: иначе между ними видны швы.
      ctx.fillRect(col * cellW, (rows - 1 - row) * cellH, cellW + 1, cellH + 1);
    }
  }
  if (lakes) {
    ctx.fillStyle = LAKE;
    for (const [row, col] of field.lakes || []) {
      ctx.fillRect(col * cellW, (rows - 1 - row) * cellH, cellW + 1, cellH + 1);
    }
  }
  if (rivers) {
    ctx.strokeStyle = RIVER;
    ctx.lineWidth = Math.max(1, cellW * 0.4);
    for (const river of field.rivers || []) {
      ctx.beginPath();
      river.forEach(([lat, lon], index) => {
        const x = ((lon + 180) / 360) * width;
        const y = ((90 - lat) / 180) * height;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }
  }
}

/** Что вышло из чисел, словами: доля моря, гор, сколько озёр и рек. */
export function summary(field) {
  const { rows, cols, grid, sea_level: sea, mountain_level: mountain } = field;
  let water = 0;
  let peaks = 0;
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const height = grid[row][col];
      if (height < sea) water += 1;
      else if (height >= mountain) peaks += 1;
    }
  }
  const cells = rows * cols;
  const land = cells - water;
  return {
    seaShare: water / cells,
    mountainShare: land > 0 ? peaks / land : 0,
    lakes: (field.lakes || []).length,
    rivers: (field.rivers || []).length,
    wet: Boolean(field.wet),
  };
}
