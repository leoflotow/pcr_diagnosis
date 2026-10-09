"""兼容原有案例表的证据快照和学习记录。"""

from contextlib import closing
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from evidence_support import cause_id, parse_json, rules_version


ADDITIONAL_COLUMNS = {
    "input_json": "TEXT", "diagnosis_snapshot_json": "TEXT",
    "course_name": "TEXT", "class_name": "TEXT", "experiment_name": "TEXT", "group_code": "TEXT",
    "data_origin": "TEXT", "teacher_cause_id": "TEXT", "teacher_evidence_level": "TEXT",
    "teacher_review_version": "INTEGER DEFAULT 0", "student_revision_review_version": "INTEGER DEFAULT 0",
    "verification_plan_json": "TEXT", "verification_feedback": "TEXT",
    "teacher_rubric_json": "TEXT",
}


def now():
    return datetime.now().isoformat(timespec="microseconds")


def prepare_database(path):
    """首次升级已有库时先做 SQLite 一致性备份，不删除旧库。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return
    with closing(sqlite3.connect(path)) as conn, conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(diagnosis_records)")}
        if columns and "diagnosis_snapshot_json" not in columns:
            backup = path.with_name(path.name + ".before-competition-upgrade.bak")
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as target, target:
                    conn.backup(target)
        has_gel_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gel_observation_runs'").fetchone()
        if columns and not has_gel_table:
            backup = path.with_name(path.name + ".before-gel-observation.bak")
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as target:
                    conn.backup(target)
        has_teaching = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='teaching_tasks'").fetchone()
        if columns and not has_teaching:
            backup = path.with_name(path.name + ".before-teaching-workflow.bak")
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as target:
                    conn.backup(target)


def migrate(conn):
    columns = {r[1] for r in conn.execute("PRAGMA table_info(diagnosis_records)")}
    for name, declaration in ADDITIONAL_COLUMNS.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE diagnosis_records ADD COLUMN {name} {declaration}")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS teacher_review_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER NOT NULL,
            review_version INTEGER NOT NULL, cause_id TEXT, cause TEXT, note TEXT,
            evidence_level TEXT, verification_feedback TEXT, created_at TEXT,
            UNIQUE(record_id, review_version)
        );
        CREATE TABLE IF NOT EXISTS student_revision_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER NOT NULL,
            review_version INTEGER NOT NULL, cause TEXT, reason TEXT, created_at TEXT,
            UNIQUE(record_id, review_version)
        );
        CREATE TABLE IF NOT EXISTS gel_observation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER NOT NULL,
            context_key TEXT NOT NULL, image_sha TEXT NOT NULL, sent_sha TEXT NOT NULL,
            mapping_json TEXT NOT NULL, settings_json TEXT NOT NULL,
            prompt_version TEXT NOT NULL, model_requested TEXT NOT NULL, model_returned TEXT,
            status TEXT NOT NULL, error TEXT, observations_json TEXT, raw_response TEXT,
            usage_json TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY(record_id) REFERENCES diagnosis_records(id)
        );
        CREATE INDEX IF NOT EXISTS gel_run_context ON gel_observation_runs(record_id, context_key, id);
        CREATE TABLE IF NOT EXISTS gel_observation_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
            record_id INTEGER NOT NULL, actor TEXT NOT NULL, source_student_check_id INTEGER,
            entries_json TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES gel_observation_runs(id),
            FOREIGN KEY(record_id) REFERENCES diagnosis_records(id)
        );
    """)
    history_columns = {r[1] for r in conn.execute("PRAGMA table_info(teacher_review_history)")}
    if "rubric_json" not in history_columns:
        conn.execute("ALTER TABLE teacher_review_history ADD COLUMN rubric_json TEXT")
    from teaching_workflow import migrate as migrate_teaching
    migrate_teaching(conn)


