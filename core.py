# -*- coding: utf-8 -*-
"""
PCR电泳异常诊断Demo - Streamlit应用
功能：根据实验现象和参数，诊断PCR电泳异常原因
"""

import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import pandas as pd
import sqlite3
import os
import re
import json
import uuid
from datetime import datetime
from diagnosis_normalization import build_normalized_case, explain_normalized_case
from diagnosis_rule_engine_v2 import evaluate_rules_v2
from navigation_state import get_home_page

try:
    # 使用兼容 OpenAI SDK 的方式调用 BigModel / GLM
    from openai import OpenAI
except:
    OpenAI = None

# 数据库路径
DB_PATH = "data/app.db"

# 规则文件路径
RULES_PATH = "rules.csv"
LEGACY_RULES_PATH = "rules_v2.csv"
# 上传图片保存目录
UPLOAD_DIR = "uploads"
# 页面里使用的实验现象选项（也用于规则校验）
ABNORMALITY_OPTIONS = [
    "无条带",
    "条带弱",
    "多条带或非特异扩增",
    "条带大小不对",
    "条带拖尾或弥散",
    "阴性对照有带",
    "阳性对照无带",
    "条带畸形",
]
# 规则库必要字段（匹配新版 rules.csv 规则矩阵结构）
REQUIRED_RULE_COLUMNS = [
    "rule_id", "abnormality", "band_pattern", "cause", "priority",
    "positive_control", "negative_control", "template_condition",
    "annealing_temp_condition", "text_hint", "required_fields",
    "base_score", "evidence_text", "suggestion", "enabled"
]

# BigModel API 配置（后续如果要切换地址，只改这里）
BIGMODEL_DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
BIGMODEL_MODEL = "glm-5"
BIGMODEL_TIMEOUT_SECONDS = 20
BIGMODEL_TEMPERATURE = 1.0

# 文本线索标签（统一用这 5 类）
ALLOWED_TEXT_CLUES = ["污染", "模板量不足", "引物问题", "PCR体系问题", "退火温度问题"]
CSV_FALLBACK_ENCODINGS = ["utf-8", "utf-8-sig", "gb18030", "gbk", "cp936"]


def read_csv_with_fallback(file_path, **kwargs):
    """按常见编码顺序读取 CSV，优先 UTF-8，失败后回退中文编码。"""
    last_error = None
    for encoding in CSV_FALLBACK_ENCODINGS:
        try:
            return pd.read_csv(file_path, encoding=encoding, **kwargs)
        except UnicodeDecodeError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    return pd.read_csv(file_path, **kwargs)


def ensure_page_config(page_title, page_icon="🧪"):
    """统一页面宽屏配置；重复调用时自动忽略。"""
    try:
        st.set_page_config(
            page_title=page_title,
            page_icon=page_icon,
            layout="wide",
            initial_sidebar_state="collapsed",
        )
    except Exception:
        pass


