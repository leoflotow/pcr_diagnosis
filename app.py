# -*- coding: utf-8 -*-
"""
首页 / 导航入口
"""

import streamlit as st
from branding import PRODUCT_NAME, PRODUCT_SUBTITLE, CURRENT_MODULE
from ui_design import render_app_navigation

from navigation_state import register_home_page

from core import (
    apply_common_styles,
    enter_dev_role,
    enter_student_role,
    enter_teacher_role,
    ensure_page_config,
    get_current_role_label,
    get_dev_access_code,
    get_teacher_access_code,
    go_home,
    init_access_state,
    init_database,
    logout_dev_access,
    logout_teacher_access,
    verify_access_code,
)


def supports_dialog():
    """检查当前 Streamlit 是否支持弹窗。"""
    return callable(getattr(st, "dialog", None))


def get_access_entry_config(entry_type):
    """教师端和开发调试端共用同一套访问验证配置。"""
    configs = {
        "teacher": {
            "title": "教师端访问验证",
            "intro": "请输入教师访问码后进入教师复核页面。",
            "label": "教师访问码",
            "env_name": "TEACHER_ACCESS_CODE",
            "input_key": "teacher_access_code_input",
            "verify_key": "verify_teacher_access",
            "cancel_key": "cancel_teacher_access",
            "show_key": "show_teacher_access_panel",
            "verified_key": "teacher_verified",
            "get_code": get_teacher_access_code,
            "enter": enter_teacher_role,
        },
        "dev": {
            "title": "开发调试端访问验证",
            "intro": "请输入开发访问码后进入开发调试控制台。",
            "label": "开发访问码",
            "env_name": "DEV_ACCESS_CODE",
            "input_key": "dev_access_code_input",
            "verify_key": "verify_dev_access",
            "cancel_key": "cancel_dev_access",
            "show_key": "show_dev_access_panel",
            "verified_key": "dev_verified",
            "get_code": get_dev_access_code,
            "enter": enter_dev_role,
        },
    }
    return configs[entry_type]


def open_access_entry(entry_type):
    """从首页按钮进入受限页面。"""
    config = get_access_entry_config(entry_type)
    if st.session_state.get(config["verified_key"]):
        config["enter"]()
        st.rerun()

    if supports_dialog():
        st.session_state["active_access_dialog"] = entry_type
    else:
        st.session_state[config["show_key"]] = True
    st.rerun()


def render_access_form(entry_type, compact=False):
    """访问码表单；弹窗和兼容面板复用同一段逻辑。"""
    config = get_access_entry_config(entry_type)
    access_code = config["get_code"]()

    st.caption(config["intro"])
    if not access_code:
        st.warning(f"当前未配置 `{config['env_name']}`，暂时无法进入。")

    input_code = st.text_input(
        config["label"],
        key=config["input_key"],
        type="password",
        placeholder=f"请输入{config['label']}",
        label_visibility="collapsed" if compact else "visible",
    )

    verify_col, cancel_col = st.columns(2)
    with verify_col:
        if st.button("验证并进入", key=config["verify_key"], use_container_width=True):
            if not access_code:
                st.error(f"当前未配置 `{config['env_name']}`，无法完成验证。")
            elif verify_access_code(input_code, access_code):
                st.session_state["active_access_dialog"] = None
                st.session_state[config["show_key"]] = False
                config["enter"]()
                st.rerun()
            else:
                st.error("访问码错误，请重新输入。")

    with cancel_col:
        if st.button("取消", key=config["cancel_key"], use_container_width=True):
            st.session_state["active_access_dialog"] = None
            st.session_state[config["show_key"]] = False
            st.rerun()


def render_access_dialog_if_needed():
    """在支持 st.dialog 的版本中显示访问码弹窗。"""
    active_dialog = st.session_state.get("active_access_dialog")
    if active_dialog not in {"teacher", "dev"} or not supports_dialog():
        return

    config = get_access_entry_config(active_dialog)

    @st.dialog(config["title"])
    def _access_dialog():
        render_access_form(active_dialog, compact=False)

    _access_dialog()


def render_access_fallback_panel(entry_type):
    """旧版 Streamlit 的小型内嵌验证面板。"""
    config = get_access_entry_config(entry_type)
    if supports_dialog() or not st.session_state.get(config["show_key"]):
        return

    with st.container(border=True):
        st.markdown(f"**{config['title']}**")
        render_access_form(entry_type, compact=True)


def render_home_refined_styles():
    """页面样式由 core.apply_common_styles 统一注入。"""
    return


