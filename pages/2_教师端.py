# -*- coding: utf-8 -*-
"""
教师端页面
"""

import os
import re
import sqlite3
import html

import altair as alt
import pandas as pd
import streamlit as st
import teaching_ui
import teaching_workflow
from gel_image_ui import render_teacher_panel
from ui_design import design_color
from evidence_support import normalize_cause_label, cause_id, cause_options, parse_json, learning_progress, template_mass_ng

from core import (
    DB_PATH,
    is_classroom_record,
    apply_common_styles,
    ensure_page_config,
    init_access_state,
    init_database,
    load_recent_records,
    load_case_history,
    parse_all_candidates,
    parse_top1_result,
    render_diagnosis_quality_block,
    render_entry_guard,
    render_card_title,
    render_page_hero,
    return_to_home,
    save_teacher_confirmation,
)


def inject_teacher_dashboard_layout_styles():
    """页面样式由 core.apply_common_styles 统一注入。"""
    return


FIELD_ALIAS_MAP = {
    "time": ["diagnosis_time", "submit_time", "created_at", "created_time", "record_time", "timestamp", "提交时间"],
    "teacher_final": ["teacher_final_cause", "teacher_cause", "final_cause", "confirmed_cause", "教师最终原因", "教师确认原因"],
    "diagnosis_result": ["diagnosis_result", "system_diagnosis_result", "result_text", "诊断结果"],
    "top1_reason": ["top1_reason", "top1_result", "system_top1_reason", "top1_cause", "Top1 原因"],
    "class": ["class_name", "class", "course_class", "student_class", "teaching_class", "班级", "班级名称", "教学班"],
    "negative_control": ["negative_control_band", "negative_control_has_band", "negative_control", "阴性对照是否有带", "阴性对照"],
    "positive_control": ["positive_control_normal", "positive_control_status", "positive_control_ok", "positive_control", "阳性对照是否正常", "阳性对照"],
    "abnormality": ["abnormality", "phenomenon", "observation", "实验现象", "异常现象"],
    "description": ["description", "student_description", "raw_description", "remark", "comment", "学生补充描述", "异常描述"],
}

TIME_SCOPE_OPTIONS = {
    "最近 7 天": 7,
    "最近 30 天": 30,
    "全部数据": None,
}
HISTORY_DISPLAY_OPTIONS = {
    "10 条": 10,
    "20 条": 20,
    "50 条": 50,
    "全部": None,
}
STAT_VIEW_OPTIONS = [
    "请选择统计视角",
    "Top1 不一致案例",
    "Top1 一致案例",
    "Top3 命中但 Top1 不一致案例",
    "高频失败原因对应案例",
]
STAT_LINK_DISPLAY_OPTIONS = {
    "最近 10 条": 10,
    "最近 20 条": 20,
}

NEGATIVE_CONTROL_PATTERN = re.compile(r"阴性对照.*?(有带|有条带|出带|出现条带|有扩增)")
POSITIVE_CONTROL_PATTERN = re.compile(r"阳性对照.*?(无带|无条带|没有带|未出带|不出带|未见条带)")
REASON_NORMALIZATION_RULES = [
    ("模板量不足", ["模板量不足", "模板浓度低", "模板少", "模板浓度过低", "模板过少"]),
    ("污染", ["污染", "气溶胶污染", "阴性对照污染"]),
    ("引物问题", ["引物问题", "引物失效", "引物设计问题", "引物二聚体", "引物降解"]),
    ("PCR体系问题", ["pcr体系问题", "体系漏加", "反应体系配置错误", "pcr体系漏加试剂", "漏加试剂", "体系配置错误"]),
    ("退火温度过高", ["退火温度过高", "退火温度偏高"]),
    ("退火温度过低", ["退火温度过低", "退火温度偏低"]),
]


def escape_html(value, default=""):
    """转义展示文本，避免历史记录内容破坏页面结构。"""
    text = normalize_display_text(value, default=default)
    return html.escape(str(text), quote=True)


