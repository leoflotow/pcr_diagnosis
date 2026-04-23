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
        <div class="pcr-hero">
            <h1 style="text-align: center;">PCR电泳异常智能复盘助手</h1>
            <p style="text-align: center; max-width: none; white-space: nowrap;">用于 PCR 电泳异常案例诊断、教师复核与教学复盘的实验教学辅助系统。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        render_card_title("角色入口")
        col_student, col_teacher = st.columns(2)

        with col_student:
            with st.container(border=True):
                st.markdown("**学生入口**")
                st.caption("直接进入学生诊断工作台，无需访问码。")
                render_home_entry_status("无需验证", "neutral")
                st.markdown("<div style='height: 0.65rem;'></div>", unsafe_allow_html=True)
                if st.button("进入学生端", key="home_enter_student", type="primary", use_container_width=True):
                    enter_student_role()
                    st.rerun()

        with col_teacher:
            with st.container(border=True):
                st.markdown("**教师入口**")
                if st.session_state.get("teacher_verified"):
                    st.caption("教师访问已验证，可直接进入教师端。")
                else:
                    st.caption("输入教师访问码后进入教师端。")
                render_teacher_access_panel_inline()

    with st.container(border=True):
        render_card_title("当前访问状态", "当前角色与访问权限仅在本次会话中生效。")
        status_col1, status_col2, status_col3 = st.columns(3)
        with status_col1:
            st.metric("当前角色", get_current_role_label())
        with status_col2:
            st.metric("教师端访问", "已开启" if st.session_state.get("teacher_verified") else "未开启")
        with status_col3:
            st.metric("开发调试访问", "已开启" if st.session_state.get("dev_verified") else "未开启")

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
