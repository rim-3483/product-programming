import threading
from typing import Dict, List, Optional, Set, Tuple
from src.models import RunType, Task, TaskStatus


class Orchestrator:
    """
    Потокобезопасное ядро оркестратора расчёта рисков.
    Реализует:
    - S1/S2: исключение конфликтов по общим источникам данных
    - S3: отклонение дублей (одинаковый процесс + отчётная дата в A(t) U Q(t))
    - S4: атомарный захват всех нужных источников при старте (защита от deadlock)
    - S5: приоритетную диспетчеризацию по формуле Score(j, t)
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()        # Защита от гонки данных при одновременных вызовах
        self.active_tasks: List[Task] = []    # A(t) — выполняются прямо сейчас
        self.queue: List[Task] = []           # Q(t) — ждут в очереди
        self.history: List[Task] = []         # Завершённые, упавшие и отклонённые
        self.current_time: float = 0.0        # Текущее модельное время (в минутах)

    def get_busy_resources(self) -> Set[str]:
        """Возвращает B(t) — объединение всех ресурсов, занятых активными задачами."""
        with self._lock:
            busy: Set[str] = set()
            for task in self.active_tasks:
                busy.update(task.resources)
            return busy

    def find_duplicate(self, process_name: str, biz_date: str) -> Optional[Task]:
        """
        Сценарий S3: проверяет, есть ли уже задача с тем же (p_j, d_j)
        в работе A(t) или в очереди Q(t).
        """
        with self._lock:
            for task in self.active_tasks + self.queue:
                if task.process_name == process_name and task.biz_date == biz_date:
                    return task
            return None

    def calculate_score(self, task: Task, current_time: Optional[float] = None) -> float:
        """
        Сценарий S5: расчёт веса приоритета (чем МЕНЬШЕ score, тем выше приоритет).
        Score(j, t) = 30 * is_manual(j) + 1.0 * w_j - 1.5 * (t - t_j)
        """
        with self._lock:
            t = self.current_time if current_time is None else current_time
            wait_time = max(0.0, t - task.created_at)
            return (
                30.0 * task.is_manual
                + 1.0 * float(task.estimated_duration)
                - 1.5 * wait_time
            )

    def submit_task(
        self,
        process_name: str,
        biz_date: str,
        run_type: str | RunType = RunType.MANUAL,
        current_time: Optional[float] = None,
        estimated_duration: Optional[float] = None,
        custom_resources: Optional[Set[str]] = None,
    ) -> Tuple[bool, Task, str]:
        """
        Атомарно принимает новую заявку на запуск расчёта.
        Возвращает: (принята_ли_задача, объект_Task, сообщение_для_интерфейса).
        """
        with self._lock:
            if current_time is not None:
                self.current_time = current_time

            # 1. Проверка на дубль (S3)
            existing = self.find_duplicate(process_name, biz_date)
            if existing is not None:
                rejected_task = Task(
                    process_name=process_name,
                    biz_date=biz_date,
                    run_type=run_type,
                    created_at=self.current_time,
                    estimated_duration=estimated_duration,
                    resources=custom_resources,
                    status=TaskStatus.REJECTED,
                )
                self.history.append(rejected_task)
                msg = (
                    f"Дубль отклонён: процесс '{process_name}' за {biz_date} уже "
                    f"находится в статусе '{existing.status.value}' (ID: {existing.task_id})."
                )
                return False, existing, msg

            # 2. Создаём задачу и ставим в очередь Q(t)
            new_task = Task(
                process_name=process_name,
                biz_date=biz_date,
                run_type=run_type,
                created_at=self.current_time,
                estimated_duration=estimated_duration,
                resources=custom_resources,
                status=TaskStatus.QUEUED,
            )
            self.queue.append(new_task)

            # 3. Пересчитываем очередь
            self.schedule(self.current_time)

            msg = f"Задача '{process_name}' за {biz_date} принята (статус: {new_task.status.value})."
            return True, new_task, msg

    def schedule(self, current_time: Optional[float] = None) -> List[Task]:
        """
        Пересчёт очереди (S1, S2, S4, S5).
        Запускает из Q(t) все совместимые задачи в порядке возрастания Score(j, t).
        """
        with self._lock:
            if current_time is not None:
                self.current_time = current_time

            started_now: List[Task] = []

            while True:
                busy = self.get_busy_resources()

                # Отбираем задачи, у которых R_j ∩ B(t) = ∅ (все нужные источники свободны)
                ready_tasks = [
                    task for task in self.queue
                    if task.resources.isdisjoint(busy)
                ]

                if not ready_tasks:
                    break

                # Выбираем задачу с минимальным Score(j, t)
                best_task = min(
                    ready_tasks,
                    key=lambda task: (self.calculate_score(task, self.current_time), task.created_at),
                )

                # Атомарно переводим задачу из Q(t) в A(t) — исключает deadlock (S4)
                self.queue.remove(best_task)
                best_task.status = TaskStatus.RUNNING
                best_task.started_at = self.current_time
                self.active_tasks.append(best_task)
                started_now.append(best_task)

            return started_now

    def complete_task(
        self,
        task_id: str,
        success: bool = True,
        current_time: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Task]:
        """
        Завершает активную задачу, освобождает её ресурсы и запускает пересчёт очереди.
        """
        with self._lock:
            if current_time is not None:
                self.current_time = current_time

            target = next((t for t in self.active_tasks if t.task_id == task_id), None)
            if target is None:
                return None

            self.active_tasks.remove(target)
            target.finished_at = self.current_time
            if success:
                target.status = TaskStatus.COMPLETED
            else:
                target.status = TaskStatus.FAILED
                target.error_message = error_message or "Ошибка выполнения расчёта"

            self.history.append(target)

            # Ресурсы освободились — проверяем очередь Q(t)
            self.schedule(self.current_time)
            return target

    def advance_time(self, minutes: float) -> List[Task]:
        """
        Сдвигает модельное время на `minutes` вперёд (target_time) и пошагово
        завершает ВСЕ задачи (включая стартовавшие из очереди в процессе),
        чьё время окончания <= target_time.
        """
        if minutes < 0:
            raise ValueError("Сдвиг времени не может быть отрицательным")

        with self._lock:
            target_time = self.current_time + minutes
            finished_tasks: List[Task] = []

            while True:
                # Ищем все активные задачи, которые успевают завершиться до target_time
                due_tasks = [
                    t for t in self.active_tasks
                    if t.started_at is not None
                    and (t.started_at + float(t.estimated_duration)) <= target_time
                ]
                if not due_tasks:
                    break

                # Завершаем самую раннюю по времени окончания задачу,
                # чтобы в точный момент finish_t освободить ресурсы и запустить следующую из очереди
                earliest = min(due_tasks, key=lambda t: t.started_at + float(t.estimated_duration))
                finish_t = earliest.started_at + float(earliest.estimated_duration)
                completed = self.complete_task(earliest.task_id, success=True, current_time=finish_t)
                if completed:
                    finished_tasks.append(completed)

            # Фиксируем итоговое время после завершения всех промежуточных событий
            self.current_time = target_time
            self.schedule(target_time)
            return finished_tasks

    def get_state_snapshot(self) -> Dict:
        """Потокобезопасный срез состояния для отрисовки в Streamlit."""
        with self._lock:
            return {
                "current_time": self.current_time,
                "busy_resources": sorted(list(self.get_busy_resources())),
                "active": list(self.active_tasks),
                "queue": sorted(self.queue, key=lambda t: self.calculate_score(t)),
                "history": list(self.history),
            }
