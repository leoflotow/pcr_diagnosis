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
    init_access_state,
    init_database,
    logout_dev_access,
    logout_teacher_access,
    return_to_home,
    render_card_title,
    render_page_hero,
    render_soft_notice,
    switch_to_home_page,
    verify_access_code,
)
from navigation_state import get_home_page, register_home_page


PAGE_TARGETS = {
    "student": "pages/1_学生端.py",
    "teacher": "pages/2_教师端.py",
    "dev": "pages/3_开发调试端.py",
}


def render_teacher_access_panel():
    """教师端访问码验证区。"""
    if not st.session_state.get("show_teacher_access_panel"):
        return

    with st.container(border=True):
        render_card_title("教师入口验证", "输入教师访问码后，当前会话中教师端才会显示在导航中。")
        teacher_code = get_teacher_access_code()
        if not teacher_code:
            st.warning("当前未配置教师访问码 `TEACHER_ACCESS_CODE`，暂时无法进入教师端。")

        input_col, button_col = st.columns([2, 1])
        with input_col:
            input_code = st.text_input(
                "教师访问码",
                key="teacher_access_code_input",
                type="password",
                placeholder="请输入教师访问码",
            )
        with button_col:
            st.write("")
            st.write("")
            if st.button("验证并进入教师端", key="verify_teacher_access", use_container_width=True):
                if not teacher_code:
                    st.error("教师访问码未配置，无法完成验证。")
                elif verify_access_code(input_code, teacher_code):
                    enter_teacher_role()
                    st.success("教师访问码验证成功。")
                    st.rerun()
                else:
                    st.error("教师访问码错误，请重新输入。")


def render_dev_access_panel():
    """开发调试端访问码验证区。"""
    if not st.session_state.get("show_dev_access_panel"):
        return

    with st.container(border=True):
        render_card_title("开发调试入口验证", "输入开发访问码后，当前会话中开发调试端才会显示在导航中。")
        dev_code = get_dev_access_code()
        if not dev_code:
            st.warning("当前未配置开发访问码 `DEV_ACCESS_CODE`，暂时无法进入开发调试端。")

        input_col, button_col = st.columns([2, 1])
        with input_col:
            input_code = st.text_input(
                "开发访问码",
                key="dev_access_code_input",
                type="password",
                placeholder="请输入开发访问码",
            )
        with button_col:
            st.write("")
            st.write("")
            if st.button("验证并进入开发调试端", key="verify_dev_access", use_container_width=True):
                if not dev_code:
                    st.error("开发访问码未配置，无法完成验证。")
                elif verify_access_code(input_code, dev_code):
                    enter_dev_role()
                    st.success("开发访问码验证成功。")
                    st.rerun()
                else:
                    st.error("开发访问码错误，请重新输入。")