def render_teacher_page_header(record_count):
    """教师端紧凑 Hero 区。"""
    with st.container(key="pcr_teacher_hero_shell"):
        with st.container(key="pcr_teacher_hero_inner"):
            with st.container(key="pcr_teacher_hero_card"):
                st.markdown(
                    f"""
                    <div class="pcr-teacher-hero-copy">
                        <h1>教师复核与案例看板</h1>
                        <p>查看学生实验记录，复核系统诊断结果，并沉淀可用于教学改进的异常案例。</p>
                        <div class="pcr-teacher-hero-meta">
                            <span class="pcr-teacher-status-tag ok">教师已验证</span>
                            <span class="pcr-teacher-status-tag">当前记录 {record_count} 条</span>
                            <span class="pcr-teacher-status-tag">复核工作台</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_section_kicker(text):
    st.markdown(f'<div class="pcr-section-kicker">{html.escape(text)}</div>', unsafe_allow_html=True)


def normalize_field_key(value):
    """统一字段名格式，便于做兼容匹配"""
    return re.sub(r"[\s_]+", "", str(value or "")).lower()


def find_compatible_column(columns, candidate_names):
    """在现有表结构中查找最匹配的字段名"""
    normalized_map = {normalize_field_key(col): col for col in columns}
    for name in candidate_names:
        matched = normalized_map.get(normalize_field_key(name))
        if matched:
            return matched
    return None


def is_blank(value):
    text = str(value or "").strip()
    return text == "" or text.lower() in {"nan", "none", "null"}


def normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_record_id(value):
    if pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        text = normalize_text(value)
        return text or None


def normalize_display_text(value, default="未填写"):
    text = normalize_text(value)
    return text if text else default


def normalize_reason_label(value):
    return normalize_cause_label(value)


def is_confirmed_cause(value):
    """
    判断教师是否已经确认了失败原因。
    修复了 pandas 读取空值产生 'nan' 以及 '未知' 状态统计不一致的问题。
    """
    # 1. 拦截原生的 None 或 pandas 的 NaN
    import pandas as pd
    if pd.isna(value):
        return False

    # 2. 文本标准化（复用你代码中原有的 normalize_text 逻辑）
    # 如果你的上下文中没有 normalize_text，可以直接用 str(value or "").strip()
    text = str(value or "").strip()

    # 3. 拦截被转成字符串的特殊空值（处理 float 类型的 NaN 被 str() 转换后的情况）
    if text.lower() in {"nan", "none", "null"}:
        return False

    # 4. 核心判定：排除各种未确认的占位符，务必包含 "未知" 以对齐底部列表逻辑
    return text not in {"", "-", "未确认", "未填写", "未知"} and bool(normalize_cause_label(text))


def parse_dashboard_time(series):
    return pd.to_datetime(series, errors="coerce") if series is not None else pd.Series(dtype="datetime64[ns]")


def extract_primary_reason(row, column_mapping):
    """优先取教师最终原因，缺失时回退到系统 Top1 诊断结果"""
    teacher_col = column_mapping.get("teacher_final")
    if teacher_col:
        teacher_reason = normalize_text(row.get(teacher_col))
        if is_confirmed_cause(teacher_reason):
            return teacher_reason

    top1_col = column_mapping.get("top1_reason")
    if top1_col:
        top1_reason = normalize_text(row.get(top1_col))
        if top1_reason:
            return top1_reason

    diagnosis_result_col = column_mapping.get("diagnosis_result")
    if diagnosis_result_col:
        top1_reason, _ = parse_top1_result(row.get(diagnosis_result_col))
        if top1_reason and top1_reason != "未知":
            return top1_reason

    return None


def extract_system_reason_candidates(row, column_mapping):
    """提取系统 Top1~Top3 原因，兼容显式字段和 diagnosis_result 文本"""
    diagnosis_result_col = column_mapping.get("diagnosis_result")
    top1_col = column_mapping.get("top1_reason")

    candidates = []
    if diagnosis_result_col:
        raw_candidates = parse_all_candidates(row.get(diagnosis_result_col))
        candidates = [extract_cause_text(item) for item in raw_candidates if extract_cause_text(item)]

    if not candidates and top1_col:
        top1_reason = normalize_text(row.get(top1_col))
        if top1_reason:
            candidates = [top1_reason]

    return candidates[:3]


def build_case_brief(row, column_mapping):
    abnormality_col = column_mapping.get("abnormality")
    description_col = column_mapping.get("description")
    abnormality = normalize_text(row.get(abnormality_col)) if abnormality_col else ""
    description = normalize_text(row.get(description_col)) if description_col else ""

    description_short = description
    if len(description_short) > 24:
        description_short = f"{description_short[:24]}..."

    if abnormality and description_short:
        return f"{abnormality}｜{description_short}"
    if abnormality:
        return abnormality
    if description_short:
        return description_short
    return "未填写"


def sort_recent_cases(df):
    if df.empty:
        return df
    if "_dashboard_time" in df.columns and df["_dashboard_time"].notna().any():
        return df.sort_values("_dashboard_time", ascending=False, na_position="last")
    if "id" in df.columns:
        return df.sort_values("id", ascending=False)
    return df


def match_negative_control_abnormal(value):
    """识别“阴性对照有带”"""
    text = normalize_text(value).lower()
    if not text:
        return None
    if any(keyword in text for keyword in ["有带", "有条带", "有扩增", "出现条带", "出带"]):
        return True
    if any(keyword in text for keyword in ["无带", "无条带", "没有带", "未见条带"]):
        return False
    if text in {"yes", "y", "true", "1", "是", "有"}:
        return True
    if text in {"no", "n", "false", "0", "否", "无"}:
        return False
    return None


def match_positive_control_abnormal(value):
    """识别“阳性对照无带”"""
    text = normalize_text(value).lower()
    if not text:
        return None
    if any(keyword in text for keyword in ["无带", "无条带", "没有带", "未出带", "不出带", "未见条带", "异常", "不正常"]):
        return True
    if any(keyword in text for keyword in ["有带", "有条带", "正常"]):
        return False
    if text in {"no", "n", "false", "0", "否"}:
        return True
    if text in {"yes", "y", "true", "1", "是"}:
        return False
    return None


def build_text_fallback(row, column_mapping):
    parts = []
    for key in ["abnormality", "description"]:
        column_name = column_mapping.get(key)
        if column_name:
            text = normalize_text(row.get(column_name))
            if text:
                parts.append(text)
    return "；".join(parts)


def normalize_keyword_text(value):
    return re.sub(r"\s+", "", normalize_text(value).lower())


def extract_record_top_reasons(record):
    """从历史记录结构中提取 Top1~Top3 原因名称"""
    top1 = normalize_text(record.get("Top1 原因"))
    candidates = record.get("候选原因列表", []) or []
    parsed_candidates = [extract_cause_text(item) for item in candidates if extract_cause_text(item)]
    if not parsed_candidates and top1:
        parsed_candidates = [top1]
    if parsed_candidates and not top1:
        top1 = parsed_candidates[0]

    top2 = parsed_candidates[1] if len(parsed_candidates) > 1 else ""
    top3 = parsed_candidates[2] if len(parsed_candidates) > 2 else ""
    return top1, top2, top3


def build_record_keyword_text(record):
    """拼接关键词搜索文本，做宽松包含匹配"""
    top1, top2, top3 = extract_record_top_reasons(record)
    parts = [
        record.get("学生补充描述", ""),
        record.get("教师备注", ""),
        record.get("教师最终原因", ""),
        record.get("实验现象", ""),
        top1,
        top2,
        top3,
    ]
    return normalize_keyword_text(" ".join([normalize_text(part) for part in parts if normalize_text(part)]))

def build_teacher_records_dataframe(records):
    """把历史记录列表转成便于筛选和排序的 DataFrame —— 已修复状态错乱问题"""
    rows = []
    for index, record in enumerate(records):
        # 🔥 强制从单条记录本身读取，不做任何全局污染计算
        teacher_final_raw = record.get("教师最终原因", "")
        teacher_final = normalize_text(teacher_final_raw)

        # 🔥 只看这条记录自己是不是已确认，绝对不关联其他记录
        is_confirmed = False
        if teacher_final and teacher_final not in ["", "-", "未确认", "未填写", "未知"]:
            is_confirmed = True

        top1, top2, top3 = extract_record_top_reasons(record)
        top1_normalized = normalize_reason_label(top1)
        teacher_final_normalized = normalize_reason_label(teacher_final)
        has_image = bool(normalize_text(record.get("凝胶图路径"))) or normalize_text(record.get("凝胶图")) == "有图"

        rows.append({
            "record_index": index,
            "id": record.get("id"),
            "提交时间": normalize_display_text(record.get("提交时间"), default="-"),
            "实验现象": normalize_display_text(record.get("实验现象"), default="未填写"),
            "教师最终原因": teacher_final if is_confirmed else "",
            "教师最终原因展示": teacher_final if is_confirmed else "未确认",
            "是否已确认": is_confirmed,  # 🔥 修复：每条独立计算
            "是否未确认": not is_confirmed,
            "是否有图片": has_image,
            "系统 Top1": normalize_display_text(top1, default="-"),
            "系统 Top2": normalize_display_text(top2, default="-"),
            "系统 Top3": normalize_display_text(top3, default="-"),
            "Top1 是否不一致": bool(
                is_confirmed
                and teacher_final_normalized
                and top1_normalized
                and teacher_final_normalized != top1_normalized
            ),
            "关键词文本": build_record_keyword_text(record),
            "_sort_time": pd.to_datetime(record.get("提交时间"), errors="coerce"),
        })

    return pd.DataFrame(rows)

def build_teacher_filter_options(records_df):
    """为历史记录筛选区生成动态选项"""
    options = {
        "异常类型选项": ["全部"],
        "系统判断选项": ["全部"],
        "教师原因选项": ["全部"],
        "显示异常类型筛选": False,
        "显示系统判断筛选": False,
        "显示教师原因筛选": False,
    }
    if records_df.empty:
        return options

    if "实验现象" in records_df.columns:
        abnormality_values = sorted({value for value in records_df["实验现象"].tolist() if normalize_text(value) and value != "未填写"})
        if abnormality_values:
            options["异常类型选项"].extend(abnormality_values)
            options["显示异常类型筛选"] = True

    if "教师最终原因" in records_df.columns:
        teacher_reason_values = sorted({value for value in records_df["教师最终原因"].tolist() if normalize_text(value)})
        if teacher_reason_values:
            options["教师原因选项"].extend(teacher_reason_values)
            options["显示教师原因筛选"] = True

    if "系统 Top1" in records_df.columns:
        system_reason_values = sorted({value for value in records_df["系统 Top1"].tolist() if normalize_text(value) and value != "-"})
        if system_reason_values:
            options["系统判断选项"].extend(system_reason_values)
            options["显示系统判断筛选"] = True

    return options


def sort_teacher_records(records_df, sort_order):
    if records_df.empty:
        return records_df

    sort_by_time = "_sort_time" in records_df.columns and records_df["_sort_time"].notna().any()
    ascending = sort_order == "按提交时间升序"
    if sort_by_time:
        return records_df.sort_values(["_sort_time", "id"], ascending=[ascending, ascending], na_position="last")
    if "id" in records_df.columns:
        return records_df.sort_values("id", ascending=ascending, na_position="last")
    return records_df


def apply_teacher_record_filters(
    records_df,
    confirm_status,
    abnormality_filter,
    system_reason_filter,
    teacher_reason_filter,
    keyword,
    image_filter,
    only_unconfirmed,
    only_top1_mismatch,
    only_with_image,
    sort_order,
    display_limit,
):
    """按逐层过滤方式处理教师端历史记录"""
    filtered_df = records_df.copy()

    if filtered_df.empty:
        return filtered_df

    if confirm_status == "已确认":
        filtered_df = filtered_df[filtered_df["是否已确认"]]
    elif confirm_status == "未确认":
        filtered_df = filtered_df[filtered_df["是否未确认"]]

    if abnormality_filter != "全部" and "实验现象" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["实验现象"] == abnormality_filter]

    if system_reason_filter != "全部" and "系统 Top1" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["系统 Top1"] == system_reason_filter]

    if teacher_reason_filter != "全部" and "教师最终原因" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["教师最终原因"] == teacher_reason_filter]

    keyword_text = normalize_keyword_text(keyword)
    if keyword_text:
        filtered_df = filtered_df[filtered_df["关键词文本"].str.contains(keyword_text, na=False)]

    if only_unconfirmed:
        filtered_df = filtered_df[filtered_df["是否未确认"]]

    if only_top1_mismatch and "Top1 是否不一致" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["Top1 是否不一致"]]

    if image_filter == "有图片":
        filtered_df = filtered_df[filtered_df["是否有图片"]]
    elif image_filter == "无图片":
        filtered_df = filtered_df[~filtered_df["是否有图片"]]

    if only_with_image:
        filtered_df = filtered_df[filtered_df["是否有图片"]]

    filtered_df = sort_teacher_records(filtered_df, sort_order)
    if display_limit is not None:
        filtered_df = filtered_df.head(display_limit)
    return filtered_df


def reset_teacher_history_filters():
    """重置案例复核队列筛选项。"""
    for key in [
        "teacher_history_confirm_status",
        "teacher_history_abnormality_filter",
        "teacher_history_system_reason_filter",
        "teacher_history_teacher_reason_filter",
        "teacher_history_keyword",
        "teacher_history_sort_order",
        "teacher_history_image_filter",
        "teacher_history_display_limit",
        "teacher_history_only_unconfirmed",
        "teacher_history_only_top1_mismatch",
        "teacher_history_only_with_image",
    ]:
        st.session_state.pop(key, None)


def load_teacher_dashboard_data():
    """读取教师看板所需历史数据，并自动识别关键字段"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT * FROM diagnosis_records", conn)
    except Exception as exc:
        return pd.DataFrame(), {}, f"统计数据读取失败，已自动降级：{exc}"
    finally:
        if conn is not None:
            conn.close()

    if "data_origin" in df.columns:
        df = df[~df["data_origin"].isin(["模拟演示", "规则回归"])].copy()

    column_mapping = {
        key: find_compatible_column(df.columns, aliases)
        for key, aliases in FIELD_ALIAS_MAP.items()
    }

    if df.empty:
        return df, column_mapping, None

    time_col = column_mapping.get("time")
    class_col = column_mapping.get("class")
    teacher_col = column_mapping.get("teacher_final")

    if time_col:
        df["_dashboard_time"] = parse_dashboard_time(df[time_col])
    else:
        df["_dashboard_time"] = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")

    if class_col:
        df["_class_name"] = df[class_col].apply(lambda value: normalize_display_text(value, default="未填写"))
    else:
        df["_class_name"] = pd.Series("", index=df.index, dtype="object")

    if teacher_col:
        df["_confirmed"] = df[teacher_col].apply(is_confirmed_cause) & (df.get("teacher_evidence_level", pd.Series("", index=df.index)).fillna("") != "原因待核实")
    else:
        df["_confirmed"] = pd.Series(False, index=df.index, dtype="bool")

    df["_reason"] = df.apply(lambda row: extract_primary_reason(row, column_mapping), axis=1)
    return df, column_mapping, None


def apply_dashboard_filters(df, column_mapping, time_scope, class_filter):
    """按班级和时间范围筛选统计数据"""
    class_scoped_df = df.copy()
    class_col = column_mapping.get("class")
    if class_col and class_filter and class_filter != "全部班级":
        class_scoped_df = class_scoped_df[class_scoped_df["_class_name"] == class_filter].copy()

    filtered_df = class_scoped_df
    days = TIME_SCOPE_OPTIONS.get(time_scope)
    time_col = column_mapping.get("time")
    time_filter_available = time_col is not None and class_scoped_df.get("_dashboard_time") is not None
    if time_filter_available:
        time_filter_available = class_scoped_df["_dashboard_time"].notna().any()
    if time_filter_available and days:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
        filtered_df = class_scoped_df[
            class_scoped_df["_dashboard_time"].notna()
            & (class_scoped_df["_dashboard_time"] >= cutoff)
        ].copy()

    return class_scoped_df, filtered_df, time_filter_available


def compute_dashboard_stats(filtered_df, class_scoped_df, column_mapping):
    total_count = int(len(filtered_df))
    confirmed_count = int(filtered_df["_confirmed"].sum()) if "_confirmed" in filtered_df else 0
    unconfirmed_count = total_count - confirmed_count

    recent_30_count = "无法统计"
    if column_mapping.get("time") and "_dashboard_time" in class_scoped_df and class_scoped_df["_dashboard_time"].notna().any():
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=30)
        recent_30_count = int((
            class_scoped_df["_dashboard_time"].notna()
            & (class_scoped_df["_dashboard_time"] >= cutoff)
        ).sum())

    return {
        "总诊断记录数": total_count,
        "已教师确认数": confirmed_count,
        "未确认数": unconfirmed_count,
        "最近 30 天新增记录数": recent_30_count,
    }


def build_reason_summary(filtered_df):
    """聚合失败原因统计，供 Top5 图表和明细表复用"""
    if filtered_df.empty or "_reason" not in filtered_df:
        return pd.DataFrame(columns=["失败原因", "次数", "已确认数", "未确认数"])

    reason_df = filtered_df.copy()
    reason_df["_reason"] = reason_df["_reason"].apply(normalize_text)
    reason_df = reason_df[reason_df["_reason"] != ""]
    if reason_df.empty:
        return pd.DataFrame(columns=["失败原因", "次数", "已确认数", "未确认数"])

    summary_df = (
        reason_df.groupby("_reason", dropna=False)
        .agg(次数=("_reason", "size"), 已确认数=("_confirmed", "sum"))
        .reset_index()
        .rename(columns={"_reason": "失败原因"})
    )
    summary_df["已确认数"] = summary_df["已确认数"].astype(int)
    summary_df["未确认数"] = summary_df["次数"] - summary_df["已确认数"]
    summary_df = summary_df.sort_values(["次数", "已确认数", "失败原因"], ascending=[False, False, True])
    return summary_df.head(10)


def build_case_consistency_status(is_confirmed, comparable, top1_match, top3_hit):
    """统一一致性状态判断，供统计看板与历史详情复用"""
    if not is_confirmed or not comparable:
        return "无法比较"
    if top1_match:
        return "一致"
    if top3_hit:
        return "Top3命中但Top1不一致"
    return "未命中"


