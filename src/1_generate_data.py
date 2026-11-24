
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

random.seed(42)


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
    same_task = a["process"] == b["process"] and a["biz_date"] == b["biz_date"]
    shared_source = bool(set(a["sources"]) & set(b["sources"]))
    return same_task or shared_source


plan = []
for d in range(30):
    day = FIRST_DAY + timedelta(days=d)
    yesterday = (day - timedelta(days=1)).date()

    for name in PROCESSES:
        start = day.replace(hour=2, minute=random.randint(0, 20))
        plan.append((name, start, yesterday, "scheduled", None))

    for _ in range(random.randint(3, 8)):
        start = day + timedelta(hours=random.randint(9, 18), minutes=random.randint(0, 59))
        biz_date = (day - timedelta(days=random.randint(0, 5))).date()
        plan.append((random.choice(list(PROCESSES)), start, biz_date, "manual", random.choice(USERS)))

    if random.random() < 0.15:
        start = day.replace(hour=2, minute=random.randint(5, 40))
        plan.append((random.choice(list(PROCESSES)), start, yesterday, "manual", random.choice(USERS)))

plan.sort(key=lambda x: x[1])

rows = []
running = []
for name, start, biz_date, run_type, user in plan:
    me = {"process": name, "biz_date": biz_date, "sources": PROCESSES[name]["sources"]}

    running = [r for r in running if r["end"] > start]          #
    n_conflicting = sum(conflict(me, r) for r in running)
    is_duplicate = any(r["process"] == name and r["biz_date"] == biz_date for r in running)

    monday = 1.3 if biz_date.weekday() == 0 else 1.0
    clean_min = PROCESSES[name]["base_min"] * monday * random.uniform(0.9, 1.1)
    duration = clean_min * (1 + 0.25 * n_conflicting)


    p_fail = 0.6 if is_duplicate else (0.35 if n_conflicting >= 2 else (0.05 if n_conflicting == 1 else 0))
    failed = random.random() < p_fail
    if failed:
        duration *= 0.6

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
