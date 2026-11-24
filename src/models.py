from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set
import uuid


class TaskStatus(str, Enum):
    QUEUED = "В очереди"          # Q(t)
    RUNNING = "Выполняется"       # A(t)
    COMPLETED = "Завершено"
    FAILED = "Ошибка"
    REJECTED = "Отклонено (дубль)"


class RunType(str, Enum):
    SCHEDULED = "scheduled"       # Ночной по расписанию
    MANUAL = "manual"             # Ручной днём


# Фиксированные источники данных S(p) для каждого процесса (из 1_generate_data.py)
PROCESS_RESOURCES: Dict[str, Set[str]] = {
    "credit_risk": {"crm", "transactions", "ratings"},
    "market_risk": {"market_data", "limits"},
    "liquidity_risk": {"transactions", "limits"},
    "operational_risk": {"crm", "transactions"},
    "stress_test": {"market_data", "ratings", "limits"},
}

# Базовое чистое время расчёта в минутах (clean_min / base_min)
DEFAULT_PROCESS_DURATION: Dict[str, float] = {
    "credit_risk": 40.0,
    "market_risk": 25.0,
    "liquidity_risk": 30.0,
    "operational_risk": 20.0,
    "stress_test": 60.0,
}


@dataclass
class Task:
    process_name: str
    biz_date: str
    run_type: RunType = RunType.MANUAL
    created_at: float = 0.0                          # t_j (минута поступления заявки)
    estimated_duration: Optional[float] = None       # w_j (прогноз длительности)
    resources: Optional[Set[str]] = None             # R_j = S(p_j)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: TaskStatus = TaskStatus.QUEUED
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        # Приводим run_type к Enum, если передали строкой ("manual" / "scheduled")
        if isinstance(self.run_type, str):
            self.run_type = RunType(self.run_type)

        # Если ресурсы не переданы вручную — берём стандартный набор S(p)
        if self.resources is None:
            if self.process_name not in PROCESS_RESOURCES:
                raise ValueError(f"Неизвестный процесс: {self.process_name}")
            self.resources = set(PROCESS_RESOURCES[self.process_name])
        else:
            self.resources = set(self.resources)

        # Если длительность w_j не передана от ML-модели — берём базовую
        if self.estimated_duration is None:
            self.estimated_duration = DEFAULT_PROCESS_DURATION.get(self.process_name, 30.0)

    @property
    def is_manual(self) -> int:
        return 1 if self.run_type == RunType.MANUAL else 0
