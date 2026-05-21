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
    render_card_title,
    verify_access_code,
)


def render_teacher_access_panel_inline():
    """教师端访问码验证区，放在教师入口卡片内部。"""
    teacher_code = get_teacher_access_code()

    if st.session_state.get("teacher_verified"):
        render_home_entry_status("已验证", "success")
        st.markdown("<div style='height: 0.65rem;'></div>", unsafe_allow_html=True)
        if st.button("进入教师端", key="home_open_teacher_direct", use_container_width=True):
            enter_teacher_role()
            st.rerun()
        return

    if not st.session_state.get("show_teacher_access_panel"):
        render_home_entry_status("需访问码", "warning")
        st.markdown("<div style='height: 0.65rem;'></div>", unsafe_allow_html=True)
        if st.button("验证教师端访问码", key="home_show_teacher_access", use_container_width=True):
            st.session_state["show_teacher_access_panel"] = True
            st.rerun()
        return

    st.caption("请输入教师访问码后进入教师端。")
    if not teacher_code:
        st.warning("当前未配置教师访问码 `TEACHER_ACCESS_CODE`，暂时无法进入教师端。")

    input_code = st.text_input(
        "教师访问码",
        key="teacher_access_code_input",
        type="password",
        placeholder="请输入教师访问码",
        label_visibility="collapsed",
    )

    verify_col, cancel_col = st.columns(2)
    with verify_col:
        if st.button("验证并进入", key="verify_teacher_access", use_container_width=True):
            if not teacher_code:
                st.error("教师访问码未配置，无法完成验证。")
            elif verify_access_code(input_code, teacher_code):
                enter_teacher_role()
                st.success("教师访问码验证成功。")
                st.rerun()
            else:
                st.error("教师访问码错误，请重新输入。")

    with cancel_col:
        if st.button("取消", key="cancel_teacher_access", use_container_width=True):
            st.session_state["show_teacher_access_panel"] = False
            st.rerun()


def render_home_entry_status(text, kind="neutral"):
    """首页角色入口的小状态标签。"""
    palette = {
        "success": ("#dcfce7", "#166534", "#86efac"),
        "warning": ("#ffedd5", "#9a3412", "#fdba74"),
        "neutral": ("#e0f2fe", "#075985", "#bae6fd"),
    }
    bg, color, border = palette.get(kind, palette["neutral"])
    st.markdown(
        f"""
        <span style="
            display: inline-flex;
            align-items: center;
            min-height: 1.65rem;
            padding: 0.16rem 0.62rem;
            border-radius: 999px;
            border: 1px solid {border};
            background: {bg};
            color: {color};
            font-size: 0.78rem;
            font-weight: 700;
        ">{text}</span>
        """,
        unsafe_allow_html=True,
    )


def render_dev_access_panel_bottom():
    """开发调试端访问码验证区，放在首页底部。"""
    dev_code = get_dev_access_code()

    with st.expander("开发调试", expanded=st.session_state.get("show_dev_access_panel", False)):
        if st.session_state.get("dev_verified"):
            st.success("开发调试端已验证")
            if st.button("进入开发调试端", key="page_open_dev_direct", use_container_width=True):
                enter_dev_role()
                st.rerun()
            return

        if not st.session_state.get("show_dev_access_panel"):
            if st.button("开发调试入口", key="page_show_dev_access", use_container_width=True):
                st.session_state["show_dev_access_panel"] = True
                st.rerun()
            return

        if not dev_code:
            st.warning("当前未配置开发访问码 `DEV_ACCESS_CODE`，暂时无法进入开发调试端。")

        input_code = st.text_input(
            "开发访问码",
            key="dev_access_code_input",
            type="password",
            placeholder="请输入开发访问码",
            label_visibility="collapsed",
        )

        action_col1, action_col2 = st.columns(2)
        with action_col1:
            if st.button("验证并进入", key="verify_dev_access", use_container_width=True):
                if not dev_code:
                    st.error("开发访问码未配置，无法完成验证。")
                elif verify_access_code(input_code, dev_code):
                    enter_dev_role()
                    st.success("开发访问码验证成功。")
                    st.rerun()
                else:
                    st.error("开发访问码错误，请重新输入。")

        with action_col2:
            if st.button("收起", key="hide_dev_access_panel", use_container_width=True):
                st.session_state["show_dev_access_panel"] = False
                st.rerun()


