<!-- SPDX-License-Identifier: LicenseRef-EverseLife-Content
     Copyright (C) 2026 Nurlan Urazkulov -->

# Фацеты и провинции: словарь местности

> **Статус:** в реализации (стоит на D-321, D-323) · словарь имён и калибровок. С волной 7 плана ландшафта (90-production/12 §6, дополнение к D-321) строки фацетов живут как данные вольта — `data/facets.yaml`, английские имена оверлеем в `data/locales/en.yaml`, — а выбор фацета делает `engine/facet.py` по осям `biome.facet_axes`. Блок ниже — источник этих строк; правится он, и правка переносится в данные. Имена самих биомов (`biome.names`, D-321) получили тот же английский оверлей доменом `biomes` в `renames.json` (дополнение к D-331, 2026-09-12) — для легенды карты и слова клиента о находке; отказы мира пока говорят словом вольта (OQ-162).
>
> **Числа** здесь — стартовые калибровки для переноса в `data/constants.yaml` (D-065); в тексте они не обсуждаются. Порядок величин — от `biome.marks`, `biome.vein_k`, `biome.reach_m`, `biome.swing_c` в [реестре констант](../30-economy/07-constants.md).
>
> **Семнадцать биомов** *(семнадцатый — снежное поле Авроры, D-338)*. Четыре зональных — `rainforest`, `savanna`, `semidesert`, `woodland` — объявлены в `biome.names` волной 4 плана ландшафта (дополнение к D-321 от 2026-09-09); словарь написан под закрытый список из шестнадцати, и они входят в него на равных.

Три масштаба местности. **Макро** (3,5 км и крупнее) — климат и биом, их даёт шум и география (D-323). **Фацет** (пятна в десятки метров, мозаика с клетками размером с клетку поля, 50 м) — грань биома, в которой стоишь: стоя в лесу, ты всегда в лесу, но в чаще, на опушке, на гари или в буреломе; два узла в трёхстах метрах друг от друга читаются по-разному, в двадцати — обычно одинаково (владелец 2026-09-09, план §6), а первые кольца разведки вокруг города носят несколько лиц, не одно (дополнение к D-321 от 2026-09-18: до него мозаика была в 200 м, и все находки у столицы Терры выходили «Прибрежным лесом»). **Провинция** (несколько километров: на Терре сорок областей на 1 400 км² суши, около шести километров поперёк; «десятки километров» были до ужатия планет 2026-09-10) — область с собственным именем на карте и характером: сдвигом осадков и температуры, множителем жилы и парой фацетов, которые здесь встречаются чаще.

Фацет выбирается детерминированно из четырёх величин точки: `noise` — одна ровная выборка на клетку мозаики со стороной `wave_m` (50 м), даёт мозаику; `slope` — местная крутизна, 0 плоско, 1 обрыв; `wet` — близость воды; `high` — высота внутри местного пятна, 0 дно ложбины, 1 макушка. Поэтому у каждого фацета указано, где он сидит, диапазонами по трём последним; `noise` раздаётся по долям `share`. Пятое и последнее, что входит в выбор, — **провинция**: названные в её `favours` лица весят здесь `biome.facet_axes.favour_k` раз (волна 8 плана ландшафта), потому что провинция и есть «пара фацетов, которые здесь встречаются чаще». Наклон, а не закон: остальные лица биома сохраняют свою долю. Ничего сверх этих пяти в выборе нет — фацетов, зависящих от истории места, игроков или времени года, здесь нет по построению.

---

## Речевой регистр

Регистр — **поселенческий землемерный**: слова, какими первый лесник, землемер или ямщик подписывал бы четвертной лист карты. Это не поэзия и не наука, а служебная речь людей, которым место надо назвать так, чтобы напарник понял без карты: Гарь, Ерник, Веретье, Косогор, Курумник. Почти всё взято из живого русского географического словаря (Даль, землеустроительные описания, сибирские и северные говоры), потому что именно там уже сто лет лежат короткие, плоские, физические имена для того, что человек видит под ногами. Регистр подходит миру потому, что игрок в нём — напечатанный первопоселенец без истории: у него нет ни легенд, ни имён героев, только земля, вода, камень и крутизна; и имена, выведенные из четырёх измеримых величин, не могут обещать больше, чем даёт движок.

Правила имён, по которым словарь проверялся:

- имя работает в отрыве от предлога: подставляется как есть, в именительном («Вы здесь: Опушка», «путь до «Солончак»»), склонять его нечем (D-258);
- до 18 знаков — имя ложится подписью на карту;
- не совпадает с именами вещей и станций из `data/recipes.yaml`;
- различимо на слух внутри своего биома;
- английское имя — перевод смысла, а не транслит;
- имя провинции — как на старой карте, от приметы места, а не от людей.

---

## Фацеты

Поля: `share` — доля мест биома в процентах, внутри биома в сумме 100; `where` — диапазоны `slope`, `wet`, `high`; `marks` — доли мест фацета с лесом, камнем и лугом, абсолютные (заменяют `biome.marks` для этого фацета); `vein_k`, `reach_k`, `swing_k` — множители к `biome.vein_k`, `biome.reach_m` и `biome.swing_c` родительского биома.

