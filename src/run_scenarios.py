import json
from pathlib import Path
from src.orchestrator import Orchestrator
from src.models import TaskStatus
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
file_path = ROOT / "data" / "test_scenarios.json"

with open(file_path, 'r', encoding='utf-8') as file:
    data = json.load(file)


a = int(input('Введите номер сценария от 1 до 5: '))
scenario = data[a-1]
orch = Orchestrator()
sorted_tasks = sorted(
    scenario["tasks"],
    key=lambda task: task["submit_at_min"]
)
print(scenario["name"])
for task in sorted_tasks:
    arrival_time = task["submit_at_min"]
    delta = arrival_time - orch.current_time
    orch.advance_time(delta)
    accepted, new_task, message = orch.submit_task(
        process_name=task["process"],
        biz_date=task["biz_date"],
        run_type=task["run_type"],
        estimated_duration=task["duration_min"],
        custom_resources=set(task["sources"])
    )
    if not accepted:
        print("Отклонена заявка:", message)
while orch.active_tasks or orch.queue:
    orch.advance_time(1)

print("Ожидаемое поведение:", scenario["expected"])
completed = 0
rejected = 0
failed = 0
completed_tasks = []
for task in orch.history:
    if task.status == TaskStatus.COMPLETED:
        completed_tasks.append(task)
        completed += 1
    if task.status == TaskStatus.REJECTED:
        rejected += 1
    if task.status == TaskStatus.FAILED:
        failed += 1

conflicts = 0
for i in range(len(completed_tasks)):
    for j in range(i + 1, len(completed_tasks)):
        task1 = completed_tasks[i]
        task2 = completed_tasks[j]
        common_resources = task1.resources & task2.resources
        overlap = (
                task1.started_at < task2.finished_at
                and task2.started_at < task1.finished_at
        )
        if overlap and common_resources:
            conflicts += 1
            print(
                "Обнаружен конфликт между",
                task1.process_name,
                "и",
                task2.process_name,
                "Общие ресурсы:",
                common_resources
            )

print("\nРезультаты симуляции:")
print("Завершено:", completed)
print("Отклонено:", rejected)
print("Ошибок:", failed)
print("Конфликтов:", conflicts)
print("Итоговое время:", orch.current_time)

tasks = sorted(
    completed_tasks,
    key=lambda task: task.started_at
)

names = [task.process_name for task in tasks]

starts = [task.started_at for task in tasks]

durations = [
    task.finished_at - task.started_at
    for task in tasks
]
fig, ax = plt.subplots(figsize=(10, 5))

for i in range(len(tasks)):
    ax.barh(
        i,
        durations[i],
        left=starts[i]
    )

ax.set_yticks(range(len(tasks)), names)
ax.set_xlabel("Время (минуты)")
ax.set_ylabel("Процессы")
ax.set_title(scenario["name"])

plt.tight_layout()
plt.show()

assert len(orch.active_tasks) == 0
assert len(orch.queue) == 0
assert completed + rejected + failed == len(scenario["tasks"])
assert conflicts == 0
print("Проверка сценария пройдена!")