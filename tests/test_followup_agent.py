import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import core
from diagnosis_normalization import build_normalized_case
from followup_agent import apply_followup_choices, interpret_operation_text, plan_followup_questions


class FollowupAgentTests(unittest.TestCase):
    def setUp(self):
        self.case = {
            "abnormality": "无条带",
            "template_amount": 1.0,
            "annealing_temp": 60.0,
            "cycles": 30,
            "positive_control_normal": "是",
            "negative_control_band": "否",
            "description": "",
        }

    def test_questions_target_controls_band_position_and_operation(self):
        case = dict(self.case, abnormality="阴性对照有带", negative_control_band="否")
        with patch("followup_agent._model_client", return_value=None):
            questions, source = plan_followup_questions(case)
        self.assertEqual([item["id"] for item in questions], ["negative_control", "operation"])
        self.assertEqual(source, "本地追问规划")

        case = dict(self.case, abnormality="多条带或非特异扩增")
        with patch("followup_agent._model_client", return_value=None):
            questions, _ = plan_followup_questions(case)
        self.assertEqual([item["id"] for item in questions], ["sample_band", "operation"])

    def test_explicit_evidence_changes_normalized_rule_inputs(self):
        updated = apply_followup_choices(self.case, {
            "positive_control": "完全无带",
            "negative_control": "明显小于目标条带",
        })
        self.assertEqual(updated["positive_control_normal"], "否")
        self.assertEqual(updated["positive_control_detail"], "无带")
        self.assertEqual(updated["negative_control_band"], "是")
        self.assertEqual(
            build_normalized_case({**updated, "negative_control_band": updated["negative_control_detail"]})["negative_control"],
            "小片段带",
        )

    def test_model_can_only_rephrase_questions_and_propose_allowed_hints(self):
        class FakeClient:
            def __init__(self, content):
                message = SimpleNamespace(content=content)
                self.chat = SimpleNamespace(completions=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=message)]),
                ))

        wording = '{"positive_control":"请观察阳性对照泳道，预期条带是否清晰？","operation":"请描述已确认的操作异常？"}'
        with patch("followup_agent._model_client", return_value=FakeClient(wording)):
            questions, source = plan_followup_questions(self.case)
        self.assertEqual(source, "AI整理问法")
        self.assertIn("阳性对照", questions[0]["text"])
        self.assertEqual(questions[-1]["kind"], "text")

        with patch("followup_agent._model_client", return_value=FakeClient('["漏加试剂","不存在的标签"]')):
            hints, source = interpret_operation_text("确认漏加聚合酶")
        self.assertEqual(hints, ["漏加试剂"])
        self.assertEqual(source, "AI候选线索")

    def test_confirmed_hint_and_control_reorder_existing_rules(self):
        with patch("core.extract_text_clues_with_fallback", return_value=([], "本地规则抽取", {})):
            initial, *_ = core.diagnose(**self.case)
            updated = apply_followup_choices(self.case, {"positive_control": "完全无带"})
            final, *_ = core.diagnose(**updated, extra_text_hints=["漏加试剂"])
        self.assertTrue(initial)
        self.assertTrue(final)
        self.assertNotEqual(initial[0]["原因"], final[0]["原因"])

    def test_reassessment_is_saved_on_same_record_and_teacher_confirmation_locks_it(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(core, "DB_PATH", os.path.join(temp_dir, "cases.db")):
            core.init_database()
            record_id = core.save_diagnosis_record(
                "无条带", 1.0, 60.0, 30, "是", "否", "", "初判", None,
            )
            followup = {
                "initial_results": [{"原因": "模板量不足", "总分": 80}],
                "final_results": [{"原因": "PCR体系漏加或关键试剂失活", "总分": 130}],
                "questions": [{"id": "operation", "text": "是否漏加试剂？"}],
                "answers": {"operation": "确认漏加聚合酶"},
                "extra_hints": ["漏加试剂"],
            }
            self.assertTrue(core.save_followup_reassessment(record_id, "再判断", "否", "否", followup))
            saved = core.load_record_by_id(record_id)
            self.assertEqual(saved["diagnosis_result"], "再判断")
            self.assertEqual(core.parse_followup_data(saved["followup_json"])["extra_hints"], ["漏加试剂"])
            self.assertEqual(len(core.load_recent_records()[0]["followup_data"]["questions"]), 1)

            core.save_teacher_confirmation(record_id, "PCR体系漏加或关键试剂失活", "已复核")
            self.assertFalse(core.save_followup_reassessment(record_id, "再次修改", "是", "否", followup))


if __name__ == "__main__":
    unittest.main()