```yaml
facets:
  # ---------- rainforest (дождевой лес) ----------
  - id: jungle_thicket
    ru: Дебри
    en: Deep jungle
    biome: rainforest
    share: 35
    where: {slope: [0.0, 0.4], wet: [0.0, 0.7], high: [0.2, 0.8]}
    marks: {woods: 100, stones: 5, meadow: 0}
    vein_k: 0.8
    reach_k: 0.6
    swing_k: 0.7
    note: стволы в два обхвата, под ногами прелый лист, неба не видно
  - id: jungle_gap
    ru: Прогалина
    en: Sun gap
    biome: rainforest
    share: 10
    where: {slope: [0.0, 0.3], wet: [0.0, 0.6], high: [0.3, 0.9]}
    marks: {woods: 60, stones: 5, meadow: 40}
    vein_k: 1.0
    reach_k: 1.4
    swing_k: 1.2
    note: упало большое дерево, в дыру бьёт свет, трава по грудь
  - id: jungle_deadfall
    ru: Валежник
    en: Log tangle
    biome: rainforest
    share: 10
    where: {slope: [0.0, 0.5], wet: [0.0, 0.5], high: [0.5, 1.0]}
    marks: {woods: 80, stones: 10, meadow: 10}
    vein_k: 1.0
    reach_k: 0.8
    swing_k: 1.0
    note: стволы навалены крест-накрест, идти — значит лезть
  - id: jungle_bottom
    ru: Мокрый лог
    en: Wet hollow
    biome: rainforest
    share: 20
    where: {slope: [0.0, 0.3], wet: [0.4, 1.0], high: [0.0, 0.3]}
    marks: {woods: 80, stones: 0, meadow: 20}
    vein_k: 0.5
    reach_k: 0.5
    swing_k: 0.6
    note: чёрная вода между корнями, ноги вязнут по щиколотку
  - id: jungle_ridge
    ru: Гряда
    en: Ridge
    biome: rainforest
    share: 15
    where: {slope: [0.2, 0.6], wet: [0.0, 0.4], high: [0.7, 1.0]}
    marks: {woods: 85, stones: 20, meadow: 5}
    vein_k: 1.4
    reach_k: 1.3
    swing_k: 1.0
    note: сухой хребтик под пологом, корни держатся за камень
  - id: jungle_scarp
    ru: Крутояр
    en: Scarp
    biome: rainforest
    share: 10
    where: {slope: [0.6, 1.0], wet: [0.0, 1.0], high: [0.2, 0.9]}
    marks: {woods: 50, stones: 60, meadow: 0}
    vein_k: 1.8
    reach_k: 1.5
    swing_k: 1.0
    note: обрыв в зелени, с уступа видно верхушки внизу

  # ---------- savanna (саванна) ----------
  - id: tall_grass
    ru: Травостой
    en: Tall grass
    biome: savanna
    share: 35
    where: {slope: [0.0, 0.3], wet: [0.1, 0.5], high: [0.2, 0.8]}
    marks: {woods: 10, stones: 5, meadow: 90}
    vein_k: 0.8
    reach_k: 1.0
    swing_k: 1.0
    note: трава выше пояса, по ней идут тропы зверья
  - id: grove
    ru: Роща
    en: Grove
    biome: savanna
    share: 15
    where: {slope: [0.0, 0.3], wet: [0.3, 0.8], high: [0.0, 0.5]}
    marks: {woods: 70, stones: 5, meadow: 30}
    vein_k: 0.8
    reach_k: 0.6
    swing_k: 0.8
    note: кучка широких деревьев, под ними тень и сбитая копытами земля
  - id: bare_patch
    ru: Плешина
    en: Bare patch
    biome: savanna
    share: 15
    where: {slope: [0.0, 0.2], wet: [0.0, 0.3], high: [0.5, 1.0]}
    marks: {woods: 0, stones: 30, meadow: 10}
    vein_k: 1.2
    reach_k: 1.3
    swing_k: 1.3
    note: рыжая утоптанная земля, трава не держится, солнце жарит
  - id: pan
    ru: Западина
    en: Pan
    biome: savanna
    share: 12
    where: {slope: [0.0, 0.15], wet: [0.5, 1.0], high: [0.0, 0.25]}
    marks: {woods: 20, stones: 0, meadow: 60}
    vein_k: 0.5
    reach_k: 1.0
    swing_k: 0.8
    note: блюдце с потрескавшимся илом, после дождя стоит вода
  - id: outcrop
    ru: Останец
    en: Outcrop
    biome: savanna
    share: 8
    where: {slope: [0.4, 1.0], wet: [0.0, 0.4], high: [0.7, 1.0]}
    marks: {woods: 10, stones: 90, meadow: 5}
    vein_k: 2.0
    reach_k: 1.8
    swing_k: 1.1
    note: груда серых глыб над травой, с макушки видно далеко
  - id: riverside_wood
    ru: Приречный лес
    en: Riverside wood
    biome: savanna
    share: 10
    where: {slope: [0.0, 0.3], wet: [0.7, 1.0], high: [0.0, 0.4]}
    marks: {woods: 80, stones: 5, meadow: 20}
    vein_k: 0.6
    reach_k: 0.5
    swing_k: 0.7
    note: полоса густых деревьев вдоль пересыхающего русла
  - id: scrub
    ru: Кустарник
    en: Scrub
    biome: savanna
    share: 5
    where: {slope: [0.1, 0.5], wet: [0.0, 0.4], high: [0.4, 0.9]}
    marks: {woods: 40, stones: 20, meadow: 30}
    vein_k: 1.0
    reach_k: 0.7
    swing_k: 1.1
    note: колючий низкий кустарник, цепляет одежду

  # ---------- desert (пустыня) ----------
  - id: dune
    ru: Бархан
    en: Dune
    biome: desert
    share: 25
    where: {slope: [0.1, 0.5], wet: [0.0, 0.2], high: [0.5, 1.0]}
    marks: {woods: 0, stones: 0, meadow: 0}
    vein_k: 0.3
    reach_k: 1.0
    swing_k: 1.1
    note: сыпучий песок, ветер сдувает след за час
  - id: stony_flat
    ru: Каменистая равнина
    en: Stony flat
    biome: desert
    share: 25
    where: {slope: [0.0, 0.2], wet: [0.0, 0.2], high: [0.3, 0.8]}
    marks: {woods: 0, stones: 70, meadow: 0}
    vein_k: 1.3
    reach_k: 1.3
    swing_k: 1.0
    note: чёрный от загара щебень, ровно, как стол
  - id: salt_flat
    ru: Соляная корка
    en: Salt flat
    biome: desert
    share: 12
    where: {slope: [0.0, 0.1], wet: [0.2, 0.6], high: [0.0, 0.2]}
    marks: {woods: 0, stones: 10, meadow: 0}
    vein_k: 0.6
    reach_k: 1.5
    swing_k: 1.2
    note: белая корка хрустит, вода под ней горькая
  - id: dry_wash
    ru: Сухое русло
    en: Dry wash
    biome: desert
    share: 15
    where: {slope: [0.0, 0.3], wet: [0.3, 0.8], high: [0.0, 0.3]}
    marks: {woods: 10, stones: 40, meadow: 10}
    vein_k: 1.0
    reach_k: 0.8
    swing_k: 0.9
    note: гравий и промытые валуны, редкий куст в ложе
  - id: mesa
    ru: Столовая гора
    en: Mesa
    biome: desert
    share: 8
    where: {slope: [0.5, 1.0], wet: [0.0, 0.2], high: [0.6, 1.0]}
    marks: {woods: 0, stones: 100, meadow: 0}
    vein_k: 2.0
    reach_k: 1.8
    swing_k: 1.0
    note: обрыв слоистого камня, наверху плоско и ветрено
  - id: oasis
    ru: Оазис
    en: Oasis
    biome: desert
    share: 5
    where: {slope: [0.0, 0.2], wet: [0.8, 1.0], high: [0.0, 0.3]}
    marks: {woods: 60, stones: 0, meadow: 40}
    vein_k: 0.4
    reach_k: 0.6
    swing_k: 0.6
    note: пальмы над лужей, кругом густая трава — одна зелень на день пути
  - id: clay_pan
    ru: Такыр
    en: Clay pan
    biome: desert
    share: 10
    where: {slope: [0.0, 0.1], wet: [0.1, 0.4], high: [0.1, 0.4]}
    marks: {woods: 0, stones: 5, meadow: 0}
    vein_k: 0.7
    reach_k: 1.6
    swing_k: 1.2
    note: глина растрескалась плитками, твёрдая, как обожжённая

  # ---------- semidesert (полупустыня) ----------
  - id: wormwood_flat
    ru: Полынник
    en: Wormwood flat
    biome: semidesert
    share: 35
    where: {slope: [0.0, 0.2], wet: [0.0, 0.4], high: [0.2, 0.8]}
    marks: {woods: 0, stones: 20, meadow: 30}
    vein_k: 1.0
    reach_k: 1.2
    swing_k: 1.0
    note: серая полынь по щиколотку, пахнет горько
  - id: alkali_flat
    ru: Солонец
    en: Alkali flat
    biome: semidesert
    share: 15
    where: {slope: [0.0, 0.1], wet: [0.3, 0.7], high: [0.0, 0.3]}
    marks: {woods: 0, stones: 5, meadow: 10}
    vein_k: 0.6
    reach_k: 1.3
    swing_k: 1.1
    note: земля белёсая и рыхлая, трава — пучками
  - id: gully
    ru: Овраг
    en: Gully
    biome: semidesert
    share: 15
    where: {slope: [0.4, 1.0], wet: [0.2, 0.7], high: [0.0, 0.4]}
    marks: {woods: 10, stones: 40, meadow: 20}
    vein_k: 1.4
    reach_k: 0.5
    swing_k: 0.9
    note: рыжие стенки, на дне промоина с редкой зеленью
  - id: saxaul
    ru: Саксаульник
    en: Saxaul stand
    biome: semidesert
    share: 10
    where: {slope: [0.0, 0.3], wet: [0.0, 0.3], high: [0.3, 0.8]}
    marks: {woods: 40, stones: 10, meadow: 5}
    vein_k: 0.9
    reach_k: 0.8
    swing_k: 1.0
    note: кривые низкие деревца, древесина твёрдая, как кость
  - id: stony_rise
    ru: Каменистый увал
    en: Stony rise
    biome: semidesert
    share: 15
    where: {slope: [0.2, 0.6], wet: [0.0, 0.3], high: [0.6, 1.0]}
    marks: {woods: 0, stones: 70, meadow: 10}
    vein_k: 1.8
    reach_k: 1.5
    swing_k: 1.1
    note: россыпь щебня на горбу, ветер не стихает
  - id: dry_lake
    ru: Сухое озеро
    en: Dry lake
    biome: semidesert
    share: 10
    where: {slope: [0.0, 0.1], wet: [0.4, 0.8], high: [0.0, 0.2]}
    marks: {woods: 0, stones: 0, meadow: 5}
    vein_k: 0.5
    reach_k: 1.6
    swing_k: 1.2
    note: ровное дно в трещинах, по краю кайма соли

  # ---------- steppe (степь) ----------
  - id: feather_grass
    ru: Ковыльник
    en: Feather grass
    biome: steppe
    share: 40
    where: {slope: [0.0, 0.2], wet: [0.0, 0.5], high: [0.3, 0.9]}
    marks: {woods: 0, stones: 5, meadow: 100}
    vein_k: 0.8
    reach_k: 1.2
    swing_k: 1.0
    note: серебристая трава волнами до самого края
  - id: grove_island
    ru: Колок
    en: Grove island
    biome: steppe
    share: 10
    where: {slope: [0.0, 0.2], wet: [0.4, 0.9], high: [0.0, 0.4]}
    marks: {woods: 80, stones: 0, meadow: 30}
    vein_k: 0.7
    reach_k: 0.5
    swing_k: 0.7
    note: кучка берёз и осин в западине, кругом голая степь
  - id: ravine
    ru: Балка
    en: Ravine
    biome: steppe
    share: 15
    where: {slope: [0.3, 0.8], wet: [0.3, 0.8], high: [0.0, 0.4]}
    marks: {woods: 30, stones: 20, meadow: 60}
    vein_k: 1.3
    reach_k: 0.5
    swing_k: 0.8
    note: пологая лощина с кустами по склонам, внизу сырее
  - id: long_rise
    ru: Увал
    en: Long rise
    biome: steppe
    share: 15
    where: {slope: [0.1, 0.4], wet: [0.0, 0.3], high: [0.7, 1.0]}
    marks: {woods: 0, stones: 30, meadow: 70}
    vein_k: 1.4
    reach_k: 1.6
    swing_k: 1.1
    note: длинный горб, с него видна вся округа
  - id: liman
    ru: Лиман
    en: Wet swale
    biome: steppe
    share: 10
    where: {slope: [0.0, 0.1], wet: [0.6, 1.0], high: [0.0, 0.3]}
    marks: {woods: 5, stones: 0, meadow: 80}
    vein_k: 0.5
    reach_k: 1.0
    swing_k: 0.8
    note: мокрый луг в блюдце, весной под водой
  - id: stony_ground
    ru: Каменник
    en: Stony ground
    biome: steppe
    share: 10
    where: {slope: [0.1, 0.5], wet: [0.0, 0.3], high: [0.5, 1.0]}
    marks: {woods: 0, stones: 70, meadow: 30}
    vein_k: 1.8
    reach_k: 1.3
    swing_k: 1.1
    note: плиты и щебень торчат из дёрна, трава редкая

  # ---------- woodland (сухолесье) ----------
  - id: open_wood
    ru: Редколесье
    en: Open wood
    biome: woodland
    share: 35
    where: {slope: [0.0, 0.3], wet: [0.1, 0.5], high: [0.3, 0.8]}
    marks: {woods: 60, stones: 15, meadow: 50}
    vein_k: 0.9
    reach_k: 1.0
    swing_k: 1.0
    note: деревья стоят вразброс, между ними сухая трава
  - id: oak_stand
    ru: Дубрава
    en: Oak stand
    biome: woodland
    share: 15
    where: {slope: [0.0, 0.3], wet: [0.3, 0.7], high: [0.2, 0.6]}
    marks: {woods: 90, stones: 10, meadow: 10}
    vein_k: 0.8
    reach_k: 0.7
    swing_k: 0.8
    note: широкие кроны смыкаются, под ногами жёлуди и сухой лист
  - id: glade
    ru: Поляна
    en: Glade
    biome: woodland
    share: 15
    where: {slope: [0.0, 0.2], wet: [0.2, 0.6], high: [0.2, 0.7]}
    marks: {woods: 20, stones: 5, meadow: 90}
    vein_k: 0.8
    reach_k: 1.3
    swing_k: 1.1
    note: круглый луг в кольце деревьев
  - id: brush
    ru: Чапыжник
    en: Brush
    biome: woodland
    share: 12
    where: {slope: [0.3, 0.7], wet: [0.0, 0.4], high: [0.4, 0.9]}
    marks: {woods: 40, stones: 30, meadow: 20}
    vein_k: 1.3
    reach_k: 0.6
    swing_k: 1.1
    note: жёсткий низкий кустарник по склону, не продраться
  - id: dry_hollow
    ru: Сухой лог
    en: Dry hollow
    biome: woodland
    share: 13
    where: {slope: [0.1, 0.5], wet: [0.3, 0.8], high: [0.0, 0.3]}
    marks: {woods: 70, stones: 20, meadow: 20}
    vein_k: 1.0
    reach_k: 0.6
    swing_k: 0.8
    note: узкое русло без воды, по дну камни и тенистые деревья
  - id: bald_top
    ru: Лысина
    en: Bald top
    biome: woodland
    share: 10
    where: {slope: [0.2, 0.6], wet: [0.0, 0.3], high: [0.8, 1.0]}
    marks: {woods: 5, stones: 70, meadow: 30}
    vein_k: 1.7
    reach_k: 1.7
    swing_k: 1.2
    note: голый камень на горбу, деревья кончаются ниже

  # ---------- forest (широколиственный лес) ----------
  - id: thicket
    ru: Чаща
    en: Thicket
    biome: forest
    share: 35
    where: {slope: [0.0, 0.4], wet: [0.1, 0.6], high: [0.2, 0.8]}
    marks: {woods: 100, stones: 10, meadow: 0}
    vein_k: 0.8
    reach_k: 0.7
    swing_k: 0.8
    note: сомкнутый полог, полумрак, тропы нет
  - id: edge
    ru: Опушка
    en: Edge
    biome: forest
    share: 12
    where: {slope: [0.0, 0.3], wet: [0.1, 0.6], high: [0.3, 0.9]}
    marks: {woods: 60, stones: 5, meadow: 60}
    vein_k: 0.9
    reach_k: 1.5
    swing_k: 1.2
    note: деревья редеют, трава густая, светло
  - id: windthrow
    ru: Ветровал
    en: Windthrow
    biome: forest
    share: 8
    where: {slope: [0.1, 0.6], wet: [0.0, 0.5], high: [0.6, 1.0]}
    marks: {woods: 80, stones: 15, meadow: 10}
    vein_k: 1.1
    reach_k: 0.8
    swing_k: 1.1
    note: стволы лежат в одну сторону, корни вывернуты с землёй
  - id: burn
    ru: Гарь
    en: Burn
    biome: forest
    share: 8
    where: {slope: [0.0, 0.4], wet: [0.0, 0.4], high: [0.4, 0.9]}
    marks: {woods: 30, stones: 10, meadow: 50}
    vein_k: 1.0
    reach_k: 1.4
    swing_k: 1.3
    note: чёрные стволы стоят голые, между ними кипрей и малина
  - id: alder_bottom
    ru: Ольшаник
    en: Alder bottom
    biome: forest
    share: 15
    where: {slope: [0.0, 0.3], wet: [0.5, 1.0], high: [0.0, 0.3]}
    marks: {woods: 90, stones: 0, meadow: 20}
    vein_k: 0.5
    reach_k: 0.5
    swing_k: 0.7
    note: чёрная ольха по щиколотку в воде, комары
  - id: knoll
    ru: Взлобок
    en: Knoll
    biome: forest
    share: 12
    where: {slope: [0.2, 0.5], wet: [0.0, 0.4], high: [0.7, 1.0]}
    marks: {woods: 85, stones: 20, meadow: 10}
    vein_k: 1.4
    reach_k: 1.1
    swing_k: 1.0
    note: сухой пригорок под дубами, корни выступают из земли
  - id: steep_gully
    ru: Яр
    en: Steep gully
    biome: forest
    share: 10
    where: {slope: [0.6, 1.0], wet: [0.3, 0.9], high: [0.1, 0.5]}
    marks: {woods: 60, stones: 50, meadow: 5}
    vein_k: 1.7
    reach_k: 0.6
    swing_k: 0.9
    note: обрывистый овраг с ручьём на дне, глина и камень в стенках

  # ---------- taiga (тайга) ----------
  - id: spruce_stand
    ru: Ельник
    en: Spruce stand
    biome: taiga
    share: 30
    where: {slope: [0.0, 0.4], wet: [0.2, 0.7], high: [0.1, 0.6]}
    marks: {woods: 100, stones: 10, meadow: 0}
    vein_k: 0.8
    reach_k: 0.6
    swing_k: 0.7
    note: тёмные ели, под ногами мох и хвоя, сыро и тихо
  - id: pine_wood
    ru: Бор
    en: Pine wood
    biome: taiga
    share: 25
    where: {slope: [0.0, 0.3], wet: [0.0, 0.4], high: [0.5, 1.0]}
    marks: {woods: 90, stones: 20, meadow: 10}
    vein_k: 1.1
    reach_k: 1.3
    swing_k: 1.1
    note: сосны на песке, сухо, светло, брусничник
  - id: swamp_wood
    ru: Согра
    en: Swamp wood
    biome: taiga
    share: 15
    where: {slope: [0.0, 0.2], wet: [0.6, 1.0], high: [0.0, 0.3]}
    marks: {woods: 60, stones: 0, meadow: 20}
    vein_k: 0.4
    reach_k: 0.6
    swing_k: 0.7
    note: чахлые сосенки во мху, кочки, вода в следах
  - id: deadfall
    ru: Бурелом
    en: Deadfall
    biome: taiga
    share: 10
    where: {slope: [0.1, 0.6], wet: [0.1, 0.5], high: [0.4, 1.0]}
    marks: {woods: 80, stones: 15, meadow: 5}
    vein_k: 1.0
    reach_k: 0.7
    swing_k: 1.0
    note: сухие стволы навалом, идёшь по брёвнам
  - id: boulder_run
    ru: Валунник
    en: Boulder run
    biome: taiga
    share: 8
    where: {slope: [0.3, 0.8], wet: [0.0, 0.3], high: [0.6, 1.0]}
    marks: {woods: 20, stones: 100, meadow: 0}
    vein_k: 2.2
    reach_k: 1.5
    swing_k: 1.2
    note: серые глыбы во мху, между ними пусто и гулко
  - id: forest_glade
    ru: Луговина
    en: Forest glade
    biome: taiga
    share: 12
    where: {slope: [0.0, 0.2], wet: [0.3, 0.7], high: [0.1, 0.5]}
    marks: {woods: 20, stones: 5, meadow: 80}
    vein_k: 0.8
    reach_k: 1.5
    swing_k: 1.2
    note: открытый луг в тайге, трава по пояс, по краю осины

  # ---------- tundra (тундра) ----------
  - id: moss_flat
    ru: Моховина
    en: Moss flat
    biome: tundra
    share: 30
    where: {slope: [0.0, 0.2], wet: [0.3, 0.7], high: [0.2, 0.6]}
    marks: {woods: 0, stones: 10, meadow: 40}
    vein_k: 0.8
    reach_k: 1.0
    swing_k: 1.0
    note: пружинит под ногой, мох и ягель без края
  - id: hummocks
    ru: Кочкарник
    en: Hummocks
    biome: tundra
    share: 20
    where: {slope: [0.0, 0.15], wet: [0.5, 1.0], high: [0.0, 0.3]}
    marks: {woods: 0, stones: 0, meadow: 50}
    vein_k: 0.5
    reach_k: 0.9
    swing_k: 0.9
    note: кочки по колено, между ними ржавая вода
  - id: rubble
    ru: Россыпь
    en: Rubble
    biome: tundra
    share: 15
    where: {slope: [0.1, 0.5], wet: [0.0, 0.3], high: [0.6, 1.0]}
    marks: {woods: 0, stones: 90, meadow: 5}
    vein_k: 1.8
    reach_k: 1.4
    swing_k: 1.1
    note: щебень и плитняк, лишайник на камнях
  - id: dwarf_scrub
    ru: Ерник
    en: Dwarf scrub
    biome: tundra
    share: 15
    where: {slope: [0.0, 0.3], wet: [0.3, 0.8], high: [0.1, 0.5]}
    marks: {woods: 30, stones: 5, meadow: 30}
    vein_k: 0.7
    reach_k: 0.6
    swing_k: 0.9
    note: карликовая берёзка по пояс, цепкая, вязкая
  - id: frost_mound
    ru: Бугор пучения
    en: Frost mound
    biome: tundra
    share: 8
    where: {slope: [0.2, 0.6], wet: [0.2, 0.6], high: [0.7, 1.0]}
    marks: {woods: 0, stones: 30, meadow: 40}
    vein_k: 1.0
    reach_k: 1.5
    swing_k: 1.1
    note: круглый холм с трещиной на макушке, внутри лёд
  - id: hollow
    ru: Ложбина
    en: Hollow
    biome: tundra
    share: 12
    where: {slope: [0.0, 0.2], wet: [0.6, 1.0], high: [0.0, 0.25]}
    marks: {woods: 0, stones: 5, meadow: 30}
    vein_k: 0.6
    reach_k: 1.0
    swing_k: 0.9
    note: осевшее блюдце с мелким озерцом, берега оплывают

  # ---------- coast (берег) ----------
  - id: sandy_shore
    ru: Пляж
    en: Sandy shore
    biome: coast
    share: 20
    where: {slope: [0.0, 0.1], wet: [0.8, 1.0], high: [0.0, 0.2]}
    marks: {woods: 0, stones: 5, meadow: 0}
    vein_k: 0.4
    reach_k: 1.5
    swing_k: 0.9
    note: плотный сырой песок, полоса водорослей по линии прибоя
  - id: shingle
    ru: Галечник
    en: Shingle
    biome: coast
    share: 15
    where: {slope: [0.0, 0.2], wet: [0.8, 1.0], high: [0.0, 0.25]}
    marks: {woods: 0, stones: 60, meadow: 0}
    vein_k: 0.8
    reach_k: 1.3
    swing_k: 1.0
    note: окатанная галька гремит под ногой, к воде круче
  - id: cliff
    ru: Обрыв
    en: Cliff
    biome: coast
    share: 15
    where: {slope: [0.6, 1.0], wet: [0.5, 1.0], high: [0.3, 1.0]}
    marks: {woods: 10, stones: 100, meadow: 10}
    vein_k: 2.0
    reach_k: 1.8
    swing_k: 1.0
    note: стена слоистого камня, внизу бьёт вода
  - id: dune_ridge
    ru: Дюна
    en: Dune ridge
    biome: coast
    share: 12
    where: {slope: [0.2, 0.5], wet: [0.4, 0.8], high: [0.5, 1.0]}
    marks: {woods: 10, stones: 0, meadow: 30}
    vein_k: 0.4
    reach_k: 1.3
    swing_k: 1.2
    note: сыпучий вал с колосняком на гребне
  - id: tidal_flat
    ru: Солёный луг
    en: Salt meadow
    biome: coast
    share: 13
    where: {slope: [0.0, 0.1], wet: [0.7, 1.0], high: [0.0, 0.2]}
    marks: {woods: 0, stones: 0, meadow: 50}
    vein_k: 0.3
    reach_k: 1.2
    swing_k: 0.8
    note: солёный луг, в прилив под водой, ил в промоинах
  - id: shore_wood
    ru: Прибрежный лес
    en: Shore wood
    biome: coast
    share: 15
    where: {slope: [0.0, 0.3], wet: [0.4, 0.8], high: [0.3, 0.9]}
    marks: {woods: 80, stones: 10, meadow: 20}
    vein_k: 0.6
    reach_k: 0.6
    swing_k: 0.8
    note: кривые от ветра деревья, все кроны наклонены от моря
  - id: lagoon
    ru: Лагуна
    en: Lagoon
    biome: coast
    share: 10
    where: {slope: [0.0, 0.1], wet: [0.9, 1.0], high: [0.0, 0.15]}
    marks: {woods: 5, stones: 0, meadow: 40}
    vein_k: 0.3
    reach_k: 1.2
    swing_k: 0.8
    note: тихая мелкая вода за косой, тростник по краю

  # ---------- floodplain (пойма) ----------
  - id: water_meadow
    ru: Заливной луг
    en: Water meadow
    biome: floodplain
    share: 30
    where: {slope: [0.0, 0.1], wet: [0.5, 0.9], high: [0.1, 0.5]}
    marks: {woods: 5, stones: 0, meadow: 100}
    vein_k: 0.7
    reach_k: 1.3
    swing_k: 1.0
    note: ровный сочный луг, весной под водой
  - id: willow_brake
    ru: Ивняк
    en: Willow brake
    biome: floodplain
    share: 20
    where: {slope: [0.0, 0.2], wet: [0.8, 1.0], high: [0.0, 0.3]}
    marks: {woods: 80, stones: 0, meadow: 20}
    vein_k: 0.5
    reach_k: 0.6
    swing_k: 0.8
    note: густой ивовый прут по самой воде, ил под ногами
  - id: oxbow
    ru: Старица
    en: Oxbow
    biome: floodplain
    share: 12
    where: {slope: [0.0, 0.1], wet: [0.9, 1.0], high: [0.0, 0.2]}
    marks: {woods: 20, stones: 0, meadow: 40}
    vein_k: 0.3
    reach_k: 1.0
    swing_k: 0.8
    note: дугой стоячая вода, ряска, по берегу камыш
  - id: levee_ridge
    ru: Грива
    en: Levee ridge
    biome: floodplain
    share: 15
    where: {slope: [0.0, 0.2], wet: [0.3, 0.7], high: [0.6, 1.0]}
    marks: {woods: 60, stones: 5, meadow: 40}
    vein_k: 1.2
    reach_k: 1.2
    swing_k: 1.0
    note: сухая гряда над лугом, дубы и песок
  - id: sandbar
    ru: Коса
    en: Sandbar
    biome: floodplain
    share: 10
    where: {slope: [0.0, 0.15], wet: [0.9, 1.0], high: [0.0, 0.2]}
    marks: {woods: 0, stones: 10, meadow: 5}
    vein_k: 0.6
    reach_k: 1.5
    swing_k: 1.1
    note: намытая полоса песка в излучине, без травы
  - id: steep_bank
    ru: Круча
    en: Steep bank
    biome: floodplain
    share: 8
    where: {slope: [0.6, 1.0], wet: [0.6, 1.0], high: [0.3, 1.0]}
    marks: {woods: 30, stones: 40, meadow: 20}
    vein_k: 1.6
    reach_k: 1.4
    swing_k: 1.0
    note: подмытый берег, глина и слои песка, корни висят
  - id: bottomland_wood
    ru: Урёма
    en: Bottomland wood
    biome: floodplain
    share: 5
    where: {slope: [0.0, 0.2], wet: [0.6, 0.9], high: [0.2, 0.6]}
    marks: {woods: 90, stones: 0, meadow: 20}
    vein_k: 0.6
    reach_k: 0.5
    swing_k: 0.7
    note: густой сырой лес, крапива и хмель по стволам

  # ---------- marsh (болото) ----------
  - id: quagmire
    ru: Топь
    en: Quagmire
    biome: marsh
    share: 20
    where: {slope: [0.0, 0.1], wet: [0.8, 1.0], high: [0.0, 0.25]}
    marks: {woods: 0, stones: 0, meadow: 20}
    vein_k: 0.2
    reach_k: 1.0
    swing_k: 0.8
    note: зыбун, под мхом вода, нога уходит по колено и дальше
  - id: moss_bog
    ru: Мшара
    en: Moss bog
    biome: marsh
    share: 25
    where: {slope: [0.0, 0.1], wet: [0.6, 0.9], high: [0.2, 0.6]}
    marks: {woods: 10, stones: 0, meadow: 30}
    vein_k: 0.5
    reach_k: 1.1
    swing_k: 1.0
    note: рыжий сфагнум и клюква, сосенки по колено
  - id: reed_beds
    ru: Плавни
    en: Reed beds
    biome: marsh
    share: 15
    where: {slope: [0.0, 0.1], wet: [0.9, 1.0], high: [0.0, 0.2]}
    marks: {woods: 0, stones: 0, meadow: 50}
    vein_k: 0.2
    reach_k: 0.4
    swing_k: 0.8
    note: тростник выше головы, протоки с тёмной водой
  - id: bog_ridge
    ru: Веретье
    en: Bog ridge
    biome: marsh
    share: 15
    where: {slope: [0.0, 0.3], wet: [0.3, 0.6], high: [0.7, 1.0]}
    marks: {woods: 70, stones: 10, meadow: 30}
    vein_k: 1.5
    reach_k: 1.3
    swing_k: 1.1
    note: сухая грядка в болоте, сосны и черника
  - id: fen_hollow
    ru: Мочажина
    en: Fen hollow
    biome: marsh
    share: 15
    where: {slope: [0.0, 0.1], wet: [0.7, 1.0], high: [0.1, 0.4]}
    marks: {woods: 0, stones: 0, meadow: 60}
    vein_k: 0.3
    reach_k: 1.2
    swing_k: 0.9
    note: осока по колено, вода стоит вровень с травой
  - id: marsh_wood
    ru: Болотный лес
    en: Marsh wood
    biome: marsh
    share: 10
    where: {slope: [0.0, 0.2], wet: [0.6, 0.9], high: [0.3, 0.7]}
    marks: {woods: 70, stones: 0, meadow: 20}
    vein_k: 0.5
    reach_k: 0.6
    swing_k: 0.8
    note: чахлые берёзы и ели на кочках, дно мягкое

  # ---------- foothills (предгорье) ----------
  - id: hillside
    ru: Косогор
    en: Hillside
    biome: foothills
    share: 30
    where: {slope: [0.3, 0.6], wet: [0.0, 0.5], high: [0.3, 0.8]}
    marks: {woods: 40, stones: 40, meadow: 40}
    vein_k: 1.2
    reach_k: 1.2
    swing_k: 1.0
    note: пологий длинный склон, трава и редкие деревья
  - id: scree
    ru: Осыпь
    en: Talus
    biome: foothills
    share: 12
    where: {slope: [0.5, 0.9], wet: [0.0, 0.3], high: [0.4, 0.9]}
    marks: {woods: 0, stones: 100, meadow: 0}
    vein_k: 2.0
    reach_k: 1.4
    swing_k: 1.1
    note: съезжающий щебень, каждый шаг — полшага назад
  - id: glen
    ru: Падь
    en: Glen
    biome: foothills
    share: 18
    where: {slope: [0.1, 0.4], wet: [0.5, 1.0], high: [0.0, 0.3]}
    marks: {woods: 80, stones: 20, meadow: 30}
    vein_k: 0.8
    reach_k: 0.5
    swing_k: 0.7
    note: узкая долина с ручьём, лес по обоим склонам
  - id: shelf
    ru: Полка
    en: Shelf
    biome: foothills
    share: 12
    where: {slope: [0.0, 0.2], wet: [0.1, 0.5], high: [0.4, 0.8]}
    marks: {woods: 30, stones: 40, meadow: 50}
    vein_k: 1.0
    reach_k: 1.5
    swing_k: 1.0
    note: ровная площадка на склоне, с неё видно долину
  - id: crag
    ru: Утёс
    en: Crag
    biome: foothills
    share: 8
    where: {slope: [0.8, 1.0], wet: [0.0, 0.4], high: [0.6, 1.0]}
    marks: {woods: 0, stones: 100, meadow: 0}
    vein_k: 2.5
    reach_k: 1.8
    swing_k: 1.1
    note: отвесная скала торчит из склона, у подножия глыбы
  - id: saddle
    ru: Седловина
    en: Saddle
    biome: foothills
    share: 10
    where: {slope: [0.1, 0.4], wet: [0.0, 0.3], high: [0.8, 1.0]}
    marks: {woods: 10, stones: 60, meadow: 30}
    vein_k: 1.4
    reach_k: 2.0
    swing_k: 1.2
    note: прогиб между двумя горбами, сквозной ветер
  - id: piedmont_wood
    ru: Подгорный лес
    en: Piedmont wood
    biome: foothills
    share: 10
    where: {slope: [0.1, 0.3], wet: [0.3, 0.7], high: [0.0, 0.4]}
    marks: {woods: 80, stones: 20, meadow: 20}
    vein_k: 0.9
    reach_k: 0.7
    swing_k: 0.8
    note: густой лес у подножия, валуны между стволами

  # ---------- alpine (горный склон) ----------
  - id: alpine_meadow
    ru: Альпийский луг
    en: Alpine meadow
    biome: alpine
    share: 20
    where: {slope: [0.2, 0.5], wet: [0.3, 0.7], high: [0.1, 0.5]}
    marks: {woods: 0, stones: 30, meadow: 80}
    vein_k: 1.0
    reach_k: 1.3
    swing_k: 0.9
    note: низкая густая трава в цветах, камни выглядывают
  - id: boulder_field
    ru: Курумник
    en: Boulder field
    biome: alpine
    share: 20
    where: {slope: [0.3, 0.7], wet: [0.0, 0.3], high: [0.3, 0.8]}
    marks: {woods: 0, stones: 100, meadow: 0}
    vein_k: 2.0
    reach_k: 1.2
    swing_k: 1.1
    note: море глыб в лишайнике, шагаешь с камня на камень
  - id: rock_face
    ru: Скальник
    en: Rock face
    biome: alpine
    share: 15
    where: {slope: [0.8, 1.0], wet: [0.0, 0.5], high: [0.3, 1.0]}
    marks: {woods: 0, stones: 100, meadow: 0}
    vein_k: 2.5
    reach_k: 1.6
    swing_k: 1.0
    note: отвес голого камня, пройти только вдоль
  - id: crest
    ru: Гребень
    en: Crest
    biome: alpine
    share: 10
    where: {slope: [0.4, 0.8], wet: [0.0, 0.2], high: [0.9, 1.0]}
    marks: {woods: 0, stones: 100, meadow: 0}
    vein_k: 1.8
    reach_k: 2.0
    swing_k: 1.3
    note: узкий хребет, ветер валит с ног, обе стороны вниз
  - id: snowfield
    ru: Снежник
    en: Snow patch
    biome: alpine
    share: 10
    where: {slope: [0.2, 0.6], wet: [0.4, 0.8], high: [0.6, 1.0]}
    marks: {woods: 0, stones: 20, meadow: 0}
    vein_k: 0.6
    reach_k: 1.5
    swing_k: 0.7
    note: слежавшийся снег не тает и летом, по краю талая вода
  - id: cirque
    ru: Ледниковый цирк
    en: Cirque
    biome: alpine
    share: 10
    where: {slope: [0.1, 0.4], wet: [0.5, 1.0], high: [0.0, 0.3]}
    marks: {woods: 0, stones: 60, meadow: 20}
    vein_k: 1.2
    reach_k: 1.0
    swing_k: 0.8
    note: чаша с озерцом под отвесными стенами
  - id: scree_slope
    ru: Щебнистый склон
    en: Scree slope
    biome: alpine
    share: 15
    where: {slope: [0.5, 0.8], wet: [0.0, 0.3], high: [0.4, 0.9]}
    marks: {woods: 0, stones: 100, meadow: 0}
    vein_k: 2.0
    reach_k: 1.3
    swing_k: 1.1
    note: мелкий щебень едет под ногой до самого низа

  # ---------- snow (снежное поле, Аврора; D-338) ----------
  - id: deep_snow
    ru: Глубокий снег
    en: Deep snow
    biome: snow
    share: 30
    where: {slope: [0.0, 0.2], wet: [0.0, 1.0], high: [0.0, 0.45]}
    marks: {woods: 0, stones: 0, meadow: 0}
    vein_k: 0.6
    reach_k: 0.8
    swing_k: 0.9
    note: снег по пояс, тропу приходится топтать
  - id: wind_crust
    ru: Наст
    en: Wind crust
    biome: snow
    share: 25
    where: {slope: [0.0, 0.25], wet: [0.0, 1.0], high: [0.45, 1.0]}
    marks: {woods: 0, stones: 10, meadow: 0}
    vein_k: 0.6
    reach_k: 1.2
    swing_k: 1.1
    note: ветер спрессовал снег в корку, она держит шаг и хрустит
  - id: drift_ridges
    ru: Сугробы
    en: Snow drifts
    biome: snow
    share: 20
    where: {slope: [0.2, 0.5], wet: [0.0, 1.0], high: [0.0, 1.0]}
    marks: {woods: 0, stones: 10, meadow: 0}
    vein_k: 0.7
    reach_k: 0.9
    swing_k: 1.0
    note: ветер намёл гряды выше роста, между ними тихо
  - id: black_boulders
    ru: Чёрные валуны
    en: Black boulders
    biome: snow
    share: 15
    where: {slope: [0.6, 1.0], wet: [0.0, 1.0], high: [0.55, 1.0]}
    marks: {woods: 0, stones: 90, meadow: 0}
    vein_k: 1.6
    reach_k: 1.5
    swing_k: 1.2
    note: чёрные валуны торчат из снега, между ними сдувает до камня
  - id: frozen_hollow
    ru: Мёрзлая лощина
    en: Frozen hollow
    biome: snow
    share: 10
    where: {slope: [0.0, 0.15], wet: [0.0, 1.0], high: [0.0, 0.3]}
    marks: {woods: 0, stones: 0, meadow: 0}
    vein_k: 0.5
    reach_k: 1.0
    swing_k: 0.8
    note: в низине снег синеет, под ним старый лёд

  # ---------- ice (ледяное поле: ледники и шапки; у Авроры — полюса с D-338) ----------
  - id: firn_plain
    ru: Фирн
    en: Firn plain
    biome: ice
    share: 30
    where: {slope: [0.0, 0.2], wet: [0.0, 0.5], high: [0.3, 0.8]}
    marks: {woods: 0, stones: 0, meadow: 0}
    vein_k: 0.6
    reach_k: 1.2
    swing_k: 1.0
    note: слежавшийся зернистый снег держит шаг, ровно до горизонта
  - id: sastrugi
    ru: Заструги
    en: Sastrugi
    biome: ice
    share: 20
    where: {slope: [0.0, 0.2], wet: [0.0, 0.3], high: [0.5, 1.0]}
    marks: {woods: 0, stones: 0, meadow: 0}
    vein_k: 0.6
    reach_k: 1.3
    swing_k: 1.1
    note: твёрдые снежные гребни по ветру, об них ломают ноги
  - id: crevasses
    ru: Ледяные трещины
    en: Crevasse field
    biome: ice
    share: 12
    where: {slope: [0.2, 0.6], wet: [0.0, 0.4], high: [0.2, 0.7]}
    marks: {woods: 0, stones: 0, meadow: 0}
    vein_k: 0.8
    reach_k: 1.0
    swing_k: 1.0
    note: синие разломы под тонкими снежными мостами
  - id: bare_summit
    ru: Голец
    en: Bare summit
    biome: ice
    share: 8
    where: {slope: [0.4, 1.0], wet: [0.0, 0.3], high: [0.8, 1.0]}
    marks: {woods: 0, stones: 100, meadow: 0}
    vein_k: 2.5
    reach_k: 1.8
    swing_k: 1.2
    note: чёрный камень торчит из льда, единственное, что не бело
  - id: glaze_ice
    ru: Наледь
    en: Bare ice
    biome: ice
    share: 12
    where: {slope: [0.0, 0.3], wet: [0.5, 1.0], high: [0.0, 0.3]}
    marks: {woods: 0, stones: 0, meadow: 0}
    vein_k: 0.7
    reach_k: 1.4
    swing_k: 0.9
    note: голый лёд без снега, скользко, в глубине видно пузыри
  - id: melt_pool
    ru: Полынья
    en: Melt pool
    biome: ice
    share: 8
    where: {slope: [0.0, 0.1], wet: [0.8, 1.0], high: [0.0, 0.2]}
    marks: {woods: 0, stones: 0, meadow: 0}
    vein_k: 0.4
    reach_k: 1.2
    swing_k: 0.8
    note: тёмная вода в снегу, парит на морозе
  - id: pressure_ridges
    ru: Торосы
    en: Pressure ridges
    biome: ice
    share: 10
    where: {slope: [0.3, 0.8], wet: [0.4, 0.9], high: [0.4, 0.9]}
    marks: {woods: 0, stones: 0, meadow: 0}
    vein_k: 0.6
    reach_k: 0.7
    swing_k: 1.0
    note: ломаные льдины стоят дыбом, обход длинный

  # ---------- cinder (чёрное поле, Пироксис) ----------
  - id: smooth_lava
    ru: Лавовая гладь
    en: Smooth lava
    biome: cinder
    share: 25
    where: {slope: [0.0, 0.2], wet: [0.0, 0.3], high: [0.2, 0.7]}
    marks: {woods: 0, stones: 90, meadow: 0}
    vein_k: 1.0
    reach_k: 1.4
    swing_k: 1.0
    note: застывшие складки, как чёрное тесто, идти ровно
  - id: clinker
    ru: Колючая лава
    en: Rough lava
    biome: cinder
    share: 25
    where: {slope: [0.1, 0.4], wet: [0.0, 0.2], high: [0.3, 0.9]}
    marks: {woods: 0, stones: 100, meadow: 0}
    vein_k: 1.2
    reach_k: 1.0
    swing_k: 1.1
    note: острые обломки режут подошву, идти вдвое медленнее
  - id: cinder_cone
    ru: Шлаковый конус
    en: Cinder cone
    biome: cinder
    share: 10
    where: {slope: [0.5, 0.9], wet: [0.0, 0.2], high: [0.7, 1.0]}
    marks: {woods: 0, stones: 90, meadow: 0}
    vein_k: 1.8
    reach_k: 1.8
    swing_k: 1.2
    note: конус рыжей и чёрной крошки, на макушке кратер
  - id: ash_flat
    ru: Пепельное поле
    en: Ash flat
    biome: cinder
    share: 15
    where: {slope: [0.0, 0.15], wet: [0.0, 0.3], high: [0.1, 0.5]}
    marks: {woods: 0, stones: 30, meadow: 0}
    vein_k: 0.8
    reach_k: 1.5
    swing_k: 1.2
    note: серая мелкая крошка по щиколотку, след держится долго
  - id: hot_ground
    ru: Паровые щели
    en: Steam vents
    biome: cinder
    share: 8
    where: {slope: [0.0, 0.3], wet: [0.2, 0.6], high: [0.3, 0.7]}
    marks: {woods: 0, stones: 60, meadow: 0}
    vein_k: 1.5
    reach_k: 0.8
    swing_k: 0.6
    note: из трещин идёт пар, камни тёплые, пахнет серой
  - id: collapse_trench
    ru: Провал
    en: Collapse pit
    biome: cinder
    share: 7
    where: {slope: [0.4, 1.0], wet: [0.0, 0.3], high: [0.0, 0.4]}
    marks: {woods: 0, stones: 100, meadow: 0}
    vein_k: 2.2
    reach_k: 0.6
    swing_k: 0.8
    note: рухнувший свод, внизу чёрный ход уходит в темноту
  - id: lava_basin
    ru: Лавовая котловина
    en: Lava basin
    biome: cinder
    share: 10
    where: {slope: [0.0, 0.2], wet: [0.5, 1.0], high: [0.0, 0.25]}
    marks: {woods: 0, stones: 50, meadow: 0}
    vein_k: 1.0
    reach_k: 1.2
    swing_k: 0.9
    note: чаша в лаве, на дне вода, вокруг соляная кайма
```