def init_access_state():
    """初始化首页入口与动态导航所需的会话状态。"""
    defaults = {
        "current_role": "home",
        "teacher_entered": False,
        "dev_entered": False,
        "teacher_verified": False,
        "dev_verified": False,
        "show_teacher_access_panel": False,
        "show_dev_access_panel": False,
        "active_access_dialog": None,
        "navigation_target": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def request_navigation(target):
    """记录下一次需要切换到的目标页面。"""
    st.session_state["navigation_target"] = target


def enter_student_role():
    st.session_state["current_role"] = "student"
    request_navigation("student")


def enter_teacher_role():
    st.session_state["teacher_entered"] = True
    st.session_state["teacher_verified"] = True
    st.session_state["show_teacher_access_panel"] = False
    st.session_state["current_role"] = "teacher"
    request_navigation("teacher")


def enter_dev_role():
    st.session_state["dev_entered"] = True
    st.session_state["dev_verified"] = True
    st.session_state["show_dev_access_panel"] = False
    st.session_state["current_role"] = "dev"
    request_navigation("dev")


def go_home(clear_entries=False):
    """返回首页；可选清空教师端/开发端入口状态。"""
    st.session_state["current_role"] = "home"
    st.session_state["active_access_dialog"] = None
    if clear_entries:
        st.session_state["teacher_entered"] = False
        st.session_state["dev_entered"] = False
        st.session_state["teacher_verified"] = False
        st.session_state["dev_verified"] = False
        st.session_state["show_teacher_access_panel"] = False
        st.session_state["show_dev_access_panel"] = False
    request_navigation("home")


def return_to_home(clear_entries=False):
    """返回首页视图：更新状态后真正切换到首页页对象。"""
    go_home(clear_entries=clear_entries)
    switch_to_home_page()


def switch_to_home_page():
    """真正切换到首页；若首页页对象尚未注册则安全回退为 rerun。"""
    home_page = get_home_page()
    if home_page is not None:
        st.switch_page(home_page)
        return
    st.rerun()


def get_current_role_label():
    role_map = {
        "home": "首页",
        "student": "学生",
        "teacher": "教师",
        "dev": "开发调试",
    }
    return role_map.get(st.session_state.get("current_role", "home"), "首页")


def get_config_value(name):
    """优先从 `.streamlit/secrets.toml` 读取，失败时回退到环境变量。"""
    try:
        secret_value = st.secrets[name]
        normalized_secret = str(secret_value).strip()
        if normalized_secret:
            return normalized_secret
    except Exception:
        pass

    env_value = os.getenv(name, "")
    normalized_env = str(env_value or "").strip()
    return normalized_env or None


def get_teacher_access_code():
    return get_config_value("TEACHER_ACCESS_CODE")


def get_dev_access_code():
    return get_config_value("DEV_ACCESS_CODE")


def verify_access_code(input_code, expected_code):
    """轻量访问码校验；未配置时不放行。"""
    normalized_expected = str(expected_code or "").strip()
    normalized_input = str(input_code or "").strip()
    if not normalized_expected:
        return False
    return normalized_input == normalized_expected


def logout_teacher_access():
    st.session_state["teacher_verified"] = False
    st.session_state["teacher_entered"] = False
    st.session_state["show_teacher_access_panel"] = False
    st.session_state["active_access_dialog"] = None
    if st.session_state.get("current_role") == "teacher":
        st.session_state["current_role"] = "home"
    request_navigation("home")


def logout_dev_access():
    st.session_state["dev_verified"] = False
    st.session_state["dev_entered"] = False
    st.session_state["show_dev_access_panel"] = False
    st.session_state["active_access_dialog"] = None
    if st.session_state.get("current_role") == "dev":
        st.session_state["current_role"] = "home"
    request_navigation("home")


def render_entry_guard(page_name):
    """教师端/开发调试端的轻量访问拦截提示。"""
    with st.container(border=True):
        render_card_title("页面访问受限", f"当前会话尚未获得“{page_name}”入口。")
        st.warning(f"请先从首页的“{page_name}入口”完成访问码验证，再进入本页面。")
        col_home, col_reset = st.columns(2)
        with col_home:
            if st.button("返回首页", key=f"guard_home_{page_name}", use_container_width=True):
                return_to_home(clear_entries=False)
        with col_reset:
            if st.button("返回首页并重置入口状态", key=f"guard_reset_{page_name}", use_container_width=True):
                return_to_home(clear_entries=True)


def apply_common_styles(theme="student"):
    """
    注入全局样式（只做视觉优化，不改业务逻辑）
    theme: student / teacher / dev
    """
    # 三个角色页的主色区分：学生蓝、教师青、开发灰黑
    palette_map = {
        "home": {
            "primary": "#0b1f3a",
            "primary_2": "#123a63",
            "accent": "#0ea5b7",
            "bg": "#eef7fb",
        },
        "student": {
            "primary": "#0b1f3a",
            "primary_2": "#1d4ed8",
            "accent": "#0ea5b7",
            "bg": "#eef7fb",
        },
        "teacher": {
            "primary": "#0b1f3a",
            "primary_2": "#0f766e",
            "accent": "#0ea5b7",
            "bg": "#edf8f7",
        },
        "dev": {
            "primary": "#0b1f3a",
            "primary_2": "#334155",
            "accent": "#0ea5b7",
            "bg": "#f2f6f8",
        },
    }
    palette = palette_map.get(theme, palette_map["student"])

    st.markdown(
        f"""
        <style>
        :root {{
            --pcr-primary: {palette["primary"]};
            --pcr-primary-2: {palette["primary_2"]};
            --pcr-accent: {palette["accent"]};
            --pcr-bg: {palette["bg"]};
            --pcr-card: #ffffff;
            --pcr-text: #0f172a;
            --pcr-muted: #475569;
            --pcr-success: #16a34a;
            --pcr-warning: #ea580c;
            --pcr-danger: #dc2626;
            --pcr-border: #dbe3f0;
        }}

        .stApp {{
            background: linear-gradient(180deg, var(--pcr-bg) 0%, #f8fbff 100%);
        }}

        .main .block-container {{
            padding-top: 1rem;
            padding-bottom: 2.9rem;
            padding-left: clamp(1rem, 2.2vw, 2.4rem);
            padding-right: clamp(1rem, 2.2vw, 2.4rem);
            max-width: 1520px;
        }}

        @media (min-width: 1400px) {{
            .main .block-container {{
                max-width: min(1540px, 96vw);
            }}
        }}

        @media (max-width: 768px) {{
            .main .block-container {{
                padding-left: 0.85rem;
                padding-right: 0.85rem;
                padding-top: 0.7rem;
            }}
        }}

        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, rgba(255,255,255,0.94) 0%, rgba(241,245,255,0.96) 100%);
            border-right: 1px solid rgba(148, 163, 184, 0.18);
        }}

        section[data-testid="stSidebar"] > div {{
            padding-top: 0.75rem;
        }}

        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {{
            border-radius: 12px;
            margin-bottom: 0.28rem;
            padding: 0.56rem 0.72rem;
            border: 1px solid transparent;
            transition: all 0.18s ease;
        }}

        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {{
            background: rgba(255, 255, 255, 0.85);
            border-color: rgba(148, 163, 184, 0.2);
        }}

        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {{
            background: rgba(255, 255, 255, 0.98);
            border-color: rgba(59, 130, 246, 0.22);
            box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
        }}

        .pcr-hero {{
            background: linear-gradient(135deg, var(--pcr-primary) 0%, var(--pcr-primary-2) 100%);
            color: #ffffff;
            border-radius: 24px;
            padding: 1.55rem 1.65rem;
            margin-bottom: 1.15rem;
            box-shadow: 0 18px 44px rgba(15, 23, 42, 0.16);
            position: relative;
            overflow: hidden;
        }}

        .pcr-hero::after {{
            content: "";
            position: absolute;
            right: -80px;
            bottom: -180px;
            width: 340px;
            height: 340px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.12);
        }}

        .pcr-hero h1 {{
            margin: 0.45rem 0 0.45rem 0;
            font-size: clamp(1.85rem, 2.4vw, 2.5rem);
            font-weight: 700;
            letter-spacing: 0.1px;
            position: relative;
            z-index: 1;
        }}

        .pcr-hero p {{
            margin: 0;
            opacity: 0.96;
            font-size: 1.02rem;
            line-height: 1.65;
            max-width: 72ch;
            position: relative;
            z-index: 1;
        }}

        .pcr-role-badge {{
            display: inline-block;
            background: rgba(255, 255, 255, 0.16);
            border: 1px solid rgba(255, 255, 255, 0.35);
            color: #ffffff;
            border-radius: 999px;
            padding: 0.28rem 0.82rem;
            font-size: 0.79rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            position: relative;
            z-index: 1;
        }}

        .pcr-card-title {{
            color: var(--pcr-text);
            font-size: 1.16rem;
            font-weight: 700;
            margin: 0.05rem 0 0.34rem 0;
            line-height: 1.35;
        }}

        .pcr-muted {{
            color: var(--pcr-muted);
            font-size: 0.95rem;
            line-height: 1.6;
            margin-bottom: 0.2rem;
        }}

        /* 统一卡片边框、阴影、圆角，适配 st.container(border=True) */
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            border-color: var(--pcr-border) !important;
            border-radius: 18px !important;
            background: var(--pcr-card);
            box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
            overflow: hidden;
        }}

        div[data-testid="stVerticalBlockBorderWrapper"] > div {{
            padding: 0.14rem 0.18rem;
        }}

        .pcr-top1-card {{
            border: 1px solid #bfd4ff;
            background: linear-gradient(180deg, #f4f8ff 0%, #eef5ff 100%);
            border-radius: 16px;
            padding: 0.95rem 1rem;
            margin-bottom: 0.7rem;
        }}

        .pcr-sub-card {{
            border: 1px solid var(--pcr-border);
            background: #ffffff;
            border-radius: 14px;
            padding: 0.82rem 0.95rem;
            margin-bottom: 0.65rem;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.045);
        }}

        .pcr-status-pill {{
            display: inline-block;
            border-radius: 999px;
            padding: 0.18rem 0.65rem;
            font-size: 0.77rem;
            font-weight: 700;
            margin-left: 0.45rem;
        }}

        .pcr-status-ok {{
            background: #dcfce7;
            color: #166534;
            border: 1px solid #86efac;
        }}

        .pcr-status-pending {{
            background: #ffedd5;
            color: #9a3412;
            border: 1px solid #fdba74;
        }}

        /* 按钮风格统一 */
        .pcr-tile {{
            height: 100%;
            border: 1px solid var(--pcr-border);
            background: linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(247,250,255,0.96) 100%);
            border-radius: 18px;
            padding: 1rem 1rem 0.95rem 1rem;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
        }}

        .pcr-tile-tag {{
            display: inline-block;
            margin-bottom: 0.55rem;
            padding: 0.18rem 0.62rem;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.1);
            color: var(--pcr-primary);
            font-size: 0.76rem;
            font-weight: 700;
        }}

        .pcr-tile h3 {{
            margin: 0 0 0.4rem 0;
            font-size: 1.04rem;
            color: var(--pcr-text);
        }}

        .pcr-tile p {{
            margin: 0;
            color: var(--pcr-muted);
            font-size: 0.94rem;
            line-height: 1.65;
        }}

        .pcr-soft-note {{
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-left: 4px solid var(--pcr-primary);
            background: rgba(255, 255, 255, 0.84);
            border-radius: 16px;
            padding: 0.95rem 1rem;
        }}

        .pcr-soft-note-title {{
            margin: 0 0 0.28rem 0;
            font-size: 0.92rem;
            font-weight: 700;
            color: var(--pcr-text);
        }}

        .pcr-soft-note p {{
            margin: 0;
            color: var(--pcr-muted);
            line-height: 1.68;
            font-size: 0.94rem;
        }}

        .pcr-dev-panel {{
            border: 1px solid var(--pcr-border);
            border-radius: 18px;
            background: #ffffff;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
            padding: 1rem 1rem 0.9rem 1rem;
            min-height: 23rem;
            margin-bottom: 1rem;
        }}

        .pcr-dev-panel.compact {{
            min-height: 17rem;
        }}

        .pcr-dev-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.8rem;
            margin-top: 0.8rem;
        }}

        .pcr-dev-check-card {{
            border: 1px solid var(--pcr-border);
            border-radius: 14px;
            padding: 0.9rem 0.95rem;
            background: #ffffff;
            min-height: 7.5rem;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.04);
        }}

        .pcr-dev-check-card b {{
            display: block;
            margin-bottom: 0.35rem;
            font-size: 0.96rem;
            color: var(--pcr-text);
        }}

        .pcr-dev-check-card p {{
            margin: 0;
            color: var(--pcr-muted);
            font-size: 0.9rem;
            line-height: 1.6;
        }}

        .pcr-dev-check-card.success {{ border-left: 4px solid #16a34a; background: #f0fdf4; }}
        .pcr-dev-check-card.warning {{ border-left: 4px solid #d97706; background: #fffbeb; }}
        .pcr-dev-check-card.error {{ border-left: 4px solid #dc2626; background: #fef2f2; }}

        .pcr-status-card {{
            border: 1px solid var(--pcr-border);
            border-radius: 16px;
            padding: 0.85rem 0.95rem;
            background: #ffffff;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.05);
            margin-bottom: 0.7rem;
        }}

        .pcr-status-card b {{
            display: block;
            margin-bottom: 0.28rem;
            font-size: 0.95rem;
            color: var(--pcr-text);
        }}

        .pcr-status-card p {{
            margin: 0;
            font-size: 0.88rem;
            line-height: 1.58;
            color: var(--pcr-muted);
        }}

        .pcr-status-success {{ border-left: 4px solid #16a34a; }}
        .pcr-status-warning {{ border-left: 4px solid #ea580c; }}
        .pcr-status-error {{ border-left: 4px solid #dc2626; }}
        .pcr-status-neutral {{ border-left: 4px solid #64748b; }}

        .pcr-step-header {{
            border: 1px solid var(--pcr-border);
            border-radius: 18px;
            background: linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(247,249,255,0.95) 100%);
            padding: 1rem 1rem 0.8rem 1rem;
            margin-bottom: 1rem;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
        }}

        .pcr-step-kicker {{
            color: var(--pcr-primary);
            font-weight: 700;
            font-size: 0.84rem;
            margin-bottom: 0.18rem;
        }}

        .pcr-step-title {{
            color: var(--pcr-text);
            font-weight: 700;
            font-size: 1.16rem;
            margin-bottom: 0.3rem;
        }}

        .pcr-step-desc {{
            color: var(--pcr-muted);
            font-size: 0.93rem;
            line-height: 1.6;
        }}

        .pcr-student-toolbar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            border: 1px solid var(--pcr-border);
            border-radius: 18px;
            background: rgba(255, 255, 255, 0.92);
            padding: 0.95rem 1rem;
            margin-bottom: 1rem;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
        }}

        .pcr-student-toolbar-title {{
            margin: 0 0 0.18rem 0;
            color: var(--pcr-text);
            font-weight: 700;
            font-size: 1rem;
            line-height: 1.35;
        }}

        .pcr-student-toolbar-desc {{
            margin: 0;
            color: var(--pcr-muted);
            font-size: 0.9rem;
            line-height: 1.55;
        }}

        .pcr-stepper-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 0.85rem 0 0.85rem 0;
        }}

        .pcr-stepper-item {{
            border: 1px solid var(--pcr-border);
            border-radius: 14px;
            background: #ffffff;
            padding: 0.78rem 0.85rem;
            min-height: 5.25rem;
        }}

        .pcr-stepper-item.active {{
            border-color: rgba(29, 78, 216, 0.42);
            background: linear-gradient(180deg, #eff6ff 0%, #ffffff 100%);
            box-shadow: 0 10px 24px rgba(29, 78, 216, 0.1);
        }}

        .pcr-stepper-item.done {{
            border-color: rgba(22, 163, 74, 0.28);
            background: #f0fdf4;
        }}

        .pcr-stepper-index {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1.55rem;
            height: 1.55rem;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.1);
            color: var(--pcr-primary);
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 0.46rem;
        }}

        .pcr-stepper-item.done .pcr-stepper-index {{
            background: #dcfce7;
            color: #166534;
        }}

        .pcr-stepper-item.active .pcr-stepper-index {{
            background: var(--pcr-primary);
            color: #ffffff;
        }}

        .pcr-stepper-title {{
            color: var(--pcr-text);
            font-weight: 700;
            font-size: 0.92rem;
            line-height: 1.35;
            margin-bottom: 0.25rem;
        }}

        .pcr-stepper-status {{
            color: var(--pcr-muted);
            font-size: 0.78rem;
            line-height: 1.45;
        }}

        .pcr-current-step-summary {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.25rem;
        }}

        .pcr-current-step-chip {{
            flex: 0 0 auto;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.1);
            color: var(--pcr-primary);
            border: 1px solid rgba(59, 130, 246, 0.2);
            padding: 0.2rem 0.7rem;
            font-size: 0.78rem;
            font-weight: 800;
        }}

        .pcr-review-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 0.75rem 0;
        }}

        .pcr-review-item {{
            border: 1px solid var(--pcr-border);
            border-radius: 14px;
            background: #ffffff;
            padding: 0.75rem 0.85rem;
        }}

        .pcr-review-label {{
            color: var(--pcr-muted);
            font-size: 0.78rem;
            font-weight: 700;
            margin-bottom: 0.24rem;
        }}

        .pcr-review-value {{
            color: var(--pcr-text);
            font-size: 0.98rem;
            font-weight: 700;
            line-height: 1.45;
            overflow-wrap: anywhere;
        }}

        .pcr-result-meta-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 0.65rem 0 0.85rem 0;
        }}

        @media (max-width: 900px) {{
            .pcr-student-toolbar,
            .pcr-current-step-summary {{
                display: block;
            }}

            .pcr-stepper-grid,
            .pcr-review-grid,
            .pcr-result-meta-grid {{
                grid-template-columns: 1fr;
            }}

            .pcr-current-step-chip {{
                display: inline-flex;
                margin-top: 0.55rem;
            }}
        }}

        [data-testid="stMetric"] {{
            background: linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(247,249,255,0.94) 100%);
            border: 1px solid var(--pcr-border);
            border-radius: 16px;
            padding: 0.9rem 1rem;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
        }}

        [data-testid="stMetricLabel"] {{
            font-size: 0.88rem;
            font-weight: 700;
        }}

        [data-testid="stMetricValue"] {{
            font-size: clamp(1.5rem, 2.1vw, 2.1rem);
        }}

        div[data-testid="stDataFrame"] {{
            border: 1px solid var(--pcr-border);
            border-radius: 16px;
            overflow: hidden;
            background: #ffffff;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
        }}

        [data-testid="stExpander"] {{
            border: 1px solid var(--pcr-border);
            border-radius: 16px;
            overflow: hidden;
            background: #ffffff;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.04);
            margin-bottom: 0.7rem;
        }}

        [data-testid="stExpander"] details summary {{
            background: rgba(248, 250, 252, 0.9);
        }}

        .stAlert {{
            border-radius: 14px;
        }}

        div.stButton > button, div.stDownloadButton > button, div[data-testid="stFormSubmitButton"] button {{
            border-radius: 12px;
            font-weight: 700;
            border: 1px solid #c9d6ef;
            min-height: 2.8rem;
            padding-left: 0.95rem;
            padding-right: 0.95rem;
            box-shadow: 0 6px 16px rgba(15, 23, 42, 0.05);
        }}

        button[kind="primary"] {{
            background: linear-gradient(135deg, var(--pcr-primary) 0%, var(--pcr-primary-2) 100%) !important;
            color: #ffffff !important;
            border: none !important;
        }}

        .stMarkdown p, .stMarkdown li {{
            line-height: 1.68;
        }}

        .stMarkdown ul {{
            margin-top: 0.25rem;
            margin-bottom: 0.4rem;
        }}

        [data-testid="stHorizontalBlock"] {{
            gap: 1rem;
        }}

        .stProgress > div > div > div > div {{
            background: linear-gradient(90deg, var(--pcr-primary) 0%, var(--pcr-accent) 100%);
        }}

        .stProgress > div > div {{
            height: 0.48rem;
            border-radius: 999px;
        }}

        div.stButton > button, div.stDownloadButton > button {{
            border-radius: 10px;
            font-weight: 600;
            border: 1px solid #c9d6ef;
        }}

        /* Competition polish layer: unified lab brand system */
        :root {{
            --pcr-ink: #07172b;
            --pcr-lab-blue: #0b1f3a;
            --pcr-diagnostic-blue: #2563eb;
            --pcr-gel-cyan: #0ea5b7;
            --pcr-cyan-soft: #dff8fb;
            --pcr-amber: #f59e0b;
            --pcr-surface: rgba(255, 255, 255, 0.88);
            --pcr-surface-strong: #ffffff;
            --pcr-shadow-sm: 0 8px 20px rgba(11, 31, 58, 0.07);
            --pcr-shadow-md: 0 18px 44px rgba(11, 31, 58, 0.12);
            --pcr-shadow-lg: 0 26px 70px rgba(11, 31, 58, 0.16);
        }}

        .stApp {{
            background:
                linear-gradient(rgba(14, 165, 183, 0.035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(14, 165, 183, 0.03) 1px, transparent 1px),
                radial-gradient(circle at 18% 8%, rgba(14, 165, 183, 0.16), transparent 28%),
                radial-gradient(circle at 92% 2%, rgba(37, 99, 235, 0.12), transparent 26%),
                linear-gradient(180deg, var(--pcr-bg) 0%, #f8fbfd 48%, #ffffff 100%);
            background-size: 34px 34px, 34px 34px, auto, auto, auto;
            color: var(--pcr-ink);
        }}

        .main .block-container {{
            padding-top: clamp(0.75rem, 1.7vw, 1.4rem);
            max-width: min(1480px, 95vw);
        }}

        section[data-testid="stSidebar"] {{
            background:
                linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(240, 249, 251, 0.98) 100%);
            border-right: 1px solid rgba(11, 31, 58, 0.08);
            box-shadow: 12px 0 34px rgba(11, 31, 58, 0.045);
        }}

        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {{
            border-radius: 14px;
            min-height: 2.95rem;
            font-weight: 750;
            letter-spacing: 0;
        }}

        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {{
            background: linear-gradient(90deg, rgba(14, 165, 183, 0.13), rgba(37, 99, 235, 0.08));
            border-color: rgba(14, 165, 183, 0.28);
            box-shadow: inset 4px 0 0 var(--pcr-gel-cyan), 0 12px 24px rgba(11, 31, 58, 0.08);
        }}

        [data-testid="collapsedControl"] {{
            position: relative;
        }}

        [data-testid="collapsedControl"]::after {{
            content: "点此展开侧边栏";
            position: absolute;
            left: 2.15rem;
            top: 50%;
            transform: translateY(-50%);
            white-space: nowrap;
            pointer-events: none;
            border: 1px solid rgba(14, 165, 183, 0.2);
            border-radius: 999px;
            padding: 0.18rem 0.56rem;
            background: rgba(255, 255, 255, 0.82);
            color: #075985;
            font-size: 0.76rem;
            font-weight: 750;
            box-shadow: 0 6px 16px rgba(11, 31, 58, 0.06);
        }}

        .pcr-sidebar-expand-hint {{
            position: fixed;
            top: 0.72rem;
            left: 2.45rem;
            z-index: 999999;
            display: none;
            pointer-events: none;
            border: 1px solid rgba(14, 165, 183, 0.22);
            border-radius: 999px;
            padding: 0.18rem 0.62rem;
            background: rgba(255, 255, 255, 0.9);
            color: #075985;
            font-size: 0.76rem;
            font-weight: 800;
            line-height: 1.2;
            box-shadow: 0 8px 18px rgba(11, 31, 58, 0.07);
            backdrop-filter: blur(8px);
        }}

        body:has([data-testid="collapsedControl"]) .pcr-sidebar-expand-hint {{
            display: block;
        }}

        @media (max-width: 640px) {{
            .pcr-sidebar-expand-hint {{
                display: none;
            }}
        }}

        .pcr-hero {{
            border-radius: 22px;
            padding: clamp(1.25rem, 2.2vw, 2rem);
            margin-bottom: 1.1rem;
            background:
                linear-gradient(135deg, rgba(11, 31, 58, 0.98) 0%, rgba(18, 58, 99, 0.96) 54%, rgba(14, 165, 183, 0.88) 100%);
            box-shadow: var(--pcr-shadow-lg);
            border: 1px solid rgba(255, 255, 255, 0.18);
            min-height: 10.8rem;
        }}

        .pcr-hero::after {{
            content: "";
            position: absolute;
            inset: auto 2rem 1.2rem auto;
            width: min(30vw, 360px);
            height: 74%;
            border-radius: 18px;
            background:
                repeating-linear-gradient(
                    90deg,
                    rgba(255,255,255,0.08) 0 14px,
                    rgba(14,165,183,0.26) 14px 18px,
                    rgba(255,255,255,0.05) 18px 40px
                ),
                linear-gradient(180deg, rgba(255,255,255,0.12), rgba(255,255,255,0.02));
            opacity: 0.78;
            transform: skewX(-7deg);
        }}

        .pcr-hero h1 {{
            max-width: 13em;
            font-size: clamp(2rem, 3vw, 3.15rem);
            font-weight: 850;
            letter-spacing: 0;
            line-height: 1.12;
        }}

        .pcr-hero p {{
            max-width: 46rem;
            font-size: clamp(0.98rem, 1.1vw, 1.1rem);
            color: rgba(255, 255, 255, 0.9);
            white-space: normal !important;
        }}

        .pcr-role-badge {{
            background: rgba(223, 248, 251, 0.12);
            border-color: rgba(223, 248, 251, 0.38);
            color: #e7fdff;
        }}

        div[data-testid="stVerticalBlockBorderWrapper"] {{
            border-color: rgba(11, 31, 58, 0.1) !important;
            border-radius: 14px !important;
            background: var(--pcr-surface);
            box-shadow: var(--pcr-shadow-sm);
            backdrop-filter: blur(10px);
        }}

        .pcr-card-title {{
            font-size: 1.08rem;
            font-weight: 850;
            color: var(--pcr-ink);
        }}

        .pcr-home-hero {{
            position: relative;
            overflow: hidden;
            border-radius: 24px;
            padding: clamp(1.35rem, 2.5vw, 2.4rem);
            margin-bottom: 1rem;
            color: #ffffff;
            background:
                linear-gradient(135deg, rgba(7, 23, 43, 0.98) 0%, rgba(11, 31, 58, 0.96) 58%, rgba(14, 165, 183, 0.88) 100%);
            box-shadow: var(--pcr-shadow-lg);
            display: grid;
            grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
            gap: clamp(1.2rem, 3vw, 3rem);
            align-items: center;
        }}

        .pcr-home-hero h1 {{
            margin: 0;
            font-size: clamp(2.15rem, 3.5vw, 4rem);
            line-height: 1.08;
            font-weight: 900;
            letter-spacing: 0;
        }}

        .pcr-home-hero p {{
            max-width: 52rem;
            margin: 0.85rem 0 1.1rem 0;
            color: rgba(255, 255, 255, 0.88);
            line-height: 1.75;
            font-size: 1.04rem;
        }}

        .pcr-home-proof {{
            display: flex;
            gap: 0.55rem;
            flex-wrap: wrap;
            margin-top: 0.9rem;
        }}

        .pcr-home-proof span {{
            border: 1px solid rgba(223, 248, 251, 0.32);
            background: rgba(223, 248, 251, 0.1);
            color: #e7fdff;
            border-radius: 999px;
            padding: 0.28rem 0.7rem;
            font-size: 0.8rem;
            font-weight: 750;
        }}

        .pcr-hero-actions {{
            margin: 0.2rem 0 1.6rem 0;
        }}

        .pcr-home-section-title {{
            margin: clamp(1.55rem, 2.4vw, 2.2rem) 0 0.82rem 0;
        }}

        .pcr-home-section-title h2 {{
            margin: 0;
            color: var(--pcr-ink);
            font-size: clamp(1.3rem, 1.6vw, 1.75rem);
            line-height: 1.28;
            font-weight: 880;
            letter-spacing: 0;
        }}

        .pcr-home-section-title p {{
            margin: 0.35rem 0 0 0;
            color: var(--pcr-muted);
            font-size: 0.96rem;
            line-height: 1.7;
        }}

        .pcr-gel-panel {{
            position: relative;
            min-height: 15.5rem;
            border-radius: 22px;
            padding: 1.05rem;
            background: rgba(255, 255, 255, 0.09);
            border: 1px solid rgba(255, 255, 255, 0.18);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16);
        }}

        .pcr-gel-title {{
            color: rgba(255,255,255,0.76);
            font-size: 0.78rem;
            font-weight: 750;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.75rem;
        }}

        .pcr-gel-grid {{
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 0.58rem;
            height: 10.8rem;
        }}

        .pcr-gel-lane {{
            position: relative;
            overflow: hidden;
            border-radius: 12px;
            background: linear-gradient(180deg, rgba(7,23,43,0.64), rgba(11,31,58,0.36));
            border: 1px solid rgba(223, 248, 251, 0.14);
        }}

        .pcr-gel-lane::before,
        .pcr-gel-lane::after {{
            content: "";
            position: absolute;
            left: 18%;
            right: 18%;
            height: 0.52rem;
            border-radius: 999px;
            background: rgba(103, 232, 249, 0.78);
            box-shadow: 0 0 18px rgba(103, 232, 249, 0.7);
        }}

        .pcr-gel-lane::before {{ top: var(--band-a, 26%); opacity: var(--a, .92); }}
        .pcr-gel-lane::after {{ top: var(--band-b, 62%); opacity: var(--b, .5); }}

        .pcr-workbench-card {{
            border: 1px solid rgba(11, 31, 58, 0.1);
            border-radius: 14px;
            padding: 1rem;
            background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(246,251,253,0.92));
            min-height: 13rem;
            box-shadow: var(--pcr-shadow-sm);
        }}

        .pcr-workbench-card h3 {{
            margin: 0 0 0.45rem 0;
            font-size: 1.05rem;
            color: var(--pcr-ink);
        }}

        .pcr-workbench-card p {{
            margin: 0 0 0.8rem 0;
            color: var(--pcr-muted);
            line-height: 1.6;
            min-height: 3.1rem;
        }}

        .pcr-workbench-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.42rem;
            margin-bottom: 0.8rem;
        }}

        .pcr-workbench-meta span,
        .pcr-status-strip span,
        .pcr-home-status-grid span,
        .pcr-current-step-chip {{
            border-radius: 999px;
            border: 1px solid rgba(14, 165, 183, 0.22);
            background: rgba(223, 248, 251, 0.58);
            color: #075985;
            font-size: 0.76rem;
            font-weight: 800;
            padding: 0.18rem 0.58rem;
        }}

        .pcr-status-strip {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.7rem;
        }}

        .pcr-status-strip > div {{
            border: 1px solid rgba(11, 31, 58, 0.08);
            border-radius: 12px;
            padding: 0.74rem 0.82rem;
            background: rgba(255,255,255,0.72);
        }}

        .pcr-status-strip b {{
            display: block;
            margin-top: 0.32rem;
            color: var(--pcr-ink);
            font-size: 1.05rem;
        }}

        .pcr-flow-grid {{
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 0.72rem;
            margin-bottom: 0.65rem;
        }}

        .pcr-flow-card {{
            position: relative;
            min-height: 12.4rem;
            border: 1px solid rgba(11, 31, 58, 0.1);
            border-radius: 14px;
            padding: 0.9rem 0.85rem;
            background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(246,251,253,0.9));
            box-shadow: var(--pcr-shadow-sm);
        }}

        .pcr-flow-index {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 2rem;
            height: 2rem;
            border-radius: 999px;
            background: rgba(14, 165, 183, 0.12);
            border: 1px solid rgba(14, 165, 183, 0.22);
            color: #075985;
            font-size: 0.8rem;
            font-weight: 850;
            margin-bottom: 0.62rem;
        }}

        .pcr-flow-card h3 {{
            margin: 0 0 0.45rem 0;
            color: var(--pcr-ink);
            font-size: 0.98rem;
            line-height: 1.38;
            font-weight: 850;
        }}

        .pcr-flow-card p {{
            margin: 0;
            color: var(--pcr-muted);
            font-size: 0.86rem;
            line-height: 1.58;
        }}

        .pcr-flow-arrow {{
            position: absolute;
            top: 1rem;
            right: -0.62rem;
            z-index: 2;
            width: 1.28rem;
            height: 1.28rem;
            border-radius: 999px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: #075985;
            background: #e0f7fb;
            border: 1px solid rgba(14, 165, 183, 0.24);
            font-weight: 850;
            font-size: 0.78rem;
        }}

        .pcr-home-status-panel {{
            border: 1px solid rgba(11, 31, 58, 0.08);
            border-radius: 14px;
            padding: 0.75rem;
            background: rgba(255, 255, 255, 0.66);
            box-shadow: 0 8px 18px rgba(11, 31, 58, 0.04);
            margin-bottom: 0.58rem;
        }}

        .pcr-home-status-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.58rem;
        }}

        .pcr-home-status-grid > div {{
            border: 1px solid rgba(11, 31, 58, 0.07);
            border-radius: 12px;
            padding: 0.58rem 0.68rem;
            background: rgba(248, 252, 253, 0.78);
        }}

        .pcr-home-status-grid b {{
            display: block;
            margin-top: 0.25rem;
            color: var(--pcr-ink);
            font-size: 0.96rem;
        }}

        .pcr-student-toolbar {{
            border-radius: 14px;
            background: linear-gradient(90deg, #ffffff 0%, rgba(223,248,251,0.7) 100%);
            border-color: rgba(14, 165, 183, 0.16);
        }}

        .pcr-stepper-item {{
            border-radius: 13px;
        }}

        .pcr-stepper-item.active {{
            border-color: rgba(14, 165, 183, 0.55);
            background: linear-gradient(180deg, rgba(223,248,251,0.78), #ffffff);
            box-shadow: 0 12px 28px rgba(14, 165, 183, 0.13);
        }}

        .pcr-stepper-item.active .pcr-stepper-index {{
            background: var(--pcr-gel-cyan);
        }}

        .pcr-readiness-panel {{
            border: 1px solid rgba(14, 165, 183, 0.2);
            border-radius: 14px;
            padding: 0.95rem;
            background: linear-gradient(180deg, rgba(223,248,251,0.68), rgba(255,255,255,0.94));
            box-shadow: var(--pcr-shadow-sm);
            margin-bottom: 0.8rem;
        }}

        .pcr-readiness-title {{
            margin: 0 0 0.6rem 0;
            font-size: 0.95rem;
            font-weight: 850;
            color: var(--pcr-ink);
        }}

        .pcr-readiness-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.5rem;
        }}

        .pcr-readiness-item {{
            border-radius: 11px;
            padding: 0.58rem 0.62rem;
            background: rgba(255,255,255,0.76);
            border: 1px solid rgba(11,31,58,0.07);
        }}

        .pcr-readiness-item span {{
            color: var(--pcr-muted);
            font-size: 0.74rem;
            font-weight: 750;
        }}

        .pcr-readiness-item b {{
            display: block;
            margin-top: 0.15rem;
            color: var(--pcr-ink);
            font-size: 0.95rem;
        }}

        .pcr-gel-placeholder {{
            border: 1px dashed rgba(14, 165, 183, 0.45);
            border-radius: 14px;
            min-height: 9.5rem;
            padding: 0.95rem;
            background:
                repeating-linear-gradient(90deg, rgba(14,165,183,0.1) 0 10px, transparent 10px 32px),
                linear-gradient(180deg, rgba(223,248,251,0.72), rgba(255,255,255,0.86));
            display: flex;
            flex-direction: column;
            justify-content: center;
            color: #075985;
        }}

        .pcr-gel-placeholder b {{
            color: var(--pcr-ink);
            margin-bottom: 0.28rem;
        }}

        .pcr-top1-card {{
            border-color: rgba(14, 165, 183, 0.28);
            background:
                linear-gradient(135deg, rgba(223,248,251,0.9), rgba(255,255,255,0.98));
            border-radius: 16px;
            box-shadow: var(--pcr-shadow-md);
        }}

        .pcr-candidate-list {{
            display: grid;
            gap: 0.55rem;
            margin: 0.7rem 0;
        }}

        .pcr-candidate-row {{
            display: flex;
            justify-content: space-between;
            gap: 0.75rem;
            align-items: center;
            border: 1px solid rgba(11,31,58,0.08);
            border-radius: 12px;
            padding: 0.62rem 0.75rem;
            background: rgba(255,255,255,0.8);
        }}

        .pcr-candidate-row b {{
            color: var(--pcr-ink);
        }}

        .pcr-candidate-row span {{
            color: var(--pcr-muted);
            font-weight: 750;
            white-space: nowrap;
        }}

        div.stButton > button, div.stDownloadButton > button {{
            border-radius: 11px;
            border-color: rgba(14, 165, 183, 0.32);
            min-height: 2.8rem;
        }}

        div.stButton > button[kind="primary"],
        div.stButton > button[data-testid="baseButton-primary"] {{
            background: linear-gradient(90deg, var(--pcr-lab-blue), var(--pcr-diagnostic-blue));
            border: 0;
            box-shadow: 0 12px 24px rgba(37, 99, 235, 0.18);
        }}

        /* Open Design / IBM Carbon inspired homepage layer */
        :root {{
            --pcr-bg: #F6FAFC;
            --pcr-surface: #FFFFFF;
            --pcr-ink: #161616;
            --pcr-muted: #525252;
            --pcr-border: #D8E3EA;
            --pcr-lab-blue: #0B1F3A;
            --pcr-diagnostic-blue: #2563EB;
            --pcr-diagnostic-blue-hover: #1D4ED8;
            --pcr-gel-cyan: #0EA5B7;
            --pcr-domain-muted: #E0F7FA;
            --pcr-accent-tint: #EFF6FF;
        }}

        .stApp {{
            background: var(--pcr-bg);
            color: var(--pcr-ink);
        }}

        .main .block-container {{
            max-width: min(1200px, calc(100vw - 64px));
            padding-top: 0;
            padding-left: 0;
            padding-right: 0;
            padding-bottom: 0;
        }}

        .pcr-home-hero {{
            min-height: clamp(560px, 72vh, 720px);
            width: 100%;
            margin: 0 0 4rem 0;
            padding: clamp(4rem, 8vw, 6rem) clamp(2rem, 4vw, 4rem);
            border-radius: 0;
            border: 0;
            box-shadow: none;
            color: #F6FAFC;
            background: var(--pcr-lab-blue);
            display: grid;
            grid-template-columns: minmax(0, 0.95fr) minmax(360px, 1.05fr);
            gap: clamp(2rem, 5vw, 5rem);
            align-items: center;
            overflow: hidden;
        }}

        .pcr-home-hero::before {{
            content: "";
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 1px;
            background: rgba(216, 227, 234, 0.16);
        }}

        .pcr-home-hero-content {{
            padding-left: 2rem;
        }}

        .pcr-home-kicker {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 1.5rem;
            color: var(--pcr-gel-cyan);
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.02rem;
        }}

        .pcr-home-kicker i {{
            width: 0.5rem;
            height: 0.5rem;
            border-radius: 50%;
            background: var(--pcr-gel-cyan);
        }}

        .pcr-home-hero h1 {{
            max-width: 11.5em;
            margin: 0 0 1.25rem 0;
            font-size: clamp(2.25rem, 4vw, 3.25rem);
            line-height: 1.15;
            font-weight: 300;
            letter-spacing: 0;
            color: #F6FAFC;
        }}

        .pcr-home-hero p {{
            max-width: 34rem;
            margin: 0;
            color: rgba(246, 250, 252, 0.8);
            font-size: 1rem;
            line-height: 1.6;
        }}

        .pcr-gel-panel {{
            min-height: 32rem;
            border-radius: 4px;
            padding: 0;
            border: 1px solid rgba(14, 165, 183, 0.24);
            background: rgba(14, 165, 183, 0.08);
            box-shadow: none;
            overflow: hidden;
        }}

        .pcr-gel-header {{
            display: grid;
            grid-template-columns: 4.6rem repeat(7, 1fr);
            gap: 0;
            padding: 0.9rem 1.1rem 0.55rem 1.1rem;
            color: rgba(103, 197, 221, 0.72);
            font-family: "IBM Plex Mono", Consolas, monospace;
            font-size: 0.8rem;
            text-align: center;
            border-bottom: 1px solid rgba(14, 165, 183, 0.13);
            background: rgba(3, 16, 32, 0.18);
        }}

        .pcr-gel-body {{
            position: relative;
            display: grid;
            grid-template-columns: 4.6rem 1fr;
            gap: 0.75rem;
            height: 27.4rem;
            padding: 1.2rem 1.2rem 1.4rem 1.2rem;
        }}

        .pcr-gel-scale {{
            display: grid;
            grid-template-rows: repeat(7, 1fr);
            color: rgba(103, 197, 221, 0.72);
            font-family: "IBM Plex Mono", Consolas, monospace;
            font-size: 0.76rem;
            align-items: center;
            text-align: right;
        }}

        .pcr-gel-grid {{
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 0.75rem;
            height: 100%;
        }}

        .pcr-gel-lane {{
            position: relative;
            overflow: hidden;
            border-radius: 4px;
            border: 1px solid rgba(14, 165, 183, 0.14);
            background: rgba(2, 16, 32, 0.24);
        }}

        .pcr-gel-lane::before,
        .pcr-gel-lane::after {{
            left: 20%;
            right: 20%;
            height: 0.2rem;
            border-radius: 2px;
            background: var(--pcr-gel-cyan);
            box-shadow: none;
        }}

        .pcr-gel-lane.marker::before {{
            top: 10%;
            box-shadow:
                0 2.7rem 0 var(--pcr-gel-cyan),
                0 5.4rem 0 var(--pcr-gel-cyan),
                0 8.1rem 0 var(--pcr-gel-cyan),
                0 10.8rem 0 var(--pcr-gel-cyan),
                0 13.5rem 0 var(--pcr-gel-cyan),
                0 16.2rem 0 var(--pcr-gel-cyan),
                0 18.9rem 0 var(--pcr-gel-cyan);
        }}

        .pcr-gel-lane.marker::after {{
            display: none;
        }}

        .pcr-gel-lane.weak::before,
        .pcr-gel-lane.weak::after {{
            opacity: 0.35;
        }}

        .pcr-gel-lane.smear::after {{
            left: 28%;
            right: 28%;
            height: 3rem;
            border-radius: 4px;
            opacity: 0.22;
        }}

        .pcr-diagnosis-note {{
            position: absolute;
            right: 1.2rem;
            bottom: 1.4rem;
            width: 12rem;
            border: 1px solid rgba(37, 99, 235, 0.32);
            border-radius: 4px;
            padding: 0.9rem;
            background: rgba(11, 31, 58, 0.72);
        }}

        .pcr-diagnosis-note span {{
            display: block;
            margin-bottom: 0.35rem;
            color: var(--pcr-gel-cyan);
            font-family: "IBM Plex Mono", Consolas, monospace;
            font-size: 0.72rem;
            letter-spacing: 0.08rem;
        }}

        .pcr-diagnosis-note b {{
            display: block;
            margin-bottom: 0.35rem;
            color: #F6FAFC;
            font-size: 0.95rem;
            font-weight: 600;
        }}

        .pcr-diagnosis-note p {{
            margin: 0;
            color: rgba(246, 250, 252, 0.62);
            font-size: 0.78rem;
            line-height: 1.5;
        }}

        div.stButton > button,
        div.stDownloadButton > button {{
            border-radius: 0;
            min-height: 3rem;
            border: 1px solid var(--pcr-border);
            box-shadow: none;
            font-size: 0.88rem;
            font-weight: 600;
            letter-spacing: 0;
        }}

        div.stButton > button[kind="primary"],
        div.stButton > button[data-testid="baseButton-primary"] {{
            background: var(--pcr-diagnostic-blue) !important;
            border-color: var(--pcr-diagnostic-blue) !important;
            box-shadow: none !important;
            color: #ffffff !important;
        }}

        div.stButton > button[kind="primary"]:hover,
        div.stButton > button[data-testid="baseButton-primary"]:hover {{
            background: var(--pcr-diagnostic-blue-hover) !important;
            border-color: var(--pcr-diagnostic-blue-hover) !important;
        }}

        .pcr-home-section-title {{
            margin: 0 auto 3rem auto;
            padding-top: 4.5rem;
            text-align: center;
            max-width: 56rem;
        }}

        .pcr-home-section-title span {{
            display: inline-flex;
            margin-bottom: 1rem;
            border-radius: 999px;
            padding: 0.3rem 0.8rem;
            background: var(--pcr-accent-tint);
            color: var(--pcr-diagnostic-blue);
            font-size: 0.78rem;
            font-weight: 600;
        }}

        .pcr-home-section-title span:empty {{
            display: none;
        }}

        .pcr-home-section-title h2 {{
            margin: 0;
            color: var(--pcr-ink);
            font-size: clamp(1.9rem, 3vw, 2.25rem);
            line-height: 1.22;
            font-weight: 300;
        }}

        .pcr-home-section-title p {{
            margin: 1rem 0 0 0;
            color: var(--pcr-muted);
            font-size: 1rem;
            line-height: 1.6;
        }}

        .pcr-problem-grid {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 1.5rem;
            margin-bottom: 1rem;
        }}

        .pcr-problem-card {{
            min-height: 12.6rem;
            border-radius: 4px;
            padding: 2rem;
            background: var(--pcr-lab-blue);
            color: #F6FAFC;
        }}

        .pcr-problem-number {{
            margin-bottom: 1rem;
            color: var(--pcr-gel-cyan);
            font-family: "IBM Plex Mono", Consolas, monospace;
            font-size: 0.9rem;
        }}

        .pcr-problem-card h3 {{
            margin: 0 0 0.75rem 0;
            color: #F6FAFC;
            font-size: 1.1rem;
            line-height: 1.35;
            font-weight: 600;
        }}

        .pcr-problem-card p {{
            margin: 0;
            color: rgba(246, 250, 252, 0.72);
            font-size: 0.92rem;
            line-height: 1.58;
        }}

        .pcr-flow-grid {{
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 0;
            margin: 1rem 0 2rem 0;
        }}

        .pcr-flow-card {{
            position: relative;
            min-height: 15rem;
            border: 1px solid var(--pcr-border);
            border-radius: 4px;
            padding: 2rem 1.25rem;
            background: #FFFFFF;
            box-shadow: none;
            text-align: center;
        }}

        .pcr-flow-card:hover {{
            border-color: var(--pcr-diagnostic-blue);
        }}

        .pcr-flow-index {{
            width: 2.5rem;
            height: 2.5rem;
            margin: 0 auto 1rem auto;
            border: 0;
            border-radius: 50%;
            background: var(--pcr-accent-tint);
            color: var(--pcr-diagnostic-blue);
            font-family: "IBM Plex Mono", Consolas, monospace;
            font-size: 0.9rem;
            font-weight: 400;
        }}

        .pcr-flow-card h3 {{
            margin: 0 0 0.55rem 0;
            color: var(--pcr-ink);
            font-size: 1rem;
            line-height: 1.35;
            font-weight: 600;
        }}

        .pcr-flow-card p {{
            margin: 0;
            color: var(--pcr-muted);
            font-size: 0.82rem;
            line-height: 1.5;
        }}

        .pcr-flow-connector {{
            position: absolute;
            right: -1px;
            top: 50%;
            width: 2px;
            height: 2rem;
            background: var(--pcr-border);
            transform: translateY(-50%);
        }}

        .pcr-flow-connector::after {{
            content: "";
            position: absolute;
            right: -5px;
            top: 50%;
            width: 0;
            height: 0;
            border-left: 6px solid var(--pcr-border);
            border-top: 4px solid transparent;
            border-bottom: 4px solid transparent;
            transform: translateY(-50%);
        }}

        .pcr-capability-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 1.5rem;
            margin-bottom: 5rem;
        }}

        .pcr-capability-card {{
            min-height: 17rem;
            border: 1px solid var(--pcr-border);
            border-radius: 4px;
            padding: 2rem;
            background: #FFFFFF;
        }}

        .pcr-capability-card:hover {{
            border-color: var(--pcr-diagnostic-blue);
        }}

        .pcr-capability-icon {{
            width: 3rem;
            height: 3rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 1.25rem;
            border-radius: 4px;
            font-family: "IBM Plex Mono", Consolas, monospace;
            font-size: 0.9rem;
        }}

        .pcr-capability-icon.blue {{
            background: var(--pcr-accent-tint);
            color: var(--pcr-diagnostic-blue);
        }}

        .pcr-capability-icon.cyan {{
            background: var(--pcr-domain-muted);
            color: var(--pcr-gel-cyan);
        }}

        .pcr-capability-card h3 {{
            margin: 0 0 0.75rem 0;
            color: var(--pcr-ink);
            font-size: 1.12rem;
            font-weight: 600;
        }}

        .pcr-capability-card p {{
            margin: 0;
            color: var(--pcr-muted);
            font-size: 0.92rem;
            line-height: 1.6;
        }}

        .pcr-home-footer {{
            display: grid;
            grid-template-columns: 2fr 1fr 1fr 1.2fr;
            gap: 3rem;
            margin-top: 3.5rem;
            padding: 3rem 2rem;
            border-radius: 0;
            background: var(--pcr-lab-blue);
            color: #F6FAFC;
        }}

        .pcr-home-footer h3 {{
            margin: 0 0 0.5rem 0;
            color: #F6FAFC;
            font-size: 1rem;
            font-weight: 600;
        }}

        .pcr-home-footer p {{
            margin: 0;
            color: rgba(246, 250, 252, 0.58);
            font-size: 0.88rem;
            line-height: 1.55;
        }}

        .pcr-footer-label {{
            display: block;
            margin-bottom: 1rem;
            color: rgba(246, 250, 252, 0.48);
            font-size: 0.76rem;
            font-weight: 600;
        }}

        .pcr-footer-status {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.55rem;
            color: rgba(246, 250, 252, 0.78);
            font-size: 0.88rem;
        }}

        .pcr-footer-status i {{
            width: 0.38rem;
            height: 0.38rem;
            border-radius: 50%;
            background: #6F6F6F;
        }}

        .pcr-footer-status i.open {{
            background: #24A148;
        }}

        .pcr-footer-status i.current {{
            background: var(--pcr-gel-cyan);
            box-shadow: 0 0 0 3px rgba(14, 165, 183, 0.18);
        }}

        @media (max-width: 768px) {{
            .main .block-container {{
                max-width: 100vw;
                padding-left: 0;
                padding-right: 0;
            }}

            .pcr-home-hero {{
                grid-template-columns: 1fr;
                min-height: auto;
                padding: 4rem 1rem 3rem 1rem;
            }}

            .pcr-home-hero h1 {{
                font-size: 2.15rem;
            }}

            .pcr-home-hero-content {{
                padding-left: 0;
            }}

            .pcr-gel-panel {{
                min-height: 20rem;
            }}

            .pcr-gel-grid {{
                height: 100%;
            }}

            .pcr-hero {{
                min-height: 8.8rem;
                padding: 1.1rem;
            }}

            .pcr-hero::after {{
                width: 52%;
                opacity: 0.34;
            }}

            .pcr-status-strip,
            .pcr-readiness-grid,
            .pcr-home-status-grid {{
                grid-template-columns: 1fr;
            }}

            .pcr-problem-grid,
            .pcr-capability-grid,
            .pcr-home-footer {{
                grid-template-columns: 1fr;
            }}

            .pcr-stepper-grid {{
                display: none;
            }}

            .pcr-flow-grid {{
                grid-template-columns: 1fr;
                gap: 1rem;
            }}

            .pcr-flow-card {{
                min-height: auto;
            }}

            .pcr-flow-connector,
            .pcr-flow-arrow {{
                display: none;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_hero(title, subtitle, role_label):
    """页面顶部 Hero 区"""
    st.markdown(
        f"""
        <div class="pcr-hero">
            <span class="pcr-role-badge">{role_label}</span>
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_card_title(title, desc=""):
    """卡片标题辅助函数"""
    st.markdown(f'<div class="pcr-card-title">{title}</div>', unsafe_allow_html=True)
    if desc:
        st.markdown(f'<div class="pcr-muted">{desc}</div>', unsafe_allow_html=True)


def render_info_tiles(items, columns=3):
    """横向信息卡片，用于首页说明与步骤展示。"""
    if not items:
        return

    cols = st.columns(columns)
    for index, item in enumerate(items):
        with cols[index % columns]:
            st.markdown(
                f"""
                <div class="pcr-tile">
                    <span class="pcr-tile-tag">{item.get("tag", "模块")}</span>
                    <h3>{item.get("title", "")}</h3>
                    <p>{item.get("desc", "")}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_soft_notice(title, desc):
    """轻量提示卡。"""
    st.markdown(
        f"""
        <div class="pcr-soft-note">
            <div class="pcr-soft-note-title">{title}</div>
            <p>{desc}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_hero(title, subtitle, role_text=""):
    """统一的页面顶部 hero；首页可不显示左上角角标。"""
    badge_html = ""
    if str(role_text or "").strip():
        badge_html = f'<span class="pcr-role-badge">{role_text}</span>'

    st.markdown(
        f"""
        <div class="pcr-hero">
            {badge_html}
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def run_system_self_check():
    """
    系统自检：
    检查关键组件是否可用，返回统一结构，避免单项失败影响全页。
    """
    checks = {}

    # 1) rules.csv 检查：文件存在且可读取
    try:
        if not os.path.exists(RULES_PATH):
            checks["rules_csv"] = {"level": "warning", "status": "未检测到", "detail": f"{RULES_PATH} 不存在"}
        else:
            read_csv_with_fallback(RULES_PATH)
            checks["rules_csv"] = {"level": "success", "status": "正常", "detail": "rules.csv 读取成功"}
    except Exception as e:
        checks["rules_csv"] = {"level": "error", "status": "失败", "detail": str(e)[:120]}

    # 2) SQLite 检查：可连接并执行简单查询
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        checks["sqlite"] = {"level": "success", "status": "正常", "detail": f"{DB_PATH} 可连接"}
    except Exception as e:
        checks["sqlite"] = {"level": "error", "status": "失败", "detail": str(e)[:120]}

    # 3) uploads 目录检查
    if os.path.isdir(UPLOAD_DIR):
        checks["uploads"] = {"level": "success", "status": "正常", "detail": f"{UPLOAD_DIR} 已存在"}
    else:
        checks["uploads"] = {"level": "warning", "status": "未创建", "detail": f"{UPLOAD_DIR} 目录不存在"}

    # 4) 环境变量检查
    api_key_exists = bool(os.getenv("BIGMODEL_API_KEY", "").strip())
    base_url_exists = bool(os.getenv("BIGMODEL_BASE_URL", "").strip())
    model_exists = bool(os.getenv("BIGMODEL_MODEL", "").strip())
    checks["bigmodel_api_key"] = {
        "level": "success" if api_key_exists else "warning",
        "status": "正常" if api_key_exists else "未检测到",
        "detail": "BIGMODEL_API_KEY"
    }
    checks["bigmodel_base_url"] = {
        "level": "success" if base_url_exists else "warning",
        "status": "正常" if base_url_exists else "未检测到",
        "detail": "BIGMODEL_BASE_URL"
    }
    checks["bigmodel_model"] = {
        "level": "success",
        "status": "正常",
        "detail": os.getenv("BIGMODEL_MODEL", BIGMODEL_MODEL)
    }

    # 6) 文本抽取优先方式（当前代码逻辑）
    checks["extractor_strategy"] = {
        "level": "success",
        "status": "正常",
        "detail": "优先调用 BigModel / GLM 接口，失败时回退本地关键词规则"
    }

    return checks


def render_system_self_check():
    """渲染系统自检区域"""
    st.markdown("### 系统自检")
    checks = run_system_self_check()

    # 固定展示顺序，方便演示时快速扫一眼
    items = [
        ("rules_csv", "rules.csv 读取"),
        ("sqlite", "SQLite 数据库连接"),
        ("uploads", "uploads 文件夹"),
        ("bigmodel_api_key", "BIGMODEL_API_KEY"),
        ("bigmodel_base_url", "BIGMODEL_BASE_URL"),
        ("bigmodel_model", "当前模型名"),
        ("extractor_strategy", "文本抽取优先方式"),
    ]

    for key, label in items:
        item = checks.get(key, {"level": "warning", "status": "未知", "detail": ""})
        msg = f"{label}：{item['status']}（{item['detail']}）"
        if item["level"] == "success":
            st.success(msg)
        elif item["level"] == "error":
            st.error(msg)
        else:
            st.warning(msg)


def render_system_self_check():
    """渲染系统自检区域，使用统一状态卡布局。"""
    st.markdown("### 系统自检")
    checks = run_system_self_check()
    items = [
        ("rules_csv", "rules.csv 读取"),
        ("sqlite", "SQLite 数据库连接"),
        ("uploads", "uploads 文件夹"),
        ("bigmodel_api_key", "BIGMODEL_API_KEY"),
        ("bigmodel_base_url", "BIGMODEL_BASE_URL"),
        ("bigmodel_model", "当前模型"),
        ("extractor_strategy", "文本抽取优先方式"),
    ]

    cols = st.columns(3)
    level_class_map = {
        "success": "pcr-status-success",
        "warning": "pcr-status-warning",
        "error": "pcr-status-error",
    }
    for index, (key, label) in enumerate(items):
        item = checks.get(key, {"level": "warning", "status": "未知", "detail": ""})
        css_class = level_class_map.get(item["level"], "pcr-status-neutral")
        with cols[index % 3]:
            st.markdown(
                f"""
                <div class="pcr-status-card {css_class}">
                    <b>{label}：{item['status']}</b>
                    <p>{item['detail']}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )


def run_rules_library_check():
    """
    规则库检查：
    返回 {"ok": bool, "issues": [...], "warnings": [...]}，用于页面显示。
    """
    issues = []
    warnings = []

    # 1) 文件存在与读取
    if not os.path.exists(RULES_PATH):
        issues.append(f"{RULES_PATH} 不存在")
        return {"ok": False, "issues": issues, "warnings": warnings}

    try:
        df = read_csv_with_fallback(RULES_PATH)
    except Exception as e:
        issues.append(f"rules.csv 读取失败：{str(e)[:120]}")
        return {"ok": False, "issues": issues, "warnings": warnings}

    # 2) 必要字段是否齐全
    missing_cols = [c for c in REQUIRED_RULE_COLUMNS if c not in df.columns]
    if missing_cols:
        issues.append(f"缺少必要字段：{', '.join(missing_cols)}")

    # 下面检查都在字段存在时进行，避免二次报错
    def count_empty(col_name):
        s = df[col_name]
        return int((s.isna() | (s.astype(str).str.strip() == "")).sum())

    # 3) 空字段检查
    if "abnormality" in df.columns:
        empty_abn = count_empty("abnormality")
        if empty_abn > 0:
            issues.append(f"abnormality 有空值：{empty_abn} 行")
    if "cause" in df.columns:
        empty_cause = count_empty("cause")
        if empty_cause > 0:
            issues.append(f"cause 有空值：{empty_cause} 行")
    if "suggestion" in df.columns:
        empty_suggestion = count_empty("suggestion")
        if empty_suggestion > 0:
            issues.append(f"suggestion 有空值：{empty_suggestion} 行")

    # 4) 分数字段检查：新版使用 base_score，旧版兼容 score
    score_column = "base_score" if "base_score" in df.columns else "score" if "score" in df.columns else None
    if score_column:
        score_num = pd.to_numeric(df[score_column], errors="coerce")
        invalid_score = int(score_num.isna().sum())
        if invalid_score > 0:
            issues.append(f"{score_column} 存在不可转数字值：{invalid_score} 行")

    # 5) 每种 abnormality 至少 1 条规则（按页面选项检查）
    if "abnormality" in df.columns:
        abn_series = df["abnormality"].astype(str).str.strip()
        normalized_options = {
            build_normalized_case({"abnormality": abn}).get("abnormality")
            for abn in ABNORMALITY_OPTIONS
        }
        allowed_values = set(ABNORMALITY_OPTIONS) | {value for value in normalized_options if value}
        for abn in ABNORMALITY_OPTIONS:
            normalized_abn = build_normalized_case({"abnormality": abn}).get("abnormality")
            if int(((abn_series == abn) | (abn_series == normalized_abn)).sum()) == 0:
                issues.append(f"实验现象“{abn}”缺少规则")

        # 可选提示：发现页面之外的 abnormality 值（不算硬错误）
        extra_values = sorted(set([x for x in abn_series if x and x not in allowed_values]))
        if extra_values:
            warnings.append(f"发现未在页面选项中的 abnormality：{', '.join(extra_values)}")

    return {"ok": len(issues) == 0, "issues": issues, "warnings": warnings}


def clear_history_records():
    """
    清空历史诊断记录（仅清数据，不删库、不删表结构）
    返回: (是否成功, 提示信息)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 删除前先统计总数（不要依赖 rowcount）
        cursor.execute("SELECT COUNT(*) FROM diagnosis_records")
        total_before = int(cursor.fetchone()[0] or 0)

        cursor.execute("DELETE FROM diagnosis_records")
        conn.commit()

        # 删除后再核对一次，用前后差值作为最终删除条数
        cursor.execute("SELECT COUNT(*) FROM diagnosis_records")
        total_after = int(cursor.fetchone()[0] or 0)
        deleted_count = max(total_before - total_after, 0)

        conn.close()
        return True, f"已清空历史诊断记录，共删除 {deleted_count} 条。"
    except Exception as e:
        return False, f"清空历史诊断记录失败：{str(e)[:120]}"


def clear_uploaded_images():
    """
    清空 uploads 下的测试图片文件。
    返回: (是否成功, 提示信息)
    """
    if not os.path.isdir(UPLOAD_DIR):
        return True, "uploads 文件夹不存在，无需清空。"

    # 删除前先统计当前文件数量
    files = [name for name in os.listdir(UPLOAD_DIR) if os.path.isfile(os.path.join(UPLOAD_DIR, name))]
    total_before = len(files)

    deleted_count = 0
    failed_count = 0
    failed_names = []

    for name in files:
        path = os.path.join(UPLOAD_DIR, name)
        try:
            os.remove(path)
            deleted_count += 1
        except Exception:
            failed_count += 1
            failed_names.append(name)

    if failed_count == 0:
        return True, f"已清空上传图片，共删除 {deleted_count} 个文件（删除前共 {total_before} 个）。"
    return False, f"部分图片删除失败：删除前共 {total_before}，成功 {deleted_count}，失败 {failed_count}（{', '.join(failed_names[:3])}）"


def init_database():
    """初始化SQLite数据库，创建诊断记录表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 创建诊断记录表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS diagnosis_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            abnormality TEXT,
            template_amount REAL,
            annealing_temp REAL,
            cycles INTEGER,
            positive_control_normal TEXT,
            negative_control_band TEXT,
            description TEXT,
            diagnosis_result TEXT,
            diagnosis_time TEXT,
            gel_image_path TEXT,
            teacher_final_cause TEXT,
            teacher_note TEXT,
            teacher_confirm_time TEXT
        )
    """)

    # 兼容旧数据库：如果缺少教师确认字段，则自动补字段（最小改动，不重建库）
    cursor.execute("PRAGMA table_info(diagnosis_records)")
    existing_cols = [row[1] for row in cursor.fetchall()]
    if "teacher_final_cause" not in existing_cols:
        cursor.execute("ALTER TABLE diagnosis_records ADD COLUMN teacher_final_cause TEXT")
    if "teacher_note" not in existing_cols:
        cursor.execute("ALTER TABLE diagnosis_records ADD COLUMN teacher_note TEXT")
    if "teacher_confirm_time" not in existing_cols:
        cursor.execute("ALTER TABLE diagnosis_records ADD COLUMN teacher_confirm_time TEXT")
    if "gel_image_path" not in existing_cols:
        cursor.execute("ALTER TABLE diagnosis_records ADD COLUMN gel_image_path TEXT")

    conn.commit()
    conn.close()


def save_diagnosis_record(abnormality, template_amount, annealing_temp, cycles,
                          positive_control_normal, negative_control_band,
                          description, diagnosis_result, gel_image_path=None):
    """保存诊断记录到数据库"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO diagnosis_records 
        (abnormality, template_amount, annealing_temp, cycles, 
         positive_control_normal, negative_control_band, description, 
         diagnosis_result, diagnosis_time, gel_image_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        abnormality,
        template_amount,
        annealing_temp,
        cycles,
        positive_control_normal,
        negative_control_band,
        description,
        diagnosis_result,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        gel_image_path
    ))
    # 返回本次写入记录ID，后续教师确认可复用同一条记录
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return record_id


def save_teacher_confirmation(record_id, teacher_final_cause, teacher_note):
    """保存教师确认结果到已有诊断记录"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE diagnosis_records
        SET teacher_final_cause = ?, teacher_note = ?, teacher_confirm_time = ?
        WHERE id = ?
    """, (
        teacher_final_cause,
        teacher_note,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        record_id
    ))
    conn.commit()
    conn.close()


