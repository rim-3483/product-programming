import streamlit as st
from datetime import date
import sys
import os
import pandas as pd
import plotly.express as px

# Добавление корня проекта в sys.path. <- нужно, чтобы работали импорты из src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models import RunType, TaskStatus, PROCESS_RESOURCES, DEFAULT_PROCESS_DURATION
from src.orchestrator import Orchestrator

st.set_page_config(layout="wide", page_title="Оркестратор Рисков")

@st.cache_resource
def get_orchestrator():
    return Orchestrator()

orch = get_orchestrator()

# Получение среза состояния
snapshot = orch.get_state_snapshot()
current_time = snapshot["current_time"]
busy_resources = set(snapshot["busy_resources"])

st.title("Оркестратор параллельных расчётов рисков")

# Панель 1 и 2: Верхний ряд
col1, col2 = st.columns([1, 1.5])

with col1:
    st.subheader("1. Новая заявка")
    with st.form("new_task_form"):
        process_name = st.selectbox("Процесс", list(PROCESS_RESOURCES.keys()))
        biz_date = st.date_input("Отчётная дата", value=date.today())
        run_type = st.radio(
            "Тип запуска",
            [RunType.SCHEDULED, RunType.MANUAL],
            format_func=lambda x: x.value
        )

        # Preview
        res_list = ", ".join(sorted(PROCESS_RESOURCES[process_name]))
        dur = DEFAULT_PROCESS_DURATION.get(process_name, 30.0)
        st.caption(f"Источники: {res_list}")
        st.caption(f"Прогноз длительности: ~{dur} мин")

        submitted = st.form_submit_button("Отправить", type="primary")

        if submitted:
            ok, task, msg = orch.submit_task(
                process_name=process_name,
                biz_date=str(biz_date),
                run_type=run_type,
                current_time=current_time
            )
            st.toast(msg, icon="✅" if ok else "⚠️")
            st.rerun()

with col2:
    st.subheader("2. Источники и активные задачи")

    # отбор уникальных источников из конфигурации
    all_sources = sorted(set().union(*PROCESS_RESOURCES.values()))

    for src in all_sources:
        if src in busy_resources:
            # поиск: какая именно задача держит конкретный ресурс
            holder = next((t for t in snapshot["active"] if src in t.resources), None)
            if holder:
                rem = max(0, int(holder.started_at + holder.estimated_duration - current_time))
                st.markdown(f"🔴 **{src}** — {holder.process_name} {holder.biz_date} · {holder.task_id} · ~{rem} мин")
            else:
                st.markdown(f"🔴 **{src}** — занят")
        else:
            st.markdown(f"🟢 **{src}** — свободен")

    if snapshot["active"]:
        st.divider()
        st.markdown("**Текущие активные задачи (A(t)):**")
        for t in snapshot["active"]:
            rem = max(0, int(t.started_at + t.estimated_duration - current_time))
            st.caption(f"⚙️ {t.process_name} {t.biz_date} · {t.run_type.value} · ~{rem} мин · {t.task_id}")
    else:
        st.info("Нет активных задач")

# Панель 3.1: Очередь
st.divider()
st.subheader("3. Очередь (Q(t))")

if not snapshot["queue"]:
    st.info("Очередь пуста")
else:
    queue_data = []
    for i, t in enumerate(snapshot["queue"]):
        wait = max(0, int(current_time - t.created_at))
        score = round(orch.calculate_score(t), 1)
        blocked = t.resources & busy_resources
        blocked_str = ", ".join(sorted(blocked)) if blocked else "—"

        queue_data.append({
            "#": i + 1,
            "Задача": f"{t.process_name} {t.biz_date}",
            "Тип": t.run_type.value,
            "w (мин)": t.estimated_duration,
            "Ждёт (мин)": wait,
            "Score": score,
            "Блокирует": blocked_str
        })

    st.dataframe(queue_data, use_container_width=True, hide_index=True)

# Панель 3.2 (Диаграмма Ганта)
st.divider()
st.subheader("Диаграмма выполнения задач:")

# Сбор данных для диаграммы из активных задач и истории
gantt_data = []

