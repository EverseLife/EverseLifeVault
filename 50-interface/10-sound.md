<!-- SPDX-License-Identifier: LicenseRef-EverseLife-Content
     Copyright (C) 2026 Nurlan Urazkulov -->

# Звук: фоновая музыка планет и космоса

> **Статус:** идея (2026-09-12) · **Зависит от:** [10-world/00-setting-overview](../10-world/00-setting-overview.md), [10-world/02-terra](../10-world/02-terra.md), [10-world/04-pyroxis](../10-world/04-pyroxis.md), [10-world/05-aurora](../10-world/05-aurora.md), [10-world/06-space-and-travel](../10-world/06-space-and-travel.md)
>
> Промпты и настройки для генерации фоновых треков в Suno v5.5. Как звук
> попадает в клиент, где переключается и как громкость живёт в настройках —
> отдельное решение; здесь только материал.

## Тон

Музыка следует трём нотам сеттинга: **пустота**, **наследство**, **начало**.
Не героическая космоопера, не трейлерный оркестр. Фон, который не тянет
внимание: без вокала, без ударных, без мелодии-крючка, без нарастаний и
кульминаций. Сутки на планетах длинные (33–46 часов, D-029), ночь и день
не различаются музыкой.

**Один тембровый якорь на все места** — тёплый аналоговый пад. По нему
игрок узнаёт, что это одна игра; холод Авроры и жар Пироксиса читаются по
тому, что вокруг него.

## Инструмент

**Suno v5.5**, Custom mode. Причины: удобнее всех, инструменталы в v5.5
стали чистыми, ползунок длины до 6 минут. Оговорки:

- Suno не делает бесшовный стык. Луп режется в редакторе из середины трека
  с кроссфейдом; для этого и берётся максимальная длина.
- Suno плохо понимает отрицания в поле Style. Всё «без чего» — в поле
  **Exclude styles**, а не в промпт.
- Если лупы не сойдутся — те же промпты в **Stable Audio**: у него
  длительность и зацикливание заданы явно, а эмбиент-текстуры чище. Udio
  даёт более дорогой звук, но с ним больше возни.

### Общие для всех треков

| Поле | Значение |
|---|---|
| Model | v5.5 — без него нет ползунка Duration |
| Instrumental | включён |
| Duration (More options) | Custom, **6:00** |
| Audio influence | не трогать; только при загрузке референса |
| Persona | нет |

**Поле Lyrics** одно на все треки. С включённым Instrumental Suno читает из
него только теги в скобках — они задают форму. `[End]` в конце обязателен:
даёт жёсткую остановку вместо затухания, которое ломает луп.

```text
[Instrumental]
[Intro: sparse drone, no melody]
[Sustain: slow evolving textures, static harmony]
[Sustain: same mood, subtle variation, no build]
[Sustain: same mood, no climax]
[End]
```

Генерировать по два варианта на промпт (так по умолчанию). Общие поправки:

- Suno добавляет ритм — Weirdness +10, в Exclude дописать `beat, rhythm`.
- Получается «песенно», с мелодией — убрать из Style названия инструментов
  (piano, strings), оставить только текстуры.
- Появился хор — заменить `wordless breath pads` на `airy pads`, в Exclude
  добавить `choir, humming`.

## Треки

### Терра

Колыбель: первые города, поля и кряж, дороги и рынки. Единственное место,
где есть тепло и люди. Первая дорога, первый закон.

**Style**

```text
Warm minimalist ambient, felt piano, bowed strings, warm analog pad, faint wooden workshop textures, wide open plains, slow breathing pulse, hopeful loneliness, settler frontier, major-leaning, no beat, instrumental, seamless loop
```

**Exclude styles**

```text
vocals, choir, drums, percussion, epic orchestral, cinematic trailer, EDM, pop, rock, folk song, guitar solo, catchy melody, fade out
```

**Настройки**

| Поле | Значение |
|---|---|
| Weirdness | 35% |
| Style influence | 80% |
| Duration | 6:00 |

Если пиано начинает вести мелодию — убрать `felt piano`, оставить
`bowed strings, warm analog pad`.

### Аврора

Мерзлота, почти нет атмосферы, под километром льда города настоящих людей.
Изотопные реакторы Предтеч гаснут; первая искра мёртвого города — огонь.
Опасность детерминирована: головоломка, а не рулетка.

**Style**

```text
Glacial dark ambient, deep sub-bass reactor hum, glassy crystalline tones, ice cracking, sonar pings, huge cold cavernous reverb, wordless breath pads, abandoned underground city, reverent, static minor drone, no beat, instrumental, seamless loop
```