def save_uploaded_image(uploaded_file):
    """
    保存上传图片到 uploads 目录。
    返回: (保存路径或None, 错误信息或None)
    """
    if uploaded_file is None:
        return None, None

    try:
        # 确保上传目录存在
        os.makedirs(UPLOAD_DIR, exist_ok=True)

        # 生成不重复文件名：时间戳 + uuid
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        unique_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
        save_path = os.path.join(UPLOAD_DIR, unique_name)

        # 写入二进制文件
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        return save_path, None
    except Exception as e:
        return None, str(e)[:200]


def load_rules(path=RULES_PATH):
    """加载规则文件，支持多种编码兼容"""
    encodings = ["utf-8", "utf-8-sig", "gbk"]
    for enc in encodings:
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception:
            break
    return pd.read_csv(path, encoding="utf-8", errors="replace")


def normalize_yes_no(value):
    """
    统一布尔值表示：
    支持“是/否”“yes/no”“true/false”等写法，最终转换为 yes/no
    """
    value_str = str(value).strip().lower()
    if value_str in ["是", "yes", "y", "true", "1"]:
        return "yes"
    if value_str in ["否", "no", "n", "false", "0"]:
        return "no"
    return value_str


def safe_to_float(value, default=None):
    """安全地把值转成浮点数，失败时返回 default"""
    try:
        if str(value).strip().lower() == "any":
            return default
        return float(value)
    except:
        return default


