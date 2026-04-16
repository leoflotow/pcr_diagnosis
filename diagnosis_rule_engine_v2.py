# -*- coding: utf-8 -*-
"""
新版规则矩阵并行评估引擎。

说明：
- 基于 normalized_case 读取新版 rules.csv + rule_combos.csv 进行并行打分
- 不替换旧主诊断逻辑
- 任意文件缺失、单行异常、字段异常时都应安全降级
"""

import os

import pandas as pd


RULES_V2_PATH = "rules.csv"
RULE_COMBOS_V2_PATH = "rule_combos.csv"
UNKNOWN_LABEL = "unknown"

BASE_RULE_COLUMNS = [
    "rule_id",
    "abnormality",
    "band_pattern",
    "cause",
    "priority",
    "positive_control",
    "negative_control",
    "template_condition",
    "annealing_temp_condition",
    "text_hint",
    "required_fields",
    "base_score",
    "evidence_text",
    "suggestion",
    "enabled",
]

COMBO_RULE_COLUMNS = [
    "combo_id",
    "cause",
    "condition_1",
    "condition_2",
    "condition_3",
    "bonus_score",
    "combo_type",
    "combo_evidence",
    "enabled",
]

MATCH_FIELDS = [
    "abnormality",
    "band_pattern",
    "positive_control",
    "negative_control",
    "template_condition",
    "annealing_temp_condition",
]


def _safe_text(value, default=""):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return str(value).strip()


def _safe_float(value, default=0.0):
    try:
        text = _safe_text(value)
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def _is_unknown(value):
    return _safe_text(value).lower() in {"", UNKNOWN_LABEL, "none", "null", "nan"}


def _is_enabled(value):
    return _safe_text(value).lower() in {"1", "true", "yes", "y", "是"}


def _split_pipe_values(value):
    text = _safe_text(value)
    if not text:
        return []
    return [part.strip() for part in text.split("|") if part and part.strip()]


def _dedupe_keep_order(items):
    cleaned = []
    seen = set()
    for item in items:
        text = _safe_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _read_csv_with_fallback(path):
    encodings = ["utf-8", "utf-8-sig", "gbk"]
    for encoding in encodings:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, encoding="utf-8", errors="replace")


def _empty_eval(normalized_case=None, status="empty"):
    return {
        "normalized_case": normalized_case or {},
        "base_rule_hits": [],
        "combo_hits": [],
        "ranked_causes": [],
        "top1": None,
        "top2": None,
        "top3": None,
        "status": status,
    }


def load_rules_v2(path=RULES_V2_PATH):
    if not os.path.exists(path):
        return pd.DataFrame(columns=BASE_RULE_COLUMNS)

    try:
        df = _read_csv_with_fallback(path)
    except Exception:
        return pd.DataFrame(columns=BASE_RULE_COLUMNS)

    for column in BASE_RULE_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    signature = {"rule_id", "cause", "abnormality", "base_score", "enabled"}
    if not signature.issubset(set(df.columns)):
        return pd.DataFrame(columns=BASE_RULE_COLUMNS)

    try:
        df = df[df["enabled"].apply(_is_enabled)].copy()
    except Exception:
        return pd.DataFrame(columns=BASE_RULE_COLUMNS)

    df["priority"] = df["priority"].apply(lambda value: int(_safe_float(value, 0)))
    df["base_score"] = df["base_score"].apply(lambda value: float(_safe_float(value, 0)))

    for column in BASE_RULE_COLUMNS:
        if column in {"priority", "base_score"}:
            continue
        df[column] = df[column].apply(_safe_text)

    return df.reset_index(drop=True)


def load_rule_combos_v2(path=RULE_COMBOS_V2_PATH):
    if not os.path.exists(path):
        return pd.DataFrame(columns=COMBO_RULE_COLUMNS)

    try:
        df = _read_csv_with_fallback(path)
    except Exception:
        return pd.DataFrame(columns=COMBO_RULE_COLUMNS)

    for column in COMBO_RULE_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    signature = {"combo_id", "cause", "condition_1", "condition_2", "bonus_score", "combo_type", "enabled"}
    if not signature.issubset(set(df.columns)):
        return pd.DataFrame(columns=COMBO_RULE_COLUMNS)

    try:
        df = df[df["enabled"].apply(_is_enabled)].copy()
    except Exception:
        return pd.DataFrame(columns=COMBO_RULE_COLUMNS)

    df["bonus_score"] = df["bonus_score"].apply(lambda value: float(_safe_float(value, 0)))
    for column in COMBO_RULE_COLUMNS:
        if column == "bonus_score":
            continue
        df[column] = df[column].apply(_safe_text)

    df["combo_type"] = df["combo_type"].str.lower()
    df = df[df["combo_type"].isin(["support", "contradict"])].copy()
    return df.reset_index(drop=True)


