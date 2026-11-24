"""ШАГ 1. Делаем ВЫДУМАННЫЙ журнал запусков за 30 дней.

Представь, что оркестратора нет: процессы запускаются как попало.
Если два запуска идут одновременно и делят источник данных, они конфликтуют:
из-за этого задача идёт дольше, а иногда падает.

Результат: data/run_log.csv (журнал), data/test_scenarios.json (сценарии для теста оркестратора)."""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent   # корень проекта (на уровень выше src/)
DATA_DIR = ROOT / "data"                         # папка data в корне проекта
DATA_DIR.mkdir(exist_ok=True)

random.seed(42)            # чтобы при каждом запуске получались одни и те же данные

# 5 процессов: из каких источников берут данные и сколько минут считаются, если никто не мешает
PROCESSES = {
    "credit_risk":      {"sources": ["crm", "transactions", "ratings"],   "base_min": 40},
    "market_risk":      {"sources": ["market_data", "limits"],            "base_min": 25},
    "liquidity_risk":   {"sources": ["transactions", "limits"],           "base_min": 30},
    "operational_risk": {"sources": ["crm", "transactions"],              "base_min": 20},
    "stress_test":      {"sources": ["market_data", "ratings", "limits"], "base_min": 60},
}
USERS = ["user1", "user2", "user3", "user4", "user5", "user6"]
FIRST_DAY = datetime(2026, 10, 1)


def conflict(a, b):
    """Два запуска конфликтуют, если это тот же процесс за ту же дату
    ИЛИ у них есть общий источник данных."""
    same_task = a["process"] == b["process"] and a["biz_date"] == b["biz_date"]
    shared_source = bool(set(a["sources"]) & set(b["sources"]))
    return same_task or shared_source


# --- 1. Составляем план: кто и когда нажимает «запустить» ---
plan = []
for d in range(30):
    day = FIRST_DAY + timedelta(days=d)
    yesterday = (day - timedelta(days=1)).date()

    # каждую ночь все 5 процессов стартуют по расписанию почти одновременно
    for name in PROCESSES:
        start = day.replace(hour=2, minute=random.randint(0, 20))
        plan.append((name, start, yesterday, "scheduled", None))

    # днём пользователи запускают процессы вручную (иногда за прошлые даты)
    for _ in range(random.randint(3, 8)):
        start = day + timedelta(hours=random.randint(9, 18), minutes=random.randint(0, 59))
        biz_date = (day - timedelta(days=random.randint(0, 5))).date()
        plan.append((random.choice(list(PROCESSES)), start, biz_date, "manual", random.choice(USERS)))

    # иногда кто-то нажимает ту же кнопку вручную, пока идёт ночной запуск (дубль)
    if random.random() < 0.15:
        start = day.replace(hour=2, minute=random.randint(5, 40))
        plan.append((random.choice(list(PROCESSES)), start, yesterday, "manual", random.choice(USERS)))

plan.sort(key=lambda x: x[1])      # идём по времени

# --- 2. «Проживаем» этот план и смотрим, что получается ---
rows = []
running = []                       # кто сейчас выполняется
for name, start, biz_date, run_type, user in plan:
    me = {"process": name, "biz_date": biz_date, "sources": PROCESSES[name]["sources"]}

    running = [r for r in running if r["end"] > start]          # убираем тех, кто уже закончил
    n_conflicting = sum(conflict(me, r) for r in running)       # сколько работающих нам мешают
    is_duplicate = any(r["process"] == name and r["biz_date"] == biz_date for r in running)

    monday = 1.3 if biz_date.weekday() == 0 else 1.0            # за понедельник считается дольше
    clean_min = PROCESSES[name]["base_min"] * monday * random.uniform(0.9, 1.1)
    duration = clean_min * (1 + 0.25 * n_conflicting)           # каждый конфликт: +25% времени

    # шанс упасть: дубль почти всегда ломает, два конфликта часто, один конфликт редко
    p_fail = 0.6 if is_duplicate else (0.35 if n_conflicting >= 2 else (0.05 if n_conflicting == 1 else 0))
    failed = random.random() < p_fail
    if failed:
        duration *= 0.6                                         # упал на середине

    end = start + timedelta(minutes=duration)
    running.append({**me, "end": end})
    rows.append({
        "process": name, "sources": ";".join(me["sources"]), "start": start, "end": end,
        "biz_date": biz_date, "run_type": run_type, "user": user,
        "n_conflicting": n_conflicting, "is_duplicate": int(is_duplicate),
        "clean_min": round(clean_min, 1), "duration_min": round(duration, 1),
        "status": "failed" if failed else "ok",
    })

df = pd.DataFrame(rows)
df.to_csv(DATA_DIR / "run_log.csv", index=False)
print(f"Запусков: {len(df)}, с конфликтом: {(df.n_conflicting > 0).sum()}, "
      f"упало: {(df.status == 'failed').sum()}, дублей: {df.is_duplicate.sum()}")


# --- 3. Сценарии для проверки будущего оркестратора (отдать тому, кто тестирует) ---
def task(id_, proc, date, run_type="manual", user="user1", at=0, sources=None, minutes=None):
    return {"id": id_, "process": proc, "biz_date": date, "run_type": run_type, "user": user,
            "submit_at_min": at, "sources": sources or PROCESSES[proc]["sources"],
            "duration_min": minutes or PROCESSES[proc]["base_min"]}


scenarios = [
    {"name": "S1 один процесс, разные даты",
     "tasks": [task("A", "credit_risk", "2026-10-08", user="user1"),
               task("B", "credit_risk", "2026-10-09", user="user2")],
     "expected": "B ждёт A (общие источники), ошибок нет"},
    {"name": "S2 разные процессы, одна дата",
     "tasks": [task("A", "credit_risk", "2026-10-09"), task("B", "market_risk", "2026-10-09", user="user2"),
               task("C", "liquidity_risk", "2026-10-09", user="user3")],
     "expected": "A и B идут параллельно (нет общих источников), C ждёт обоих"},
    {"name": "S3 ручной запуск против регламентного",
     "tasks": [task("A", "credit_risk", "2026-10-09", run_type="scheduled"),
               task("B", "credit_risk", "2026-10-09", user="user4", at=10)],
     "expected": "B отклонён как дубль (тот же процесс и дата)"},
    {"name": "S4 ловушка взаимной блокировки",
     "tasks": [task("A", "test_A", "2026-10-09", sources=["crm", "ratings"], minutes=20),
               task("B", "test_B", "2026-10-09", sources=["ratings", "crm"], minutes=20, at=1)],
     "expected": "B ждёт A, зависания нет"},
    {"name": "S5 ночной пик",
     "tasks": [task(f"N{i}", n, "2026-10-09", run_type="scheduled", at=i * 3) for i, n in enumerate(PROCESSES)] +
              [task("M1", "market_risk", "2026-10-07", user="user5", at=10)],
     "expected": "очередь, часть задач параллельно, конфликтов 0"},
]
with open(DATA_DIR / "test_scenarios.json", "w", encoding="utf-8") as f:
    json.dump(scenarios, f, ensure_ascii=False, indent=2)