def authorized_gel_record(path, record_id, code=None, teacher_authorized=False):
    """学生必须持有对应查询码；教师调用由已验证页面授权。"""
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM diagnosis_records WHERE id=?", (record_id,)).fetchone()
    if not row or row["data_origin"] in {"模拟演示", "规则回归"}:
        return None
    if not teacher_authorized:
        digest = hashlib.sha256(str(code or "").strip().encode()).hexdigest()
        if not code or row["student_access_hash"] != digest:
            return None
    return dict(row)


def load_gel_history(path, record_id, code=None, teacher_authorized=False):
    if not authorized_gel_record(path, record_id, code, teacher_authorized):
        return {"runs": [], "checks": []}
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='gel_observation_runs'").fetchone():
            return {"runs": [], "checks": []}
        runs = [dict(row) for row in conn.execute(
            "SELECT * FROM gel_observation_runs WHERE record_id=? ORDER BY id DESC", (record_id,))]
        checks = [dict(row) for row in conn.execute(
            "SELECT * FROM gel_observation_checks WHERE record_id=? ORDER BY id DESC", (record_id,))]
    for run in runs:
        for source, target in [("mapping_json", "mapping"), ("settings_json", "settings"),
                               ("observations_json", "observations"), ("usage_json", "usage")]:
            run[target] = json.loads(run[source]) if run[source] else None
    for check in checks:
        check["entries"] = json.loads(check["entries_json"])
    return {"runs": runs, "checks": checks}


