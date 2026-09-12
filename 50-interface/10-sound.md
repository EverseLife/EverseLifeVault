<!-- SPDX-License-Identifier: LicenseRef-EverseLife-Content
     Copyright (C) 2026 Nurlan Urazkulov -->

# Звук: фоновая музыка планет и космоса

> **Статус:** реализовано (D-333, 2026-09-12: клиент, провод и пять треков в сборке; трек Акватики — когда вернётся планета) · **Зависит от:** [10-world/00-setting-overview](../10-world/00-setting-overview.md), [10-world/02-terra](../10-world/02-terra.md), [10-world/04-pyroxis](../10-world/04-pyroxis.md), [10-world/05-aurora](../10-world/05-aurora.md), [10-world/06-space-and-travel](../10-world/06-space-and-travel.md), [09-redesign-2026-08](09-redesign-2026-08.md)
>
> Промпты и настройки для генерации фоновых треков в Suno v6 (план Pro), и
> правило клиента: что играет где и как громкость переживает перезагрузку
> (D-333).

## В клиенте (D-333)

**Что играет.** Трек выбирается по тому же месту, что и тема экрана (D-074,
D-080): планета под ногами даёт свой трек; на борту корабля — космос, и
у него два трека: корпус снят с причала, летит или дрейфует — «перелёт»;
пришвартован у причала или на своём круге орбиты — «орбита». Корабль у
космодрома Терры — всё ещё борт: тема уже говорит «пустота», музыка
говорит то же. С борта сервер отдаёт одно слово `look.ships.underway`:
помещения не знают ни причала, ни орбиты, а корпус уходит из ответа, как
только снялся, — вывести это клиенту неоткуда (D-225). `look.travel` не
подходит: это шаг тела между помещениями, а не рейс. Таймеров по данным
нет (D-226): музыка меняется вместе с `look`, как тема.

**Что правится.** П3 редизайна (D-238, D-318) запрещал звук в окне.
Фоновая музыка — не звук окна: не привязана к кнопке или числу и ничего о
мире не сообщает, поэтому D-333 выводит её из-под запрета; сам запрет и
короткие сигналы §6 брифа остаются как были.

**Громкость** — кнопка-нота в шапке, рамочная, как «сводка» рядом; под ней
один ползунок, и **ноль — выключено**: ни отдельного выключателя, ни
записки (владелец, 2026-09-12, вечер). На телефоне музыка — строка меню
«ещё» с ползунком на месте. Это настройка вида по D-298: живёт в браузере
(`everselife.music.volume`), не в учётной записи, переживает перезагрузку
и выход из игры. **По умолчанию включено на 50%** (владелец, 2026-09-12).
Слух получает квадрат положения ползунка: линейная шкала на слух неровная.

**Первый звук — после первого жеста.** Браузер не даст звука до клика или
клавиши; клиент ждёт первого `pointerdown`/`keydown` после входа, и до
него тишина. У кого музыка выключена, аудиоэлемент не создаётся вовсе.

**Где лежат файлы.** `frontend/public/music/<трек>.m4a`, AAC 96 kbps,
шесть имён: `terra`, `aurora`, `pyroxis`, `aquatica`, `space-transit`,
`space-orbit`. Лежат в git обычными файлами и едут в образ вместе с
остальным `public/` (`vite build` кладёт его в `dist/`). Имена без
отпечатка, поэтому nginx кэширует `/music/` на сутки, а не навечно;
перегенерированный трек заменяет файл, а не добавляет новый. Файла нет —
трек молчит (404 в консоли пишет сам браузер), и до перезагрузки страницы
клиент его больше не просит.

**Луп** — атрибутом `loop` одного элемента через Web Audio. Стык
готовится в файле, а не в клиенте: у WAV из Suno срезаются вступление и
затухание (края, где уровень ниже 35% медианы), хвост сводится с началом
кроссфейдом равной мощности за 4 с, и трек кончается ровно тем, с чего
начался. Громкость выравнивается на −20 LUFS (`loudnorm`), чтобы планеты
не отличались по уровню; кодек AAC 96 kbps, `faststart`. Смена трека —
спад за 1,2 с, подмена, подъём.

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

**Suno v6** (план Pro), Custom mode с Advanced options. Причины: удобнее
всех, инструменталы чистые, ползунок длины до 6 минут. В v6 три модели:
**v6** — точная и предсказуемая, основная для всех треков; **v6-wild** —
разброс и эксперимент, годится на вторую попытку для Авроры и Пироксиса,
где нужна текстура, а не форма; v6-mini — бесплатная урезанная, не нужна.
Оговорки:

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
| Model | v6 (v6-wild — только на вторую попытку, см. трек) |
| Instrumental | включён |
| Duration | Custom, **6:00** |
| Max Mode | выключен: он про плотность и «дорогой» мастеринг, фону это лишнее |
| Variety | Normal: разброс между дублями нужен умеренный, стиль держит промпт |
| Vocal gender | не трогать: инструментал |
| Personalize / My Taste | выключен: вкус аккаунта тянет к песням, а не к фону |
| Audio influence | не трогать; только при загрузке референса |
| Persona | нет |
| Style prompt | до 1000 символов; наши короче 260, длиннее для Suno хуже |

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
| Model | v6 |

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
| Model | v6; вторая попытка — v6-wild, если лёд звучит как обычный дарк-эмбиент |

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
| Model | v6; вторая попытка — v6-wild, если не хватает пепла и грязи в текстуре |

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
| Model | v6 |

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
| Model | v6 |

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
| Model | v6 |

## Открытые вопросы

- Лицензия сгенерированного: у Suno коммерческие права только на платных
  планах; план Pro их даёт, но условия на момент генерации стоит сохранить
  рядом с треками.
- Щелчок на стыке лупа: если после реальных треков слышен — два элемента с
  перекрытием вместо атрибута `loop`.
- Музыка по узлу (шахта, комплекс Предтеч, рынок) — не заведена: сначала
  планеты, и только если фон по планете окажется однообразным.
