"""Streamlit-интерфейс агента и аналитического дашборда."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.agent import ROLE_DEAN, ROLE_STUDENT, ROLE_TEACHER, RiskAgent
from src.config import DB_PATH, FIGURE_DIR, METRICS_PATH, PROCESSED_DIR, PROJECT_ROOT
from src.tools import AnalyticsTools, recommendations_from_factors

st.set_page_config(
    page_title="Академический навигатор",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
:root { --navy:#0b1220; --blue:#2563eb; --cyan:#06b6d4; --red:#ef4444; --amber:#f59e0b; }
.stApp { background: linear-gradient(180deg, #f8fafc 0%, #ffffff 44%); }
.block-container { padding-top: 1.65rem; padding-bottom: 3rem; max-width: 1440px; }
[data-testid="stSidebar"] { background: #0b1220; }
[data-testid="stSidebar"] * { color: #e2e8f0; }
[data-testid="stSidebar"] [data-baseweb="select"] * { color: #0f172a; }
.hero { background: radial-gradient(circle at 90% 10%, rgba(6,182,212,.22), transparent 28%), linear-gradient(135deg,#0b1220,#172554 68%,#164e63); color:white; border-radius:22px; padding:28px 32px; margin-bottom:18px; box-shadow:0 18px 40px rgba(15,23,42,.18); }
.hero h1 { margin:0 0 8px; font-size:2.15rem; letter-spacing:-.03em; }
.hero p { color:#cbd5e1; margin:0; font-size:1.03rem; max-width:850px; }
.eyebrow { color:#67e8f9; text-transform:uppercase; letter-spacing:.16em; font-weight:700; font-size:.72rem; margin-bottom:8px; }
.kpi { background:white; border:1px solid #e2e8f0; border-radius:16px; padding:16px 18px; box-shadow:0 7px 20px rgba(15,23,42,.05); min-height:104px; }
.kpi .label { color:#64748b; font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; font-weight:650; }
.kpi .value { color:#0f172a; font-size:1.72rem; font-weight:760; margin-top:8px; }
.kpi .hint { color:#94a3b8; font-size:.78rem; margin-top:2px; }
.risk-low { color:#059669; } .risk-medium { color:#d97706; } .risk-high { color:#dc2626; }
.note { border-left:4px solid #06b6d4; background:#ecfeff; border-radius:0 12px 12px 0; padding:12px 16px; color:#164e63; margin:10px 0; }
.small-muted { color:#64748b; font-size:.82rem; }
[data-testid="stMetric"] { background:#fff; border:1px solid #e2e8f0; padding:14px; border-radius:14px; }
.stTabs [data-baseweb="tab-list"] { gap:7px; }
.stTabs [data-baseweb="tab"] { border-radius:11px; padding:8px 15px; background:#f1f5f9; }
.stTabs [aria-selected="true"] { background:#dbeafe; color:#1d4ed8; }
</style>
""",
    unsafe_allow_html=True,
)

if not DB_PATH.exists() or not METRICS_PATH.exists():
    st.error("Проект ещё не подготовлен. Выполните `python scripts/run_pipeline.py` из корня репозитория.")
    st.stop()

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "agent" not in st.session_state:
    st.session_state.agent = RiskAgent(session_id=st.session_state.session_id)
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Здравствуйте! Я помогу интерпретировать академические риски. Спросите общую сводку, карточку студента, сведения о группе или качество модели.",
        }
    ]

tools = AnalyticsTools()
agent: RiskAgent = st.session_state.agent
students = tools.list_students()

with st.sidebar:
    st.markdown("## ◈ Навигатор")
    st.caption("Раннее выявление риска · учебный прототип")
    st.divider()
    role = st.selectbox("Роль пользователя", [ROLE_DEAN, ROLE_TEACHER, ROLE_STUDENT], help="В прототипе это демонстрация RBAC, а не полноценная аутентификация.")
    own_student_id: str | None = None
    if role == ROLE_STUDENT:
        labels = {row.student_id: f"{row.student_id} · {row.full_name}" for row in students.itertuples()}
        own_student_id = st.selectbox("Моя учетная запись", list(labels), format_func=lambda value: labels[value])
    st.divider()
    llm_ok, llm_text = agent.llm.status()
    st.markdown(f"**Режим генерации**  \n{'🟢' if llm_ok else '⚪'} {llm_text}")
    st.caption("Все числа всегда извлекаются детерминированными SQL-инструментами.")
    st.divider()
    st.markdown("**Контрольная дата данных**  \n30 апреля 2026")
    st.markdown("**Набор данных**  \nСинтетический · seed 42")
    st.caption("Персональные данные реальных людей не используются.")

