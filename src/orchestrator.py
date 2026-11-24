import threading
from typing import Dict, List, Optional, Set, Tuple
from src.models import RunType, Task, TaskStatus


class Orchestrator:

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.active_tasks: List[Task] = []
        self.queue: List[Task] = []
        self.history: List[Task] = []
        self.current_time: float = 0.0

    def get_busy_resources(self) -> Set[str]:
        with self._lock:
            busy: Set[str] = set()
            for task in self.active_tasks:
                busy.update(task.resources)
            return busy

    def find_duplicate(self, process_name: str, biz_date: str) -> Optional[Task]:
        with self._lock:
            for task in self.active_tasks + self.queue:
                if task.process_name == process_name and task.biz_date == biz_date:
                    return task
            return None

    def calculate_score(self, task: Task, current_time: Optional[float] = None) -> float:

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

        with self._lock:
            if current_time is not None:
                self.current_time = current_time
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

            self.schedule(self.current_time)

            msg = f"Задача '{process_name}' за {biz_date} принята (статус: {new_task.status.value})."
            return True, new_task, msg

    def schedule(self, current_time: Optional[float] = None) -> List[Task]:

        with self._lock:
            if current_time is not None:
                self.current_time = current_time

            started_now: List[Task] = []

            while True:
                busy = self.get_busy_resources()
                ready_tasks = [
                    task for task in self.queue
                    if task.resources.isdisjoint(busy)
                ]

                if not ready_tasks:
                    break
                best_task = min(
                    ready_tasks,
                    key=lambda task: (self.calculate_score(task, self.current_time), task.created_at),
                )
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

        if minutes < 0:
            raise ValueError("Сдвиг времени не может быть отрицательным")

        with self._lock:
            target_time = self.current_time + minutes
            finished_tasks: List[Task] = []

            while True:
                due_tasks = [
                    t for t in self.active_tasks
                    if t.started_at is not None
                    and (t.started_at + float(t.estimated_duration)) <= target_time
                ]
                if not due_tasks:
                    break

                earliest = min(due_tasks, key=lambda t: t.started_at + float(t.estimated_duration))
                finish_t = earliest.started_at + float(earliest.estimated_duration)
                completed = self.complete_task(earliest.task_id, success=True, current_time=finish_t)
                if completed:
                    finished_tasks.append(completed)

            self.current_time = target_time
            self.schedule(target_time)
            return finished_tasks

    def get_state_snapshot(self) -> Dict:

        with self._lock:
            return {
                "current_time": self.current_time,
                "busy_resources": sorted(list(self.get_busy_resources())),
                "active": list(self.active_tasks),
                "queue": sorted(self.queue, key=lambda t: self.calculate_score(t)),
                "history": list(self.history),
            }