def build_consistency_category_label(status_text):
    mapping = {
        "一致": "Top1 一致",
        "Top3命中但Top1不一致": "Top1 不一致但 Top3 命中",
        "未命中": "Top3 也未命中",
    }
    return mapping.get(status_text, "无法比较")


def compute_control_abnormal_stats(filtered_df, column_mapping):
    """统计两类对照异常，优先结构化字段，缺失时回退到文本关键词匹配"""
    result = {
        "negative_control_band_count": None,
        "positive_control_failure_count": None,
    }
    if filtered_df.empty:
        return result

    negative_col = column_mapping.get("negative_control")
    positive_col = column_mapping.get("positive_control")

    if negative_col:
        matched_series = filtered_df[negative_col].apply(match_negative_control_abnormal)
        valid_series = matched_series.dropna()
        if not valid_series.empty:
            result["negative_control_band_count"] = int(valid_series.sum())

    if positive_col:
        matched_series = filtered_df[positive_col].apply(match_positive_control_abnormal)
        valid_series = matched_series.dropna()
        if not valid_series.empty:
            result["positive_control_failure_count"] = int(valid_series.sum())

    if result["negative_control_band_count"] is not None and result["positive_control_failure_count"] is not None:
        return result

    text_ready_df = filtered_df.copy()
    text_ready_df["_text_fallback"] = text_ready_df.apply(lambda row: build_text_fallback(row, column_mapping), axis=1)
    has_text_data = text_ready_df["_text_fallback"].str.strip().ne("").any()
    if not has_text_data:
        return result

    if result["negative_control_band_count"] is None:
        result["negative_control_band_count"] = int(
            text_ready_df["_text_fallback"].apply(lambda text: bool(NEGATIVE_CONTROL_PATTERN.search(text))).sum()
        )

    if result["positive_control_failure_count"] is None:
        result["positive_control_failure_count"] = int(
            text_ready_df["_text_fallback"].apply(lambda text: bool(POSITIVE_CONTROL_PATTERN.search(text))).sum()
        )

    return result


def build_consistency_dataframe(filtered_df, column_mapping):
    """基于当前筛选结果构建系统判断与教师确认一致性明细"""
    if filtered_df.empty:
        return pd.DataFrame(columns=[
            "id", "提交时间", "异常现象 / 案例摘要", "系统 Top1", "系统 Top2", "系统 Top3",
            "教师最终原因", "是否已确认", "是否可比较", "Top1 是否一致", "Top3 是否命中", "一致性状态", "一致性分类",
        ])

    teacher_col = column_mapping.get("teacher_final")
    diagnosis_result_col = column_mapping.get("diagnosis_result")
    time_col = column_mapping.get("time")

    records = []
    for _, row in filtered_df.iterrows():
        teacher_reason_raw = normalize_text(row.get(teacher_col)) if teacher_col else ""
        is_confirmed = is_confirmed_cause(teacher_reason_raw) and row.get("teacher_evidence_level") != "原因待核实"
        teacher_reason_normalized = normalize_reason_label(teacher_reason_raw)

        system_candidates = extract_system_reason_candidates(row, column_mapping)
        system_top1 = system_candidates[0] if len(system_candidates) > 0 else ""
        system_top2 = system_candidates[1] if len(system_candidates) > 1 else ""
        system_top3 = system_candidates[2] if len(system_candidates) > 2 else ""
        normalized_candidates = [normalize_reason_label(item) for item in system_candidates if normalize_reason_label(item)]

        has_system_result = bool(normalize_text(row.get(diagnosis_result_col))) if diagnosis_result_col else bool(system_candidates)
        comparable = bool(is_confirmed and teacher_reason_normalized and normalized_candidates and has_system_result)

        top1_match = comparable and teacher_reason_normalized == normalized_candidates[0]
        top3_hit = comparable and teacher_reason_normalized in normalized_candidates[:3]
        consistency_status = build_case_consistency_status(is_confirmed, comparable, top1_match, top3_hit)
        consistency_category = build_consistency_category_label(consistency_status)

        records.append({
            "id": normalize_record_id(row.get("id")),
            "提交时间": normalize_display_text(row.get(time_col), default="-") if time_col else "-",
            "异常现象 / 案例摘要": build_case_brief(row, column_mapping),
            "系统 Top1": normalize_display_text(system_top1, default="-"),
            "系统 Top2": normalize_display_text(system_top2, default="-"),
            "系统 Top3": normalize_display_text(system_top3, default="-"),
            "教师最终原因": normalize_display_text(teacher_reason_raw, default="未确认"),
            "是否已确认": is_confirmed,
            "是否可比较": comparable,
            "Top1 是否一致": top1_match,
            "Top3 是否命中": top3_hit,
            "一致性状态": consistency_status,
            "一致性分类": consistency_category,
            "_dashboard_time": row.get("_dashboard_time"),
            "_teacher_reason_normalized": teacher_reason_normalized,
            "_system_candidates_normalized": normalized_candidates,
        })

    return pd.DataFrame(records)



def compute_consistency_stats(consistency_df):
    # ########### 修复版 ###########
    # 强制双重保险：只保留 已确认=True + 是否可比较=True
    if consistency_df.empty:
        return {
            "已确认案例数": 0,
            "可比较已确认案例数": 0,
            "Top1 一致率": "暂无可展示数据",
            "Top3 命中率": "暂无可展示数据",
            "无法比较案例数": 0,
            "一致性分布": pd.DataFrame(columns=["类别", "案例数"]),
        }

    # ================= 核心修复：强制只取【真正已确认】的 =================
    confirmed_df = consistency_df[consistency_df["是否已确认"] == True].copy()
    comparable_df = confirmed_df[confirmed_df["是否可比较"] == True].copy()

    confirmed_count = len(confirmed_df)
    comparable_count = len(comparable_df)
    unable_compare_count = len(confirmed_df[confirmed_df["是否可比较"] == False])

    top1_match_count = comparable_df["Top1 是否一致"].sum() if comparable_count else 0
    top3_hit_count = comparable_df["Top3 是否命中"].sum() if comparable_count else 0

    top1_rate = f"{(top1_match_count / comparable_count) * 100:.1f}%" if comparable_count else "暂无可展示数据"
    top3_rate = f"{(top3_hit_count / comparable_count) * 100:.1f}%" if comparable_count else "暂无可展示数据"

    # ================= 修复：只统计可比较的已确认案例 =================
    distribution_df = pd.DataFrame({
        "类别": ["Top1 一致", "Top1 不一致但 Top3 命中", "Top3 也未命中"],
        "案例数": [
            int((comparable_df["一致性分类"] == "Top1 一致").sum()) if comparable_count else 0,
            int((comparable_df["一致性分类"] == "Top1 不一致但 Top3 命中").sum()) if comparable_count else 0,
            int((comparable_df["一致性分类"] == "Top3 也未命中").sum()) if comparable_count else 0,
        ]
    })

    return {
        "已确认案例数": confirmed_count,
        "可比较已确认案例数": comparable_count,
        "Top1 一致率": top1_rate,
        "Top3 命中率": top3_rate,
        "无法比较案例数": unable_compare_count,
        "一致性分布": distribution_df,
    }


def build_feedback_loop_status(record):
    """为单条历史记录生成闭环状态信息"""
    teacher_final = normalize_text(record.get("教师最终原因"))
    is_confirmed = is_confirmed_cause(teacher_final) and record.get("teacher_evidence_level") != "原因待核实"

    top1, top2, top3 = extract_record_top_reasons(record)
    normalized_teacher = normalize_reason_label(teacher_final)
    normalized_top1 = normalize_reason_label(top1)
    normalized_candidates = [normalize_reason_label(item) for item in [top1, top2, top3] if normalize_reason_label(item)]

    comparable = bool(is_confirmed and normalized_teacher and normalized_candidates)
    top1_match = comparable and normalized_teacher == normalized_top1
    top3_hit = comparable and normalized_teacher in normalized_candidates
    consistency_status = build_case_consistency_status(is_confirmed, comparable, top1_match, top3_hit)

    return {
        "当前状态": "已确认" if is_confirmed else ("已复核，原因待核实" if teacher_final else "未确认"),
        "系统 Top1": normalize_display_text(top1, default="未识别"),
        "系统 Top2": normalize_display_text(top2, default="未识别"),
        "系统 Top3": normalize_display_text(top3, default="未识别"),
        "教师最终确认原因": normalize_display_text(teacher_final, default="未确认"),
        "教师备注": normalize_display_text(record.get("教师备注"), default="未填写"),
        "教师确认时间": normalize_display_text(record.get("教师确认时间"), default="未记录"),
        "教师是否已完成确认": "是" if is_confirmed else "否",
        "一致性状态": consistency_status,
        "是否可比较": comparable,
        "Top1 是否一致": top1_match,
        "Top3 是否命中": top3_hit,
    }


def build_feedback_loop_summary(loop_status):
    """生成适合展示的闭环结论语句"""
    current_status = loop_status.get("当前状态")
    consistency_status = loop_status.get("一致性状态")

    if current_status != "已确认":
        return "该记录还没有完成教师确认，暂时只作为待查看记录。"
    if consistency_status == "一致":
        return "该记录中，系统首选判断与教师最终确认一致。"
    if consistency_status == "Top3命中但Top1不一致":
        return "该记录中，系统 Top1 判断与教师确认不一致，但前三个候选原因里包含了教师确认的原因。"
    if consistency_status == "未命中":
        return "该记录中，系统候选结果没有覆盖教师确认的原因，后续可以补充规则。"
    return "该记录已有教师确认信息，但当前字段不足，暂时无法完成对比。"


def get_case_value_tag(loop_status, missing_info_count):
    """生成轻量案例价值标签"""
    if loop_status.get("当前状态") != "已确认":
        return "未完成确认案例"
    if missing_info_count >= 3:
        return "待补充信息案例"
    if loop_status.get("一致性状态") == "一致":
        return "可作为已确认案例"
    if loop_status.get("一致性状态") == "Top3命中但Top1不一致":
        return "可作为误判纠偏案例"
    if loop_status.get("一致性状态") == "未命中":
        return "可作为规则补充案例"
    return "待补充信息案例"