overview = tools.overview()
st.markdown(
    """
<div class="hero">
  <div class="eyebrow">Управление данными · 09.03.03</div>
  <h1>Академический навигатор</h1>
  <p>Интеллектуальный агент раннего предупреждения: объединяет данные деканата, LMS и посещаемости, оценивает риск и предлагает проверяемые действия поддержки.</p>
</div>
""",
    unsafe_allow_html=True,
)

kpi_cols = st.columns(4)
kpis = [
    ("Студентов", f"{overview['students']}", f"{overview['groups']} учебных групп", ""),
    ("Высокий риск", f"{overview['high_risk']}", f"{overview['high_risk']/max(overview['students'],1):.1%} выборки", "risk-high"),
    ("Посещаемость", f"{overview['attendance_rate']:.1%}", "среднее значение", ""),
    ("Промежуточный балл", f"{overview['midterm_avg']:.1f}", "из 100", ""),
]
for column, (label, value, hint, css) in zip(kpi_cols, kpis):
    column.markdown(f'<div class="kpi"><div class="label">{label}</div><div class="value {css}">{value}</div><div class="hint">{hint}</div></div>', unsafe_allow_html=True)

agent_tab, student_tab, dashboard_tab, model_tab, quality_tab, about_tab = st.tabs(
    ["✦ Агент", "◎ Карточка", "▦ Дашборд", "◫ Модель", "✓ Качество данных", "ⓘ О проекте"]
)

with agent_tab:
    left, right = st.columns([1.9, 1], gap="large")
    with left:
        st.subheader("Диалог с данными")
        st.caption("Агент выбирает разрешённый инструмент, получает проверенный контекст и только затем формирует ответ.")
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        prompt = st.chat_input("Например: покажи топ 5 студентов с высоким риском")
        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Запрашиваю данные и проверяю ограничения…"):
                    response = agent.ask(prompt, role=role, own_student_id=own_student_id)
                st.markdown(response.answer)
                if response.sources:
                    st.caption("Источники: " + ", ".join(response.sources) + (" · текст: Ollama" if response.llm_used else " · текст: шаблонный режим"))
            st.session_state.messages.append({"role": "assistant", "content": response.answer})
    with right:
        st.subheader("Быстрые запросы")
        suggestions = ["Покажи общую сводку", "Сводка по группе ПИ-401", "Покажи топ 5 студентов с высоким риском", "Какое качество модели?"]
        if role == ROLE_STUDENT:
            suggestions = ["Какой мой риск?", "Что мне делать?", "Какое качество модели?"]
        for suggestion in suggestions:
            if st.button(suggestion, use_container_width=True, key=f"suggest_{suggestion}"):
                response = agent.ask(suggestion, role=role, own_student_id=own_student_id)
                st.session_state.messages.extend([{"role": "user", "content": suggestion}, {"role": "assistant", "content": response.answer}])
                st.rerun()
        st.markdown('<div class="note"><b>Граница применения</b><br>Прогноз используется только для ранней поддержки. Автоматические санкции и решения об отчислении запрещены.</div>', unsafe_allow_html=True)
        with st.expander("Как устроен запрос"):
            st.markdown("1. Классификация намерения.\n2. Проверка роли.\n3. Параметризованный SQL-инструмент.\n4. Формирование проверенного контекста.\n5. Шаблон или локальная LLM.\n6. Запись обезличенного технического журнала.")

