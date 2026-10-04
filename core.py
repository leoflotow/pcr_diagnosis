# -*- coding: utf-8 -*-
"""
生物实验智析助手 - Streamlit 应用
功能：根据实验现象和参数，诊断PCR电泳异常原因
"""

import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
from branding import PRODUCT_NAME, PRODUCT_SUBTITLE, CURRENT_MODULE
from ui_design import apply_design_system
import pandas as pd
import sqlite3
import os
import re
import json
import uuid
import hashlib
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from datetime import datetime
from diagnosis_normalization import build_normalized_case, explain_normalized_case
from diagnosis_rule_engine_v2 import evaluate_rules_v2
from navigation_state import get_home_page
import case_storage
from evidence_support import confirmed_description, normalize_cause_label, parse_json, rules_version, template_mass_ng, positive_number

try:
    # 使用兼容 OpenAI SDK 的方式调用 BigModel / GLM
    from openai import OpenAI
except:
    OpenAI = None

# 数据库路径
DB_PATH = os.getenv("PCR_DIAGNOSIS_DB_PATH", "data/app.db")

# 规则文件路径
RULES_PATH = "rules.csv"
LEGACY_RULES_PATH = "rules_v2.csv"
# 上传图片保存目录
UPLOAD_DIR = os.getenv("PCR_DIAGNOSIS_UPLOAD_DIR", "uploads")
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
BIGMODEL_TIMEOUT_SECONDS = 8
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
            page_title=PRODUCT_NAME if page_title == PRODUCT_NAME else f"{PRODUCT_NAME}｜{page_title}",
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
    if name in {"TEACHER_ACCESS_CODE", "DEV_ACCESS_CODE"} and is_demo_environment():
        return "demo-teacher" if name == "TEACHER_ACCESS_CODE" else "demo-dev"
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
    """所有角色共享同一视觉体系，theme 保留原调用兼容性。"""
    apply_design_system()




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
        allowed_values = set(ABNORMALITY_OPTIONS) | {value for value in normalized_options if value} | {"any"}
        for abn in ABNORMALITY_OPTIONS:
            normalized_abn = build_normalized_case({"abnormality": abn}).get("abnormality")
            if int(((abn_series == abn) | (abn_series == normalized_abn)).sum()) == 0:
                issues.append(f"实验现象“{abn}”缺少规则")

        # 可选提示：发现页面之外的 abnormality 值（不算硬错误）
        extra_values = sorted(set([x for x in abn_series if x and x not in allowed_values]))
        if extra_values:
            warnings.append(f"发现未在页面选项中的 abnormality：{', '.join(extra_values)}")

    return {"ok": len(issues) == 0, "issues": issues, "warnings": warnings}


def is_demo_environment():
    from pathlib import Path
    root = Path(__file__).resolve().parent / "data" / "demo"
    return (os.getenv("PCR_DIAGNOSIS_DEMO_MODE") == "1"
            and Path(DB_PATH).resolve() == root / "demo.db"
            and Path(UPLOAD_DIR).resolve() == root / "uploads")


def clear_history_records():
    """
    清空历史诊断记录（仅清数据，不删库、不删表结构）
    返回: (是否成功, 提示信息)
    """
    if not is_demo_environment():
        return False, "课堂数据库受保护。请用 demo_runner.py 启动独立演示后再恢复模拟案例。"
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 删除前先统计总数（不要依赖 rowcount）
        cursor.execute("SELECT COUNT(*) FROM diagnosis_records")
        total_before = int(cursor.fetchone()[0] or 0)
        if cursor.execute("SELECT COUNT(*) FROM diagnosis_records WHERE coalesce(data_origin,'') NOT IN ('模拟演示','规则回归')").fetchone()[0]:
            conn.close()
            return False, "演示库存在非模拟记录，已停止清理。"

        cursor.execute("DELETE FROM diagnosis_records")
        cursor.execute("DELETE FROM teacher_review_history")
        cursor.execute("DELETE FROM student_revision_history")
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
    if not is_demo_environment():
        return False, "课堂上传目录受保护；仅允许清理独立演示目录。"
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
    case_storage.prepare_database(DB_PATH)
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
            teacher_confirm_time TEXT,
            followup_json TEXT,
            student_initial_hypothesis TEXT,
            student_access_hash TEXT,
            student_revised_cause TEXT,
            student_revision_reason TEXT,
            student_revision_time TEXT
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
    if "followup_json" not in existing_cols:
        cursor.execute("ALTER TABLE diagnosis_records ADD COLUMN followup_json TEXT")
    for column in (
        "student_initial_hypothesis", "student_access_hash", "student_revised_cause",
        "student_revision_reason", "student_revision_time",
    ):
        if column not in existing_cols:
            cursor.execute(f"ALTER TABLE diagnosis_records ADD COLUMN {column} TEXT")

    case_storage.migrate(conn)
    conn.commit()
    conn.close()


