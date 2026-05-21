# -*- coding: utf-8 -*-
"""
学生端页面
"""

import os
from datetime import datetime
from html import escape

import streamlit as st

from core import (
    ABNORMALITY_OPTIONS,
    apply_common_styles,
    build_case_summary,
    diagnose,
    ensure_page_config,
    init_database,
    render_diagnosis_quality_block,
    render_card_title,
    render_page_hero,
    save_diagnosis_record,
    save_uploaded_image,
)


STUDENT_FORM_DEFAULTS = {
    "student_form_abnormality": "无条带",
    "student_form_template_amount": 1.0,
    "student_form_annealing_temp": 60.0,
    "student_form_cycles": 30,
    "student_form_positive_control_normal": "是",
    "student_form_negative_control_band": "否",
    "student_form_description": "",
}

STUDENT_DEMO_DATA = {
    "student_form_abnormality": "无条带",
    "student_form_template_amount": 1.0,
    "student_form_annealing_temp": 60.0,
    "student_form_cycles": 30,
    "student_form_positive_control_normal": "否",
    "student_form_negative_control_band": "否",
    "student_form_description": "怀疑模板量不足，PCR体系可能漏加。",
}

STUDENT_FORM_STATE_VERSION = 2

STUDENT_STEP_TITLES = [
    "实验现象与对照情况",
    "PCR 关键参数",
    "补充描述与图片上传",
    "确认并开始诊断",
]


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
# ----------------------------

def init_student_wizard_state():
    """初始化学生端向导状态"""
    # 新增：建立独立于组件生命周期的持久化存储区
    if "student_data_storage" not in st.session_state:
        st.session_state["student_data_storage"] = STUDENT_FORM_DEFAULTS.copy()

    if st.session_state.get("student_form_state_version") != STUDENT_FORM_STATE_VERSION:
        legacy_default_mapping = {
            "student_form_template_amount": (2.0, 1.0),
            "student_form_annealing_temp": (55.0, 60.0),
            "student_form_cycles": (30, 30),
        }
        for key, (legacy_value, new_value) in legacy_default_mapping.items():
            # 这里改为更新持久化存储区
            if st.session_state["student_data_storage"].get(key) == legacy_value:
                st.session_state["student_data_storage"][key] = new_value
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


def clear_student_uploaded_image():
    """清空暂存图片"""
    st.session_state["student_uploaded_image_bytes"] = None
    st.session_state["student_uploaded_image_name"] = ""
    st.session_state["student_uploaded_image_type"] = ""
    st.session_state.pop("student_form_gel_image_file", None)


def reset_student_form_state(overrides=None, target_step=None):
    """按默认值或演示数据重置学生端表单状态。"""
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
    clear_student_uploaded_image()


def load_student_demo_data():
    """加载演示数据到向导状态。"""
    reset_student_form_state(
        STUDENT_DEMO_DATA,
        target_step=st.session_state.get("student_current_step", 1),
    )