with student_tab:
    st.subheader("Индивидуальная карточка раннего предупреждения")
    if role == ROLE_STUDENT:
        selected_student = own_student_id
    else:
        student_labels = {row.student_id: f"{row.student_id} · {row.full_name} · {row.group_name}" for row in students.itertuples()}
        selected_student = st.selectbox("Студент", list(student_labels), format_func=lambda value: student_labels[value], key="card_student")
    card = tools.student_card(selected_student) if selected_student else None
    if card:
        gauge_col, detail_col = st.columns([1, 1.45], gap="large")
        with gauge_col:
            color = "#ef4444" if card["risk_level"] == "Высокий" else "#f59e0b" if card["risk_level"] == "Средний" else "#10b981"
            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=card["risk_probability"] * 100,
                number={"suffix": "%", "font": {"size": 42, "color": "#0f172a"}},
                title={"text": f"{card['risk_level']} риск", "font": {"size": 18}},
                gauge={
                    "axis": {"range": [0, 100]}, "bar": {"color": color},
                    "steps": [{"range": [0, 35], "color": "#d1fae5"}, {"range": [35, 65], "color": "#fef3c7"}, {"range": [65, 100], "color": "#fee2e2"}],
                    "threshold": {"line": {"color": "#0f172a", "width": 3}, "value": 65},
                },
            ))
            fig.update_layout(height=310, margin=dict(l=35, r=35, t=60, b=20), paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Вероятность модели, а не вероятность отчисления. Порог высокого уровня на дашборде — 65%.")
        with detail_col:
            st.markdown(f"### {card['full_name']}")
            st.caption(f"{card['student_id']} · {card['group_name']}")
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Посещаемость", f"{card['attendance_rate']:.1%}")
            mc2.metric("Промеж. балл", f"{card['midterm_avg']:.1f}")
            mc3.metric("Работы вовремя", f"{card['submission_on_time_rate']:.1%}")
            st.markdown("**Факторы, повышающие риск**")
            for factor in card["top_factors"]:
                st.markdown(f"- {factor['label']}: **{factor['value']:.2f}** — {factor['effect']}")
            st.markdown("**План поддержки**")
            for index, action in enumerate(recommendations_from_factors(card["top_factors"]), 1):
                st.markdown(f"{index}. {action}")
            st.info("Объяснение локальное и приближённое: оно сочетает глобальную permutation importance и отклонение показателя от медианы.")

with dashboard_tab:
    st.subheader("Мониторинг академического риска")
    predictions = tools.all_predictions()
    groups = ["Все группы"] + sorted(predictions["group_name"].unique().tolist())
    selected_group = st.selectbox("Фильтр по группе", groups)
    view = predictions if selected_group == "Все группы" else predictions[predictions["group_name"] == selected_group]

    c1, c2 = st.columns([1, 1.65], gap="large")
    with c1:
        order = ["Низкий", "Средний", "Высокий"]
        risk_counts = view["risk_level"].value_counts().reindex(order, fill_value=0).rename_axis("Уровень").reset_index(name="Студентов")
        fig = px.pie(risk_counts, values="Студентов", names="Уровень", hole=0.65, color="Уровень", color_discrete_map={"Низкий": "#10b981", "Средний": "#f59e0b", "Высокий": "#ef4444"})
        fig.update_layout(title="Структура уровней риска", height=390, margin=dict(t=55, b=20, l=10, r=10), legend_orientation="h")
        fig.update_traces(textposition="inside", textinfo="percent+value")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        group_table = tools.group_table()
        fig = px.bar(group_table, x="Группа", y="Средний риск", color="Высокий риск", color_continuous_scale=["#bfdbfe", "#2563eb", "#ef4444"], text="Высокий риск", title="Средняя вероятность и число студентов высокого риска")
        fig.update_yaxes(tickformat=".0%", range=[0, max(0.75, group_table["Средний риск"].max() * 1.18)])
        fig.update_layout(height=390, margin=dict(t=55, b=20, l=10, r=10), coloraxis_colorbar_title="Высокий<br>риск")
        st.plotly_chart(fig, use_container_width=True)

    fig = px.scatter(view, x="attendance_rate", y="midterm_avg", color="risk_level", hover_data=["student_id", "full_name", "group_name", "risk_probability"], color_discrete_map={"Низкий": "#10b981", "Средний": "#f59e0b", "Высокий": "#ef4444"}, category_orders={"risk_level": ["Низкий", "Средний", "Высокий"]}, title="Карта ранних индикаторов")
    fig.update_xaxes(title="Посещаемость", tickformat=".0%")
    fig.update_yaxes(title="Промежуточный балл")
    fig.update_layout(height=440, legend_title="Уровень риска")
    st.plotly_chart(fig, use_container_width=True)

    if role != ROLE_STUDENT:
        st.markdown("#### Приоритетный список")
        high = view[view["risk_level"] == "Высокий"].copy()
        high["risk_probability"] = high["risk_probability"].map(lambda x: f"{x:.1%}")
        high["attendance_rate"] = high["attendance_rate"].map(lambda x: f"{x:.1%}")
        st.dataframe(high[["student_id", "full_name", "group_name", "risk_probability", "attendance_rate", "midterm_avg"]], hide_index=True, use_container_width=True, column_config={"student_id": "ID", "full_name": "ФИО", "group_name": "Группа", "risk_probability": "Риск", "attendance_rate": "Посещаемость", "midterm_avg": st.column_config.NumberColumn("Промеж. балл", format="%.1f")})
    else:
        st.info("В роли студента списки других обучающихся скрыты.")

    if role == ROLE_DEAN:
        with st.expander("Техническая активность прототипа"):
            activity = tools.query_activity()
            if activity.empty:
                st.caption("Запросов пока нет.")
            else:
                st.dataframe(activity, hide_index=True, use_container_width=True)

with model_tab:
    st.subheader("Оценка модели и интерпретация")
    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    test = metrics["test"]
    cols = st.columns(5)
    for col, label, value in zip(cols, ["F1", "Recall", "Precision", "ROC-AUC", "Brier"], [test["f1"], test["recall"], test["precision"], test["roc_auc"], test["brier"]]):
        col.metric(label, f"{value:.3f}")
    st.caption(f"Выбран: {metrics['selected_model']} · порог {metrics['threshold']:.2f} · тест {metrics['dataset']['test_rows']} наблюдений · seed {metrics['dataset']['seed']}")
    img1, img2 = st.columns(2)
    with img1:
        st.image(str(FIGURE_DIR / "confusion_matrix.png"), caption="Матрица ошибок")
    with img2:
        st.image(str(FIGURE_DIR / "roc_curve.png"), caption="ROC-кривая")
    st.image(str(FIGURE_DIR / "feature_importance.png"), caption="Permutation importance", width=920)
    with st.expander("Сравнение кандидатов на validation"):
        rows = []
        for name, values in metrics["validation"].items():
            rows.append({"Модель": name, "F1": values["f1"], "Recall": values["recall"], "Precision": values["precision"], "ROC-AUC": values["roc_auc"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.warning("Метрики рассчитаны на синтетических данных. Перед реальным применением необходимы внешняя валидация, анализ справедливости и мониторинг дрейфа.")

with quality_tab:
    st.subheader("Контроль качества и происхождение данных")
    summary = json.loads((PROCESSED_DIR / "etl_summary.json").read_text(encoding="utf-8"))
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Источников", "3 системы")
    q2.metric("Проверок", summary["quality_checks"])
    q3.metric("Выявлено проблем", summary["quality_issues_detected"])
    q4.metric("Ошибок FK", summary["foreign_key_errors"])
    st.image(str(FIGURE_DIR / "data_quality.png"), caption="Проблемные записи по исходным файлам", width=900)
    quality = tools.quality_log()
    st.dataframe(quality, hide_index=True, use_container_width=True, column_config={"source_name": "Источник", "check_name": "Проверка", "affected_rows": "Затронуто", "action_taken": "Действие"})
    st.markdown("**Загруженные таблицы**")
    st.json(summary["loaded_rows"], expanded=False)

with about_tab:
    st.subheader("Архитектура решения")
    a1, a2 = st.columns(2, gap="large")
    with a1:
        architecture = PROJECT_ROOT / "docs" / "architecture.svg"
        if architecture.exists():
            st.image(str(architecture), caption="Архитектура конвейера")
    with a2:
        erd = PROJECT_ROOT / "docs" / "er_diagram.svg"
        if erd.exists():
            st.image(str(erd), caption="Упрощённая ER-диаграмма")
    st.markdown("""
#### Принципы
- **Воспроизводимость:** фиксированный seed, единый конвейер и сохранённые разбиения.
- **Проверяемость:** LLM не пишет SQL и получает только результат разрешённого инструмента.
- **Минимизация данных:** пол и возраст не используются моделью; итоговые оценки исключены из признаков.
- **Human-in-the-loop:** прогноз инициирует проверку и поддержку, а не административное решение.
- **Локальный режим:** проект работает без API; при необходимости подключается Ollama.
""")
    st.markdown('<div class="note"><b>Учебный статус</b><br>Все ФИО, события и оценки синтетические. Проект не готов к принятию решений в реальном вузе без правовой, этической и статистической валидации.</div>', unsafe_allow_html=True)
