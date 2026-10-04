# -*- coding: utf-8 -*-
"""
学生端页面
"""

import os
import secrets
from datetime import datetime
from html import escape

import streamlit as st
import ai_config
from gel_image_ui import render_student_panel
from branding import PRODUCT_NAME

from core import (
    DB_PATH,
    ABNORMALITY_OPTIONS,
    apply_common_styles,
    build_diagnosis_context,
    build_case_summary,
    build_evidence_summary,
    compute_confidence_level,
    diagnose,
    detect_missing_key_info,
    ensure_page_config,
    format_diagnosis_result_text,
    init_database,
    load_student_record,
    is_classroom_record,
    parse_candidate_result_item,
    parse_all_candidates,
    parse_followup_data,
    render_card_title,
    render_page_hero,
    return_to_home,
    save_diagnosis_record,
    save_followup_reassessment,
    save_student_revision,
    save_uploaded_image,
    validate_uploaded_image,
    save_verification_plan,
    extract_text_clues_with_fallback,
)
from diagnosis_normalization import STANDARD_TEXT_HINTS, build_normalized_case
from evidence_support import load_course_presets, parse_json, template_mass_ng, validate_experiment_parameters
from followup_agent import apply_followup_choices, interpret_operation_text, plan_followup_questions


STUDENT_FORM_DEFAULTS = {
    "student_form_abnormality": "无条带",
    "student_form_template_amount": None,
    "student_form_annealing_temp": None,
    "student_form_cycles": None,
    "student_form_positive_control_normal": "未观察",
    "student_form_negative_control_band": "未观察",
    "student_form_description": "",
    "student_form_initial_hypothesis": "",
    **{f"student_form_{k}": "" for k in ("course_name", "class_name", "experiment_name", "group_code", "polymerase", "lane_notes")},
    **{f"student_form_{k}": None for k in ("template_concentration", "reaction_volume", "target_size", "recommended_temp")},
    "student_form_template_type": "待确认",
    "student_form_confirmed_hints": [],
    "student_form_data_origin": "真实课堂",
    "student_form_local_mode": False,
}

STUDENT_FORM_STATE_VERSION = 4

STUDENT_STEP_TITLES = [
    "实验现象与对照",
    "PCR 关键参数",
    "描述与图片",
    "确认并诊断",
]


def parameter_text(value, unit=""):
    """参数缺失时显示待填写，保留原始输入的空值。"""
    return "待填写" if value is None else f"{value} {unit}".strip()


def render_student_refined_styles():
    """页面样式由 core.apply_common_styles 统一注入。"""
    return


class SessionUploadedFile:
    """把上传图片以会话内字节流形式暂存，便于步骤切换后复用"""

    def __init__(self, name, data):
        self.name = name
        self._data = data

    def getbuffer(self):
        return memoryview(self._data)


def html_text(value):
    """把动态值转成安全的 HTML 文本，避免页面把用户输入当成标签解析。"""
    return escape(str(value), quote=True)


def render_scoring_detail(detail, fallback_score):
    """渲染打分明细（简化复用）"""
    st.markdown(f"- 基础分：{detail.get('基础分', 0)}")

    pos = detail.get("阳性对照", {})
    st.markdown(
        f"- 阳性对照：{'命中' if pos.get('命中') else '未命中'}，"
        f"{'加分' + str(pos.get('加分', 0)) if pos.get('加分', 0) else '不加分'}"
    )

    neg = detail.get("阴性对照", {})
    st.markdown(
        f"- 阴性对照：{'命中' if neg.get('命中') else '未命中'}，"
        f"{'加分' + str(neg.get('加分', 0)) if neg.get('加分', 0) else '不加分'}"
    )

    tpl = detail.get("模板量范围", {})
    st.markdown(
        f"- 模板量范围：{'命中' if tpl.get('命中') else '未命中'}，"
        f"{'加分' + str(tpl.get('加分', 0)) if tpl.get('加分', 0) else '不加分'}"
    )

    tmp = detail.get("退火温度范围", {})
    st.markdown(
        f"- 退火温度范围：{'命中' if tmp.get('命中') else '未命中'}，"
        f"{'加分' + str(tmp.get('加分', 0)) if tmp.get('加分', 0) else '不加分'}"
    )

    cyc = detail.get("循环数范围", {})
    st.markdown(
        f"- 循环数范围：{'命中' if cyc.get('命中') else '未命中'}，"
        f"{'加分' + str(cyc.get('加分', 0)) if cyc.get('加分', 0) else '不加分'}"
    )

    txt = detail.get("文本线索", {})
    extracted = txt.get("抽取线索", [])
    hit = txt.get("命中线索", [])
    st.markdown(f"- 文本线索抽取：{('、'.join(extracted)) if extracted else '无'}")
    st.markdown(f"- 文本线索命中：{('、'.join(hit)) if hit else '无'}")
    st.markdown(
        f"- 文本线索加分："
        f"{'加分' + str(txt.get('加分', 0)) if txt.get('加分', 0) else '不加分'}"
    )

    st.markdown(f"- 最终总分：{detail.get('最终总分', fallback_score)}")

# --- 新增：持久化同步函数 ---
def sync_val(key):
    """组件值变化时，立刻同步到持久化字典中"""
    if key in st.session_state:
        st.session_state["student_data_storage"][key] = st.session_state[key]
    if key == "student_form_description":
        st.session_state["student_form_confirmed_hints"] = []
        st.session_state["student_data_storage"]["student_form_confirmed_hints"] = []
# ----------------------------


def restore_widget_value_from_storage(key):
    """渲染步骤前从持久区恢复控件值，避免步骤切换后表单与摘要不同步。"""
    storage = st.session_state.get("student_data_storage", {})
    if key in storage:
        st.session_state[key] = storage[key]


def init_student_wizard_state():
    """初始化学生端向导状态"""
    # 新增：建立独立于组件生命周期的持久化存储区
    if "student_data_storage" not in st.session_state:
        st.session_state["student_data_storage"] = STUDENT_FORM_DEFAULTS.copy()

    for key, value in STUDENT_FORM_DEFAULTS.items():
        st.session_state["student_data_storage"].setdefault(key, value)
    st.session_state["student_form_state_version"] = STUDENT_FORM_STATE_VERSION
    # 关键修复：将被 Streamlit 自动销毁的组件数据，从持久化字典中恢复出来
    for key, value in st.session_state["student_data_storage"].items():
        if key not in st.session_state:
            st.session_state[key] = value

    if "student_current_step" not in st.session_state:
        st.session_state["student_current_step"] = 1
    if "student_last_payload" not in st.session_state:
        st.session_state["student_last_payload"] = None
    if "student_uploaded_image_bytes" not in st.session_state:
        st.session_state["student_uploaded_image_bytes"] = None
    if "student_uploaded_image_name" not in st.session_state:
        st.session_state["student_uploaded_image_name"] = ""
    if "student_uploaded_image_type" not in st.session_state:
        st.session_state["student_uploaded_image_type"] = ""
    if "student_show_result_report" not in st.session_state:
        st.session_state["student_show_result_report"] = bool(st.session_state.get("student_last_payload"))