def check_in_range(user_value, min_value, max_value):
    """检查用户数值是否在规则范围内；any 表示不限制"""
    min_v = safe_to_float(min_value, None)
    max_v = safe_to_float(max_value, None)

    if min_v is not None and user_value < min_v:
        return False
    if max_v is not None and user_value > max_v:
        return False
    return True


def normalize_text_clues(clues):
    """把各种同义写法归一到固定的 5 类线索标签"""
    alias_map = {
        "污染": "污染",
        "模板量不足": "模板量不足",
        "模板少": "模板量不足",
        "模板浓度低": "模板量不足",
        "引物问题": "引物问题",
        "引物失效": "引物问题",
        "PCR体系问题": "PCR体系问题",
        "体系漏加": "PCR体系问题",
        "退火温度问题": "退火温度问题",
        "退火温度过高": "退火温度问题",
        "退火温度过低": "退火温度问题",
    }

    normalized = []
    for c in clues:
        clue = str(c).strip()
        if not clue:
            continue
        clue = alias_map.get(clue, clue)
        if clue in ALLOWED_TEXT_CLUES and clue not in normalized:
            normalized.append(clue)
    return normalized


def mask_api_key(api_key):
    """只显示 key 前6位和后4位，中间隐藏，避免泄露"""
    key = str(api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 10:
        return f"{key[:2]}***{key[-2:]}"
    return f"{key[:6]}***{key[-4:]}"


def extract_text_clues(description):
    """
    从学生补充描述中提取简单文本线索（关键词规则法）
    这是一个“伪 AI 抽取器”，用于先打通自由文本参与诊断的链路
    """
    text = str(description or "").strip().lower()
    if not text:
        return []

    # 每类线索对应一组关键词（命中任意一个即可）
    clue_rules = {
        "污染": ["污染", "contam", "杂带", "阴性对照有带"],
        "模板量不足": ["模板量不足", "模板少", "模板浓度低", "模板太少", "上样少"],
        "引物问题": ["引物问题", "引物失效", "引物降解", "primer"],
        "PCR体系问题": ["体系漏加", "pcr体系问题", "体系问题", "漏加试剂", "漏加"],
        "退火温度问题": ["退火温度问题", "温度过高", "温度过低", "退火温度过高", "退火温度过低", "退火高", "退火低", "太高", "太低"],
    }

    clues = []
    for clue_name, keywords in clue_rules.items():
        if any(k in text for k in keywords):
            clues.append(clue_name)
    return normalize_text_clues(clues)


def parse_bigmodel_clues_response(content):
    """
    解析 BigModel 返回内容（宽松版）：
    1) 优先解析纯 JSON
    2) 再尝试从代码块/数组/对象中提取 JSON
    3) 最后做一次标签关键词兜底提取
    成功返回 (线索列表, None)，失败返回 (None, 失败原因)
    """
    raw = str(content or "").strip()
    if not raw:
        return None, "模型返回空结果"

    def _normalize_from_data(data):
        """从 list/dict 中提取并归一化线索"""
        if isinstance(data, list):
            return normalize_text_clues(data)
        if isinstance(data, dict):
            for key in ["clues", "labels", "result", "data"]:
                value = data.get(key)
                if isinstance(value, list):
                    return normalize_text_clues(value)
        return None

    # 1) 先试直接 JSON
    try:
        direct_data = json.loads(raw)
        clues = _normalize_from_data(direct_data)
        if clues is not None:
            if clues:
                return clues, None
            return None, "模型返回空结果"
    except:
        pass

    # 2) 再试提取 JSON 片段（代码块 / 数组 / 对象）
    candidates = []
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
    if code_block_match:
        candidates.append(code_block_match.group(1).strip())

    list_match = re.search(r"\[[\s\S]*\]", raw)
    if list_match:
        candidates.append(list_match.group(0).strip())

    obj_match = re.search(r"\{[\s\S]*\}", raw)
    if obj_match:
        candidates.append(obj_match.group(0).strip())

    for part in candidates:
        try:
            part_data = json.loads(part)
            clues = _normalize_from_data(part_data)
            if clues is not None:
                if clues:
                    return clues, None
                return None, "模型返回空结果"
        except:
            continue

    # 3) 最后做一次宽松文本兜底（直接查标签词）
    loose_clues = [label for label in ALLOWED_TEXT_CLUES if label in raw]
    loose_clues = normalize_text_clues(loose_clues)
    if loose_clues:
        return loose_clues, None

    return None, "返回内容不是合法 JSON"


def extract_text_clues_with_bigmodel(description, api_key, base_url, model):
    """
    优先调用 BigModel API 抽取文本线索。
    返回: (线索列表或None, 调试信息字典)
    """
    debug = {
        "bigmodel_called": False,
        "bigmodel_success": False,
        "fail_reason": "",
        "error_detail": "",
    }

    # 没安装 openai SDK：让上层回退
    if OpenAI is None:
        debug["fail_reason"] = "缺少 openai 依赖"
        return None, debug

    try:
        text = str(description or "").strip()
        debug["bigmodel_called"] = True

        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=BIGMODEL_TIMEOUT_SECONDS,
        )
        resp = client.chat.completions.create(
            model=model,
            temperature=BIGMODEL_TEMPERATURE,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是PCR诊断文本线索抽取器。"
                        "只允许从以下标签中选择并输出："
                        "污染, 模板量不足, 引物问题, PCR体系问题, 退火温度问题。"
                        "必须只输出一个JSON数组，不要输出任何其他文字。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"学生补充描述：{text}",
                },
            ],
        )

        content = ""
        if resp and resp.choices and resp.choices[0].message:
            content = resp.choices[0].message.content or ""

        parsed, parse_error = parse_bigmodel_clues_response(content)
        if parsed is None:
            debug["fail_reason"] = parse_error or "返回内容解析失败"
            return None, debug

        debug["bigmodel_success"] = True
        return parsed, debug
    except Exception as e:
        debug["fail_reason"] = "BigModel API 请求失败"
        debug["error_detail"] = str(e)[:200]
        return None, debug


