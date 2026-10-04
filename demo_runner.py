"""启动独立的本地参赛演示，课堂数据库和上传目录不参与演示。"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEMO_DIR = ROOT / "data" / "demo"


def configure_demo():
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.update({"PCR_DIAGNOSIS_DB_PATH": str(DEMO_DIR / "demo.db"),
                       "PCR_DIAGNOSIS_UPLOAD_DIR": str(DEMO_DIR / "uploads"),
                       "PCR_DIAGNOSIS_DEMO_MODE": "1", "BIGMODEL_API_KEY": ""})


def seed_demo(reset=False):
    configure_demo()
    import core
    from contextlib import closing
    from followup_agent import apply_followup_choices, plan_followup_questions
    core.DB_PATH = os.environ["PCR_DIAGNOSIS_DB_PATH"]
    core.UPLOAD_DIR = os.environ["PCR_DIAGNOSIS_UPLOAD_DIR"]
    core.init_database()
    with closing(sqlite3.connect(core.DB_PATH)) as conn, conn:
        if reset:
            # 固定演示路径仍检查数据来源，拒绝清理混入的课堂记录。
            if conn.execute("SELECT count(*) FROM diagnosis_records WHERE coalesce(data_origin,'') NOT IN ('模拟演示','规则回归')").fetchone()[0]:
                raise ValueError("演示库中存在非模拟记录，已停止恢复。")
            for table in ("student_revision_history", "teacher_review_history", "diagnosis_records"):
                conn.execute(f"DELETE FROM {table}")
        elif conn.execute("SELECT count(*) FROM diagnosis_records").fetchone()[0]:
            return
    cases = json.loads((ROOT / "demo_cases.json").read_text(encoding="utf-8"))
    for index, case in enumerate(cases, 1):
        raw = {k: case[k] for k in ("abnormality", "template_amount", "annealing_temp", "cycles", "positive_control_normal", "negative_control_band", "description")}
        raw.update({"local_mode": True, "data_origin": "模拟演示", "class_name": "参赛模拟班", "course_name": "模拟课堂", "lane_notes": case["lane_notes"]})
        initial, _, hints, source, debug = core.diagnose(**{k: raw[k] for k in ("abnormality", "template_amount", "annealing_temp", "cycles", "positive_control_normal", "negative_control_band", "description")}, confirmed_text_hints=[])
        code = f"demo-case-{index}"
        illustration = ROOT / case.get("image_path", "")
        image_path = None
        if illustration.is_file():
            upload = BytesIO(illustration.read_bytes())
            upload.name = illustration.name
            image_path, error = core.save_uploaded_image(upload)
            if error:
                raise ValueError(error)
        record_id = core.save_diagnosis_record(raw["abnormality"],raw["template_amount"],raw["annealing_temp"],raw["cycles"],raw["positive_control_normal"],raw["negative_control_band"],raw["description"],core.format_diagnosis_result_text(initial),
                                               gel_image_path=image_path,student_initial_hypothesis=case["initial_hypothesis"],student_access_code=code,initial_results=initial,raw_case=raw,
                                               evidence={"normalized_case": debug["normalized_case"], "text_clues": [], "source": source})
        updated = apply_followup_choices(raw,case["answers"])
        final, _, _, _, debug = core.diagnose(**{k: updated[k] for k in ("abnormality", "template_amount", "annealing_temp", "cycles", "positive_control_normal", "negative_control_band", "description")},
                                             positive_control_detail=updated.get("positive_control_detail"), negative_control_detail=updated.get("negative_control_detail"), band_pattern=updated.get("band_pattern"),
                                             confirmed_text_hints=[],extra_text_hints=case["confirmed_hints"])
        questions, source = plan_followup_questions(raw,initial)
        core.save_followup_reassessment(record_id,core.format_diagnosis_result_text(final),updated["positive_control_normal"],updated["negative_control_band"],
                                       {"initial_results": initial, "final_results": final, "questions": questions, "answers": case["answers"], "extra_hints": case["confirmed_hints"],
                                        "updated_case": updated, "question_source": source, "positive_control_detail": updated.get("positive_control_detail"), "negative_control_detail": updated.get("negative_control_detail"), "band_pattern": updated.get("band_pattern")})
        core.save_teacher_confirmation(record_id,case["teacher_cause"],"【模拟材料】"+case["teacher_note"],evidence_level="经验复核")
        if index != 3:
            core.save_student_revision(record_id,code,case["student_revision"],case["revision_reason"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-demo", action="store_true", help="恢复固定的模拟案例，不操作课堂库")
    parser.add_argument("--prepare-only", action="store_true", help="只准备演示数据")
    parser.add_argument("--port", type=int, default=8513)
    args = parser.parse_args()
    os.chdir(ROOT)
    seed_demo(args.reset_demo)
    if args.prepare_only:
        print("独立模拟案例已准备。查询码：demo-case-1、demo-case-2、demo-case-3。")
        return
    secrets = DEMO_DIR / "secrets.toml"
    secrets.write_text('TEACHER_ACCESS_CODE="demo-teacher"\nDEV_ACCESS_CODE="demo-dev"\n',encoding="utf-8")
    print(f"本地演示：http://127.0.0.1:{args.port}；教师码 demo-teacher，调试码 demo-dev。全部为模拟数据。")
    subprocess.run([sys.executable,"-m","streamlit","run","app.py","--server.address","127.0.0.1","--server.port",str(args.port),
                    "--server.headless","true","--secrets.files",str(secrets)],cwd=ROOT,check=True)


if __name__ == "__main__":
    main()