def build_home_section_title_html(title, desc=""):
    kicker = desc.split("：", 1)[0] if desc and "：" in desc else ""
    note = desc.split("：", 1)[1] if desc and "：" in desc else desc
    return f"""
        <div class="pcr-section-head">
            <div>
                {f'<div class="pcr-section-kicker">{kicker}</div>' if kicker else ""}
                <h2>{title}</h2>
            </div>
            {f'<p class="pcr-section-note">{note}</p>' if note else ""}
        </div>
        """


def render_home_section_title(title, desc=""):
    st.html(build_home_section_title_html(title, desc))


def build_problem_cards_html():
    items = [
        (
            "01",
            "学生排查失败原因缺少依据",
            "PCR-电泳实验出现无条带、弱带、多条带、拖尾等异常后，学生往往难以判断问题来自模板、引物、体系、程序还是电泳条件。",
        ),
        (
            "02",
            "教师需反复说明相似异常",
            "教师需要多次处理相似实验失败案例，但很多排错经验停留在口头说明中，难以整理为可供教学使用的案例。",
        ),
        (
            "03",
            "课程缺少结构化异常案例",
            "实验失败本身具有教学价值，但如果没有记录、复核和统计机制，就难以支撑后续教学改进。",
        ),
    ]
    cards = []
    for number, title, desc in items:
        cards.append(
            (
                '<div class="pcr-problem-card">'
                '<div class="pcr-problem-top">'
                f'<span class="pcr-problem-number">{number}</span>'
                '<span class="pcr-mini-icon"></span>'
                '</div>'
                f"<h3>{title}</h3>"
                f"<p>{desc}</p>"
                "</div>"
            )
        )
    return f'<div class="pcr-problem-grid">{"".join(cards)}</div>'


def render_problem_cards():
    st.html(build_problem_cards_html())


def build_workflow_section_html():
    steps = [
        ("01", "学生记录与初判", "记录异常现象、对照和参数，并在看系统结果前写下自己的判断。"),
        ("02", "信息规范整理", "将学生输入整理为诊断规则可识别的结构化字段。"),
        ("03", "规则诊断", "依据基础诊断规则生成候选原因排序。"),
        ("04", "追问补证", "核对缺失或矛盾信息，再由规则引擎重新排序原因。"),
        ("05", "教师确认", "教师查看系统判断并确认最终原因。"),
        ("06", "学生修订", "学生查看教师反馈后修订判断，案例保留初判与修订记录。"),
        ("07", "验证方案", "学生设计变量、对照和预期结果，教师反馈；计划与实际复测分别记录。"),
    ]
    cards = []
    for index, (number, title, desc) in enumerate(steps):
        connector = "" if index == len(steps) - 1 else '<span class="pcr-flow-connector"></span>'
        cards.append(
            (
                '<div class="pcr-flow-card">'
                f'<div class="pcr-flow-index">{number}</div>'
                f"<h3>{title}</h3>"
                f"<p>{desc}</p>"
                f"{connector}"
                "</div>"
            )
        )

    return f'<div class="pcr-workflow-wrap"><div class="pcr-flow-grid">{"".join(cards)}</div></div>'


def render_workflow_section():
    st.html(build_workflow_section_html())


def build_capability_cards_html():
    items = [
        ("01", "异常信息记录", "支持记录异常现象、阳性/阴性对照、PCR 参数、学生补充描述和凝胶图片。", "blue"),
        ("02", "规则诊断", "基于基础规则与组合规则生成前三项候选原因。", "cyan"),
        ("03", "诊断依据说明", "展示诊断依据、证据支持程度、证据摘要和缺失信息提示，避免只给结论。", "blue"),
        ("04", "教师复核与学生修订", "教师确认原因并反馈；学生凭查询码找回案例、修订判断，教师可查看全过程记录。", "cyan"),
    ]
    cards = []
    for number, title, desc, tone in items:
        cards.append(
            (
                '<div class="pcr-capability-card">'
                f'<div class="pcr-capability-icon {tone}">{number}</div>'
                f"<h3>{title}</h3>"
                f"<p>{desc}</p>"
                "</div>"
            )
        )
    return f'<div class="pcr-capability-grid">{"".join(cards)}</div>'


def render_capability_cards():
    st.html(build_capability_cards_html())


