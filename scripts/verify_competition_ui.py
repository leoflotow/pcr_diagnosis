"""在临时库验证参赛版学生、教师、查询和验证方案流程。"""

import hashlib
import json
import os
import sys
import tempfile
from io import BytesIO
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import core
from streamlit.testing.v1 import AppTest
from PIL import Image


def check(app):
    assert not app.exception, [item.message for item in app.exception]
    return app


def labelled(elements, label):
    matches = [item for item in elements if item.label == label]
    assert len(matches) == 1, (label, len(matches))
    return matches[0]


def main(with_image=True):
    original = ROOT / "data" / "app.db"
    before = hashlib.sha256(original.read_bytes()).hexdigest() if original.exists() else None
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        stack.enter_context(patch.object(core, "DB_PATH", str(Path(directory) / "ui.db")))
        stack.enter_context(patch.object(core, "UPLOAD_DIR", str(Path(directory) / "uploads")))
        stack.enter_context(patch.dict(os.environ, {"BIGMODEL_API_KEY": "", "PCR_DIAGNOSIS_DEMO_MODE": "0"}))
        app = check(AppTest.from_file("pages/1_学生端.py", default_timeout=15).run())
        app.button(key="student_load_demo").click().run()
        if not with_image:
            app.session_state["student_uploaded_image_bytes"] = None
            app.session_state["student_uploaded_image_name"] = ""
        for step in range(1, 4):
            check(app.button(key=f"student_next_step_{step}").click().run())
            if step == 2 and with_image:
                buffer = BytesIO()
                Image.new("RGB", (20, 20), "white").save(buffer, format="PNG")
                app.session_state["student_uploaded_image_bytes"] = buffer.getvalue()
                app.session_state["student_uploaded_image_name"] = "模拟测试.png"
                check(app.run())
        check(app.button(key="student_run_diagnosis").click().run())
        payload = app.session_state["student_last_payload"]
        record_id = payload["record_id"]
        code = app.session_state["student_access_code"]
        assert core.load_student_record(code)["data_origin"] == "模拟演示"
        saved_image = core.load_student_record(code)["gel_image_path"]
        assert bool(saved_image) == with_image
        if with_image:
            assert Path(saved_image).exists()
        for item in app.selectbox:
            if item.key == "student_followup_positive_control":
                item.select("完全无带")
            elif item.key == "student_followup_negative_control":
                item.select("无带")
        app.text_area(key="student_followup_operation").set_value("核对模拟配液单，确认漏加聚合酶")
        check(app.run())
        check(app.button(key="student_followup_extract").click().run())
        assert app.multiselect(key="student_followup_confirmed_hints").value == []
        app.multiselect(key="student_followup_confirmed_hints").select("漏加试剂")
        check(app.button(key="student_followup_reassess").click().run())
        assert app.session_state["student_last_payload"]["results"][0]["原因"] == "PCR体系漏加或关键试剂失活"

        teacher = AppTest.from_file("pages/2_教师端.py", default_timeout=15)
        teacher.session_state["teacher_verified"] = True
        check(teacher.run())
        assert teacher.selectbox(key="teacher_dashboard_origin").value == "真实课堂"
        labelled(teacher.selectbox, "最终原因").select("PCR体系漏加或关键试剂失活")
        labelled(teacher.text_area, "教师备注").set_value("核对模拟配液单，确认遗漏；请设计验证")
        labelled(teacher.selectbox, "结论证据等级").select("原始记录支持")
        check(labelled(teacher.button, "保存复核结果").click().run())
        assert core.load_record_by_id(record_id)["teacher_review_version"] == 1
        teacher.selectbox(key="teacher_dashboard_origin").select("模拟演示").run()
        check(teacher)

        restored = check(AppTest.from_file("pages/1_学生端.py", default_timeout=15).run())
        labelled(restored.text_input, "案例查询码").set_value(code)
        check(labelled(restored.button, "找回案例").click().run())
        labelled(restored.text_input, "看到教师反馈后，你现在认为最可能的原因是什么？").set_value("PCR体系漏加或关键试剂失活")
        labelled(restored.text_area, "哪些证据让你保留或修改了初判？").set_value("阳性也无带，配液单确认遗漏，不能只归因为样本模板")
        check(labelled(restored.button, "提交修订判断").click().run())
        for field, value in {"hypothesis": "漏加聚合酶", "variable": "重新核对配液，其余条件一致", "controls": "阳性、阴性与样本", "expected_result": "阳性恢复目标条带", "interpretation": "若仍失败排查其他体系因素"}.items():
            restored.text_area(key=f"verification_{record_id}_{field}").set_value(value)
        check(labelled(restored.button, "保存验证方案").click().run())
        record = core.load_student_record(code)
        assert record["student_revision_review_version"] == 1
        assert json.loads(record["verification_plan_json"])["kind"] == "计划，尚未复测"
        report = core.build_case_review_report({"record_id": record_id})
        assert "下一步验证方案（计划记录，尚未复测）" in report
        assert core.load_case_history(record_id)["student"]

        for page, flags in [("app.py", {}), ("pages/3_开发调试端.py", {"dev_verified": True})]:
            test = AppTest.from_file(page, default_timeout=15)
            for name, value in flags.items():
                test.session_state[name] = value
            check(test.run())
    if before:
        assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    print(f"{'有图' if with_image else '无图'}流程：四页、向导、手动确认、补证、教师复核、跨会话查询、学生修订、验证计划与报告通过；课堂库未改动。")


if __name__ == "__main__":
    for with_image in [False, True]:
        main(with_image)
