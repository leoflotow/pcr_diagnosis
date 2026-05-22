# -*- coding: utf-8 -*-
"""
首页 / 导航入口
"""

import streamlit as st

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
    render_info_tiles,
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


def render_home_section_title(title, desc=""):
    st.markdown(
        f"""
        <div class="pcr-home-section-title">
            <h2>{title}</h2>
            {f"<p>{desc}</p>" if desc else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_workflow_section():
    steps = [
        ("01", "学生提交异常", "记录异常现象、对照结果、PCR 参数、文字描述和凝胶图片。"),
        ("02", "信息标准化", "将学生输入归一化为诊断规则可识别的结构化字段。"),
        ("03", "规则矩阵诊断", "基于 rules.csv 基础规则生成候选原因排序。"),
        ("04", "组合规则加权", "结合 rule_combos.csv 对关键证据组合进行加权修正。"),
        ("05", "教师确认", "教师查看系统判断并确认最终原因。"),
        ("06", "案例沉淀与统计", "历史记录进入教师端看板，用于复盘、筛选和教学分析。"),
    ]
    cards = []
    for index, (number, title, desc) in enumerate(steps):
        connector = "" if index == len(steps) - 1 else '<span class="pcr-flow-arrow">→</span>'
        cards.append(
            f"""
            <div class="pcr-flow-card">
                <div class="pcr-flow-index">{number}</div>
                <h3>{title}</h3>
                <p>{desc}</p>
                {connector}
            </div>
            """
        )

    st.markdown(
        f"""
        <div class="pcr-flow-grid">
            {''.join(cards)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_bottom_status_area():
    teacher_status = "已验证" if st.session_state.get("teacher_verified") else "未验证"
    dev_status = "已验证" if st.session_state.get("dev_verified") else "未验证"
    st.markdown(
        f"""
        <div class="pcr-home-status-panel">
            <div class="pcr-home-status-grid">
                <div><span>学生端</span><b>开放</b></div>
                <div><span>教师端</span><b>{teacher_status}</b></div>
                <div><span>开发调试端</span><b>{dev_status}</b></div>
                <div><span>当前角色</span><b>{get_current_role_label()}</b></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_home, col_reset = st.columns([1, 1])
    with col_home:
        if st.button("返回首页", key="home_keep_home", use_container_width=True):
            go_home(clear_entries=False)
            st.rerun()
    with col_reset:
        if st.button("清空全部入口状态", key="home_reset_access", use_container_width=True):
            go_home(clear_entries=True)
            st.rerun()


def render_home_portal():
    """首页统一门户。"""
    st.session_state["current_role"] = "home"
    apply_common_styles(theme="home")

    st.markdown(
        """
        <div class="pcr-home-hero">
            <div>
                <h1>分子生物学实验 PCR-电泳异常智能复盘助手</h1>
                <p>面向分子生物学实验教学场景，帮助学生结构化记录异常现象，辅助系统生成候选原因，并支持教师复核确认与案例沉淀。</p>
                <div class="pcr-home-proof">
                    <span>结构化记录</span>
                    <span>规则矩阵诊断</span>
                    <span>组合规则加权</span>
                    <span>教师闭环复核</span>
                </div>
            </div>
            <div class="pcr-gel-panel">
                <div class="pcr-gel-title">Gel Electrophoresis Signal</div>
                <div class="pcr-gel-grid">
                    <div class="pcr-gel-lane" style="--band-a:22%;--band-b:66%;--a:.95;--b:.32;"></div>
                    <div class="pcr-gel-lane" style="--band-a:42%;--band-b:72%;--a:.38;--b:.1;"></div>
                    <div class="pcr-gel-lane" style="--band-a:29%;--band-b:54%;--a:.9;--b:.64;"></div>
                    <div class="pcr-gel-lane" style="--band-a:60%;--band-b:60%;--a:.15;--b:.12;"></div>
                    <div class="pcr-gel-lane" style="--band-a:25%;--band-b:48%;--a:.82;--b:.72;"></div>
                    <div class="pcr-gel-lane" style="--band-a:36%;--band-b:69%;--a:.55;--b:.24;"></div>
                    <div class="pcr-gel-lane" style="--band-a:18%;--band-b:58%;--a:.98;--b:.46;"></div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="pcr-hero-actions">', unsafe_allow_html=True)
    col_student, col_teacher, col_dev = st.columns([1.28, 1, 0.9])
    with col_student:
        if st.button("开始学生诊断", key="home_enter_student", type="primary", use_container_width=True):
            enter_student_role()
            st.rerun()
    with col_teacher:
        if st.button("教师复核入口", key="home_enter_teacher", use_container_width=True):
            open_access_entry("teacher")
    with col_dev:
        if st.button("开发调试入口", key="home_enter_dev", use_container_width=True):
            open_access_entry("dev")
    st.markdown("</div>", unsafe_allow_html=True)

    render_access_fallback_panel("teacher")
    render_access_fallback_panel("dev")

    render_home_section_title("项目解决的问题")
    render_info_tiles(
        [
            {
                "tag": "学生端痛点",
                "title": "学生不知道从哪里排查失败原因",
                "desc": "PCR-电泳实验出现无条带、弱带、多条带、拖尾等异常后，学生往往难以判断问题来自模板、引物、体系、程序还是电泳条件。",
            },
            {
                "tag": "教师端痛点",
                "title": "教师重复解释相似异常",
                "desc": "教师需要反复处理相似实验失败案例，但很多排错经验停留在口头解释中，难以沉淀为可复用案例。",
            },
            {
                "tag": "课程端痛点",
                "title": "课程缺少结构化失败案例",
                "desc": "实验失败本身具有教学价值，但如果没有记录、复核和统计机制，就难以支撑后续教学改进。",
            },
        ],
        columns=3,
    )

    render_home_section_title(
        "系统工作流",
        "从学生提交到教师确认，再到案例统计，形成可复盘、可积累的教学闭环。",
    )
    render_workflow_section()

    render_home_section_title("核心能力")
    render_info_tiles(
        [
            {
                "tag": "结构化采集",
                "title": "记录关键实验信息",
                "desc": "支持记录异常现象、阳性/阴性对照、PCR 参数、学生补充描述和凝胶图片。",
            },
            {
                "tag": "规则诊断",
                "title": "生成候选原因排序",
                "desc": "基于基础规则与组合规则生成 Top1 / Top2 / Top3 候选原因。",
            },
            {
                "tag": "证据解释",
                "title": "展示依据而不只给结论",
                "desc": "展示诊断依据、置信度、证据摘要和缺失信息提示，避免只给结论。",
            },
            {
                "tag": "教师闭环",
                "title": "复核确认并沉淀案例",
                "desc": "教师可确认最终原因、填写备注，并通过统计看板追踪系统判断与教师确认的一致性。",
            },
        ],
        columns=4,
    )

    render_home_section_title("入口与状态", "会话状态仅在本次访问中生效，作为底部辅助信息保留。")
    render_bottom_status_area()
    render_access_dialog_if_needed()


HOME_PAGE = st.Page(render_home_portal, title="首页", icon="🏠", default=True)
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
    ensure_page_config("PCR电泳异常诊断助手")
    init_database()
    init_access_state()

    render_sidebar_status()
    pages = build_navigation_pages()
    navigator = st.navigation(pages, position="sidebar")
    handle_pending_navigation()
    navigator.run()


if __name__ == "__main__":
    main()
