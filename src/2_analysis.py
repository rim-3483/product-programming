"""ШАГ 2. Ищем узкие места в журнале: считаем цифры и рисуем графики.

Результат (папка output):
  graph1_conflict_pairs.png  какие процессы чаще всего мешают друг другу
  graph2_hot_sources.png     какие источники данных самые «горячие»
  graph3_peak_hours.png      в какие часы затор
  graph4_run_types.png       ручные против регламентных запусков
  summary.md                 текст с цифрами: его вставляем в ИИ-чат (ШАГ 3)"""
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent   # корень проекта (на уровень выше src/)
DATA_DIR = ROOT / "data"                         # входные данные (журнал из шага 1)
OUTPUT_DIR = ROOT / "output"                     # все результаты
OUTPUT_DIR.mkdir(exist_ok=True)

df = pd.read_csv(DATA_DIR / "run_log.csv", parse_dates=["start", "end"]).sort_values("start")
df["sources"] = df["sources"].str.split(";")
rows = df.to_dict("records")
names = sorted(df.process.unique())

# --- Находим пары запусков, которые шли одновременно и мешали друг другу ---
pair_count = Counter()      # какие пары процессов
source_count = Counter()    # какие источники
for i, a in enumerate(rows):
    for b in rows[i + 1:]:
        if b["start"] >= a["end"]:          # дальше запуски начинаются уже после конца a
            break
        shared = set(a["sources"]) & set(b["sources"])
        same_task = a["process"] == b["process"] and a["biz_date"] == b["biz_date"]
        if shared or same_task:
            pair_count[tuple(sorted((a["process"], b["process"])))] += 1
            for s in shared:
                source_count[s] += 1

# --- Главные цифры ---
total = len(df)
with_conflict = (df.n_conflicting > 0).mean()
failed = (df.status == "failed").sum()
good = df[df.status == "ok"]
slowdown = (good.duration_min / good.clean_min).mean()
by_hour = df.groupby(df.start.dt.hour).size()
peak_hour = by_hour.idxmax()
by_type = df.groupby("run_type").agg(conflict=("n_conflicting", lambda s: (s > 0).mean()),
                                     failed=("status", lambda s: (s == "failed").mean()))

# --- График 1: матрица конфликтов ---
matrix = np.zeros((len(names), len(names)), dtype=int)
for (p, q), c in pair_count.items():
    matrix[names.index(p), names.index(q)] += c
    if p != q:
        matrix[names.index(q), names.index(p)] += c
fig, ax = plt.subplots(figsize=(6.5, 5))
img = ax.imshow(matrix, cmap="Reds")
ax.set_xticks(range(len(names)), names, rotation=35, ha="right")
ax.set_yticks(range(len(names)), names)
for i in range(len(names)):
    for j in range(len(names)):
        ax.text(j, i, matrix[i, j], ha="center", va="center")
ax.set_title("Какие процессы чаще всего конфликтуют")
fig.colorbar(img, shrink=0.8)
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "graph1_conflict_pairs.png", dpi=150)

# --- График 2: горячие источники ---
fig, ax = plt.subplots(figsize=(6, 3.8))
src, cnt = zip(*source_count.most_common())
ax.barh(src[::-1], cnt[::-1], color="#c0392b")
ax.set_title("Самые «горячие» источники данных\n(сколько раз из-за них конфликт)")
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "graph2_hot_sources.png", dpi=150)

# --- График 3: часы пик ---
fig, ax = plt.subplots(figsize=(7, 3.8))
hours = range(24)
ax.bar(hours, [by_hour.get(h, 0) for h in hours], color="#95a5a6", label="все запуски")
conf_hour = df[df.n_conflicting > 0].groupby(df.start.dt.hour).size()
ax.bar(hours, [conf_hour.get(h, 0) for h in hours], color="#c0392b", label="запуски с конфликтом")
ax.set_xlabel("час старта")
ax.set_ylabel("число запусков")
ax.set_title("Часы пик: ночной регламент создаёт затор")
ax.legend()
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "graph3_peak_hours.png", dpi=150)

# --- График 4: ручные и регламентные ---
fig, ax = plt.subplots(figsize=(5.5, 3.8))
x = np.arange(len(by_type))
ax.bar(x - 0.2, by_type.conflict * 100, 0.4, label="с конфликтом, %", color="#e67e22")
ax.bar(x + 0.2, by_type.failed * 100, 0.4, label="упали, %", color="#c0392b")
ax.set_xticks(x, ["регламентные" if t == "scheduled" else "ручные" for t in by_type.index])
ax.set_title("Ручные и регламентные запуски")
ax.legend()
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "graph4_run_types.png", dpi=150)

# --- Текстовая сводка: её отдаём ИИ-чату ---
top_pairs = "; ".join(f"{p} + {q} ({c})" for (p, q), c in pair_count.most_common(3))
top_sources = "; ".join(f"{s} ({c})" for s, c in source_count.most_common(3))
processes_text = "; ".join(f"{p}: {', '.join(sorted(set(sum(df[df.process == p].sources.tolist(), []))))}" for p in names)
summary = f"""# Сводка журнала запусков (30 дней, оркестратора нет)
- Всего запусков: {total}; с конфликтом: {with_conflict:.0%}; упало: {failed} ({failed / total:.0%}); двойных запусков (тот же процесс и дата): {df.is_duplicate.sum()}.
- Конфликт замедляет задачу в среднем в {slowdown:.2f} раза.
- Самые конфликтные пары процессов: {top_pairs}.
- Самые горячие источники: {top_sources}.
- Час пика: {peak_hour}:00, на него приходится {by_hour[peak_hour] / total:.0%} всех запусков (ночной регламент: все 5 процессов стартуют в течение 20 минут).
- Ручные запуски: конфликт у {by_type.loc['manual', 'conflict']:.0%}, упали {by_type.loc['manual', 'failed']:.0%}; регламентные: конфликт у {by_type.loc['scheduled', 'conflict']:.0%}, упали {by_type.loc['scheduled', 'failed']:.0%}.
- Процессы и их источники: {processes_text}.
"""
(OUTPUT_DIR / "summary.md").write_text(summary, encoding="utf-8")
print(summary)
