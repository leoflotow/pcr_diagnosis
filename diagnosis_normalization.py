# -*- coding: utf-8 -*-
"""
旧字段 -> 新规则标准字段的标准化映射层。

本模块只负责：
1. 兼容当前项目已有输入 / 历史记录字段名
2. 归一化为新版规则矩阵需要的标准字段
3. 为后续新版规则引擎接入提供统一 normalized_case
"""

import json
import re


UNKNOWN_LABEL = "unknown"

TEMPLATE_LOW_THRESHOLD = 1.0
TEMPLATE_HIGH_THRESHOLD = 5.0
ANNEALING_TEMP_DELTA_THRESHOLD = 2.0

STANDARD_TEXT_HINTS = [
    "污染",
    "普通台面配液",
    "模板低",
    "模板差",
    "引物问题",
    "漏加试剂",
    "退火偏低",
    "退火偏高",
    "循环偏少",
    "循环偏多",
    "电泳问题",
    "上样过量",
    "上样不足",
    "操作不规范",
]

STANDARD_BAND_PATTERNS = {
    "no_band",
    "weak",
    "multiple",
    "unexpected_size",
    "smear",
    "primer_dimer_like",
    "single_clear",
    "distorted",
    UNKNOWN_LABEL,
}


def is_missing_value(value):
    if value is None:
        return True
    text = str(value).strip()
    return text in {"", "-", "None", "nan", "NaN", "null", "NULL"}


def safe_to_float(value, default=None):
    try:
        if is_missing_value(value):
            return default
        return float(value)
    except Exception:
        return default


def get_raw_field(raw_case, field_names):
    if not isinstance(raw_case, dict):
        return None

    fallback_value = None
    for field_name in field_names:
        if field_name not in raw_case:
            continue
        value = raw_case.get(field_name)
        if not is_missing_value(value):
            return value
        if fallback_value is None:
            fallback_value = value
    return fallback_value


def _dedupe_keep_order(values):
    normalized = []
    seen = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _split_hint_values(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if not is_missing_value(item)]

    text = str(value).strip()
    if not text:
        return []

    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if not is_missing_value(item)]
        except Exception:
            pass

    parts = re.split(r"[|,，、;/；\n]+", text)
    return [part.strip() for part in parts if part and part.strip()]


