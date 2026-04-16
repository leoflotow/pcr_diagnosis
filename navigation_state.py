# -*- coding: utf-8 -*-
"""
共享 st.navigation 首页页对象。
"""

import streamlit as st


HOME_PAGE_SESSION_KEY = "_home_page_object"


def register_home_page(home_page):
    """注册首页页对象，供跨模块复用。"""
    st.session_state[HOME_PAGE_SESSION_KEY] = home_page
    return home_page


def get_home_page():
    """获取当前会话中已注册的首页页对象。"""
    return st.session_state.get(HOME_PAGE_SESSION_KEY)