def save_diagnosis_record(abnormality, template_amount, annealing_temp, cycles,
                          positive_control_normal, negative_control_band,
                          description, diagnosis_result, gel_image_path=None,
                          student_initial_hypothesis=None, student_access_code=None,
                          initial_results=None, raw_case=None, evidence=None):
    return case_storage.save_record(
        DB_PATH, abnormality, template_amount, annealing_temp, cycles,
        positive_control_normal, negative_control_band, description, diagnosis_result,
        gel_image_path, student_initial_hypothesis, student_access_code,
        initial_results, raw_case, evidence,
    )



def save_teacher_confirmation(record_id, teacher_final_cause, teacher_note,
                              evidence_level="经验复核", verification_feedback="", expected_version=None, rubric=None, data_origin=None):
    """每次复核生成版本，保留之前的结论和对应的学生修订。"""
    return case_storage.save_review(DB_PATH, record_id, teacher_final_cause, teacher_note,
                                   evidence_level, verification_feedback, expected_version, rubric, data_origin)



def save_followup_reassessment(record_id, diagnosis_result, positive_control_normal,
                               negative_control_band, followup_data):
    return case_storage.save_reassessment(DB_PATH, record_id, diagnosis_result,
                                         positive_control_normal, negative_control_band, followup_data)



