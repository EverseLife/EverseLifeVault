# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nurlan Urazkulov

"""Симуляция экономики: автотест баланса до того, как его проверят игроки.

    python tools/simulate.py              прогнать 30 дней, собрать отчёт
    python tools/simulate.py --days 60    другой горизонт
    python tools/simulate.py --seed 7     другой розыгрыш популяции

Что делает:
  1. Читает build/*.json — те же данные, что читает движок (D-065)
  2. Гоняет популяцию агентов по профилю из балансной модели: 60/30/10
  3. Каждый день агент выбирает занятие по доходу, работает, продаёт, ест
  4. Проверяет инварианты И1, И2, И3, И7 и три новые петли пятого круга
  5. Пишет 90-production/04-simulation.md

Чего НЕ делает и не будет: не проверяет, весело ли (это Э0, бумажные прототипы),
не моделирует политику и не даёт настоящих цен. Её задача одна — поймать
катастрофу до того, как её поймают игроки.

ВАЖНО про числа. Игровые величины берутся только из build/constants.json.
Всё, чего в реестре нет, вынесено в ASSUMPTIONS и в отчёте печатается отдельным
списком: это не баланс, а дыры в данных, которые симуляция и должна вскрывать.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
REPORT = ROOT / "90-production" / "04-simulation.md"

C = json.loads((BUILD / "constants.json").read_text(encoding="utf-8"))
LAWS = json.loads((BUILD / "laws.json").read_text(encoding="utf-8"))
RECIPES = json.loads((BUILD / "recipes.json").read_text(encoding="utf-8"))
BY_NAME = {r["name"]: r for r in RECIPES["recipes"]}


def qty(recipe: str, ingredient: str, fallback: float) -> float:
    """Количество входа — из данных, а не из головы (D-133)."""
    return BY_NAME.get(recipe, {}).get("amounts", {}).get(ingredient, fallback)


def op_qty(output: str, ingredient: str, fallback: float) -> float:
    """Сколько входа уходит в единицу продукта операции (D-141).

    До появления `consumes` у операций этого нельзя было спросить, и якорь
    подглядывал в состав рецепта «Сталь» — то есть мерил не то.
    """
    for op in RECIPES.get("operations", []):
        if output in op.get("gives", []):
            return op.get("amounts", {}).get(output, {}).get(ingredient, fallback)
    return fallback


def rate(raw: str, fallback: float) -> float:
    """Выход часа труда по сырью — из `harvest.rates`."""
    return C.get("harvest.rates", {}).get(raw, fallback)


def rng_between(spec, r: random.Random) -> float:
    """Константа-диапазон {min, max} -> число."""
    return r.uniform(spec["min"], spec["max"])


def law_default(law_id: str, fallback: float) -> float:
    for law in LAWS["code_laws"]:
        if law["id"] == law_id:
            try:
                return float(law.get("default", fallback))
            except (TypeError, ValueError):
                return fallback
    return fallback


# --------------------------------------------------------------- допущения
# Ни одно из этих чисел не лежит в реестре констант. Каждое — либо дыра в
# данных (помечено «ДЫРА»), либо чисто модельная величина, которой в игре
# нет и быть не должно (помечено «модель»).

ASSUMPTIONS: dict[str, tuple[float, str]] = {
    "farm.plot_area": (
        100, "Из примера в 06-farming: сотня метров на три делянки"),
    "price.ore_anchor": (
        1.5, "Якорь из 02-proof-of-work: расчёт удара по своду идёт при 1,5 ТК"),
    "city.built_area_per_agent": (
        15, "модель: сколько метров застройки приходится на жителя — с них город "
            "берёт земельный налог"),
    "city.own_area": (
        600, "модель: застройка самого города — ратуша, суд, библиотека, станция"),
    "city.own_nodes": (
        8, "модель: сколько узлов принадлежит городу. Содержание растёт нелинейно"),
    "city.surplus_spend_share": (
        50, "модель: какую долю излишка город вкладывает в дороги за сутки"),
    "city.officials": (
        4, "модель: должностей на жалованье — смотритель, мудрец, энергетик, судья"),
    "agro.capital_cost": (
        3000, "ДЫРА: цена полевого автомата не выводится, пока постройки считаются "
              "формулой, а не рецептом"),
    "market.elasticity": (
        0.35, "модель: скорость сползания цены к равновесию"),
    "market.max_move": (
        15, "модель: потолок дневного хода цены, % — иначе рынок звенит"),
    "agent.switch_threshold": (
        30, "модель: насколько выгоднее должно быть, чтобы сменить занятие, %"),
    "agent.reconsider_share": (
        20, "модель: доля популяции, пересматривающая занятие за день"),
    "agent.unknown_discount": (
        50, "модель: со скидкой оценивается занятие, о котором спросить некого"),
    "agent.warmup_days": (
        5, "модель: сколько дней никто не меняет занятие. Без разгона цепочка "
           "переделов не успевает завестись — та самая проблема холодного старта"),
    "market.fill_memory": (
        0.2, "модель: с какой скоростью агент забывает вчерашний срыв поставки"),
    "market.price_memory": (
        0.15, "модель: агент решает по цене, усреднённой примерно за неделю"),
    "market.no_trade_move": (
        3, "модель: потолок роста цены товара, которым ни разу не торговали, %"),
    "agent.start_money": (
        60, "модель: стартовый кошелёк, чтобы первый день вообще состоялся"),
    "agent.population": (
        200, "модель: размер популяции"),
    "sink.ingot_per_agent_day": (
        1.0, "модель: содержание построек и снаряжения — то, чего первая версия "
             "не считает подробно. Без этого стока металл некому потреблять, "
             "и вся ветка добычи схлопывается в ноль"),
}


def A(key: str) -> float:
    return ASSUMPTIONS[key][0]


# ------------------------------------------------------------------- товары

RAW = ["Руда", "Уголь", "Зерно", "Овощи", "Дерево"]
MADE = ["Слиток", "Кирка", "Мука", "Хлеб", "Похлёбка"]
GOODS = RAW + MADE
FOOD = ["Хлеб", "Похлёбка"]      # готовое: сытнее, но портится вчетверо быстрее
FOOD_RAW = ["Овощи"]             # сырое: репа с грядки. Голодным не оставит
QUALITY_COOKED = 55.0            # выше cook.hot_quality_min — даёт сытость
QUALITY_RAW = 25.0               # ниже: просто еда
POWERED = {"кузнец", "мельник"}  # чьи станции берут энергию из пула (D-135)

# Стартовые цены: считаются от якоря руды по трудоёмкости, а не назначаются.
# Час труда должен стоить примерно одинаково — это И2, и симуляция проверит,
# удержится ли равенство, когда цены поедут.
LABOR = RECIPES.get("labor_hours", {})
SIM_TO_LADDER = {"Слиток": "Сталь", "Кирка": "Железная кирка"}


def labor_of(good: str) -> float:
    """Часов труда в единице — из `build/recipes.json` (D-133)."""
    return LABOR.get(SIM_TO_LADDER.get(good, good), 0.0)


def seed_prices() -> dict[str, float]:
    """Цена = труд × стоимость часа. Не выдумывается, а берётся из лестницы.

    Якорь: час добычи даёт `mining.iron_per_hour` руды по `price.ore_anchor`,
    значит час труда стоит столько-то ТК. Всё остальное — трудоёмкость,
    посчитанная сборкой, умноженная на цену часа. Так стартовая точка
    согласована с лестницей по построению, а не подобрана.
    """
    ore = A("price.ore_anchor")
    hour = C["mining.iron_per_hour"] * ore
    p = {}
    for g in GOODS:
        h = labor_of(g)
        p[g] = round(h * hour, 3) if h > 0 else ore
    return p


# ------------------------------------------------------------------- рынок

class Market:
    """Один стакан на мир: заявки сводятся, деньги переходят от покупателя.

    Два упрощения, о которых честнее сказать, чем изобразить: рынок один на
    мир, хотя в игре они локальные (D-003), и цена одна на товар, без стакана
    по ступеням качества.

    Главное свойство модели — **деньги не берутся из воздуха**. Продавец
    получает ровно то, что заплатил покупатель, минус налог с продажи (D-127)
    и комиссия рынка. Налог уходит в казну и в обороте больше не участвует.
    """

    def __init__(self) -> None:
        self.price = seed_prices()
        # цена, по которой агент принимает решение: он помнит неделю, а не
        # вчерашний день. Без этого популяция раскачивается — все уходят из
        # занятия на дне цены и возвращаются на пике
        self.memory = dict(self.price)
        self.offers: dict[str, list[tuple]] = {g: [] for g in GOODS}
        self.wants: dict[str, list[tuple]] = {g: [] for g in GOODS}
        self.traded: dict[str, float] = {g: 0.0 for g in GOODS}
        # доля исполнения заявок: сколько из желаемого удалось купить и продать.
        # Без неё агенты гонятся за маржой, которую физически не реализовать —
        # первый прогон показал, как 198 из 200 уходят в повара при пустых амбарах
        self.fill_buy: dict[str, float] = {g: 1.0 for g in GOODS}
        self.fill_sell: dict[str, float] = {g: 1.0 for g in GOODS}
        self.tax_trade = law_default("tax_trade", 3) / 100
        self.fee = C["market.default_fee"] / 100
        self.treasury = 0.0
        self.builders_last = 1

    def offer(self, agent, good: str, qty: float) -> None:
        if qty > 0:
            self.offers[good].append((agent, qty))

    def want(self, agent, good: str, qty: float) -> None:
        if qty > 0:
            self.wants[good].append((agent, qty))

    def clear(self) -> None:
        """Сводит заявки, проводит деньги и товар, потом двигает цену."""
        elast = A("market.elasticity")
        cap = A("market.max_move") / 100
        for g in GOODS:
            supply = sum(q for _, q in self.offers[g])
            demand = sum(q for _, q in self.wants[g])
            price = self.price[g]

            # покупатель ограничен ещё и кошельком — это отдельный ограничитель
            budget_qty = 0.0
            for a, q in self.wants[g]:
                budget_qty += min(q, a.money / price if price > 0 else 0)
            demand_eff = min(demand, budget_qty)

            traded = min(supply, demand_eff)
            self.traded[g] = traded
            fill_sell = traded / supply if supply > 0 else 1.0
            fill_buy = traded / demand if demand > 0 else 1.0
            # сглаживаем: разовый провал не должен обрушивать ожидания
            k = A("market.fill_memory")
            self.fill_sell[g] = (1 - k) * self.fill_sell[g] + k * fill_sell
            self.fill_buy[g] = (1 - k) * self.fill_buy[g] + k * fill_buy

            for a, q in self.offers[g]:
                sold = q * fill_sell
                a.inv[g] -= sold
                a.sold[g] = sold
                revenue = sold * price * (1 - self.tax_trade - self.fee)
                a.money += revenue
                a.income_today += revenue
                self.treasury += sold * price * self.tax_trade
            for a, q in self.wants[g]:
                afford = min(q, a.money / price if price > 0 else 0)
                bought = afford * fill_buy
                cost = bought * price
                if cost > a.money:
                    bought = a.money / price if price > 0 else 0
                    cost = a.money
                a.money -= cost
                a.inv[g] += bought

            # цену двигает платёжеспособный спрос, а не желание: иначе товар,
            # который никто не может купить, дорожает до бесконечности
            if supply + demand_eff > 0:
                move = elast * (demand_eff - supply) / (supply + demand_eff)
                move = max(-cap, min(cap, move))
                # пустой стакан — это не цена, а её отсутствие. Товар, которым
                # ни разу не торговали, не имеет права дорожать без предела
                if traded <= 0:
                    move = min(move, A("market.no_trade_move") / 100)
                self.price[g] = max(0.01, price * (1 + move))
            k = A("market.price_memory")
            self.memory[g] = (1 - k) * self.memory[g] + k * self.price[g]

        self.offers = {g: [] for g in GOODS}
        self.wants = {g: [] for g in GOODS}


# ------------------------------------------------------------------- казна

class Treasury:
    """Город: собирает налоги и тратит их через людей (D-127).

    Ведёт себя на рынке как обычный покупатель — у него есть кошелёк и склад,
    и уголь для станции он **покупает у игроков**, а не создаёт. Это и делает
    его крупнейшим потребителем топлива в мире.
    """

    def __init__(self) -> None:
        self.money = 0.0
        self.inv: dict[str, float] = {g: 0.0 for g in GOODS}
        self.income_today = 0.0
        self.tax_land = law_default("tax_land", 0.2)
        self.salary = law_default("salary", 0)
        self.log: list[dict] = []
        self.dry_days = 0
        self.repair_done = 0.0

    def energy_bill(self, a: "Agent") -> float:
        """Счёт по счётчику: быт с метра плюс работа станций (D-135)."""
        area = A("city.built_area_per_agent")
        home = C["energy.home_draw_per_m2"] * area * C["energy.meter_period"]
        stations = C["energy.auto_bench_draw"] * a.hours if a.job in POWERED else 0.0
        return (home + stations) * C["energy.tariff_default"] / 100

    def order_repairs(self, m: Market) -> None:
        """Ремонт — это заказ людям, а не списание (D-134).

        Город покупает материалы на рынке и откладывает деньги на оплату труда
        тех, кто чинит. Нет исполнителей — ремонт не выполнен, даже если казна
        полна: город без людей разваливается при любом золоте.
        """
        need = (C["build.upkeep_per_area"] * A("city.own_area")
                * C["upkeep.materials_share"] / 100 / 100)
        m.want(self, "Слиток", need)
        m.want(self, "Дерево", need * 2)

    def day(self, agents: list[Agent], m: Market, trade_tax: float,
            materials: float = 0.0) -> None:
        # доход: налог с продаж (собран рынком), земельный и счета за энергию
        land = self.tax_land * A("city.built_area_per_agent") * len(agents)
        power = 0.0
        for a in agents:
            bill = self.energy_bill(a)
            paid = min(a.money, bill)
            a.money -= paid
            power += paid
        self.money += land + power

        # расход: содержание городских построек, нелинейно от их числа (D-106).
        # Часть уходит людям как плата за ремонт, часть — в материалы, которые
        # город уже купил на рынке
        nodes = A("city.own_nodes")
        upkeep = (C["build.upkeep_per_area"] * A("city.own_area")
                  * nodes ** C["upkeep.territory_exponent"] / nodes)
        labor = upkeep * C["upkeep.labor_share"] / 100
        builders = [a for a in agents if a.job == "строитель"]
        wages = self.salary * A("city.officials")
        spend = labor + wages
        paid = min(self.money, spend)
        self.money -= paid
        # зарплату получают те, кто вышел чинить
        if builders and paid > wages:
            share = (paid - wages) / len(builders)
            for a in builders:
                a.money += share
                a.income_today += share
        self.repair_done = 1.0 if builders else 0.0

        invested = 0.0

        # излишек уходит в развитие — по умолчанию в дороги (устав `surplus_use`,
        # D-134). Это не благотворительность: деньги, собранные налогами и
        # счетами за энергию, обязаны вернуться в оборот, иначе казна работает
        # насосом и высушивает экономику досуха
        reserve = spend * 3
        surplus = max(0.0, self.money - reserve)
        if surplus > 0 and builders:
            invest = surplus * A("city.surplus_spend_share") / 100
            self.money -= invest
            share = invest / len(builders)
            for a in builders:
                a.money += share
                a.income_today += share
            invested = invest
        else:
            invested = 0.0

        self.log.append({
            "с продаж": trade_tax,
            "земельный": land,
            "энергия": power,
            "материалы": materials,
            "содержание": upkeep,
            "жалованье": wages,
            "развитие": invested,
            "недоплачено": spend - paid,
            "остаток": self.money,
        })
        if spend - paid > 0.01:
            self.dry_days += 1

    def burn_fuel(self) -> float:
        """Станция сжигает купленное. Не хватило — город сидит без энергии."""
        need = C["energy.coal_plant_fuel_draw"] * 24
        got = min(self.inv["Уголь"], need)
        self.inv["Уголь"] -= got
        return got / need if need else 1.0


# ------------------------------------------------------------------ агенты

PROFILE = [
    ("казуальный", 0.60, (0.5, 1.0)),
    ("регулярный", 0.30, (2.0, 3.0)),
    ("хардкорный", 0.10, (5.0, 7.0)),
]

JOBS = ["шахтёр", "угольщик", "кузнец", "мельник", "фермер", "повар", "строитель"]


@dataclass
class Agent:
    id: int
    profile: str
    hours: float
    r: random.Random
    money: float = 0.0
    job: str = "шахтёр"
    inv: dict[str, float] = field(default_factory=lambda: {g: 0.0 for g in GOODS})
    tool_wear: float = 0.0          # % износа кирки
    has_tool: bool = False
    stamina: float = 0.0
    land: float = 0.0               # м² делянок у фермера
    fertility: float = 100.0
    growing: float = 0.0            # дней до сбора
    has_agro: bool = False          # полевой автомат
    meals: list[str] = field(default_factory=list)
    income_today: float = 0.0
    hungry_days: int = 0
    sold: dict[str, float] = field(default_factory=lambda: {g: 0.0 for g in GOODS})

    def limit(self, good: str, want: float, m: "Market") -> float:
        """Выпуск режут тогда, и только тогда, когда товар не разошёлся.

        Первая версия ограничивала выпуск вчерашней продажей всегда — и это
        оказалось храповиком: при нехватке еды повара делали девять порций на
        триста пятьдесят едоков, потому что вчера продали мало. Живой человек
        поступает иначе: разобрали всё — работаю на полную.
        """
        if m.fill_sell[good] > 0.9:
            return want
        room = max(self.sold[good] * 1.25, want * 0.3)
        return max(0.0, min(want, room - self.inv[good]))

    def drain(self) -> float:
        """Расход выносливости за час: темп выбирает игрок (D-091)."""
        base = {"казуальный": 0.35, "регулярный": 0.55, "хардкорный": 0.8}[self.profile]
        lo, hi = C["body.drain_rate"]["min"], C["body.drain_rate"]["max"]
        return lo + (hi - lo) * base


# ------------------------------------------------------------------- работа
# Каждая функция возвращает, сколько чего произведено за час труда.

def expected_income(job: str, m: Market, a: Agent) -> float:
    """Сколько ТК в час сулит занятие при вчерашних ценах.

    Маржа умножается на **доступность входов и сбыт**: нельзя заработать на
    разнице цен, если сырья нет в продаже, а готовое некому продать. Без этого
    агенты уходят в самую маржинальную профессию и стоят там без дела.
    """
    p, buy, sell = m.memory, m.fill_buy, m.fill_sell
    per_hour = 60 / C["craft.time_per_unit"]
    waste = 1 - C["craft.waste_share"] / 100

    if job in ("шахтёр", "угольщик"):
        if not a.has_tool and a.money < p["Кирка"]:
            return 0.0
        per_hour_mined = C["mining.iron_per_hour"] if job == "шахтёр" else rate("Уголь", 60)
        good = "Руда" if job == "шахтёр" else "Уголь"
        return per_hour_mined * p[good] * sell[good]
    if job == "кузнец":
        cost = p["Руда"] * qty("Сталь", "Слиток железа", 3) + p["Уголь"] * qty("Сталь", "Уголь", 5)
        avail = min(buy["Руда"], buy["Уголь"])
        return per_hour * (p["Слиток"] - cost) * waste * avail * sell["Слиток"]
    if job == "мельник":
        margin = p["Мука"] - p["Зерно"] * qty("Мука", "Зерно", 10)
        return per_hour * margin * waste * buy["Зерно"] * sell["Мука"]
    if job == "повар":
        bread = (p["Хлеб"] - p["Мука"] * qty("Хлеб", "Мука", 1)) * buy["Мука"] * sell["Хлеб"]
        stew = (p["Похлёбка"] - p["Овощи"] * qty("Похлёбка", "Овощи", 4)) * buy["Овощи"] * sell["Похлёбка"]
        return per_hour * max(bread, stew) * waste
    if job == "строитель":
        # платит город: доля содержания, делённая на тех, кто вышел чинить
        pot = (C["build.upkeep_per_area"] * A("city.own_area")
               * C["upkeep.labor_share"] / 100)
        others = max(1, m.builders_last)
        return pot / others / max(a.hours, 0.5)
    if job == "фермер":
        area = a.land or A("farm.plot_area")
        cycle = C["farm.cycle_days"]
        total = area * C["farm.yield_per_m2"]
        revenue = total / 2 * (p["Зерно"] * sell["Зерно"] + p["Овощи"] * sell["Овощи"])
        care_hours = (3 * C["farm.plot_overhead"] + C["farm.care_time_per_m2"] * area) / 60
        return revenue / max(care_hours * cycle, 0.1)
    return 0.0


def work(a: Agent, m: Market, hours: float, log: dict) -> None:
    """Час труда превращается в товар. Всё, что произведено, идёт на рынок."""
    job = a.job
    if job in ("шахтёр", "угольщик"):
        if not a.has_tool:
            return
        per_hour_mined = C["mining.iron_per_hour"] if job == "шахтёр" else rate("Уголь", 60)
        good = "Руда" if job == "шахтёр" else "Уголь"
        a.inv[good] += per_hour_mined * hours
        log["добыто"][good] = log["добыто"].get(good, 0) + per_hour_mined * hours
        a.tool_wear += C["wear.tool_per_session"]
        if a.tool_wear >= 100:
            a.has_tool, a.tool_wear = False, 0.0
            log["сломано инструментов"] += 1
    elif job in ("кузнец", "мельник", "повар"):
        per_hour = (60 / C["craft.time_per_unit"]) * hours
        waste = 1 - C["craft.waste_share"] / 100
        if job == "кузнец":
            ore = qty("Сталь", "Слиток железа", 3)
            coal = qty("Сталь", "Уголь", 5)
            can = min(a.inv["Руда"] // ore, a.inv["Уголь"] // coal, per_hour,
                      a.limit("Слиток", per_hour, m))
            a.inv["Руда"] -= can * ore
            a.inv["Уголь"] -= can * coal
            made = can * waste
            # часть слитков сразу в кирки — инструмент нужен всем
            picks = min(made // qty("Железная кирка", "Слиток железа", 4), per_hour / 4)
            made -= picks * qty("Железная кирка", "Слиток железа", 4)
            a.inv["Слиток"] += made
            a.inv["Кирка"] += picks
            log["сделано"]["Слиток"] = log["сделано"].get("Слиток", 0) + made
            log["сделано"]["Кирка"] = log["сделано"].get("Кирка", 0) + picks
        elif job == "мельник":
            can = min(a.inv["Зерно"] // qty("Мука", "Зерно", 10), per_hour,
                      a.limit("Мука", per_hour, m))
            a.inv["Зерно"] -= can * qty("Мука", "Зерно", 10)
            a.inv["Мука"] += can * waste
            log["сделано"]["Мука"] = log["сделано"].get("Мука", 0) + can * waste
        else:
            bread = min(a.inv["Мука"] // qty("Хлеб", "Мука", 1), per_hour / 2,
                        a.limit("Хлеб", per_hour / 2, m))
            a.inv["Мука"] -= bread * qty("Хлеб", "Мука", 1)
            a.inv["Хлеб"] += bread * waste
            stew = min(a.inv["Овощи"] // qty("Похлёбка", "Овощи", 4), per_hour / 2,
                       a.limit("Похлёбка", per_hour / 2, m))
            a.inv["Овощи"] -= stew * qty("Похлёбка", "Овощи", 4)
            a.inv["Похлёбка"] += stew * waste
            log["сделано"]["Хлеб"] = log["сделано"].get("Хлеб", 0) + bread * waste
            log["сделано"]["Похлёбка"] = log["сделано"].get("Похлёбка", 0) + stew * waste
    elif job == "фермер":
        farm_day(a, hours, log)
    elif job == "строитель":
        pass  # результат его труда — исправные здания, а не товар на складе


def farm_day(a: Agent, hours: float, log: dict) -> None:
    """Делянки: уход присутственный, рост офлайн (D-118)."""
    if a.land == 0:
        a.land = A("farm.plot_area")
        a.growing = C["farm.cycle_days"]
    area = a.land
    need = (3 * C["farm.plot_overhead"] + C["farm.care_time_per_m2"] * area) / 60
    care = min(1.0, hours / need) if need > 0 else 1.0
    a.growing -= 1
    if a.growing <= 0:
        neglect = (1 - care) * C["farm.neglect_penalty"] / 100
        fert = a.fertility / 100
        total = area * C["farm.yield_per_m2"] * fert * (1 - neglect)
        if a.has_agro:
            total *= C["agro.yield_share"] / 100
        a.inv["Зерно"] += total / 2
        a.inv["Овощи"] += total / 2
        log["выращено"] += total
        a.growing = C["farm.cycle_days"]
        # севооборот: каждый третий цикл под бобами, иначе истощение
        a.fertility = min(100, a.fertility - C["farm.soil_depletion"]
                          + C["farm.legume_recovery"] / 3)


def restore_per_meal(a: Agent, quality: float) -> float:
    """Сколько выносливости даёт один приём: качество плюс разнообразие (D-105, D-121)."""
    lo, hi = C["food.restore_by_quality"]["min"], C["food.restore_by_quality"]["max"]
    per_meal = C["body.food_restore"] * (lo + (hi - lo) * quality / 100)
    kinds = len(set(a.meals[-C["food.variety_window"]:]))
    if kinds >= C["food.variety_min_kinds"]:
        per_meal *= 1 + C["body.diet_variety_bonus"] / 100
    return per_meal


def eat(a: Agent, m: Market, spent_hours: float, log: dict) -> None:
    """Еда восполняет выносливость мгновенно (D-091), качество решает сколько.

    Сначала едят готовое — оно сытнее и даёт сытость (D-119). Не хватило —
    грызут сырые овощи: голод от бедности в игре невозможен по замыслу (D-121).
    """
    need_stamina = spent_hours * a.drain()
    got_stamina = 0.0
    for good, quality in [(g, QUALITY_COOKED) for g in FOOD] + \
                         [(g, QUALITY_RAW) for g in FOOD_RAW]:
        if got_stamina >= need_stamina:
            break
        per_meal = restore_per_meal(a, quality)
        meals_left = (need_stamina - got_stamina) / per_meal
        take = min(a.inv[good], meals_left)
        if take > 0:
            a.inv[good] -= take
            a.meals.extend([good] * max(1, int(take)))
            got_stamina += take * per_meal
            log["съедено"] += take
    if got_stamina < need_stamina * 0.9:
        a.hungry_days += 1
        log["голодных дней"] += 1
    else:
        a.hungry_days = 0


def spoil(a: Agent) -> None:
    """Порча: готовое портится в cook.spoilage_multiplier быстрее сырья (D-119)."""
    base = C["spoilage.food_base"] / 100
    for good in FOOD:
        a.inv[good] *= 1 - base * C["cook.spoilage_multiplier"]
    for good in ("Зерно", "Овощи"):
        a.inv[good] *= 1 - base


# --------------------------------------------------------------------- мир

def run(days: int, seed: int) -> dict:
    r = random.Random(seed)
    agents: list[Agent] = []
    n = int(A("agent.population"))
    idx = 0
    for name, share, (lo, hi) in PROFILE:
        for _ in range(int(n * share)):
            a = Agent(id=idx, profile=name, hours=r.uniform(lo, hi), r=r)
            a.job = JOBS[idx % len(JOBS)]
            a.money = A("agent.start_money")
            a.has_tool = True
            agents.append(a)
            idx += 1

    m = Market()
    city = Treasury()
    daily = []
    stock_hist = []
    observed: dict[str, float] = {j: 0.0 for j in JOBS}       # вчерашний доход в час
    observed_workers: dict[str, int] = {j: 0 for j in JOBS}

    for day in range(1, days + 1):
        log = {"добыто": {}, "сделано": {}, "выращено": 0.0, "съедено": 0.0,
               "голодных дней": 0, "сломано инструментов": 0,
               "ушло в содержание": 0.0}
        incomes: dict[str, list[float]] = {j: [] for j in JOBS}

        # 1. выбор занятия: пересматривает не вся популяция разом, а часть.
        #    Иначе рынок звенит — все уходят в одно занятие и возвращаются.
        #
        #    Смотрят при этом на **наблюдаемый доход соседей**, а не на
        #    теоретическую маржу: человек спрашивает знакомого, сколько тот
        #    заработал, и видит, что у ста пекарей выручки нет. Теоретическая
        #    оценка идёт со скидкой и только для пустующих занятий — иначе
        #    популяция сваливается в монокультуру, что и показали прогоны.
        def attractiveness(j: str, a: Agent) -> float:
            if observed_workers.get(j, 0) >= 3:
                return observed[j]
            return expected_income(j, m, a) * A("agent.unknown_discount") / 100

        for a in agents:
            if day <= A("agent.warmup_days"):
                break
            # голодный идёт сажать репу, не глядя на прибыльность. Без этого
            # правила популяция уходит в самую денежную профессию и вымирает
            # с голоду при полных кошельках — так и вышло в прогоне с металлом
            if a.hungry_days > 0:
                # идёт туда, где цепочка провисла: зерно гниёт — молоть,
                # мука лежит — печь, ничего нет — пахать
                grain = sum(x.inv["Зерно"] for x in agents)
                flour = sum(x.inv["Мука"] for x in agents)
                if flour > len(agents) / 2:
                    a.job = "повар"
                elif grain > len(agents) / 2:
                    a.job = "мельник"
                else:
                    a.job = "фермер"
                a.hungry_days = 0
                continue
            if r.random() > A("agent.reconsider_share") / 100:
                continue
            best = max(JOBS, key=lambda j: attractiveness(j, a))
            if best != a.job:
                gain, cur = attractiveness(best, a), attractiveness(a.job, a)
                if cur <= 0 or gain > cur * (1 + A("agent.switch_threshold") / 100):
                    if a.job == "фермер":
                        a.land = 0.0   # землю бросил, цикл начнётся заново
                    a.job = best

        # 2. труд
        for a in agents:
            a.income_today = 0.0
            if not a.has_tool and a.job in ("шахтёр", "угольщик"):
                if a.money >= m.price["Кирка"] * 1.1:
                    m.want(a, "Кирка", 1)      # купит на клиринге
                else:
                    a.job = "фермер"           # на кирку не хватает — в поле
            work(a, m, a.hours, log)

        # 3. заявки: продаём излишек, покупаем входы и еду
        for a in agents:
            for g in GOODS:
                keep = 2.0 if g in FOOD else 0.0
                if g == "Кирка" and a.job != "кузнец":
                    keep = 0.0
                if a.inv[g] > keep:
                    m.offer(a, g, a.inv[g] - keep)
            per_hour = 60 / C["craft.time_per_unit"]
            if a.job == "кузнец":
                m.want(a, "Руда", per_hour * a.hours * qty("Сталь", "Слиток железа", 3))
                m.want(a, "Уголь", per_hour * a.hours * qty("Сталь", "Уголь", 5))
            if a.job == "мельник":
                m.want(a, "Зерно", per_hour * a.hours * qty("Мука", "Зерно", 10))
            if a.job == "повар":
                m.want(a, "Мука", per_hour * a.hours / 2)
                m.want(a, "Овощи", per_hour * a.hours / 2 * qty("Похлёбка", "Овощи", 4))
            # еда: сколько приёмов нужно, чтобы закрыть сегодняшний расход
            need = a.hours * a.drain() / restore_per_meal(a, QUALITY_COOKED)
            for g in FOOD:
                m.want(a, g, max(0.0, need - a.inv[g]))
            # и подстраховка сырым: репа с грядки закрывает всю потребность,
            # если готового не досталось. Голода от бедности быть не должно (D-121)
            m.want(a, "Овощи", max(0.0, need - a.inv["Овощи"]))
            # содержание построек и снаряжения: сток металла, который первая
            # версия не считает подробно, но без которого его некому потреблять
            m.want(a, "Слиток", A("sink.ingot_per_agent_day"))

        m.builders_last = sum(1 for a in agents if a.job == "строитель")
        # город — такой же покупатель: топливо для станции он покупает у игроков
        trade_tax = m.treasury
        city.money += trade_tax
        m.treasury = 0.0
        money_before_market = city.money
        m.want(city, "Уголь", C["energy.coal_plant_fuel_draw"] * 24)
        city.order_repairs(m)

        m.clear()

        # 4. кирка, если купил; еда; порча
        for a in agents:
            if not a.has_tool and a.inv["Кирка"] >= 1:
                a.inv["Кирка"] -= 1
                a.has_tool = True
                a.tool_wear = 0.0
            # купленный слиток уходит в содержание — из мира он вышел
            spent = min(a.inv["Слиток"], A("sink.ingot_per_agent_day"))
            a.inv["Слиток"] -= spent
            log["ушло в содержание"] += spent
            eat(a, m, a.hours, log)
            spoil(a)
            if a.hours > 0:
                incomes[a.job].append(a.income_today / a.hours)

        plant = city.burn_fuel()
        city.inv["Слиток"] = 0.0   # ушло в ремонт
        city.inv["Дерево"] = 0.0
        city.day(agents, m, trade_tax, max(0.0, money_before_market - city.money))

        # что увидят соседи завтра
        for j in JOBS:
            vals = incomes[j]
            observed_workers[j] = len(vals)
            observed[j] = statistics.mean(vals) if vals else 0.0

        stock = {g: sum(x.inv[g] for x in agents) for g in GOODS}
        stock_hist.append(stock)
        daily.append({
            "день": day,
            "цены": dict(m.price),
            "доход": {j: (statistics.mean(v) if v else 0.0) for j, v in incomes.items()},
            "занятость": {j: sum(1 for a in agents if a.job == j) for j in JOBS},
            "лог": log,
            "запас": stock,
            "деньги": sum(a.money for a in agents),
            "казна": city.money,
            "станция": plant,
        })

    return {"дни": daily, "агенты": agents, "рынок": m, "запасы": stock_hist,
            "казна": city}


def buy_input(a: Agent, m: Market, good: str, qty: float) -> None:
    cost = m.price[good] * qty
    if cost <= a.money:
        a.money -= cost
        a.inv[good] += qty
    elif a.money > 0:
        got = a.money / m.price[good]
        a.inv[good] += got
        a.money = 0.0


# --------------------------------------------------------------- инварианты

def check(res: dict) -> list[dict]:
    days = res["дни"]
    last7 = days[-7:]
    out = []

    # И2: доход в час по профессиям в пределах ±30%
    incomes = {j: statistics.mean([d["доход"][j] for d in last7 if d["доход"][j] > 0] or [0])
               for j in JOBS}
    live = {j: v for j, v in incomes.items() if v > 0}
    if len(live) >= 2:
        med = statistics.median(live.values())
        worst = min(live, key=lambda j: live[j])
        best = max(live, key=lambda j: live[j])
        spread = (live[best] - live[worst]) / med if med else 0
        out.append({
            "id": "И2", "что": "Час труда равен по доходу между профессиями, ±30%",
            "ок": spread <= 0.6,
            "факт": f"разброс {spread*100:.0f}% — «{best}» {live[best]:.1f} ТК/ч против «{worst}» {live[worst]:.1f}",
            "ручка": "цены переделов, farm.yield_per_m2, mining.*_per_hour",
        })

    # И1: приток ≈ отток — запас не должен расти неделя за неделей
    grow = []
    for g in GOODS:
        a = res["запасы"][-8][g] if len(res["запасы"]) > 8 else res["запасы"][0][g]
        b = res["запасы"][-1][g]
        if a > 1:
            grow.append((g, (b - a) / a))
    bad = [(g, x) for g, x in grow if x > 0.5]
    out.append({
        "id": "И1", "что": "Приток ≈ отток на горизонте недели",
        "ок": not bad,
        "факт": ("накопления нет" if not bad else
                 ", ".join(f"{g} +{x*100:.0f}% за неделю" for g, x in bad[:4])),
        "ручка": "стоки: wear.*, spoilage.*, craft.waste_share",
    })

    # И7: новичок окупается за ≤2 часа
    price = days[-1]["цены"]
    newbie_hour = C["mining.iron_per_hour"] * price["Руда"]
    day_food = 2 * price["Хлеб"]
    hours_to_pick = price["Кирка"] / newbie_hour if newbie_hour else 999
    out.append({
        "id": "И7", "что": "Новичок выходит на самоокупаемость за ≤2 часа",
        "ок": hours_to_pick <= 2,
        "факт": f"кирка стоит {hours_to_pick:.1f} ч добычи, дневная еда — {day_food/max(newbie_hour,0.01):.1f} ч",
        "ручка": "цена инструмента через recipe.*, mining.iron_per_hour",
    })

    # Расслоение еды (D-121): дешёвая еда должна быть дешёвой
    # считаем по трудоёмкости, а не по смоделированной цене: арифметике
    # верить можно, а рыночной части модели — только как сигналу
    meals_day = statistics.mean([d["лог"]["съедено"] for d in last7]) / len(res["агенты"])
    food_hours = meals_day * labor_of("Хлеб")
    food_share = food_hours
    out.append({
        "id": "D-121", "что": "Дневная еда не съедает весь рабочий день",
        "ок": food_share <= 1.0,
        "факт": (f"по трудоёмкости дневной рацион стоит {food_hours:.2f} часа труда "
                 f"({meals_day:.1f} порции по {labor_of('Хлеб'):.2f} ч)"),
        "ручка": "agro.yield_share, farm.yield_per_m2, food.restore_by_quality",
    })

    # И3 / риск D-120: доход капитала против труда
    manual = incomes.get("фермер", 0)
    auto = manual * C["agro.yield_share"] / 100 if manual else 0
    energy_cost = C["agro.energy_per_hour"] * C["energy.tariff_default"] / 100
    out.append({
        "id": "D-120", "что": "Полевой автомат не дешевле батрака (иначе умирает наём)",
        "ок": auto - energy_cost < manual,
        "факт": f"автомат даёт {auto:.1f} ТК/ч против {manual:.1f} у человека, энергия съедает {energy_cost:.2f} ТК/ч",
        "ручка": "agro.yield_share, agro.energy_per_hour, energy.tariff_default",
    })

    # Занятость: не должно быть профессии, из которой ушли все
    # Профессия не обязана существовать, если спроса на неё нет: при выходе
    # шестьдесят единиц руды в час миру хватает двух шахтёров на две сотни душ.
    # Проверяем не занятость, а покрытие спроса
    food_made = statistics.mean([d["лог"]["сделано"].get("Хлеб", 0)
                                 + d["лог"]["сделано"].get("Похлёбка", 0)
                                 + d["лог"]["выращено"] / 2 for d in last7])
    food_need = statistics.mean([d["лог"]["съедено"] for d in last7]) or 1
    out.append({
        "id": "Р1", "что": "Пищевая цепочка покрывает потребность",
        "ок": food_made >= food_need,
        "факт": f"производится {food_made:.0f} порций в сутки при съедаемых {food_need:.0f}",
        "ручка": "`farm.yield_per_m2`, доля фермеров, `craft.time_per_unit`",
    })

    # Казна: сводится ли город на умолчаниях устава (D-127, D-130)
    city = res["казна"]
    week = city.log[-7:]
    income = sum(x["земельный"] + x["с продаж"] for x in week)
    spend = sum(x["материалы"] + x["содержание"] * C["upkeep.labor_share"] / 100
                + x["жалованье"] + x.get("развитие", 0) for x in week)
    unpaid = sum(x["недоплачено"] for x in week)
    out.append({
        "id": "К1", "что": "Казна сводится: доход покрывает содержание и жалованье",
        "ок": unpaid < 0.01,
        "факт": (f"за неделю доход {income:.0f} ТК против расходов {spend:.0f} ТК; "
                 f"не оплачено {unpaid:.0f} ТК, дней в нуле {city.dry_days}"),
        "ручка": "tax_trade, tax_land, salary, `build.upkeep_per_area`",
    })
    surplus = city.money
    week_income = sum(x["с продаж"] + x["земельный"] + x["энергия"] for x in week)
    out.append({
        "id": "К3", "что": "Профицит не лежит мёртвым грузом (D-134)",
        "ок": surplus < week_income,
        "факт": (f"в казне {surplus:.0f} ТК при недельном доходе {week_income:.0f} ТК. "
                 "Дороги и развитие модель пока не строит — деньги копятся"),
        "ручка": "устав `surplus_use`, ставки налогов, `energy.home_draw_per_m2`",
    })
    plant = statistics.mean([d["станция"] for d in last7])
    out.append({
        "id": "К2", "что": "Станция не встала: город смог купить топливо",
        "ок": plant >= 0.8,
        "факт": f"котёл загружен на {plant*100:.0f}% от потребности",
        "ручка": "`energy.coal_plant_fuel_draw`, цена угля, доход казны",
    })

    hungry = sum(d["лог"]["голодных дней"] for d in last7)
    out.append({
        "id": "Р2", "что": "Голода нет: еды хватает на популяцию",
        "ок": hungry < len(res["агенты"]),
        "факт": f"{hungry} голодных человеко-дней за последнюю неделю",
        "ручка": "farm.yield_per_m2, доля фермеров, spoilage.food_base",
    })

    return out


# --------------------------------------------------------------- калибровка

def calibrate() -> list[dict]:
    """Что обязано быть верно, чтобы И2 выполнялся при заданном якоре.

    Это самая полезная часть симуляции и единственная, которая не зависит от
    поведения агентов: чистая арифметика от `mining.iron_per_hour`. Она не
    подбирает баланс, она говорит, **каким обязано быть** недостающее число,
    чтобы час труда стоил одинаково во всех занятиях (И2).
    """
    out = []
    anchor = C["mining.iron_per_hour"]          # единиц руды за час
    ore_price = A("price.ore_anchor")
    hour = anchor * ore_price                   # ТК за час труда — эталон

    # 1. Земледелие: сколько урожая обязана давать делянка
    area = A("farm.plot_area")
    cycle = C["farm.cycle_days"]
    care_per_day = (3 * C["farm.plot_overhead"] + C["farm.care_time_per_m2"] * area) / 60
    plow = C["farm.plow_time_per_m2"] * area / 60
    hours_per_cycle = care_per_day * cycle + plow
    # урожай должен окупить эти часы по цене эталонного часа
    revenue_needed = hour * hours_per_cycle
    out.append({
        "что": "`farm.yield_per_m2` — урожай с метра за цикл",
        "взято": C["farm.yield_per_m2"],
        "следует": revenue_needed / (area * ore_price),
        "как": f"уход {care_per_day:.2f} ч/сутки × {cycle:.0f} суток плюс вспашка "
               f"{plow:.1f} ч = {hours_per_cycle:.1f} ч на цикл; при равной цене с рудой",
    })

    # 2. Уголь: час угольщика должен стоить столько же
    out.append({
        "что": "`mining.coal_per_hour` — выход угля за час",
        "взято": rate("Уголь", 60),
        "следует": anchor,
        "как": "при равной цене руды и угля — тот же выход; отличаться должны цены, "
               "а не производительность, иначе И2 держится только на рынке",
    })

    # 3. Ремесло: сколько сырья должно уходить в единицу передела
    craft_units = rate("Слиток железа", 60 / C["craft.time_per_unit"])
    fuel = op_qty("Слиток железа", "Уголь", 0.0)
    out.append({
        "что": "Руды на слиток — количество у операции «Плавка»",
        "взято": op_qty("Слиток железа", "Руда", 0),
        # уголь съедает часть бюджета труда, и на руду остаётся остальное
        "следует": anchor / craft_units - fuel,
        "как": f"час добычи даёт {anchor:.0f} руды, час у горна — {craft_units:.0f} слитков "
               f"(`harvest.rates`), из них {fuel:g} уходит на уголь. Если руды на слиток "
               "идёт меньше, кузнец беднее шахтёра при любой цене",
    })

    # 4. Инструмент: во сколько часов добычи обходится кирка (И7)
    sessions = 100 / C["wear.tool_per_session"]
    out.append({
        "что": "Ресурс кирки",
        "взято": sessions,
        "следует": sessions,
        "как": f"{sessions:.0f} сессий добычи — из `wear.tool_per_session`. "
               f"Значит один шахтёр создаёт спрос на {1 / sessions:.2f} кирки в сутки",
    })

    # 5. Еда: сколько её нужно миру в сутки
    need_day = 0.0
    for name, share, (lo, hi) in PROFILE:
        n = A("agent.population") * share
        h = (lo + hi) / 2
        drain = C["body.drain_rate"]["min"] + (C["body.drain_rate"]["max"] -
                                               C["body.drain_rate"]["min"]) * \
            {"казуальный": 0.35, "регулярный": 0.55, "хардкорный": 0.8}[name]
        per_meal = C["body.food_restore"] * 1.03
        need_day += n * h * drain / per_meal
    out.append({
        "что": "Приёмов пищи в сутки на популяцию",
        "взято": need_day,
        "следует": need_day,
        "как": f"{int(A('agent.population'))} человек по профилю 60/30/10 съедают "
               f"{need_day:.0f} порций в сутки. Это нижняя граница того, что обязано "
               "производить земледелие вместе с готовкой",
    })
    return out


# ------------------------------------------------------------------- отчёт

def report(res: dict, checks: list[dict], days: int, seed: int) -> str:
    d = res["дни"]
    last = d[-1]
    lines = [
        "# Симуляция экономики",
        "",
        "> **Статус:** генерируется · **Источник:** `tools/simulate.py` · "
        f"прогон {days} дней, популяция {int(A('agent.population'))}, зерно {seed}",
        ">",
        "> **Руками не править.** Это автотест баланса: он читает `build/*.json` — "
        "те же данные, что и движок, — и проверяет инварианты из "
        "[балансной модели](../30-economy/05-balance-model.md).",
        "",
        "## Вердикт",
        "",
        "| # | Что проверяем | Итог | Факт | Что крутить |",
        "|---|---|---|---|---|",
    ]
    for c in checks:
        mark = "✅" if c["ок"] else "❌"
        lines.append(f"| {c['id']} | {c['что']} | {mark} | {c['факт']} | `{c['ручка']}` |")

    failed = [c for c in checks if not c["ок"]]
    lines += ["", f"**Сломано проверок: {len(failed)} из {len(checks)}.**", ""]

    lines += ["## Цены", "", "| Товар | Старт | Финал | Изменение |", "|---|---|---|---|"]
    first = d[0]["цены"]
    for g in GOODS:
        chg = (last["цены"][g] / first[g] - 1) * 100
        lines.append(f"| {g} | {first[g]:.2f} | {last['цены'][g]:.2f} | {chg:+.0f}% |")

    lines += ["", "## Доход в час по профессиям (последняя неделя)", "",
              "| Занятие | ТК/час | Людей на финише |", "|---|---|---|"]
    last7 = d[-7:]
    for j in JOBS:
        avg = statistics.mean([x["доход"][j] for x in last7 if x["доход"][j] > 0] or [0])
        lines.append(f"| {j} | {avg:.1f} | {last['занятость'][j]} |")

    lines += ["", "## Запасы в мире", "", "| Товар | День 1 | Финал |", "|---|---|---|"]
    for g in GOODS:
        lines.append(f"| {g} | {res['запасы'][0][g]:.0f} | {res['запасы'][-1][g]:.0f} |")

    city = res["казна"]
    week = city.log[-7:]
    lines += ["", "## Казна города", "",
              "Город здесь не абстракция: он берёт налог с продаж и земельный, платит "
              "содержание и жалованье, а **уголь для станции покупает у игроков** — "
              "как обычный участник рынка (D-127).", "",
              "| Статья | ТК за последнюю неделю |", "|---|---|",
              f"| Налог с продаж | {sum(x['с продаж'] for x in week):.0f} |",
              f"| Земельный налог | {sum(x['земельный'] for x in week):.0f} |",
              f"| Энергия по счётчику | {sum(x['энергия'] for x in week):.0f} |",
              f"| Материалы на ремонт | −{sum(x['материалы'] for x in week):.0f} |",
              f"| Оплата труда ремонтников | −{sum(x['содержание'] * C['upkeep.labor_share'] / 100 for x in week):.0f} |",
              f"| Жалованье должностям | −{sum(x['жалованье'] for x in week):.0f} |",
              f"| Развитие: дороги | −{sum(x.get('развитие', 0) for x in week):.0f} |",
              f"| **Не оплачено** | **{sum(x['недоплачено'] for x in week):.0f}** |",
              f"| Остаток в казне | {city.money:.0f} |",
              "",
              f"Суток с непокрытыми расходами: **{city.dry_days}** из {days}. "
              f"Порог, после которого город начинает сыпаться, — `treasury.grace_days` "
              f"= {C['treasury.grace_days']}.",
              "",
              "## Что следует из якоря", "",
              "Единственная часть отчёта, не зависящая от поведения агентов: чистая "
              "арифметика от `mining.iron_per_hour`. Она не подбирает баланс — она "
              "говорит, **каким обязано быть** число, чтобы час труда стоил одинаково "
              "во всех занятиях (И2).", "",
              "| Величина | Взято в модели | Следует из якоря | Откуда |",
              "|---|---|---|---|"]
    for c in calibrate():
        lines.append(f"| {c['что']} | {c['взято']:.2f} | **{c['следует']:.2f}** | {c['как']} |")

    holes = [(k, v) for k, v in ASSUMPTIONS.items() if v[1].startswith("ДЫРА")]
    model = [(k, v) for k, v in ASSUMPTIONS.items() if not v[1].startswith("ДЫРА")]
    lines += ["", "## Чего не хватило в реестре", "",
              "Симуляция не имеет права выдумывать игровые числа. Вот всё, что "
              "пришлось предположить, потому что в `build/constants.json` этого нет:",
              "", "| Величина | Взято | Почему её нет |", "|---|---|---|"]
    for k, (v, why) in holes:
        lines.append(f"| `{k}` | {v} | {why.removeprefix('ДЫРА: ')} |")
    lines += ["", "Список короткий: количества входов больше не выдумываются — "
              "они выводятся из трудоёмкости и приходят из `build/recipes.json` (D-133).", "",
              "### Чисто модельные величины", "",
              "Их в игре нет и быть не должно — они описывают саму симуляцию:", "",
              "| Величина | Взято | Что это |", "|---|---|---|"]
    for k, (v, why) in model:
        lines.append(f"| `{k}` | {v} | {why.removeprefix('модель: ')} |")

    lines += ["", "## Насколько этой модели можно верить", "",
              "**Арифметическая часть сходится, рыночная — нет.** Всё, что считается "
              "от трудоёмкости — цены-ориентиры, стоимость рациона, покрытие спроса, — "
              "устойчиво и воспроизводится. Всё, что зависит от торга между агентами — "
              "равенство доходов, запасы отдельных переделов, конкуренция города за "
              "топливо, — гуляет: агенты близоруки, не планируют мощность и не умеют "
              "торговаться.", "",
              "Практическое следствие: **красный флаг в рыночной части — повод "
              "посмотреть руками, а не крутить константу.**", "",
              "Что из этого следует практически:", "",
              "| Часть отчёта | Верить? |",
              "|---|---|",
              "| **Что следует из якоря** | Да. Чистая арифметика, от поведения агентов не зависит |",
              "| **Чего не хватило в реестре** | Да. Это факт о данных, а не о модели |",
              "| Цены и доходы | Нет. Порядок величины, не более |",
              "| Инварианты | Как сигнал, а не как приговор: красный флаг стоит проверять руками |",
              "",
              "Чтобы агентная часть начала давать цены, ей нужно то, чего в ней нет: "
              "планирование мощности, запас под спрос и наём. Это следующая итерация.", "",
              "## Чего симуляция не проверяет", "",
              "- **Весело ли** — это Э0, бумажные прототипы с живыми людьми",
              "- **Политику** — города, законы, суды: там действуют люди, а не жадные агенты",
              "- **Логистику** — рынок здесь один на мир, хотя в игре они локальные (D-003)",
              "- **Настоящие цены** — агенты не спекулируют, не паникуют и не сговариваются",
              ""]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    res = run(args.days, args.seed)
    checks = check(res)
    text = report(res, checks, args.days, args.seed)
    REPORT.write_text(text, encoding="utf-8", newline="\n")

    failed = [c for c in checks if not c["ок"]]
    if not args.quiet:
        print(f"simulation: {args.days} days, {len(checks) - len(failed)}/{len(checks)} ok")
        for c in checks:
            print(("  OK   " if c["ок"] else "  FAIL ") + c["id"] + ": " + c["факт"])
        print(f"report -> {REPORT.relative_to(ROOT).as_posix()}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
