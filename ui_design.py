"""统一视觉入口；仅负责样式和导航展示，不参与业务判断。"""

from pathlib import Path
import re

import streamlit as st
from branding import PRODUCT_NAME, PRODUCT_SUBTITLE, CURRENT_MODULE


def design_color(token):
    """图表从 CSS token 读取颜色，避免另建一套配色。"""
    css = Path(__file__).with_name("ui_design.css").read_text(encoding="utf-8")
    match = re.search(r"--ds-" + re.escape(token) + r":\s*(#[0-9a-fA-F]{6})", css)
    if not match:
        raise ValueError(f"未定义的设计颜色：{token}")
    return match.group(1)


def apply_design_system():
    """所有页面共享同一套 token、组件状态及响应式规则。"""
    css = Path(__file__).with_name("ui_design.css").read_text(encoding="utf-8")
    st.html(f"<style>{css}</style>")


def render_app_navigation(active, on_home, on_student, on_teacher, on_dev):
    """使用现有导航回调，访问验证仍由原入口负责。"""
    with st.container(key="pcr_app_navigation"):
        brand, links = st.columns([1.45, 1], vertical_alignment="center")
        with brand:
            st.html(
                f'<div class="ds-brand">{PRODUCT_NAME}</div>'
                f'<div class="ds-brand-subtitle">{PRODUCT_SUBTITLE}</div>'
                f'<div class="ds-module-label">当前模块：{CURRENT_MODULE}</div>'
            )
        with links:
            columns = st.columns(4)
            entries = [("home", "首页", on_home), ("student", "实验诊断", on_student),
                       ("teacher", "教师复核", on_teacher), ("dev", "开发调试", on_dev)]
            for column, (role, label, action) in zip(columns, entries):
                with column:
                    if st.button(label, key=f"ds_nav_{role}", type="primary" if role == active else "secondary", use_container_width=True):
                        action()
                        st.rerun()