def _required_fields_ready(required_fields, normalized_case):
    for field_name in _split_pipe_values(required_fields):
        if _is_unknown(normalized_case.get(field_name)):
            return False
    return True


def _match_simple_field(rule_value, case_value):
    rule_text = _safe_text(rule_value)
    if not rule_text or rule_text.lower() == "any":
        return True, None
    if _is_unknown(case_value):
        return False, None
    return _safe_text(case_value) == rule_text, _safe_text(case_value)


def _match_text_hint(rule_value, case_hints):
    rule_text = _safe_text(rule_value)
    if not rule_text or rule_text.lower() == "any":
        return True, []

    if not isinstance(case_hints, list):
        case_hints = []

    options = _split_pipe_values(rule_value)
    if not options:
        return False, []

    matched = [hint for hint in case_hints if _safe_text(hint) in options]
    return bool(matched), matched


def match_rule_v2(rule, normalized_case):
    if not _required_fields_ready(rule.get("required_fields"), normalized_case):
        return None

    matched_fields = {}
    for field_name in MATCH_FIELDS:
        matched, matched_value = _match_simple_field(rule.get(field_name, "any"), normalized_case.get(field_name))
        if not matched:
            return None
        if matched_value is not None:
            matched_fields[field_name] = matched_value

    text_matched, matched_hints = _match_text_hint(rule.get("text_hint", "any"), normalized_case.get("text_hint", []))
    if not text_matched:
        return None
    if matched_hints:
        matched_fields["text_hint"] = matched_hints

    return {
        "rule_id": _safe_text(rule.get("rule_id")),
        "cause": _safe_text(rule.get("cause")),
        "priority": int(_safe_float(rule.get("priority"), 0)),
        "base_score": float(_safe_float(rule.get("base_score"), 0)),
        "evidence_text": _safe_text(rule.get("evidence_text")),
        "suggestion": _safe_text(rule.get("suggestion")),
        "matched_fields": matched_fields,
        "source": "base_rule",
    }


def evaluate_base_rules_v2(normalized_case, rules):
    hits = []
    seen_rule_keys = set()

    if rules is None or rules.empty:
        return hits

    for _, row in rules.iterrows():
        try:
            hit = match_rule_v2(row.to_dict(), normalized_case)
            if not hit:
                continue
            unique_key = hit["rule_id"] or f"{hit['cause']}::{len(hits)}"
            if unique_key in seen_rule_keys:
                continue
            seen_rule_keys.add(unique_key)
            hits.append(hit)
        except Exception:
            continue

    return hits


def aggregate_base_rule_hits(base_rule_hits):
    aggregated = {}

    for hit in base_rule_hits:
        cause = _safe_text(hit.get("cause"))
        if not cause:
            continue

        if cause not in aggregated:
            aggregated[cause] = {
                "cause": cause,
                "priority": 0,
                "total_base_score": 0.0,
                "combo_bonus": 0.0,
                "total_score": 0.0,
                "hit_rules": [],
                "hit_combos": [],
                "evidence_chain": [],
                "suggestions": [],
            }

        item = aggregated[cause]
        item["priority"] = max(int(item["priority"]), int(_safe_float(hit.get("priority"), 0)))
        item["total_base_score"] += float(_safe_float(hit.get("base_score"), 0))
        item["hit_rules"].append(hit)

        evidence_text = _safe_text(hit.get("evidence_text"))
        if evidence_text:
            item["evidence_chain"].append(evidence_text)

        suggestion = _safe_text(hit.get("suggestion"))
        if suggestion:
            item["suggestions"].append(suggestion)

    for item in aggregated.values():
        item["evidence_chain"] = _dedupe_keep_order(item["evidence_chain"])
        item["suggestions"] = _dedupe_keep_order(item["suggestions"])
        item["total_base_score"] = round(float(item["total_base_score"]), 2)
        item["total_score"] = round(float(item["total_base_score"]), 2)

    return aggregated