---

## Провинции

Поля: `rain_shift` — сдвиг осадков по шкале `site.rain_range` (где сушь, а где влага, — строки `biome.zonal`; болото — выше `biome.bounds.wet`); `temp_shift_c` — сдвиг средней температуры; `vein_k` — множитель к жиле; `favours` — фацеты, которые здесь встречаются чаще обычного.

```yaml
provinces:
  terra:
    - id: ore_ridge
      ru: Рудный кряж
      en: Ore Ridge
      rain_shift: -5
      temp_shift_c: -1
      vein_k: 1.8
      favours: [scree, crag]
      note: каждый второй шурф даёт цвет, зато дрова возят издалека
    - id: wet_ridge
      ru: Мокрая грива
      en: Wet Ridge
      rain_shift: 18
      temp_shift_c: 0
      vein_k: 0.8
      favours: [levee_ridge, willow_brake]
      note: единственная сухая дорога идёт по гребню, всё остальное — вода
    - id: salt_wedge
      ru: Солёный клин
      en: Salt Wedge
      rain_shift: -20
      temp_shift_c: 3
      vein_k: 0.9
      favours: [salt_flat, alkali_flat]
      note: колодцы горькие, лес не растёт, соль лежит под ногами
    - id: still_reach
      ru: Тихий плёс
      en: Still Reach
      rain_shift: 10
      temp_shift_c: 1
      vein_k: 0.6
      favours: [oxbow, water_meadow]
      note: река широкая и медленная, паводок раз в год стоит неделями
    - id: black_pinewood
      ru: Чёрный бор
      en: Black Pinewood
      rain_shift: 5
      temp_shift_c: -2
      vein_k: 1.0
      favours: [spruce_stand, pine_wood]
      note: сплошная тайга в три дня пути, тропу теряют даже свои
    - id: windy_rise
      ru: Ветреный увал
      en: Windy Rise
      rain_shift: -8
      temp_shift_c: -1
      vein_k: 1.2
      favours: [long_rise, stony_ground]
      note: ветер не стихает ни днём, ни ночью, крыши крепят камнями
    - id: rotten_lowland
      ru: Гнилая низина
      en: Rotten Lowland
      rain_shift: 22
      temp_shift_c: 1
      vein_k: 0.5
      favours: [quagmire, marsh_wood]
      note: гать гниёт за два года, дома ставят на сваях
    - id: dry_shore
      ru: Сухой берег
      en: Dry Shore
      rain_shift: -15
      temp_shift_c: 2
      vein_k: 0.8
      favours: [shingle, cliff]
      note: море есть, а пресной воды нет — её возят с гор
    - id: far_corner
      ru: Глухой угол
      en: Far Corner
      rain_shift: 8
      temp_shift_c: -1
      vein_k: 1.1
      favours: [thicket, alder_bottom]
      note: до ближайшего города два дня лесом, вести доходят последними
    - id: stone_gate
      ru: Каменные ворота
      en: Stone Gate
      rain_shift: 0
      temp_shift_c: -2
      vein_k: 1.6
      favours: [saddle, rock_face]
      note: единственный проход через хребет, зимой закрыт снегом
    - id: yellow_steppe
      ru: Жёлтая степь
      en: Yellow Steppe
      rain_shift: -12
      temp_shift_c: 2
      vein_k: 0.9
      favours: [feather_grass, liman]
      note: трава выгорает к середине лета, к лиманам сходятся все тропы
    - id: white_sands
      ru: Белые пески
      en: White Sands
      rain_shift: -25
      temp_shift_c: 4
      vein_k: 0.7
      favours: [dune, clay_pan]
      note: барханы идут на посёлок, каждый год откапывают ограды
    - id: alder_glen
      ru: Ольховая падь
      en: Alder Glen
      rain_shift: 15
      temp_shift_c: -1
      vein_k: 1.0
      favours: [glen, alder_bottom]
      note: узкая долина, солнце заходит в три часа дня
    - id: rust_hills
      ru: Рыжие холмы
      en: Rust Hills
      rain_shift: -6
      temp_shift_c: 1
      vein_k: 1.5
      favours: [hillside, bare_patch]
      note: земля красная от железа, вода в ручьях ржавая
    - id: long_spit
      ru: Долгая коса
      en: Long Spit
      rain_shift: 5
      temp_shift_c: 1
      vein_k: 0.5
      favours: [sandbar, lagoon]
      note: коса тянется на день пути, за ней тихая вода и тростник
    - id: burnt_hollow
      ru: Горелый лог
      en: Burnt Hollow
      rain_shift: -5
      temp_shift_c: 1
      vein_k: 1.0
      favours: [burn, glade]
      note: горит каждое сухое лето, кипрей до плеч
    - id: cold_spring
      ru: Студёный ключ
      en: Cold Spring
      rain_shift: 10
      temp_shift_c: -3
      vein_k: 1.1
      favours: [cirque, snowfield]
      note: вода в ключах ломит зубы даже в жару, снег лежит до июля
    - id: cranberry_moss
      ru: Клюквенная мшара
      en: Cranberry Moss
      rain_shift: 20
      temp_shift_c: -2
      vein_k: 0.5
      favours: [moss_bog, bog_ridge]
      note: клюкву берут вёдрами, зато ни камня, ни дров
    - id: oak_cape
      ru: Дубовый мыс
      en: Oak Cape
      rain_shift: 5
      temp_shift_c: 2
      vein_k: 0.8
      favours: [oak_stand, shore_wood]
      note: дубы у самой воды, брёвна спускают прямо с берега
    - id: warm_ravine
      ru: Тёплая балка
      en: Warm Ravine
      rain_shift: 3
      temp_shift_c: 3
      vein_k: 0.9
      favours: [ravine, grove_island]
      note: в балке нет ветра, огороды поспевают на две недели раньше
    - id: wormwood_plain
      ru: Полынная равнина
      en: Wormwood Plain
      rain_shift: -18
      temp_shift_c: 2
      vein_k: 1.0
      favours: [wormwood_flat, dry_lake]
      note: серо и горько во все стороны, дорогу держат по столбам
    - id: hummock_field
      ru: Кочкарное поле
      en: Hummock Field
      rain_shift: 5
      temp_shift_c: -5
      vein_k: 0.8
      favours: [hummocks, dwarf_scrub]
      note: пешком по кочкам не быстрее двух вёрст в час
    - id: blue_mountains
      ru: Синие горы
      en: Blue Mountains
      rain_shift: 5
      temp_shift_c: -4
      vein_k: 1.7
      favours: [crest, boulder_field]
      note: издали синие, вблизи — голый камень и ветер
    - id: crooked_shore
      ru: Кривой берег
      en: Crooked Shore
      rain_shift: 8
      temp_shift_c: 0
      vein_k: 0.7
      favours: [tidal_flat, sandy_shore]
      note: берег изрезан бухтами, до соседей по прямой ближе, чем по земле
    - id: gravel_ridge
      ru: Щебнистая гряда
      en: Gravel Ridge
      rain_shift: -10
      temp_shift_c: 0
      vein_k: 1.6
      favours: [stony_rise, rubble]
      note: щебень до горизонта, зато жилы ложатся близко к поверхности
    - id: rain_slope
      ru: Дождевой склон
      en: Rain Slope
      rain_shift: 25
      temp_shift_c: 2
      vein_k: 1.0
      favours: [jungle_bottom, jungle_scarp]
      note: дождь каждый день после полудня, обувь не сохнет
    - id: wet_wilds
      ru: Мокрые дебри
      en: Wet Wilds
      rain_shift: 22
      temp_shift_c: 3
      vein_k: 0.8
      favours: [jungle_thicket, jungle_gap]
      note: тропа зарастает за неделю, ходят с топором
    - id: hot_plain
      ru: Жаркая равнина
      en: Hot Plain
      rain_shift: -8
      temp_shift_c: 4
      vein_k: 1.0
      favours: [tall_grass, pan]
      note: жара к полудню такая, что работают только утром и вечером
    - id: goat_crag
      ru: Козий утёс
      en: Goat Crag
      rain_shift: 0
      temp_shift_c: -1
      vein_k: 1.4
      favours: [crag, scree]
      note: только козы держатся на этих склонах, тропы идут карнизами
    - id: willow_bottoms
      ru: Ивовая пойма
      en: Willow Bottoms
      rain_shift: 12
      temp_shift_c: 1
      vein_k: 0.6
      favours: [willow_brake, bottomland_wood]
      note: ивняк стоит стеной по обоим берегам, вода мутная и тёплая
    - id: bald_knolls
      ru: Лысые сопки
      en: Bald Knolls
      rain_shift: -5
      temp_shift_c: -2
      vein_k: 1.5
      favours: [bald_top, knoll]
      note: макушки голые, лес только по низам, зимой ветер сносит снег до земли
    - id: pine_sands
      ru: Сосновые пески
      en: Pine Sands
      rain_shift: -5
      temp_shift_c: 0
      vein_k: 0.9
      favours: [pine_wood, edge]
      note: сухой бор на песке, вода глубоко, зато грибы и брусника
    - id: flood_meadows
      ru: Заливные луга
      en: Flood Meadows
      rain_shift: 15
      temp_shift_c: 1
      vein_k: 0.5
      favours: [water_meadow, oxbow]
      note: травы столько, что косить не успевают, зато паводок сносит стога
    - id: grey_range
      ru: Седой хребет
      en: Grey Range
      rain_shift: 10
      temp_shift_c: -5
      vein_k: 1.8
      favours: [snowfield, rock_face]
      note: снег на гребне держится круглый год, тропы только через седловины
    - id: feather_grass_reach
      ru: Ковыльный край
      en: Feather-grass Reach
      rain_shift: -10
      temp_shift_c: 1
      vein_k: 0.8
      favours: [feather_grass, long_rise]
      note: степь без единого дерева, дрова везут за два дня
    - id: dark_spruce
      ru: Тёмный ельник
      en: Dark Spruce
      rain_shift: 12
      temp_shift_c: -3
      vein_k: 0.9
      favours: [spruce_stand, swamp_wood]
      note: солнце сквозь ели не проходит, мох по колено, путь держат по ручьям
    - id: lichen_flats
      ru: Ягельник
      en: Lichen Flats
      rain_shift: -5
      temp_shift_c: -6
      vein_k: 1.0
      favours: [moss_flat, frost_mound]
      note: ягель хрустит под ногой, летом мошка, зимой ни зги
    - id: dry_washes
      ru: Сухие русла
      en: Dry Washes
      rain_shift: -20
      temp_shift_c: 3
      vein_k: 1.2
      favours: [dry_wash, mesa]
      note: дождь раз в год, зато после него по руслам идёт вода стеной
    - id: dune_shore
      ru: Дюнный берег
      en: Dune Shore
      rain_shift: 3
      temp_shift_c: 0
      vein_k: 0.5
      favours: [dune_ridge, sandy_shore]
      note: песок засыпает всё, что не ходит, сосны в дюнах кривые
    - id: cold_glen
      ru: Стылая падь
      en: Cold Glen
      rain_shift: 5
      temp_shift_c: -4
      vein_k: 1.3
      favours: [glen, deadfall]
      note: холод стекает в долину, иней на траве в июле

  aurora:
    - id: white_level
      ru: Белая гладь
      en: White Level
      rain_shift: -5
      temp_shift_c: -2
      vein_k: 0.7
      favours: [wind_crust, deep_snow]
      note: ровно, как стол, на три дня пути, вешки — единственная примета
    - id: black_teeth
      ru: Чёрные зубья
      en: Black Teeth
      rain_shift: -10
      temp_shift_c: -3
      vein_k: 1.9
      favours: [black_boulders]
      note: чёрные валуны торчат из снега рядом, у их подножия единственный камень на планете
    - id: broken_ice
      ru: Рваный край
      en: Broken Edge
      rain_shift: 0
      temp_shift_c: 0
      vein_k: 0.8
      favours: [wind_crust, drift_ridges, pressure_ridges, crevasses]
      note: к полюсу снег рвётся о торосы шапки, путь втрое длиннее прямой
    - id: warm_lead
      ru: Туманная падь
      en: Misty Glen
      rain_shift: 15
      temp_shift_c: 4
      vein_k: 0.9
      favours: [frozen_hollow, deep_snow]
      note: теплее соседей: снег оседает, стоит морозный туман, в низинах — старый лёд
    - id: wind_ridge
      ru: Ветровой гребень
      en: Wind Ridge
      rain_shift: -15
      temp_shift_c: -5
      vein_k: 0.8
      favours: [drift_ridges, wind_crust]
      note: ветер несёт снег стеной, сугробы в рост, стоять нельзя
    - id: blue_rifts
      ru: Синие сугробы
      en: Blue Drifts
      rain_shift: 0
      temp_shift_c: -2
      vein_k: 1.1
      favours: [drift_ridges]
      note: в тени сугробы синие, между ними ветер выметает канавы до старого льда
    - id: still_basin
      ru: Тихая котловина
      en: Still Basin
      rain_shift: 5
      temp_shift_c: -6
      vein_k: 0.6
      favours: [frozen_hollow, deep_snow]
      note: ветра нет, зато самый лютый холод — воздух стекает и стоит
    - id: stone_edge
      ru: Каменный берег
      en: Stone Edge
      rain_shift: 5
      temp_shift_c: 2
      vein_k: 1.5
      favours: [black_boulders, wind_crust]
      note: снежное поле упирается в камень, тут ставят первые дома
    - id: loose_snows
      ru: Рыхлые снега
      en: Loose Snows
      rain_shift: 20
      temp_shift_c: 1
      vein_k: 0.5
      favours: [deep_snow]
      note: снег валит неделями, по пояс, дороги торят заново
    - id: ice_rampart
      ru: Высокий вал
      en: High Rampart
      rain_shift: -5
      temp_shift_c: -1
      vein_k: 1.0
      favours: [drift_ridges, pressure_ridges]
      note: гряда надувов в высоту дома тянется через всю область, к полюсу переходит в торосы
    - id: mirror_ice
      ru: Голая равнина
      en: Bare Plain
      rain_shift: -20
      temp_shift_c: -4
      vein_k: 1.2
      favours: [wind_crust]
      note: ветер сдувает снег до наста, блестит, как стекло, не устоять
    - id: melt_edge
      ru: Инейный дол
      en: Rime Dale
      rain_shift: 10
      temp_shift_c: 5
      vein_k: 0.9
      favours: [deep_snow, frozen_hollow]
      note: самый тёплый край: сырой воздух оседает инеем, к утру всё в корке

  pyroxis:
    - id: black_level
      ru: Чёрная гладь
      en: Black Level
      rain_shift: -10
      temp_shift_c: 1
      vein_k: 1.0
      favours: [smooth_lava]
      note: ровная чёрная корка на день пути, солнце печёт снизу
    - id: thorn_field
      ru: Колючее поле
      en: Thorn Field
      rain_shift: -5
      temp_shift_c: 0
      vein_k: 1.2
      favours: [clinker]
      note: обувь рвётся за неделю, по прямой идти нельзя
    - id: sulphur_springs
      ru: Серные ключи
      en: Sulphur Springs
      rain_shift: 5
      temp_shift_c: 4
      vein_k: 1.6
      favours: [hot_ground]
      note: пар и вонь, зато здесь единственное тепло на два дня пути
    - id: rust_cones
      ru: Рыжие конусы
      en: Rust Cones
      rain_shift: -10
      temp_shift_c: 2
      vein_k: 1.8
      favours: [cinder_cone, clinker]
      note: три десятка конусов в ряд, с каждого видно следующий
    - id: ash_lowland
      ru: Пепельная низина
      en: Ash Lowland
      rain_shift: 0
      temp_shift_c: 0
      vein_k: 0.7
      favours: [ash_flat]
      note: пепел по колено, ветер поднимает его стеной, дышат через тряпку
    - id: sunken_edge
      ru: Провальный край
      en: Sunken Edge
      rain_shift: -5
      temp_shift_c: -1
      vein_k: 2.0
      favours: [collapse_trench]
      note: земля проваливается под ногой в чёрные ходы, дорогу щупают
    - id: salt_bowls
      ru: Солёные чаши
      en: Salt Bowls
      rain_shift: 10
      temp_shift_c: 1
      vein_k: 0.9
      favours: [lava_basin]
      note: вода в котловинах горькая, зато единственная на два дня пути
    - id: hot_slope
      ru: Горячий склон
      en: Hot Slope
      rain_shift: -15
      temp_shift_c: 6
      vein_k: 1.5
      favours: [hot_ground, cinder_cone]
      note: камень тёплый круглые сутки, снег не ложится, спать можно на земле
    - id: cold_field
      ru: Стылое поле
      en: Cold Field
      rain_shift: 5
      temp_shift_c: -5
      vein_k: 0.8
      favours: [smooth_lava, ash_flat]
      note: старая лава давно остыла, ветер и мороз, ни пара, ни тепла
    - id: glass_bank
      ru: Стеклянный откос
      en: Glass Bank
      rain_shift: -10
      temp_shift_c: 0
      vein_k: 1.4
      favours: [smooth_lava, collapse_trench]
      note: лава застыла блестящей коркой, режет, как стекло, на солнце слепит
    - id: smoke_ridge
      ru: Дымная гряда
      en: Smoke Ridge
      rain_shift: 0
      temp_shift_c: 3
      vein_k: 1.7
      favours: [cinder_cone, hot_ground]
      note: над гребнем всегда дым, ночью видно красное
    - id: still_bowl
      ru: Тихая чаша
      en: Still Bowl
      rain_shift: 15
      temp_shift_c: -2
      vein_k: 0.6
      favours: [lava_basin, ash_flat]
      note: низина между конусами, ветра нет, пепел ложится ровно, как снег
```

---

## Другие регистры

Пять фацетов леса в двух других регистрах — чтобы выбрать регистр и переписать в нём остальное.

| Фацет (поселенческий) | Сухой промысловый | Старорусский географический |
|---|---|---|
| Чаща | Спелый лес | Раменье |
| Опушка | Кромка | Окраек |
| Ветровал | Валежник | Ломь |
| Гарь | Горельник | Пал |
| Ольшаник | Сырой участок | Суболоть |