def render_feedback_loop_block(record):
    """渲染教师确认反馈闭环展示模块"""
    loop_status = build_feedback_loop_status(record)
    missing_info_count = len(
        [
            item for item in [
                record.get("阳性对照是否正常"),
                record.get("阴性对照是否有带"),
                record.get("模板量"),
                record.get("退火温度"),
                record.get("学生补充描述"),
            ]
            if is_blank(item) or str(item).strip() in {"-", "未填写"}
        ]
    )
    case_value_tag = get_case_value_tag(loop_status, missing_info_count)
    summary_text = build_feedback_loop_summary(loop_status)

    with st.container(border=True):
        render_card_title("教师确认结果", "对照系统判断和教师最终确认，方便查看差异。")

        overview_cols = st.columns(4)
        overview_cols[0].metric("当前状态", loop_status["当前状态"])
        overview_cols[1].metric("系统 Top1 判断", loop_status["系统 Top1"])
        overview_cols[2].metric("教师最终确认原因", loop_status["教师最终确认原因"])
        overview_cols[3].metric("一致性状态", loop_status["一致性状态"])

        compare_left, compare_right = st.columns(2)
        with compare_left:
            st.markdown("**系统判断侧**")
            st.markdown(f"- 系统 Top1：{loop_status['系统 Top1']}")
            st.markdown(f"- 系统 Top2：{loop_status['系统 Top2']}")
            st.markdown(f"- 系统 Top3：{loop_status['系统 Top3']}")
            st.caption("系统证据支持程度、证据摘要见上方“系统 Top1 诊断证据支持解读”模块。")
        with compare_right:
            st.markdown("**教师确认侧**")
            st.markdown(f"- 教师最终确认原因：{loop_status['教师最终确认原因']}")
            st.markdown(f"- 教师备注：{loop_status['教师备注']}")
            st.markdown(f"- 教师确认时间：{loop_status['教师确认时间']}")
            st.markdown(f"- 教师是否已完成确认：{loop_status['教师是否已完成确认']}")

        st.markdown(f"**对比说明：** {summary_text}")
        st.markdown(f"**案例价值标签：** `{case_value_tag}`")


def normalize_case_for_similarity(record):
    """提取结构化相似匹配所需字段"""
    top1, top2, top3 = extract_record_top_reasons(record)
    teacher_final = normalize_text(record.get("教师最终原因"))
    text_clues = record.get("抽取到的文本线索", []) or []
    return {
        "id": record.get("id"),
        "time": pd.to_datetime(record.get("提交时间"), errors="coerce"),
        "abnormality": normalize_text(record.get("实验现象")),
        "teacher_final": teacher_final if is_confirmed_cause(teacher_final) else "",
        "teacher_final_normalized": normalize_reason_label(teacher_final),
        "system_top1": normalize_text(top1),
        "system_top1_normalized": normalize_reason_label(top1),
        "system_top2": normalize_text(top2),
        "system_top2_normalized": normalize_reason_label(top2),
        "system_top3": normalize_text(top3),
        "system_top3_normalized": normalize_reason_label(top3),
        "positive_control": normalize_text(record.get("阳性对照是否正常")),
        "negative_control": normalize_text(record.get("阴性对照是否有带")),
        "template_amount": record.get("模板量"),
        "annealing_temp": record.get("退火温度"),
        "has_image": bool(normalize_text(record.get("凝胶图路径"))) or normalize_text(record.get("凝胶图")) == "有图",
        "text_clues": [normalize_reason_label(item) or normalize_text(item) for item in text_clues if normalize_text(item)],
        "is_confirmed": is_confirmed_cause(teacher_final) and record.get("teacher_evidence_level") != "原因待核实",
    }


def extract_similarity_reasons(current_case, candidate_case):
    """基于实际命中字段生成相似依据说明"""
    reasons = []

    if current_case["abnormality"] and current_case["abnormality"] == candidate_case["abnormality"]:
        reasons.append(f"同为“{current_case['abnormality']}”异常")

    if current_case["teacher_final_normalized"] and current_case["teacher_final_normalized"] == candidate_case["teacher_final_normalized"]:
        reasons.append("教师确认原因相同")

    if current_case["system_top1_normalized"] and current_case["system_top1_normalized"] == candidate_case["system_top1_normalized"]:
        reasons.append("系统首选诊断相同")

    if current_case["negative_control"] and current_case["negative_control"] == candidate_case["negative_control"]:
        reasons.append("阴性对照状态一致")

    if current_case["positive_control"] and current_case["positive_control"] == candidate_case["positive_control"]:
        reasons.append("阳性对照状态一致")

    if current_case["has_image"] and candidate_case["has_image"]:
        reasons.append("均包含凝胶图片")

    current_clues = set(current_case["text_clues"])
    candidate_clues = set(candidate_case["text_clues"])
    shared_clues = [item for item in current_clues.intersection(candidate_clues) if item]
    if shared_clues:
        reasons.append(f"文本线索均涉及“{'、'.join(shared_clues[:2])}”")

    if current_case["system_top2_normalized"] and current_case["system_top2_normalized"] == candidate_case["system_top2_normalized"]:
        reasons.append("Top2 候选相近")

    if current_case["system_top3_normalized"] and current_case["system_top3_normalized"] == candidate_case["system_top3_normalized"]:
        reasons.append("Top3 候选相近")

    return reasons[:3]


def compute_case_similarity_score(current_record, candidate_record):
    """计算轻量、可解释的结构化相似度分数"""
    current_case = normalize_case_for_similarity(current_record)
    candidate_case = normalize_case_for_similarity(candidate_record)

    if current_case["id"] == candidate_case["id"]:
        return {"score": -1, "reasons": []}

    score = 0
    if current_case["abnormality"] and current_case["abnormality"] == candidate_case["abnormality"]:
        score += 30

    if current_case["teacher_final_normalized"] and current_case["teacher_final_normalized"] == candidate_case["teacher_final_normalized"]:
        score += 26

    if current_case["system_top1_normalized"] and current_case["system_top1_normalized"] == candidate_case["system_top1_normalized"]:
        score += 18

    if current_case["positive_control"] and current_case["positive_control"] == candidate_case["positive_control"]:
        score += 8

    if current_case["negative_control"] and current_case["negative_control"] == candidate_case["negative_control"]:
        score += 8

    if current_case["has_image"] == candidate_case["has_image"]:
        score += 4

    current_template = pd.to_numeric([current_case["template_amount"]], errors="coerce")[0]
    candidate_template = pd.to_numeric([candidate_case["template_amount"]], errors="coerce")[0]
    if pd.notna(current_template) and pd.notna(candidate_template) and abs(current_template - candidate_template) <= 1:
        score += 6

    current_temp = pd.to_numeric([current_case["annealing_temp"]], errors="coerce")[0]
    candidate_temp = pd.to_numeric([candidate_case["annealing_temp"]], errors="coerce")[0]
    if pd.notna(current_temp) and pd.notna(candidate_temp) and abs(current_temp - candidate_temp) <= 3:
        score += 6

    shared_clues = set(current_case["text_clues"]).intersection(set(candidate_case["text_clues"]))
    score += min(len(shared_clues) * 4, 8)

    if current_case["system_top2_normalized"] and current_case["system_top2_normalized"] == candidate_case["system_top2_normalized"]:
        score += 3
    if current_case["system_top3_normalized"] and current_case["system_top3_normalized"] == candidate_case["system_top3_normalized"]:
        score += 3

    if current_case["is_confirmed"] == candidate_case["is_confirmed"]:
        score += 2

    reasons = extract_similarity_reasons(current_case, candidate_case)
    return {"score": score, "reasons": reasons}


def get_similar_cases(current_record, all_records, limit=5):
    """召回并排序相似历史案例，排除当前案例本身"""
    candidates = []
    for candidate_record in all_records:
        if candidate_record.get("id") == current_record.get("id"):
            continue

        similarity = compute_case_similarity_score(current_record, candidate_record)
        if similarity["score"] <= 0:
            continue

        candidate_time = pd.to_datetime(candidate_record.get("提交时间"), errors="coerce")
        candidate_confirmed = is_confirmed_cause(candidate_record.get("教师最终原因"))
        candidates.append({
            "record": candidate_record,
            "score": similarity["score"],
            "reasons": similarity["reasons"],
            "confirmed_priority": 1 if candidate_confirmed else 0,
            "time": candidate_time,
            "id": candidate_record.get("id") or 0,
        })

    ranked_cases = sorted(
        candidates,
        key=lambda item: (
            item["confirmed_priority"],
            item["score"],
            item["time"] if pd.notna(item["time"]) else pd.Timestamp.min,
            item["id"],
        ),
        reverse=True,
    )
    return ranked_cases[:limit]


def render_similar_case_block(current_record, all_records):
    """渲染相似历史案例回看模块（修复：移除内部折叠面板，避免嵌套报错）"""
    similar_cases = get_similar_cases(current_record, all_records, limit=5)

    with st.container(border=True):
        render_card_title("可参考的相似历史案例", "基于当前数据库中的结构化字段进行轻量匹配，优先展示已确认案例。")

        if not similar_cases:
            st.info("暂无足够相似的历史案例")
            return

        # 修复点：直接展示卡片，不使用 expander，彻底解决嵌套问题
        for index, case_item in enumerate(similar_cases, 1):
            record = case_item["record"]
            teacher_final = normalize_display_text(record.get("教师最终原因"), default="未确认")
            if teacher_final == "未确认":
                teacher_final = "未确认"
            similar_reason_text = "；".join(case_item["reasons"]) if case_item["reasons"] else "结构化字段部分匹配"

            # 使用容器替代折叠面板
            with st.container(border=True):
                st.markdown(
                    f"**{index}. 记录ID {record.get('id', '-')} | {record.get('提交时间', '-')} | 相似度 {case_item['score']}**")
                col_left, col_right = st.columns(2)
                with col_left:
                    st.markdown(f"- 提交时间：{record.get('提交时间', '-')}")
                    st.markdown(f"- 实验现象：{record.get('实验现象', '-')}")
                    st.markdown(f"- 系统 Top1：{record.get('Top1 原因', '-')}")
                with col_right:
                    st.markdown(f"- 教师最终确认原因：{teacher_final}")
                    st.markdown(f"- 是否有图片：{record.get('凝胶图', '无图')}")
                    st.markdown(f"- 相似依据：{similar_reason_text}")

def build_records_by_id(records):
    records_by_id = {}
    for record in records:
        record_id = normalize_record_id(record.get("id"))
        if record_id is not None:
            records_by_id[record_id] = record
    return records_by_id


def build_stat_view_options():
    return STAT_VIEW_OPTIONS


def filter_records_by_stat_view(view_name, consistency_df, filtered_df, selected_reason=""):
    if view_name == "Top1 不一致案例":
        linked_df = consistency_df[
            consistency_df["是否已确认"]
            & consistency_df["是否可比较"]
            & (~consistency_df["Top1 是否一致"])
        ].copy()
        linked_df = sort_recent_cases(linked_df)
        return linked_df, f"当前共找到 {len(linked_df)} 条 Top1 不一致案例。"

    if view_name == "Top1 一致案例":
        linked_df = consistency_df[
            consistency_df["是否已确认"]
            & consistency_df["是否可比较"]
            & consistency_df["Top1 是否一致"]
        ].copy()
        linked_df = sort_recent_cases(linked_df)
        return linked_df, f"当前共找到 {len(linked_df)} 条 Top1 一致案例。"

    if view_name == "Top3 命中但 Top1 不一致案例":
        linked_df = consistency_df[
            consistency_df["是否已确认"]
            & consistency_df["是否可比较"]
            & (~consistency_df["Top1 是否一致"])
            & consistency_df["Top3 是否命中"]
        ].copy()
        linked_df = sort_recent_cases(linked_df)
        return linked_df, f"当前共找到 {len(linked_df)} 条 Top3 命中但 Top1 不一致案例。"

    if view_name == "高频失败原因对应案例":
        reason_value = normalize_text(selected_reason)
        if not reason_value:
            return pd.DataFrame(), "请选择一个失败原因后查看对应案例。"
        reason_df = filtered_df.copy()
        if reason_df.empty or "_reason" not in reason_df.columns:
            return pd.DataFrame(), f"当前筛选范围内暂无“{reason_value}”相关案例。"
        reason_df["_reason"] = reason_df["_reason"].apply(normalize_text)
        linked_df = reason_df[reason_df["_reason"] == reason_value].copy()
        linked_df = sort_recent_cases(linked_df)
        return linked_df, f"当前共找到 {len(linked_df)} 条“{reason_value}”相关案例。"

    return pd.DataFrame(), "请选择一个统计视角查看对应案例明细。"