def normalize_abnormality(raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return UNKNOWN_LABEL

    alias_map = {
        "无条带": "无条带",
        "条带弱": "条带弱",
        "弱带": "条带弱",
        "多条带": "多条带或非特异扩增",
        "非特异扩增": "多条带或非特异扩增",
        "多条带或非特异扩增": "多条带或非特异扩增",
        "条带大小不对": "条带大小不对",
        "大小异常": "条带大小不对",
        "条带大小异常": "条带大小不对",
        "条带拖尾": "条带拖尾或弥散",
        "条带弥散": "条带拖尾或弥散",
        "条带拖尾或弥散": "条带拖尾或弥散",
        "阴性对照有带": "阴性对照有带",
        "阳性对照无带": "阳性对照无带",
        "条带畸形": "条带畸形",
        "条带过宽": "条带畸形",
        "横向扩散": "条带畸形",
        "条带位置偏移": "条带畸形",
        "弯曲条带": "条带畸形"
    }
    return alias_map.get(text, UNKNOWN_LABEL)


def normalize_positive_control(raw_positive_control_normal):
    if isinstance(raw_positive_control_normal, bool):
        return "正常" if raw_positive_control_normal else "无带"

    text = str(raw_positive_control_normal or "").strip()
    if text in {"1", "true", "True", "是", "正常"}:
        return "正常"
    if text in {"0", "false", "False", "否", "异常"}:
        return "无带"
    return UNKNOWN_LABEL


def normalize_negative_control(raw_negative_control_band):
    if isinstance(raw_negative_control_band, bool):
        return "目标大小相近带" if raw_negative_control_band else "无带"

    text = str(raw_negative_control_band or "").strip()
    if text in {"0", "false", "False", "否", "无"}:
        return "无带"
    if text in {"1", "true", "True", "是", "有"}:
        return "目标大小相近带"
    return UNKNOWN_LABEL


def _normalize_hint_token(raw_hint, student_text=""):
    hint = str(raw_hint or "").strip()
    if not hint:
        return []

    token_map = {
        "污染": ["污染", "气溶胶污染", "交叉污染"],
        "普通台面配液": ["普通台面配液", "台面配液", "开放台面配液"],
        "模板低": ["模板低", "模板量不足", "模板少", "模板浓度低", "模板太少"],
        "模板差": ["模板差", "模板质量差", "模板降解", "模板不纯", "有抑制物", "含抑制物"],
        "引物问题": ["引物问题", "引物失效", "引物降解", "引物设计问题"],
        "漏加试剂": ["漏加试剂", "体系漏加", "PCR体系问题", "漏加"],
        "退火偏低": ["退火偏低", "退火温度偏低", "退火温度过低"],
        "退火偏高": ["退火偏高", "退火温度偏高", "退火温度过高"],
        "循环偏少": ["循环偏少", "循环数少", "循环过少"],
        "循环偏多": ["循环偏多", "循环数多", "循环过多"],
        "电泳问题": ["电泳问题", "跑胶问题", "凝胶问题"],
        "上样过量": ["上样过量", "上样太多"],
        "上样不足": ["上样不足", "上样太少"],
        "操作不规范": ["操作不规范", "操作失误", "操作有误"],
    }

    for canonical, aliases in token_map.items():
        if hint == canonical or hint in aliases:
            return [canonical]

    if hint == "退火温度问题":
        text = str(student_text or "")
        if any(keyword in text for keyword in ["退火偏低", "退火低", "温度低", "太低"]):
            return ["退火偏低"]
        if any(keyword in text for keyword in ["退火偏高", "退火高", "温度高", "太高"]):
            return ["退火偏高"]
        return []

    return []


def _extract_hints_from_text(student_text):
    text = str(student_text or "").strip().lower()
    if not text:
        return []

    keyword_rules = {
        "污染": ["污染", "contam", "交叉污染", "气溶胶"],
        "普通台面配液": ["普通台面", "台面配液", "开放台面", "普通实验台"],
        "模板低": ["模板量不足", "模板少", "模板低", "模板浓度低", "模板太少"],
        "模板差": ["模板差", "模板降解", "模板不纯", "纯度差", "有抑制物", "含抑制物"],
        "引物问题": ["引物问题", "引物失效", "引物降解", "primer"],
        "漏加试剂": ["漏加试剂", "漏加", "忘加", "没加", "体系漏加"],
        "退火偏低": ["退火偏低", "退火温度低", "温度偏低", "退火低", "温度太低"],
        "退火偏高": ["退火偏高", "退火温度高", "温度偏高", "退火高", "温度太高"],
        "循环偏少": ["循环偏少", "循环少", "循环数少", "循环不够"],
        "循环偏多": ["循环偏多", "循环多", "循环数多", "循环过多"],
        "电泳问题": ["电泳问题", "跑胶问题", "凝胶问题", "电泳条件"],
        "上样过量": ["上样过量", "上样太多", "样品过量"],
        "上样不足": ["上样不足", "上样太少"],
        "操作不规范": ["操作不规范", "操作失误", "操作有误", "未换枪头", "枪头混用", "流程不规范"],
    }

    hints = []
    for canonical, keywords in keyword_rules.items():
        if any(keyword in text for keyword in keywords):
            hints.append(canonical)
    return _dedupe_keep_order(hints)


def normalize_text_hints(student_text, extracted_hints):
    normalized = []

    for raw_hint in _split_hint_values(extracted_hints):
        normalized.extend(_normalize_hint_token(raw_hint, student_text=student_text))

    normalized.extend(_extract_hints_from_text(student_text))
    normalized = _dedupe_keep_order(normalized)
    return [hint for hint in normalized if hint in STANDARD_TEXT_HINTS]


def normalize_template_condition(template_value, text_hints):
    text_hints = text_hints or []
    if "模板差" in text_hints:
        return "降解或不纯"

    template_num = safe_to_float(template_value, None)
    if template_num is None:
        return UNKNOWN_LABEL
    if template_num < TEMPLATE_LOW_THRESHOLD:
        return "偏低"
    if template_num > TEMPLATE_HIGH_THRESHOLD:
        return "偏高"
    return "正常"


def normalize_annealing_temp_condition(current_temp, recommended_temp, text_hints):
    text_hints = text_hints or []
    if "退火偏低" in text_hints:
        return "偏低"
    if "退火偏高" in text_hints:
        return "偏高"

    current_temp_num = safe_to_float(current_temp, None)
    recommended_temp_num = safe_to_float(recommended_temp, None)
    if current_temp_num is None or recommended_temp_num is None:
        return UNKNOWN_LABEL

    delta = current_temp_num - recommended_temp_num
    if delta <= -ANNEALING_TEMP_DELTA_THRESHOLD:
        return "偏低"
    if delta >= ANNEALING_TEMP_DELTA_THRESHOLD:
        return "偏高"
    return "正常"


def infer_band_pattern_from_abnormality(abnormality):
    mapping = {
        "无条带": "no_band",
        "条带弱": "weak",
        "多条带或非特异扩增": "multiple",
        "条带大小不对": "unexpected_size",
        "条带拖尾或弥散": "smear",
        "阳性对照无带": "no_band",
        "条带畸形": "distorted",
    }
    return mapping.get(abnormality, UNKNOWN_LABEL)


def _normalize_band_pattern(raw_value):
    text = str(raw_value or "").strip()
    return text if text in STANDARD_BAND_PATTERNS else UNKNOWN_LABEL


def build_normalized_case(raw_case):
    raw_case = raw_case or {}

    abnormality_raw = get_raw_field(raw_case, [
        "abnormality", "phenomenon", "issue_type", "observation", "实验现象", "异常现象"
    ])
    description = get_raw_field(raw_case, [
        "description", "student_text", "student_description", "note", "comment",
        "raw_description", "remark", "学生补充描述", "异常描述"
    ])
    extracted_hints = get_raw_field(raw_case, [
        "extracted_hints", "text_clues", "ai_hints", "text_hint", "text_clues_raw",
        "文本线索", "抽取到的文本线索"
    ])
    positive_control_raw = get_raw_field(raw_case, [
        "positive_control_normal", "positive_control", "阳性对照是否正常", "阳性对照"
    ])
    negative_control_raw = get_raw_field(raw_case, [
        "negative_control_band", "negative_control", "阴性对照是否有带", "阴性对照"
    ])
    template_value = get_raw_field(raw_case, [
        "template_amount", "template", "template_concentration", "模板量", "模板浓度"
    ])
    current_temp = get_raw_field(raw_case, [
        "annealing_temp", "pcr_temp", "current_annealing_temp", "退火温度"
    ])
    recommended_temp = get_raw_field(raw_case, [
        "recommended_temp", "recommended_annealing_temp", "target_annealing_temp",
        "建议退火温度", "推荐退火温度"
    ])
    band_pattern_raw = get_raw_field(raw_case, [
        "band_pattern", "band_type", "条带模式", "条带形态"
    ])

    abnormality = normalize_abnormality(abnormality_raw)
    text_hints = normalize_text_hints(description, extracted_hints)
    positive_control = normalize_positive_control(positive_control_raw)
    negative_control = normalize_negative_control(negative_control_raw)
    template_condition = normalize_template_condition(template_value, text_hints)
    annealing_temp_condition = normalize_annealing_temp_condition(current_temp, recommended_temp, text_hints)
    band_pattern = _normalize_band_pattern(band_pattern_raw)
    if band_pattern == UNKNOWN_LABEL:
        band_pattern = infer_band_pattern_from_abnormality(abnormality)

    return {
        "abnormality": abnormality,
        "band_pattern": band_pattern,
        "positive_control": positive_control,
        "negative_control": negative_control,
        "template_condition": template_condition,
        "annealing_temp_condition": annealing_temp_condition,
        "text_hint": text_hints,
    }


def explain_normalized_case(raw_case):
    raw_case = raw_case or {}
    return {
        "raw_case": raw_case,
        "normalized_case": build_normalized_case(raw_case),
    }