def render_bottom_status_area():
    teacher_status = "已验证" if st.session_state.get("teacher_verified") else "未验证"
    dev_status = "已验证" if st.session_state.get("dev_verified") else "未验证"
    teacher_dot = "" if st.session_state.get("teacher_verified") else " warn"
    dev_dot = "" if st.session_state.get("dev_verified") else " warn"
    st.html(
        f"""
        <div class="pcr-status-footer-wrap" id="status">
            <div class="pcr-status-footer">
                <div class="pcr-status-intro">
                    <div class="pcr-section-kicker">入口状态</div>
                    <h2>页面状态与角色入口</h2>
                </div>
                <div class="pcr-status-grid">
                    <div class="pcr-status-card">
                        <div class="pcr-status-label"><span class="pcr-status-dot"></span>学生端</div>
                        <div class="pcr-status-value">开放</div>
                    </div>
                    <div class="pcr-status-card">
                        <div class="pcr-status-label"><span class="pcr-status-dot{teacher_dot}"></span>教师端</div>
                        <div class="pcr-status-value">{teacher_status}</div>
                    </div>
                    <div class="pcr-status-card">
                        <div class="pcr-status-label"><span class="pcr-status-dot{dev_dot}"></span>开发调试端</div>
                        <div class="pcr-status-value">{dev_status}</div>
                    </div>
                    <div class="pcr-status-card">
                        <div class="pcr-status-label"><span class="pcr-status-dot info"></span>当前角色</div>
                        <div class="pcr-status-value">{get_current_role_label()}</div>
                    </div>
                </div>
            </div>
        </div>
        """,
    )

    with st.container(key="pcr_status_reset_row"):
        left_col, _ = st.columns([0.9, 1.25])
        with left_col:
            if st.button("重置访问状态", key="home_reset_access", use_container_width=True):
                go_home(clear_entries=True)
                st.rerun()


def render_home_portal():
    """首页统一门户。"""
    st.session_state["current_role"] = "home"
    apply_common_styles(theme="home")
    render_home_refined_styles()

    st.html(
        f"""
        <header class="pcr-ref-topbar">
            <div class="pcr-ref-topbar-inner">
                <div class="pcr-ref-brand">
                    <div class="pcr-ref-brand-mark" aria-hidden="true"></div>
                    <div class="pcr-ref-brand-title">{PRODUCT_NAME}</div>
                </div>
                <nav class="pcr-ref-nav" aria-label="首页导航">
                    <a href="#problems">问题</a>
                    <a href="#workflow">流程</a>
                    <a href="#capabilities">功能</a>
                    <a href="#status">入口</a>
                </nav>
            </div>
        </header>
        """
    )

    st.html(
        f"""
        <div class="pcr-home-hero-refined">
            <div class="pcr-hero-content">
                <div class="pcr-hero-copy">
                    <div class="pcr-home-kicker">当前模块：{CURRENT_MODULE}</div>
                    <h1><span>{PRODUCT_NAME}</span></h1>
                    <p>{PRODUCT_SUBTITLE}</p>
                    <div class="pcr-hero-value-strip">
                        <div class="pcr-hero-value-item">
                            <div class="pcr-hero-value-title">结构化记录</div>
                            <div class="pcr-hero-value-desc">实验异常有据可查</div>
                        </div>
                        <div class="pcr-hero-value-item">
                            <div class="pcr-hero-value-title">诊断依据说明</div>
                            <div class="pcr-hero-value-desc">判断依据清晰呈现</div>
                        </div>
                        <div class="pcr-hero-value-item">
                            <div class="pcr-hero-value-title">师生反馈复盘</div>
                            <div class="pcr-hero-value-desc">初判与修订留在同一案例</div>
                        </div>
                    </div>
                </div>
                <div class="pcr-hero-visual" aria-label="抽象凝胶电泳品牌符号">
                    <div class="pcr-gel-brandmark">
                        <div class="pcr-gel-core">
                            <div class="pcr-gel-lane">
                                <i class="pcr-gel-band" style="top: 18%"></i>
                                <i class="pcr-gel-band thin" style="top: 34%"></i>
                                <i class="pcr-gel-band weak" style="top: 62%"></i>
                            </div>
                            <div class="pcr-gel-lane">
                                <i class="pcr-gel-band" style="top: 28%"></i>
                                <i class="pcr-gel-band weak" style="top: 70%"></i>
                            </div>
                            <div class="pcr-gel-lane">
                                <i class="pcr-gel-band" style="top: 23%"></i>
                                <i class="pcr-gel-band" style="top: 55%"></i>
                            </div>
                            <div class="pcr-gel-lane">
                                <i class="pcr-gel-band weak" style="top: 42%"></i>
                            </div>
                            <div class="pcr-gel-lane">
                                <i class="pcr-gel-band" style="top: 30%"></i>
                                <i class="pcr-gel-band thin" style="top: 66%"></i>
                            </div>
                            <div class="pcr-gel-lane">
                                <i class="pcr-gel-band smear" style="top: 45%"></i>
                                <i class="pcr-gel-band thin" style="top: 73%"></i>
                            </div>
                            <div class="pcr-gel-lane">
                                <i class="pcr-gel-band" style="top: 39%"></i>
                                <i class="pcr-gel-band weak" style="top: 57%"></i>
                            </div>
                            <div class="pcr-gel-scanline"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """
    )

    with st.container(key="pcr_hero_action_row"):
        col_student, col_teacher, col_dev = st.columns([1.28, 1, 0.9])
        with col_student:
            if st.button("实验诊断入口", key="home_enter_student", type="primary", use_container_width=True):
                enter_student_role()
                st.rerun()
        with col_teacher:
            if st.button("教师复核入口", key="home_enter_teacher", use_container_width=True):
                open_access_entry("teacher")
        with col_dev:
            if st.button("开发调试入口", key="home_enter_dev", use_container_width=True):
                open_access_entry("dev")

    render_access_fallback_panel("teacher")
    render_access_fallback_panel("dev")

    st.html(
        f"""
        <div class="pcr-problem-band" id="problems">
            <section class="pcr-section-dark">
                {build_home_section_title_html("实验异常诊断中的常见教学难点", "教学问题：学生、教师和课程建设共同面对的三个问题。")}
                {build_problem_cards_html()}
            </section>
        </div>
        """,
    )

    st.html(
        f"""
        <section class="pcr-section" id="workflow">
            {build_home_section_title_html("实验复盘流程", "七步流程串起学生初判、追问补证、规则判断、教师复核、修订与验证计划。")}
            {build_workflow_section_html()}
        </section>
        """,
    )

    st.html(
        f"""
        <section class="pcr-section" id="capabilities">
            {build_home_section_title_html("系统主要功能", "支持诊断依据说明、教师复核、反馈后修订与验证方案。")}
            {build_capability_cards_html()}
        </section>
        """,
    )

    render_bottom_status_area()


