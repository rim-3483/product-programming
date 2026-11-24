import streamlit as st
from datetime import date
import sys
import os

#чтобы работали импорты из src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models import RunType, TaskStatus, PROCESS_RESOURCES, DEFAULT_PROCESS_DURATION
from src.orchestrator import Orchestrator

st.set_page_config(layout="wide", page_title="Оркестратор Рисков")

# Инициализация в сессии
if "orch" not in st.session_state:
    st.session_state.orch = Orchestrator()

orch = st.session_state.orch

# Получение среза состояния
snapshot = orch.get_state_snapshot()
current_time = snapshot["current_time"]
busy_resources = set(snapshot["busy_resources"])

st.title("Оркестратор параллельных расчётов рисков")

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

        # Preview (что занято, сколько времени на это что-то уйдет)
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

    all_sources = sorted(set().union(*PROCESS_RESOURCES.values()))

    for src in all_sources:
        if src in busy_resources:
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

    # Вывод в обратном порядке
    st.code("\n".join(log_lines[::-1]), language="text")

st.divider()
st.subheader("Управление временем")
col_t1, col_t2 = st.columns([1, 1])

with col_t1:
    st.metric("Текущее время (t)", f"{current_time:.0f} мин")

with col_t2:
    with st.form("time_form"):
        minutes = st.number_input("advance_time, мин", min_value=1.0, value=10.0, step=1.0)
        if st.form_submit_button("Применить сдвиг времени", type="primary"):
            orch.advance_time(minutes)
            st.rerun()