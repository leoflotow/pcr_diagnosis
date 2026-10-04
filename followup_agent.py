"""针对初判缺口生成追问，并把学生补充描述整理为待确认线索。"""

import json
import re

from diagnosis_normalization import STANDARD_TEXT_HINTS
import ai_config

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


MODEL_BASE_URL = ai_config.BASE_URL
MAX_QUESTIONS = 3


def _model_client():
    key = ai_config.api_key()
    if not key or OpenAI is None:
        return None
    return OpenAI(
        api_key=key,
        base_url=MODEL_BASE_URL,
        timeout=8,
        max_retries=0,
    )


def _read_json(content):
    text = str(content or "").strip()
    block = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if block:
        text = block.group(1).strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _base_questions(case, results=None):
    abnormality = case.get("abnormality")
    positive = case.get("positive_control_normal")
    negative = case.get("negative_control_band")
    candidate_causes = "、".join(str(item.get("原因", "")) for item in (results or [])[:3])
    questions = []

    if (abnormality == "阳性对照无带" or positive in {"否", "未观察", "未设置", "无法确认"}
            or abnormality in {"无条带", "条带弱"}
            or ("PCR体系" in candidate_causes and "模板" in candidate_causes)):
        questions.append({
            "id": "positive_control", "kind": "choice",
            "text": "请再核对阳性对照泳道：预期大小的条带实际是什么表现？",
            "reason": "阳性对照有助于区分样本问题与PCR体系问题。",
            "options": ["正常清晰", "完全无带", "明显弱带", "暂无法确认"],
        })

    if negative in {"是", "未观察", "未设置", "无法确认"} or abnormality == "阴性对照有带" or "污染" in candidate_causes:
        questions.append({
            "id": "negative_control", "kind": "choice",
            "text": "请对照 Marker 核对阴性对照泳道：条带位于什么位置？",
            "reason": "目标大小附近与小片段条带对应的规则不同。",
            "options": ["实际无带", "与预期目标大小相近", "明显小于目标条带", "拖尾或弥散", "暂无法确认"],
        })

    if abnormality in {"多条带或非特异扩增", "条带大小不对", "条带拖尾或弥散", "条带畸形"}:
        questions.append({
            "id": "sample_band", "kind": "choice",
            "text": "请比较样本条带与 Marker 和预期产物：主要观察到哪种位置或形态？",
            "reason": "明确条带位置可以缩小非特异扩增与小片段产物等候选原因。",
            "options": ["预期条带旁有额外小片段", "主要条带大小偏离预期", "拖尾或弥散", "暂无法判断"],
        })

    questions.append({
        "id": "operation", "kind": "text",
        "text": "回想配液、加样和电泳过程：有无实际发生的漏加、枪头混用、模板异常或上样问题？请只写观察到或确认过的情况。",
        "reason": "操作过程中的具体事实可补足参数和对照结果无法反映的线索。",
    })
    # 最多三个观察问题；操作说明始终保留为可选补证入口。
    return questions[:-1][:MAX_QUESTIONS] + questions[-1:]


def plan_followup_questions(case, results=None):
    """问题主题与选项由程序限定；模型只能润色问句，不能修改诊断事实。"""
    questions = _base_questions(case, results=results)
    if case.get("local_mode"):
        return questions, "本地追问规划"
    client = _model_client()
    if client is None:
        return questions, "本地追问规划"

    request = [{"id": item["id"], "text": item["text"], "reason": item["reason"]} for item in questions]
    try:
        response = client.chat.completions.create(
            **ai_config.request_options(),
            temperature=0.2,
            messages=[
                {"role": "system", "content": "你是PCR实验教学追问助手。只润色给定问题的中文问句，不改变问题主题，不添加诊断结论或实验事实。输出JSON对象，键为原id，值为一个问句；不要输出其他文字。"},
                {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
            ],
        )
        wording = _read_json(response.choices[0].message.content)
        if not isinstance(wording, dict):
            return questions, "本地追问规划"
        required_terms = {
            "positive_control": "阳性对照",
            "negative_control": "阴性对照",
            "sample_band": "条带",
            "operation": "操作",
        }
        for item in questions:
            proposed = wording.get(item["id"])
            required = required_terms.get(item["id"])
            if (isinstance(proposed, str) and 12 <= len(proposed.strip()) <= 120
                    and "？" in proposed and (not required or required in proposed)):
                item["text"] = proposed.strip()
        return questions, "AI整理问法"
    except Exception:
        return questions, "本地追问规划"


def interpret_operation_text(text, local_mode=False):
    """模型只提出候选标签，必须由学生确认后才进入规则引擎。"""
    description = str(text or "").strip()
    if not description:
        return [], "未填写操作描述"
    client = None if local_mode else _model_client()
    if client is None:
        return [], "手动确认线索"
    try:
        response = client.chat.completions.create(
            **ai_config.request_options(),
            temperature=0.1,
            messages=[
                {"role": "system", "content": "你是PCR实验记录线索整理助手。仅提取学生明确表示实际发生的事实；否定、猜测、提问和未确认的情况均不提取。只能从给定标签选，输出JSON数组。不得推断诊断结论。标签：" + "、".join(STANDARD_TEXT_HINTS)},
                {"role": "user", "content": description[:2000]},
            ],
        )
        labels = _read_json(response.choices[0].message.content)
        if isinstance(labels, list):
            return list(dict.fromkeys(x for x in labels if isinstance(x, str) and x in STANDARD_TEXT_HINTS)), "AI候选线索"
    except Exception:
        pass
    return [], "手动确认线索"


def apply_followup_choices(case, answers):
    """仅采用学生明确选择的证据；未确认的项目沿用初始记录。"""
    updated = dict(case)
    positive = answers.get("positive_control")
    if positive == "正常清晰":
        updated["positive_control_normal"] = "是"
        updated["positive_control_detail"] = "正常"
    elif positive == "完全无带":
        updated["positive_control_normal"] = "否"
        updated["positive_control_detail"] = "无带"
    elif positive == "明显弱带":
        updated["positive_control_normal"] = "否"
        updated["positive_control_detail"] = "弱带"
    elif positive == "无带或明显弱带":
        # 兼容旧案例中未区分的选项，不把弱带误认作完全无带。
        updated["positive_control_normal"] = "否"
        updated["positive_control_detail"] = "异常待分型"

    negative = answers.get("negative_control")
    negative_map = {
        "实际无带": ("否", "无带"),
        "与预期目标大小相近": ("是", "目标大小相近带"),
        "明显小于目标条带": ("是", "小片段带"),
        "拖尾或弥散": ("是", "拖尾或弥散"),
    }
    if negative in negative_map:
        updated["negative_control_band"], updated["negative_control_detail"] = negative_map[negative]

    band_map = {
        "预期条带旁有额外小片段": "primer_dimer_like",
        "主要条带大小偏离预期": "unexpected_size",
        "拖尾或弥散": "smear",
    }
    if answers.get("sample_band") in band_map:
        updated["band_pattern"] = band_map[answers["sample_band"]]
    return updated