HOME_PAGE = register_home_page(st.Page(render_home_portal, title="首页", icon="🏠", default=True))
STUDENT_PAGE = st.Page("pages/1_学生端.py", title="学生端", icon="🎓")
TEACHER_PAGE = st.Page("pages/2_教师端.py", title="教师端", icon="🧑‍🏫")
DEV_PAGE = st.Page("pages/3_开发调试端.py", title="开发调试端", icon="🛠️")

PAGE_TARGETS = {
    "home": HOME_PAGE,
    "student": STUDENT_PAGE,
    "teacher": TEACHER_PAGE,
    "dev": DEV_PAGE,
}


def build_navigation_pages():
    """根据当前会话状态动态组装页面导航。"""
    pages = [
        HOME_PAGE,
        STUDENT_PAGE,
    ]

    if st.session_state.get("teacher_verified"):
        pages.append(TEACHER_PAGE)
    if st.session_state.get("dev_verified"):
        pages.append(DEV_PAGE)

    return pages


def render_sidebar_status():
    """侧边栏中的会话状态与快捷操作。"""
    with st.sidebar:
        st.markdown("**会话状态 / 工作台导航**")
        st.caption(f"当前角色：{get_current_role_label()}")
        st.caption(f"教师端访问：{'已验证' if st.session_state.get('teacher_verified') else '未验证'}")
        st.caption(f"开发调试访问：{'已验证' if st.session_state.get('dev_verified') else '未验证'}")

        if st.button("返回首页", key="sidebar_go_home", use_container_width=True):
            go_home(clear_entries=False)
            st.rerun()

        if st.session_state.get("teacher_verified"):
            if st.button("退出教师访问", key="sidebar_logout_teacher", use_container_width=True):
                logout_teacher_access()
                st.rerun()

        if st.session_state.get("dev_verified"):
            if st.button("退出开发访问", key="sidebar_logout_dev", use_container_width=True):
                logout_dev_access()
                st.rerun()


def handle_pending_navigation():
    """处理首页验证成功后的自动跳转。"""
    target = st.session_state.get("navigation_target")
    if not target:
        return

    st.session_state["navigation_target"] = None
    target_page = PAGE_TARGETS.get(target)
    if target_page:
        st.switch_page(target_page)


def main():
    ensure_page_config(PRODUCT_NAME)
    init_database()
    init_access_state()

    pages = build_navigation_pages()
    navigator = st.navigation(pages, position="hidden")
    handle_pending_navigation()
    active_path = navigator.url_path
    active = {"学生端": "student", "教师端": "teacher", "开发调试端": "dev"}.get(active_path, "home")
    render_app_navigation(
        active, lambda: go_home(clear_entries=False), enter_student_role,
        lambda: open_access_entry("teacher"), lambda: open_access_entry("dev"),
    )
    import os
    if os.getenv("PCR_DIAGNOSIS_DEMO_MODE") == "1":
        st.info("参赛本地演示｜全部案例为模拟材料，课堂数据库独立保存，当前不调用 AI 接口。")
    navigator.run()
    render_access_dialog_if_needed()


if __name__ == "__main__":
    main()