def render_home_portal():
    """首页统一门户。"""
    st.session_state["current_role"] = "home"
    apply_common_styles(theme="home")

    render_page_hero(
        "PCR-电泳异常智能复盘助手",
        "首页作为统一入口：学生端可直接进入，教师端和开发调试端需要先完成访问码验证。",
        "项目首页",
    )

    with st.container(border=True):
        render_card_title("角色入口", "教师端与开发调试端只有验证成功后，才会在当前会话的左侧导航中显示。")
        col_student, col_teacher, col_dev = st.columns(3)

        with col_student:
            st.markdown("**学生入口**")
            st.caption("直接进入学生诊断工作台，无需访问码。")
            if st.button("进入学生端", key="home_enter_student", type="primary", use_container_width=True):
                enter_student_role()
                st.rerun()

        with col_teacher:
            st.markdown("**教师入口**")
            st.caption("点击后显示教师访问码验证区。")
            if st.session_state.get("teacher_verified"):
                st.success("教师端已验证")
                if st.button("进入教师端", key="home_open_teacher_direct", use_container_width=True):
                    enter_teacher_role()
                    st.rerun()
            else:
                if st.button("验证教师端访问码", key="home_show_teacher_access", use_container_width=True):
                    st.session_state["show_teacher_access_panel"] = True
                    st.session_state["show_dev_access_panel"] = False
                    st.rerun()

        with col_dev:
            st.markdown("**开发调试入口**")
            st.caption("点击后显示开发访问码验证区。")
            if st.session_state.get("dev_verified"):
                st.success("开发调试端已验证")
                if st.button("进入开发调试端", key="home_open_dev_direct", use_container_width=True):
                    enter_dev_role()
                    st.rerun()
            else:
                if st.button("验证开发访问码", key="home_show_dev_access", use_container_width=True):
                    st.session_state["show_dev_access_panel"] = True
                    st.session_state["show_teacher_access_panel"] = False
                    st.rerun()

    render_teacher_access_panel()
    render_dev_access_panel()

    with st.container(border=True):
        render_card_title("当前会话状态", "验证状态和当前角色仅保存在当前会话中。")
        st.markdown(f"- 当前角色：{get_current_role_label()}")
        st.markdown(f"- 教师端已验证：{'是' if st.session_state.get('teacher_verified') else '否'}")
        st.markdown(f"- 开发调试端已验证：{'是' if st.session_state.get('dev_verified') else '否'}")
        col_home, col_reset = st.columns(2)
        with col_home:
            if st.button("返回首页", key="home_keep_home", use_container_width=True):
                return_to_home(clear_entries=False)
        with col_reset:
            if st.button("清空全部入口状态", key="home_reset_access", use_container_width=True):
                return_to_home(clear_entries=True)

    with st.container(border=True):
        render_card_title("使用说明", "本次只做轻量访问码验证，不做账号体系。")
        render_soft_notice(
            "当前规则",
            "教师端使用 `TEACHER_ACCESS_CODE`，开发调试端使用 `DEV_ACCESS_CODE`。未配置访问码时，不会自动放行。",
        )


def build_navigation_pages():
    """根据当前会话状态动态组装页面导航。"""
    home_page = register_home_page(
        st.Page(render_home_portal, title="首页", icon="🏠", default=True)
    )
    pages = [
        home_page,
        st.Page("pages/1_学生端.py", title="学生端", icon="🎓"),
    ]

    if st.session_state.get("teacher_verified"):
        pages.append(st.Page("pages/2_教师端.py", title="教师端", icon="🧑‍🏫"))
    if st.session_state.get("dev_verified"):
        pages.append(st.Page("pages/3_开发调试端.py", title="开发调试端", icon="🛠️"))

    return pages


def render_sidebar_status():
    """侧边栏中的会话状态与快捷操作。"""
    with st.sidebar:
        st.caption(f"当前角色：{get_current_role_label()}")
        st.caption(f"教师端：{'已验证' if st.session_state.get('teacher_verified') else '未验证'}")
        st.caption(f"开发调试端：{'已验证' if st.session_state.get('dev_verified') else '未验证'}")

        if st.button("返回首页", key="sidebar_go_home", use_container_width=True):
            return_to_home(clear_entries=False)

        if st.session_state.get("teacher_verified"):
            if st.button("退出教师访问", key="sidebar_logout_teacher", use_container_width=True):
                logout_teacher_access()
                switch_to_home_page()

        if st.session_state.get("dev_verified"):
            if st.button("退出开发访问", key="sidebar_logout_dev", use_container_width=True):
                logout_dev_access()
                switch_to_home_page()


def handle_pending_navigation():
    """处理首页验证成功后的自动跳转。"""
    target = st.session_state.get("navigation_target")
    if not target:
        st.session_state["navigation_target"] = None
        return

    if target == "home":
        st.session_state["navigation_target"] = None
        home_page = get_home_page()
        if home_page is not None:
            st.switch_page(home_page)
        return

    target_path = PAGE_TARGETS.get(target)
    st.session_state["navigation_target"] = None
    if target_path:
        st.switch_page(target_path)


def main():
    ensure_page_config("PCR-电泳异常智能复盘助手")
    init_database()
    init_access_state()

    pages = build_navigation_pages()
    render_sidebar_status()
    navigator = st.navigation(pages, position="sidebar")
    handle_pending_navigation()
    navigator.run()


if __name__ == "__main__":
    main()