def parse_followup_data(value):
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def load_student_record(access_code):
    """凭私有查询码读取案例；数据库只保存查询码摘要。"""
    code = str(access_code or "").strip()
    if not code:
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM diagnosis_records WHERE student_access_hash = ?",
            (hashlib.sha256(code.encode("utf-8")).hexdigest(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_student_revision(record_id, access_code, revised_cause, revision_reason):
    return case_storage.save_revision(DB_PATH, record_id, access_code, revised_cause, revision_reason)


def save_verification_plan(record_id, access_code, plan):
    return case_storage.save_verification_plan(DB_PATH, record_id, access_code, plan)



def validate_uploaded_image(uploaded_file):
    """预览与保存共用图片检查，避免损坏文件中断页面。"""
    if uploaded_file is None:
        return None
    try:
        data = uploaded_file.getbuffer()
        if len(data) > 10 * 1024 * 1024:
            return "图片超过 10 MB，请缩小后再上传。"
        with Image.open(BytesIO(data)) as picture:
            if picture.format not in {"PNG", "JPEG"}:
                return "请上传有效的 PNG 或 JPG 图片。"
            picture.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return "图片无法读取或文件已损坏，请重新导出为 PNG 或 JPG 后上传。"
    return None


def save_uploaded_image(uploaded_file):
    """
    保存上传图片到 uploads 目录。
    返回: (保存路径或None, 错误信息或None)
    """
    if uploaded_file is None:
        return None, None
    error = validate_uploaded_image(uploaded_file)
    if error:
        return None, error

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


def filter_confirmed_description(description):
    """只保留明确的肯定事实，处理否定、疑问及中英文正常描述。"""
    return confirmed_description(description)



def extract_text_clues(description):
    """
    从学生补充描述中提取简单文本线索（关键词规则法）
    这是一个“伪 AI 抽取器”，用于先打通自由文本参与诊断的链路
    """
    text = filter_confirmed_description(description).lower()
    if not text:
        return []

    # 每类线索对应一组关键词（命中任意一个即可）
    clue_rules = {
        "污染": ["污染", "contam"],
        "模板量不足": ["模板量不足", "模板少", "模板浓度低", "模板太少"],
        "引物问题": ["引物问题", "引物失效", "引物降解", "primer degradation", "primer mismatch", "primer failure"],
        "PCR体系问题": ["体系漏加", "pcr体系问题", "体系问题", "漏加试剂", "漏加"],
        "退火温度问题": ["退火温度问题", "退火温度过高", "退火温度过低", "退火高", "退火低"],
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
        text = filter_confirmed_description(description).strip()
        if not text:
            debug["fail_reason"] = "描述中没有可确认的事实线索"
            return [], debug
        debug["bigmodel_called"] = True

        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=BIGMODEL_TIMEOUT_SECONDS,
            max_retries=0,
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
                        "只提取明确观察或核实的事实，不把猜测、提问、否定陈述或模型推断当成证据。"
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

    # 3. 后备规则仅对明确匹配的条件加分；any 不构成证据。
    rule_positive = normalize_yes_no(rule.get('positive_control_normal', 'any'))
    user_positive = normalize_yes_no(positive_control_normal)
    positive_hit = rule_positive != "any" and rule_positive == user_positive
    positive_add = 10 if positive_hit else 0
    score += positive_add

    # 4. 阴性对照
    rule_negative = normalize_yes_no(rule.get('negative_control_band', 'any'))
    user_negative = normalize_yes_no(negative_control_band)
    negative_hit = rule_negative != "any" and rule_negative == user_negative
    negative_add = 10 if negative_hit else 0
    score += negative_add

    # 5. 模板量在范围内加分
    # 加入体积不是 DNA 输入量；旧表的体积阈值不再作为模板量证据。
    template_hit = False
    template_add = 8 if template_hit else 0
    score += template_add

    # 6. 退火温度在范围内加分
    # 绝对温度需结合引物 Tm 与酶说明，旧表阈值不用于定性。
    temp_hit = False
    temp_add = 8 if temp_hit else 0
    score += temp_add

    # 7. 循环数在范围内加分（保留现有字段能力）
    cycles_hit = False
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
             positive_control_normal, negative_control_band, description="",
             extra_text_hints=None, negative_control_detail=None, band_pattern=None,
             positive_control_detail=None, experiment_parameters=None, confirmed_text_hints=None):
    """
    诊断函数：根据输入的实验参数，返回可能的异常原因
    """
    # 从学生描述中抽取文本线索：优先 BigModel / GLM，失败回退本地关键词规则
    if confirmed_text_hints is None:
        text_clues, clue_source, api_debug = extract_text_clues_with_fallback(description)
    else:
        text_clues, clue_source, api_debug = list(confirmed_text_hints), "学生确认的事实线索", {}
    api_debug["normalized_case"] = build_normalized_case({
        **(experiment_parameters or {}),
        "abnormality": abnormality,
        "template_amount": template_amount,
        "annealing_temp": annealing_temp,
        "cycles": cycles,
        "positive_control_normal": positive_control_detail or positive_control_normal,
        "negative_control_band": negative_control_detail or negative_control_band,
        "description": description,
        "text_clues": list(text_clues) + list(extra_text_hints or []),
        "band_pattern": band_pattern,
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
    experiment_parameters=None,
):
    """整理诊断可信度模块所需上下文"""
    image_available = bool(has_image) if has_image is not None else bool(str(gel_image_path or "").strip())
    return {
        "实验资料": experiment_parameters or {},
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

    unknown = {"", "-", "未观察", "未设置", "无法确认", "unknown", "None", "未填写"}
    for field, label in [("阳性对照是否正常", "阳性对照"), ("阴性对照是否有带", "阴性对照")]:
        if str(context.get(field) or "") in unknown:
            missing_items.append(f"{label}结果尚未确认；请核对原始泳道记录")
    parameters = context.get("实验资料", {})
    reason = context.get("候选原因", "")
    if "模板" in reason:
        if not positive_number(parameters.get("template_concentration")):
            missing_items.append("请补充模板浓度（ng/μL），不能只凭加入体积判断输入量")
        if not positive_number(parameters.get("reaction_volume")):
            missing_items.append("请补充反应总体积（μL）和模板类型")
    if "退火" in reason and not positive_number(parameters.get("recommended_temp")):
        missing_items.append("请补充该引物及聚合酶对应的推荐退火温度")
    # 图片和自由描述是可选复核资料，不作为通用置信度扣分项。

    return missing_items


def compute_confidence_level(ranked_results, detail=None, context=None):
    """基于分差、命中证据和缺失信息给出轻量置信度"""
    ranked_results = ranked_results or []
    detail = detail or {}
    context = context or {}

    if not ranked_results:
        return "未知", "缺少可用的诊断结果，暂无法判断。"

    top1_reason = str(ranked_results[0].get("原因") or "")
    if any(word in top1_reason for word in ("待核查", "待区分", "需核对", "原因待", "记录矛盾", "对照失败", "对照异常")):
        return "低", "当前结果是待核查的现象归类或记录矛盾，需补证后再判断具体原因。"

    top1_score = safe_to_float(ranked_results[0].get("总分"), None)
    top2_score = safe_to_float(ranked_results[1].get("总分"), None) if len(ranked_results) > 1 else None
    score_gap = (top1_score - top2_score) if top1_score is not None and top2_score is not None else None

    evidence_hits = count_hit_evidence(detail)
    missing_count = len(detect_missing_key_info({**context, "候选原因": top1_reason}))

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
        return "中", "历史记录缺少完整打分明细，当前按中等证据支持程度展示。"

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
            evidence_points.append("阳性对照异常；需先区分完全无带与弱带，再检查阳性模板、反应体系和程序。")
        elif positive_detail.get("命中") or safe_to_float(positive_detail.get("加分"), 0) > 0:
            evidence_points.append("阳性对照结果已纳入判断，可帮助区分是体系问题还是样本本身问题。")

    negative_value = str(context.get("阴性对照是否有带") or "").strip()
    negative_detail = detail.get("阴性对照", {}) or {}
    if negative_value and negative_value != "-":
        if negative_value == "是":
            evidence_points.append("阴性对照有带；需比较条带与目标片段的位置，区分目标大小带与短片段伪产物。")
        elif negative_detail.get("命中") or safe_to_float(negative_detail.get("加分"), 0) > 0:
            evidence_points.append("本次阴性对照未见条带，可作为判断背景扩增的对照信息。")

    template_value = context.get("模板量")
    if not is_missing_value(template_value):
        evidence_points.append(f"模板加入体积为 {template_value} μL；单凭体积不能判断 DNA 输入量是否过高或过低。")

    annealing_value = context.get("退火温度")
    temp_detail = detail.get("退火温度范围", {}) or {}
    if not is_missing_value(annealing_value):
        if temp_detail.get("命中") or safe_to_float(temp_detail.get("加分"), 0) > 0:
            evidence_points.append(f"当前退火温度为 {annealing_value}℃；温度高低应与该引物及聚合酶推荐条件比较。")
        elif "退火温度" in str(top1_reason):
            evidence_points.append(f"当前退火温度为 {annealing_value}℃，仍需与推荐条件比较后才能判断偏高或偏低。")

    text_section = detail.get("文本线索", {}) or {}
    hit_clues = text_section.get("命中线索", []) or []
    extracted_clues = text_section.get("抽取线索", []) or []
    context_clues = context.get("文本线索", []) or []
    if hit_clues:
        evidence_points.append(f"描述中提到“{'、'.join(hit_clues)}”等线索，仍需结合实验记录核实。")
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
    experiment_parameters=None,
    title="诊断证据支持解读",
):
    """统一渲染置信度 + 证据摘要 + 缺失信息提示"""
    ranked_results = build_ranked_results(
        top_results=top_results,
        candidate_texts=candidate_texts,
        top1_reason=top1_reason,
        top1_score=top1_score,
    )
    if not ranked_results:
        st.info("暂无可用于展示的证据支持信息。")
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
        experiment_parameters=experiment_parameters,
    )

    confidence_level, confidence_reason = compute_confidence_level(ranked_results, detail=detail, context=context)
    evidence_points = build_evidence_summary(top1_result.get("原因", top1_reason), detail=detail, context=context)
    missing_items = detect_missing_key_info({**context, "候选原因": top1_result.get("原因", top1_reason)})

    with st.container(border=True):
        st.markdown(f"**{title}**")
        metric_cols = st.columns(2)
        metric_cols[0].metric("证据支持程度", confidence_level)
        metric_cols[1].markdown(f"**判断说明**\n\n{confidence_reason}")

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
            st.success("当前未发现本候选要求的关键字段缺项，仍需结合实际实验复核。")


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
        followup_data = parse_followup_data(data.get("followup_json"))

        # 学生补充描述过长时截断，避免摘要区过长
        desc_full = str(data.get("description") or "").strip()
        desc_short = desc_full
        if len(desc_short) > 30:
            desc_short = desc_short[:30] + "..."

        snapshot = parse_json(data.get("diagnosis_snapshot_json"))
        raw_case = parse_json(data.get("input_json"))
        stored_results = followup_data.get("final_results") or snapshot.get("results") or followup_data.get("initial_results")
        top_results = stored_results if isinstance(stored_results, list) else []
        if not top_results:
            top_results = build_ranked_results(candidate_texts=parse_all_candidates(diagnosis_result))
        top1_reason = top_results[0].get("原因", "") if top_results else ""
        top1_score = top_results[0].get("总分") if top_results else None
        all_candidates = [f"{i}. {item.get('原因', '未知')} (总分:{item.get('总分', '-')})" for i, item in enumerate(top_results, 1)]
        text_clues = snapshot.get("evidence", {}).get("text_clues", [])
        text_clues = list(dict.fromkeys(text_clues + followup_data.get("extra_hints", [])))
        normalized_case = snapshot.get("evidence", {}).get("normalized_case", {})
        rules_v2_eval = {}
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
            "学生初判": data.get("student_initial_hypothesis") or "-",
            "学生修订原因": data.get("student_revised_cause") or "-",
            "学生修订依据": data.get("student_revision_reason") or "-",
            "学生修订时间": data.get("student_revision_time") or "-",
            "凝胶图路径": gel_image_path if gel_image_path else "",
            "凝胶图": "有图" if has_image else "无图",
            "normalized_case": normalized_case,
            "followup_data": followup_data,
            "input_data": raw_case,
            "snapshot": snapshot,
            **{k: data.get(k) for k in case_storage.ADDITIONAL_COLUMNS},
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


def load_case_history(record_id):
    """读取复核与修订的版本记录，不重算历史诊断。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return {
            "teacher": [dict(row) for row in conn.execute("SELECT * FROM teacher_review_history WHERE record_id=? ORDER BY review_version", (record_id,))],
            "student": [dict(row) for row in conn.execute("SELECT * FROM student_revision_history WHERE record_id=? ORDER BY review_version", (record_id,))],
        }
    finally:
        conn.close()


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
    return normalize_cause_label(reason)



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
        return "系统候选结果已覆盖教师确认原因，但排序仍有优化空间，可作为纠偏案例参考。"
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
    followup_data = parse_followup_data(db_record.get("followup_json")) or payload.get("followup_data", {})

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
    student_initial = db_record.get("student_initial_hypothesis") or payload.get("student_initial_hypothesis")
    student_revised = db_record.get("student_revised_cause")
    student_revision_reason = db_record.get("student_revision_reason")
    student_revision_time = db_record.get("student_revision_time")
    current_status = "已确认" if not is_missing_value(teacher_final) else "未确认"
    if db_record.get("teacher_evidence_level") == "原因待核实":
        current_status = "已复核，原因待核实"

    diagnosis_result = db_record.get("diagnosis_result", "")
    snapshot = parse_json(db_record.get("diagnosis_snapshot_json"))
    raw_case = parse_json(db_record.get("input_json")) or payload
    if followup_data.get("updated_case"):
        raw_case = {**raw_case, **followup_data["updated_case"]}
    text_clues = snapshot.get("evidence", {}).get("text_clues", payload.get("text_clues", []))
    text_clues = list(dict.fromkeys((text_clues or []) + followup_data.get("extra_hints", [])))
    stored_results = followup_data.get("final_results") or snapshot.get("results") or followup_data.get("initial_results")
    top_results = stored_results if isinstance(stored_results, list) and stored_results else payload.get("results", [])
    ranked_results = build_ranked_results(top_results=top_results, candidate_texts=parse_all_candidates(diagnosis_result))
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
        description=description or followup_data.get("answers", {}).get("operation", ""),
        text_clues=text_clues,
        gel_image_path=image_path,
        has_image=has_image,
        experiment_parameters=raw_case,
    )
    confidence_level, confidence_reason = compute_confidence_level(
        ranked_results,
        detail=top1_detail,
        context=context,
    )
    evidence_points = build_evidence_summary(top1_reason, detail=top1_detail, context=context)
    missing_items = detect_missing_key_info({**context, "候选原因": top1_reason})
    consistency_status = build_report_consistency_status(teacher_final, ranked_results)
    if db_record.get("teacher_evidence_level") == "原因待核实":
        consistency_status = "原因待核实，暂不比较"
    feedback_summary = build_feedback_loop_summary_for_report(consistency_status)
    review_suggestions = build_review_suggestions(
        top1_reason,
        missing_items=missing_items,
        top1_suggestion=top1_suggestion,
        confidence_level=confidence_level,
    )

    lines = [f"《{PRODUCT_NAME} · 实验复盘报告》", PRODUCT_SUBTITLE, f"当前模块：{CURRENT_MODULE}"]

    append_report_section(
        lines,
        "一、报告标题区",
        [
            f"案例编号：{normalize_report_value(record_id, '未记录')}",
            f"提交时间：{normalize_report_value(submit_time, '未记录')}",
            f"是否有图片：{'有图片' if has_image else '无图片'}",
            f"当前状态：{current_status}",
            f"记录来源：{db_record.get('data_origin') or raw_case.get('data_origin') or '未标注'}",
            f"规则版本：{snapshot.get('rules_version', '旧记录，未保存版本')}",
        ],
    )

    append_report_section(
        lines,
        "二、基本实验信息",
        [
            f"课程／班级／实验／匿名组号：{normalize_report_value(raw_case.get('course_name'))}／{normalize_report_value(raw_case.get('class_name'))}／{normalize_report_value(raw_case.get('experiment_name'))}／{normalize_report_value(raw_case.get('group_code'))}",
            f"异常现象：{normalize_report_value(abnormality)}",
            f"阳性对照结果：{normalize_report_value(positive_control)}",
            f"阴性对照结果：{normalize_report_value(negative_control)}",
            f"模板相关信息：{normalize_report_value(template_amount)}",
            f"退火温度 / 程序设置信息：退火温度 {normalize_report_value(annealing_temp)}；循环数 {normalize_report_value(cycles)}",
            f"学生补充描述：{normalize_report_value(description)}",
            f"文本线索：{normalize_report_value(text_clues)}",
            f"模板类型：{normalize_report_value(raw_case.get('template_type'))}；浓度：{normalize_report_value(raw_case.get('template_concentration'))} ng/μL；反应总体积：{normalize_report_value(raw_case.get('reaction_volume'))} μL",
            f"目标片段：{normalize_report_value(raw_case.get('target_size'))} bp；推荐退火温度：{normalize_report_value(raw_case.get('recommended_temp'))} ℃；聚合酶：{normalize_report_value(raw_case.get('polymerase'))}",
            f"泳道人工标注：{normalize_report_value(raw_case.get('lane_notes'))}",
        ],
    )

    diagnosis_lines = [
        f"Top1 原因：{normalize_report_value(ranked_results[0].get('原因') if len(ranked_results) > 0 else '', '未识别')}",
        f"Top2 原因：{normalize_report_value(ranked_results[1].get('原因') if len(ranked_results) > 1 else '', '未识别')}",
        f"Top3 原因：{normalize_report_value(ranked_results[2].get('原因') if len(ranked_results) > 2 else '', '未识别')}",
    ]
    if confidence_level != "未知" or confidence_reason:
        diagnosis_lines.append(f"Top1 证据支持程度：{confidence_level}")
    if confidence_reason:
        diagnosis_lines.append(f"证据支持说明：{confidence_reason}")
    if evidence_points:
        diagnosis_lines.append("证据摘要：")
        diagnosis_lines.extend([f"- {point}" for point in evidence_points[:5]])
    if missing_items:
        diagnosis_lines.append("缺失信息提示：")
        diagnosis_lines.extend([f"- {item}" for item in missing_items])
    else:
        diagnosis_lines.append("缺失信息提示：当前未发现本候选要求的关键字段缺项，仍需结合实际实验复核。")
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

    if followup_data.get("final_results"):
        first = followup_data.get("initial_results", [])
        later = followup_data.get("final_results", [])
        followup_lines = [
            f"初判 Top1：{first[0].get('原因', '未识别') if first else '未识别'}",
            f"补证后 Top1：{later[0].get('原因', '未识别') if later else '未识别'}",
        ]
        for question in followup_data.get("questions", []):
            answer = followup_data.get("answers", {}).get(question.get("id"), "未补充")
            followup_lines.append(f"追问：{question.get('text', '')}；回答：{answer or '未补充'}")
        followup_lines.append(f"学生确认的操作线索：{normalize_report_value(followup_data.get('extra_hints', []), '无')}")
        append_report_section(lines, "追问补证与再判断", followup_lines)

    teacher_review_lines = [
        f"教师最终确认原因：{normalize_report_value(teacher_final, '未确认')}",
        f"教师备注：{normalize_report_value(teacher_note)}",
        f"结论证据等级：{normalize_report_value(db_record.get('teacher_evidence_level'), '旧记录，未标注')}",
        f"当前反馈版本：{db_record.get('teacher_review_version') or 0}",
        f"验证方案反馈：{normalize_report_value(db_record.get('verification_feedback'))}",
    ]
    if not is_missing_value(teacher_confirm_time):
        teacher_review_lines.append(f"教师确认时间：{normalize_report_value(teacher_confirm_time)}")
    if current_status == "未确认":
        teacher_review_lines.append("该案例尚未完成教师确认。")
    else:
        teacher_review_lines.append(f"一致性状态：{consistency_status}")
        teacher_review_lines.append(f"对比说明：{feedback_summary}")
    append_report_section(lines, "五、教师复核结果", teacher_review_lines)

    if student_initial:
        learning_lines = [f"学生诊断前判断：{normalize_report_value(student_initial)}"]
        if student_revised:
            learning_lines.extend([
                f"教师反馈后修订原因：{normalize_report_value(student_revised)}",
                f"修订依据：{normalize_report_value(student_revision_reason)}",
                f"修订时间：{normalize_report_value(student_revision_time)}",
            ])
            if int(db_record.get('teacher_review_version') or 0) != int(db_record.get('student_revision_review_version') or 0):
                learning_lines.append("该修订对应旧版教师反馈，待根据当前反馈再次修订。")
        else:
            learning_lines.append(
                "教师反馈后修订：待教师复核。" if current_status == "未确认"
                else "教师反馈后修订：尚未提交。"
            )
        append_report_section(lines, "学生判断与修订", learning_lines)

    plan = parse_json(db_record.get("verification_plan_json"))
    if plan:
        append_report_section(lines, "下一步验证方案（计划记录，尚未复测）", [
            f"{label}：{normalize_report_value(plan.get(field))}" for field, label in [
                ("hypothesis", "假设"), ("variable", "变量"), ("controls", "对照"),
                ("expected_result", "预期结果"), ("interpretation", "结果解释")]])
    rubric = parse_json(db_record.get("teacher_rubric_json"))
    if rubric:
        append_report_section(lines, "教师人工教学评价", [
            f"{stage_label}／{dimension}：{normalize_report_value(value, '未评价')}" for stage, stage_label in [("initial", "初判"), ("revised", "修订")]
            for dimension, value in rubric.get(stage, {}).items()])

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
            "排序分数和证据支持程度不是概率。教师经验复核不等于复测验证；未完成验证的原因仍需结合原始记录核查。",
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
        f"【{PRODUCT_NAME} · 案例摘要】",
        PRODUCT_SUBTITLE,
        f"当前模块：{CURRENT_MODULE}",
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
