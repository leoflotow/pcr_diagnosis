"""课堂任务与教学过程记录；不调用诊断评分，不改写旧案例。"""

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import secrets
import sqlite3

from evidence_support import parse_json

DIMENSIONS = ("对照解释", "证据引用", "替代原因", "验证方案")
SCHEME_FIELDS = ("course_name", "experiment_name", "template_type", "template_concentration",
                 "reaction_volume", "target_size", "recommended_temp", "polymerase", "controls", "protocol_notes", "template_amount", "cycles")
SCHEME_NUMBERS = {"template_concentration", "reaction_volume", "target_size", "recommended_temp", "template_amount", "cycles"}


def now():
    return datetime.now().isoformat(timespec="microseconds")


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@contextmanager
def connection(path, write=False):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS teaching_tasks (
            id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
            instructions TEXT NOT NULL, due_at TEXT, transfer_prompt TEXT NOT NULL,
            scheme_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_records (
            record_id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS learning_submissions (
            id INTEGER PRIMARY KEY, record_id INTEGER UNIQUE NOT NULL, task_id INTEGER NOT NULL,
            answer TEXT NOT NULL, reasoning TEXT NOT NULL, minutes REAL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS learning_evaluations (
            id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL, stage TEXT NOT NULL,
            source_version INTEGER NOT NULL, rubric_json TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS teacher_exposures (
            record_id INTEGER PRIMARY KEY, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS independent_reviews (
            id INTEGER PRIMARY KEY, record_id INTEGER UNIQUE NOT NULL, cause TEXT NOT NULL,
            reason TEXT NOT NULL, evidence_level TEXT NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS course_scheme_versions (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL,
            payload_json TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(name, version)
        );
        CREATE TABLE IF NOT EXISTS experiment_retests (
            id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL, payload_json TEXT NOT NULL,
            plan_json TEXT NOT NULL, image_path TEXT, image_sha TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS retest_reviews (
            id INTEGER PRIMARY KEY, retest_id INTEGER NOT NULL, conclusion TEXT NOT NULL,
            note TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS teaching_suggestions (
            id INTEGER PRIMARY KEY, scope_json TEXT NOT NULL, context_sha TEXT NOT NULL,
            result_json TEXT NOT NULL, model TEXT NOT NULL, usage_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS gel_evaluation_samples (
            id INTEGER PRIMARY KEY, family TEXT NOT NULL, split TEXT NOT NULL, quality TEXT NOT NULL,
            image_path TEXT NOT NULL, image_sha TEXT NOT NULL, prepared_sha TEXT NOT NULL,
            mapping_json TEXT NOT NULL, settings_json TEXT NOT NULL, reference_json TEXT NOT NULL,
            disputed_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS gel_evaluation_runs (
            id INTEGER PRIMARY KEY, sample_id INTEGER NOT NULL, context_sha TEXT NOT NULL,
            model TEXT NOT NULL, prompt_version TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS gel_evaluation_audits (
            id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, mismatch_json TEXT NOT NULL,
            note TEXT NOT NULL, created_at TEXT NOT NULL
        );
    """)


def require_teacher(authorized):
    if authorized is not True:
        raise ValueError("请先完成教师访问验证。")


def text(value, label, maximum=5000, required=True):
    value = str(value or "").strip()
    if (required and not value) or len(value) > maximum:
        raise ValueError(f"{label}不能为空且最多 {maximum} 字。")
    return value


def student_record(conn, record_id, code):
    row = conn.execute("SELECT * FROM diagnosis_records WHERE id=?", (record_id,)).fetchone()
    if not row or row["data_origin"] in {"模拟演示", "规则回归"}:
        raise ValueError("未找到可访问的课堂案例。")
    digest = hashlib.sha256(str(code or "").strip().encode()).hexdigest()
    if not code or row["student_access_hash"] != digest:
        raise ValueError("查询码不匹配。")
    return dict(row)


def classroom_record(conn, record_id):
    row = conn.execute("SELECT * FROM diagnosis_records WHERE id=?", (record_id,)).fetchone()
    if not row or row["data_origin"] in {"模拟演示", "规则回归"}:
        raise ValueError("未找到课堂案例。")
    return dict(row)


def task_by_code(path, code):
    with connection(path) as conn:
        row = conn.execute("SELECT * FROM teaching_tasks WHERE code=?", (str(code or "").strip().upper(),)).fetchone()
    return dict(row) if row else None


def task_status(task):
    if not task or not task["active"]:
        return "已关闭"
    if task["due_at"] and datetime.fromisoformat(task["due_at"]) < datetime.now():
        return "已截止"
    return "开放"


def create_task(path, title, instructions, transfer_prompt, due_at="", scheme_id=None, teacher_authorized=False, after_insert=None):
    require_teacher(teacher_authorized)
    title = text(title, "任务名称", 120)
    instructions = text(instructions, "任务说明")
    transfer_prompt = text(transfer_prompt, "新案例题目", required=False)
    if due_at:
        try:
            parsed = datetime.fromisoformat(due_at)
            if parsed.tzinfo or parsed <= datetime.now():
                raise ValueError()
            due_at = parsed.isoformat(timespec="minutes")
        except ValueError:
            raise ValueError("截止时间需填写未来的本地时间，例如 2026-10-25 18:00。") from None
    with connection(path, True) as conn:
        scheme = conn.execute("SELECT * FROM course_scheme_versions WHERE id=?", (scheme_id,)).fetchone() if scheme_id else None
        if scheme_id and not scheme:
            raise ValueError("课程方案不存在。")
        code = secrets.token_hex(4).upper()
        cursor = conn.execute("INSERT INTO teaching_tasks(code,title,instructions,due_at,transfer_prompt,scheme_json,created_at) VALUES (?,?,?,?,?,?,?)",
                     (code, title, instructions, due_at, transfer_prompt, dump(dict(scheme)) if scheme else "{}", now()))
        if after_insert:
            after_insert(conn, cursor.lastrowid)
    return code


def list_tasks(path, teacher_authorized=False):
    require_teacher(teacher_authorized)
    with connection(path) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM teaching_tasks ORDER BY id DESC")]


def set_task_active(path, task_id, active, teacher_authorized=False):
    require_teacher(teacher_authorized)
    with connection(path, True) as conn:
        conn.execute("UPDATE teaching_tasks SET active=? WHERE id=?", (int(bool(active)), task_id))


def link_new_record(conn, record_id, raw_case):
    """与案例 INSERT 同一事务；任务不可事后随意变更。"""
    code = str(raw_case.get("teaching_task_code") or "").strip().upper()
    if not code:
        return
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM teaching_tasks WHERE code=?", (code,)).fetchone()
    if not row or task_status(dict(row)) != "开放":
        raise ValueError("课堂任务不存在、已关闭或已截止，请重新核对。")
    conn.execute("INSERT INTO task_records VALUES (?,?,?)", (record_id, row["id"], now()))


def record_task(path, record_id, code=None, teacher_authorized=False):
    with connection(path) as conn:
        if teacher_authorized is True:
            classroom_record(conn, record_id)
        else:
            student_record(conn, record_id, code)
        task = conn.execute("SELECT t.* FROM teaching_tasks t JOIN task_records r ON t.id=r.task_id WHERE r.record_id=?", (record_id,)).fetchone()
        answer = conn.execute("SELECT * FROM learning_submissions WHERE record_id=?", (record_id,)).fetchone()
    return {"task": dict(task) if task else None, "submission": dict(answer) if answer else None}


def save_transfer(path, record_id, code, answer, reasoning, minutes=None):
    answer, reasoning = text(answer, "独立判断"), text(reasoning, "判断依据")
    if minutes is not None and (type(minutes) not in {int, float} or not math.isfinite(minutes) or not 0 < minutes <= 1440):
        raise ValueError("实际用时需为 0–1440 分钟之间的正数，未知请留空。")
    with connection(path, True) as conn:
        student_record(conn, record_id, code)
        task = conn.execute("SELECT t.* FROM teaching_tasks t JOIN task_records r ON t.id=r.task_id WHERE r.record_id=?", (record_id,)).fetchone()
        if not task or not task["transfer_prompt"] or task_status(dict(task)) != "开放":
            raise ValueError("此任务未设置新案例题目，或已关闭、截止。")
        if conn.execute("SELECT 1 FROM learning_submissions WHERE record_id=?", (record_id,)).fetchone():
            raise ValueError("新案例独立作答已提交，保留原稿，不重复覆盖。")
        conn.execute("INSERT INTO learning_submissions(record_id,task_id,answer,reasoning,minutes,created_at) VALUES (?,?,?,?,?,?)",
                     (record_id, task["id"], answer, reasoning, minutes, now()))


def save_learning_evaluation(path, record_id, stage, rubric, note="", teacher_authorized=False):
    require_teacher(teacher_authorized)
    if stage not in {"initial", "revised", "transfer"} or set(rubric) != set(DIMENSIONS):
        raise ValueError("评价阶段或维度无效。")
    if any(v is not None and (type(v) is not int or v not in {0, 1, 2}) for v in rubric.values()):
        raise ValueError("分数只能为 0、1、2 或未评价。")
    with connection(path, True) as conn:
        row = classroom_record(conn, record_id)
        version = 0
        if stage == "initial" and not row["student_initial_hypothesis"]:
            raise ValueError("尚无学生初判。")
        if stage == "revised":
            version = int(row["student_revision_review_version"] or 0)
            if not row["student_revision_time"] or version != int(row["teacher_review_version"] or 0):
                raise ValueError("尚无对应最新反馈的学生修订。")
        if stage == "transfer":
            submission = conn.execute("SELECT id FROM learning_submissions WHERE record_id=?", (record_id,)).fetchone()
            if not submission:
                raise ValueError("尚无新案例作答。")
            version = submission["id"]
        conn.execute("INSERT INTO learning_evaluations(record_id,stage,source_version,rubric_json,note,created_at) VALUES (?,?,?,?,?,?)",
                     (record_id, stage, version, dump(rubric), text(note, "评价备注", required=False), now()))


def task_export(path, task_id, teacher_authorized=False):
    require_teacher(teacher_authorized)
    with connection(path) as conn:
        records = conn.execute("SELECT d.* FROM diagnosis_records d JOIN task_records r ON d.id=r.record_id WHERE r.task_id=? AND COALESCE(d.data_origin,'') NOT IN ('模拟演示','规则回归') ORDER BY d.id", (task_id,)).fetchall()
        rows = []
        for record in records:
            record = dict(record)
            answer = conn.execute("SELECT * FROM learning_submissions WHERE record_id=?", (record["id"],)).fetchone()
            output = {"案例编号": record["id"], "匿名小组": record["group_code"] or "未填写", "来源": record["data_origin"] or "未标注",
                      "初判": record["student_initial_hypothesis"] or "", "修订": record["student_revised_cause"] or "",
                      "修订依据": record["student_revision_reason"] or "", "新案例判断": answer["answer"] if answer else "",
                      "新案例依据": answer["reasoning"] if answer else "", "自报用时分钟": answer["minutes"] if answer else None}
            blind = conn.execute("SELECT cause,reason,evidence_level FROM independent_reviews WHERE record_id=?", (record["id"],)).fetchone()
            output.update({"教师独立判断": blind["cause"] if blind else "", "独立判断依据": blind["reason"] if blind else "",
                           "教师最终判断": record["teacher_final_cause"] or "", "最终判断依据": record["teacher_note"] or ""})
            for stage, label in [("initial", "初判"), ("revised", "修订"), ("transfer", "新案例")]:
                expected = answer["id"] if stage == "transfer" and answer else int(record["student_revision_review_version"] or 0) if stage == "revised" else 0
                evaluation = conn.execute("SELECT * FROM learning_evaluations WHERE record_id=? AND stage=? AND source_version=? ORDER BY id DESC LIMIT 1", (record["id"],stage,expected)).fetchone()
                fallback = parse_json(record["teacher_rubric_json"]).get(stage, {}) if stage != "transfer" else {}
                rubric = parse_json(evaluation["rubric_json"]) if evaluation else fallback
                current = stage != "revised" or bool(record["student_revision_time"] and int(record["student_revision_review_version"] or 0) == int(record["teacher_review_version"] or 0))
                if stage == "transfer" and not answer or not current:
                    rubric = {}
                for dimension in DIMENSIONS:
                    output[f"{label}·{dimension}"] = rubric.get(dimension)
            rows.append(output)
    return rows


def mark_exposed(path, record_id, teacher_authorized=False):
    require_teacher(teacher_authorized)
    with connection(path, True) as conn:
        classroom_record(conn, record_id)
        conn.execute("INSERT OR IGNORE INTO teacher_exposures VALUES (?,?)", (record_id, now()))


def mark_many_exposed(path, record_ids, teacher_authorized=False):
    require_teacher(teacher_authorized)
    with connection(path, True) as conn:
        conn.executemany("INSERT OR IGNORE INTO teacher_exposures VALUES (?,?)", [(i,now()) for i in record_ids])


def independent_record(path, record_id, teacher_authorized=False):
    require_teacher(teacher_authorized)
    with connection(path) as conn:
        record = classroom_record(conn, record_id)
        saved = conn.execute("SELECT * FROM independent_reviews WHERE record_id=?", (record_id,)).fetchone()
        exposed = conn.execute("SELECT 1 FROM teacher_exposures WHERE record_id=?", (record_id,)).fetchone()
    # 仅返回原始输入；界面在提交独立判断前不渲染任何系统候选。
    allowed = ("id", "abnormality", "template_amount", "annealing_temp", "cycles", "positive_control_normal", "negative_control_band", "description", "gel_image_path", "input_json")
    return {"raw": {key: record[key] for key in allowed}, "review": dict(saved) if saved else None,
            "eligible": not saved and not exposed and not record["teacher_final_cause"]}


def save_independent_review(path, record_id, cause, reason, evidence_level, teacher_authorized=False):
    require_teacher(teacher_authorized)
    cause, reason = text(cause, "独立判断", 500), text(reason, "独立判断依据")
    if evidence_level not in {"经验复核", "原始记录支持", "复测验证", "原因待核实"}:
        raise ValueError("证据等级无效。")
    with connection(path, True) as conn:
        record = classroom_record(conn, record_id)
        if record["teacher_final_cause"] or conn.execute("SELECT 1 FROM teacher_exposures WHERE record_id=?", (record_id,)).fetchone():
            raise ValueError("该案例已查看系统建议或完成原因复核，不能补记为独立判断。")
        if conn.execute("SELECT 1 FROM independent_reviews WHERE record_id=?", (record_id,)).fetchone():
            raise ValueError("独立判断已提交，不能覆盖。")
        conn.execute("INSERT INTO independent_reviews(record_id,cause,reason,evidence_level,snapshot_json,created_at) VALUES (?,?,?,?,?,?)",
                     (record_id,cause,reason,evidence_level,dump({"initial": parse_json(record["diagnosis_snapshot_json"]), "followup": parse_json(record["followup_json"])}),now()))


def save_scheme(path, name, payload, source, expected_version=0, teacher_authorized=False):
    require_teacher(teacher_authorized)
    name, source = text(name,"方案名称",120), text(source,"方案依据",2000)
    clean = {key: payload.get(key) for key in SCHEME_FIELDS}
    for key in SCHEME_NUMBERS:
        value = clean[key]
        if value is not None and (type(value) not in {int,float} or not math.isfinite(value) or value <= 0):
            raise ValueError("数值条件必须为正数，未知请留空。")
    if clean["cycles"] is not None and type(clean["cycles"]) is not int:
        raise ValueError("循环数需为整数，未知请留空。")
    if clean["template_type"] not in {"待确认", "质粒", "基因组 DNA", "cDNA", "其他"}:
        raise ValueError("模板类型无效。")
    for key in set(SCHEME_FIELDS) - SCHEME_NUMBERS:
        clean[key] = text(clean[key], key, 2000, required=False)
    with connection(path, True) as conn:
        latest = conn.execute("SELECT MAX(version) FROM course_scheme_versions WHERE name=?", (name,)).fetchone()[0] or 0
        if latest != expected_version:
            raise ValueError("方案已有新版本，请刷新后核对。")
        cursor = conn.execute("INSERT INTO course_scheme_versions(name,version,payload_json,source,created_at) VALUES (?,?,?,?,?)", (name,latest+1,dump(clean),source,now()))
        return cursor.lastrowid


def list_schemes(path):
    with connection(path) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM course_scheme_versions ORDER BY id DESC")]


RETEST_CONCLUSIONS = ["支持原假设", "削弱原假设", "仍无法判断"]
RETEST_FIELDS = ("performed_at", "changed", "kept", "controls", "sample_result", "expected_comparison", "conclusion")


def save_retest(path, record_id, code, payload, image_path=None):
    from gel_image_assistant import prepare_image
    clean = {field: text(payload.get(field), field, 5000) for field in RETEST_FIELDS}
    if clean["conclusion"] not in RETEST_CONCLUSIONS:
        raise ValueError("复测解释无效。")
    try:
        performed = datetime.fromisoformat(clean["performed_at"])
        if performed.tzinfo or performed > datetime.now():
            raise ValueError()
    except ValueError:
        raise ValueError("请填写已实际实施的本地日期时间，不能是未来时间。") from None
    image_sha = None
    if image_path:
        prepared = prepare_image(image_path,[{"lane_id":1,"role":"身份未确认"}])
        image_sha = prepared["image_sha"]
    with connection(path,True) as conn:
        record = student_record(conn,record_id,code)
        plan = parse_json(record["verification_plan_json"])
        if not plan:
            raise ValueError("请先保存验证计划，再记录实际复测。")
        cursor = conn.execute("INSERT INTO experiment_retests(record_id,payload_json,plan_json,image_path,image_sha,created_at) VALUES (?,?,?,?,?,?)",
                              (record_id,dump(clean),dump(plan),image_path,image_sha,now()))
        return cursor.lastrowid


def load_retests(path, record_id, code=None, teacher_authorized=False):
    with connection(path) as conn:
        classroom_record(conn,record_id) if teacher_authorized is True else student_record(conn,record_id,code)
        rows = [dict(row) for row in conn.execute("SELECT * FROM experiment_retests WHERE record_id=? ORDER BY id DESC",(record_id,))]
        for row in rows:
            review = conn.execute("SELECT * FROM retest_reviews WHERE retest_id=? ORDER BY id DESC LIMIT 1",(row["id"],)).fetchone()
            row["review"] = dict(review) if review else None
            row["payload"] = parse_json(row["payload_json"])
    return rows


def review_retest(path, retest_id, conclusion, note, expected_review_id=None, teacher_authorized=False):
    require_teacher(teacher_authorized)
    if conclusion not in RETEST_CONCLUSIONS:
        raise ValueError("复核解释无效。")
    note = text(note,"复核依据")
    with connection(path,True) as conn:
        row = conn.execute("SELECT * FROM experiment_retests WHERE id=?",(retest_id,)).fetchone()
        if not row:
            raise ValueError("复测记录不存在。")
        classroom_record(conn,row["record_id"])
        latest = conn.execute("SELECT id FROM retest_reviews WHERE retest_id=? ORDER BY id DESC LIMIT 1",(retest_id,)).fetchone()
        if (latest["id"] if latest else None) != expected_review_id:
            raise ValueError("复测复核已更新，请刷新后重试。")
        conn.execute("INSERT INTO retest_reviews(retest_id,conclusion,note,created_at) VALUES (?,?,?,?)",(retest_id,conclusion,note,now()))


ISSUE_ACTIONS = {
    "controls": {"label":"对照信息待核对", "actions":["安排对照判读练习", "核对本次对照设置与记录"]},
    "followup": {"label":"补证尚未完成", "actions":["集中讲解如何寻找区分证据", "提醒小组完成定向补证"]},
    "revision": {"label":"教师反馈后修订待完成", "actions":["安排反馈后的解释修订", "提醒查看最新教师反馈"]},
    "plan": {"label":"验证计划尚未记录", "actions":["安排变量与对照设计练习", "提供验证方案填写指导"]},
    "evidence": {"label":"人工评价的证据引用为0或1分", "actions":["安排事实与推测区分练习", "示范如何引用原始记录"]},
    "transfer": {"label":"新案例分析待提交", "actions":["安排新案例独立分析时间", "提醒完成独立作答"]},
}


def build_issues(path, task_id=None, teacher_authorized=False):
    require_teacher(teacher_authorized)
    with connection(path) as conn:
        if task_id is not None:
            rows = conn.execute("SELECT d.* FROM diagnosis_records d JOIN task_records r ON r.record_id=d.id WHERE r.task_id=? AND d.data_origin='真实课堂'",(task_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM diagnosis_records WHERE data_origin='真实课堂'").fetchall()
        groups = {key:[] for key in ISSUE_ACTIONS}
        for row in rows:
            r = dict(row); rid = r["id"]
            if r["positive_control_normal"] not in {"是","否"} or r["negative_control_band"] not in {"是","否"}:
                groups["controls"].append(rid)
            if not parse_json(r["followup_json"]).get("final_results"):
                groups["followup"].append(rid)
            if r["teacher_final_cause"] and (not r["student_revision_time"] or int(r["teacher_review_version"] or 0)!=int(r["student_revision_review_version"] or 0)):
                groups["revision"].append(rid)
            if not parse_json(r["verification_plan_json"]):
                groups["plan"].append(rid)
            rubric = parse_json(r["teacher_rubric_json"]).get("initial",{})
            latest = conn.execute("SELECT rubric_json FROM learning_evaluations WHERE record_id=? AND stage='initial' ORDER BY id DESC LIMIT 1",(rid,)).fetchone()
            if latest:
                rubric = parse_json(latest["rubric_json"])
            if rubric.get("证据引用") in {0,1}:
                groups["evidence"].append(rid)
            task = conn.execute("SELECT t.transfer_prompt FROM teaching_tasks t JOIN task_records r ON t.id=r.task_id WHERE r.record_id=?",(rid,)).fetchone()
            if task and task["transfer_prompt"] and not conn.execute("SELECT 1 FROM learning_submissions WHERE record_id=?",(rid,)).fetchone():
                groups["transfer"].append(rid)
    issues = [{"code":key,"label":ISSUE_ACTIONS[key]["label"],"count":len(ids),"case_ids":ids} for key,ids in groups.items() if ids]
    context = {"task_id":task_id,"denominator":len(rows),"issues":issues}
    context["sha"] = hashlib.sha256(dump(context).encode()).hexdigest()
    return context


def request_teaching_suggestions(context):
    """只发送聚合数量，由模型从审核过的动作集合中选取，不生成学生标签或成绩。"""
    import ai_config
    if not ai_config.api_key():
        raise ValueError("尚未配置接口，可直接使用下方已有教学建议。")
    from openai import OpenAI
    anonymous = [{"code":i["code"],"count":i["count"],"allowed_actions":ISSUE_ACTIONS[i["code"]]["actions"]} for i in context["issues"]]
    try:
        client = OpenAI(api_key=ai_config.api_key(),base_url=ai_config.BASE_URL,timeout=ai_config.TEXT_TIMEOUT,max_retries=0)
        response = client.chat.completions.create(**ai_config.request_options(800),temperature=0,
            response_format={"type":"json_object"},messages=[{"role":"user","content":"根据聚合记录为每项选择一个allowed_actions中的教学动作。只返回JSON，格式为{\"suggestions\":[{\"code\":\"...\",\"action\":\"...\"}]}。不得添加新问题、原因、人数、学生评价或其他字段。数据："+dump({"case_count":context["denominator"],"issues":anonymous})}])
        if response.choices[0].finish_reason != "stop":
            raise ValueError()
        data = json.loads(response.choices[0].message.content)
        if set(data)!={"suggestions"} or not isinstance(data["suggestions"],list):
            raise ValueError()
        expected = {i["code"] for i in context["issues"]}
        if len(data["suggestions"])!=len(expected):
            raise ValueError()
        seen=set()
        for item in data["suggestions"]:
            if set(item)!={"code","action"} or item["code"] not in expected or item["code"] in seen or item["action"] not in ISSUE_ACTIONS[item["code"]]["actions"]:
                raise ValueError()
            seen.add(item["code"])
        return {"suggestions":data["suggestions"],"model":response.model,"usage":response.usage.model_dump() if response.usage else {}}
    except Exception:
        raise ValueError("本次教学建议整理未完成，请继续使用程序列出的依据和建议。") from None


def save_suggestions(path,context,response,teacher_authorized=False):
    require_teacher(teacher_authorized)
    current = build_issues(path,context["task_id"],True)
    if current["sha"]!=context["sha"]:
        raise ValueError("课堂记录已变化，请重新整理。")
    allowed = {i["code"] for i in current["issues"]}
    suggestions = response.get("suggestions")
    if (not isinstance(suggestions,list) or len(suggestions)!=len(allowed)
            or any(not isinstance(i,dict) or set(i)!={"code","action"} or i["code"] not in allowed
                   or i["action"] not in ISSUE_ACTIONS[i["code"]]["actions"] for i in suggestions)
            or len({i["code"] for i in suggestions})!=len(allowed)):
        raise ValueError("教学建议超出已核实的问题与动作范围。")
    with connection(path,True) as conn:
        conn.execute("INSERT INTO teaching_suggestions(scope_json,context_sha,result_json,model,usage_json,created_at) VALUES (?,?,?,?,?,?)",
                     (dump({"task_id":context["task_id"]}),context["sha"],dump(response["suggestions"]),response["model"],dump(response["usage"]),now()))


def latest_suggestions(path,context,teacher_authorized=False):
    require_teacher(teacher_authorized)
    with connection(path) as conn:
        row = conn.execute("SELECT * FROM teaching_suggestions WHERE context_sha=? ORDER BY id DESC LIMIT 1",(context["sha"],)).fetchone()
    return dict(row) if row else None


EVALUATION_SPLITS = ["校准集", "独立验收集"]
EVALUATION_QUALITIES = ["清晰", "弱带", "过曝", "低分辨率", "其他"]


def save_evaluation_sample(path,image_path,prepared,reference,disputed,family,split,quality,teacher_authorized=False):
    require_teacher(teacher_authorized)
    from gel_image_assistant import prepare_image,validate_observations
    family = text(family,"原图族编号",100)
    if split not in EVALUATION_SPLITS or quality not in EVALUATION_QUALITIES:
        raise ValueError("评估集合或质量分组无效。")
    current = prepare_image(image_path,prepared["mapping"],prepared["settings"])
    if current["context_key"]!=prepared["context_key"]:
        raise ValueError("图片或设置已经变化，请重新标注。")
    reference = validate_observations(reference,current["mapping"])
    ids = [i["lane_id"] for i in current["mapping"]]
    if not isinstance(disputed,list) or any(type(i) is not int or i not in ids for i in disputed) or len(set(disputed))!=len(disputed):
        raise ValueError("争议泳道无效。")
    with connection(path,True) as conn:
        existing = conn.execute("SELECT split FROM gel_evaluation_samples WHERE family=? OR image_sha=?",(family,current["image_sha"])).fetchall()
        if any(r["split"]!=split for r in existing):
            raise ValueError("同一原图及其变体必须处于同一个评估集合。请沿用原图族编号。")
        seen = conn.execute("SELECT r.response_json FROM gel_evaluation_runs r JOIN gel_evaluation_samples s ON s.id=r.sample_id WHERE s.family=? OR s.image_sha=?", (family,current["image_sha"])).fetchall()
        if any(parse_json(r["response_json"]).get("status")=="success" for r in seen):
            raise ValueError("此原图族已经产生模型观察，不能再补记新的独立参考标注。请使用已保存的参考版本。")
        cursor = conn.execute("INSERT INTO gel_evaluation_samples(family,split,quality,image_path,image_sha,prepared_sha,mapping_json,settings_json,reference_json,disputed_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (family,split,quality,str(image_path),current["image_sha"],current["sent_sha"],dump(current["mapping"]),dump(current["settings"]),dump(reference),dump(disputed),now()))
        return cursor.lastrowid


def evaluation_samples(path,teacher_authorized=False):
    require_teacher(teacher_authorized)
    with connection(path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM gel_evaluation_samples ORDER BY id DESC")]


def prepare_evaluation(sample):
    from gel_image_assistant import prepare_image
    prepared = prepare_image(sample["image_path"],json.loads(sample["mapping_json"]),parse_json(sample["settings_json"]))
    if prepared["image_sha"]!=sample["image_sha"] or prepared["sent_sha"]!=sample["prepared_sha"]:
        raise ValueError("评估原图已改变，不能套用旧参考标注。")
    return prepared


def save_evaluation_run(path,sample_id,prepared,response,teacher_authorized=False):
    require_teacher(teacher_authorized)
    from gel_image_assistant import validate_observations,parse_response,PROMPT_VERSION
    import ai_config
    if response.get("status") not in {"success","failed"}:
        raise ValueError("本次没有实际请求，无需保存评估版本。")
    with connection(path,True) as conn:
        sample = conn.execute("SELECT * FROM gel_evaluation_samples WHERE id=?",(sample_id,)).fetchone()
        if not sample:
            raise ValueError("请先独立保存参考标注。")
        current = prepare_evaluation(dict(sample))
        if current["context_key"]!=prepared["context_key"]:
            raise ValueError("评估图片上下文发生变化。")
        if response["status"]=="success":
            observed=validate_observations(response["observations"],current["mapping"])
            if parse_response(response["raw_response"],current["mapping"])!=observed:
                raise ValueError("原始响应与观察不一致。")
            clean={"status":"success","observations":observed,"raw_response":response["raw_response"],"model_returned":response.get("model_returned",""),"usage":response.get("usage",{})}
        else:
            clean={"status":"failed","error":"本次请求未完成，不能计入识别表现。"}
        cursor=conn.execute("INSERT INTO gel_evaluation_runs(sample_id,context_sha,model,prompt_version,response_json,created_at) VALUES (?,?,?,?,?,?)",
                            (sample_id,current["context_key"],ai_config.MODEL,PROMPT_VERSION,dump(clean),now()))
        return cursor.lastrowid


def evaluation_runs(path,sample_id=None,teacher_authorized=False):
    require_teacher(teacher_authorized)
    with connection(path) as conn:
        rows=conn.execute("SELECT * FROM gel_evaluation_runs"+(" WHERE sample_id=?" if sample_id is not None else "")+" ORDER BY id DESC",(sample_id,) if sample_id is not None else ()).fetchall()
        output=[]
        for r in rows:
            item=dict(r)
            audit=conn.execute("SELECT * FROM gel_evaluation_audits WHERE run_id=? ORDER BY id DESC LIMIT 1",(r["id"],)).fetchone()
            item["audit"]=dict(audit) if audit else None
            output.append(item)
    return output


def save_evaluation_audit(path,run_id,mismatches,note,teacher_authorized=False):
    require_teacher(teacher_authorized)
    with connection(path,True) as conn:
        row=conn.execute("SELECT r.response_json,s.mapping_json FROM gel_evaluation_runs r JOIN gel_evaluation_samples s ON s.id=r.sample_id WHERE r.id=?",(run_id,)).fetchone()
        if not row or parse_json(row["response_json"]).get("status")!="success":
            raise ValueError("未找到成功的观察版本。")
        ids={i["lane_id"] for i in json.loads(row["mapping_json"])}
        if not isinstance(mismatches,list) or any(type(i) is not int or i not in ids for i in mismatches) or len(set(mismatches))!=len(mismatches):
            raise ValueError("泳道错配标注无效。")
        conn.execute("INSERT INTO gel_evaluation_audits(run_id,mismatch_json,note,created_at) VALUES (?,?,?,?)",
                     (run_id,dump(mismatches),text(note,"人工评估备注",required=False),now()))


def evaluation_comparison(sample,run):
    response=parse_json(run["response_json"])
    if response.get("status")!="success":
        return []
    references={i["lane_id"]:i for i in parse_json(sample["reference_json"])["lanes"]}
    disputed=set(json.loads(sample["disputed_json"]))
    mismatch=set(json.loads(run["audit"]["mismatch_json"])) if run.get("audit") else None
    output=[]
    for observed in response["observations"]["lanes"]:
        lid=observed["lane_id"]; ref=references[lid]; a=ref["band_count"]; b=observed["band_count"]
        excluded=lid in disputed or (mismatch is not None and lid in mismatch)
        comparable=not excluded and a is not None and b is not None
        output.append({"样本编号":sample["id"],"原图族":sample["family"],"集合":sample["split"],"质量":sample["quality"],
                       "观察版本":run["id"],"请求模型":run["model"],"返回模型":response.get("model_returned",""),"提示词":run["prompt_version"],
                       "泳道":lid,"参考有争议":lid in disputed,"参考条带数":a,"AI原始条带数":b,
                       "数量可比较":comparable,"数量少于参考":max(a-b,0) if comparable else None,
                       "数量多于参考":max(b-a,0) if comparable else None,
                       "参考未知时保留未知":b is None if a is None and not excluded else None,
                       "参考已知时AI未知":b is None if a is not None and not excluded else None,
                       "泳道错配人工标记":lid in mismatch if mismatch is not None and lid not in disputed else None,
                       "参考形态":ref["pattern"],"AI原始形态":observed["pattern"],
                       "参考位置":ref["position"],"AI原始位置":observed["position"],
                       "参考亮度":ref["brightness"],"AI原始亮度":observed["brightness"]})
    return output


def teaching_report_lines(path,record_id):
    """仅用于已获授权案例报告的内部读取；不调用模型。"""
    context=record_task(path,record_id,teacher_authorized=True)
    lines=[]
    if context["task"]:
        task=context["task"]; lines.append(f"课堂任务：{task['title']}；编号：{task['code']}")
        if context["submission"]:
            s=context["submission"]
            lines.extend(["新案例独立判断："+s["answer"],"新案例依据："+s["reasoning"],f"自报作答用时：{s['minutes'] if s['minutes'] is not None else '未记录'} 分钟"])
    with connection(path) as conn:
        r=conn.execute("SELECT * FROM independent_reviews WHERE record_id=?",(record_id,)).fetchone()
        if r:
            lines.extend(["教师独立判断："+r["cause"],"独立依据："+r["reason"],"独立判断证据等级："+r["evidence_level"]])
        evaluations=conn.execute("SELECT * FROM learning_evaluations WHERE record_id=? ORDER BY id",(record_id,)).fetchall()
        for e in evaluations:
            lines.append(f"人工过程评价版本 {e['id']}：阶段 {e['stage']}；对应版本 {e['source_version']}；{e['rubric_json']}；{e['note']}")
        raw=classroom_record(conn,record_id)
        scheme=parse_json(raw["input_json"]).get("course_scheme_snapshot",{})
        if scheme:
            lines.append("本次采用的课程方案快照："+dump(scheme))
    for retest in load_retests(path,record_id,teacher_authorized=True):
        lines.extend([f"实际复测记录 #{retest['id']}（学生报告，尚需教师复核）",dump(retest["payload"]),"对应验证计划快照："+retest["plan_json"]])
        if retest["image_path"]:
            lines.append("复测图片已另存；原图指纹："+(retest["image_sha"] or ""))
        if retest["review"]:
            lines.extend(["教师复测解释："+retest["review"]["conclusion"],"教师复测依据："+retest["review"]["note"]])
    return lines
