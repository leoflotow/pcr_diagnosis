"""在临时库验证正式教学页面、查询和验证方案流程。"""

import hashlib
import json
import os
import re
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
import ai_config
import case_storage
from streamlit.testing.v1 import AppTest
from PIL import Image


def check(app):
    assert not app.exception, [item.message for item in app.exception]
    messages = []
    for kind in ("markdown", "caption", "info", "success", "warning", "error", "text"):
        messages.extend(str(item.value) for item in app.get(kind))
    for item in app.selectbox:
        messages.extend(str(option) for option in item.options)
    text = "\n".join(messages)
    assert not re.search(r"比赛|竞赛|参赛|演示|demo|虚拟|模拟", text, re.IGNORECASE), text
    return app


def labelled(elements, label):
    matches = [item for item in elements if item.label == label]
    assert len(matches) == 1, (label, len(matches))
    return matches[0]


def main(with_image=True):
    original = ROOT / "data" / "app.db"
    before = (original.stat().st_size, original.stat().st_mtime_ns) if original.exists() else None
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        stack.enter_context(patch.object(core, "DB_PATH", str(Path(directory) / "ui.db")))
        stack.enter_context(patch.object(core, "UPLOAD_DIR", str(Path(directory) / "uploads")))
        stack.enter_context(patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "PCR_DIAGNOSIS_DEMO_MODE": "0"}))
        app = check(AppTest.from_file("pages/1_学生端.py", default_timeout=15).run())
        values = {
            "student_form_abnormality": "无条带", "student_form_template_amount": 1.0,
            "student_form_annealing_temp": 60.0, "student_form_cycles": 30,
            "student_form_positive_control_normal": "否", "student_form_negative_control_band": "否",
            "student_form_description": "样本与阳性对照都没有目标条带，尚未核对配液记录。",
            "student_form_initial_hypothesis": "我认为模板量不足，因为样本没有目标条带。",
            "student_form_local_mode": True,
        }
        storage = dict(app.session_state["student_data_storage"])
        storage.update(values)
        app.session_state["student_data_storage"] = storage
        for key, value in values.items():
            app.session_state[key] = value
        check(app.run())
        assert "student_load_demo" not in [item.key for item in app.button]

        if not with_image:
            app.session_state["student_uploaded_image_bytes"] = None
            app.session_state["student_uploaded_image_name"] = ""
        for step in range(1, 4):
            check(app.button(key=f"student_next_step_{step}").click().run())
            if step == 2 and with_image:
                buffer = BytesIO()
                Image.new("RGB", (20, 20), "white").save(buffer, format="PNG")
                app.session_state["student_uploaded_image_bytes"] = buffer.getvalue()
                app.session_state["student_uploaded_image_name"] = "流程校验.png"
                check(app.run())
        check(app.button(key="student_run_diagnosis").click().run())
        payload = app.session_state["student_last_payload"]
        record_id = payload["record_id"]
        code = app.session_state["student_access_code"]
        assert core.load_student_record(code)["data_origin"] == "真实课堂"
        saved_image = core.load_student_record(code)["gel_image_path"]
        assert bool(saved_image) == with_image
        if with_image:
            assert Path(saved_image).exists()
            candidate = {"quality": "部分可辨", "quality_issues": ["弱带不清"], "lanes": [
                {"lane_id": 1, "band_count": 1, "pattern": "单条", "position": "中部", "brightness": "较弱"}]}
            response = {"status": "success", "observations": candidate, "raw_response": json.dumps(candidate),
                        "model_returned": "deepseek-flash", "usage": {"total_tokens": 10}}
            case_before_image = core.load_record_by_id(record_id)
            stack.enter_context(patch.object(ai_config, "api_key", return_value="fake-ui-test"))
            mocked_image = stack.enter_context(patch("gel_image_ui.request_observation", return_value=response))
            check(app.run())
            consent = labelled(app.checkbox, "我已确认发送区域不含姓名等身份信息，同意发送至 DeepSeek 辅助观察")
            check(consent.check().run())
            check(app.button(key=f"gel_student_{record_id}_request").click().run())
            mocked_image.assert_called_once()
            history = case_storage.load_gel_history(core.DB_PATH, record_id, code)
            run = history["runs"][0]
            editor_key = f"gel_student_{record_id}_check_{run['id']}_0_0_editor"
            app.session_state[editor_key] = {"edited_rows": {0: {"state": "已修正", "band_count": 2, "pattern": "多条"}},
                                            "added_rows": [], "deleted_rows": []}
            check(labelled(app.button, "保存核对记录").click().run())
            history = case_storage.load_gel_history(core.DB_PATH, record_id, code)
            assert history["checks"][0]["entries"][0]["state"] == "已修正", history
            assert history["checks"][0]["entries"][0]["band_count"] == 2
            assert core.load_record_by_id(record_id) == case_before_image
            check(app.run())
            check(app.button(key=f"gel_student_{record_id}_request").click().run())
            mocked_image.assert_called_once()
        for item in app.selectbox:
            if item.key == "student_followup_positive_control":
                item.select("完全无带")
            elif item.key == "student_followup_negative_control":
                item.select("无带")
        app.text_area(key="student_followup_operation").set_value("核对配液单，确认漏加聚合酶")
        check(app.run())
        check(app.button(key="student_followup_extract").click().run())
        assert app.multiselect(key="student_followup_confirmed_hints").value == []
        app.multiselect(key="student_followup_confirmed_hints").select("漏加试剂")
        check(app.button(key="student_followup_reassess").click().run())
        assert app.session_state["student_last_payload"]["results"][0]["原因"] == "PCR体系漏加或关键试剂失活"

        hidden_id = core.save_diagnosis_record(
            "无条带", 1.0, 60.0, 30, "否", "否", "内部案例不得展示", "",
            student_access_code="internal-case", raw_case={"data_origin": "模拟演示", "class_name": "内部案例不得展示"})
        assert not core.is_classroom_record(core.load_record_by_id(hidden_id))
        teacher = AppTest.from_file("pages/2_教师端.py", default_timeout=15)
        teacher.session_state["teacher_verified"] = True
        check(teacher.run())
        check(teacher.radio(key="teacher_workspace").set_value("常规案例复核").run())
        assert teacher.selectbox(key="teacher_dashboard_origin").value == "真实课堂"
        assert "内部案例不得展示" not in "\n".join(str(item.value) for item in teacher.markdown)
        assert "内部案例不得展示" not in teacher.selectbox(key="teacher_dashboard_class_filter").options
        if with_image:
            case_before_image = core.load_record_by_id(record_id)
            history = case_storage.load_gel_history(core.DB_PATH, record_id, code)
            student_check = history["checks"][0]
            key = f"gel_teacher_{record_id}_check_{run['id']}_0_{student_check['id']}_editor"
            teacher.session_state[key] = {"edited_rows": {0: {"state": "无法确认"}}, "added_rows": [], "deleted_rows": []}
            check(labelled(teacher.button, "保存图像复核").click().run())
            assert core.load_record_by_id(record_id) == case_before_image
            history = case_storage.load_gel_history(core.DB_PATH, record_id, code)
            assert history["checks"][0]["actor"] == "teacher"
            assert history["checks"][0]["entries"][0]["band_count"] is None
        labelled(teacher.selectbox, "最终原因").select("PCR体系漏加或关键试剂失活")
        labelled(teacher.text_area, "教师备注").set_value("核对配液单，确认遗漏；请设计验证")
        labelled(teacher.selectbox, "结论证据等级").select("原始记录支持")
        check(labelled(teacher.button, "保存复核结果").click().run())
        assert core.load_record_by_id(record_id)["teacher_review_version"] == 1

        restored = check(AppTest.from_file("pages/1_学生端.py", default_timeout=15).run())
        labelled(restored.text_input, "案例查询码").set_value("internal-case")
        check(labelled(restored.button, "找回案例").click().run())
        assert any("未找到对应案例" in item.value for item in restored.error)
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
        assert "生物实验智学平台" in report
        assert core.load_case_history(record_id)["student"]

        for page, flags in [("app.py", {}), ("pages/3_开发调试端.py", {"dev_verified": True})]:
            test = AppTest.from_file(page, default_timeout=15)
            for name, value in flags.items():
                test.session_state[name] = value
            check(test.run())
            assert "dev_reset_demo" not in [item.key for item in test.button]
    if before:
        assert (original.stat().st_size, original.stat().st_mtime_ns) == before
    print(f"{'有图' if with_image else '无图'}流程：四页、向导、手动确认、补证、教师复核、跨会话查询、学生修订、验证计划与报告通过；课堂库未改动。")


if __name__ == "__main__":
    for with_image in [False, True]:
        main(with_image)