def render_student_quick_actions():
    """渲染学生端轻量操作区，保留课堂演示入口。"""
    with st.container():
        left_col, right_col = st.columns([0.72, 0.28])
        with left_col:
            st.markdown(
                """
                <div class="pcr-student-toolbar">
                    <div>
                        <div class="pcr-student-toolbar-title">按步骤完成诊断输入</div>
                        <p class="pcr-student-toolbar-desc">
                            当前页面只在最后一步触发诊断；前面步骤可随时返回修改。
                        </p>
                    </div>
                    <span class="pcr-current-step-chip">课堂演示模式</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right_col:
            if st.button("加载演示数据", key="student_load_demo", use_container_width=True):
                load_student_demo_data()
                st.success("已加载演示数据，可按步骤继续演示。")
                st.rerun()


def persist_uploaded_file(uploaded_file):
    """把上传文件保存到 session_state，避免切步后丢失"""
    if uploaded_file is None:
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
    """收集当前学生端输入数据（核心修复：从安全的 storage 读取）"""
    storage = st.session_state["student_data_storage"]
    return {
        "abnormality": storage.get("student_form_abnormality", "无条带"),
        "template_amount": storage.get("student_form_template_amount", 0.0),
        "annealing_temp": storage.get("student_form_annealing_temp", 0.0),
        "cycles": storage.get("student_form_cycles", 30),
        "positive_control_normal": storage.get("student_form_positive_control_normal", "是"),
        "negative_control_band": storage.get("student_form_negative_control_band", "否"),
        "description": storage.get("student_form_description", ""),
        "gel_image_file": get_persisted_uploaded_file(),
    }


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
    saved_image_path, image_save_error = save_uploaded_image(form_data["gel_image_file"])

    results, _, text_clues, clue_source, api_debug = diagnose(
        form_data["abnormality"],
        form_data["template_amount"],
        form_data["annealing_temp"],
        form_data["cycles"],
        form_data["positive_control_normal"],
        form_data["negative_control_band"],
        form_data["description"],
    )

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
        )
        payload["record_id"] = record_id

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
                    <div class="pcr-step-desc">聚焦完成当前输入；诊断会在最后一步统一生成并保存。</div>
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
    with st.container(border=True):
        render_card_title("实验现象与对照情况", "先记录凝胶上看到的主要异常，再确认阳性/阴性对照表现。")
        col_left, col_right = st.columns(2)
        with col_left:
            # 增加 on_change=sync_val 和 args 使得修改能即时保存
            st.selectbox("实验现象", ABNORMALITY_OPTIONS, key="student_form_abnormality", on_change=sync_val, args=("student_form_abnormality",))
            st.radio("阳性对照是否正常", ["是", "否"], key="student_form_positive_control_normal", on_change=sync_val, args=("student_form_positive_control_normal",))
        with col_right:
            st.radio("阴性对照是否有带", ["是", "否"], key="student_form_negative_control_band", on_change=sync_val, args=("student_form_negative_control_band",))
            st.caption("如还有其他现象，可在第 3 步补充描述中继续说明。")


def render_step_2_pcr_params():
    """第 2 步：PCR 关键参数"""
    with st.container(border=True):
        render_card_title("PCR 关键参数", "填写会影响扩增结果的核心参数，用于匹配规则库。")
        col_left, col_right = st.columns(2)
        with col_left:
            st.number_input("模板量 (μL)", min_value=0.0, step=0.5, key="student_form_template_amount", on_change=sync_val, args=("student_form_template_amount",))
            st.number_input("循环数", min_value=1, step=1, key="student_form_cycles", on_change=sync_val, args=("student_form_cycles",))
        with col_right:
            st.number_input("退火温度 (℃)", min_value=0.0, step=0.5, key="student_form_annealing_temp", on_change=sync_val, args=("student_form_annealing_temp",))
            st.caption("当前项目已支持的关键参数主要包括模板量、退火温度和循环数。")


def render_step_3_text_and_image():
    """第 3 步：补充描述与图片上传"""
    with st.container(border=True):
        render_card_title("补充描述与图片上传", "补充文字线索；凝胶图片可选上传，用于案例留存和教师复核。")
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
        with image_col:
            uploaded_file = st.file_uploader(
                "上传凝胶图片（可选）",
                type=["png", "jpg", "jpeg"],
                accept_multiple_files=False,
                key="student_form_gel_image_file",
            )
            persist_uploaded_file(uploaded_file)

            image_bytes = st.session_state.get("student_uploaded_image_bytes")
            image_name = st.session_state.get("student_uploaded_image_name", "")
            if image_bytes:
                st.image(image_bytes, caption=f"当前暂存图片：{image_name}", use_container_width=True)
                if st.button("清除当前图片", key="student_clear_uploaded_image", use_container_width=True):
                    clear_student_uploaded_image()
                    st.rerun()
            else:
                st.info("当前未上传图片，也可以继续下一步。")


def render_step_4_review():
    """第 4 步：确认并开始诊断"""
    form_data = collect_student_form_payload()
    with st.container(border=True):
        render_card_title("确认并开始诊断", "请核对输入摘要；确认无误后点击“开始诊断”。")
        image_status = "是" if form_data["gel_image_file"] else "否"
        description_text = form_data["description"] if form_data["description"] else "未填写"
        review_items = [
            ("实验现象", form_data["abnormality"]),
            ("阳性对照是否正常", form_data["positive_control_normal"]),
            ("阴性对照是否有带", form_data["negative_control_band"]),
            ("模板量", form_data["template_amount"]),
            ("退火温度", form_data["annealing_temp"]),
            ("循环数", form_data["cycles"]),
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
        st.caption("如需修改，可返回前面步骤继续调整；诊断结果会保存到教师端可查看的记录中。")


def render_student_step_navigation():
    """渲染步骤切换按钮"""
    current_step = st.session_state["student_current_step"]
    total_steps = len(STUDENT_STEP_TITLES)
    left_col, right_col = st.columns(2)

    with left_col:
        if current_step > 1 and st.button("上一步", key=f"student_prev_step_{current_step}", use_container_width=True):
            go_to_prev_step()
            st.rerun()

    with right_col:
        if current_step < total_steps:
            if st.button("下一步", key=f"student_next_step_{current_step}", use_container_width=True):
                go_to_next_step()
                st.rerun()
        else:
            if st.button("开始诊断", key="student_run_diagnosis", type="primary", use_container_width=True):
                run_student_diagnosis()
                st.success("已完成诊断，可在下方查看结果。")
                st.rerun()


def render_student_results(payload):
    """渲染原有诊断结果区域"""
    results = payload.get("results", [])
    text_clues = payload.get("text_clues", [])
    clue_source = payload.get("clue_source", "本地规则抽取")
    record_id = payload.get("record_id")
    gel_image_path = payload.get("gel_image_path")
    image_save_error = payload.get("image_save_error")

    with st.container(border=True):
        render_card_title("诊断结果", "Top1 高亮展示，Top2/Top3 作为候选补充。")

        clue_text = "、".join(text_clues) if text_clues else "未抽取到明显线索"
        st.markdown(
            (
                '<div class="pcr-result-meta-grid">'
                '<div class="pcr-review-item">'
                '<div class="pcr-review-label">文本线索来源</div>'
                f'<div class="pcr-review-value">{html_text(clue_source)}</div>'
                "</div>"
                '<div class="pcr-review-item">'
                '<div class="pcr-review-label">抽取线索</div>'
                f'<div class="pcr-review-value">{html_text(clue_text)}</div>'
                "</div>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        if image_save_error:
            st.warning(f"图片保存失败，但不影响诊断：{image_save_error}")
        if gel_image_path and os.path.exists(gel_image_path):
            st.image(gel_image_path, caption=f"已上传：{gel_image_path}", use_container_width=True)
        elif gel_image_path:
            st.info(f"图片已记录路径，但文件未找到：{gel_image_path}")
        else:
            st.info("本次未上传凝胶图片")

        if results:
            top1 = results[0]
            st.markdown(
                f"""
                <div class="pcr-top1-card">
                    <b>Top1 原因：</b>{top1.get('原因', '-')}<br/>
                    <b>总分：</b>{top1.get('总分', '-')}<br/>
                    <b>建议：</b>{top1.get('建议', '-')}
                </div>
                """,
                unsafe_allow_html=True,
            )

            render_diagnosis_quality_block(
                top_results=results,
                detail=top1.get("诊断依据", {}),
                abnormality=payload.get("abnormality", ""),
                positive_control_normal=payload.get("positive_control_normal", ""),
                negative_control_band=payload.get("negative_control_band", ""),
                template_amount=payload.get("template_amount"),
                annealing_temp=payload.get("annealing_temp"),
                cycles=payload.get("cycles"),
                description=payload.get("description", ""),
                text_clues=text_clues,
                gel_image_path=gel_image_path,
                has_image=bool(gel_image_path and os.path.exists(gel_image_path)),
                title="Top1 诊断可信度解读",
            )

            if len(results) > 1:
                for index, result_item in enumerate(results[1:], 2):
                    st.markdown(
                        f"""
                        <div class="pcr-sub-card">
                            <b>Top{index}：</b>{result_item.get('原因', '-')}（总分: {result_item.get('总分', '-')}）
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            for index, result_item in enumerate(results, 1):
                with st.expander(f"{index}. 诊断依据 / 打分明细"):
                    render_scoring_detail(result_item.get("诊断依据", {}), result_item.get("总分", "-"))

            if record_id:
                st.success("诊断完成！结果已保存到数据库。")
        else:
            st.warning("该异常类型暂无规则。")

    if results:
        with st.container(border=True):
            render_card_title("复盘报告导出", "可预览规范化复盘报告，并下载为 TXT 文件。")
            summary_key = f"student_case_summary_{record_id}"
            generate_key = f"student_generate_case_summary_{record_id}"
            if record_id:
                download_name = f"pcr_review_report_case_{record_id}.txt"
            else:
                download_name = f"pcr_review_report_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
            st.caption("点击下方按钮可生成规范化复盘报告，并下载为 TXT 文件。")

            if st.button("生成复盘报告", key=generate_key):
                st.session_state[summary_key] = build_case_summary(payload)

            summary_text = st.session_state.get(summary_key, "")
            if summary_text:
                st.markdown("**复盘报告预览**")
                st.text_area("复盘报告预览", value=summary_text, height=420)
                st.download_button(
                    "下载复盘报告（TXT）",
                    data=summary_text,
                    file_name=download_name,
                    mime="text/plain",
                )

def main():
    """学生端主流程。"""
    ensure_page_config("学生端诊断工作台")
    init_database()
    apply_common_styles(theme="student")
    st.session_state["current_role"] = "student"
    init_student_wizard_state()

    render_page_hero(
        "学生端诊断工作台",
        "填写实验参数与补充描述，快速获得可解释的诊断候选结果。",
        "学生端",
    )

    render_student_quick_actions()

    render_student_wizard_header()

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

    payload = st.session_state.get("student_last_payload")
    if payload is not None:
        render_student_results(payload)


if __name__ == "__main__":
    main()