def clear_followup_widget_state():
    for key in list(st.session_state):
        if key.startswith("student_followup_"):
            del st.session_state[key]


def clear_student_uploaded_image():
    """清空暂存图片"""
    st.session_state["student_uploaded_image_bytes"] = None
    st.session_state["student_uploaded_image_name"] = ""
    st.session_state["student_uploaded_image_type"] = ""
    st.session_state.pop("student_form_gel_image_file", None)


def reset_student_form_state(overrides=None, target_step=None):
    """按默认值重置学生端表单状态。"""
    form_values = dict(STUDENT_FORM_DEFAULTS)
    if overrides:
        form_values.update(overrides)

    for key, value in form_values.items():
        # 同时重置持久化字典和当前 session 键
        st.session_state["student_data_storage"][key] = value
        st.session_state[key] = value

    if target_step is None:
        target_step = st.session_state.get("student_current_step", 1)
    st.session_state["student_current_step"] = target_step
    st.session_state["student_last_payload"] = None
    st.session_state["student_show_result_report"] = False
    st.session_state.pop("student_access_code", None)
    clear_followup_widget_state()
    clear_student_uploaded_image()
    st.session_state.pop("student_extraction_evidence", None)


def render_student_quick_actions():
    """渲染学生端实验记录指引。"""
    st.markdown(
        """
        <div class="pcr-student-guide">
            <div>
                <div class="pcr-student-guide-title">按步骤填写实验信息</div>
                <p class="pcr-student-guide-desc">可随时返回前一步调整信息，确认后再生成诊断结果。</p>
            </div>
            <span class="pcr-student-guide-chip">信息核对</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_student_topbar():
    """渲染页面内顶部导航。"""
    with st.container(key="pcr_student_topbar_row"):
        left_col, right_col = st.columns([0.78, 0.22])
        with left_col:
            st.markdown(
                """
                <div class="pcr-student-topbar">
                    <span class="pcr-student-page-label">实验诊断页面</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right_col:
            with st.container(key="pcr_student_return"):
                if st.button("返回首页", key="student_return_home", use_container_width=True):
                    return_to_home(clear_entries=False)


def persist_uploaded_file(uploaded_file):
    """把上传文件保存到 session_state，避免切步后丢失"""
    if uploaded_file is None:
        return
    error = validate_uploaded_image(uploaded_file)
    if error:
        st.session_state["student_uploaded_image_bytes"] = None
        st.session_state["student_uploaded_image_name"] = ""
        st.session_state["student_uploaded_image_type"] = ""
        st.warning(error)
        return
    st.session_state["student_uploaded_image_bytes"] = uploaded_file.getvalue()
    st.session_state["student_uploaded_image_name"] = uploaded_file.name
    st.session_state["student_uploaded_image_type"] = getattr(uploaded_file, "type", "")


def get_persisted_uploaded_file():
    """取回会话中暂存的上传文件"""
    image_bytes = st.session_state.get("student_uploaded_image_bytes")
    image_name = st.session_state.get("student_uploaded_image_name", "")
    if image_bytes and image_name:
        return SessionUploadedFile(image_name, image_bytes)
    return None


def collect_student_form_payload():
    storage = st.session_state["student_data_storage"]
    return {**{key.removeprefix("student_form_"): storage.get(key) for key in STUDENT_FORM_DEFAULTS
               if key not in {"student_form_initial_hypothesis"}},
            "gel_image_file": get_persisted_uploaded_file()}



def render_student_readiness_panel():
    """渲染诊断准备度侧栏，帮助学生确认关键证据是否齐全。"""
    form_data = collect_student_form_payload()
    current_step = st.session_state.get("student_current_step", 1)
    has_description = bool(str(form_data["description"]).strip())
    has_image = bool(form_data["gel_image_file"])
    readiness_items = [
        ("实验现象", form_data["abnormality"] or "待填写", bool(form_data["abnormality"])),
        (
            "对照结果",
            f"阳性{form_data['positive_control_normal']} / 阴性{form_data['negative_control_band']}",
            form_data["positive_control_normal"] in {"是", "否"} and form_data["negative_control_band"] in {"是", "否"},
        ),
        (
            "PCR 参数",
            " / ".join(parameter_text(form_data.get(field), unit) for field, unit in [("template_amount", "μL"), ("annealing_temp", "℃"), ("cycles", "次")]),
            all(form_data.get(k) is not None for k in ("template_amount", "annealing_temp", "cycles")),
        ),
        ("补充描述", "已填写" if has_description else "可选补充", has_description),
        ("凝胶图片", "已上传" if has_image else "未上传", has_image),
        ("诊断触发", "确认信息后生成" if current_step < 4 else "可以生成诊断", current_step >= 4),
    ]
    cards = [
        (
            '<div class="pcr-readiness-item">'
            f'<span class="pcr-readiness-dot {"done" if is_ready else ""}"></span>'
            "<div>"
            f'<div class="pcr-readiness-label">{html_text(label)}</div>'
            f'<div class="pcr-readiness-value">{html_text(value)}</div>'
            "</div>"
            "</div>"
        )
        for label, value, is_ready in readiness_items
    ]
    st.markdown(
        f"""
        <div class="pcr-readiness-panel">
            <div class="pcr-readiness-title">诊断准备度</div>
            <p class="pcr-readiness-desc">系统将根据已填写信息生成候选原因。</p>
            <div class="pcr-readiness-grid">{''.join(cards)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    payload = st.session_state.get("student_last_payload")
    if payload and payload.get("results"):
        top1 = payload["results"][0]
        st.markdown(
            f"""
            <div class="pcr-readiness-panel">
                <div class="pcr-readiness-title">最近一次诊断</div>
                <div class="pcr-readiness-item">
                    <span class="pcr-readiness-dot done"></span>
                    <div>
                        <div class="pcr-readiness-label">首要候选原因</div>
                        <div class="pcr-readiness-value">{html_text(top1.get('原因', '-'))}</div>
                    </div>
                </div>
                <div class="pcr-readiness-item" style="margin-top:0.5rem;">
                    <span class="pcr-readiness-dot {'done' if payload.get('text_clues') else ''}"></span>
                    <div>
                        <div class="pcr-readiness-label">文本线索</div>
                        <div class="pcr-readiness-value">{html_text('、'.join(payload.get('text_clues', [])) if payload.get('text_clues') else '未抽取')}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def go_to_next_step():
    st.session_state["student_current_step"] = min(
        len(STUDENT_STEP_TITLES),
        st.session_state["student_current_step"] + 1,
    )


def go_to_prev_step():
    st.session_state["student_current_step"] = max(1, st.session_state["student_current_step"] - 1)


def run_student_diagnosis():
    """执行原有诊断逻辑，并保存结果到 session_state"""
    form_data = collect_student_form_payload()
    initial_hypothesis = st.session_state["student_form_initial_hypothesis"].strip()
    access_code = secrets.token_urlsafe(12)
    saved_image_path, image_save_error = save_uploaded_image(form_data["gel_image_file"])

    results, _, text_clues, clue_source, api_debug = diagnose(
        form_data["abnormality"],
        form_data["template_amount"],
        form_data["annealing_temp"],
        form_data["cycles"],
        form_data["positive_control_normal"],
        form_data["negative_control_band"],
        form_data["description"],
        experiment_parameters=form_data,
        confirmed_text_hints=form_data.get("confirmed_hints", []),
    )

    clear_followup_widget_state()
    questions, question_source = plan_followup_questions(form_data, results=results) if results else ([], "")

    payload = {
        "results": results,
        "text_clues": text_clues,
        "clue_source": clue_source,
        "api_debug": api_debug,
        "record_id": None,
        "gel_image_path": saved_image_path,
        "image_save_error": image_save_error,
        "submit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "abnormality": form_data["abnormality"],
        "template_amount": form_data["template_amount"],
        "annealing_temp": form_data["annealing_temp"],
        "cycles": form_data["cycles"],
        "positive_control_normal": form_data["positive_control_normal"],
        "negative_control_band": form_data["negative_control_band"],
        "description": form_data["description"],
        "followup_questions": questions,
        "followup_question_source": question_source,
        "followup_completed": False,
        "student_initial_hypothesis": initial_hypothesis,
        **{k: v for k, v in form_data.items() if k != "gel_image_file"},
    }

    if results:
        result_text = ""
        for index, result_item in enumerate(results, 1):
            result_text += f"{index}. {result_item['原因']} (总分:{result_item['总分']}); "

        record_id = save_diagnosis_record(
            form_data["abnormality"],
            form_data["template_amount"],
            form_data["annealing_temp"],
            form_data["cycles"],
            form_data["positive_control_normal"],
            form_data["negative_control_band"],
            form_data["description"],
            result_text,
            gel_image_path=saved_image_path,
            student_initial_hypothesis=initial_hypothesis,
            student_access_code=access_code,
            initial_results=results,
            raw_case={k: v for k, v in form_data.items() if k != "gel_image_file"},
            evidence={"text_clues": text_clues, "normalized_case": api_debug.get("normalized_case", {}),
                      "initial_extraction": st.session_state.get("student_extraction_evidence", {}), "confirmed_description": form_data["description"],
                      "model": ai_config.MODEL, "source": clue_source},
        )
        payload["record_id"] = record_id
        st.session_state["student_access_code"] = access_code

    st.session_state["student_last_payload"] = payload
    st.session_state["last_api_debug"] = api_debug


def render_student_wizard_header():
    """渲染聚焦式步骤条和当前步骤提示。"""
    current_step = st.session_state["student_current_step"]
    total_steps = len(STUDENT_STEP_TITLES)
    step_items = []
    for index, title in enumerate(STUDENT_STEP_TITLES, 1):
        if index < current_step:
            state_class = "done"
            status_text = "已完成"
            index_text = "✓"
        elif index == current_step:
            state_class = "active"
            status_text = "正在填写"
            index_text = str(index)
        else:
            state_class = ""
            status_text = "待填写"
            index_text = str(index)

        step_items.append(
            f"""
            <div class="pcr-stepper-item {state_class}">
                <div class="pcr-stepper-index">{index_text}</div>
                <div class="pcr-stepper-title">{title}</div>
                <div class="pcr-stepper-status">{status_text}</div>
            </div>
            """
        )

    with st.container():
        st.markdown(
            f"""
            <div class="pcr-current-step-summary">
                <div>
                    <div class="pcr-step-kicker">当前步骤</div>
                    <div class="pcr-step-title">第 {current_step} / {total_steps} 步：{STUDENT_STEP_TITLES[current_step - 1]}</div>
                    <div class="pcr-step-desc">可随时返回前一步调整信息，确认后再生成诊断结果。</div>
                </div>
                <span class="pcr-current-step-chip">{round(current_step / total_steps * 100)}% 完成</span>
            </div>
            <div class="pcr-stepper-grid">
                {''.join(step_items)}
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.progress(current_step / total_steps)


def render_step_1_basic_info():
    """第 1 步：实验现象与对照情况"""
    with st.container(border=True, key="pcr_student_form_card_step1"):
        render_card_title("记录实验现象与对照结果", "先记录凝胶中看到的主要异常，再确认阳性与阴性对照表现。")
        with st.expander("课程、班级与匿名小组", expanded=False):
            for field, label in [("course_name", "课程名称"), ("class_name", "班级"), ("experiment_name", "实验项目／课次"), ("group_code", "匿名小组编号")]:
                key = "student_form_" + field
                st.text_input(label, key=key, on_change=sync_val, args=(key,))
            st.checkbox("使用本地模式（不调用 AI 接口）", key="student_form_local_mode", on_change=sync_val, args=("student_form_local_mode",))
        col_left, col_right = st.columns(2)
        with col_left:
            # 增加 on_change=sync_val 和 args 使得修改能即时保存
            st.selectbox("实验现象", ABNORMALITY_OPTIONS, key="student_form_abnormality", on_change=sync_val, args=("student_form_abnormality",))
            st.radio("阳性对照是否正常", ["未观察", "未设置", "无法确认", "是", "否"], key="student_form_positive_control_normal", on_change=sync_val, args=("student_form_positive_control_normal",))
        with col_right:
            st.radio("阴性对照是否有带", ["未观察", "未设置", "无法确认", "是", "否"], key="student_form_negative_control_band", on_change=sync_val, args=("student_form_negative_control_band",))
            st.caption("如还有其他现象，可在第 3 步补充描述中继续说明。")


def render_step_2_pcr_params():
    with st.container(border=True, key="pcr_student_form_card_step2"):
        render_card_title("填写 PCR 条件与课程方案", "未知参数可以留空；推荐条件应来自实际实验方案或试剂说明。")
        presets = load_course_presets()
        if presets:
            chosen = st.selectbox("课程方案预设", range(len(presets)), format_func=lambda i: presets[i]["name"], key="student_preset_choice")
            st.caption(presets[chosen].get("source", ""))
            if st.button("应用课程方案", key="student_apply_preset"):
                for field, value in presets[chosen].items():
                    key = "student_form_" + field
                    if key in STUDENT_FORM_DEFAULTS:
                        st.session_state["student_data_storage"][key] = value
                        st.session_state[key] = value
                st.rerun()
        cols = st.columns(2)
        for index, (field, label, step) in enumerate([
            ("template_amount", "模板加入体积（μL）", 0.5),
            ("annealing_temp", "实际退火温度（℃）", 0.5),
            ("cycles", "循环数", 1),
        ]):
            key = "student_form_" + field
            restore_widget_value_from_storage(key)
            with cols[index % 2]:
                st.number_input(label, min_value=1 if field == "cycles" else 0.01, value=None,
                                step=step, key=key, on_change=sync_val, args=(key,), placeholder="未知时留空")
        with st.expander("补充模板、目标片段与推荐条件", expanded=False):
            st.selectbox("模板类型", ["待确认", "质粒", "基因组 DNA", "cDNA", "其他"], key="student_form_template_type", on_change=sync_val, args=("student_form_template_type",))
            for field, label in [("template_concentration", "模板浓度（ng/μL）"), ("reaction_volume", "反应总体积（μL）"), ("target_size", "预期片段大小（bp）"), ("recommended_temp", "推荐退火温度（℃）")]:
                key = "student_form_" + field
                restore_widget_value_from_storage(key)
                st.number_input(label, min_value=0.01, value=None, key=key, on_change=sync_val, args=(key,), placeholder="按实际方案填写")
            st.text_input("聚合酶名称／推荐条件来源", key="student_form_polymerase", on_change=sync_val, args=("student_form_polymerase",))
            mass = template_mass_ng(collect_student_form_payload())
            if mass is not None:
                st.info(f"记录的 DNA 输入质量为 {mass:g} ng。是否适量仍需结合模板类型和试剂说明判断。")
        for issue in validate_experiment_parameters(collect_student_form_payload()):
            st.warning(issue)



def render_step_3_text_and_image():
    """第 3 步：补充描述与图片上传"""
    with st.container(border=True, key="pcr_student_form_card_step3"):
        render_card_title("补充实验描述与凝胶图片", "可描述操作过程中的特殊情况，也可以上传凝胶图片作为教师复核依据。")
        desc_col, image_col = st.columns([0.58, 0.42])
        with desc_col:
            st.text_area(
                "学生补充描述",
                height=150,
                placeholder="请补充任何其他可能的信息，例如模板情况、体系怀疑点、异常观察等...",
                key="student_form_description",
                on_change=sync_val,
                args=("student_form_description",)
            )
            if st.button("整理候选线索", key="student_extract_initial"):
                description = st.session_state.get("student_form_description", "")
                if st.session_state.get("student_form_local_mode"):
                    from core import extract_text_clues
                    clues, source = extract_text_clues(description), "本地规则抽取"
                else:
                    clues, source, _ = extract_text_clues_with_fallback(description)
                proposed = build_normalized_case({"description": description, "text_clues": clues})["text_hint"]
                st.session_state["student_extraction_evidence"] = {"description": description, "proposed": proposed, "source": source}
                st.rerun()
            suggestion = st.session_state.get("student_extraction_evidence", {})
            if suggestion.get("description") == st.session_state.get("student_form_description", ""):
                st.info(f"候选建议（{suggestion.get('source', '')}）：{'、'.join(suggestion.get('proposed', [])) or '无明确线索'}；请在下方逐项确认。")
            st.multiselect("确认实际发生的事实线索", STANDARD_TEXT_HINTS, key="student_form_confirmed_hints", on_change=sync_val, args=("student_form_confirmed_hints",))
            st.caption("自动整理只是候选建议；请取消未发生的项目。仅当前确认的线索影响排序，也可直接手动选择。")
        with image_col:
            uploaded_file = st.file_uploader(
                "上传凝胶图片（可选，PNG/JPG，不超过 10 MB）",
                type=["png", "jpg", "jpeg"],
                accept_multiple_files=False,
                key="student_form_gel_image_file",
            )
            persist_uploaded_file(uploaded_file)
            st.text_area("凝胶图泳道说明（人工标注）", key="student_form_lane_notes", on_change=sync_val, args=("student_form_lane_notes",),
                         placeholder="例如 M：Marker；1：阳性；2：阴性；3：样本。记录位置、预期大小和观察结果。")
            st.caption("此处为人工记录。完成独立初判后，可在结果页主动使用 AI 辅助观察；图像观察不直接参与诊断。")

            image_bytes = st.session_state.get("student_uploaded_image_bytes")
            image_name = st.session_state.get("student_uploaded_image_name", "")
            if image_bytes:
                st.image(image_bytes, caption=f"当前暂存图片：{image_name}", use_container_width=True)
                if st.button("清除当前图片", key="student_clear_uploaded_image", use_container_width=True):
                    clear_student_uploaded_image()
                    st.rerun()
            else:
                st.markdown(
                    """
                    <div class="pcr-gel-placeholder">
                        <b>凝胶图可选上传</b>
                        <span>上传后会随案例保存，教师端可用于复核；未上传也可继续诊断。</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_step_4_review():
    """第 4 步：确认并诊断"""
    form_data = collect_student_form_payload()
    with st.container(border=True, key="pcr_student_form_card_step4"):
        render_card_title("确认信息并生成诊断", "请核对前面填写的信息，确认后系统将生成候选原因、诊断依据和处理建议。")
        image_status = "是" if form_data["gel_image_file"] else "否"
        description_text = form_data["description"] if form_data["description"] else "未填写"
        review_items = [
            ("实验现象", form_data["abnormality"]),
            ("阳性对照是否正常", form_data["positive_control_normal"]),
            ("阴性对照是否有带", form_data["negative_control_band"]),
            ("模板加入体积", parameter_text(form_data["template_amount"], "μL")),
            ("退火温度", parameter_text(form_data["annealing_temp"], "℃")),
            ("循环数", parameter_text(form_data["cycles"])),
            ("是否已上传图片", image_status),
            ("学生补充描述", description_text),
        ]
        cards = [
            (
                '<div class="pcr-review-item">'
                f'<div class="pcr-review-label">{html_text(label)}</div>'
                f'<div class="pcr-review-value">{html_text(value)}</div>'
                "</div>"
            )
            for label, value in review_items
        ]
        st.markdown(
            f'<div class="pcr-review-grid">{"".join(cards)}</div>',
            unsafe_allow_html=True,
        )
        st.caption("已确认的事实线索：" + ("、".join(form_data.get("confirmed_hints", [])) or "无。系统按已记录的观察进行保守排查。"))
        st.text_area(
            "查看系统结果前，你认为最可能的原因是什么？依据是什么？",
            key="student_form_initial_hypothesis",
            height=100,
            placeholder="例如：我认为模板量不足，因为样本没有目标条带，但阳性对照正常。",
            on_change=sync_val,
            args=("student_form_initial_hypothesis",),
        )
        st.caption("请先独立写下判断；提交后将与系统结果、教师复核及你的修订一起保存。")


def render_student_step_navigation():
    """渲染步骤切换按钮"""
    current_step = st.session_state["student_current_step"]
    total_steps = len(STUDENT_STEP_TITLES)
    st.markdown('<div class="pcr-student-actions">', unsafe_allow_html=True)
    left_col, right_col = st.columns(2)

    with left_col:
        if current_step > 1 and st.button("上一步", key=f"student_prev_step_{current_step}", use_container_width=True):
            go_to_prev_step()
            st.rerun()

    with right_col:
        if current_step < total_steps:
            if st.button("下一步", key=f"student_next_step_{current_step}", type="primary", use_container_width=True):
                go_to_next_step()
                st.rerun()
        else:
            if st.button("生成诊断结果", key="student_run_diagnosis", type="primary", use_container_width=True):
                issues = validate_experiment_parameters(collect_student_form_payload())
                if issues:
                    st.error("请先核对参数：" + "；".join(issues))
                    return
                if not st.session_state.get("student_form_initial_hypothesis", "").strip():
                    st.warning("请先填写你的初步判断和依据。")
                    return
                run_student_diagnosis()
                st.session_state["student_show_result_report"] = True
                st.success("诊断已完成，本次记录已保存，可在教师端继续复核。")
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def get_result_report_parts(payload):
    """整理结果报告展示所需的安全数据，不改变诊断结果本身。"""
    results = payload.get("results", []) or []
    top1 = results[0] if results else {}
    detail = top1.get("诊断依据", {}) or {}
    followup_data = payload.get("followup_data", {})
    operation_text = followup_data.get("answers", {}).get("operation", "")
    context = build_diagnosis_context(
        abnormality=payload.get("abnormality", ""),
        positive_control_normal=payload.get("positive_control_normal", ""),
        negative_control_band=payload.get("negative_control_band", ""),
        template_amount=payload.get("template_amount"),
        annealing_temp=payload.get("annealing_temp"),
        cycles=payload.get("cycles"),
        description=payload.get("description", "") or operation_text,
        text_clues=payload.get("text_clues", []) + followup_data.get("extra_hints", []),
        gel_image_path=payload.get("gel_image_path", ""),
        has_image=bool(payload.get("gel_image_path")),
        experiment_parameters=payload,
    )
    confidence_level, confidence_reason = compute_confidence_level(results, detail=detail, context=context)
    evidence_points = build_evidence_summary(top1.get("原因", ""), detail=detail, context=context)
    missing_items = detect_missing_key_info({**context, "候选原因": top1.get("原因", "")})
    return results, top1, confidence_level, confidence_reason, evidence_points, missing_items


def render_result_overview(payload, results, top1, confidence_level):
    """以正文层级呈现结论，保留原有状态与文本线索信息。"""
    st.html(f'''<div class="pcr-result-overview">
        <div class="pcr-result-kicker">诊断结果总览</div>
        <h2 class="pcr-result-title">{html_text(top1.get("原因", "暂无诊断结果"))}</h2>
        <div class="pcr-result-meta"><span>证据支持程度：<b class="pcr-confidence-pill">{html_text(confidence_level)}</b></span>
        <span>总分 {html_text(top1.get("总分", "-"))}</span></div>
        <p class="pcr-result-desc">系统判断仅作为实验复盘参考，最终原因可由教师结合原始图像与操作记录确认。</p>
        </div>''')


def render_primary_result(top1, confidence_level, confidence_reason, evidence_points, missing_items=None):
    """合并证据展示，原判断说明仍可展开查看。"""
    points = list(evidence_points or ["当前可提炼的证据较少，系统主要基于已有规则分值进行排序。"])
    points += list(missing_items or [])
    evidence_html = "".join(f"<li>{html_text(point)}</li>" for point in dict.fromkeys(points))
    st.html(f'''<div class="pcr-result-primary">
        <h3>系统依据与补充建议</h3>
        <ol class="pcr-evidence-list">{evidence_html}</ol>
        <div class="pcr-soft-note"><div class="pcr-result-label">建议措施</div>
        <p>{html_text(top1.get("建议", "建议结合原始实验记录和凝胶图片继续复核。"))}</p></div>
        </div>''')


def render_candidate_results(results):
    """渲染 Top2 / Top3 次级候选原因。"""
    secondary = (results or [])[1:3]
    if not secondary:
        return

    cards = []
    for index, result_item in enumerate(secondary, 2):
        suggestion = result_item.get("建议") or "可结合诊断依据进一步复核。"
        cards.append(
            '<div class="pcr-candidate-card">'
            f'<div class="pcr-candidate-rank">Top{index} 候选原因</div>'
            f'<h4>{html_text(result_item.get("原因", "-"))}</h4>'
            f'<p>总分 {html_text(result_item.get("总分", "-"))}</p>'
            f'<p>{html_text(suggestion)}</p>'
            "</div>"
        )

    st.markdown(
        f"""
        <div class="pcr-result-candidates">
            <h3 class="pcr-result-section-title">其他候选原因</h3>
            <div class="pcr-candidate-grid">{''.join(cards)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for index, result_item in enumerate(secondary, 2):
        with st.expander(f"查看 Top{index} 候选原因详情"):
            render_scoring_detail(result_item.get("诊断依据", {}), result_item.get("总分", "-"))


def render_result_evidence(missing_items):
    """渲染系统依据与补充建议。"""
    if missing_items:
        missing_html = "".join(f"<li>{html_text(item)}</li>" for item in missing_items)
    else:
        missing_html = "<li>当前关键信息较完整，可结合教师复核继续确认。</li>"

    st.markdown(
        f"""
        <div class="pcr-result-evidence">
            <h3 class="pcr-result-section-title">系统依据与补充建议</h3>
            <p>系统根据异常现象、对照结果、PCR 参数和补充描述生成候选原因。</p>
            <p>为了提高判断稳定性，可继续补充或核对以下信息：</p>
            <ul>{missing_html}</ul>
            <p class="pcr-result-note">教师复核时建议结合凝胶原图、上样量、模板浓度测定结果和实际操作记录综合判断。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_input_summary(payload):
    """渲染本次输入摘要。"""
    image_text = "已上传" if payload.get("gel_image_path") else "未上传"
    summary_items = [
        ("实验现象", payload.get("abnormality", "-")),
        ("阳性对照", payload.get("positive_control_normal", "-")),
        ("阴性对照", payload.get("negative_control_band", "-")),
        ("模板加入体积", parameter_text(payload.get("template_amount"), "μL")),
        ("退火温度", parameter_text(payload.get("annealing_temp"), "℃")),
        ("循环数", parameter_text(payload.get("cycles"))),
        ("补充描述", payload.get("description") or "未填写"),
        ("凝胶图片", image_text),
    ]
    items_html = "".join(
        '<div class="pcr-input-summary-item">'
        f'<span class="pcr-input-summary-label">{html_text(label)}</span>'
        f'<b class="pcr-input-summary-value">{html_text(value)}</b>'
        "</div>"
        for label, value in summary_items
    )
    st.markdown(
        f"""
        <div class="pcr-input-summary">
            <h3 class="pcr-result-section-title">本次输入摘要</h3>
            <div class="pcr-input-summary-grid">{items_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def return_to_student_editing():
    """从结果报告回到第 4 步，保留已填写数据。"""
    st.session_state["student_show_result_report"] = False
    st.session_state["student_current_step"] = 4
    st.rerun()


def reassess_with_followup(payload, questions, answers, extra_hints):
    updated_case = apply_followup_choices(payload, answers)
    results, _, text_clues, clue_source, api_debug = diagnose(
        updated_case["abnormality"],
        updated_case["template_amount"],
        updated_case["annealing_temp"],
        updated_case["cycles"],
        updated_case["positive_control_normal"],
        updated_case["negative_control_band"],
        updated_case.get("description", ""),
        extra_text_hints=extra_hints,
        negative_control_detail=updated_case.get("negative_control_detail"),
        band_pattern=updated_case.get("band_pattern"),
        positive_control_detail=updated_case.get("positive_control_detail"),
        experiment_parameters=updated_case,
        confirmed_text_hints=payload.get("confirmed_hints", payload.get("text_clues", [])),
    )
    if not results:
        st.error("补证后没有可用的诊断结果，请返回修改原始记录。")
        return

    followup_data = {
        "initial_results": payload.get("results", []),
        "final_results": results,
        "questions": questions,
        "answers": answers,
        "extra_hints": extra_hints,
        "negative_control_detail": updated_case.get("negative_control_detail"),
        "positive_control_detail": updated_case.get("positive_control_detail"),
        "band_pattern": updated_case.get("band_pattern"),
        "question_source": payload.get("followup_question_source", ""),
        "hint_source": st.session_state.get("student_followup_hint_source", ""),
        "updated_case": {k: v for k, v in updated_case.items() if k not in {"results", "followup_data", "api_debug"}},
        "evidence": {"text_clues": text_clues, "normalized_case": api_debug.get("normalized_case", {})},
    }
    record_id = payload.get("record_id")
    if record_id and not save_followup_reassessment(
        record_id,
        format_diagnosis_result_text(results),
        updated_case["positive_control_normal"],
        updated_case["negative_control_band"],
        followup_data,
    ):
        st.error("补证结果未能保存到原案例；若教师已经确认该案例，请新建记录后再诊断。当前排序未更新。")
        return

    payload.update({
        "results": results,
        "text_clues": text_clues,
        "clue_source": clue_source,
        "api_debug": api_debug,
        "positive_control_normal": updated_case["positive_control_normal"],
        "negative_control_band": updated_case["negative_control_band"],
        "negative_control_detail": updated_case.get("negative_control_detail"),
        "band_pattern": updated_case.get("band_pattern"),
        "followup_data": followup_data,
        "followup_completed": True,
    })
    st.session_state["student_last_payload"] = payload
    st.rerun()


def render_followup_block(payload):
    """展示一轮定向追问，补证后在同一案例内重新排序。"""
    if payload.get("followup_completed"):
        followup_data = payload.get("followup_data", {})
        first = followup_data.get("initial_results", [])
        latest = followup_data.get("final_results", [])
        with st.container(border=True):
            st.markdown("### 追问补证与再判断")
            st.write(
                f"初判 Top1：{first[0].get('原因', '未识别') if first else '未识别'} → "
                f"补证后 Top1：{latest[0].get('原因', '未识别') if latest else '未识别'}"
            )
            for question in followup_data.get("questions", []):
                answer = followup_data.get("answers", {}).get(question["id"], "")
                if answer:
                    st.markdown(f"- **{question['text']}** {answer}")
            hints = followup_data.get("extra_hints", [])
            st.caption(f"已确认的操作线索：{'、'.join(hints) if hints else '无'}。排序由规则引擎重新计算，最终原因仍需教师复核。")
        return

    questions = payload.get("followup_questions", [])
    if not questions:
        return
    with st.container(key="pcr_followup_form"):
        st.markdown("### 追问补证")
        st.write("以下问题用于核对初判中尚不充分或可能矛盾的证据。无法确认的项目可保持原记录。")
        st.caption(f"问法来源：{payload.get('followup_question_source', '本地追问规划')}；问题主题和选项由程序限定。")
        answers = {}
        for question_number, question in enumerate(questions, 1):
            st.html(f'<div class="ds-question-title"><span>{question_number}</span><b>{html_text(question["text"])}</b></div>')
            st.caption(question["reason"])
            key = f"student_followup_{question['id']}"
            if question["kind"] == "choice":
                answers[question["id"]] = st.selectbox(
                    "请选择观察结果", ["请选择"] + question["options"], key=key,
                    label_visibility="visible",
                )
            else:
                answers[question["id"]] = st.text_area(
                    "实际操作描述", key=key, height=130,
                    placeholder="例如：配液时确认漏加了聚合酶；没有把猜测写成已发生的事实。",
                    label_visibility="visible",
                ).strip()

        operation_text = answers.get("operation", "")
        if operation_text and st.session_state.get("student_followup_analyzed_text") != operation_text:
            if st.button("整理操作线索", key="student_followup_extract", use_container_width=True):
                hints, source = interpret_operation_text(operation_text, local_mode=payload.get("local_mode", False))
                st.session_state["student_followup_analyzed_text"] = operation_text
                st.session_state["student_followup_proposed_hints"] = hints
                st.session_state["student_followup_confirmed_hints"] = []
                st.session_state["student_followup_hint_source"] = source
                st.rerun()
            st.info("请先整理操作描述，再确认哪些线索确实发生。")
            return

        confirmed_hints = []
        if operation_text:
            st.info("候选建议：" + ("、".join(st.session_state.get("student_followup_proposed_hints", [])) or "无明确线索") + "；请逐项核对后手动选择。")
            confirmed_hints = st.multiselect(
                "请确认实际发生的操作线索（模型建议仅供核对）",
                STANDARD_TEXT_HINTS,
                key="student_followup_confirmed_hints",
                placeholder="请选择已确认的操作线索",
            )
            st.caption(f"线索来源：{st.session_state.get('student_followup_hint_source', '手动确认线索')}。未勾选的线索不会影响规则排序。")

        if st.button("用补充证据重新判断", key="student_followup_reassess", type="primary", use_container_width=True):
            selected = any(
                value and value not in {"请选择", "暂无法确认", "暂无法判断"}
                for question_id, value in answers.items() if question_id != "operation"
            )
            if not selected and not confirmed_hints:
                st.warning("尚无可用于重新排序的明确证据。请核对一个观察结果，或确认实际发生的操作线索。")
                return
            reassess_with_followup(payload, questions, answers, confirmed_hints)


def render_student_case_lookup():
    """跨会话找回本人案例，查询码仅在创建时显示给学生。"""
    with st.expander("已有案例？用查询码找回反馈"):
        with st.form("student_case_lookup_form"):
            access_code = st.text_input("案例查询码", type="password", placeholder="输入创建案例时保存的查询码")
            submitted = st.form_submit_button("找回案例")
        if submitted:
            record = load_student_record(access_code)
            if not record or not is_classroom_record(record):
                st.error("未找到对应案例，请核对查询码。")
                return
            followup = parse_followup_data(record.get("followup_json"))
            results = followup.get("final_results") or parse_json(record.get("diagnosis_snapshot_json")).get("results") or followup.get("initial_results") or [
                parse_candidate_result_item(item, index)
                for index, item in enumerate(parse_all_candidates(record.get("diagnosis_result")), 1)
            ]
            results = [item for item in results if isinstance(item, dict)]
            case = {
                **parse_json(record.get("input_json")),
                "abnormality": record.get("abnormality"),
                "template_amount": record.get("template_amount"),
                "annealing_temp": record.get("annealing_temp"),
                "cycles": record.get("cycles"),
                "positive_control_normal": record.get("positive_control_normal"),
                "negative_control_band": record.get("negative_control_band"),
                "description": record.get("description") or "",
            }
            case.update(followup.get("updated_case", {}))
            snapshot = parse_json(record.get("diagnosis_snapshot_json"))
            questions, source = ([], "")
            if not followup.get("final_results") and not record.get("teacher_final_cause"):
                questions, source = plan_followup_questions({**case, "local_mode": True}, results=results)
            st.session_state["student_access_code"] = access_code.strip()
            st.session_state["student_last_payload"] = {
                **case,
                "record_id": record["id"],
                "results": results,
                "text_clues": snapshot.get("evidence", {}).get("text_clues", case.get("confirmed_hints", [])),
                "submit_time": record.get("diagnosis_time"),
                "gel_image_path": record.get("gel_image_path"),
                "followup_data": followup,
                "followup_completed": bool(followup.get("final_results")),
                "followup_questions": questions,
                "followup_question_source": source,
                "student_initial_hypothesis": record.get("student_initial_hypothesis") or "",
                "restored": True,
            }
            st.session_state["student_show_result_report"] = True
            clear_followup_widget_state()
            st.rerun()


def render_student_learning_loop(payload):
    """展示初判、系统判断、教师反馈和一次学生修订。"""
    record_id = payload.get("record_id")
    code = st.session_state.get("student_access_code")
    if not record_id or not code:
        return
    record = load_student_record(code)
    if not record or record.get("id") != record_id:
        return

    with st.container(key="pcr_learning_loop"):
        st.markdown("### 学习复盘")
        st.write(f"案例编号：{record_id}｜你的诊断前判断：{record.get('student_initial_hypothesis') or '未填写'}")
        st.caption("请妥善保存下方查询码。换浏览器或稍后返回时，可用它找回教师反馈；查询码不会出现在教师列表中。")
        st.code(code, language=None)

        followup = parse_followup_data(record.get("followup_json"))
        initial = followup.get("initial_results") or []
        final = followup.get("final_results") or []
        if initial:
            st.write(f"系统初判：{initial[0].get('原因', '未识别')}")
        if final:
            st.write(f"系统补证后判断：{final[0].get('原因', '未识别')}")

        if st.button("刷新教师反馈", key=f"student_refresh_feedback_{record_id}"):
            st.rerun()
        teacher_final = record.get("teacher_final_cause")
        if not teacher_final:
            st.info("教师尚未复核。请保存查询码，稍后返回查看反馈并修订判断。")
            return

        st.success(f"教师复核意见：{teacher_final}")
        st.caption("结论证据等级：" + (record.get("teacher_evidence_level") or "旧记录，未标注"))
        if record.get("teacher_evidence_level") == "原因待核实":
            st.info("教师已给出反馈，原因仍待核实。修订应说明证据缺口，不把暂定意见当作实验验证。")
        st.write(f"教师反馈：{record.get('teacher_note') or '教师未填写补充说明。'}")
        review_version = int(record.get("teacher_review_version") or 0)
        revision_version = int(record.get("student_revision_review_version") or 0)
        if record.get("student_revision_time") and revision_version != review_version:
            st.warning("教师更新了复核结论。之前的修订已保留，请依据本次反馈再提交一次修订。")
            st.write(f"上一版修订：{record.get('student_revised_cause')}；依据：{record.get('student_revision_reason')}")
        if record.get("student_revision_time") and revision_version == review_version:
            st.write(f"你修订后的原因：{record.get('student_revised_cause')}")
            st.write(f"修订依据：{record.get('student_revision_reason')}")
            st.caption(f"提交时间：{record.get('student_revision_time')}。本案例的学习复盘已完成。")
            return

        with st.form(f"student_revision_form_{record_id}"):
            revised_cause = st.text_input("看到教师反馈后，你现在认为最可能的原因是什么？")
            revision_reason = st.text_area("哪些证据让你保留或修改了初判？", height=100)
            submitted = st.form_submit_button("提交修订判断", type="primary")
        if submitted:
            if not revised_cause.strip() or not revision_reason.strip():
                st.warning("请同时填写修订原因和依据。")
            elif save_student_revision(record_id, code, revised_cause, revision_reason):
                st.success("修订已保存，学习复盘完成。")
                st.rerun()
            else:
                st.error("修订未保存。请刷新案例并确认教师已经复核，且此前没有提交过修订。")


def render_student_verification_plan(payload):
    record_id = payload.get("record_id")
    code = st.session_state.get("student_access_code")
    record = load_student_record(code) if code else None
    if not record or record.get("id") != record_id:
        return
    plan = parse_json(record.get("verification_plan_json"))
    with st.expander("下一步验证方案", expanded=not plan):
        st.caption("这是待实施的验证计划，保存方案不代表已完成复测。请说明如何区分候选原因。")
        with st.form(f"student_verification_{record_id}"):
            values = {}
            for field, label in [("hypothesis", "要验证的原因／假设"), ("variable", "改变哪个变量，其余条件如何保持一致？"),
                                 ("controls", "设置哪些对照？"), ("expected_result", "预期观察到什么结果？"), ("interpretation", "不同结果分别支持或削弱哪个原因？")]:
                values[field] = st.text_area(label, value=plan.get(field, ""), key=f"verification_{record_id}_{field}", height=85)
            submitted = st.form_submit_button("保存验证方案", type="primary")
        if submitted:
            if save_verification_plan(record_id, code, values):
                st.success("验证方案已保存，教师可以查看并反馈。")
                st.rerun()
            else:
                st.warning("请填写全部五项，并核对案例查询码。")
        if record.get("verification_feedback"):
            st.write("教师对验证方案的反馈：" + record["verification_feedback"])


def render_student_results(payload):
    """渲染报告化诊断结果区域。"""
    results = payload.get("results", [])
    record_id = payload.get("record_id")
    gel_image_path = payload.get("gel_image_path")
    image_save_error = payload.get("image_save_error")

    st.markdown('<div class="pcr-student-result-page">', unsafe_allow_html=True)

    if image_save_error:
        st.warning(f"图片保存失败，但不影响诊断：{image_save_error}")
    if not results:
        st.warning("该异常类型暂无规则。")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    results, top1, confidence_level, confidence_reason, evidence_points, missing_items = get_result_report_parts(payload)
    authorized_record = load_student_record(st.session_state.get("student_access_code"))
    teacher_confirmed = bool(
        authorized_record and authorized_record.get("id") == record_id
        and authorized_record.get("teacher_final_cause")
    )
    if teacher_confirmed:
        st.success("教师已完成复核。请在下方查看反馈并修订你的判断。")
    elif payload.get("followup_completed"):
        st.success("补充证据后已重新排序，教师端可查看初判与再判断记录。")
    else:
        st.info("当前为初步判断。请完成下方定向追问，补充证据后重新排序。", icon=":material/info:")
    with st.container(key="pcr_diagnosis_split"):
        diagnosis_col, followup_col = st.columns([0.49, 0.51])
        with diagnosis_col:
            render_result_overview(payload, results, top1, confidence_level)
            render_primary_result(top1, confidence_level, confidence_reason, evidence_points, missing_items)
            items = [("实验现象", payload.get("abnormality", "-")),
                     ("阳性对照", payload.get("positive_control_normal", "-")),
                     ("阴性对照", payload.get("negative_control_band", "-")),
                     ("模板", parameter_text(payload.get("template_amount"), "μL")),
                     ("退火", parameter_text(payload.get("annealing_temp"), "℃")),
                     ("循环", parameter_text(payload.get("cycles")))]
            st.html('<h3>本次输入摘要</h3><div class="ds-input-strip">' + ''.join(
                f'<div><span>{html_text(label)}</span><b>{html_text(value)}</b></div>'
                for label, value in items) + '</div>')
        with followup_col:
            if payload.get("followup_completed") or not teacher_confirmed:
                render_followup_block(payload)
            elif teacher_confirmed:
                st.success("教师已完成复核。请在下方查看反馈并修订你的判断。")
    render_student_learning_loop(payload)
    render_student_verification_plan(payload)

    status = "已保存" if payload.get("record_id") else "未保存"
    hints = list(dict.fromkeys(payload.get("text_clues", []) + payload.get("followup_data", {}).get("extra_hints", [])))
    with st.expander("记录状态与文本线索"):
        st.write(f"记录状态：{status} · 诊断时间：{payload.get('submit_time', '-')}")
        st.write(f"候选原因：{' / '.join(f'Top{i}' for i in range(1, len(results) + 1))}")
        st.write(f"文本线索：{'、'.join(hints) if hints else '未抽取'}")

    with st.expander("主要判断说明"):
        st.write(f"系统优先判断为：{top1.get('原因', '-')}")
        st.write(confidence_reason)

    with st.expander("其他候选原因与补充建议"):
        render_candidate_results(results)
        render_result_evidence(missing_items)


    with st.expander("查看本次输入摘要", expanded=False):
        render_input_summary(payload)
        if gel_image_path and os.path.exists(gel_image_path):
            st.image(gel_image_path, caption="凝胶图资料（请对照原图人工核对）", use_container_width=True)

    if record_id:
        render_student_panel(DB_PATH, record_id, st.session_state.get("student_access_code"))

    st.markdown(
        """
        <div class="pcr-result-actions">
            <h3>诊断记录操作</h3>
            <p class="pcr-result-desc">本次诊断已生成记录，可返回修改输入，也可下载本次记录用于课后复盘。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_cols = st.columns([1, 1])
    with action_cols[0]:
        if payload.get("restored"):
            if st.button("新建实验记录", key="student_return_to_editing", use_container_width=True):
                reset_student_form_state(target_step=1)
                st.rerun()
        elif st.button("返回修改", key="student_return_to_editing", use_container_width=True):
            return_to_student_editing()

    if record_id:
        download_name = f"{PRODUCT_NAME}_实验复盘报告_案例{record_id}.txt"
    else:
        download_name = f"{PRODUCT_NAME}_实验复盘报告_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    with action_cols[1]:
        st.download_button(
            "下载本次记录（TXT）",
            data=build_case_summary(payload),
            file_name=download_name,
            mime="text/plain",
            type="primary",
            use_container_width=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

def main():
    """学生端主流程。"""
    ensure_page_config("实验异常记录与诊断输入")
    init_database()
    apply_common_styles(theme="student")
    render_student_refined_styles()
    st.session_state["current_role"] = "student"
    init_student_wizard_state()

    payload = st.session_state.get("student_last_payload")
    show_result_report = bool(payload and st.session_state.get("student_show_result_report", True))
    if show_result_report:
        st.html(f'''<div class="ds-result-heading"><h1>实验异常记录与诊断输入</h1>
            <div class="ds-record-context">案例 {html_text(payload.get('record_id', '-'))} ·
            {html_text(payload.get('submit_time', '-'))} · {'已保存' if payload.get('record_id') else '未保存'}</div></div>''')
    else:
        render_page_hero(
            "实验异常记录与诊断输入",
            "按步骤记录实验观察、对照结果和 PCR 条件，系统将生成可解释的诊断建议。",
            "实验记录流程",
        )

    if show_result_report:
        render_student_results(payload)
        render_student_case_lookup()
        return

    render_student_case_lookup()
    render_student_quick_actions()
    render_student_wizard_header()

    with st.container(key="pcr_student_workspace"):
        main_col, side_col = st.columns([0.7, 0.3])
        with main_col:
            current_step = st.session_state["student_current_step"]
            if current_step == 1:
                render_step_1_basic_info()
            elif current_step == 2:
                render_step_2_pcr_params()
            elif current_step == 3:
                render_step_3_text_and_image()
            else:
                render_step_4_review()

            render_student_step_navigation()

        with side_col:
            render_student_readiness_panel()


if __name__ == "__main__":
    main()