def extract_text_clues_with_fallback(description):
    """
    抽取入口：
    1) 先走 BigModel API
    2) 失败后自动回退本地关键词抽取器
    返回：(线索列表, 抽取来源文案, 调试信息)
    """
    api_key = os.getenv("BIGMODEL_API_KEY", "").strip()
    base_url_env = os.getenv("BIGMODEL_BASE_URL", "").strip()
    base_url = base_url_env or BIGMODEL_DEFAULT_BASE_URL
    model = os.getenv("BIGMODEL_MODEL", BIGMODEL_MODEL)

    debug_info = {
        "api_key_exists": bool(api_key),
        "base_url_exists": bool(base_url_env),
        "api_key_masked": mask_api_key(api_key),
        "extractor_used": "本地规则抽取",
        "fail_reason": "",
        "error_detail": "",
        "base_url": base_url,
        "model": model,
    }

    # 没有学生描述时，直接本地抽取（通常为空线索）
    text = str(description or "").strip()
    if not text:
        debug_info["fail_reason"] = "学生描述为空，未调用 BigModel"
        local_clues = extract_text_clues(description)
        return local_clues, "本地规则抽取", debug_info

    # 没有 key，直接本地兜底
    if not api_key:
        debug_info["fail_reason"] = "未读取到 BIGMODEL_API_KEY"
        local_clues = extract_text_clues(description)
        return local_clues, "本地规则抽取", debug_info

    bigmodel_clues, bigmodel_debug = extract_text_clues_with_bigmodel(description, api_key, base_url, model)
    if bigmodel_clues is not None:
        debug_info["extractor_used"] = "AI（BigModel）抽取"
        return bigmodel_clues, "AI（BigModel）抽取", debug_info

    # BigModel 调用失败，记录失败原因并回退
    debug_info["fail_reason"] = bigmodel_debug.get("fail_reason", "BigModel 调用失败")
    debug_info["error_detail"] = bigmodel_debug.get("error_detail", "")

    local_clues = extract_text_clues(description)
    return local_clues, "本地规则抽取", debug_info