def save_gel_run(path, record_id, code, prepared, response):
    from gel_image_assistant import prepare_image, validate_observations, PROMPT_VERSION
    import ai_config
    record = authorized_gel_record(path, record_id, code)
    if not record or not record["gel_image_path"]:
        raise ValueError("无权更新该案例，或案例未保存图片。")
    current = prepare_image(record["gel_image_path"], prepared["mapping"], prepared["settings"])
    if current["context_key"] != prepared["context_key"]:
        raise ValueError("图片已变化，请重新核对后再识别。")
    status = response.get("status")
    if status not in {"success", "failed"}:
        raise ValueError("本次未进行有效请求，无需保存观察记录。")
    observations = None
    raw = None
    if status == "success":
        observations = validate_observations(response["observations"], current["mapping"])
        # 原始候选须通过同一白名单校验，不把模型的原因或自由说明写入库。
        from gel_image_assistant import parse_response
        raw = response["raw_response"]
        if parse_response(raw, current["mapping"]) != observations:
            raise ValueError("模型原始候选与解析观察不一致。")
    with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
        cursor = conn.execute("""INSERT INTO gel_observation_runs
            (record_id,context_key,image_sha,sent_sha,mapping_json,settings_json,prompt_version,
             model_requested,model_returned,status,error,observations_json,raw_response,usage_json,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                record_id,current["context_key"],current["image_sha"],current["sent_sha"],
                json.dumps(current["mapping"], ensure_ascii=False), json.dumps(current["settings"]),
                PROMPT_VERSION,ai_config.MODEL,response.get("model_returned", ""),status,
                response.get("error", ""),json.dumps(observations, ensure_ascii=False) if observations else None,
                raw,json.dumps(response.get("usage", {})),now()))
        return cursor.lastrowid


def save_gel_check(path, record_id, run_id, context_key, entries, actor, code=None,
                   teacher_authorized=False, source_student_check_id=None):
    from gel_image_assistant import prepare_image, validate_checks
    if actor not in {"student", "teacher"} or actor == "teacher" and not teacher_authorized:
        raise ValueError("图像核对权限无效。")
    record = authorized_gel_record(path, record_id, code, teacher_authorized if actor == "teacher" else False)
    if not record:
        raise ValueError("无权更新该案例。")
    with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.row_factory = sqlite3.Row
        run = conn.execute("SELECT * FROM gel_observation_runs WHERE id=? AND record_id=? AND status='success'",
                           (run_id,record_id)).fetchone()
        if not run or run["context_key"] != context_key:
            raise ValueError("观察记录已变化，请刷新。")
        latest_run = conn.execute("SELECT id FROM gel_observation_runs WHERE record_id=? AND status='success' ORDER BY id DESC LIMIT 1", (record_id,)).fetchone()
        if not latest_run or latest_run["id"] != run_id:
            raise ValueError("已有新的图像观察版本，旧版本只读，请刷新。")
        prepared = prepare_image(record["gel_image_path"], json.loads(run["mapping_json"]), json.loads(run["settings_json"]))
        if prepared["context_key"] != context_key:
            raise ValueError("原图或观察配置已经改变，请重新识别。")
        if actor == "teacher":
            latest = conn.execute("SELECT id FROM gel_observation_checks WHERE run_id=? AND actor='student' ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
            if (latest["id"] if latest else None) != source_student_check_id:
                raise ValueError("学生核对记录已更新，请刷新后复核。")
        clean = validate_checks(entries, json.loads(run["observations_json"]))
        cursor = conn.execute("""INSERT INTO gel_observation_checks
            (run_id,record_id,actor,source_student_check_id,entries_json,created_at) VALUES (?,?,?,?,?,?)""",
            (run_id,record_id,actor,source_student_check_id,json.dumps(clean,ensure_ascii=False),now()))
        return cursor.lastrowid


def gel_report_lines(path, record_id):
    """导出已保存候选与人工核对，绝不请求模型或生成诊断。"""
    history = load_gel_history(path, record_id, teacher_authorized=True)
    run = next((item for item in history["runs"] if item["status"] == "success"), None)
    if not run:
        return []
    lines = ["AI 图像观察及人工核对均不直接参与诊断、原因排序或评分。",
             f"观察版本：#{run['id']}；时间：{run['created_at']}；模型：{run['model_requested']}；提示词：{run['prompt_version']}",
             f"对应原图指纹：{run['image_sha']}；处理图指纹：{run['sent_sha']}",
             "AI 原始候选（需对照原图核对）：",
             f"候选可读性：{run['observations']['quality']}；需核对问题：{'、'.join(run['observations']['quality_issues']) or '未提出'}"]
    record = authorized_gel_record(path, record_id, teacher_authorized=True)
    current_path = Path(record["gel_image_path"] or "")
    if not current_path.is_file() or hashlib.sha256(current_path.read_bytes()).hexdigest() != run["image_sha"]:
        lines.insert(1, "当前原图缺失或已改变；以下为历史图像记录，不能套用于当前图片。")
    roles = {item["lane_id"]: item["role"] for item in run["mapping"]}
    for item in run["observations"]["lanes"]:
        lines.append(f"泳道 {item['lane_id']}（人工指定：{roles[item['lane_id']]}）：候选数量 {item['band_count'] if item['band_count'] is not None else '未知'}；{item['pattern']}；{item['position']}；{item['brightness']}")
    student = next((item for item in history["checks"] if item["run_id"] == run["id"] and item["actor"] == "student"), None)
    teacher = next((item for item in history["checks"] if item["run_id"] == run["id"] and item["actor"] == "teacher"), None)
    for check, label in [(student, "学生核对"), (teacher, "教师图像复核")]:
        if not check:
            lines.append(label + "：未保存。")
            continue
        lines.append(f"{label}版本 #{check['id']}；时间：{check['created_at']}")
        if label == "教师图像复核" and check["source_student_check_id"] != (student["id"] if student else None):
            lines.append("此教师图像复核对应旧版学生核对，待重新查看。")
        for item in check["entries"]:
            lines.append(f"泳道 {item['lane_id']}：{item['state']}；数量 {item['band_count'] if item['band_count'] is not None else '未知'}；{item['pattern']}；{item['position']}；{item['brightness']}；人工备注：{item['note'] or '无'}")
    return lines


def snapshot(results, raw_case=None, evidence=None):
    return {"results": results or [], "rules_version": rules_version(), "created_at": now(),
            "input": raw_case or {}, "evidence": evidence or {}}


def save_record(path, abnormality, template_amount, annealing_temp, cycles,
                positive_control_normal, negative_control_band, description, diagnosis_result,
                gel_image_path=None, student_initial_hypothesis=None, student_access_code=None,
                initial_results=None, raw_case=None, evidence=None):
    raw_case = raw_case or {}
    followup = {"initial_results": initial_results} if initial_results else {}
    values = {
        "abnormality": abnormality, "template_amount": template_amount, "annealing_temp": annealing_temp,
        "cycles": cycles, "positive_control_normal": positive_control_normal,
        "negative_control_band": negative_control_band, "description": description,
        "diagnosis_result": diagnosis_result, "diagnosis_time": now(), "gel_image_path": gel_image_path,
        "student_initial_hypothesis": (student_initial_hypothesis or "").strip(),
        "student_access_hash": hashlib.sha256(student_access_code.encode()).hexdigest() if student_access_code else None,
        "followup_json": json.dumps(followup, ensure_ascii=False),
        "input_json": json.dumps(raw_case, ensure_ascii=False),
        "diagnosis_snapshot_json": json.dumps(snapshot(initial_results, raw_case, evidence), ensure_ascii=False),
        **{k: raw_case.get(k, "") for k in ("course_name", "class_name", "experiment_name", "group_code")},
        "data_origin": raw_case.get("data_origin", "未标注"),
    }
    with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
        cursor = conn.execute(f"INSERT INTO diagnosis_records ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
        from teaching_workflow import link_new_record
        link_new_record(conn, cursor.lastrowid, raw_case)
        return cursor.lastrowid


def save_review(path, record_id, cause, note, evidence_level="经验复核", verification_feedback="", expected_version=None, rubric=None, data_origin=None):
    if not str(cause or "").strip():
        return False
    with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM diagnosis_records WHERE id=?", (record_id,)).fetchone()
        if not row or (expected_version is not None and int(row["teacher_review_version"] or 0) != expected_version):
            return False
        version = int(row["teacher_review_version"] or 0)
        independent = conn.execute("SELECT cause FROM independent_reviews WHERE record_id=?", (record_id,)).fetchone()
        if independent and cause_id(independent["cause"]) != cause_id(cause) and not str(note or "").strip():
            # 改变独立判断时必须留下理由，原独立判断始终保留。
            return False
        rubric_text = json.dumps(rubric or {}, ensure_ascii=False)
        if (row["teacher_final_cause"] == cause.strip() and (row["teacher_note"] or "") == note
                and row["teacher_evidence_level"] == evidence_level
                and (row["verification_feedback"] or "") == verification_feedback):
            # 评分或来源标注的更新不产生新的反馈版本，避免反复要求学生修订。
            conn.execute("UPDATE diagnosis_records SET teacher_rubric_json=?,data_origin=? WHERE id=?",
                         (rubric_text, data_origin or row["data_origin"], record_id))
            conn.execute("UPDATE teacher_review_history SET rubric_json=? WHERE record_id=? AND review_version=?",
                         (rubric_text, record_id, version))
            return True
        if row["teacher_final_cause"] and version == 0:
            conn.execute("INSERT OR IGNORE INTO teacher_review_history (record_id,review_version,cause_id,cause,note,evidence_level,created_at) VALUES (?,0,?,?,?,?,?)",
                         (record_id, cause_id(row["teacher_final_cause"]), row["teacher_final_cause"], row["teacher_note"], "旧记录，证据等级未标注", row["teacher_confirm_time"]))
        version += 1
        timestamp = now()
        conn.execute("INSERT INTO teacher_review_history (record_id,review_version,cause_id,cause,note,evidence_level,verification_feedback,created_at,rubric_json) VALUES (?,?,?,?,?,?,?,?,?)",
                     (record_id,version,cause_id(cause),cause.strip(),note,evidence_level,verification_feedback,timestamp,rubric_text))
        conn.execute("UPDATE diagnosis_records SET teacher_final_cause=?,teacher_note=?,teacher_confirm_time=?,teacher_cause_id=?,teacher_review_version=?,teacher_evidence_level=?,verification_feedback=?,teacher_rubric_json=?,data_origin=? WHERE id=?",
                     (cause.strip(),note,timestamp,cause_id(cause),version,evidence_level,verification_feedback,rubric_text,data_origin or row["data_origin"],record_id))
        return True


def save_reassessment(path, record_id, result_text, positive, negative, followup_data):
    with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM diagnosis_records WHERE id=?", (record_id,)).fetchone()
        if not row or str(row["teacher_final_cause"] or "").strip():
            return False
        data = dict(followup_data)
        previous = parse_json(row["followup_json"])
        data["initial_results"] = previous.get("initial_results") or data.get("initial_results", [])
        data["rules_version"] = rules_version()
        data["created_at"] = now()
        snap = parse_json(row["diagnosis_snapshot_json"])
        data["initial_snapshot"] = snap
        data["final_snapshot"] = snapshot(data.get("final_results"), data.get("updated_case"), data.get("evidence"))
        conn.execute("UPDATE diagnosis_records SET diagnosis_result=?,positive_control_normal=?,negative_control_band=?,followup_json=? WHERE id=?",
                     (result_text,positive,negative,json.dumps(data,ensure_ascii=False),record_id))
        return True


def save_revision(path, record_id, code, cause, reason, expected_version=None):
    if not all(str(v or "").strip() for v in (record_id,code,cause,reason)):
        return False
    digest = hashlib.sha256(code.strip().encode()).hexdigest()
    with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM diagnosis_records WHERE id=? AND student_access_hash=?", (record_id,digest)).fetchone()
        if not row or not row["teacher_final_cause"]:
            return False
        version = int(row["teacher_review_version"] or 0)
        if expected_version is not None and version != expected_version:
            return False
        if row["student_revision_time"] and int(row["student_revision_review_version"] or 0) == version:
            return False
        if row["student_revision_time"]:
            conn.execute("INSERT OR IGNORE INTO student_revision_history (record_id,review_version,cause,reason,created_at) VALUES (?,?,?,?,?)",
                         (record_id,int(row["student_revision_review_version"] or 0),row["student_revised_cause"],row["student_revision_reason"],row["student_revision_time"]))
        timestamp = now()
        conn.execute("UPDATE diagnosis_records SET student_revised_cause=?,student_revision_reason=?,student_revision_time=?,student_revision_review_version=? WHERE id=?",
                     (cause.strip(),reason.strip(),timestamp,version,record_id))
        conn.execute("INSERT INTO student_revision_history (record_id,review_version,cause,reason,created_at) VALUES (?,?,?,?,?)",
                     (record_id,version,cause.strip(),reason.strip(),timestamp))
        return True


def save_verification_plan(path, record_id, code, plan):
    fields = ("hypothesis", "variable", "controls", "expected_result", "interpretation")
    if not all(str(plan.get(f, "")).strip() for f in fields):
        return False
    digest = hashlib.sha256(str(code or "").strip().encode()).hexdigest()
    data = {f: str(plan[f]).strip() for f in fields}
    data.update({"kind": "计划，尚未复测", "updated_at": now()})
    with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
        cursor = conn.execute("UPDATE diagnosis_records SET verification_plan_json=? WHERE id=? AND student_access_hash=?",
                              (json.dumps(data,ensure_ascii=False),record_id,digest))
        return cursor.rowcount == 1


def init_database(path):
    """初始化SQLite数据库，创建诊断记录表"""
    prepare_database(path)
    conn = sqlite3.connect(path)
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

    migrate(conn)
    conn.commit()
    conn.close()
