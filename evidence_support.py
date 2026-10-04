"""事实语句、原因标识与实验资料的共用处理。"""

import hashlib
import json
import math
import re
from pathlib import Path


UNKNOWN_VALUES = {"", "-", "None", "nan", "unknown", "未观察", "未设置", "无法确认", "待确认", "未填写"}
UNCERTAIN = re.compile(
    r"怀疑|疑似|可能|也许|或许|估计|猜测|不确定|是否|是不是|会不会|推测|待确认|需确认|尚未确认|未确认|待核实|均待|"
    r"排除|不是|并非|未见|未发现|未检测到|未出现|不存在|未发生|没有|没发生|无污染|未污染|没漏加|未漏加|并没有|"
    r"\b(?:no|not|without|possible|suspect|maybe)\b", re.I
)
ALIASES = {
    "模板量不足": {"模板量不足", "模板浓度低", "模板少", "模板浓度过低", "模板过少", "模板过低"},
    "污染": {"污染", "气溶胶污染", "阴性对照污染", "交叉污染"},
    "引物问题": {"引物问题", "引物失效", "引物设计问题", "引物降解"},
    "PCR体系问题": {"pcr体系问题", "体系漏加", "反应体系配置错误", "pcr体系漏加试剂", "漏加试剂", "体系配置错误"},
    "退火温度过高": {"退火温度过高", "退火温度偏高"},
    "退火温度过低": {"退火温度过低", "退火温度偏低"},
}


def confirmed_clauses(description):
    """保守保留肯定事实；问句必须在移除标点前识别。"""
    clauses = re.split(r"[。；;，,\n]+", str(description or ""))
    return [c.strip() for c in clauses if c.strip() and not UNCERTAIN.search(c)
            and not re.search(r"[？?]", c)]


def confirmed_description(description):
    return "。".join(confirmed_clauses(description))


def normalize_cause_label(value):
    """仅合并明确的同义词；多原因和待核实结论不强行归类。"""
    text = str(value or "").strip()
    if text in UNKNOWN_VALUES or text in {"未知", "未确认", "其他/待补充"}:
        return ""
    clauses = confirmed_clauses(text)
    labels = []
    for clause in clauses:
        cleaned = re.sub(r"^(?:确认(?:是|为)?|实际(?:是|为)?|最终(?:原因)?(?:是|为|：|:)?|原因(?:是|为|：|:)?)+", "", clause).strip()
        compact = re.sub(r"\s+", "", cleaned).lower()
        label = next((k for k, values in ALIASES.items() if compact in values), cleaned)
        labels.append(label)
    labels = list(dict.fromkeys(labels))
    if len(labels) != 1 or re.search(r"和|以及|或|/|与.*均", labels[0]):
        # 规则中的复合候选名是固定标签，应原样保留，不能并入更泛的原因。
        known = set(cause_options())
        return text if text in known else ""
    return labels[0]


def cause_options():
    import csv
    path = Path(__file__).with_name("rules.csv")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open(encoding=encoding, newline="") as f:
                return sorted({row["cause"].strip() for row in csv.DictReader(f) if row.get("cause")})
        except UnicodeError:
            continue
    return []


def cause_id(value):
    label = normalize_cause_label(value)
    return "cause_" + hashlib.sha256(label.encode("utf-8")).hexdigest()[:16] if label else ""


def rules_version():
    digest = hashlib.sha256()
    for name in ("rules.csv", "rule_combos.csv", "rules_v2.csv", "diagnosis_normalization.py", "diagnosis_rule_engine_v2.py", "evidence_support.py", "core.py", "followup_agent.py"):
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()[:16]


def parse_json(value, default=None):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else (default or {})
    except (ValueError, TypeError):
        return default or {}


def positive_number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (ValueError, TypeError):
        return None


def template_mass_ng(parameters):
    concentration = positive_number(parameters.get("template_concentration"))
    volume = positive_number(parameters.get("template_amount"))
    return round(concentration * volume, 3) if concentration and volume else None


def validate_experiment_parameters(parameters):
    """检查单位与明显的录入矛盾，不设置通用 DNA 量阈值。"""
    issues = []
    total = positive_number(parameters.get("reaction_volume"))
    template = positive_number(parameters.get("template_amount"))
    if total and template and template >= total:
        issues.append("模板加入体积应小于反应总体积，请核对单位与数值。")
    for field in ("template_amount", "template_concentration", "reaction_volume", "target_size", "annealing_temp", "recommended_temp", "cycles"):
        value = parameters.get(field)
        if value is not None and value != "" and positive_number(value) is None:
            issues.append(f"{field} 应为大于零的有限数值，未知时请留空。")
    return issues


def load_course_presets(path=None):
    path = Path(path) if path else Path(__file__).with_name("course_presets.json")
    try:
        presets = json.loads(path.read_text(encoding="utf-8"))
        return [p for p in presets if isinstance(p, dict) and p.get("name")]
    except (OSError, ValueError):
        return []


def learning_progress(records):
    """每个阶段明确分母；修订按所对应的教师反馈版本计数。"""
    rows = []
    for r in records:
        followup = parse_json(r.get("followup_json") or r.get("followup_data"))
        review_version = int(r.get("teacher_review_version") or 0)
        revision_version = int(r.get("student_revision_review_version") or 0)
        reviewed = (r.get("teacher_final_cause") or r.get("教师最终原因")) not in (None, "", "未确认", "-")
        initial = (r.get("student_initial_hypothesis") or r.get("学生初判")) not in (None, "", "-")
        revision = (r.get("student_revision_time") or r.get("学生修订时间")) not in (None, "", "-")
        current = revision and review_version == revision_version
        rows.append({"案例编号": r.get("id"), "独立初判": initial,
                     "追问补证": bool(followup.get("final_results")), "教师复核": reviewed,
                     "学生修订": current, "需重新修订": revision and not current,
                     "验证方案": bool(parse_json(r.get("verification_plan_json")).get("hypothesis"))})
    total = len(rows)
    reviewed = sum(r["教师复核"] for r in rows)
    metrics = {name: {"count": sum(r[name] for r in rows), "denominator": reviewed if name == "学生修订" else total}
               for name in ("独立初判", "追问补证", "教师复核", "学生修订", "验证方案")}
    return metrics, rows
