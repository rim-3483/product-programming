import threading
import unittest
from src.models import RunType, TaskStatus
from src.orchestrator import Orchestrator


class TestOrchestrator(unittest.TestCase):
    def test_s1_parallel_independent_processes(self) -> None:
        """S1: Процессы без общих источников идут параллельно."""
        orch = Orchestrator()
        ok1, t1, _ = orch.submit_task("credit_risk", "2026-11-20", RunType.SCHEDULED, current_time=0)
        ok2, t2, _ = orch.submit_task("market_risk", "2026-11-20", RunType.MANUAL, current_time=0)

        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertEqual(t1.status, TaskStatus.RUNNING)
        self.assertEqual(t2.status, TaskStatus.RUNNING)
        self.assertEqual(len(orch.active_tasks), 2)

    def test_s2_conflict_same_process_different_dates(self) -> None:
        """S2: Один и тот же процесс за разные даты блокирует сам себя и идёт последовательно."""
        orch = Orchestrator()
        _, t1, _ = orch.submit_task("operational_risk", "2026-11-20", RunType.MANUAL, current_time=0)
        _, t2, _ = orch.submit_task("operational_risk", "2026-11-21", RunType.MANUAL, current_time=1)

        self.assertEqual(t1.status, TaskStatus.RUNNING)
        self.assertEqual(t2.status, TaskStatus.QUEUED)

        orch.complete_task(t1.task_id, success=True, current_time=20)
        self.assertEqual(t2.status, TaskStatus.RUNNING)

    def test_s3_reject_duplicate(self) -> None:
        """S3: Дубль (одинаковый процесс + дата в работе или очереди) отклоняется."""
        orch = Orchestrator()
        ok1, t1, _ = orch.submit_task("credit_risk", "2026-11-20", RunType.SCHEDULED, current_time=0)
        ok2, returned_task, _ = orch.submit_task("credit_risk", "2026-11-20", RunType.MANUAL, current_time=5)

        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertEqual(returned_task.task_id, t1.task_id)
        self.assertEqual(len(orch.active_tasks), 1)
        self.assertEqual(len(orch.queue), 0)
        self.assertEqual(orch.history[-1].status, TaskStatus.REJECTED)

    def test_s4_no_deadlock_atomic_reservation(self) -> None:
        """S4: Взаимная блокировка невозможна благодаря атомарному захвату всех ресурсов."""
        orch = Orchestrator()
        # Задачи с пересекающимися ресурсами (crm, ratings)
        _, t1, _ = orch.submit_task(
            "task_a", "2026-11-20", custom_resources={"crm", "ratings"}, estimated_duration=10, current_time=0
        )
        _, t2, _ = orch.submit_task(
            "task_b", "2026-11-20", custom_resources={"ratings", "crm"}, estimated_duration=10, current_time=0
        )

        self.assertEqual(t1.status, TaskStatus.RUNNING)
        self.assertEqual(t2.status, TaskStatus.QUEUED)

        orch.advance_time(25)
        self.assertEqual(t1.status, TaskStatus.COMPLETED)
        self.assertEqual(t2.status, TaskStatus.COMPLETED)
        self.assertEqual(len(orch.active_tasks), 0)

    def test_s5_priority_score_and_aging(self) -> None:
        """S5: Регламентные задачи (scheduled) имеют приоритет над ручными (manual), но aging спасает от голодания."""
        orch = Orchestrator()
        # Блокируем transactions процессом operational_risk (20 мин)
        _, blocker, _ = orch.submit_task("operational_risk", "2026-11-20", RunType.MANUAL, current_time=0)

        # В очередь приходят ручная задача (t=1) и позже регламентная (t=2)
        _, manual_task, _ = orch.submit_task("liquidity_risk", "2026-11-20", RunType.MANUAL, current_time=1)
        _, sched_task, _ = orch.submit_task("credit_risk", "2026-11-20", RunType.SCHEDULED, current_time=2)

        # Завершаем блокер на 20-й минуте: Score(sched)=40 - 1.5*18 = 13.0 < Score(manual)=30+30 - 1.5*19 = 31.5
        orch.complete_task(blocker.task_id, success=True, current_time=20)
        self.assertEqual(sched_task.status, TaskStatus.RUNNING)
        self.assertEqual(manual_task.status, TaskStatus.QUEUED)

    def test_large_advance_time_step(self) -> None:
        """Проверка большого скачка виртуального времени: цепочка задач должна полностью завершиться."""
        orch = Orchestrator()
        # 3 последовательных запуска operational_risk (по 20 мин каждый = 60 мин суммарно)
        _, t1, _ = orch.submit_task("operational_risk", "2026-11-20", current_time=0)
        _, t2, _ = orch.submit_task("operational_risk", "2026-11-21", current_time=0)
        _, t3, _ = orch.submit_task("operational_risk", "2026-11-22", current_time=0)

        # Делаем один большой скачок на 100 минут вперёд
        finished = orch.advance_time(100)

        self.assertEqual(len(finished), 3)
        self.assertEqual(orch.current_time, 100.0)
        self.assertEqual(len(orch.active_tasks), 0)
        self.assertEqual(len(orch.queue), 0)
        self.assertEqual([t.status for t in (t1, t2, t3)], [TaskStatus.COMPLETED] * 3)

    def test_thread_safety_concurrent_submits(self) -> None:
        """Проверка синхронизации: при одновременном запуске из 10 потоков дубли отсекаются и ресурсы не конфликтуют."""
        orch = Orchestrator()
        results = []

        def worker() -> None:
            res = orch.submit_task("credit_risk", "2026-11-20", RunType.MANUAL, current_time=0)
            results.append(res[0])

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        # Только 1 заявка должна быть принята, остальные 9 отклонены как дубли
        self.assertEqual(sum(results), 1)
        self.assertEqual(len(orch.active_tasks), 1)
    def test_resource_release_after_failure(self) -> None:
        """Тест 8: Освобождение ресурсов и запуск очереди после падения задачи с ошибкой."""
        orch = Orchestrator()
        _, t1, _ = orch.submit_task("operational_risk", "2026-11-20", RunType.MANUAL, current_time=0)
        _, t2, _ = orch.submit_task("operational_risk", "2026-11-21", RunType.MANUAL, current_time=1)

        self.assertEqual(t1.status, TaskStatus.RUNNING)
        self.assertEqual(t2.status, TaskStatus.QUEUED)

        # Завершаем первую задачу с ошибкой
        orch.complete_task(t1.task_id, success=False, current_time=10, error_message="DB timeout")

        self.assertEqual(t1.status, TaskStatus.FAILED)
        self.assertEqual(t2.status, TaskStatus.RUNNING)

    def test_duplicate_in_queue(self) -> None:
        """Тест 9: Отклонение дубликата, который уже ожидает в очереди Q(t)."""
        orch = Orchestrator()
        # Занимаем transactions
        _, blocker, _ = orch.submit_task("operational_risk", "2026-11-20", RunType.MANUAL, current_time=0)
        # Ставим credit_risk в очередь
        ok1, queued_task, _ = orch.submit_task("credit_risk", "2026-11-20", RunType.SCHEDULED, current_time=1)
        # Отправляем дубль того же credit_risk, пока оригинал ещё в очереди
        ok2, returned_task, _ = orch.submit_task("credit_risk", "2026-11-20", RunType.MANUAL, current_time=2)

        self.assertTrue(ok1)
        self.assertEqual(queued_task.status, TaskStatus.QUEUED)
        self.assertFalse(ok2)
        self.assertEqual(returned_task.task_id, queued_task.task_id)
        self.assertEqual(len(orch.queue), 1)
        self.assertEqual(orch.history[-1].status, TaskStatus.REJECTED)

    def test_priority_after_waiting(self) -> None:
        """Тест 10: Длительное ожидание снижает Score (aging), позволяя ручной задаче обогнать новую регламентную."""
        orch = Orchestrator()
        # Блокируем transactions процессом operational_risk (20 мин)
        _, blocker, _ = orch.submit_task("operational_risk", "2026-11-20", RunType.MANUAL, current_time=0)
        # Ручная задача встаёт в очередь на 1-й минуте (w_j = 30)
        _, old_manual, _ = orch.submit_task("liquidity_risk", "2026-11-20", RunType.MANUAL, current_time=1)
        # Новая регламентная задача приходит на 35-й минуте (w_j = 40)
        # К 35-й минуте: Score(old_manual) = 30 + 30 - 1.5 * 34 = 9.0 < Score(new_sched) = 0 + 40 - 0 = 40.0
        _, new_sched, _ = orch.submit_task("credit_risk", "2026-11-20", RunType.SCHEDULED, current_time=35)

        orch.complete_task(blocker.task_id, success=True, current_time=35)

        self.assertEqual(old_manual.status, TaskStatus.RUNNING)
        self.assertEqual(new_sched.status, TaskStatus.QUEUED)

    def test_concurrent_resource_conflicts(self) -> None:
        """Тест 11: Отсутствие конфликтов по ресурсам при конкурентной отправке разных задач из нескольких потоков."""
        orch = Orchestrator()
        processes = [
            ("credit_risk", "2026-11-20"),
            ("market_risk", "2026-11-20"),
            ("liquidity_risk", "2026-11-20"),
            ("operational_risk", "2026-11-20"),
            ("stress_test", "2026-11-20"),
            ("credit_risk", "2026-11-21"),
            ("liquidity_risk", "2026-11-21"),
        ]

        def worker(proc: str, date: str) -> None:
            orch.submit_task(proc, date, RunType.MANUAL, current_time=0)

        threads = [threading.Thread(target=worker, args=(p, d)) for p, d in processes]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        # Проверяем, что ни у каких двух активных задач нет пересечения по ресурсам
        active = orch.active_tasks
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                self.assertTrue(
                    active[i].resources.isdisjoint(active[j].resources),
                    f"Конфликт ресурсов между {active[i].process_name} и {active[j].process_name}",
                )
        self.assertEqual(len(active) + len(orch.queue), len(processes))



if __name__ == "__main__":
    unittest.main()
