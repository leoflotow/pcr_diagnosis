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
    """首页专属样式，避免影响学生端和教师端工作台。"""
    st.html(
        """
        <style>
        :root {
            --pcr-home-dark: #0B1F3A;
            --pcr-home-dark-2: #12345C;
            --pcr-home-blue: #2563EB;
            --pcr-home-blue-hover: #1D4ED8;
            --pcr-home-cyan: #0EA5B7;
            --pcr-home-bg: #F6FAFC;
            --pcr-home-surface: #FFFFFF;
            --pcr-home-border: #D8E3EA;
            --pcr-home-text: #161616;
            --pcr-home-muted: #64748B;
            --pcr-home-shadow: 0 18px 48px rgba(11, 31, 58, 0.10);
            --pcr-home-font: "IBM Plex Sans", "Microsoft YaHei", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
            --pcr-home-mono: "IBM Plex Mono", "SFMono-Regular", Consolas, monospace;
        }

        .stApp {
            background:
                radial-gradient(circle at 14% 4%, rgba(14, 165, 183, 0.10), transparent 28rem),
                radial-gradient(circle at 82% 0%, rgba(37, 99, 235, 0.10), transparent 30rem),
                linear-gradient(180deg, #F6FAFC 0%, #EEF6FB 100%);
            color: var(--pcr-home-text);
            font-family: var(--pcr-home-font);
        }

        .main .block-container {
            max-width: 100%;
            padding-left: clamp(1rem, 3vw, 2rem);
            padding-right: clamp(1rem, 3vw, 2rem);
            padding-top: 0;
        }

        .pcr-sidebar-expand-hint {
            top: 0.55rem !important;
            left: 2.35rem !important;
            border-radius: 999px !important;
            border: 1px solid rgba(216, 227, 234, 0.85) !important;
            background: rgba(246, 250, 252, 0.92) !important;
            color: #31506F !important;
            box-shadow: 0 8px 22px rgba(11, 31, 58, 0.08) !important;
            backdrop-filter: blur(10px);
        }

        section[data-testid="stSidebar"]:not([aria-expanded="true"]) ~ div .pcr-sidebar-expand-hint,
        body:has([data-testid="collapsedControl"]) .pcr-sidebar-expand-hint {
            display: inline-flex !important;
        }

        section[data-testid="stSidebar"][aria-expanded="true"] ~ div .pcr-sidebar-expand-hint,
        body:has(section[data-testid="stSidebar"][aria-expanded="true"]) .pcr-sidebar-expand-hint {
            display: none !important;
        }

        .pcr-home-hero-refined {
            position: relative;
            overflow: hidden;
            min-height: clamp(620px, 78vh, 760px);
            margin: 0 calc(-1 * clamp(1rem, 3vw, 2rem)) 0 calc(-1 * clamp(1rem, 3vw, 2rem));
            color: #F6FAFC;
            background:
                linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px),
                linear-gradient(135deg, #06172B 0%, #0B1F3A 48%, #12345C 100%);
            background-size: 40px 40px, 40px 40px, auto;
            border: 0;
            box-shadow: 0 36px 90px rgba(11, 31, 58, 0.22);
        }

        .pcr-home-hero-refined::after {
            content: "";
            position: absolute;
            right: -12%;
            bottom: -30%;
            width: 58%;
            height: 58%;
            background: radial-gradient(circle, rgba(14, 165, 183, 0.24), transparent 62%);
            pointer-events: none;
        }

        .pcr-hero-content {
            position: relative;
            z-index: 1;
            width: min(1240px, calc(100vw - 64px));
            min-height: clamp(620px, 78vh, 760px);
            margin: 0 auto;
            display: grid;
            grid-template-columns: minmax(0, 1.03fr) minmax(390px, 0.88fr);
            gap: clamp(2rem, 5vw, 4.5rem);
            align-items: center;
            padding: clamp(3.4rem, 7vw, 5.2rem) 0;
        }

        .pcr-hero-copy {
            min-width: 0;
        }

        .pcr-section-kicker,
        .pcr-home-kicker {
            display: inline-flex;
            align-items: center;
            gap: 0.75rem;
            color: #DFF7FB;
            font-family: var(--pcr-home-mono);
            font-size: 0.76rem;
            letter-spacing: 0.04rem;
            text-transform: uppercase;
        }

        .pcr-home-kicker::before,
        .pcr-section-kicker::before {
            content: "";
            width: 2.5rem;
            height: 1px;
            background: var(--pcr-home-cyan);
            box-shadow: 0 0 16px rgba(14, 165, 183, 0.85);
        }

        .pcr-home-hero-refined h1 {
            max-width: 760px;
            margin: 1.5rem 0 1.45rem 0;
            color: #FFFFFF;
            font-size: clamp(2.95rem, 5.2vw, 4.5rem);
            line-height: 1.08;
            font-weight: 300;
            letter-spacing: 0;
        }

        .pcr-home-hero-refined p {
            max-width: 680px;
            margin: 0;
            color: #D8E3EA;
            font-size: clamp(1rem, 1.3vw, 1.13rem);
            line-height: 1.68;
        }

        .pcr-hero-metrics {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 1px;
            max-width: 650px;
            margin-top: 2.5rem;
            border: 1px solid rgba(216, 227, 234, 0.18);
            background: rgba(216, 227, 234, 0.18);
        }

        .pcr-hero-metric {
            padding: 1rem;
            background: rgba(11, 31, 58, 0.54);
        }

        .pcr-hero-metric strong {
            display: block;
            margin-bottom: 0.35rem;
            color: #FFFFFF;
            font-size: 1.2rem;
            font-weight: 400;
        }

        .pcr-hero-metric span {
            color: #C6C6C6;
            font-size: 0.76rem;
            letter-spacing: 0.02rem;
        }

        .pcr-hero-visual {
            position: relative;
            min-height: 560px;
            display: grid;
            place-items: center;
        }

        .pcr-hero-visual::before,
        .pcr-hero-visual::after {
            content: "";
            position: absolute;
            width: 82%;
            aspect-ratio: 1;
            border: 1px solid rgba(216, 227, 234, 0.16);
            transform: rotate(-8deg);
        }

        .pcr-hero-visual::after {
            width: 74%;
            transform: rotate(8deg);
            border-color: rgba(14, 165, 183, 0.16);
        }

        .pcr-gel-brandmark {
            position: relative;
            z-index: 1;
            width: min(100%, 480px);
            aspect-ratio: 0.9;
            padding: 1.75rem;
            border: 1px solid rgba(216, 227, 234, 0.24);
            background: rgba(255, 255, 255, 0.08);
            box-shadow: 0 28px 80px rgba(0, 0, 0, 0.28);
            backdrop-filter: blur(16px);
        }

        .pcr-gel-core {
            position: relative;
            height: 100%;
            overflow: hidden;
            border: 1px solid rgba(223, 247, 251, 0.18);
            background:
                linear-gradient(180deg, rgba(14, 165, 183, 0.10), transparent 34%, rgba(37, 99, 235, 0.08)),
                repeating-linear-gradient(180deg, rgba(255,255,255,0.04) 0 1px, transparent 1px 28px),
                #071C31;
        }

        .pcr-gel-core::before {
            content: "";
            position: absolute;
            inset: 0;
            background:
                linear-gradient(90deg, transparent 0 11%, rgba(216, 227, 234, 0.08) 11.2% 11.6%, transparent 11.9%);
            background-size: 14.28% 100%;
        }

        .pcr-gel-lane {
            position: absolute;
            top: 12%;
            bottom: 10%;
            width: 11%;
            border-left: 1px solid rgba(216, 227, 234, 0.08);
            border-right: 1px solid rgba(216, 227, 234, 0.05);
        }

        .pcr-gel-lane:nth-child(1) { left: 8%; }
        .pcr-gel-lane:nth-child(2) { left: 21%; }
        .pcr-gel-lane:nth-child(3) { left: 34%; }
        .pcr-gel-lane:nth-child(4) { left: 47%; }
        .pcr-gel-lane:nth-child(5) { left: 60%; }
        .pcr-gel-lane:nth-child(6) { left: 73%; }
        .pcr-gel-lane:nth-child(7) { left: 86%; width: 7%; }

        .pcr-gel-brandmark .pcr-gel-lane::before,
        .pcr-gel-brandmark .pcr-gel-lane::after {
            content: none !important;
            display: none !important;
        }

        .pcr-gel-band {
            position: absolute;
            left: 18%;
            right: 18%;
            height: 0.42rem;
            border-radius: 999px;
            background: #6DEAF3;
            opacity: var(--band-opacity, 0.86);
            filter: blur(0.2px);
            box-shadow: 0 0 16px rgba(109, 234, 243, 0.82), 0 0 28px rgba(14, 165, 183, 0.42);
        }

        .pcr-gel-band.thin { height: 0.18rem; opacity: 0.7; }
        .pcr-gel-band.weak { opacity: 0.34; }
        .pcr-gel-band.smear {
            height: 4.8rem;
            opacity: 0.22;
            background: linear-gradient(180deg, rgba(109,234,243,0.1), rgba(109,234,243,0.85), rgba(109,234,243,0.08));
            filter: blur(8px);
        }

        .pcr-gel-scanline {
            position: absolute;
            left: 0;
            right: 0;
            top: 47%;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(223,247,251,0.92), transparent);
            opacity: 0.65;
        }

        .pcr-gel-float {
            position: absolute;
            right: -1.25rem;
            bottom: 4.2rem;
            width: 12rem;
            border: 1px solid rgba(216, 227, 234, 0.2);
            background: rgba(7, 28, 49, 0.84);
            padding: 1rem 1.1rem;
            color: #F6FAFC;
            box-shadow: 0 20px 48px rgba(0,0,0,0.24);
            backdrop-filter: blur(10px);
        }

        .pcr-gel-float span {
            display: block;
            margin-bottom: 0.45rem;
            color: #9EE7EF;
            font-family: var(--pcr-home-mono);
            font-size: 0.72rem;
            letter-spacing: 0.06rem;
            text-transform: uppercase;
        }

        .pcr-gel-float b {
            display: block;
            margin-bottom: 0.35rem;
            font-size: 1.2rem;
            font-weight: 400;
        }

        .pcr-gel-float p {
            color: #C6C6C6;
            font-size: 0.82rem;
            line-height: 1.5;
        }

        .pcr-hero-action-row {
            width: min(1240px, calc(100vw - 64px));
            margin: -3.7rem auto 5.2rem auto;
            position: relative;
            z-index: 3;
        }

        .st-key-pcr_hero_action_row {
            width: min(1240px, calc(100vw - 64px));
            margin: -3.7rem auto 5.2rem auto;
            position: relative;
            z-index: 3;
        }

        .pcr-hero-action-row [data-testid="column"],
        .st-key-pcr_hero_action_row [data-testid="column"] {
            padding: 0 !important;
        }

        .pcr-hero-action-row button,
        .st-key-pcr_hero_action_row button {
            min-height: 3rem;
            border-radius: 0 !important;
            font-weight: 600 !important;
            letter-spacing: 0 !important;
            transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease;
        }

        .pcr-hero-action-row button:hover,
        .st-key-pcr_hero_action_row button:hover {
            transform: translateY(-1px);
        }

        .pcr-hero-action-row [data-testid="column"]:first-child button,
        .st-key-pcr_hero_action_row [data-testid="column"]:first-child button {
            background: var(--pcr-home-blue) !important;
            color: #FFFFFF !important;
            border-color: var(--pcr-home-blue) !important;
            box-shadow: 0 16px 32px rgba(37, 99, 235, 0.26) !important;
        }

        .pcr-hero-action-row [data-testid="column"]:nth-child(2) button,
        .st-key-pcr_hero_action_row [data-testid="column"]:nth-child(2) button {
            background: rgba(255, 255, 255, 0.04) !important;
            color: #FFFFFF !important;
            border-color: rgba(223, 247, 251, 0.52) !important;
        }

        .pcr-hero-action-row [data-testid="column"]:nth-child(3) button,
        .st-key-pcr_hero_action_row [data-testid="column"]:nth-child(3) button {
            background: rgba(255, 255, 255, 0.02) !important;
            color: #D8E3EA !important;
            border-color: rgba(216, 227, 234, 0.22) !important;
        }

        .pcr-section {
            width: min(1240px, calc(100vw - 64px));
            margin: 0 auto;
            padding: 4.8rem 0;
        }

        .pcr-section-dark {
            width: min(1240px, calc(100vw - 64px));
            margin: 0 auto;
            padding: 4.6rem 0;
            color: #F6FAFC;
        }

        .pcr-section-head {
            display: grid;
            grid-template-columns: minmax(0, 0.92fr) minmax(280px, 0.5fr);
            gap: 2rem;
            align-items: end;
            margin: 0 0 2.4rem 0;
        }

        .pcr-section-head h2 {
            margin: 0;
            color: var(--pcr-home-dark);
            font-size: clamp(2rem, 3vw, 2.85rem);
            line-height: 1.16;
            font-weight: 300;
            letter-spacing: 0;
        }

        .pcr-section-note {
            margin: 0;
            color: var(--pcr-home-muted);
            font-size: 1rem;
            line-height: 1.65;
        }

        .pcr-problem-band {
            margin-left: calc(-1 * clamp(1rem, 3vw, 2rem));
            margin-right: calc(-1 * clamp(1rem, 3vw, 2rem));
            background:
                radial-gradient(circle at 20% 0%, rgba(14, 165, 183, 0.16), transparent 28rem),
                linear-gradient(180deg, #0B1F3A 0%, #0D2747 100%);
        }

        .pcr-problem-band .pcr-section-head h2 {
            color: #FFFFFF;
        }

        .pcr-problem-band .pcr-section-note {
            color: #D8E3EA;
        }

        .pcr-problem-band .pcr-section-kicker {
            color: #9EE7EF;
        }

        .pcr-problem-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 1rem;
        }

        .pcr-problem-card {
            min-height: 17.5rem;
            display: flex;
            flex-direction: column;
            padding: 1.5rem;
            border: 1px solid rgba(216, 227, 234, 0.18);
            background: rgba(255,255,255,0.055);
            box-shadow: none;
            color: #FFFFFF;
        }

        .pcr-problem-card:first-child {
            border-color: rgba(14, 165, 183, 0.45);
            background:
                linear-gradient(180deg, rgba(14, 165, 183, 0.13), rgba(255,255,255,0.04)),
                rgba(255,255,255,0.035);
        }

        .pcr-problem-top,
        .pcr-capability-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 2.1rem;
        }

        .pcr-problem-number {
            color: #9EE7EF;
            font-family: var(--pcr-home-mono);
            font-size: 0.86rem;
            letter-spacing: 0.04rem;
        }

        .pcr-mini-icon {
            width: 2.35rem;
            height: 2.35rem;
            border: 1px solid rgba(216, 227, 234, 0.22);
            background:
                linear-gradient(90deg, transparent 0 34%, rgba(14,165,183,0.72) 34% 44%, transparent 44% 60%, rgba(37,99,235,0.8) 60% 72%, transparent 72%),
                rgba(255,255,255,0.04);
        }

        .pcr-problem-card h3,
        .pcr-flow-card h3,
        .pcr-capability-card h3 {
            margin: 0;
            color: inherit;
            font-size: 1.2rem;
            line-height: 1.36;
            font-weight: 650;
        }

        .pcr-problem-card p {
            margin: auto 0 0 0;
            color: #D8E3EA;
            font-size: 0.96rem;
            line-height: 1.72;
        }

        .pcr-workflow-wrap {
            position: relative;
            padding: 1.5rem 0 0.25rem 0;
        }

        .pcr-workflow-wrap::before {
            content: "";
            position: absolute;
            left: 2rem;
            right: 2rem;
            top: 50%;
            height: 1px;
            background: linear-gradient(90deg, var(--pcr-home-blue), var(--pcr-home-cyan), var(--pcr-home-blue));
            opacity: 0.28;
        }

        .pcr-flow-grid {
            position: relative;
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 0.75rem;
            align-items: start;
        }

        .pcr-flow-card {
            position: relative;
            min-height: 12.6rem;
            padding: 1.15rem;
            border: 1px solid var(--pcr-home-border);
            background: rgba(255, 255, 255, 0.92);
            box-shadow: var(--pcr-home-shadow);
        }

        .pcr-flow-card:nth-child(even) {
            margin-top: 2.35rem;
        }

        .pcr-flow-index {
            width: 2.75rem;
            height: 2.75rem;
            display: grid;
            place-items: center;
            margin-bottom: 1rem;
            background: var(--pcr-home-dark);
            color: #FFFFFF;
            font-family: var(--pcr-home-mono);
            font-size: 0.82rem;
            box-shadow: 0 10px 24px rgba(11,31,58,0.16);
        }

        .pcr-flow-card:nth-child(2) .pcr-flow-index,
        .pcr-flow-card:nth-child(5) .pcr-flow-index {
            background: var(--pcr-home-cyan);
        }

        .pcr-flow-card:nth-child(4) .pcr-flow-index {
            background: var(--pcr-home-blue);
        }

        .pcr-flow-card h3 {
            color: var(--pcr-home-dark);
            font-size: 1.02rem;
        }

        .pcr-flow-card p {
            margin: 0.65rem 0 0 0;
            color: var(--pcr-home-muted);
            font-size: 0.88rem;
            line-height: 1.62;
        }

        .pcr-flow-connector {
            display: none;
        }

        .pcr-capability-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 1rem;
        }

        .pcr-capability-card {
            position: relative;
            min-height: 17.6rem;
            padding: 1.5rem;
            overflow: hidden;
            border: 1px solid var(--pcr-home-border);
            background: #FFFFFF;
            box-shadow: var(--pcr-home-shadow);
        }

        .pcr-capability-card::before {
            content: "";
            position: absolute;
            inset: 0 0 auto 0;
            height: 3px;
            background: linear-gradient(90deg, var(--pcr-home-blue), var(--pcr-home-cyan));
            opacity: 0.72;
        }

        .pcr-capability-card:nth-child(2) {
            border-color: rgba(14, 165, 183, 0.3);
            background:
                linear-gradient(180deg, rgba(224,247,250,0.86), rgba(255,255,255,0.96) 48%),
                #FFFFFF;
        }

        .pcr-capability-icon {
            width: 3rem;
            height: 3rem;
            display: grid;
            place-items: center;
            margin-bottom: 1.8rem;
            border: 1px solid var(--pcr-home-border);
            color: var(--pcr-home-blue);
            background: #EFF6FF;
            font-family: var(--pcr-home-mono);
            font-size: 0.86rem;
        }

        .pcr-capability-icon.cyan {
            color: var(--pcr-home-cyan);
            background: #E0F7FA;
        }

        .pcr-capability-card h3 {
            color: var(--pcr-home-dark);
            font-size: 1.25rem;
        }

        .pcr-capability-card p {
            margin: 1rem 0 0 0;
            color: #334155;
            font-size: 0.96rem;
            line-height: 1.72;
        }

        .pcr-status-footer-wrap {
            margin-left: calc(-1 * clamp(1rem, 3vw, 2rem));
            margin-right: calc(-1 * clamp(1rem, 3vw, 2rem));
            padding: 4.8rem 0 5.1rem 0;
            color: #F4F4F4;
            background:
                linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px),
                #071C31;
            background-size: 40px 40px, 40px 40px, auto;
        }

        .pcr-status-footer {
            width: min(1240px, calc(100vw - 64px));
            margin: 0 auto;
            display: grid;
            grid-template-columns: 0.9fr 1.25fr;
            gap: 1px;
            border: 1px solid rgba(216, 227, 234, 0.18);
            background: rgba(216, 227, 234, 0.16);
        }

        .pcr-status-intro,
        .pcr-status-grid {
            background: rgba(11, 31, 58, 0.72);
            padding: 2rem;
        }

        .pcr-status-intro h2 {
            margin: 1rem 0 1rem 0;
            color: #FFFFFF;
            font-size: clamp(1.85rem, 3vw, 2.5rem);
            line-height: 1.18;
            font-weight: 300;
        }

        .pcr-status-intro p {
            margin: 0;
            color: #C6C6C6;
            font-size: 0.95rem;
            line-height: 1.68;
        }

        .pcr-tech-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 1.5rem;
        }

        .pcr-tech-row span {
            border: 1px solid rgba(14,165,183,0.32);
            background: rgba(14,165,183,0.12);
            color: #DFF7FB;
            padding: 0.32rem 0.7rem;
            font-size: 0.78rem;
        }

        .pcr-status-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
        }

        .pcr-status-card {
            padding: 1.1rem;
            border: 1px solid rgba(216, 227, 234, 0.16);
            background: rgba(255,255,255,0.04);
        }

        .pcr-status-label {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: #D8E3EA;
            font-size: 0.86rem;
            margin-bottom: 0.8rem;
        }

        .pcr-status-dot {
            width: 0.5rem;
            height: 0.5rem;
            border-radius: 50%;
            background: #24A148;
            box-shadow: 0 0 12px rgba(36, 161, 72, 0.72);
        }

        .pcr-status-dot.warn {
            background: #F1C21B;
            box-shadow: 0 0 12px rgba(241, 194, 27, 0.72);
        }

        .pcr-status-dot.info {
            background: var(--pcr-home-cyan);
            box-shadow: 0 0 12px rgba(14, 165, 183, 0.72);
        }

        .pcr-status-value {
            color: #FFFFFF;
            font-size: 1.05rem;
            line-height: 1.45;
            font-weight: 400;
        }

        .pcr-footer-action-row {
            width: min(1240px, calc(100vw - 64px));
            margin: 1rem auto 0 auto;
        }

        .st-key-pcr_footer_action_row {
            width: min(1240px, calc(100vw - 64px));
            margin: -3rem auto 0 auto;
            position: relative;
            z-index: 2;
        }

        .pcr-footer-action-row button,
        .st-key-pcr_footer_action_row button {
            min-height: 2.5rem;
            border-radius: 0 !important;
            background: rgba(255,255,255,0.04) !important;
            color: #D8E3EA !important;
            border-color: rgba(216,227,234,0.22) !important;
            box-shadow: none !important;
        }

        @media (max-width: 1180px) {
            .pcr-hero-content {
                grid-template-columns: 1fr;
            }

            .pcr-hero-visual {
                min-height: 480px;
            }

            .pcr-flow-grid {
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }

            .pcr-flow-card:nth-child(even) {
                margin-top: 0;
            }

            .pcr-workflow-wrap::before {
                display: none;
            }

            .pcr-capability-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 760px) {
            .pcr-hero-content,
            .pcr-hero-action-row,
            .st-key-pcr_hero_action_row,
            .pcr-section,
            .pcr-section-dark,
            .pcr-status-footer,
            .pcr-footer-action-row {
                width: min(100%, calc(100vw - 32px));
            }

            .pcr-home-hero-refined,
            .pcr-hero-content {
                min-height: auto;
            }

            .pcr-home-hero-refined h1 {
                font-size: 2.35rem;
            }

            .pcr-hero-action-row {
                margin-top: -2.2rem;
            }

            .pcr-hero-metrics,
            .pcr-problem-grid,
            .pcr-flow-grid,
            .pcr-capability-grid,
            .pcr-status-footer,
            .pcr-status-grid,
            .pcr-section-head {
                grid-template-columns: 1fr;
            }

            .pcr-problem-card,
            .pcr-flow-card,
            .pcr-capability-card {
                min-height: auto;
            }

            .pcr-gel-float {
                right: 0.8rem;
                bottom: 1.4rem;
            }
        }
        </style>
        """
    )


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
            "学生不知道从哪里排查失败原因",
            "PCR-电泳实验出现无条带、弱带、多条带、拖尾等异常后，学生往往难以判断问题来自模板、引物、体系、程序还是电泳条件。",
        ),
        (
            "02",
            "教师重复解释相似异常",
            "教师需要反复处理相似实验失败案例，但很多排错经验停留在口头解释中，难以沉淀为可复用案例。",
        ),
        (
            "03",
            "课程缺少结构化失败案例",
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
        ("01", "学生提交异常", "记录异常现象、对照结果、PCR 参数、文字描述和凝胶图片。"),
        ("02", "信息标准化", "将学生输入归一化为诊断规则可识别的结构化字段。"),
        ("03", "规则矩阵诊断", "基于 rules.csv 基础规则生成候选原因排序。"),
        ("04", "组合规则加权", "结合 rule_combos.csv 对关键证据组合进行加权修正。"),
        ("05", "教师确认", "教师查看系统判断并确认最终原因。"),
        ("06", "案例沉淀与统计", "历史记录进入教师端看板，用于复盘、筛选和教学分析。"),
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
        ("01", "结构化采集", "支持记录异常现象、阳性/阴性对照、PCR 参数、学生补充描述和凝胶图片。", "blue"),
        ("02", "规则诊断", "基于基础规则与组合规则生成 Top1 / Top2 / Top3 候选原因。", "cyan"),
        ("03", "证据解释", "展示诊断依据、置信度、证据摘要和缺失信息提示，避免只给结论。", "blue"),
        ("04", "教师闭环", "教师可确认最终原因、填写备注，并通过统计看板追踪系统判断与教师确认的一致性。", "cyan"),
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
        <div class="pcr-status-footer-wrap">
            <div class="pcr-status-footer">
                <div class="pcr-status-intro">
                    <div class="pcr-section-kicker">Entry summary</div>
                    <h2>产品状态与角色入口摘要</h2>
                    <p>这里展示当前会话可进入的角色状态，让首页保持展示感，也让进入工作台时路径清晰。</p>
                    <div class="pcr-tech-row">
                        <span>Streamlit</span>
                        <span>rules.csv</span>
                        <span>rule_combos.csv</span>
                        <span>教师复核</span>
                    </div>
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

    with st.container(key="pcr_footer_action_row"):
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
    render_home_refined_styles()

    st.html('<div class="pcr-sidebar-expand-hint">点此展开侧边栏</div>')

    st.html(
        """
        <div class="pcr-home-hero-refined">
            <div class="pcr-hero-content">
                <div class="pcr-hero-copy">
                    <div class="pcr-home-kicker">Teaching diagnostic system</div>
                    <h1>分子生物学实验 PCR-电泳异常智能复盘助手</h1>
                    <p>面向分子生物学实验教学场景，帮助学生结构化记录异常现象，辅助系统生成候选原因，并支持教师复核确认与案例沉淀。</p>
                    <div class="pcr-hero-metrics">
                        <div class="pcr-hero-metric"><strong>Top 1/2/3</strong><span>候选原因排序</span></div>
                        <div class="pcr-hero-metric"><strong>rules.csv</strong><span>基础规则矩阵</span></div>
                        <div class="pcr-hero-metric"><strong>教师确认</strong><span>复盘闭环沉淀</span></div>
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
                        <div class="pcr-gel-float">
                            <span>Evidence</span>
                            <b>Top1 / Top2</b>
                            <p>规则矩阵 · 组合加权</p>
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
            if st.button("开始学生诊断", key="home_enter_student", type="primary", use_container_width=True):
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
        <div class="pcr-problem-band">
            <section class="pcr-section-dark">
                {build_home_section_title_html("把实验异常从口头排查变成可复盘的教学线索", "Problems：学生、教师和课程建设共同面对的三个问题。")}
                {build_problem_cards_html()}
            </section>
        </div>
        """,
    )

    st.html(
        f"""
        <section class="pcr-section">
            {build_home_section_title_html("从异常记录到教师确认，形成一条可解释的诊断路径", "Workflow：六步流程覆盖学生记录、信息标准化、规则判断、教师确认与案例沉淀。")}
            {build_workflow_section_html()}
        </section>
        """,
    )

    st.html(
        f"""
        <section class="pcr-section">
            {build_home_section_title_html("围绕采集、诊断、解释、闭环展开的能力矩阵", "Capabilities：让实验失败记录能够被解释、复核和持续积累。")}
            {build_capability_cards_html()}
        </section>
        """,
    )

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