**Exclude styles**

```text
vocals, choir, humming, drums, percussion, epic orchestral, cinematic trailer, horror stingers, jump scare, EDM, piano melody, fade out
```

**Настройки**

| Поле | Значение |
|---|---|
| Weirdness | 55% |
| Style influence | 80% |
| Duration | 6:00 |

Реакторный гул должен быть полом микса, а не событием: если он пульсирует
как ритм — в Exclude `pulsing bass, beat`.

### Пироксис

Раскалённая насквозь, ночи не бывает, сутки 46 часов. Лавовые поля,
пепельные бури, кислорода нет. Извержения идут по расписанию (D-197) и
перекраивают карту: ритм, а не катастрофа. Угроза — среда, не существа.

**Style**

```text
Industrial volcanic dark ambient, seismic sub-bass rumble, distorted low brass drones, furnace metallic resonance, granular ash static, detuning heat shimmer pads, slow tectonic pulse, hostile, dissonant, no melody, no beat, instrumental, seamless loop
```

**Exclude styles**

```text
vocals, choir, drums, percussion, industrial metal, breakbeat, EDM, epic orchestral, cinematic trailer, screaming lead, guitar, fade out
```

**Настройки**

| Поле | Значение |
|---|---|
| Weirdness | 55% |
| Style influence | 85% |
| Duration | 6:00 |

`slow tectonic pulse` — раз в 8–16 секунд, ощущается, а не слышится. Если
Suno делает из него бит — заменить на `rare distant seismic swells`.

### Космос: перелёт

Недели полёта по дуге Ламберта вокруг молчащей звезды (D-271). Галактика
пуста. Корабль слышен изнутри: жизнеобеспечение, вентиляция, аккумуляторы.
Нет ощущения скорости, нет героики: терпение и расстояние.

**Style**

```text
Vast empty space ambient, shipboard life-support hum, slow evolving deep drones, rare pure sine and glass tones, dead radio hiss, weightless, patient, immense distance, no harmony movement, no beat, instrumental, seamless loop
```

**Exclude styles**

```text
vocals, choir, drums, percussion, epic orchestral, cinematic trailer, synthwave, arpeggios, EDM, piano, guitar, melody, fade out
```

**Настройки**

| Поле | Значение |
|---|---|
| Weirdness | 35% |
| Style influence | 80% |
| Duration | 6:00 |

Самый статичный трек из всех: почти без гармонического движения. Если
скучно даже для фона — добавить `slow filter sweeps`, но не аккорды.

### Космос: орбита и стыковка

Корабль на низкой орбите ждёт причала (D-245, D-288). Тот же гул борта, но
с ощущением прибытия: тональный центр возвращается, с поверхности идёт
маяк порта.

**Style**

```text
Quiet space ambient in low orbit, life-support hum, slow deep drones, soft periodic beacon pulse, faint proximity tones, relay clicks, calm expectant arrival, weightless, no beat, instrumental, seamless loop
```

**Exclude styles**

```text
vocals, choir, drums, percussion, epic orchestral, cinematic trailer, synthwave, EDM, piano, guitar, melody, build-up, fade out
```

**Настройки**

| Поле | Значение |
|---|---|
| Weirdness | 35% |
| Style influence | 80% |
| Duration | 6:00 |

Маяк — мягкий периодический тон, не метроном. Если он превращается в ритм —
заменить `soft periodic beacon pulse` на `occasional soft beacon tone`.

### Акватика (в запас)

Вне альфы (D-104); линия нимф видна в меню как «ещё в разработке». Океан,
живое вместо машинного, чужое, но не враждебное.

**Style**

```text
Submerged organic ambient, hydrophone textures, water-pressure filtered pads, soft resonant bells, bowed glass, gentle bubbling currents, slow breathing motion, alive, alien, mysterious, modal, no beat, instrumental, seamless loop
```

**Exclude styles**

```text
vocals, choir, drums, percussion, epic orchestral, cinematic trailer, new age flute, harp, EDM, tropical, melody, fade out
```

**Настройки**

| Поле | Значение |
|---|---|
| Weirdness | 45% |
| Style influence | 80% |
| Duration | 6:00 |

## Открытые вопросы

- Где переключается трек: по планете под ногами, по слою (поверхность,
  борт, орбита) или по узлу. Космос уже требует двух треков на один слой.
- Громкость и выключатель — в настройках учётной записи (вкладка
  «Учётная запись», D-238) или в общем меню.
- Лицензия сгенерированного: у Suno коммерческие права только на платных
  планах; проверить план до того, как треки попадут в сборку.