def build_stat_linked_records(linked_df, records_by_id):
    linked_records = []
    seen_ids = set()
    if linked_df.empty or "id" not in linked_df.columns:
        return linked_records

    for record_id in linked_df["id"].tolist():
        normalized_id = normalize_record_id(record_id)
        if normalized_id is None or normalized_id in seen_ids:
            continue
        record = records_by_id.get(normalized_id)
        if record:
            linked_records.append(record)
            seen_ids.add(normalized_id)
    return linked_records


def render_case_detail(record, all_records, detail_key_prefix):
    record_id = record.get("id")
    with st.expander(f"查看详情（记录ID: {record_id}）"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**学生输入摘要**")
            st.markdown(f"- 记录 ID：{record_id}")
            st.markdown(f"- 提交时间：{record.get('提交时间', '-')}")
            st.markdown(f"- 实验现象：{record.get('实验现象', '-')}")
            st.markdown(f"- 模板量：{record.get('模板量', '-')} μL")
            st.markdown(f"- 退火温度：{record.get('退火温度', '-')} ℃")
            st.markdown(f"- 循环数：{record.get('循环数', '-')}")
        with col2:
            st.markdown("**系统诊断摘要**")
            st.markdown(f"- 阳性对照是否正常：{record.get('阳性对照是否正常', '-')}")
            st.markdown(f"- 阴性对照是否有带：{record.get('阴性对照是否有带', '-')}")
            st.markdown(f"- Top1 原因：{record.get('Top1 原因', '-')}")
            st.markdown(f"- Top1 分数：{record.get('Top1 分数', '-')}")

        st.markdown(f"- 学生补充描述：{record.get('学生补充描述', '-')}")
        if record.get("学生初判") not in (None, "-"):
            st.markdown(f"- 学生诊断前判断：{record.get('学生初判')}")
        clues = record.get("抽取到的文本线索", [])
        st.markdown(f"- 抽取到的文本线索：{('、'.join(clues)) if clues else '无'}")

        candidates = record.get("候选原因列表", [])
        if len(candidates) > 1:
            for item in candidates[1:]:
                st.markdown(f"- 其他候选原因：{item}")
        else:
            st.markdown("- 其他候选原因：无")

        with st.container(border=True):
            st.markdown('<div class="pcr-teacher-review-form">', unsafe_allow_html=True)
            render_card_title("教师复核确认", "请选择最终原因并补充备注，保存后将作为本条案例的教师确认结论。")
            independent = teaching_workflow.independent_record(DB_PATH, record_id, True)["review"]
            if independent:
                st.write("此前独立判断：" + independent["cause"])
                st.caption("如最终判断改变，请在教师备注中说明原因。独立原稿保留。")
            candidate_causes = [extract_cause_text(x) for x in candidates if extract_cause_text(x)]
            if not candidate_causes and record.get("Top1 原因"):
                candidate_causes = [record.get("Top1 原因")]
            confirm_options = ["请选择"] + list(dict.fromkeys(candidate_causes + cause_options() + ["其他/待补充"]))

            with st.form(f"{detail_key_prefix}_teacher_confirm_form_{record_id}"):
                teacher_choice = st.selectbox("最终原因", confirm_options, index=confirm_options.index(record.get("教师最终原因")) if record.get("教师最终原因") in confirm_options else 0, key=f"{detail_key_prefix}_teacher_choice_{record_id}")
                custom_cause = ""
                if teacher_choice == "其他/待补充":
                    custom_cause = st.text_input("请填写教师最终原因", key=f"{detail_key_prefix}_teacher_custom_{record_id}")
                teacher_note = st.text_area("教师备注", value=record.get("教师备注") if record.get("教师备注") not in (None, "-") else "", height=100, key=f"{detail_key_prefix}_teacher_note_{record_id}")
                evidence_options = ["经验复核", "原始记录支持", "复测验证", "原因待核实"]
                evidence_level = st.selectbox("结论证据等级", evidence_options, index=evidence_options.index(record.get("teacher_evidence_level")) if record.get("teacher_evidence_level") in evidence_options else 0, key=f"{detail_key_prefix}_evidence_{record_id}")
                st.caption("经验判断、原始记录与复测结果分别标记；系统与教师一致率不等于实验验证准确率。")
                verification_feedback = st.text_area("验证方案反馈", value=record.get("verification_feedback") or "", key=f"{detail_key_prefix}_verification_feedback_{record_id}")
                source_options = ["未标注", "真实课堂"]
                data_origin = st.selectbox("核对记录来源", source_options, format_func=lambda v: "课堂记录" if v == "真实课堂" else "待核实", index=source_options.index(record.get("data_origin")) if record.get("data_origin") in source_options else 0, key=f"{detail_key_prefix}_source_{record_id}")
                previous_rubric = parse_json(record.get("teacher_rubric_json"))
                rubric = dict(previous_rubric)
                with st.expander("人工教学评价（可选，不自动评分）"):
                    st.caption("0：未体现；1：部分体现；2：有具体依据。未评价保留为空；同案例修订分数不等同于学习迁移。")
                    for stage, title in [("initial", "学生初判"), ("revised", "学生修订")]:
                        st.markdown(f"**{title}**")
                        rubric[stage] = {}
                        for dimension in ["对照解释", "证据引用", "替代原因", "验证方案"]:
                            old = previous_rubric.get(stage, {}).get(dimension)
                            rubric[stage][dimension] = st.selectbox(dimension, [None, 0, 1, 2], index=[None, 0, 1, 2].index(old) if old in [None, 0, 1, 2] else 0,
                                format_func=lambda v: "未评价" if v is None else str(v), key=f"{detail_key_prefix}_rubric_{record_id}_{stage}_{dimension}")
                save_confirm = st.form_submit_button("保存复核结果", type="primary")

            if save_confirm:
                final_cause = custom_cause.strip() if teacher_choice == "其他/待补充" else teacher_choice
                if not final_cause or final_cause == "请选择":
                    st.warning("请选择或填写教师最终原因。")
                elif independent and not teacher_note.strip() and cause_id(independent["cause"]) != cause_id(final_cause):
                    st.warning("最终判断与此前独立判断不同，请在教师备注中填写改变判断的依据。")
                else:
                    saved = save_teacher_confirmation(record_id, final_cause, teacher_note.strip(), evidence_level,
                                                      verification_feedback.strip(), expected_version=int(record.get("teacher_review_version") or 0), rubric=rubric, data_origin=data_origin)
                    if not saved:
                        st.error("记录已被其他会话更新，请刷新后再复核。")
                        return
                    st.success("复核结果已保存；此前反馈和学生修订仍保留。")
                    st.cache_data.clear()  # 必须加
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        render_diagnosis_quality_block(
            top_results=record.get("系统结果列表", []),
            candidate_texts=candidates,
            top1_reason=record.get("Top1 原因", ""),
            top1_score=record.get("Top1 分数", ""),
            abnormality=record.get("实验现象", ""),
            positive_control_normal=record.get("阳性对照是否正常", ""),
            negative_control_band=record.get("阴性对照是否有带", ""),
            template_amount=record.get("模板量"),
            annealing_temp=record.get("退火温度"),
            cycles=record.get("循环数"),
            description=record.get("学生补充描述", ""),
            text_clues=clues,
            gel_image_path=record.get("凝胶图路径", ""),
            has_image=bool(record.get("凝胶图路径")),
            experiment_parameters=record.get("input_data", {}),
            title="系统 Top1 诊断证据支持解读",
        )

        render_feedback_loop_block(record)
        history = load_case_history(record_id)
        if history["teacher"] or history["student"]:
            with st.expander("历次教师反馈与学生修订"):
                for item in history["teacher"]:
                    st.write(f"教师反馈 v{item['review_version']}｜{item['created_at']}｜{item['evidence_level']}：{item['cause']}；{item['note'] or '无备注'}")
                for item in history["student"]:
                    st.write(f"对应反馈 v{item['review_version']} 的学生修订｜{item['created_at']}：{item['cause']}；依据：{item['reason']}")
        st.caption(f"记录来源：{record.get('data_origin') or '未标注'}｜规则版本：{record.get('snapshot', {}).get('rules_version', '旧记录，未保存版本')}｜复核版本：{record.get('teacher_review_version') or 0}")
        raw_case = record.get("input_data", {})
        if raw_case.get("lane_notes"):
            st.write("人工泳道标注：" + raw_case["lane_notes"])
        if template_mass_ng(raw_case) is not None:
            st.write(f"DNA 输入质量：{template_mass_ng(raw_case):g} ng（按记录数值计算，适量范围需参照具体体系）")
        plan = parse_json(record.get("verification_plan_json"))
        if plan:
            st.markdown("**学生下一步验证方案（尚未复测）**")
            for field, label in [("hypothesis", "假设"), ("variable", "变量"), ("controls", "对照"), ("expected_result", "预期结果"), ("interpretation", "结果解释")]:
                st.write(f"{label}：{plan.get(field, '')}")
        if int(record.get("teacher_review_version") or 0) != int(record.get("student_revision_review_version") or 0) and record.get("学生修订时间") not in (None, "-", ""):
            st.warning("已保存的学生修订对应之前的教师反馈，等待学生根据新版本再次修订。")
        followup_data = record.get("followup_data", {})
        if followup_data.get("final_results"):
            st.markdown("**追问补证记录**")
            initial = followup_data.get("initial_results", [])
            final = followup_data.get("final_results", [])
            st.write(
                f"初判 Top1：{initial[0].get('原因', '未识别') if initial else '未识别'} → "
                f"补证后 Top1：{final[0].get('原因', '未识别') if final else '未识别'}"
            )
            for question in followup_data.get("questions", []):
                answer = followup_data.get("answers", {}).get(question.get("id"), "")
                if answer:
                    st.write(f"{question.get('text', '')} 回答：{answer}")
            hints = followup_data.get("extra_hints", [])
            st.write(f"学生确认的操作线索：{'、'.join(hints) if hints else '无'}")
        render_teacher_panel(DB_PATH, record_id)
        render_similar_case_block(record, all_records)

        st.markdown(f"- 教师最终原因：{record.get('教师最终原因', '未确认')}")
        st.markdown(f"- 教师备注：{record.get('教师备注', '-')}")
        st.markdown(f"- 教师确认时间：{record.get('教师确认时间', '-')}")
        if record.get("学生初判") not in (None, "-"):
            if record.get("学生修订时间") not in (None, "-"):
                st.markdown(f"- 学生修订原因：{record.get('学生修订原因', '-')}")
                st.markdown(f"- 学生修订依据：{record.get('学生修订依据', '-')}")
                st.markdown(f"- 学生修订时间：{record.get('学生修订时间', '-')}")
            elif record.get("教师最终原因") not in (None, "未确认", "-"):
                st.markdown("- 学生反馈后修订：待提交")
            else:
                st.markdown("- 学生反馈后修订：待教师复核")

        img_path = record.get("凝胶图路径", "")
        if img_path and os.path.exists(img_path):
            st.image(img_path, caption="历史凝胶图片", use_container_width=True)
        elif img_path:
            st.info("图片文件不存在")
        else:
            st.info("无图片")


def build_case_queue_summary_dataframe(records_to_render, start_index=1):
    """生成折叠区中的轻量案例摘要，避免长列表全部展开。"""
    rows = []
    for offset, record in enumerate(records_to_render, start_index):
        loop_status = build_feedback_loop_status(record)
        rows.append(
            {
                "序号": offset,
                "记录ID": record.get("id", "-"),
                "提交时间": normalize_display_text(record.get("提交时间"), default="-"),
                "实验现象": normalize_display_text(record.get("实验现象"), default="未填写"),
                "系统 Top1": normalize_display_text(record.get("Top1 原因"), default="-"),
                "教师确认": normalize_display_text(loop_status["教师最终确认原因"], default="未确认"),
                "一致性": normalize_display_text(loop_status["一致性状态"], default="-"),
            }
        )
    return pd.DataFrame(rows)


def render_case_summary_drawer(remaining_records, start_index):
    """用自定义折叠摘要区展示剩余记录，和单条详情折叠形成层级区分。"""
    summary_df = build_case_queue_summary_dataframe(remaining_records, start_index=start_index)
    header_cells = "".join(f"<th>{escape_html(column, '-')}</th>" for column in summary_df.columns)
    body_rows = []
    for _, row in summary_df.iterrows():
        cells = "".join(f"<td>{escape_html(row[column], '-')}</td>" for column in summary_df.columns)
        body_rows.append(f"<tr>{cells}</tr>")

    st.markdown(
        f"""
        <details class="pcr-summary-drawer">
            <summary>
                <span class="pcr-summary-drawer-title">其余 {len(remaining_records)} 条记录摘要</span>
                <span class="pcr-summary-drawer-hint">点击展开查看</span>
            </summary>
            <div class="pcr-summary-drawer-body">
                <table class="pcr-summary-table">
                    <thead><tr>{header_cells}</tr></thead>
                    <tbody>{''.join(body_rows)}</tbody>
                </table>
            </div>
        </details>
        """,
        unsafe_allow_html=True,
    )


def render_case_record_list(records_to_render, all_records, list_key_prefix, visible_detail_count=3):
    if not records_to_render:
        return

    total_count = len(records_to_render)
    visible_count = min(visible_detail_count, total_count)
    st.markdown(
        f"""
        <div class="pcr-case-list-toolbar">
            <div>
                <b>案例复核队列</b><br/>
                <span>默认展开前 {visible_count} 条案例，其余记录放在下方摘要中，便于快速复核。</span>
            </div>
            <div>
                <span class="pcr-tag info">共 {total_count} 条</span>
                <span class="pcr-tag ok">显示 {visible_count} 条</span>
                <span class="pcr-tag muted">折叠 {max(total_count - visible_count, 0)} 条</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    visible_records = records_to_render[:visible_count]
    for idx, record in enumerate(visible_records, 1):
        loop_status = build_feedback_loop_status(record)
        status_class = "ok" if loop_status["当前状态"] == "已确认" else "warn"
        status_label = "已复核" if loop_status["当前状态"] == "已确认" else "待复核"
        consistency_status = loop_status["一致性状态"]
        attention_label = "需关注" if loop_status["当前状态"] == "已确认" and consistency_status != "一致" else consistency_status
        consistency_class = "ok" if consistency_status == "一致" else "info" if "Top3" in consistency_status else "warn"
        image_status = normalize_display_text(record.get("凝胶图"), default="无图")
        image_class = "info" if "有" in image_status else "muted"
        teacher_final = loop_status["教师最终确认原因"]
        desc = normalize_display_text(record.get("学生补充描述"), default="未填写")
        if len(desc) > 68:
            desc = f"{desc[:68]}..."

        st.markdown(
            f"""
            <div class="pcr-teacher-case-card">
                <div class="pcr-teacher-case-main">
                    <div>
                        <div class="pcr-teacher-case-title">
                            {idx}. {escape_html(record.get('实验现象'), '-')} · Top1：{escape_html(record.get('Top1 原因'), '-')}
                        </div>
                        <div class="pcr-teacher-case-meta">
                            提交时间：{escape_html(record.get('提交时间'), '-')} ｜ 教师确认：{escape_html(teacher_final, '未确认')}
                        </div>
                        <div class="pcr-teacher-case-desc">
                            学生描述：{escape_html(desc, '未填写')}
                        </div>
                    </div>
                    <div class="pcr-record-tags">
                        <span class="pcr-tag {status_class}">{escape_html(status_label, '-')}</span>
                        <span class="pcr-tag {consistency_class}">{escape_html(attention_label, '-')}</span>
                        <span class="pcr-tag {image_class}">{escape_html(image_status, '无图')}</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        render_case_detail(record, all_records, detail_key_prefix=f"{list_key_prefix}_{record.get('id', idx)}")

    remaining_records = records_to_render[visible_count:]
    if remaining_records:
        render_case_summary_drawer(remaining_records, start_index=visible_count + 1)


def render_dashboard_empty_state(title, detail, min_height_rem=18.35):
    """渲染等高空态面板，让左右看板在无数据时仍保持视觉平衡。"""
    st.markdown(
        f'<div class="pcr-dashboard-empty" style="min-height:{float(min_height_rem):.2f}rem;">'
        f'<div><b>{escape_html(title, "-")}</b><span>{escape_html(detail, "-")}</span></div></div>',
        unsafe_allow_html=True,
    )


def render_teacher_section_header(title, desc="", dark=False):
    """统一教师端区域标题。"""
    st.markdown(
        f'<div><h2 class="pcr-teacher-section-title">{escape_html(title, "-")}</h2>'
        f'<p class="pcr-teacher-section-desc">{escape_html(desc, "")}</p></div>',
        unsafe_allow_html=True,
    )


def render_teacher_kpi_cards(metrics):
    """渲染班级实验记录概览 KPI。"""
    kpi_items = [
        ("总诊断记录", metrics.get("总诊断记录数", 0), "当前筛选范围内的全部学生记录", "focus"),
        ("待复核记录", metrics.get("未确认数", 0), "需要教师继续确认的案例", ""),
        ("已复核记录", metrics.get("已教师确认数", 0), "已完成教师最终原因确认", ""),
        ("近 30 天记录", metrics.get("最近 30 天新增记录数", "无法统计"), "用于观察近期课堂实验情况", ""),
    ]
    cards = []
    for label, value, note, card_class in kpi_items:
        cards.append(
            f'<div class="pcr-teacher-kpi-card {card_class}">'
            f'<div class="pcr-teacher-kpi-label">{escape_html(label, "-")}</div>'
            f'<div class="pcr-teacher-kpi-value">{escape_html(value, "-")}</div>'
            f'<div class="pcr-teacher-kpi-note">{escape_html(note, "-")}</div>'
            "</div>"
        )
    st.markdown(f'<div class="pcr-teacher-kpi-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_consistency_insight_card(consistency_stats, consistency_df):
    """渲染系统判断与教师确认一致性卡片。"""
    comparable_count = int(consistency_stats.get("可比较已确认案例数", 0) or 0)
    confirmed_count = int(consistency_stats.get("已确认案例数", 0) or 0)
    unable_count = int(consistency_stats.get("无法比较案例数", 0) or 0)

    if comparable_count == 0:
        render_dashboard_empty_state(
            "暂无可展示数据",
            "当教师完成更多记录确认后，系统将展示一致率和差异分析。",
            min_height_rem=7.2,
        )
        st.markdown(
            f'<div class="pcr-teacher-mini-grid">'
            f'<div class="pcr-teacher-mini-stat"><span>已复核记录</span><b>{confirmed_count}</b></div>'
            f'<div class="pcr-teacher-mini-stat"><span>已比较记录</span><b>{comparable_count}</b></div>'
            f'<div class="pcr-teacher-mini-stat"><span>待比较记录</span><b>{unable_count}</b></div>'
            "</div>",
            unsafe_allow_html=True,
        )
        return

    latest_mismatch = "暂无近期不一致记录"
    if not consistency_df.empty:
        mismatch_df = get_recent_mismatch_cases(consistency_df, limit=1)
        if not mismatch_df.empty:
            row = mismatch_df.iloc[0]
            latest_mismatch = (
                f"{normalize_display_text(row.get('异常现象 / 案例摘要'), default='未填写')}："
                f"系统 {normalize_display_text(row.get('系统 Top1'), default='-')}，"
                f"教师 {normalize_display_text(row.get('教师最终原因'), default='-')}"
            )

    st.markdown(
        f'<div><div class="pcr-teacher-kpi-value" style="color:var(--ds-text); margin-top:0;">{escape_html(consistency_stats.get("Top1 一致率", "-"), "-")}</div>'
        '<p style="color:var(--ds-muted); margin:0 0 var(--ds-3) 0;">系统 Top1 判断与教师确认的一致率。</p>'
        f'<div class="pcr-teacher-mini-grid"><div class="pcr-teacher-mini-stat"><span>已比较记录</span><b>{comparable_count}</b></div>'
        f'<div class="pcr-teacher-mini-stat"><span>待比较记录</span><b>{unable_count}</b></div>'
        f'<div class="pcr-teacher-mini-stat"><span>Top3 命中率</span><b>{escape_html(consistency_stats.get("Top3 命中率", "-"), "-")}</b></div></div>'
        f'<div class="pcr-teacher-empty-state" style="margin-top:0.85rem;"><div><b>最近不一致提示</b><span>{escape_html(latest_mismatch, "-")}</span></div></div></div>',
        unsafe_allow_html=True,
    )


def render_top_reason_bars(reason_summary_df, top_n=5):
    """渲染高频失败原因 Top5 横向条。"""
    top_df = reason_summary_df[["失败原因", "次数"]].head(top_n).copy() if not reason_summary_df.empty else pd.DataFrame()
    if top_df.empty:
        render_dashboard_empty_state(
            "暂无可展示数据",
            "当前筛选范围内暂无可汇总的失败原因数据。",
            min_height_rem=7.2,
        )
        return

    max_count = max(int(top_df["次数"].max()), 1)
    total_count = max(int(top_df["次数"].sum()), 1)
    rows = []
    for rank, row in enumerate(top_df.itertuples(index=False), 1):
        reason = str(row[0])
        count = int(row[1])
        width = count / max_count * 100
        percent = count / total_count * 100
        rows.append(
            f'<div class="pcr-top-reason-row {"top" if rank == 1 else ""}">'
            f'<div class="pcr-top-reason-head"><span>Top{rank} {escape_html(reason, "-")}</span>'
            f"<span>{count} 次 · {percent:.0f}%</span></div>"
            f'<div class="pcr-top-reason-bar"><div class="pcr-top-reason-fill" style="width:{width:.1f}%;"></div></div>'
            "</div>"
        )
    st.markdown("".join(rows), unsafe_allow_html=True)


def render_recent_attention_records(records, limit=3):
    """优先展示待复核和需关注案例。"""
    if not records:
        render_dashboard_empty_state(
            "暂无可展示数据",
            "当前还没有学生诊断记录，待提交后会在这里形成复核队列。",
            min_height_rem=5.6,
        )
        return

    unconfirmed = []
    mismatch = []
    completed = []
    for record in records:
        loop_status = build_feedback_loop_status(record)
        if loop_status["当前状态"] != "已确认":
            unconfirmed.append(record)
        elif loop_status["一致性状态"] != "一致":
            mismatch.append(record)
        else:
            completed.append(record)

    selected = []
    seen_ids = set()
    for group in [unconfirmed, mismatch, completed]:
        for record in group:
            record_id = record.get("id")
            if record_id in seen_ids:
                continue
            selected.append(record)
            seen_ids.add(record_id)
            if len(selected) >= limit:
                break
        if len(selected) >= limit:
            break

    cards = []
    for record in selected:
        loop_status = build_feedback_loop_status(record)
        image_status = "有图片" if record.get("凝胶图路径") or normalize_text(record.get("凝胶图")) == "有图" else "无图片"
        tag_class = "warn" if loop_status["当前状态"] != "已确认" else "ok" if loop_status["一致性状态"] == "一致" else "warn"
        cards.append(
            f'<div class="pcr-teacher-attention-card">'
            f'<b>{escape_html(record.get("实验现象"), "未填写")} · {escape_html(loop_status["当前状态"], "-")}</b>'
            f'<span>时间：{escape_html(record.get("提交时间"), "-")}</span>'
            f'<span>系统 Top1：{escape_html(record.get("Top1 原因"), "-")}</span>'
            f'<span>教师确认：{escape_html(loop_status["教师最终确认原因"], "未确认")}</span>'
            f'<span>图片：{escape_html(image_status, "-")}</span>'
            f'<span class="pcr-teacher-status-tag {tag_class}" style="margin-top:0.52rem; color:var(--ds-text);">{escape_html(loop_status["一致性状态"], "-")}</span>'
            "</div>"
        )
    st.markdown(f'<div class="pcr-teacher-attention-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_stat_linked_case_list(filtered_df, consistency_df, reason_summary_df, records_by_id, all_records):
    with st.container(border=True):
        render_section_kicker("案例追踪")
        render_card_title("统计结果对应案例明细", "基于当前统计筛选范围做二次过滤，快速查看统计结论对应的具体案例。")

        view_col, limit_col = st.columns([1.4, 0.8])
        with view_col:
            selected_view = st.selectbox(
                "查看哪类案例",
                build_stat_view_options(),
                key="teacher_dashboard_stat_view",
            )
        with limit_col:
            display_label = st.selectbox(
                "明细显示条数",
                list(STAT_LINK_DISPLAY_OPTIONS.keys()),
                key="teacher_dashboard_stat_link_display_limit",
            )

        selected_reason = ""
        if selected_view == "高频失败原因对应案例":
            reason_options = reason_summary_df["失败原因"].tolist() if not reason_summary_df.empty else []
            if reason_options:
                selected_reason = st.selectbox(
                    "失败原因",
                    ["请选择失败原因"] + reason_options,
                    key="teacher_dashboard_reason_view_filter",
                )
                if selected_reason == "请选择失败原因":
                    selected_reason = ""
            else:
                st.info("当前统计范围内暂无可用的失败原因。")

        linked_df, summary_text = filter_records_by_stat_view(
            selected_view,
            consistency_df,
            filtered_df,
            selected_reason=selected_reason,
        )
        st.caption(summary_text)

        if selected_view == "请选择统计视角":
            st.info("请选择一个统计视角查看对应案例明细。")
            return

        if linked_df.empty:
            st.info("当前统计视角下暂无可展示的案例。")
            return

        display_limit = STAT_LINK_DISPLAY_OPTIONS[display_label]
        display_records = build_stat_linked_records(linked_df.head(display_limit), records_by_id)

        if not display_records:
            st.info("当前案例明细暂无法关联到完整历史记录。")
            return

        render_case_record_list(display_records, all_records, list_key_prefix="dashboard_linked")


def get_recent_mismatch_cases(consistency_df, limit=10):
    if consistency_df.empty:
        return consistency_df

    mismatch_df = consistency_df[
        consistency_df["是否已确认"]
        & consistency_df["是否可比较"]
        & (~consistency_df["Top1 是否一致"])
    ].copy()
    mismatch_df = sort_recent_cases(mismatch_df)
    return mismatch_df[[
        "提交时间",
        "异常现象 / 案例摘要",
        "系统 Top1",
        "系统 Top2",
        "系统 Top3",
        "教师最终原因",
        "Top3 是否命中",
    ]].head(limit)


def get_recent_match_cases(consistency_df, limit=10):
    if consistency_df.empty:
        return consistency_df

    match_df = consistency_df[
        consistency_df["是否已确认"]
        & consistency_df["是否可比较"]
        & consistency_df["Top1 是否一致"]
    ].copy()
    match_df = sort_recent_cases(match_df)
    return match_df[[
        "提交时间",
        "异常现象 / 案例摘要",
        "系统 Top1",
        "教师最终原因",
    ]].head(limit)


def render_consistency_distribution_visualization(distribution_df):
    """用紧凑堆叠条和精简柱图展示一致性分布。"""
    if distribution_df.empty or "案例数" not in distribution_df.columns or distribution_df["案例数"].sum() == 0:
        render_dashboard_empty_state(
            "暂无可比较的一致性数据",
            "完成教师复核后，这里会展示 Top1 一致、Top3 命中与未命中的分布。",
            min_height_rem=23.8,
        )
        return

    color_map = {
        "Top1 一致": design_color("primary"),
        "Top1 不一致但 Top3 命中": design_color("focus"),
        "Top3 也未命中": design_color("warning-text"),
    }
    total = max(int(distribution_df["案例数"].sum()), 1)
    segments = []
    legends = []
    for _, row in distribution_df.iterrows():
        category = str(row["类别"])
        count = int(row["案例数"])
        width = count / total * 100
        color = color_map.get(category, design_color("muted"))
        segments.append(
            f'<div class="pcr-stack-segment" style="width:{width:.1f}%; background:{color};"></div>'
        )
        legends.append(
            f'<span><span class="pcr-legend-dot" style="background:{color};"></span>{html.escape(category)} {count} 条</span>'
        )

    st.markdown(
        f"""
        <div class="pcr-stack-bar">{''.join(segments)}</div>
        <div class="pcr-stack-legend">{''.join(legends)}</div>
        """,
        unsafe_allow_html=True,
    )

    chart_df = distribution_df.copy()
    bar_chart = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5)
        .encode(
            y=alt.Y("类别:N", title=None, sort=None, axis=alt.Axis(labelLimit=180)),
            x=alt.X("案例数:Q", title="案例数", axis=alt.Axis(tickMinStep=1)),
            color=alt.Color(
                "类别:N",
                legend=None,
                scale=alt.Scale(
                    domain=list(color_map.keys()),
                    range=list(color_map.values()),
                ),
            ),
            tooltip=[
                alt.Tooltip("类别:N", title="类别"),
                alt.Tooltip("案例数:Q", title="案例数"),
            ],
        )
        .properties(height=220)
    )
    st.altair_chart(bar_chart, use_container_width=True)
    st.dataframe(distribution_df, use_container_width=True, hide_index=True)


def render_learning_progress(filtered_df):
    st.markdown("### 学习闭环进度")
    metrics, rows = learning_progress(filtered_df.to_dict("records"))
    cols = st.columns(5)
    for col, (label, item) in zip(cols, metrics.items()):
        numerator, denominator = item["count"], item["denominator"]
        rate = f"{numerator / denominator:.0%}" if denominator else "暂无"
        col.metric(label, f"{numerator}/{denominator}", help=f"完成比例：{rate}。学生修订以已教师复核案例为分母，其余以当前筛选案例数为分母。")
    st.caption("这是流程完成情况，不代表能力提升或诊断准确率；新案例上的独立分析需要另行评价。")
    if rows:
        with st.expander("查看阶段完成明细"):
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            st.download_button("导出阶段完成明细", pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"), "learning_progress.csv", "text/csv")


def render_teacher_dashboard(records_by_id, all_records):
    dashboard_df, column_mapping, load_error = load_teacher_dashboard_data()
    filtered_df = pd.DataFrame()
    consistency_df = pd.DataFrame()
    reason_summary_df = pd.DataFrame(columns=["失败原因", "次数", "已确认数", "未确认数"])

    with st.container(border=False, key="pcr_teacher_overview_section"):
        render_teacher_section_header(
            "班级实验记录概览",
            "按当前范围汇总学生诊断记录、复核进度和近期提交情况。",
        )
        if load_error:
            st.warning(load_error)

        filter_cols = st.columns([1, 1, 1.8] if column_mapping.get("class") else [1, 1.8])
        with filter_cols[0]:
            time_scope = st.selectbox(
                "统计时间范围",
                list(TIME_SCOPE_OPTIONS.keys()),
                index=1,
                key="teacher_dashboard_time_scope",
            )

        class_filter = "全部班级"
        if column_mapping.get("class"):
            class_options = ["全部班级"]
            if not dashboard_df.empty:
                class_values = sorted(
                    {
                        normalize_display_text(value, default="未填写")
                        for value in dashboard_df["_class_name"].tolist()
                        if normalize_display_text(value, default="未填写")
                    }
                )
                class_options.extend(class_values)
            with filter_cols[1]:
                class_filter = st.selectbox("班级筛选", class_options, key="teacher_dashboard_class_filter")
        with filter_cols[-1]:
            st.caption("筛选只影响本页概览和洞察，不会改动历史记录。")

        class_scoped_df, filtered_df, time_filter_available = apply_dashboard_filters(
            dashboard_df,
            column_mapping,
            time_scope,
            class_filter,
        )

        if not time_filter_available:
            st.caption("未识别到可用时间字段，时间范围筛选已自动降级为“全部数据”，最近 30 天指标显示为“无法统计”。")

        origins = ["真实课堂", "未标注", "全部（混合来源）"]
        origin = st.selectbox("统计记录来源", origins, format_func=lambda v: {"真实课堂": "课堂记录", "未标注": "待核实", "全部（混合来源）": "全部记录"}[v], key="teacher_dashboard_origin")
        if "data_origin" in filtered_df.columns and origin != "全部（混合来源）":
            filtered_df = filtered_df[filtered_df["data_origin"].fillna("未标注").replace("", "未标注") == origin].copy()
            class_scoped_df = class_scoped_df[class_scoped_df["data_origin"].fillna("未标注").replace("", "未标注") == origin].copy()
        st.caption("统计仅反映课堂记录；历史记录的来源可在复核时确认。")
        metrics = compute_dashboard_stats(filtered_df, class_scoped_df, column_mapping)
        render_teacher_kpi_cards(metrics)
        st.markdown('<div class="pcr-teacher-overview-bottom-spacer"></div>', unsafe_allow_html=True)

    render_learning_progress(filtered_df)

    if dashboard_df.empty:
        with st.container(border=False):
            render_teacher_section_header(
                "教学诊断洞察",
                "当学生提交更多记录后，这里会展示一致性和高频失败原因。",
            )
            insight_left, insight_right = st.columns(2)
            with insight_left:
                render_dashboard_empty_state(
                    "暂无可展示数据",
                    "当前还没有历史诊断记录，待学生提交后自动生成统计洞察。",
                    min_height_rem=7.2,
                )
            with insight_right:
                render_dashboard_empty_state(
                    "暂无可展示数据",
                    "有记录后，这里会展示高频失败原因 Top 5。",
                    min_height_rem=7.2,
                )
        return

    if filtered_df.empty:
        with st.container(border=False):
            render_teacher_section_header(
                "教学诊断洞察",
                "当前筛选条件下暂无记录，可调整筛选条件后查看。",
            )
            render_dashboard_empty_state(
                "暂无可展示数据",
                "当前筛选条件下暂无记录，可调整统计时间范围或班级后查看。",
                min_height_rem=7.2,
            )
        return

    consistency_df = build_consistency_dataframe(filtered_df, column_mapping)
    consistency_stats = compute_consistency_stats(consistency_df)
    reason_summary_df = build_reason_summary(filtered_df)

    with st.container(border=False):
        render_teacher_section_header(
            "教学诊断洞察",
            "对照系统判断和教师复核结果，观察课堂实验中的高频异常来源。",
        )
        insight_left, insight_right = st.columns(2)
        with insight_left:
            st.markdown('<div class="pcr-teacher-insight-card">', unsafe_allow_html=True)
            st.markdown('<div class="pcr-teacher-insight-title">系统判断与教师确认一致性</div>', unsafe_allow_html=True)
            render_consistency_insight_card(consistency_stats, consistency_df)
            st.markdown("</div>", unsafe_allow_html=True)
        with insight_right:
            st.markdown('<div class="pcr-teacher-insight-card">', unsafe_allow_html=True)
            st.markdown('<div class="pcr-teacher-insight-title">高频失败原因 Top 5</div>', unsafe_allow_html=True)
            render_top_reason_bars(reason_summary_df, top_n=5)
            st.markdown("</div>", unsafe_allow_html=True)

    with st.container(border=False):
        render_teacher_section_header(
            "近期需关注记录",
            "优先显示待复核记录，其次显示系统判断与教师确认不一致的案例。",
        )
        render_recent_attention_records(all_records, limit=3)


def extract_cause_text(candidate_text):
    """从候选文本中提取原因名称"""
    text = str(candidate_text or "").strip()
    m = re.match(r"^\d+\.\s*(.*?)\s*\(总分:[^)]+\)$", text)
    if m:
        return m.group(1).strip()
    return text


def main():
    ensure_page_config("教师复核与案例看板")
    init_access_state()
    if not st.session_state.get("teacher_verified"):
        apply_common_styles(theme="teacher")
        st.session_state["current_role"] = "home"
        render_page_hero(
            "教师复核与案例看板",
            "当前页面需要先从首页教师入口完成访问码验证。",
            "教师复核",
        )
        render_entry_guard("教师端")
        return

    init_database()
    apply_common_styles(theme="teacher")
    inject_teacher_dashboard_layout_styles()
    st.session_state["current_role"] = "teacher"

    # 强制清空缓存 + 重新加载最新记录（根治状态错乱）

    records = [record for record in load_recent_records(limit=5000) if is_classroom_record(record)]
    records_by_id = build_records_by_id(records)

    render_teacher_page_header(len(records))

    workspace = st.radio("教师工作区", ["独立复核", "课堂任务", "课程方案", "复测记录", "教学建议", "图像评估", "常规案例复核"], horizontal=True, key="teacher_workspace")
    if workspace != "常规案例复核":
        teaching_ui.render_teacher_workspace(DB_PATH, workspace, records)
        return
    teaching_workflow.mark_many_exposed(DB_PATH, [r["id"] for r in records], True)
    st.caption("本工作区显示系统建议；进入后已有案例不再补记为未看建议的独立判断。")
    render_teacher_dashboard(records_by_id, records)

    with st.container(border=True):
        render_teacher_section_header(
            "案例复核队列",
            "按筛选条件查看学生实验记录，并在详情中完成教师复核确认。",
        )

        if not records:
            render_dashboard_empty_state(
                "暂无可展示数据",
                "当前还没有学生诊断记录，待学生提交后会在这里形成案例复核队列。",
                min_height_rem=6.2,
            )
            return

        records_df = build_teacher_records_dataframe(records)
        filter_options = build_teacher_filter_options(records_df)

        st.markdown('<div class="pcr-teacher-filter-panel">', unsafe_allow_html=True)
        st.markdown('<div class="pcr-filter-hint">按确认状态、异常类型、系统判断、图片和关键词快速定位需要复核的案例。</div>', unsafe_allow_html=True)
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
        with filter_col1:
            confirm_status = st.selectbox(
                "确认状态",
                ["全部", "已确认", "未确认"],
                format_func=lambda value: {"已确认": "已复核", "未确认": "待复核"}.get(value, value),
                key="teacher_history_confirm_status",
            )
        with filter_col2:
            abnormality_filter = "全部"
            if filter_options["显示异常类型筛选"]:
                abnormality_filter = st.selectbox(
                    "异常类型",
                    filter_options["异常类型选项"],
                    key="teacher_history_abnormality_filter",
                )
        with filter_col3:
            system_reason_filter = "全部"
            if filter_options["显示系统判断筛选"]:
                system_reason_filter = st.selectbox(
                    "系统判断",
                    filter_options["系统判断选项"],
                    key="teacher_history_system_reason_filter",
                )
        with filter_col4:
            teacher_reason_filter = "全部"
            if filter_options["显示教师原因筛选"]:
                teacher_reason_filter = st.selectbox(
                    "教师确认",
                    filter_options["教师原因选项"],
                    key="teacher_history_teacher_reason_filter",
                )

        second_filter_cols = st.columns([1.4, 1, 1, 0.72])
        with second_filter_cols[0]:
            keyword = st.text_input(
                "关键词搜索",
                value="",
                placeholder="可搜学生描述、教师备注、Top1/Top2/Top3、教师最终原因等",
                key="teacher_history_keyword",
            )
        with second_filter_cols[1]:
            sort_order = st.selectbox(
                "排序方式",
                ["按提交时间倒序", "按提交时间升序"],
                key="teacher_history_sort_order",
            )
        with second_filter_cols[2]:
            image_filter = st.selectbox(
                "是否有图片",
                ["全部", "有图片", "无图片"],
                key="teacher_history_image_filter",
            )
        with second_filter_cols[3]:
            display_label = st.selectbox(
                "显示条数",
                list(HISTORY_DISPLAY_OPTIONS.keys()),
                index=0,
                key="teacher_history_display_limit",
            )

        quick_filter_cols = st.columns([1, 1, 1, 0.8])
        with quick_filter_cols[0]:
            only_unconfirmed = st.checkbox("只看待复核", key="teacher_history_only_unconfirmed")
        with quick_filter_cols[1]:
            only_top1_mismatch = st.checkbox("只看需关注", key="teacher_history_only_top1_mismatch")
        with quick_filter_cols[2]:
            only_with_image = st.checkbox("只看有图片", key="teacher_history_only_with_image")
        with quick_filter_cols[3]:
            st.button(
                "重置筛选",
                key="teacher_history_reset_filters",
                use_container_width=True,
                on_click=reset_teacher_history_filters,
            )
        st.markdown("</div>", unsafe_allow_html=True)

        filtered_records_df = apply_teacher_record_filters(
            records_df,
            confirm_status=confirm_status,
            abnormality_filter=abnormality_filter,
            system_reason_filter=system_reason_filter,
            teacher_reason_filter=teacher_reason_filter,
            keyword=keyword,
            image_filter=image_filter,
            only_unconfirmed=only_unconfirmed,
            only_top1_mismatch=only_top1_mismatch,
            only_with_image=only_with_image,
            sort_order=sort_order,
            display_limit=HISTORY_DISPLAY_OPTIONS[display_label],
        )

        filtered_count = len(filtered_records_df)
        filtered_confirmed_count = int(filtered_records_df["是否已确认"].sum()) if not filtered_records_df.empty else 0
        filtered_unconfirmed_count = filtered_count - filtered_confirmed_count
        filtered_image_count = int(filtered_records_df["是否有图片"].sum()) if not filtered_records_df.empty else 0
        st.caption(
            f"当前共筛选出 {filtered_count} 条记录，其中已复核 {filtered_confirmed_count} 条，待复核 {filtered_unconfirmed_count} 条，含图片 {filtered_image_count} 条。"
        )

        if filtered_records_df.empty:
            render_dashboard_empty_state(
                "暂无可展示数据",
                "当前筛选条件下暂无记录，可调整筛选条件后查看。",
                min_height_rem=5.6,
            )
            return

        display_records = [records[int(idx)] for idx in filtered_records_df["record_index"].tolist()]
        render_case_record_list(display_records, records, list_key_prefix="history")


def render_top_reason_rankings(reason_summary_df, top_n=5):
    """用横向排名条替代默认柱图，避免中文长标签挤压。"""
    top_df = reason_summary_df[["失败原因", "次数"]].head(top_n).copy()
    if top_df.empty:
        st.info("当前筛选范围内暂无可汇总的失败原因数据。")
        return

    max_count = max(int(top_df["次数"].max()), 1)
    for rank, row in enumerate(top_df.itertuples(index=False), 1):
        reason = str(row[0])
        count = int(row[1])
        progress_value = count / max_count

        with st.container(border=True):
            rank_col, reason_col, count_col = st.columns([0.16, 0.58, 0.26])
            with rank_col:
                st.markdown(f"**TOP {rank}**")
            with reason_col:
                st.markdown(f"**{reason}**")
            with count_col:
                st.markdown(f"**{count} 次**")
            st.caption(f"相对最高频原因占比 {progress_value:.0%}")
            st.markdown(
                f"""
                <div style="margin-top: 0.45rem;">
                    <div style="width: 100%; height: 14px; background: var(--ds-subtle); border-radius: 999px; overflow: hidden;">
                        <div style="width: {progress_value * 100:.1f}%; height: 14px; background: var(--ds-primary); border-radius: 999px;"></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_top_reason_visualization(reason_summary_df, top_n=5):
    """用横向排名条展示高频失败原因，避免图表在类别文本较长时挤压。"""
    top_df = reason_summary_df[["失败原因", "次数"]].head(top_n).copy()
    if top_df.empty:
        st.info("当前筛选范围内暂无可汇总的失败原因数据。")
        return

    render_top_reason_rankings(reason_summary_df, top_n=top_n)


def open_dashboard_card(min_height_rem):
    """保留接口但不再注入额外高度容器，避免卡片顶部出现空白。"""
    return None


def close_dashboard_card():
    return None


if __name__ == "__main__":
    main()