def render_home_portal():
    """首页统一门户。"""
    st.session_state["current_role"] = "home"
    apply_common_styles(theme="home")

    st.markdown(
        """
        <div class="pcr-home-hero">
            <div>
                <h1>PCR电泳异常智能复盘助手</h1>
                <p>面向实验教学与计算机创新竞赛的智能诊断工作台，串联学生输入、规则推理、教师复核与案例沉淀。</p>
                <div class="pcr-home-proof">
                    <span>规则矩阵诊断</span>
                    <span>文本线索抽取</span>
                    <span>教师闭环复核</span>
                    <span>课堂案例复盘</span>
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

    with st.container(border=True):
        render_card_title("工作台入口", "按课堂角色进入对应流程，学生诊断、教师复核和系统调试各自聚焦。")
        col_student, col_teacher, col_dev = st.columns(3)

        with col_student:
            st.markdown(
                """
                <div class="pcr-workbench-card">
                    <h3>学生诊断工作台</h3>
                    <p>按步骤录入实验现象、对照结果、PCR 参数和补充描述，生成可解释的诊断候选。</p>
                    <div class="pcr-workbench-meta"><span>无需验证</span><span>课堂演示</span></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("进入学生端", key="home_enter_student", type="primary", use_container_width=True):
                enter_student_role()
                st.rerun()

        with col_teacher:
            st.markdown(
                """
                <div class="pcr-workbench-card">
                    <h3>教师复核驾驶舱</h3>
                    <p>查看学生历史案例，分析 Top1/Top3 命中情况，完成最终原因确认和教学备注沉淀。</p>
                    <div class="pcr-workbench-meta"><span>访问码</span><span>复核闭环</span></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            render_teacher_access_panel_inline()

        with col_dev:
            st.markdown(
                """
                <div class="pcr-workbench-card">
                    <h3>系统健康控制台</h3>
                    <p>核验规则库、数据库、上传目录和模型配置，支持演示环境清理与规则在线维护。</p>
                    <div class="pcr-workbench-meta"><span>调试入口</span><span>环境管理</span></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.session_state.get("dev_verified"):
                if st.button("进入开发调试端", key="home_open_dev_card", use_container_width=True):
                    enter_dev_role()
                    st.rerun()
            else:
                if st.button("打开开发调试入口", key="home_show_dev_card", use_container_width=True):
                    st.session_state["show_dev_access_panel"] = True
                    st.rerun()

    with st.container(border=True):
        render_card_title("当前访问状态", "当前角色与访问权限仅在本次会话中生效。")
        st.markdown(
            f"""
            <div class="pcr-status-strip">
                <div><span>当前角色</span><b>{get_current_role_label()}</b></div>
                <div><span>教师端访问</span><b>{'已开启' if st.session_state.get('teacher_verified') else '未开启'}</b></div>
                <div><span>开发调试访问</span><b>{'已开启' if st.session_state.get('dev_verified') else '未开启'}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_home, col_reset = st.columns(2)
        with col_home:
            if st.button("返回首页", key="home_keep_home", use_container_width=True):
                go_home(clear_entries=False)
                st.rerun()
        with col_reset:
            if st.button("清空全部入口状态", key="home_reset_access", use_container_width=True):
                go_home(clear_entries=True)
                st.rerun()

    render_dev_access_panel_bottom()


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
        st.caption(f"当前角色：{get_current_role_label()}")
        st.caption(f"教师端：{'已验证' if st.session_state.get('teacher_verified') else '未验证'}")
        st.caption(f"开发调试端：{'已验证' if st.session_state.get('dev_verified') else '未验证'}")

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
    ensure_page_config("PCR电泳异常智能复盘助手")
    init_database()
    init_access_state()

    render_sidebar_status()
    pages = build_navigation_pages()
    navigator = st.navigation(pages, position="sidebar")
    handle_pending_navigation()
    navigator.run()


if __name__ == "__main__":
    main()
