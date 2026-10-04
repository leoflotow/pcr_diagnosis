import json
from io import BytesIO
from PIL import Image
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import core
from evidence_support import cause_id, learning_progress, normalize_cause_label, template_mass_ng, validate_experiment_parameters
from followup_agent import plan_followup_questions


class EvidenceRegressionTests(unittest.TestCase):
    def test_demo_codes_cannot_override_classroom_access(self):
        with patch.dict(os.environ, {"PCR_DIAGNOSIS_DEMO_MODE": "1", "TEACHER_ACCESS_CODE": "classroom-only"}), patch.object(core, "DB_PATH", "data/app.db"), patch.object(core.st, "secrets", {}):
            self.assertFalse(core.is_demo_environment())
            self.assertEqual(core.get_config_value("TEACHER_ACCESS_CODE"), "classroom-only")
    def test_normal_terms_negation_and_questions_do_not_become_causes(self):
        for text in ["未发生污染", "未发现污染", "没有引物问题", "已排查，没漏加试剂", "使用了新引物，primer浓度按方案配置", "有污染？", "no contamination"]:
            with self.subTest(text=text):
                self.assertEqual(core.extract_text_clues(text), [])
        self.assertEqual(core.extract_text_clues("未发生污染，确认模板浓度低"), ["模板量不足"])

    def test_teacher_conclusion_keeps_negation_and_multiple_causes_separate(self):
        self.assertEqual(normalize_cause_label("排除模板量不足，确认是污染"), "污染")
        self.assertEqual(normalize_cause_label("模板量不足和污染均待核实"), "")
        self.assertEqual(cause_id("模板浓度低"), cause_id("模板量不足"))
        self.assertNotEqual(cause_id("引物问题"), cause_id("引物二聚体或短片段非特异扩增"))

    def test_confirmed_hints_skip_model_and_preserve_typed_control_details(self):
        with patch.object(core, "extract_text_clues_with_fallback", side_effect=AssertionError("不应调用自动抽取")):
            results, _, _, _, debug = core.diagnose("阴性对照有带", 1, 60, 30, "是", "是",
                confirmed_text_hints=[], negative_control_detail="小片段带", experiment_parameters={"negative_control_band": "是"})
        self.assertEqual(debug["normalized_case"]["negative_control"], "小片段带")
        self.assertEqual(results[0]["原因"], "引物二聚体或短片段非特异扩增")

    def test_mass_is_calculated_without_inventing_a_template_threshold(self):
        self.assertEqual(template_mass_ng({"template_amount": 2, "template_concentration": 5}), 10)
        self.assertIsNone(template_mass_ng({"template_amount": 2}))
        self.assertTrue(validate_experiment_parameters({"template_amount": 20, "reaction_volume": 10}))
        self.assertTrue(validate_experiment_parameters({"template_amount": float("nan")}))
        self.assertEqual(validate_experiment_parameters({"template_amount": None}), [])

    def test_structured_recommended_temperature_is_connected_to_diagnosis(self):
        _, _, _, _, debug = core.diagnose("多条带或非特异扩增", 1, 60, 30, "是", "否",
            experiment_parameters={"recommended_temp": 65}, confirmed_text_hints=[])
        self.assertEqual(debug["normalized_case"]["annealing_temp_condition"], "偏低")

    def test_optional_image_does_not_lower_support(self):
        results = [{"原因": "污染", "总分": 100}, {"原因": "另一个原因", "总分": 60}]
        detail = {"证据链": ["泳道位置", "对照", "操作记录"]}
        context = core.build_diagnosis_context(positive_control_normal="是", negative_control_band="是", has_image=False)
        self.assertEqual(core.compute_confidence_level(results, detail, context),
                         core.compute_confidence_level(results, detail, {**context, "是否上传图片": True}))

    def test_operation_entry_is_kept_when_all_observation_questions_are_needed(self):
        with patch("followup_agent._model_client", side_effect=AssertionError("本地模式不能调用模型")):
            questions, _ = plan_followup_questions({"abnormality": "条带大小不对", "positive_control_normal": "否", "negative_control_band": "是", "local_mode": True})
        self.assertEqual([q["id"] for q in questions], ["positive_control", "negative_control", "sample_band", "operation"])


class PersistenceRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "cases.db")
        self.patch = patch.object(core, "DB_PATH", self.db)
        self.patch.start()
        core.init_database()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def create_record(self, with_snapshot=True):
        return core.save_diagnosis_record("无条带", 1, 60, 30, "是", "否", "", "1. 模板量不足 (总分:80); ",
            student_access_code="secret", student_initial_hypothesis="模板量不足，因为样本无带",
            initial_results=[{"原因": "模板量不足", "总分": 80}] if with_snapshot else None,
            raw_case={"data_origin": "模拟演示", "class_name": "模拟班"})

    def test_valid_image_is_saved_and_corrupt_file_is_rejected(self):
        class Upload:
            name = "模拟测试.png"
            def __init__(self, data):
                self.data = data
            def getbuffer(self):
                return self.data
        buffer = BytesIO()
        Image.new("RGB", (20, 20), "white").save(buffer, format="PNG")
        with patch.object(core, "UPLOAD_DIR", str(Path(self.temp.name) / "uploads")):
            saved, error = core.save_uploaded_image(Upload(buffer.getvalue()))
            self.assertIsNone(error)
            self.assertEqual(Path(saved).read_bytes(), buffer.getvalue())
            self.assertIsNotNone(core.save_uploaded_image(Upload(b"not an image"))[1])
            with patch("builtins.open", side_effect=PermissionError("测试保存失败")):
                self.assertIsNotNone(core.save_uploaded_image(Upload(buffer.getvalue()))[1])

    def test_legacy_result_does_not_recompute_when_rules_change(self):
        record_id = self.create_record(False)
        with patch.object(core, "evaluate_rules_v2", side_effect=AssertionError("历史查看不能重算")):
            self.assertEqual(core.load_recent_records()[0]["Top1 原因"], "模板量不足")
            self.assertIn("Top1 原因：模板量不足", core.build_case_review_report({"record_id": record_id}))

    def test_twenty_simultaneous_writers_preserve_all_cases(self):
        with ThreadPoolExecutor(max_workers=20) as pool:
            ids = list(pool.map(lambda _: self.create_record(), range(20)))
        self.assertEqual(len(set(ids)), 20)
        self.assertEqual(len(core.load_recent_records(limit=30)), 20)

    def test_report_includes_provenance_plan_and_feedback_version(self):
        record_id = self.create_record()
        core.save_teacher_confirmation(record_id, "模板量不足", "依据原始记录", "原始记录支持")
        values = {name: "具体实验记录" for name in ["hypothesis", "variable", "controls", "expected_result", "interpretation"]}
        self.assertTrue(core.save_verification_plan(record_id, "secret", values))
        report = core.build_case_review_report({"record_id": record_id})
        for phrase in ["记录来源：模拟演示", "规则版本：", "结论证据等级：原始记录支持", "当前反馈版本：1", "下一步验证方案（计划记录，尚未复测）"]:
            self.assertIn(phrase, report)

    def test_review_history_and_revision_are_versioned(self):
        record_id = self.create_record()
        self.assertTrue(core.save_teacher_confirmation(record_id, "模板量不足", "原始模板记录支持", "原始记录支持"))
        self.assertTrue(core.save_student_revision(record_id, "secret", "模板量不足", "引用原始模板记录"))
        self.assertFalse(core.save_student_revision(record_id, "secret", "污染", "重复修订"))
        self.assertTrue(core.save_teacher_confirmation(record_id, "污染", "新复测证据支持污染", "复测验证", expected_version=1))
        self.assertFalse(core.save_teacher_confirmation(record_id, "模板量不足", "旧页面写入", expected_version=1))
        record = core.load_record_by_id(record_id)
        metrics, rows = learning_progress([record])
        self.assertEqual(metrics["学生修订"]["count"], 0)
        self.assertTrue(rows[0]["需重新修订"])
        self.assertTrue(core.save_student_revision(record_id, "secret", "污染", "根据新增复测结果修订"))
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM teacher_review_history").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM student_revision_history").fetchone()[0], 2)

    def test_rubric_update_does_not_force_another_student_revision(self):
        record_id = self.create_record()
        core.save_teacher_confirmation(record_id, "模板量不足", "备注")
        core.save_student_revision(record_id, "secret", "模板量不足", "证据")
        self.assertTrue(core.save_teacher_confirmation(record_id, "模板量不足", "备注", rubric={"revised": {"证据引用": 2}}, expected_version=1))
        self.assertEqual(core.load_record_by_id(record_id)["teacher_review_version"], 1)

    def test_reassessment_preserves_original_snapshot_and_locks_after_review(self):
        record_id = self.create_record()
        before = core.load_record_by_id(record_id)["diagnosis_snapshot_json"]
        data = {"initial_results": [{"原因": "错误覆盖"}], "final_results": [{"原因": "污染", "总分": 100}]}
        self.assertTrue(core.save_followup_reassessment(record_id, "1. 污染 (总分:100)", "是", "是", data))
        record = core.load_record_by_id(record_id)
        self.assertEqual(record["diagnosis_snapshot_json"], before)
        self.assertEqual(json.loads(record["followup_json"])["initial_results"][0]["原因"], "模板量不足")
        core.save_teacher_confirmation(record_id, "污染", "备注")
        self.assertFalse(core.save_followup_reassessment(record_id, "错误更新", "否", "否", data))

    def test_plan_requires_private_code_and_all_fields(self):
        record_id = self.create_record()
        plan = {"hypothesis": "模板量不足", "variable": "只改变输入质量", "controls": "阳性、阴性", "expected_result": "条带改善", "interpretation": "若不改善则检查其他原因"}
        self.assertFalse(core.save_verification_plan(record_id, "wrong", plan))
        self.assertFalse(core.save_verification_plan(record_id, "secret", {"hypothesis": "模板量不足"}))
        self.assertTrue(core.save_verification_plan(record_id, "secret", plan))
        self.assertEqual(json.loads(core.load_record_by_id(record_id)["verification_plan_json"])["kind"], "计划，尚未复测")

    def test_classroom_cleanup_is_blocked(self):
        record_id = self.create_record()
        with patch.dict(os.environ, {"PCR_DIAGNOSIS_DEMO_MODE": "0"}):
            self.assertFalse(core.clear_history_records()[0])
        self.assertIsNotNone(core.load_record_by_id(record_id))


if __name__ == "__main__":
    unittest.main()
