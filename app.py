# -*- coding: utf-8 -*-
"""
首页 / 总入口
"""

import streamlit as st

from core import apply_common_styles, init_database, render_card_title, render_page_hero


def main():
    """首页：只做导航说明，不堆业务功能"""
    init_database()
    apply_common_styles(theme="student")

    render_page_hero(
        "PCR-电泳异常智能复盘助手",
        "一个面向课堂演示的 PCR 异常诊断 Demo，支持学生诊断、教师复盘与开发调试。",
        "首页",
    )

    with st.container(border=True):
        render_card_title("页面说明", "按角色拆分三页面，演示与教学更清晰。")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("**学生端**")
            st.markdown("填写参数、上传凝胶图、开始诊断、查看依据、导出案例摘要。")
        with col2:
            st.markdown("**教师端**")
            st.markdown("查看历史案例详情、确认最终原因、填写教师备注。")
        with col3:
            st.markdown("**开发调试端**")
            st.markdown("系统自检、API 调试、规则库查看/校验、演示环境重置。")

    with st.container(border=True):
        render_card_title("使用提示")
        st.info("请从左侧页面导航切换到对应角色页面进行操作。")


if __name__ == "__main__":
    main()
