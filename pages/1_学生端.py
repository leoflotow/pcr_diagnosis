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
    build_diagnosis_context,
    build_case_summary,
    build_evidence_summary,
    compute_confidence_level,
    diagnose,
    detect_missing_key_info,
    ensure_page_config,
    init_database,
    render_card_title,
    render_page_hero,
    return_to_home,
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
    "实验现象与对照",
    "PCR 关键参数",
    "描述与图片",
    "确认并诊断",
]


def render_student_refined_styles():
    """学生端专属样式：隐藏侧边栏，并与首页深蓝视觉保持一致。"""
    st.markdown(
        """
        <style>
        :root {
            --pcr-primary: #0B1F3A;
            --pcr-primary-2: #2563EB;
            --pcr-accent: #0EA5B7;
            --pcr-bg: #07172B;
            --pcr-card: rgba(223, 247, 251, 0.13);
            --pcr-text: #F6FAFC;
            --pcr-muted: #D8E3EA;
            --pcr-border: rgba(216, 227, 234, 0.20);
        }

        .stApp {
            background:
                linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px),
                radial-gradient(circle at 14% 0%, rgba(14, 165, 183, 0.18), transparent 28rem),
                radial-gradient(circle at 88% 4%, rgba(37, 99, 235, 0.18), transparent 30rem),
                linear-gradient(135deg, #06172B 0%, #0B1F3A 48%, #12345C 100%) !important;
            background-size: 40px 40px, 40px 40px, auto, auto, auto;
            color: #F6FAFC;
            font-family: "IBM Plex Sans", "Microsoft YaHei", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
        }

        header[data-testid="stHeader"],
        div[data-testid="stToolbar"],
        div[data-testid="stDecoration"],
        section[data-testid="stSidebar"],
        [data-testid="collapsedControl"],
        .pcr-sidebar-expand-hint {
            display: none !important;
            width: 0 !important;
            min-width: 0 !important;
        }

        .main .block-container,
        .block-container,
        .stMainBlockContainer,
        div[data-testid="stMainBlockContainer"],
        section[data-testid="stMain"] > div {
            max-width: min(1240px, calc(100vw - 48px)) !important;
            width: min(1240px, calc(100vw - 48px)) !important;
            margin-left: auto !important;
            margin-right: auto !important;
            padding-top: 1.2rem !important;
            padding-bottom: 3rem !important;
        }

        .pcr-student-topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.85rem;
            color: #D8E3EA;
            font-size: 0.88rem;
        }

        .pcr-student-page-label {
            display: inline-flex;
            align-items: center;
            gap: 0.7rem;
            color: #DFF7FB;
            font-size: 0.78rem;
            letter-spacing: 0.04rem;
            text-transform: uppercase;
        }

        .pcr-student-page-label::before {
            content: "";
            width: 2.35rem;
            height: 1px;
            background: #0EA5B7;
            box-shadow: 0 0 16px rgba(14, 165, 183, 0.85);
        }

        .pcr-hero {
            border-radius: 0 !important;
            border: 1px solid rgba(216, 227, 234, 0.20) !important;
            background:
                linear-gradient(135deg, rgba(255,255,255,0.09), rgba(223,247,251,0.035)),
                linear-gradient(135deg, rgba(6,23,43,0.98), rgba(18,52,92,0.92)) !important;
            box-shadow: 0 24px 70px rgba(0, 0, 0, 0.24) !important;
            padding: clamp(1.35rem, 2.6vw, 2rem) !important;
            margin-bottom: 1rem !important;
            min-height: auto !important;
        }

        .pcr-hero::after {
            opacity: 0.48 !important;
        }

        .pcr-hero h1 {
            color: #FFFFFF !important;
            font-weight: 550 !important;
            font-size: clamp(2rem, 3vw, 3.05rem) !important;
            line-height: 1.16 !important;
            max-width: 16em !important;
            margin-top: 0.6rem !important;
        }

        .pcr-hero p {
            color: #D8E3EA !important;
            max-width: 42rem !important;
        }

        .pcr-role-badge,
        .pcr-current-step-chip {
            border-radius: 999px !important;
            border: 1px solid rgba(223, 247, 251, 0.34) !important;
            background: rgba(223, 247, 251, 0.10) !important;
            color: #DFF7FB !important;
        }

        div[data-testid="stVerticalBlockBorderWrapper"],
        .pcr-student-toolbar,
        .pcr-readiness-panel,
        .pcr-stepper-item,
        .pcr-review-item,
        .pcr-sub-card,
        .pcr-top1-card,
        [data-testid="stExpander"],
        [data-testid="stMetric"] {
            border-color: rgba(216, 227, 234, 0.20) !important;
            background: rgba(223, 247, 251, 0.12) !important;
            box-shadow: 0 18px 48px rgba(0, 0, 0, 0.16) !important;
            backdrop-filter: blur(14px);
        }

        .pcr-stepper-item.active {
            border-color: rgba(109, 234, 243, 0.56) !important;
            background: rgba(14, 165, 183, 0.20) !important;
        }

        .pcr-stepper-item.done {
            border-color: rgba(109, 234, 243, 0.34) !important;
            background: rgba(14, 165, 183, 0.12) !important;
        }

        .pcr-card-title,
        .pcr-step-title,
        .pcr-stepper-title,
        .pcr-review-value,
        .pcr-readiness-item b,
        .pcr-student-toolbar-title,
        .pcr-candidate-row b,
        .pcr-top1-card * {
            color: #FFFFFF !important;
        }

        .pcr-muted,
        .pcr-step-desc,
        .pcr-stepper-status,
        .pcr-review-label,
        .pcr-readiness-item span,
        .pcr-student-toolbar-desc,
        .stCaptionContainer,
        .stMarkdown p,
        label {
            color: #D8E3EA !important;
        }

        .pcr-step-kicker,
        .pcr-readiness-title {
            color: #6DEAF3 !important;
        }

        div.stButton > button,
        div.stDownloadButton > button {
            border-radius: 0.25rem !important;
            min-height: 2.8rem;
        }

        div.stButton > button:not([kind="primary"]),
        div.stDownloadButton > button {
            background: rgba(223, 247, 251, 0.08) !important;
            color: #DFF7FB !important;
            border: 1px solid rgba(223, 247, 251, 0.32) !important;
        }

        button[kind="primary"] {
            background: #2563EB !important;
            border-color: #2563EB !important;
            color: #FFFFFF !important;
        }

        .stProgress > div > div > div > div {
            background: linear-gradient(90deg, #2563EB, #0EA5B7) !important;
        }

        input, textarea, [data-baseweb="select"] > div {
            background-color: rgba(255,255,255,0.92) !important;
        }

        @media (max-width: 768px) {
            .main .block-container,
            .block-container,
            .stMainBlockContainer,
            div[data-testid="stMainBlockContainer"],
            section[data-testid="stMain"] > div {
                max-width: calc(100vw - 28px) !important;
                width: calc(100vw - 28px) !important;
                padding-top: 0.85rem !important;
            }

            .pcr-student-topbar {
                display: block;
            }
        }

        .pcr-student-page-shell {
            max-width: 1240px;
            margin: 0 auto;
        }

        .pcr-student-topbar {
            max-width: 1240px;
            margin-left: auto;
            margin-right: auto;
        }

        .pcr-student-topbar-row,
        .st-key-pcr_student_topbar_row {
            max-width: 1240px;
            margin: 0 auto 0.85rem auto;
        }

        .pcr-student-page-label {
            color: rgba(223, 247, 251, 0.92) !important;
            text-transform: none;
            letter-spacing: 0;
            font-weight: 750;
        }

        .pcr-hero {
            max-width: 1240px;
            margin-left: auto !important;
            margin-right: auto !important;
            border-radius: 16px !important;
            padding: 1.25rem 1.5rem !important;
            min-height: 11.5rem !important;
        }

        .pcr-hero h1 {
            font-size: clamp(1.82rem, 2.45vw, 2.42rem) !important;
            max-width: 18em !important;
        }

        .pcr-hero p {
            color: rgba(255,255,255,0.82) !important;
            font-size: 1rem !important;
            line-height: 1.72 !important;
            max-width: 52rem !important;
        }

        .pcr-role-badge {
            background: rgba(14,165,183,0.16) !important;
            border-color: rgba(109,234,243,0.38) !important;
            color: #DFF7FB !important;
        }

        .st-key-pcr_student_return button,
        .pcr-student-return button {
            background: rgba(223,247,251,0.06) !important;
            border: 1px solid rgba(223,247,251,0.42) !important;
            color: #EAFBFF !important;
        }

        .pcr-student-guide {
            max-width: 1240px;
            margin: 0 auto 1rem auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            border: 1px solid rgba(216, 227, 234, 0.18);
            border-radius: 16px;
            background: rgba(223, 247, 251, 0.11);
            box-shadow: 0 18px 48px rgba(0,0,0,0.14);
            padding: 1rem 1.1rem;
            backdrop-filter: blur(14px);
        }

        .pcr-student-guide-title {
            color: #FFFFFF;
            font-weight: 760;
            font-size: 1rem;
            margin-bottom: 0.18rem;
        }

        .pcr-student-guide-desc {
            color: rgba(255,255,255,0.76);
            margin: 0;
            line-height: 1.62;
            font-size: 0.92rem;
        }

        .pcr-student-guide-chip {
            flex: 0 0 auto;
            color: #DFF7FB;
            border: 1px solid rgba(109,234,243,0.38);
            background: rgba(14,165,183,0.14);
            border-radius: 999px;
            padding: 0.28rem 0.78rem;
            font-size: 0.8rem;
            font-weight: 760;
        }

        .pcr-current-step-summary,
        .pcr-stepper-grid,
        .stProgress {
            max-width: 1240px;
            margin-left: auto !important;
            margin-right: auto !important;
        }

        .pcr-current-step-summary {
            border: 1px solid rgba(216, 227, 234, 0.16);
            border-radius: 16px;
            background: rgba(223, 247, 251, 0.10);
            padding: 0.95rem 1.05rem;
            box-shadow: 0 14px 34px rgba(0,0,0,0.12);
        }

        .pcr-step-kicker {
            color: #6DEAF3 !important;
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 0.18rem;
        }

        .pcr-step-title {
            color: #FFFFFF !important;
            font-size: 1.08rem;
            font-weight: 780;
            line-height: 1.45;
        }

        .pcr-step-desc {
            color: rgba(255,255,255,0.74) !important;
            margin-top: 0.22rem;
            font-size: 0.92rem;
            line-height: 1.58;
        }

        .pcr-stepper-grid {
            grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
            gap: 0.8rem !important;
            margin-top: 0.85rem !important;
            margin-bottom: 0.75rem !important;
        }

        .pcr-stepper-item {
            border: 1px solid rgba(216,227,234,0.18) !important;
            background: rgba(223,247,251,0.10) !important;
            border-radius: 14px !important;
            min-height: 6.2rem !important;
            padding: 0.85rem 0.9rem !important;
            box-shadow: none !important;
        }

        .pcr-stepper-item.active {
            border-color: rgba(109,234,243,0.56) !important;
            background: rgba(14,165,183,0.20) !important;
        }

        .pcr-stepper-item.done {
            border-color: rgba(109,234,243,0.34) !important;
            background: rgba(14,165,183,0.12) !important;
        }

        .pcr-stepper-index {
            background: rgba(255,255,255,0.12) !important;
            color: #DFF7FB !important;
            border: 1px solid rgba(223,247,251,0.22);
        }

        .pcr-stepper-item.active .pcr-stepper-index,
        .pcr-stepper-item.done .pcr-stepper-index {
            background: #0EA5B7 !important;
            color: #FFFFFF !important;
        }

        .pcr-stepper-title {
            color: #FFFFFF !important;
            font-size: 0.92rem !important;
            line-height: 1.38 !important;
        }

        .pcr-stepper-status {
            color: rgba(255,255,255,0.72) !important;
        }

        .pcr-current-step-chip {
            background: rgba(14,165,183,0.16) !important;
            border-color: rgba(109,234,243,0.38) !important;
            color: #DFF7FB !important;
        }

        .st-key-pcr_student_workspace {
            max-width: 1240px;
            margin: 1rem auto 0 auto;
        }

        .st-key-pcr_student_workspace [data-testid="stHorizontalBlock"] {
            align-items: flex-start;
        }

        .st-key-pcr_student_workspace [data-testid="column"] {
            min-width: 0;
        }

        .st-key-pcr_student_form_card_step1 div[data-testid="stVerticalBlockBorderWrapper"],
        .st-key-pcr_student_form_card_step2 div[data-testid="stVerticalBlockBorderWrapper"],
        .st-key-pcr_student_form_card_step3 div[data-testid="stVerticalBlockBorderWrapper"],
        .st-key-pcr_student_form_card_step4 div[data-testid="stVerticalBlockBorderWrapper"] {
            min-height: 430px !important;
            border-radius: 16px !important;
            border: 1px solid rgba(216, 227, 234, 0.18) !important;
            background: rgba(223, 247, 251, 0.12) !important;
            box-shadow: 0 22px 56px rgba(0,0,0,0.18) !important;
            backdrop-filter: blur(14px);
        }

        .st-key-pcr_student_form_card_step1 div[data-testid="stVerticalBlockBorderWrapper"] > div,
        .st-key-pcr_student_form_card_step2 div[data-testid="stVerticalBlockBorderWrapper"] > div,
        .st-key-pcr_student_form_card_step3 div[data-testid="stVerticalBlockBorderWrapper"] > div,
        .st-key-pcr_student_form_card_step4 div[data-testid="stVerticalBlockBorderWrapper"] > div {
            padding: 1.1rem 1.2rem !important;
        }

        .pcr-card-title {
            color: #FFFFFF !important;
            font-size: 1.18rem !important;
            font-weight: 780 !important;
        }

        .pcr-muted {
            color: rgba(255,255,255,0.76) !important;
            line-height: 1.64 !important;
        }

        label,
        [data-testid="stWidgetLabel"],
        [data-testid="stWidgetLabel"] p,
        .stRadio label,
        .stRadio label p,
        .stSelectbox label,
        .stNumberInput label,
        .stTextArea label,
        .stFileUploader label {
            color: rgba(255,255,255,0.88) !important;
            font-weight: 680 !important;
        }

        input,
        textarea,
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div,
        [data-baseweb="textarea"] {
            background-color: #FFFFFF !important;
            color: #0B1F3A !important;
            border-color: rgba(14,165,183,0.34) !important;
        }

        input::placeholder,
        textarea::placeholder {
            color: #64748B !important;
            opacity: 1 !important;
        }

        [data-baseweb="select"] span,
        [data-baseweb="select"] div,
        [data-baseweb="input"] input,
        [data-baseweb="textarea"] textarea {
            color: #0B1F3A !important;
        }

        .stCaptionContainer,
        .stCaptionContainer p,
        .stMarkdown p {
            color: rgba(255,255,255,0.76) !important;
        }

        .pcr-student-actions {
            margin-top: 0.95rem;
        }

        .pcr-student-actions [data-testid="stHorizontalBlock"] {
            align-items: stretch;
        }

        .pcr-readiness-panel {
            position: sticky;
            top: 1rem;
            min-height: 430px;
            border: 1px solid rgba(216, 227, 234, 0.18) !important;
            border-radius: 16px !important;
            background: rgba(7, 23, 43, 0.58) !important;
            box-shadow: 0 22px 56px rgba(0,0,0,0.18) !important;
            backdrop-filter: blur(14px);
            padding: 1.1rem !important;
            margin-bottom: 1rem !important;
        }

        .pcr-readiness-title {
            color: #FFFFFF !important;
            font-size: 1.05rem !important;
            font-weight: 820 !important;
            margin-bottom: 0.25rem !important;
        }

        .pcr-readiness-desc {
            color: rgba(255,255,255,0.74);
            margin: 0 0 0.85rem 0;
            font-size: 0.9rem;
            line-height: 1.58;
        }

        .pcr-readiness-grid {
            display: grid !important;
            grid-template-columns: 1fr !important;
            gap: 0.58rem !important;
        }

        .pcr-readiness-item {
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 0.56rem;
            align-items: flex-start;
            border-radius: 12px !important;
            padding: 0.72rem 0.76rem !important;
            border: 1px solid rgba(216,227,234,0.14) !important;
            background: rgba(223,247,251,0.09) !important;
        }

        .pcr-readiness-dot {
            width: 0.58rem;
            height: 0.58rem;
            margin-top: 0.35rem;
            border-radius: 999px;
            background: rgba(216,227,234,0.44);
            box-shadow: none;
        }

        .pcr-readiness-dot.done {
            background: #0EA5B7;
            box-shadow: 0 0 14px rgba(109,234,243,0.55);
        }

        .pcr-readiness-label {
            color: rgba(255,255,255,0.72);
            font-size: 0.76rem;
            font-weight: 760;
            margin-bottom: 0.12rem;
        }

        .pcr-readiness-value {
            display: block;
            color: #FFFFFF;
            font-size: 0.92rem;
            font-weight: 760;
            line-height: 1.48;
            overflow-wrap: anywhere;
        }

        .pcr-review-grid,
        .pcr-result-meta-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        }

        .pcr-review-item,
        .pcr-candidate-row {
            border-color: rgba(216,227,234,0.16) !important;
            background: rgba(255,255,255,0.95) !important;
        }

        .pcr-review-label {
            color: #475569 !important;
        }

        .pcr-review-value,
        .pcr-candidate-row b,
        .pcr-candidate-row span {
            color: #0B1F3A !important;
        }

        .pcr-gel-placeholder {
            border-color: rgba(109,234,243,0.42) !important;
            background:
                repeating-linear-gradient(90deg, rgba(14,165,183,0.14) 0 10px, transparent 10px 32px),
                linear-gradient(180deg, rgba(223,248,251,0.18), rgba(223,248,251,0.08)) !important;
            color: rgba(255,255,255,0.76) !important;
        }

        .pcr-gel-placeholder b {
            color: #FFFFFF !important;
        }

        .pcr-top1-card {
            border: 1px solid rgba(109,234,243,0.34) !important;
            background:
                linear-gradient(135deg, rgba(14,165,183,0.20), rgba(37,99,235,0.12)),
                rgba(7,23,43,0.72) !important;
            border-radius: 16px !important;
        }

        .pcr-top1-card,
        .pcr-top1-card * {
            color: #FFFFFF !important;
        }

        [data-testid="stExpander"] {
            border: 1px solid rgba(216,227,234,0.20) !important;
            border-radius: 12px !important;
            background: rgba(7,23,43,0.62) !important;
            overflow: hidden;
        }

        [data-testid="stExpander"] details summary {
            background: rgba(223,247,251,0.12) !important;
            color: #FFFFFF !important;
        }

        [data-testid="stExpander"] details summary *,
        [data-testid="stExpander"] p,
        [data-testid="stExpander"] li {
            color: #FFFFFF !important;
        }

        @media (max-width: 900px) {
            .pcr-student-guide,
            .pcr-current-step-summary {
                display: block;
            }

            .pcr-stepper-grid,
            .pcr-review-grid,
            .pcr-result-meta-grid {
                grid-template-columns: 1fr !important;
            }

            .pcr-readiness-panel {
                position: static;
                min-height: auto;
            }

            .st-key-pcr_student_form_card_step1 div[data-testid="stVerticalBlockBorderWrapper"],
            .st-key-pcr_student_form_card_step2 div[data-testid="stVerticalBlockBorderWrapper"],
            .st-key-pcr_student_form_card_step3 div[data-testid="stVerticalBlockBorderWrapper"],
            .st-key-pcr_student_form_card_step4 div[data-testid="stVerticalBlockBorderWrapper"] {
                min-height: auto !important;
            }
        }

        /* Final student workbench overrides. Keep these scoped to this page. */
        .main .block-container,
        .block-container,
        .stMainBlockContainer,
        div[data-testid="stMainBlockContainer"],
        section[data-testid="stMain"] > div {
            max-width: min(1480px, calc(100vw - 64px)) !important;
            width: min(1480px, calc(100vw - 64px)) !important;
        }

        .pcr-hero,
        .pcr-student-topbar-row,
        .st-key-pcr_student_topbar_row,
        .pcr-student-guide,
        .pcr-current-step-summary,
        .pcr-stepper-grid,
        .stProgress,
        .st-key-pcr_student_workspace,
        .pcr-student-result-page {
            max-width: min(1480px, calc(100vw - 64px)) !important;
            width: min(1480px, calc(100vw - 64px)) !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }

        .pcr-hero {
            min-height: 9.5rem !important;
            display: flex;
            flex-direction: column;
            justify-content: center;
            position: relative;
        }

        .pcr-hero::before {
            content: "";
            position: absolute;
            right: 1.4rem;
            top: 1.2rem;
            width: min(16rem, 24vw);
            height: 5.8rem;
            border-radius: 14px;
            opacity: 0.34;
            background:
                repeating-linear-gradient(90deg, rgba(109,234,243,0.30) 0 2px, transparent 2px 1.55rem),
                linear-gradient(135deg, rgba(14,165,183,0.25), rgba(37,99,235,0.20));
        }

        .pcr-hero h1,
        .pcr-hero p,
        .pcr-role-badge {
            max-width: 54rem !important;
        }

        .pcr-hero h1 {
            font-size: clamp(1.72rem, 2.15vw, 2.28rem) !important;
        }

        .pcr-student-guide {
            display: flex !important;
        }

        .st-key-pcr_student_workspace div[data-testid="stHorizontalBlock"] {
            gap: 1rem;
        }

        .st-key-pcr_student_form_card_step1 div[data-testid="stVerticalBlockBorderWrapper"],
        .st-key-pcr_student_form_card_step2 div[data-testid="stVerticalBlockBorderWrapper"],
        .st-key-pcr_student_form_card_step3 div[data-testid="stVerticalBlockBorderWrapper"],
        .st-key-pcr_student_form_card_step4 div[data-testid="stVerticalBlockBorderWrapper"],
        .pcr-readiness-panel {
            min-height: 420px !important;
        }

        .pcr-readiness-panel {
            top: 0.85rem;
        }

        .pcr-student-result-page {
            display: grid;
            gap: 1rem;
            margin-top: 1rem;
        }

        .pcr-result-overview,
        .pcr-result-primary,
        .pcr-result-candidates,
        .pcr-result-evidence,
        .pcr-input-summary,
        .pcr-result-actions {
            border: 1px solid rgba(216,227,234,0.18);
            border-radius: 18px;
            background: rgba(7,23,43,0.64);
            box-shadow: 0 24px 64px rgba(0,0,0,0.18);
            backdrop-filter: blur(16px);
            padding: 1.2rem;
        }

        .pcr-result-overview {
            display: grid;
            grid-template-columns: minmax(0, 1.35fr) minmax(18rem, 0.65fr);
            gap: 1rem;
            background:
                linear-gradient(135deg, rgba(14,165,183,0.18), rgba(37,99,235,0.12)),
                rgba(7,23,43,0.68);
        }

        .pcr-result-kicker,
        .pcr-result-label {
            color: #6DEAF3;
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 0.32rem;
        }

        .pcr-result-title {
            margin: 0;
            color: #FFFFFF;
            font-size: clamp(1.42rem, 2vw, 2rem);
            line-height: 1.35;
            font-weight: 820;
        }

        .pcr-result-desc,
        .pcr-result-note,
        .pcr-result-card p,
        .pcr-result-evidence li {
            color: rgba(255,255,255,0.76);
            line-height: 1.68;
        }

        .pcr-result-stat-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.65rem;
        }

        .pcr-result-stat,
        .pcr-result-card,
        .pcr-input-summary-item {
            border: 1px solid rgba(216,227,234,0.14);
            border-radius: 14px;
            background: rgba(223,247,251,0.09);
            padding: 0.78rem 0.85rem;
        }

        .pcr-result-stat span,
        .pcr-input-summary-label {
            display: block;
            color: rgba(255,255,255,0.68);
            font-size: 0.76rem;
            font-weight: 760;
            margin-bottom: 0.18rem;
        }

        .pcr-result-stat b,
        .pcr-input-summary-value {
            color: #FFFFFF;
            font-size: 0.98rem;
            line-height: 1.45;
            overflow-wrap: anywhere;
        }

        .pcr-confidence-pill {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.22rem 0.74rem;
            color: #FFFFFF;
            background: rgba(14,165,183,0.28);
            border: 1px solid rgba(109,234,243,0.38);
            font-weight: 820;
        }

        .pcr-result-primary-grid {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(18rem, 0.78fr);
            gap: 1rem;
            align-items: stretch;
        }

        .pcr-primary-reason {
            color: #FFFFFF;
            font-size: clamp(1.24rem, 1.65vw, 1.7rem);
            line-height: 1.38;
            font-weight: 840;
            margin: 0.2rem 0 0.55rem 0;
        }

        .pcr-score-chip {
            display: inline-flex;
            border-radius: 999px;
            padding: 0.2rem 0.68rem;
            background: rgba(37,99,235,0.28);
            border: 1px solid rgba(147,197,253,0.34);
            color: #FFFFFF;
            font-weight: 780;
            font-size: 0.82rem;
        }

        .pcr-evidence-list {
            margin: 0.8rem 0 0 0;
            padding-left: 1.1rem;
        }

        .pcr-candidate-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.8rem;
        }

        .pcr-candidate-card {
            border: 1px solid rgba(216,227,234,0.14);
            border-radius: 14px;
            background: rgba(223,247,251,0.08);
            padding: 0.92rem;
        }

        .pcr-candidate-rank {
            color: #6DEAF3;
            font-size: 0.76rem;
            font-weight: 820;
            margin-bottom: 0.3rem;
        }

        .pcr-candidate-card h4 {
            color: #FFFFFF;
            margin: 0 0 0.35rem 0;
            font-size: 1rem;
            line-height: 1.38;
        }

        .pcr-input-summary-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.75rem;
        }

        .pcr-result-actions-row {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.8rem;
        }

        .pcr-result-actions h3,
        .pcr-result-section-title {
            color: #FFFFFF;
            margin: 0 0 0.75rem 0;
            font-size: 1.15rem;
        }

        @media (max-width: 980px) {
            .main .block-container,
            .block-container,
            .stMainBlockContainer,
            div[data-testid="stMainBlockContainer"],
            section[data-testid="stMain"] > div,
            .pcr-hero,
            .pcr-student-topbar-row,
            .st-key-pcr_student_topbar_row,
            .pcr-student-guide,
            .pcr-current-step-summary,
            .pcr-stepper-grid,
            .stProgress,
            .st-key-pcr_student_workspace,
            .pcr-student-result-page {
                max-width: calc(100vw - 28px) !important;
                width: calc(100vw - 28px) !important;
            }

            .pcr-result-overview,
            .pcr-result-primary-grid,
            .pcr-candidate-grid,
            .pcr-input-summary-grid,
            .pcr-result-actions-row {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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


def restore_widget_value_from_storage(key):
    """渲染步骤前从持久区恢复控件值，避免步骤切换后表单与摘要不同步。"""
    storage = st.session_state.get("student_data_storage", {})
    if key in storage:
        st.session_state[key] = storage[key]


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
    if "student_show_result_report" not in st.session_state:
        st.session_state["student_show_result_report"] = bool(st.session_state.get("student_last_payload"))


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
    st.session_state["student_show_result_report"] = False
    clear_student_uploaded_image()


def load_student_demo_data():
    """载入示例记录到向导状态。"""
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
                <div class="pcr-student-guide">
                    <div>
                        <div class="pcr-student-guide-title">按步骤填写实验信息</div>
                        <p class="pcr-student-guide-desc">
                            可随时返回前一步调整信息，确认后再生成诊断结果。
                        </p>
                    </div>
                    <span class="pcr-student-guide-chip">信息核对</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right_col:
            if st.button("载入示例记录", key="student_load_demo", use_container_width=True):
                load_student_demo_data()
                st.success("已载入示例记录，可按步骤继续填写。")
                st.rerun()


def render_student_topbar():
    """渲染页面内顶部导航。"""
    with st.container(key="pcr_student_topbar_row"):
        left_col, right_col = st.columns([0.78, 0.22])
        with left_col:
            st.markdown(
                """
                <div class="pcr-student-topbar">
                    <span class="pcr-student-page-label">实验诊断页面</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right_col:
            with st.container(key="pcr_student_return"):
                if st.button("返回首页", key="student_return_home", use_container_width=True):
                    return_to_home(clear_entries=False)


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


def render_student_readiness_panel():
    """渲染诊断准备度侧栏，帮助学生确认关键证据是否齐全。"""
    form_data = collect_student_form_payload()
    current_step = st.session_state.get("student_current_step", 1)
    has_description = bool(str(form_data["description"]).strip())
    has_image = bool(form_data["gel_image_file"])
    readiness_items = [
        ("实验现象", form_data["abnormality"] or "待填写", bool(form_data["abnormality"])),
        (
            "对照结果",
            f"阳性{form_data['positive_control_normal']} / 阴性{form_data['negative_control_band']}",
            bool(form_data["positive_control_normal"] and form_data["negative_control_band"]),
        ),
        (
            "PCR 参数",
            f"{form_data['template_amount']} μL / {form_data['annealing_temp']} ℃ / {form_data['cycles']} cycles",
            True,
        ),
        ("补充描述", "已填写" if has_description else "可选补充", has_description),
        ("凝胶图片", "已上传" if has_image else "未上传", has_image),
        ("诊断触发", "确认信息后生成" if current_step < 4 else "可以生成诊断", current_step >= 4),
    ]
    cards = [
        (
            '<div class="pcr-readiness-item">'
            f'<span class="pcr-readiness-dot {"done" if is_ready else ""}"></span>'
            "<div>"
            f'<div class="pcr-readiness-label">{html_text(label)}</div>'
            f'<div class="pcr-readiness-value">{html_text(value)}</div>'
            "</div>"
            "</div>"
        )
        for label, value, is_ready in readiness_items
    ]
    st.markdown(
        f"""
        <div class="pcr-readiness-panel">
            <div class="pcr-readiness-title">诊断准备度</div>
            <p class="pcr-readiness-desc">系统将根据已填写信息生成候选原因。</p>
            <div class="pcr-readiness-grid">{''.join(cards)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    payload = st.session_state.get("student_last_payload")
    if payload and payload.get("results"):
        top1 = payload["results"][0]
        st.markdown(
            f"""
            <div class="pcr-readiness-panel">
                <div class="pcr-readiness-title">最近一次诊断</div>
                <div class="pcr-readiness-item">
                    <span class="pcr-readiness-dot done"></span>
                    <div>
                        <div class="pcr-readiness-label">首要候选原因</div>
                        <div class="pcr-readiness-value">{html_text(top1.get('原因', '-'))}</div>
                    </div>
                </div>
                <div class="pcr-readiness-item" style="margin-top:0.5rem;">
                    <span class="pcr-readiness-dot {'done' if payload.get('text_clues') else ''}"></span>
                    <div>
                        <div class="pcr-readiness-label">文本线索</div>
                        <div class="pcr-readiness-value">{html_text('、'.join(payload.get('text_clues', [])) if payload.get('text_clues') else '未抽取')}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


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
                    <div class="pcr-step-desc">可随时返回前一步调整信息，确认后再生成诊断结果。</div>
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
    with st.container(border=True, key="pcr_student_form_card_step1"):
        render_card_title("记录实验现象与对照结果", "先记录凝胶中看到的主要异常，再确认阳性与阴性对照表现。")
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
    for key in (
        "student_form_template_amount",
        "student_form_cycles",
        "student_form_annealing_temp",
    ):
        restore_widget_value_from_storage(key)

    with st.container(border=True, key="pcr_student_form_card_step2"):
        render_card_title("填写 PCR 关键参数", "补充模板量、退火温度和循环数，帮助系统判断参数是否可能影响结果。")
        col_left, col_right = st.columns(2)
        with col_left:
            st.number_input("模板量 (μL)", min_value=0.0, step=0.5, key="student_form_template_amount", on_change=sync_val, args=("student_form_template_amount",))
            st.number_input("循环数", min_value=1, step=1, key="student_form_cycles", on_change=sync_val, args=("student_form_cycles",))
        with col_right:
            st.number_input("退火温度 (℃)", min_value=0.0, step=0.5, key="student_form_annealing_temp", on_change=sync_val, args=("student_form_annealing_temp",))
            st.caption("当前项目已支持的关键参数主要包括模板量、退火温度和循环数。")


def render_step_3_text_and_image():
    """第 3 步：补充描述与图片上传"""
    with st.container(border=True, key="pcr_student_form_card_step3"):
        render_card_title("补充实验描述与凝胶图片", "可描述操作过程中的特殊情况，也可以上传凝胶图片作为教师复核依据。")
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
                st.markdown(
                    """
                    <div class="pcr-gel-placeholder">
                        <b>凝胶图可选上传</b>
                        <span>上传后会随案例保存，教师端可用于复核；未上传也可继续诊断。</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_step_4_review():
    """第 4 步：确认并诊断"""
    form_data = collect_student_form_payload()
    with st.container(border=True, key="pcr_student_form_card_step4"):
        render_card_title("确认信息并生成诊断", "请核对前面填写的信息，确认后系统将生成候选原因、诊断依据和处理建议。")
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
        st.caption("如需修改，可返回前面步骤继续调整；确认后再生成诊断结果。")


def render_student_step_navigation():
    """渲染步骤切换按钮"""
    current_step = st.session_state["student_current_step"]
    total_steps = len(STUDENT_STEP_TITLES)
    st.markdown('<div class="pcr-student-actions">', unsafe_allow_html=True)
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
            if st.button("生成诊断结果", key="student_run_diagnosis", type="primary", use_container_width=True):
                run_student_diagnosis()
                st.session_state["student_show_result_report"] = True
                st.success("诊断已完成，本次记录已保存，可在教师端继续复核。")
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def get_result_report_parts(payload):
    """整理结果报告展示所需的安全数据，不改变诊断结果本身。"""
    results = payload.get("results", []) or []
    top1 = results[0] if results else {}
    detail = top1.get("诊断依据", {}) or {}
    context = build_diagnosis_context(
        abnormality=payload.get("abnormality", ""),
        positive_control_normal=payload.get("positive_control_normal", ""),
        negative_control_band=payload.get("negative_control_band", ""),
        template_amount=payload.get("template_amount"),
        annealing_temp=payload.get("annealing_temp"),
        cycles=payload.get("cycles"),
        description=payload.get("description", ""),
        text_clues=payload.get("text_clues", []),
        gel_image_path=payload.get("gel_image_path", ""),
        has_image=bool(payload.get("gel_image_path")),
    )
    confidence_level, confidence_reason = compute_confidence_level(results, detail=detail, context=context)
    evidence_points = build_evidence_summary(top1.get("原因", ""), detail=detail, context=context)
    missing_items = detect_missing_key_info(context)
    return results, top1, confidence_level, confidence_reason, evidence_points, missing_items


def render_result_overview(payload, results, top1, confidence_level):
    """渲染诊断结果总览。"""
    record_status = "已保存" if payload.get("record_id") else "未保存"
    candidate_count = " / ".join(f"Top{index}" for index in range(1, len(results) + 1)) if results else "暂无"
    st.markdown(
        f"""
        <div class="pcr-result-overview">
            <div>
                <div class="pcr-result-kicker">诊断结果总览</div>
                <h2 class="pcr-result-title">{html_text(top1.get("原因", "暂无诊断结果"))}</h2>
                <p class="pcr-result-desc">
                    系统判断仅作为实验复盘参考，最终原因可由教师结合原始图像与操作记录确认。
                </p>
            </div>
            <div class="pcr-result-stat-grid">
                <div class="pcr-result-stat"><span>主要判断</span><b>{html_text(top1.get("原因", "-"))}</b></div>
                <div class="pcr-result-stat"><span>置信度</span><b><span class="pcr-confidence-pill">{html_text(confidence_level)}</span></b></div>
                <div class="pcr-result-stat"><span>候选原因</span><b>{html_text(candidate_count)}</b></div>
                <div class="pcr-result-stat"><span>记录状态</span><b>{html_text(record_status)}</b></div>
                <div class="pcr-result-stat"><span>诊断时间</span><b>{html_text(payload.get("submit_time", "-"))}</b></div>
                <div class="pcr-result-stat"><span>文本线索</span><b>{html_text("、".join(payload.get("text_clues", [])) if payload.get("text_clues") else "未抽取")}</b></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_primary_result(top1, confidence_level, confidence_reason, evidence_points):
    """渲染 Top1 主要判断。"""
    evidence_html = "".join(f"<li>{html_text(point)}</li>" for point in (evidence_points or ["当前可提炼的证据较少，系统主要基于已有规则分值进行排序。"])[:5])
    st.markdown(
        f"""
        <div class="pcr-result-primary">
            <h3 class="pcr-result-section-title">主要判断</h3>
            <div class="pcr-result-primary-grid">
                <div class="pcr-result-card">
                    <div class="pcr-result-label">系统优先判断为</div>
                    <div class="pcr-primary-reason">{html_text(top1.get("原因", "-"))}</div>
                    <span class="pcr-confidence-pill">置信度 {html_text(confidence_level)}</span>
                    <span class="pcr-score-chip">总分 {html_text(top1.get("总分", "-"))}</span>
                    <p>{html_text(confidence_reason)}</p>
                </div>
                <div class="pcr-result-card">
                    <div class="pcr-result-label">建议措施</div>
                    <p>{html_text(top1.get("建议", "建议结合原始实验记录和凝胶图片继续复核。"))}</p>
                </div>
            </div>
            <ul class="pcr-evidence-list">{evidence_html}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_candidate_results(results):
    """渲染 Top2 / Top3 次级候选原因。"""
    secondary = (results or [])[1:3]
    if not secondary:
        return

    cards = []
    for index, result_item in enumerate(secondary, 2):
        suggestion = result_item.get("建议") or "可结合诊断依据进一步复核。"
        cards.append(
            '<div class="pcr-candidate-card">'
            f'<div class="pcr-candidate-rank">Top{index} 候选原因</div>'
            f'<h4>{html_text(result_item.get("原因", "-"))}</h4>'
            f'<p>总分 {html_text(result_item.get("总分", "-"))}</p>'
            f'<p>{html_text(suggestion)}</p>'
            "</div>"
        )

    st.markdown(
        f"""
        <div class="pcr-result-candidates">
            <h3 class="pcr-result-section-title">其他候选原因</h3>
            <div class="pcr-candidate-grid">{''.join(cards)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for index, result_item in enumerate(secondary, 2):
        with st.expander(f"查看 Top{index} 候选原因详情"):
            render_scoring_detail(result_item.get("诊断依据", {}), result_item.get("总分", "-"))


def render_result_evidence(missing_items):
    """渲染系统依据与补充建议。"""
    if missing_items:
        missing_html = "".join(f"<li>{html_text(item)}</li>" for item in missing_items)
    else:
        missing_html = "<li>当前关键信息较完整，可结合教师复核继续确认。</li>"

    st.markdown(
        f"""
        <div class="pcr-result-evidence">
            <h3 class="pcr-result-section-title">系统依据与补充建议</h3>
            <p>系统根据异常现象、对照结果、PCR 参数和补充描述生成候选原因。</p>
            <p>为了提高判断稳定性，可继续补充或核对以下信息：</p>
            <ul>{missing_html}</ul>
            <p class="pcr-result-note">教师复核时建议结合凝胶原图、上样量、模板浓度测定结果和实际操作记录综合判断。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_input_summary(payload):
    """渲染本次输入摘要。"""
    image_text = "已上传" if payload.get("gel_image_path") else "未上传"
    summary_items = [
        ("实验现象", payload.get("abnormality", "-")),
        ("阳性对照", payload.get("positive_control_normal", "-")),
        ("阴性对照", payload.get("negative_control_band", "-")),
        ("模板量", f"{payload.get('template_amount', '-')} μL"),
        ("退火温度", f"{payload.get('annealing_temp', '-')} ℃"),
        ("循环数", payload.get("cycles", "-")),
        ("补充描述", payload.get("description") or "未填写"),
        ("凝胶图片", image_text),
    ]
    items_html = "".join(
        '<div class="pcr-input-summary-item">'
        f'<span class="pcr-input-summary-label">{html_text(label)}</span>'
        f'<b class="pcr-input-summary-value">{html_text(value)}</b>'
        "</div>"
        for label, value in summary_items
    )
    st.markdown(
        f"""
        <div class="pcr-input-summary">
            <h3 class="pcr-result-section-title">本次输入摘要</h3>
            <div class="pcr-input-summary-grid">{items_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def return_to_student_editing():
    """从结果报告回到第 4 步，保留已填写数据。"""
    st.session_state["student_show_result_report"] = False
    st.session_state["student_current_step"] = 4
    st.rerun()


def render_student_results(payload):
    """渲染报告化诊断结果区域。"""
    results = payload.get("results", [])
    record_id = payload.get("record_id")
    gel_image_path = payload.get("gel_image_path")
    image_save_error = payload.get("image_save_error")

    st.markdown('<div class="pcr-student-result-page">', unsafe_allow_html=True)

    if image_save_error:
        st.warning(f"图片保存失败，但不影响诊断：{image_save_error}")
    if not results:
        st.warning("该异常类型暂无规则。")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    results, top1, confidence_level, confidence_reason, evidence_points, missing_items = get_result_report_parts(payload)
    render_result_overview(payload, results, top1, confidence_level)
    render_primary_result(top1, confidence_level, confidence_reason, evidence_points)
    render_candidate_results(results)
    render_result_evidence(missing_items)

    with st.expander("查看本次输入摘要", expanded=False):
        render_input_summary(payload)
        if gel_image_path and os.path.exists(gel_image_path):
            st.image(gel_image_path, caption=f"已上传：{gel_image_path}", use_container_width=True)

    st.markdown(
        """
        <div class="pcr-result-actions">
            <h3>诊断记录操作</h3>
            <p class="pcr-result-desc">本次诊断已生成记录，可返回修改输入，也可下载本次记录用于课后复盘。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_cols = st.columns([1, 1])
    with action_cols[0]:
        if st.button("返回修改", key="student_return_to_editing", use_container_width=True):
            return_to_student_editing()

    if record_id:
        download_name = f"pcr_review_report_case_{record_id}.txt"
    else:
        download_name = f"pcr_review_report_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    with action_cols[1]:
        st.download_button(
            "下载本次记录（TXT）",
            data=build_case_summary(payload),
            file_name=download_name,
            mime="text/plain",
            type="primary",
            use_container_width=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

def main():
    """学生端主流程。"""
    ensure_page_config("实验异常记录与诊断输入")
    init_database()
    apply_common_styles(theme="student")
    render_student_refined_styles()
    st.session_state["current_role"] = "student"
    init_student_wizard_state()

    render_student_topbar()

    render_page_hero(
        "实验异常记录与诊断输入",
        "按步骤记录实验观察、对照结果和 PCR 条件，系统将生成可解释的诊断建议。",
        "实验记录流程",
    )

    payload = st.session_state.get("student_last_payload")
    show_result_report = bool(payload and st.session_state.get("student_show_result_report", True))

    if show_result_report:
        render_student_results(payload)
        return

    render_student_quick_actions()
    render_student_wizard_header()

    with st.container(key="pcr_student_workspace"):
        main_col, side_col = st.columns([0.7, 0.3])
        with main_col:
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

        with side_col:
            render_student_readiness_panel()


if __name__ == "__main__":
    main()