def calculate_text_clue_bonus(rule, text_clues, bonus_per_hit=5):
    """
    计算文本线索加分：
    若线索与当前规则的 cause/suggestion 关键词有关，则每命中一个线索加分
    """
    if not text_clues:
        return 0, []

    # 规则文本：用于做关键词包含判断
    rule_text = f"{rule.get('cause', '')} {rule.get('suggestion', '')}".lower()

    # 线索 -> 用于匹配规则文本的关键词
    clue_to_rule_keywords = {
        "污染": ["污染", "无菌", "超净台"],
        "模板量不足": ["模板", "模板量不足", "模板浓度过低"],
        "引物问题": ["引物"],
        "PCR体系问题": ["pcr体系", "体系", "漏加", "试剂"],
        "退火温度问题": ["退火温度", "提高退火温度", "降低退火温度", "温度过高", "温度过低"],
    }

    hit_clues = []
    for clue in text_clues:
        keywords = clue_to_rule_keywords.get(clue, [])
        if any(k in rule_text for k in keywords):
            hit_clues.append(clue)

    bonus = len(hit_clues) * bonus_per_hit
    return bonus, hit_clues


def calculate_score(rule, abnormality, template_amount, annealing_temp, cycles,
                    positive_control_normal, negative_control_band, text_clues=None):
    """
    计算规则匹配分数（宽松打分）
    只要实验现象一致，就进入候选集；其他条件按命中加分
    """
    # 1. 实验现象必须一致（进入候选集前提）
    if str(rule['abnormality']).strip() != str(abnormality).strip():
        return None

    # 2. 基础分（来自 rules.csv）
    base_score = safe_to_float(rule.get('score', 0), 0)
    score = base_score

    # 3. 阳性对照命中加分（any 视为可命中）
    rule_positive = normalize_yes_no(rule.get('positive_control_normal', 'any'))
    user_positive = normalize_yes_no(positive_control_normal)
    positive_hit = (rule_positive == "any" or rule_positive == user_positive)
    positive_add = 10 if positive_hit else 0
    score += positive_add

    # 4. 阴性对照命中加分（any 视为可命中）
    rule_negative = normalize_yes_no(rule.get('negative_control_band', 'any'))
    user_negative = normalize_yes_no(negative_control_band)
    negative_hit = (rule_negative == "any" or rule_negative == user_negative)
    negative_add = 10 if negative_hit else 0
    score += negative_add

    # 5. 模板量在范围内加分
    template_hit = check_in_range(template_amount, rule.get('min_template', 'any'), rule.get('max_template', 'any'))
    template_add = 8 if template_hit else 0
    score += template_add

    # 6. 退火温度在范围内加分
    temp_hit = check_in_range(annealing_temp, rule.get('min_temp', 'any'), rule.get('max_temp', 'any'))
    temp_add = 8 if temp_hit else 0
    score += temp_add

    # 7. 循环数在范围内加分（保留现有字段能力）
    cycles_hit = check_in_range(cycles, rule.get('min_cycles', 'any'), rule.get('max_cycles', 'any'))
    cycles_add = 4 if cycles_hit else 0
    score += cycles_add

    # 8. 学生自由文本线索命中加分
    text_bonus, hit_clues = calculate_text_clue_bonus(rule, text_clues or [], bonus_per_hit=5)
    score += text_bonus

    # 返回总分 + 打分明细，便于前端展示“诊断依据”
    return {
        "总分": round(float(score), 2),
        "明细": {
            "基础分": round(float(base_score), 2),
            "阳性对照": {"命中": positive_hit, "加分": positive_add},
            "阴性对照": {"命中": negative_hit, "加分": negative_add},
            "模板量范围": {"命中": template_hit, "加分": template_add},
            "退火温度范围": {"命中": temp_hit, "加分": temp_add},
            "循环数范围": {"命中": cycles_hit, "加分": cycles_add},
            "文本线索": {
                "抽取线索": text_clues or [],
                "命中线索": hit_clues,
                "加分": text_bonus
            },
            "最终总分": round(float(score), 2)
        }
    }


def diagnose(abnormality, template_amount, annealing_temp, cycles,
             positive_control_normal, negative_control_band, description=""):
    """
    诊断函数：根据输入的实验参数，返回可能的异常原因
    """
    # 从学生描述中抽取文本线索：优先 BigModel / GLM，失败回退本地关键词规则
    text_clues, clue_source, api_debug = extract_text_clues_with_fallback(description)
    api_debug["normalized_case"] = build_normalized_case({
        "abnormality": abnormality,
        "template_amount": template_amount,
        "annealing_temp": annealing_temp,
        "cycles": cycles,
        "positive_control_normal": positive_control_normal,
        "negative_control_band": negative_control_band,
        "description": description,
        "text_clues": text_clues,
    })
    try:
        api_debug["rules_v2_eval"] = evaluate_rules_v2(api_debug["normalized_case"])
        if (
            api_debug["rules_v2_eval"].get("status") == "ok"
            and api_debug["rules_v2_eval"].get("top1")
        ):
            primary_bundle = build_primary_diagnosis_from_rules_v2(api_debug["rules_v2_eval"])
            primary_results = primary_bundle.get("results", []) or []
            if primary_results:
                api_debug["primary_result_source"] = "rules_v2"
                return primary_results, True, text_clues, clue_source, api_debug
    except Exception as e:
        api_debug["rules_v2_error"] = str(e)[:200]

    fallback_results = diagnose_with_legacy_rules(
        abnormality,
        template_amount,
        annealing_temp,
        cycles,
        positive_control_normal,
        negative_control_band,
        text_clues=text_clues,
    )
    api_debug["primary_result_source"] = "legacy_fallback"
    api_debug["legacy_result_preview"] = fallback_results
    return fallback_results, bool(fallback_results), text_clues, clue_source, api_debug


def parse_top1_result(diagnosis_result):
    """
    从已保存的 diagnosis_result 文本中提取 Top1 原因和分数
    例如：1. 模板浓度过低 (总分:121.0); 2. ...
    """
    text = str(diagnosis_result or "").strip()
    if not text:
        return "未知", "-"

    # 取第一条（Top1）
    first_item = text.split(";")[0].strip()

    # 尝试按“1. 原因 (总分:xx)”格式解析
    match = re.match(r"^\d+\.\s*(.*?)\s*\(总分:\s*([^)]+)\)$", first_item)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    # 兜底：至少返回可读文本
    first_item = re.sub(r"^\d+\.\s*", "", first_item)
    return first_item if first_item else "未知", "-"


def parse_all_candidates(diagnosis_result):
    """
    解析 diagnosis_result 中保存的候选原因文本。
    返回列表：["1. 原因A (总分:xx)", "2. 原因B (总分:yy)", ...]
    """
    text = str(diagnosis_result or "").strip()
    if not text:
        return []

    parts = [p.strip() for p in text.split(";") if p.strip()]
    return parts


def parse_candidate_result_item(candidate_text, rank_hint=None):
    """把单条候选结果文本解析成统一结构"""
    text = str(candidate_text or "").strip()
    if not text:
        return None

    rank = rank_hint
    reason = text
    score = None

    match = re.match(r"^(?:(\d+)\.\s*)?(.*?)\s*\(总分:\s*([^)]+)\)$", text)
    if match:
        rank = int(match.group(1)) if match.group(1) else rank_hint
        reason = match.group(2).strip()
        score = safe_to_float(match.group(3), None)
    else:
        reason = re.sub(r"^\d+\.\s*", "", text).strip()

    return {
        "排名": rank if rank is not None else 0,
        "原因": reason if reason else "未知",
        "总分": score,
        "诊断依据": {},
        "建议": "",
    }


def _dedupe_keep_order(items):
    cleaned = []
    seen = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def format_diagnosis_result_text(results):
    parts = []
    for index, item in enumerate(results[:3], 1):
        reason = str(item.get("原因", "")).strip()
        score = item.get("总分")
        if not reason:
            continue
        score_text = "-" if score is None else score
        parts.append(f"{index}. {reason} (总分:{score_text})")
    return "; ".join(parts)


def convert_rules_v2_eval_to_display_results(rules_v2_eval):
    rules_v2_eval = rules_v2_eval or {}
    ranked_causes = rules_v2_eval.get("ranked_causes", []) or []
    normalized_case = rules_v2_eval.get("normalized_case", {}) or {}

    display_results = []
    for index, item in enumerate(ranked_causes[:3], 1):
        hit_rules = item.get("hit_rules", []) or []
        hit_combos = item.get("hit_combos", []) or []
        evidence_chain = _dedupe_keep_order(item.get("evidence_chain", []) or [])
        suggestions = _dedupe_keep_order(item.get("suggestions", []) or [])

        matched_positive = any("positive_control" in (rule.get("matched_fields", {}) or {}) for rule in hit_rules)
        matched_negative = any("negative_control" in (rule.get("matched_fields", {}) or {}) for rule in hit_rules)
        matched_template = any("template_condition" in (rule.get("matched_fields", {}) or {}) for rule in hit_rules)
        matched_temp = any("annealing_temp_condition" in (rule.get("matched_fields", {}) or {}) for rule in hit_rules)
        matched_text_hints = []
        for rule in hit_rules:
            matched_text_hints.extend((rule.get("matched_fields", {}) or {}).get("text_hint", []) or [])
        matched_text_hints = _dedupe_keep_order(matched_text_hints)

        detail = {
            "基础分": round(float(item.get("total_base_score", 0)), 2),
            "组合规则加成": round(float(item.get("combo_bonus", 0)), 2),
            "规则命中统计": {
                "基础规则": len(hit_rules),
                "组合规则": len(hit_combos),
            },
            "阳性对照": {
                "命中": matched_positive,
                "加分": 0,
                "值": normalized_case.get("positive_control", ""),
            },
            "阴性对照": {
                "命中": matched_negative,
                "加分": 0,
                "值": normalized_case.get("negative_control", ""),
            },
            "模板量范围": {
                "命中": matched_template,
                "加分": 0,
                "值": normalized_case.get("template_condition", ""),
            },
            "退火温度范围": {
                "命中": matched_temp,
                "加分": 0,
                "值": normalized_case.get("annealing_temp_condition", ""),
            },
            "循环数范围": {
                "命中": False,
                "加分": 0,
            },
            "文本线索": {
                "抽取线索": normalized_case.get("text_hint", []) or [],
                "命中线索": matched_text_hints,
                "加分": 0,
            },
            "命中基础规则": [rule.get("rule_id", "") for rule in hit_rules if str(rule.get("rule_id", "")).strip()],
            "命中组合规则": [combo.get("combo_id", "") for combo in hit_combos if str(combo.get("combo_id", "")).strip()],
            "证据链": evidence_chain,
            "建议列表": suggestions,
            "最终总分": round(float(item.get("total_score", 0)), 2),
        }

        display_results.append({
            "排名": index,
            "原因": item.get("cause", "未知"),
            "总分": round(float(item.get("total_score", 0)), 2),
            "建议": "；".join(suggestions) if suggestions else "",
            "建议列表": suggestions,
            "诊断依据": detail,
        })

    return display_results


def build_primary_diagnosis_from_rules_v2(rules_v2_eval):
    results = convert_rules_v2_eval_to_display_results(rules_v2_eval)
    return {
        "results": results,
        "candidate_texts": [
            f"{index}. {item.get('原因', '未知')} (总分:{item.get('总分', '-')})"
            for index, item in enumerate(results, 1)
        ],
        "top1_reason": results[0].get("原因", "") if results else "",
        "top1_score": results[0].get("总分") if results else None,
        "result_text": format_diagnosis_result_text(results),
    }


def diagnose_with_legacy_rules(
    abnormality,
    template_amount,
    annealing_temp,
    cycles,
    positive_control_normal,
    negative_control_band,
    text_clues=None,
):
    rules = load_rules(LEGACY_RULES_PATH)
    candidate_rules = rules[rules["abnormality"].astype(str).str.strip() == str(abnormality).strip()]
    if candidate_rules.empty:
        return []

    results = []
    for _, rule in candidate_rules.iterrows():
        score_data = calculate_score(
            rule,
            abnormality,
            template_amount,
            annealing_temp,
            cycles,
            positive_control_normal,
            negative_control_band,
            text_clues=text_clues,
        )
        if score_data is None:
            continue
        results.append({
            "原因": rule["cause"],
            "总分": score_data["总分"],
            "建议": rule["suggestion"],
            "诊断依据": score_data["明细"],
        })

    return sorted(results, key=lambda item: item["总分"], reverse=True)[:3]


def build_ranked_results(top_results=None, candidate_texts=None, top1_reason=None, top1_score=None):
    """统一结构化 Top1~Top3 结果，兼容实时诊断结果与历史记录"""
    ranked_results = []

    if top_results:
        for index, item in enumerate(top_results[:3], 1):
            ranked_results.append({
                "排名": index,
                "原因": item.get("原因", "未知"),
                "总分": safe_to_float(item.get("总分"), None),
                "诊断依据": item.get("诊断依据", {}) or {},
                "建议": item.get("建议", ""),
            })
        return ranked_results

    if candidate_texts:
        for index, item in enumerate(candidate_texts[:3], 1):
            parsed = parse_candidate_result_item(item, rank_hint=index)
            if parsed:
                ranked_results.append(parsed)

    if not ranked_results and top1_reason:
        ranked_results.append({
            "排名": 1,
            "原因": str(top1_reason).strip(),
            "总分": safe_to_float(top1_score, None),
            "诊断依据": {},
            "建议": "",
        })

    return ranked_results


def is_missing_value(value):
    """统一判断空值/占位值"""
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text in {"", "-", "无", "未填写", "未确认", "None", "nan"}


def build_diagnosis_context(
    abnormality="",
    positive_control_normal="",
    negative_control_band="",
    template_amount=None,
    annealing_temp=None,
    cycles=None,
    description="",
    text_clues=None,
    gel_image_path="",
    has_image=None,
):
    """整理诊断可信度模块所需上下文"""
    image_available = bool(has_image) if has_image is not None else bool(str(gel_image_path or "").strip())
    return {
        "实验现象": abnormality,
        "阳性对照是否正常": positive_control_normal,
        "阴性对照是否有带": negative_control_band,
        "模板量": template_amount,
        "退火温度": annealing_temp,
        "循环数": cycles,
        "学生补充描述": description,
        "文本线索": text_clues or [],
        "凝胶图路径": gel_image_path,
        "是否上传图片": image_available,
    }


def count_hit_evidence(detail):
    """统计当前 Top1 的命中证据数量"""
    detail = detail or {}
    evidence_chain = detail.get("证据链", []) or []
    if evidence_chain:
        return len([item for item in evidence_chain if str(item).strip()][:5])

    rule_stats = detail.get("规则命中统计", {}) or {}
    if rule_stats:
        base_hits = int(safe_to_float(rule_stats.get("基础规则"), 0) or 0)
        combo_hits = int(safe_to_float(rule_stats.get("组合规则"), 0) or 0)
        return base_hits + combo_hits

    hit_count = 0
    for key in ["阳性对照", "阴性对照", "模板量范围", "退火温度范围", "循环数范围"]:
        section = detail.get(key, {}) or {}
        if section.get("命中") or safe_to_float(section.get("加分"), 0) > 0:
            hit_count += 1

    text_section = detail.get("文本线索", {}) or {}
    if text_section.get("命中线索"):
        hit_count += 1
    return hit_count


def detect_missing_key_info(context):
    """识别影响判断稳定性的关键信息缺失项"""
    context = context or {}
    missing_items = []

    if is_missing_value(context.get("阳性对照是否正常")):
        missing_items.append("阳性对照结果未填写")
    if is_missing_value(context.get("阴性对照是否有带")):
        missing_items.append("阴性对照结果未填写")
    if is_missing_value(context.get("退火温度")):
        missing_items.append("未提供退火温度或程序设置相关信息")
    if is_missing_value(context.get("模板量")):
        missing_items.append("未提供模板浓度或模板用量相关信息")
    if is_missing_value(context.get("学生补充描述")):
        missing_items.append("未提供学生补充描述")
    if not context.get("是否上传图片"):
        missing_items.append("未上传凝胶图片")

    return missing_items


