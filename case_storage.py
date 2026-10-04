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
    """)
    history_columns = {r[1] for r in conn.execute("PRAGMA table_info(teacher_review_history)")}
    if "rubric_json" not in history_columns:
        conn.execute("ALTER TABLE teacher_review_history ADD COLUMN rubric_json TEXT")


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


def save_revision(path, record_id, code, cause, reason):
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
