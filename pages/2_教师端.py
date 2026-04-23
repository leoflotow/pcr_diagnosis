# -*- coding: utf-8 -*-
"""
教师端页面
"""

import os
import re
import sqlite3

import altair as alt
import pandas as pd
import streamlit as st

from core import (
    DB_PATH,
    apply_common_styles,
    ensure_page_config,
    init_access_state,
    init_database,
    load_recent_records,
    parse_all_candidates,
    parse_top1_result,
    render_diagnosis_quality_block,
    render_entry_guard,
    render_card_title,
    render_page_hero,
    save_teacher_confirmation,
)


def inject_teacher_dashboard_layout_styles():
    """让教师端看板同一行的卡片尽量等高。"""
    st.markdown(
        """
        <style>
        [data-testid="stHorizontalBlock"] [data-testid="column"] > div {
            height: 100%;
        }
        [data-testid="stHorizontalBlock"] div[data-testid="stVerticalBlockBorderWrapper"] {
            height: 100%;
        }
        [data-testid="stHorizontalBlock"] div[data-testid="stVerticalBlockBorderWrapper"] > div {
            height: 100%;
            display: flex;
            flex-direction: column;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
    return str(value or "").strip()


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
    """对原因标签做轻量归一化，减少表述差异带来的误判"""
    text = normalize_text(value)
    if not text or text in {"-", "未确认", "未填写", "未知"}:
        return ""

    compact_text = re.sub(r"\s+", "", text).lower()
    compact_text = re.sub(r"[，。；、,.;（）()\-]", "", compact_text)

    for canonical_label, aliases in REASON_NORMALIZATION_RULES:
        normalized_aliases = [re.sub(r"\s+", "", alias).lower() for alias in aliases]
        if compact_text in normalized_aliases:
            return canonical_label
        if any(alias in compact_text for alias in normalized_aliases):
            return canonical_label

    return text.strip()


def is_confirmed_cause(value):
    text = normalize_text(value)
    return text not in {"", "-", "未确认", "未填写"}


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
    """把历史记录列表转成便于筛选和排序的 DataFrame"""
    rows = []
    for index, record in enumerate(records):
        teacher_final = normalize_text(record.get("教师最终原因"))
        is_confirmed = is_confirmed_cause(teacher_final)
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
            "是否已确认": is_confirmed,
            "是否未确认": not is_confirmed,
            "是否有图片": has_image,
            "系统 Top1": normalize_display_text(top1, default="-"),
            "系统 Top2": normalize_display_text(top2, default="-"),
            "系统 Top3": normalize_display_text(top3, default="-"),
            "Top1 是否不一致": bool(is_confirmed and teacher_final_normalized and top1_normalized and teacher_final_normalized != top1_normalized),
            "关键词文本": build_record_keyword_text(record),
            "_sort_time": pd.to_datetime(record.get("提交时间"), errors="coerce"),
        })

    return pd.DataFrame(rows)


def build_teacher_filter_options(records_df):
    """为历史记录筛选区生成动态选项"""
    options = {
        "异常类型选项": ["全部"],
        "教师原因选项": ["全部"],
        "显示异常类型筛选": False,
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
    teacher_reason_filter,
    keyword,
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

    if teacher_reason_filter != "全部" and "教师最终原因" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["教师最终原因"] == teacher_reason_filter]

    keyword_text = normalize_keyword_text(keyword)
    if keyword_text:
        filtered_df = filtered_df[filtered_df["关键词文本"].str.contains(keyword_text, na=False)]

    if only_unconfirmed:
        filtered_df = filtered_df[filtered_df["是否未确认"]]

    if only_top1_mismatch and "Top1 是否不一致" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["Top1 是否不一致"]]

    if only_with_image:
        filtered_df = filtered_df[filtered_df["是否有图片"]]

    filtered_df = sort_teacher_records(filtered_df, sort_order)
    if display_limit is not None:
        filtered_df = filtered_df.head(display_limit)
    return filtered_df


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
        df["_confirmed"] = df[teacher_col].apply(is_confirmed_cause)
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
        is_confirmed = is_confirmed_cause(teacher_reason_raw)
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
    confirmed_df = consistency_df[consistency_df["是否已确认"]] if not consistency_df.empty else consistency_df
    comparable_df = confirmed_df[confirmed_df["是否可比较"]] if not confirmed_df.empty else confirmed_df

    confirmed_count = int(len(confirmed_df))
    comparable_count = int(len(comparable_df))
    unable_compare_count = int(len(consistency_df[~consistency_df["是否可比较"]])) if not consistency_df.empty else 0

    top1_match_count = int(comparable_df["Top1 是否一致"].sum()) if comparable_count else 0
    top3_hit_count = int(comparable_df["Top3 是否命中"].sum()) if comparable_count else 0

    top1_rate = f"{(top1_match_count / comparable_count) * 100:.1f}%" if comparable_count else "暂无可比较数据"
    top3_rate = f"{(top3_hit_count / comparable_count) * 100:.1f}%" if comparable_count else "暂无可比较数据"

    distribution_df = pd.DataFrame(
        {
            "类别": ["Top1 一致", "Top1 不一致但 Top3 命中", "Top3 也未命中"],
            "案例数": [
                int((comparable_df["一致性分类"] == "Top1 一致").sum()) if comparable_count else 0,
                int((comparable_df["一致性分类"] == "Top1 不一致但 Top3 命中").sum()) if comparable_count else 0,
                int((comparable_df["一致性分类"] == "Top3 也未命中").sum()) if comparable_count else 0,
            ],
        }
    )

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
    is_confirmed = is_confirmed_cause(teacher_final)

    top1, top2, top3 = extract_record_top_reasons(record)
    normalized_teacher = normalize_reason_label(teacher_final)
    normalized_top1 = normalize_reason_label(top1)
    normalized_candidates = [normalize_reason_label(item) for item in [top1, top2, top3] if normalize_reason_label(item)]

    comparable = bool(is_confirmed and normalized_teacher and normalized_candidates)
    top1_match = comparable and normalized_teacher == normalized_top1
    top3_hit = comparable and normalized_teacher in normalized_candidates
    consistency_status = build_case_consistency_status(is_confirmed, comparable, top1_match, top3_hit)

    return {
        "当前状态": "已确认" if is_confirmed else "未确认",
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
        return "该案例尚未完成教师确认，暂不能作为闭环案例使用。"
    if consistency_status == "一致":
        return "该案例中，系统首选判断与教师最终确认一致，可作为有效教学案例沉淀。"
    if consistency_status == "Top3命中但Top1不一致":
        return "该案例中，系统 Top1 判断与教师确认不一致，但 Top3 候选已覆盖真实原因，提示规则排序仍有优化空间。"
    if consistency_status == "未命中":
        return "该案例中，系统候选结果未覆盖教师最终确认原因，可作为规则补充与误判纠偏案例。"
    return "该案例已进入教师确认阶段，但当前记录信息不足，暂无法完成有效闭环比较。"


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
        render_card_title("教师确认反馈闭环", "结构化展示系统判断、教师确认及当前案例闭环状态。")

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
            st.caption("系统置信度、证据摘要见上方“系统 Top1 诊断可信度解读”模块。")
        with compare_right:
            st.markdown("**教师确认侧**")
            st.markdown(f"- 教师最终确认原因：{loop_status['教师最终确认原因']}")
            st.markdown(f"- 教师备注：{loop_status['教师备注']}")
            st.markdown(f"- 教师确认时间：{loop_status['教师确认时间']}")
            st.markdown(f"- 教师是否已完成确认：{loop_status['教师是否已完成确认']}")

        st.markdown(f"**闭环结论：** {summary_text}")
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
        "is_confirmed": is_confirmed_cause(teacher_final),
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
    """渲染相似历史案例回看模块"""
    similar_cases = get_similar_cases(current_record, all_records, limit=5)

    with st.container(border=True):
        render_card_title("可参考的相似历史案例", "基于当前数据库中的结构化字段进行轻量匹配，优先展示已确认案例。")

        if not similar_cases:
            st.info("暂无足够相似的历史案例")
            return

        for index, case_item in enumerate(similar_cases, 1):
            record = case_item["record"]
            teacher_final = normalize_display_text(record.get("教师最终原因"), default="未确认")
            if teacher_final == "未确认":
                teacher_final = "未确认"
            similar_reason_text = "；".join(case_item["reasons"]) if case_item["reasons"] else "结构化字段部分匹配"
            with st.expander(f"{index}. 记录ID {record.get('id', '-')} | {record.get('提交时间', '-')} | 相似度 {case_item['score']}"):
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
    with st.expander(f"展开查看详情（记录ID: {record_id}）"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"- 记录 id：{record_id}")
            st.markdown(f"- 提交时间：{record.get('提交时间', '-')}")
            st.markdown(f"- 实验现象：{record.get('实验现象', '-')}")
            st.markdown(f"- 模板量：{record.get('模板量', '-')}")
            st.markdown(f"- 退火温度：{record.get('退火温度', '-')}")
            st.markdown(f"- 循环数：{record.get('循环数', '-')}")
        with col2:
            st.markdown(f"- 阳性对照是否正常：{record.get('阳性对照是否正常', '-')}")
            st.markdown(f"- 阴性对照是否有带：{record.get('阴性对照是否有带', '-')}")
            st.markdown(f"- Top1 原因：{record.get('Top1 原因', '-')}")
            st.markdown(f"- Top1 分数：{record.get('Top1 分数', '-')}")

        st.markdown(f"- 学生补充描述：{record.get('学生补充描述', '-')}")
        clues = record.get("抽取到的文本线索", [])
        st.markdown(f"- 抽取到的文本线索：{('、'.join(clues)) if clues else '无'}")

        candidates = record.get("候选原因列表", [])
        if len(candidates) > 1:
            for item in candidates[1:]:
                st.markdown(f"- 其他候选原因：{item}")
        else:
            st.markdown("- 其他候选原因：无")

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
            title="系统 Top1 诊断可信度解读",
        )

        render_feedback_loop_block(record)
        render_similar_case_block(record, all_records)

        st.markdown(f"- 教师最终原因：{record.get('教师最终原因', '未确认')}")
        st.markdown(f"- 教师备注：{record.get('教师备注', '-')}")
        st.markdown(f"- 教师确认时间：{record.get('教师确认时间', '-')}")

        img_path = record.get("凝胶图路径", "")
        if img_path and os.path.exists(img_path):
            st.markdown(f"- 图片路径：{img_path}")
            st.image(img_path, caption="历史凝胶图片", use_container_width=True)
        elif img_path:
            st.markdown(f"- 图片路径：{img_path}")
            st.info("图片文件不存在")
        else:
            st.info("无图片")

        with st.container(border=True):
            render_card_title("教师确认", "请选择最终原因并补充备注。")
            candidate_causes = [extract_cause_text(x) for x in candidates if extract_cause_text(x)]
            if not candidate_causes and record.get("Top1 原因"):
                candidate_causes = [record.get("Top1 原因")]
            confirm_options = list(dict.fromkeys(candidate_causes + ["其他/待补充"]))

            with st.form(f"{detail_key_prefix}_teacher_confirm_form_{record_id}"):
                teacher_choice = st.selectbox("教师最终原因", confirm_options, key=f"{detail_key_prefix}_teacher_choice_{record_id}")
                custom_cause = ""
                if teacher_choice == "其他/待补充":
                    custom_cause = st.text_input("请填写教师最终原因", key=f"{detail_key_prefix}_teacher_custom_{record_id}")
                teacher_note = st.text_area("教师备注", height=3, key=f"{detail_key_prefix}_teacher_note_{record_id}")
                save_confirm = st.form_submit_button("保存教师确认结果")

            if save_confirm:
                final_cause = custom_cause.strip() if teacher_choice == "其他/待补充" else teacher_choice
                if not final_cause:
                    st.warning("请选择或填写教师最终原因。")
                else:
                    save_teacher_confirmation(record_id, final_cause, teacher_note.strip())
                    st.success("教师确认已保存")
                    st.rerun()


def render_case_record_list(records_to_render, all_records, list_key_prefix):
    for idx, record in enumerate(records_to_render, 1):
        loop_status = build_feedback_loop_status(record)
        status_class = "pcr-status-ok" if loop_status["当前状态"] == "已确认" else "pcr-status-pending"
        status_label = loop_status["当前状态"]

        st.markdown(
            f"""
            <div class="pcr-sub-card">
                <b>{idx}. {record.get('提交时间', '-')} | {record.get('实验现象', '-')} | Top1: {record.get('Top1 原因', '-')} | 教师确认: {loop_status['教师最终确认原因']} | 一致性: {loop_status['一致性状态']} | {record.get('凝胶图', '无图')}</b>
                <span class="pcr-status-pill {status_class}">{status_label}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        render_case_detail(record, all_records, detail_key_prefix=f"{list_key_prefix}_{record.get('id', idx)}")


def render_stat_linked_case_list(filtered_df, consistency_df, reason_summary_df, records_by_id, all_records):
    with st.container(border=True):
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


def render_teacher_dashboard(records_by_id, all_records):
    dashboard_df, column_mapping, load_error = load_teacher_dashboard_data()
    filtered_df = pd.DataFrame()
    consistency_df = pd.DataFrame()
    reason_summary_df = pd.DataFrame(columns=["失败原因", "次数", "已确认数", "未确认数"])

    with st.container(border=True):
        render_card_title("学情统计看板", "基于历史诊断记录自动汇总，支持按时间范围筛选；存在缺失字段时自动降级显示。")

        if load_error:
            st.warning(load_error)

        filter_cols = st.columns(2 if column_mapping.get("class") else 1)
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

        class_scoped_df, filtered_df, time_filter_available = apply_dashboard_filters(
            dashboard_df,
            column_mapping,
            time_scope,
            class_filter,
        )

        if not time_filter_available:
            st.caption("未识别到可用时间字段，时间范围筛选已自动降级为“全部数据”，最近 30 天指标显示为“无法统计”。")

        metrics = compute_dashboard_stats(filtered_df, class_scoped_df, column_mapping)
        metric_cols = st.columns(4)
        for col, (label, value) in zip(metric_cols, metrics.items()):
            col.metric(label, value)
        consistency_stats = {}
        if dashboard_df.empty:
            st.info("暂无历史诊断数据，学情统计看板已就绪，待学生提交记录后自动更新。")
        else:
            if filtered_df.empty:
                st.info("当前筛选条件下暂无可统计数据。")

            render_card_title("系统判断 vs 教师确认一致率", "复用当前筛选结果统计 Top1 一致率、Top3 命中率及最近一致/不一致案例。")
            consistency_df = build_consistency_dataframe(filtered_df, column_mapping)
            consistency_stats = compute_consistency_stats(consistency_df)

            consistency_metric_cols = st.columns(4)
            consistency_metric_cols[0].metric("已确认案例数", consistency_stats["已确认案例数"])
            consistency_metric_cols[1].metric("Top1 一致率", consistency_stats["Top1 一致率"])
            consistency_metric_cols[2].metric("Top3 命中率", consistency_stats["Top3 命中率"])
            consistency_metric_cols[3].metric("无法比较案例数", consistency_stats["无法比较案例数"])

            if consistency_stats["可比较已确认案例数"] == 0:
                st.info("当前筛选范围内暂无可比较的已确认案例。")
            else:
                st.caption(f"一致率分母为当前筛选范围内可比较的已确认案例数：{consistency_stats['可比较已确认案例数']} 条。")

        dashboard_col_left, dashboard_col_right = st.columns(2)

        with dashboard_col_left:
            with st.container(border=True):
                open_dashboard_card(13.5)
                render_card_title("系统判断与教师复核一致性分布", "统计范围：当前筛选条件下，已完成教师复核且可进行一致性比对的案例。")
                distribution_df = consistency_stats["一致性分布"]
                if distribution_df["案例数"].sum() == 0:
                    st.info("当前筛选范围内暂无可用于一致性分析的已确认案例。")
                else:
                    st.bar_chart(distribution_df.set_index("类别"))
                    st.dataframe(distribution_df, use_container_width=True, hide_index=True)
                close_dashboard_card()

        with dashboard_col_right:
            with st.container(border=True):
                open_dashboard_card(13.5)
                render_card_title("高频失败原因 Top 5", "统计规则：已完成教师复核的记录采用教师最终确认原因；未复核记录采用系统首位诊断结果。")
                reason_summary_df = build_reason_summary(filtered_df)
                if reason_summary_df.empty:
                    st.info("当前筛选范围内暂无可汇总的失败原因数据。")
                else:
                    render_top_reason_visualization(reason_summary_df, top_n=5)
                close_dashboard_card()

        case_col_left, case_col_right = st.columns(2)
        with case_col_left:
            with st.container(border=True):
                open_dashboard_card(9.5)
                render_card_title("最近不一致案例", "展示教师已完成复核、但系统首位判断与教师结论不一致的近期案例。")
                mismatch_df = get_recent_mismatch_cases(consistency_df, limit=10)
                if mismatch_df.empty:
                    st.info("当前筛选范围内暂无近期不一致案例。")
                else:
                    st.dataframe(mismatch_df, use_container_width=True, hide_index=True)
                close_dashboard_card()

        with case_col_right:
            with st.container(border=True):
                open_dashboard_card(9.5)
                render_card_title("最近一致案例", "展示系统首位判断与教师最终确认一致的近期案例。")
                match_df = get_recent_match_cases(consistency_df, limit=10)
                if match_df.empty:
                    st.info("当前筛选范围内暂无近期一致案例。")
                else:
                    st.dataframe(match_df, use_container_width=True, hide_index=True)
                close_dashboard_card()

        detail_col_left, detail_col_right = st.columns(2)
        with detail_col_left:
            with st.container(border=True):
                open_dashboard_card(10.5)
                render_card_title("对照异常统计", "优先读取结构化记录；缺失时自动回退到原始文本关键词匹配。")
                control_stats = compute_control_abnormal_stats(filtered_df, column_mapping)
                negative_count = control_stats.get("negative_control_band_count")
                positive_count = control_stats.get("positive_control_failure_count")
                if negative_count is None and positive_count is None:
                    st.info("当前筛选范围内暂无可用于对照异常统计的数据。")
                else:
                    control_cols = st.columns(2)
                    control_cols[0].metric("阴性对照有带", negative_count if negative_count is not None else "暂无可用数据")
                    control_cols[1].metric("阳性对照无带", positive_count if positive_count is not None else "暂无可用数据")
                close_dashboard_card()

        with detail_col_right:
            with st.container(border=True):
                open_dashboard_card(10.5)
                render_card_title("失败原因聚合明细", "按当前筛选条件聚合统计，并按次数降序展示前 10 项。")
                if reason_summary_df.empty:
                    st.info("当前筛选范围内暂无可展示的聚合结果。")
                else:
                    st.dataframe(reason_summary_df.head(10), use_container_width=True, hide_index=True)
                close_dashboard_card()

    render_stat_linked_case_list(filtered_df, consistency_df, reason_summary_df, records_by_id, all_records)


def extract_cause_text(candidate_text):
    """从候选文本中提取原因名称"""
    text = str(candidate_text or "").strip()
    m = re.match(r"^\d+\.\s*(.*?)\s*\(总分:[^)]+\)$", text)
    if m:
        return m.group(1).strip()
    return text


def main():
    ensure_page_config("教师端案例复盘台")
    init_access_state()
    if not st.session_state.get("teacher_verified"):
        apply_common_styles(theme="teacher")
        st.session_state["current_role"] = "home"
        render_page_hero(
            "教师端案例复盘台",
            "当前页面需要先从首页教师入口完成访问码验证。",
            "教师端",
        )
        render_entry_guard("教师端")
        return

    init_database()
    apply_common_styles(theme="teacher")
    inject_teacher_dashboard_layout_styles()
    st.session_state["current_role"] = "teacher"
    render_page_hero(
        "教师端案例复盘台",
        "查看学生历史案例，完成最终原因确认与教学备注沉淀。",
        "教师端",
    )

    records = load_recent_records(limit=5000)
    records_by_id = build_records_by_id(records)

    render_teacher_dashboard(records_by_id, records)

    with st.container(border=True):
        render_card_title("最近诊断记录", "可展开每条记录查看完整信息并进行教师确认。")

        if not records:
            st.info("暂无历史诊断记录")
            return

        records_df = build_teacher_records_dataframe(records)
        filter_options = build_teacher_filter_options(records_df)

        st.markdown("**筛选区**")
        render_card_title("筛选与快速定位", "先缩小记录范围，再进入详情查看与教师确认。")
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            confirm_status = st.selectbox(
                "确认状态",
                ["全部", "已确认", "未确认"],
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
            teacher_reason_filter = "全部"
            if filter_options["显示教师原因筛选"]:
                teacher_reason_filter = st.selectbox(
                    "教师最终原因",
                    filter_options["教师原因选项"],
                    key="teacher_history_teacher_reason_filter",
                )

        second_filter_cols = st.columns(3)
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
            display_label = st.selectbox(
                "显示条数",
                list(HISTORY_DISPLAY_OPTIONS.keys()),
                index=1,
                key="teacher_history_display_limit",
            )

        quick_filter_cols = st.columns(3)
        with quick_filter_cols[0]:
            only_unconfirmed = st.checkbox("仅看未确认案例", key="teacher_history_only_unconfirmed")
        with quick_filter_cols[1]:
            only_top1_mismatch = st.checkbox("仅看 Top1 不一致案例", key="teacher_history_only_top1_mismatch")
        with quick_filter_cols[2]:
            only_with_image = st.checkbox("仅看有图片案例", key="teacher_history_only_with_image")

        filtered_records_df = apply_teacher_record_filters(
            records_df,
            confirm_status=confirm_status,
            abnormality_filter=abnormality_filter,
            teacher_reason_filter=teacher_reason_filter,
            keyword=keyword,
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
            f"当前共筛选出 {filtered_count} 条记录，其中已确认 {filtered_confirmed_count} 条，未确认 {filtered_unconfirmed_count} 条，含图片 {filtered_image_count} 条。"
        )

        if filtered_records_df.empty:
            st.info("当前筛选条件下暂无历史记录。")
            return

        st.markdown("**案例列表**")
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
                    <div style="width: 100%; height: 14px; background: #e5eefb; border-radius: 999px; overflow: hidden;">
                        <div style="width: {progress_value * 100:.1f}%; height: 14px; background: linear-gradient(90deg, #0f766e 0%, #14b8a6 100%); border-radius: 999px;"></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_top_reason_visualization(reason_summary_df, top_n=5):
    """类别足够时用环形图，类别过少时回退到横向排名条。"""
    top_df = reason_summary_df[["失败原因", "次数"]].head(top_n).copy()
    if top_df.empty:
        st.info("当前筛选范围内暂无可汇总的失败原因数据。")
        return

    chart_df = top_df.copy()
    chart_df["占比"] = chart_df["次数"] / chart_df["次数"].sum()

    if len(chart_df) >= 3:
        color_scale = alt.Scale(
            range=["#0f766e", "#0ea5e9", "#6366f1", "#14b8a6", "#84cc16"]
        )
        donut_chart = (
            alt.Chart(chart_df)
            .mark_arc(innerRadius=68, outerRadius=115)
            .encode(
                theta=alt.Theta("次数:Q"),
                color=alt.Color("失败原因:N", legend=alt.Legend(title="失败原因"), scale=color_scale),
                tooltip=[
                    alt.Tooltip("失败原因:N", title="失败原因"),
                    alt.Tooltip("次数:Q", title="次数"),
                    alt.Tooltip("占比:Q", title="占比", format=".1%"),
                ],
            )
            .properties(height=280)
        )

        text_chart = (
            alt.Chart(pd.DataFrame({"label": ["失败原因构成"]}))
            .mark_text(fontSize=15, fontWeight="bold", color="#0f172a")
            .encode(text="label:N")
        )

        st.altair_chart(donut_chart + text_chart, use_container_width=True)
        st.dataframe(
            chart_df.assign(占比=chart_df["占比"].map(lambda x: f"{x:.1%}")),
            use_container_width=True,
            hide_index=True,
        )
    else:
        render_top_reason_rankings(reason_summary_df, top_n=top_n)


def open_dashboard_card(min_height_rem):
    """保留接口但不再注入额外高度容器，避免卡片顶部出现空白。"""
    return None


def close_dashboard_card():
    return None


if __name__ == "__main__":
    main()