def compute_confidence_level(ranked_results, detail=None, context=None):
    """基于分差、命中证据和缺失信息给出轻量置信度"""
    ranked_results = ranked_results or []
    detail = detail or {}
    context = context or {}

    if not ranked_results:
        return "未知", "缺少可用的诊断结果，暂无法判断。"

    top1_score = safe_to_float(ranked_results[0].get("总分"), None)
    top2_score = safe_to_float(ranked_results[1].get("总分"), None) if len(ranked_results) > 1 else None
    score_gap = (top1_score - top2_score) if top1_score is not None and top2_score is not None else None

    evidence_hits = count_hit_evidence(detail)
    missing_count = len(detect_missing_key_info(context))

    if score_gap is not None and score_gap >= 12 and evidence_hits >= 3 and missing_count <= 1:
        return "高", f"Top1 相比 Top2 领先 {score_gap:.1f} 分，且已有 {evidence_hits} 项命中证据，关键信息缺失较少。"

    if (
        (score_gap is not None and score_gap <= 4)
        or evidence_hits <= 1
        or missing_count >= 3
    ):
        gap_text = f"Top1 与 Top2 仅相差 {score_gap:.1f} 分" if score_gap is not None else "候选结果分差信息不足"
        return "低", f"{gap_text}，且当前证据或关键信息仍偏少，建议补充更多实验信息后再综合判断。"

    if score_gap is None and not detail:
        return "中", "历史记录缺少完整打分明细，当前按中等置信度展示。"

    gap_text = f"Top1 相比 Top2 领先 {score_gap:.1f} 分" if score_gap is not None else "当前已获取部分判断依据"
    return "中", f"{gap_text}，已有 {evidence_hits} 项主要证据支撑，但仍建议结合补充信息综合判断。"


def build_evidence_summary(top1_reason, detail=None, context=None):
    """将现有打分明细和输入信息整理成适合展示的证据摘要"""
    detail = detail or {}
    context = context or {}
    evidence_chain = _dedupe_keep_order(detail.get("证据链", []) or [])
    if evidence_chain:
        return evidence_chain[:5]
    evidence_points = []

    abnormality = str(context.get("实验现象") or "").strip()
    if abnormality:
        evidence_points.append(f"当前异常现象为“{abnormality}”，与“{top1_reason or '当前 Top1 结果'}”对应规则直接相关。")

    positive_value = str(context.get("阳性对照是否正常") or "").strip()
    positive_detail = detail.get("阳性对照", {}) or {}
    if positive_value and positive_value != "-":
        if positive_value == "否":
            evidence_points.append("阳性对照异常，说明扩增体系或程序设置存在异常的可能性较高。")
        elif positive_detail.get("命中") or safe_to_float(positive_detail.get("加分"), 0) > 0:
            evidence_points.append("阳性对照结果已纳入判断，可帮助区分是体系问题还是样本本身问题。")

    negative_value = str(context.get("阴性对照是否有带") or "").strip()
    negative_detail = detail.get("阴性对照", {}) or {}
    if negative_value and negative_value != "-":
        if negative_value == "是":
            evidence_points.append("阴性对照出现条带，提示存在污染风险，需重点关注体系污染或交叉污染。")
        elif negative_detail.get("命中") or safe_to_float(negative_detail.get("加分"), 0) > 0:
            evidence_points.append("阴性对照未见异常条带，有助于排除明显污染导致的干扰。")

    template_value = context.get("模板量")
    template_detail = detail.get("模板量范围", {}) or {}
    if not is_missing_value(template_value):
        if template_detail.get("命中") or safe_to_float(template_detail.get("加分"), 0) > 0:
            evidence_points.append(f"当前模板量为 {template_value} μL，落在该候选原因重点关注的模板量区间。")
        elif "模板" in str(top1_reason):
            evidence_points.append(f"当前模板量为 {template_value} μL，是判断模板相关异常的重要依据。")

    annealing_value = context.get("退火温度")
    temp_detail = detail.get("退火温度范围", {}) or {}
    if not is_missing_value(annealing_value):
        if temp_detail.get("命中") or safe_to_float(temp_detail.get("加分"), 0) > 0:
            evidence_points.append(f"当前退火温度为 {annealing_value}℃，与该候选原因的温度条件相匹配。")
        elif "退火温度" in str(top1_reason):
            evidence_points.append(f"当前退火温度为 {annealing_value}℃，是判断温度相关问题的重要参考。")

    text_section = detail.get("文本线索", {}) or {}
    hit_clues = text_section.get("命中线索", []) or []
    extracted_clues = text_section.get("抽取线索", []) or []
    context_clues = context.get("文本线索", []) or []
    if hit_clues:
        evidence_points.append(f"学生补充描述中提到“{'、'.join(hit_clues)}”等线索，直接支持当前 Top1 判断。")
    elif extracted_clues:
        evidence_points.append(f"系统从描述中抽取到“{'、'.join(extracted_clues)}”等线索，帮助缩小了候选范围。")
    elif context_clues:
        evidence_points.append(f"当前记录包含“{'、'.join(context_clues)}”等文字线索，可作为诊断的辅助依据。")

    if not evidence_points and str(context.get("学生补充描述") or "").strip():
        evidence_points.append("已提供学生补充描述，系统结合实验参数与文本线索完成了规则匹配。")

    deduped_points = []
    for item in evidence_points:
        if item not in deduped_points:
            deduped_points.append(item)

    return deduped_points[:5]


def render_diagnosis_quality_block(
    top_results=None,
    candidate_texts=None,
    top1_reason="",
    top1_score=None,
    detail=None,
    abnormality="",
    positive_control_normal="",
    negative_control_band="",
    template_amount=None,
    annealing_temp=None,
    cycles=None,
    description="",
    text_clues=None,
    gel_image_path="",
    has_image=None,
    title="诊断可信度解读",
):
    """统一渲染置信度 + 证据摘要 + 缺失信息提示"""
    ranked_results = build_ranked_results(
        top_results=top_results,
        candidate_texts=candidate_texts,
        top1_reason=top1_reason,
        top1_score=top1_score,
    )
    if not ranked_results:
        st.info("暂无可用于展示的诊断可信度信息。")
        return

    top1_result = ranked_results[0]
    detail = detail if detail is not None else (top1_result.get("诊断依据", {}) or {})
    context = build_diagnosis_context(
        abnormality=abnormality,
        positive_control_normal=positive_control_normal,
        negative_control_band=negative_control_band,
        template_amount=template_amount,
        annealing_temp=annealing_temp,
        cycles=cycles,
        description=description,
        text_clues=text_clues,
        gel_image_path=gel_image_path,
        has_image=has_image,
    )

    confidence_level, confidence_reason = compute_confidence_level(ranked_results, detail=detail, context=context)
    evidence_points = build_evidence_summary(top1_result.get("原因", top1_reason), detail=detail, context=context)
    missing_items = detect_missing_key_info(context)

    with st.container(border=True):
        st.markdown(f"**{title}**")
        metric_cols = st.columns(2)
        metric_cols[0].metric("置信度", confidence_level)
        metric_cols[1].markdown(f"**判断说明：**{confidence_reason}")

        st.markdown("**系统主要依据如下：**")
        if evidence_points:
            for point in evidence_points[:5]:
                st.markdown(f"- {point}")
        else:
            st.info("当前可提炼的证据较少，系统主要基于已有规则分值进行排序。")

        if missing_items:
            st.markdown("**为了提高判断准确性，建议补充以下信息：**")
            for item in missing_items:
                st.markdown(f"- {item}")
        else:
            st.success("当前关键信息较完整，判断依据相对充分。")


