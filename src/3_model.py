"""ШАГ 4. Маленькая модель: предсказываем, сколько минут займёт запуск.

Идея: по прошлым запускам модель учится, что, например, по понедельникам считается дольше,
а при конфликте ещё дольше. Потом оркестратор сможет показывать «ожидаемое время».

Результат: output/model_results.txt и график output/graph5_model.png"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

ROOT = Path(__file__).resolve().parent.parent   # корень проекта (на уровень выше src/)
DATA_DIR = ROOT / "data"                         # входные данные (журнал из шага 1)
OUTPUT_DIR = ROOT / "output"                     # все результаты
OUTPUT_DIR.mkdir(exist_ok=True)

df = pd.read_csv(DATA_DIR / "run_log.csv", parse_dates=["start", "end"]).sort_values("start")
df = df[df.status == "ok"]          # учимся на успешных запусках (упавшие обрываются и сбивают картину)

# Признаки: что известно ДО запуска
df["day_of_week"] = pd.to_datetime(df.biz_date).dt.day_of_week     # день недели расчётной даты
df["hour"] = df.start.dt.hour                               # час старта
X = pd.get_dummies(df[["process", "run_type", "day_of_week", "hour", "n_conflicting"]])   # слова -> числа
y = df.duration_min                                         # что предсказываем

# Делим по времени: на первых 80% учимся, на последних 20% проверяем
cut = int(len(df) * 0.8)
X_train, X_test = X.iloc[:cut], X.iloc[cut:]
y_train, y_test = y.iloc[:cut], y.iloc[cut:]

model = GradientBoostingRegressor(random_state=0).fit(X_train, y_train)
predicted = model.predict(X_test)

# Для сравнения: «глупый» прогноз = среднее время процесса
mean_by_process = df.iloc[:cut].groupby("process").duration_min.mean()
simple_guess = df.iloc[cut:].process.map(mean_by_process)

mae_model = mean_absolute_error(y_test, predicted)          # средняя ошибка в минутах
mae_simple = mean_absolute_error(y_test, simple_guess)
text = (f"Проверено на {len(y_test)} запусках, которые модель не видела.\n"
        f"Средняя ошибка модели:            {mae_model:.1f} мин\n"
        f"Средняя ошибка «среднее по процессу»: {mae_simple:.1f} мин\n"
        f"Модель точнее на {(1 - mae_model / mae_simple) * 100:.0f}%\n")
(OUTPUT_DIR / "model_results.txt").write_text(text, encoding="utf-8")
print(text)

fig, ax = plt.subplots(figsize=(5.2, 5))
ax.scatter(y_test, predicted, s=18, alpha=0.7, color="#2980b9")
top = max(y_test.max(), predicted.max()) * 1.05
ax.plot([0, top], [0, top], "--", color="gray")             # идеальный прогноз лежит на этой линии
ax.set_xlabel("сколько заняло на самом деле, мин")
ax.set_ylabel("что предсказала модель, мин")
ax.set_title(f"Прогноз против факта\nошибка модели {mae_model:.1f} мин, простого среднего {mae_simple:.1f} мин")
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "graph5_model.png", dpi=150)
