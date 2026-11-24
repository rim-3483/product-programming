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


if __name__ == "__main__":
    unittest.main()