def load_recent_records(limit=10):
    """读取最近诊断记录（按时间倒序），返回摘要+详情所需字段"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM diagnosis_records
        ORDER BY diagnosis_time DESC, id DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()

    records = []
    for row in rows:
        data = dict(row)
        diagnosis_result = data.get("diagnosis_result", "")

        # 学生补充描述过长时截断，避免摘要区过长
        desc_full = str(data.get("description") or "").strip()
        desc_short = desc_full
        if len(desc_short) > 30:
            desc_short = desc_short[:30] + "..."

        # 历史“抽取线索”如果库里没存，就根据学生描述现算一次（不改库结构）
        text_clues = extract_text_clues(desc_full)
        normalized_info = explain_normalized_case({
            "abnormality": data.get("abnormality"),
            "template_amount": data.get("template_amount"),
            "annealing_temp": data.get("annealing_temp"),
            "cycles": data.get("cycles"),
            "positive_control_normal": data.get("positive_control_normal"),
            "negative_control_band": data.get("negative_control_band"),
            "description": desc_full,
            "text_clues": text_clues,
        })
        normalized_case = normalized_info.get("normalized_case", {})
        rules_v2_eval = {}
        primary_bundle = {
            "results": [],
            "candidate_texts": [],
            "top1_reason": "",
            "top1_score": None,
            "result_text": "",
        }
        try:
            rules_v2_eval = evaluate_rules_v2(normalized_case)
            if rules_v2_eval.get("status") == "ok" and rules_v2_eval.get("top1"):
                primary_bundle = build_primary_diagnosis_from_rules_v2(rules_v2_eval)
        except Exception:
            rules_v2_eval = {}

        top_results = primary_bundle.get("results", []) or []
        if top_results:
            top1_reason = primary_bundle.get("top1_reason", "")
            top1_score = primary_bundle.get("top1_score")
            all_candidates = primary_bundle.get("candidate_texts", [])
        else:
            top1_reason, top1_score = parse_top1_result(diagnosis_result)
            all_candidates = parse_all_candidates(diagnosis_result)

        gel_image_path = data.get("gel_image_path")
        has_image = bool(gel_image_path)

        records.append({
            "id": data.get("id"),
            "提交时间": data.get("diagnosis_time", "-"),
            "实验现象": data.get("abnormality", "-"),
            "模板量": data.get("template_amount", "-"),
            "退火温度": data.get("annealing_temp", "-"),
            "循环数": data.get("cycles", "-"),
            "阳性对照是否正常": data.get("positive_control_normal", "-"),
            "阴性对照是否有带": data.get("negative_control_band", "-"),
            "学生补充描述": desc_full if desc_full else "-",
            "学生补充描述摘要": desc_short if desc_short else "-",
            "抽取到的文本线索": text_clues,
            "Top1 原因": top1_reason,
            "Top1 分数": top1_score,
            "候选原因列表": all_candidates,
            "系统结果列表": top_results,
            "rules_v2_eval": rules_v2_eval,
            "教师最终原因": data.get("teacher_final_cause") if data.get("teacher_final_cause") else "未确认",
            "教师备注": data.get("teacher_note") if data.get("teacher_note") else "-",
            "教师确认时间": data.get("teacher_confirm_time") if data.get("teacher_confirm_time") else "-",
            "凝胶图路径": gel_image_path if gel_image_path else "",
            "凝胶图": "有图" if has_image else "无图",
            "normalized_case": normalized_case,
        })

    return records


def load_record_by_id(record_id):
    """按 id 读取单条记录（用于导出案例摘要）"""
    if not record_id:
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM diagnosis_records WHERE id = ?", (record_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def normalize_report_value(value, empty_text="未填写"):
    """统一格式化复盘报告字段值。"""
    if isinstance(value, list):
        cleaned_items = [str(item).strip() for item in value if not is_missing_value(item)]
        return "、".join(cleaned_items) if cleaned_items else empty_text
    if is_missing_value(value):
        return empty_text
    return str(value).strip()


def append_report_section(lines, title, body_lines):
    """按统一格式追加报告区块。"""
    valid_lines = [str(item).strip() for item in body_lines if str(item).strip()]
    if not valid_lines:
        return
    if lines:
        lines.append("")
    lines.append(title)
    lines.extend(valid_lines)


def normalize_reason_for_report(reason):
    """轻量归一化原因标签，便于报告中的一致性判断。"""
    text = str(reason or "").strip().lower().replace(" ", "")
    if not text:
        return ""

    alias_groups = {
        "模板量不足": ["模板量不足", "模板浓度低", "模板少", "模板过低"],
        "污染": ["污染", "气溶胶污染", "阴性对照污染"],
        "引物问题": ["引物问题", "引物失效", "引物设计问题"],
        "PCR体系问题": ["pcr体系问题", "体系漏加", "反应体系配置错误", "pcr体系漏加试剂"],
        "退火温度过高": ["退火温度过高", "退火温度偏高"],
        "退火温度过低": ["退火温度过低", "退火温度偏低"],
        "退火温度问题": ["退火温度问题"],
    }
    for canonical, aliases in alias_groups.items():
        for alias in aliases:
            if alias in text:
                return canonical
    return text


def build_report_consistency_status(teacher_final_cause, ranked_results):
    """为复盘报告生成一致性状态。"""
    teacher_reason = normalize_reason_for_report(teacher_final_cause)
    if not teacher_reason:
        return "无法比较"

    ranked_results = ranked_results or []
    normalized_candidates = []
    for item in ranked_results[:3]:
        normalized = normalize_reason_for_report(item.get("原因", ""))
        if normalized:
            normalized_candidates.append(normalized)

    if not normalized_candidates:
        return "无法比较"
    if teacher_reason == normalized_candidates[0]:
        return "一致"
    if teacher_reason in normalized_candidates[1:]:
        return "Top3命中但Top1不一致"
    return "未命中"


def build_feedback_loop_summary_for_report(status_text):
    """生成报告中的闭环结论语句。"""
    if status_text == "一致":
        return "系统首选判断与教师最终确认一致，可作为后续讲解参考。"
    if status_text == "Top3命中但Top1不一致":
        return "系统候选结果已覆盖真实原因，但排序仍有优化空间，可作为纠偏案例参考。"
    if status_text == "未命中":
        return "系统候选结果未覆盖教师最终确认原因，建议后续补充相关规则。"
    return "该案例尚未完成有效教师确认，当前报告以系统诊断结果为主。"


def get_action_advice_by_reason(reason):
    """基于 Top1 原因给出轻量模板化建议。"""
    normalized_reason = normalize_reason_for_report(reason)
    if normalized_reason == "模板量不足":
        return "建议补查模板浓度、完整性及加样量，并复核模板保存条件。"
    if normalized_reason == "污染":
        return "建议重点检查阴性对照、操作环境、移液流程及分区操作是否规范。"
    if normalized_reason == "引物问题":
        return "建议复核引物设计、退火位点匹配、保存条件及是否存在失效情况。"
    if normalized_reason == "PCR体系问题":
        return "建议复核 PCR 体系配制、关键试剂是否漏加，以及加样顺序和配比是否正确。"
    if normalized_reason in {"退火温度过高", "退火温度过低", "退火温度问题"}:
        return "建议复核退火温度设定与 PCR 程序参数，并结合梯度退火实验进一步确认。"
    return "建议结合对照结果、关键参数和实验记录，再次核对可能的异常来源。"


def build_review_suggestions(top1_reason, missing_items=None, top1_suggestion="", confidence_level=""):
    """生成报告中的复盘建议。"""
    suggestions = []

    top1_suggestion = normalize_report_value(top1_suggestion, "")
    if top1_suggestion:
        suggestions.append(f"系统建议：{top1_suggestion}")

    base_advice = get_action_advice_by_reason(top1_reason)
    if base_advice:
        suggestions.append(base_advice)

    missing_items = missing_items or []
    if missing_items:
        missing_text = "；".join(missing_items[:3])
        suggestions.append(f"当前仍建议优先补充以下信息后再复核：{missing_text}。")
    elif confidence_level == "高":
        suggestions.append("当前关键信息相对完整，可作为课堂讨论示例。")

    deduped = []
    for item in suggestions:
        if item and item not in deduped:
            deduped.append(item)
    return deduped[:3]


def build_case_review_report(payload):
    """生成规范化复盘报告文本。"""
    payload = payload or {}
    record_id = payload.get("record_id")
    db_record = load_record_by_id(record_id) or {}

    submit_time = db_record.get("diagnosis_time") or payload.get("submit_time")
    abnormality = db_record.get("abnormality") or payload.get("abnormality")
    template_amount = db_record.get("template_amount", payload.get("template_amount"))
    annealing_temp = db_record.get("annealing_temp", payload.get("annealing_temp"))
    cycles = db_record.get("cycles", payload.get("cycles"))
    positive_control = db_record.get("positive_control_normal") or payload.get("positive_control_normal")
    negative_control = db_record.get("negative_control_band") or payload.get("negative_control_band")
    description = db_record.get("description") or payload.get("description")
    image_path = db_record.get("gel_image_path") or payload.get("gel_image_path", "")
    has_image = bool(str(image_path or "").strip())

    teacher_final = db_record.get("teacher_final_cause")
    teacher_note = db_record.get("teacher_note")
    teacher_confirm_time = db_record.get("teacher_confirm_time")
    current_status = "已确认" if not is_missing_value(teacher_final) else "未确认"

    diagnosis_result = db_record.get("diagnosis_result", "")
    text_clues = payload.get("text_clues")
    if not text_clues and str(description or "").strip():
        text_clues = extract_text_clues(description)
    text_clues = text_clues or []

    rules_v2_eval = {}
    primary_bundle = {
        "results": payload.get("results", []) or [],
        "candidate_texts": [],
        "top1_reason": "",
        "top1_score": None,
        "result_text": "",
    }
    try:
        normalized_case = build_normalized_case({
            "abnormality": abnormality,
            "template_amount": template_amount,
            "annealing_temp": annealing_temp,
            "cycles": cycles,
            "positive_control_normal": positive_control,
            "negative_control_band": negative_control,
            "description": description,
            "text_clues": text_clues,
        })
        rules_v2_eval = evaluate_rules_v2(normalized_case)
        if rules_v2_eval.get("status") == "ok" and rules_v2_eval.get("top1"):
            primary_bundle = build_primary_diagnosis_from_rules_v2(rules_v2_eval)
    except Exception:
        rules_v2_eval = {}

    top_results = primary_bundle.get("results", []) or []
    candidate_texts = primary_bundle.get("candidate_texts", []) or parse_all_candidates(diagnosis_result)
    ranked_results = build_ranked_results(top_results=top_results, candidate_texts=candidate_texts)
    if not ranked_results:
        top1_reason, top1_score = parse_top1_result(diagnosis_result)
        ranked_results = build_ranked_results(top1_reason=top1_reason, top1_score=top1_score)

    top1_result = ranked_results[0] if ranked_results else {}
    top1_reason = top1_result.get("原因", "未识别")
    top1_detail = top1_result.get("诊断依据", {}) or {}
    top1_suggestion = top1_result.get("建议", "")

    context = build_diagnosis_context(
        abnormality=abnormality,
        positive_control_normal=positive_control,
        negative_control_band=negative_control,
        template_amount=template_amount,
        annealing_temp=annealing_temp,
        cycles=cycles,
        description=description or "",
        text_clues=text_clues,
        gel_image_path=image_path,
        has_image=has_image,
    )
    confidence_level, confidence_reason = compute_confidence_level(
        ranked_results,
        detail=top1_detail,
        context=context,
    )
    evidence_points = build_evidence_summary(top1_reason, detail=top1_detail, context=context)
    missing_items = detect_missing_key_info(context)
    consistency_status = build_report_consistency_status(teacher_final, ranked_results)
    feedback_summary = build_feedback_loop_summary_for_report(consistency_status)
    review_suggestions = build_review_suggestions(
        top1_reason,
        missing_items=missing_items,
        top1_suggestion=top1_suggestion,
        confidence_level=confidence_level,
    )

    lines = ["《PCR-电泳异常记录报告》"]

    append_report_section(
        lines,
        "一、报告标题区",
        [
            f"案例编号：{normalize_report_value(record_id, '未记录')}",
            f"提交时间：{normalize_report_value(submit_time, '未记录')}",
            f"是否有图片：{'有图片' if has_image else '无图片'}",
            f"当前状态：{current_status}",
        ],
    )

    append_report_section(
        lines,
        "二、基本实验信息",
        [
            f"异常现象：{normalize_report_value(abnormality)}",
            f"阳性对照结果：{normalize_report_value(positive_control)}",
            f"阴性对照结果：{normalize_report_value(negative_control)}",
            f"模板相关信息：{normalize_report_value(template_amount)}",
            f"退火温度 / 程序设置信息：退火温度 {normalize_report_value(annealing_temp)}；循环数 {normalize_report_value(cycles)}",
            f"学生补充描述：{normalize_report_value(description)}",
            f"文本线索：{normalize_report_value(text_clues)}",
        ],
    )

    diagnosis_lines = [
        f"Top1 原因：{normalize_report_value(ranked_results[0].get('原因') if len(ranked_results) > 0 else '', '未识别')}",
        f"Top2 原因：{normalize_report_value(ranked_results[1].get('原因') if len(ranked_results) > 1 else '', '未识别')}",
        f"Top3 原因：{normalize_report_value(ranked_results[2].get('原因') if len(ranked_results) > 2 else '', '未识别')}",
    ]
    if confidence_level != "未知" or confidence_reason:
        diagnosis_lines.append(f"Top1 置信度：{confidence_level}")
    if confidence_reason:
        diagnosis_lines.append(f"置信度说明：{confidence_reason}")
    if evidence_points:
        diagnosis_lines.append("证据摘要：")
        diagnosis_lines.extend([f"- {point}" for point in evidence_points[:5]])
    if missing_items:
        diagnosis_lines.append("缺失信息提示：")
        diagnosis_lines.extend([f"- {item}" for item in missing_items])
    else:
        diagnosis_lines.append("缺失信息提示：当前关键信息较完整，判断依据相对充分。")
    append_report_section(lines, "三、系统诊断结果", diagnosis_lines)

    evidence_section_lines = []
    if evidence_points:
        evidence_section_lines.append("系统主要依据如下：")
        evidence_section_lines.extend([f"- {point}" for point in evidence_points[:5]])
    elif top1_detail:
        evidence_section_lines.append(
            "当前历史记录未生成独立证据摘要，系统主要依据为规则匹配得分、对照结果与关键参数命中情况。"
        )
    else:
        evidence_section_lines.append("当前记录未保存完整打分明细，暂无更详细的关键证据可展示。")
    append_report_section(lines, "四、诊断依据 / 关键证据", evidence_section_lines)

    teacher_review_lines = [
        f"教师最终确认原因：{normalize_report_value(teacher_final, '未确认')}",
        f"教师备注：{normalize_report_value(teacher_note)}",
    ]
    if not is_missing_value(teacher_confirm_time):
        teacher_review_lines.append(f"教师确认时间：{normalize_report_value(teacher_confirm_time)}")
    if current_status == "未确认":
        teacher_review_lines.append("该案例尚未完成教师确认。")
    else:
        teacher_review_lines.append(f"一致性状态：{consistency_status}")
        teacher_review_lines.append(f"对比说明：{feedback_summary}")
    append_report_section(lines, "五、教师复核结果", teacher_review_lines)

    append_report_section(
        lines,
        "六、改进建议 / 后续建议",
        [f"- {item}" for item in review_suggestions] if review_suggestions else ["- 建议结合更多实验记录继续复核当前案例。"],
    )

    append_report_section(
        lines,
        "七、报告尾部说明",
        [
            "本报告由系统自动生成，供实验教学和教师确认参考。",
            "最终结论以教师确认结果为准；若尚未确认，则当前结论仅供课堂分析使用。",
        ],
    )

    return "\n".join(lines)


def _build_case_summary_legacy(payload):
    """
    生成结构化案例摘要文本（txt内容）
    优先使用数据库已保存值，缺失时回退到当前内存 payload
    """
    record_id = payload.get("record_id")
    db_record = load_record_by_id(record_id) or {}

    # 诊断输入参数
    submit_time = db_record.get("diagnosis_time") or payload.get("submit_time", "-")
    abnormality = db_record.get("abnormality") or payload.get("abnormality", "-")
    template_amount = db_record.get("template_amount", payload.get("template_amount", "-"))
    annealing_temp = db_record.get("annealing_temp", payload.get("annealing_temp", "-"))
    cycles = db_record.get("cycles", payload.get("cycles", "-"))
    positive_control = db_record.get("positive_control_normal") or payload.get("positive_control_normal", "-")
    negative_control = db_record.get("negative_control_band") or payload.get("negative_control_band", "-")
    description = db_record.get("description") or payload.get("description", "-")

    # 文本线索、Top3
    text_clues = payload.get("text_clues", [])
    top_results = payload.get("results", [])
    top_lines = []
    for i, item in enumerate(top_results, 1):
        top_lines.append(f"{i}. {item.get('原因', '未知')}（总分: {item.get('总分', '-')})")
    top_lines_text = "\n".join(top_lines) if top_lines else "无"

    # Top1 主要依据（简要）
    top1_basis = "无"
    if top_results:
        detail = top_results[0].get("诊断依据", {})
        top1_basis = (
            f"基础分{detail.get('基础分', 0)}；"
            f"阳性对照加分{detail.get('阳性对照', {}).get('加分', 0)}；"
            f"阴性对照加分{detail.get('阴性对照', {}).get('加分', 0)}；"
            f"模板量加分{detail.get('模板量范围', {}).get('加分', 0)}；"
            f"退火温度加分{detail.get('退火温度范围', {}).get('加分', 0)}；"
            f"文本线索加分{detail.get('文本线索', {}).get('加分', 0)}"
        )

    # 教师确认信息
    teacher_final = db_record.get("teacher_final_cause") or "未确认"
    teacher_note = db_record.get("teacher_note") or "无"

    # 图片信息
    image_path = db_record.get("gel_image_path") or payload.get("gel_image_path", "")
    has_image = "是" if image_path else "否"

    lines = [
        "【PCR异常诊断案例摘要】",
        f"记录ID：{record_id if record_id else '无'}",
        f"提交时间：{submit_time}",
        f"实验现象：{abnormality}",
        f"模板量：{template_amount}",
        f"退火温度：{annealing_temp}",
        f"循环数：{cycles}",
        f"阳性对照是否正常：{positive_control}",
        f"阴性对照是否有带：{negative_control}",
        f"学生补充描述：{description if description else '无'}",
        f"抽取到的文本线索：{'、'.join(text_clues) if text_clues else '无'}",
        "Top 3 诊断结果：",
        top_lines_text,
        f"Top1主要诊断依据：{top1_basis}",
        f"教师最终原因：{teacher_final}",
        f"教师备注：{teacher_note}",
        f"是否上传图片：{has_image}",
    ]
    return "\n".join(lines)


def build_case_summary(payload):
    """兼容旧调用入口：输出规范化复盘报告文本。"""
    return build_case_review_report(payload)


# ---------- 规则库编辑相关函数 ----------
def check_rule_duplicate(new_rule, existing_df):
    """
    检查新规则是否与现有规则完全重复。
    重复定义：abnormality 和 cause 完全相同。
    返回：(is_duplicate, 重复的行索引列表)
    """
    if existing_df.empty:
        return False, []
    new_abn = str(new_rule.get("abnormality", "")).strip()
    new_cause = str(new_rule.get("cause", "")).strip()
    mask = (existing_df["abnormality"].astype(str).str.strip() == new_abn) & \
           (existing_df["cause"].astype(str).str.strip() == new_cause)
    duplicate_indices = existing_df[mask].index.tolist()
    return len(duplicate_indices) > 0, duplicate_indices


def check_rule_conflict(new_rule, existing_df):
    """
    检查新规则与现有规则是否存在潜在冲突。
    冲突定义：同一 abnormality 下，新规则的数值范围与已有规则重叠，且总分差异较大（>10分）。
    返回：冲突描述列表（每项为字符串）。
    """
    conflicts = []
    new_abn = str(new_rule.get("abnormality", "")).strip()
    same_abn_df = existing_df[existing_df["abnormality"].astype(str).str.strip() == new_abn]
    if same_abn_df.empty:
        return conflicts

    # 解析新规则的数值边界（any 表示无限制）
    def parse_range(min_val, max_val):
        min_v = safe_to_float(min_val, None)
        max_v = safe_to_float(max_val, None)
        return min_v, max_v

    new_min_tpl, new_max_tpl = parse_range(new_rule.get("min_template"), new_rule.get("max_template"))
    new_min_temp, new_max_temp = parse_range(new_rule.get("min_temp"), new_rule.get("max_temp"))
    new_score = safe_to_float(new_rule.get("score"), 0)

    for idx, row in same_abn_df.iterrows():
        exist_min_tpl, exist_max_tpl = parse_range(row.get("min_template"), row.get("max_template"))
        exist_min_temp, exist_max_temp = parse_range(row.get("min_temp"), row.get("max_temp"))
        exist_score = safe_to_float(row.get("score"), 0)

        # 检查模板量范围重叠
        tpl_overlap = False
        if new_min_tpl is None or exist_min_tpl is None:
            tpl_overlap = True
        else:
            if new_max_tpl is not None and exist_max_tpl is not None:
                tpl_overlap = not (new_max_tpl < exist_min_tpl or exist_max_tpl < new_min_tpl)
            else:
                tpl_overlap = True

        # 检查退火温度范围重叠
        temp_overlap = False
        if new_min_temp is None or exist_min_temp is None:
            temp_overlap = True
        else:
            if new_max_temp is not None and exist_max_temp is not None:
                temp_overlap = not (new_max_temp < exist_min_temp or exist_max_temp < new_min_temp)
            else:
                temp_overlap = True

        if tpl_overlap and temp_overlap and abs(new_score - exist_score) > 10:
            conflicts.append(
                f"与行 {idx} 的规则（原因：{row.get('cause', '')}，"
                f"模板量范围 {row.get('min_template')}~{row.get('max_template')}，"
                f"温度范围 {row.get('min_temp')}~{row.get('max_temp')}，"
                f"分数 {exist_score}）存在重叠且分数差异较大，可能造成诊断歧义。"
            )

    return conflicts


def append_rule_to_csv(new_rule_dict, rules_path=RULES_PATH):
    """
    将新规则追加写入 CSV 文件。
    返回：(是否成功, 消息)
    """
    try:
        # 读取原有数据以保留列顺序；rules.csv 可能由 Excel 以 GBK/GB18030 保存
        if os.path.exists(rules_path):
            df_existing = read_csv_with_fallback(rules_path)
            target_columns = list(df_existing.columns) if len(df_existing.columns) else list(REQUIRED_RULE_COLUMNS)
        else:
            df_existing = pd.DataFrame(columns=REQUIRED_RULE_COLUMNS)
            target_columns = list(REQUIRED_RULE_COLUMNS)

        normalized_rule = {column: new_rule_dict.get(column, "") for column in target_columns}
        new_row_df = pd.DataFrame([normalized_rule], columns=target_columns)
        updated_df = pd.concat([df_existing, new_row_df], ignore_index=True)

        # 写回文件（统一为 utf-8-sig，便于 Excel 打开）
        updated_df.to_csv(rules_path, index=False, encoding="utf-8-sig")
        return True, "新规则已成功添加。"
    except Exception as e:
        return False, f"写入规则文件失败：{str(e)[:120]}"