# 1. Выбор все еще активных задач (конец = текущее время + остаток)
for t in snapshot["active"]:
    if t.started_at is not None:
        gantt_data.append({
            "Задача": f"{t.process_name} {t.biz_date}",
            "Начало": t.started_at,
            "Конец": t.started_at + t.estimated_duration,
            "Статус": "В процессе",
            "Тип": t.run_type.value
        })

# 2. Выбор завершенных задач из истории
for t in snapshot["history"]:
    if t.status in [TaskStatus.COMPLETED, TaskStatus.FAILED] and t.started_at is not None and t.finished_at is not None:
        gantt_data.append({
            "Задача": f"{t.process_name} {t.biz_date}",
            "Начало": t.started_at,
            "Конец": t.finished_at,
            "Статус": t.status.value,
            "Тип": t.run_type.value
        })

if not gantt_data:
    st.info("Нет данных для отображения. Запустите задачи.")
else:
    df_gantt = pd.DataFrame(gantt_data)

    fig = px.timeline(
        df_gantt,
        x_start="Начало",
        x_end="Конец",
        y="Задача",
        color="Статус",
        hover_data=["Тип"],
        color_discrete_map={
            "В процессе": "#FFA500",
            "Завершено": "#2E8B57",
            "Ошибка": "#DC143C"
        }
    )

    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title_text="Модельное время (мин)")

# чтобы убрать лишние отступы
    fig.update_layout(
        margin=dict(l=20, r=20, t=20, b=20),
        height=300 + (len(df_gantt["Задача"].unique()) * 30)
    )

    st.plotly_chart(fig, use_container_width=True)

# Панель 4: Журнал
st.divider()
st.subheader("4. Журнал")

if not snapshot["history"]:
    st.info("Журнал пуст")
else:
    log_lines = []
    for t in snapshot["history"]:
        t_str = f"[{t.finished_at:>4.0f} мин]" if t.finished_at is not None else f"[{t.created_at:>4.0f} мин]"

        if t.status == TaskStatus.REJECTED:
            log_lines.append(f"{t_str} {t.process_name} {t.biz_date} — ОТКЛОНЕНО (дубль)")
        elif t.status == TaskStatus.COMPLETED:
            log_lines.append(f"{t_str} {t.process_name} {t.biz_date} — Завершено (старт: {t.started_at:>4.0f})")
        elif t.status == TaskStatus.FAILED:
            log_lines.append(f"{t_str} {t.process_name} {t.biz_date} — ОШИБКА: {t.error_message}")

    st.code("\n".join(log_lines[::-1]), language="text")

# Управление временем: Улучшенное
st.divider()
st.subheader("Управление временем")

# Верхняя строка: текущее время и быстрые кнопки
col_time_display, col_btn1, col_btn2, col_btn3 = st.columns([1.5, 1, 1, 2])

with col_time_display:
    st.metric("Текущее время (t)", f"{current_time:.0f} мин")

with col_btn1:
    if st.button("+ 1 минута", use_container_width=True):
        orch.advance_time(1)
        st.rerun()

with col_btn2:
    if st.button("+ 10 минут", use_container_width=True):
        orch.advance_time(10)
        st.rerun()

with col_btn3:
    # Логика "До следующего завершения"
    active_tasks = snapshot["active"]
    if active_tasks:
        # Вычисление ближайшего времени до завершения задачи
        next_finish_time = min(t.started_at + t.estimated_duration for t in active_tasks)
        # Вычисление разницы между этим временем и текущим
        delta = max(0.1, next_finish_time - current_time)  # 0.1 чтобы избежать advance_time(0)

        if st.button(f"→ До след. завершения (~{delta:.0f} мин)", use_container_width=True, type="primary"):
            orch.advance_time(delta)
            st.rerun()
    else:
        # Если активных задач нет, кнопка неактивна
        st.button("→ До след. завершения (нет задач)", use_container_width=True, disabled=True)

# Нижняя строка: ручной ввод
with st.expander("Ручной сдвиг времени"):
    with st.form("time_form"):
        minutes = st.number_input("Сдвинуть на (мин)", min_value=1.0, value=10.0, step=1.0)
        if st.form_submit_button("Применить"):
            orch.advance_time(minutes)
            st.rerun()