def match_combo_condition(condition_text, normalized_case):
    condition_text = _safe_text(condition_text)
    if not condition_text:
        return True
    if "=" not in condition_text:
        return False

    field_name, expected_value = condition_text.split("=", 1)
    field_name = field_name.strip()
    expected_value = expected_value.strip()
    if not field_name or not expected_value:
        return False

    actual_value = normalized_case.get(field_name)
    if field_name == "text_hint":
        if not isinstance(actual_value, list):
            return False
        return expected_value in [_safe_text(item) for item in actual_value]

    return _safe_text(actual_value) == expected_value


def evaluate_rule_combos_v2(normalized_case, combos, aggregated_results):
    combo_hits = []
    applied_combo_keys = set()

    if combos is None or combos.empty or not aggregated_results:
        return combo_hits

    for _, row in combos.iterrows():
        try:
            combo = row.to_dict()
            cause = _safe_text(combo.get("cause"))
            if not cause or cause not in aggregated_results:
                continue

            combo_id = _safe_text(combo.get("combo_id")) or f"{cause}::{len(combo_hits)}"
            unique_key = f"{cause}::{combo_id}"
            if unique_key in applied_combo_keys:
                continue

            conditions = [combo.get("condition_1"), combo.get("condition_2"), combo.get("condition_3")]
            if not all(match_combo_condition(condition, normalized_case) for condition in conditions if _safe_text(condition)):
                continue

            applied_combo_keys.add(unique_key)
            combo_type = _safe_text(combo.get("combo_type")).lower()
            raw_bonus = float(_safe_float(combo.get("bonus_score"), 0))
            score_delta = raw_bonus if combo_type == "support" else -raw_bonus

            combo_hit = {
                "combo_id": combo_id,
                "cause": cause,
                "bonus_score": round(float(score_delta), 2),
                "combo_type": combo_type,
                "combo_evidence": _safe_text(combo.get("combo_evidence")),
                "source": "combo_rule",
            }
            combo_hits.append(combo_hit)

            item = aggregated_results[cause]
            item["combo_bonus"] = round(float(item.get("combo_bonus", 0) + score_delta), 2)
            item["total_score"] = round(float(item["total_base_score"] + item["combo_bonus"]), 2)
            item["hit_combos"].append(combo_hit)

            combo_evidence = _safe_text(combo_hit.get("combo_evidence"))
            if combo_evidence:
                item["evidence_chain"] = _dedupe_keep_order(item["evidence_chain"] + [combo_evidence])
        except Exception:
            continue

    return combo_hits


def evaluate_rules_v2(normalized_case, rules_path=RULES_V2_PATH, combos_path=RULE_COMBOS_V2_PATH):
    normalized_case = normalized_case or {}
    if not isinstance(normalized_case, dict) or not normalized_case:
        return _empty_eval(normalized_case=normalized_case, status="empty")

    rules = load_rules_v2(rules_path)
    combos = load_rule_combos_v2(combos_path)
    if rules.empty:
        return _empty_eval(normalized_case=normalized_case, status="empty")

    base_rule_hits = evaluate_base_rules_v2(normalized_case, rules)
    if not base_rule_hits:
        return _empty_eval(normalized_case=normalized_case, status="empty")

    aggregated_results = aggregate_base_rule_hits(base_rule_hits)
    combo_hits = evaluate_rule_combos_v2(normalized_case, combos, aggregated_results)

    ranked_causes = sorted(
        aggregated_results.values(),
        key=lambda item: (float(item.get("total_score", 0)), int(item.get("priority", 0))),
        reverse=True,
    )

    for item in ranked_causes:
        item["evidence_chain"] = _dedupe_keep_order(item.get("evidence_chain", []))
        item["suggestions"] = _dedupe_keep_order(item.get("suggestions", []))
        item["combo_bonus"] = round(float(item.get("combo_bonus", 0)), 2)
        item["total_base_score"] = round(float(item.get("total_base_score", 0)), 2)
        item["total_score"] = round(float(item.get("total_score", 0)), 2)

    top_causes = [item.get("cause") for item in ranked_causes[:3]]
    while len(top_causes) < 3:
        top_causes.append(None)

    return {
        "normalized_case": normalized_case,
        "base_rule_hits": base_rule_hits,
        "combo_hits": combo_hits,
        "ranked_causes": ranked_causes,
        "top1": top_causes[0],
        "top2": top_causes[1],
        "top3": top_causes[2],
        "status": "ok",
    }
