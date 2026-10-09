"""新旧网页共用的诊断展示与报告业务，不依赖 Streamlit 会话。"""
import json
import re
import sqlite3
import pandas as pd
import case_storage
from branding import PRODUCT_NAME, PRODUCT_SUBTITLE, CURRENT_MODULE
from evidence_support import parse_json, normalize_cause_label, template_mass_ng, positive_number


def is_classroom_record(record):
    """课堂页面排除内部示例和规则校验记录，不改写历史来源。"""
    return record.get("data_origin") not in {"模拟演示", "规则回归"}

def parse_followup_data(value):
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}

def safe_to_float(value, default=None):
    """安全地把值转成浮点数，失败时返回 default"""
    try:
        if str(value).strip().lower() == "any":
            return default
        return float(value)
    except:
        return default

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

def load_record_by_id(record_id, db_path=None):
    """按 id 读取单条记录（用于导出案例摘要）"""
    if not record_id or not db_path:
        return None

    conn = sqlite3.connect(db_path)
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

def build_case_review_report(payload, db_path=None):
    """生成规范化复盘报告文本。"""
    payload = payload or {}
    record_id = payload.get("record_id")
    db_record = load_record_by_id(record_id, db_path) or {}
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

    if record_id:
        image_lines = case_storage.gel_report_lines(db_path, record_id)
        if image_lines:
            append_report_section(lines, "图像辅助观察与人工核对（独立记录）", image_lines)
        if is_classroom_record(db_record):
            from teaching_workflow import teaching_report_lines
            teaching_lines = teaching_report_lines(db_path, record_id)
            if teaching_lines:
                append_report_section(lines, "课堂任务、独立复核与实际复测", teaching_lines)

    append_report_section(
        lines,
        "七、报告尾部说明",
        [
            "本报告由系统自动生成，供实验教学和教师确认参考。",
            "排序分数和证据支持程度不是概率。教师经验复核不等于复测验证；未完成验证的原因仍需结合原始记录核查。",
        ],
    )

    return "\n".join(lines)

def build_case_summary(payload, db_path=None):
    """兼容旧调用入口：输出规范化复盘报告文本。"""
    return build_case_review_report(payload, db_path)
