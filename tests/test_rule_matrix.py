import unittest
from unittest.mock import patch

import core
from diagnosis_normalization import STANDARD_BAND_PATTERNS, STANDARD_TEXT_HINTS, build_normalized_case
from diagnosis_rule_engine_v2 import (
    aggregate_base_rule_hits,
    evaluate_rules_v2,
    load_rule_combos_v2,
    load_rules_v2,
    match_rule_v2,
)


class RuleMatrixTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            "abnormality": "无条带",
            "template_amount": 1.0,
            "annealing_temp": 60,
            "positive_control_normal": "是",
            "negative_control_band": "否",
        }

    def evaluate(self, **changes):
        normalized = build_normalized_case({**self.base, **changes})
        return normalized, evaluate_rules_v2(normalized)

    def test_volume_and_absolute_temperature_do_not_prove_a_cause(self):
        case, result = self.evaluate()
        self.assertEqual(case["template_condition"], "unknown")
        self.assertEqual(case["annealing_temp_condition"], "unknown")
        self.assertIn("需核查", result["top1"])
        self.assertNotIn("模板量不足", result["top1"])

    def test_negative_control_band_position_changes_ranking(self):
        scenarios = [
            ("是", "阴性对照有带（待区分污染与引物二聚体）"),
            ("目标大小相近带", "污染"),
            ("小片段带", "引物二聚体或短片段非特异扩增"),
            ("拖尾或弥散", "阴性对照异常背景待核查"),
        ]
        for band, expected in scenarios:
            with self.subTest(band=band):
                _, result = self.evaluate(abnormality="阴性对照有带", negative_control_band=band)
                self.assertEqual(result["top1"], expected)

    def test_positive_control_failure_requires_specific_evidence(self):
        _, initial = self.evaluate(abnormality="阳性对照无带", positive_control_normal="无带")
        _, confirmed = self.evaluate(
            abnormality="阳性对照无带", positive_control_normal="无带", text_clues=["漏加试剂"]
        )
        self.assertIn("待排查", initial["top1"])
        self.assertEqual(confirmed["top1"], "PCR体系漏加或关键试剂失活")

    def test_specific_evidence_reorders_sample_causes(self):
        scenarios = [
            ({"abnormality": "多条带或非特异扩增", "text_clues": ["退火偏低"]}, "退火温度过低"),
            ({"abnormality": "条带大小不对", "text_clues": ["Marker异常"]}, "Marker判读或凝胶迁移异常"),
            ({"abnormality": "条带拖尾或弥散", "text_clues": ["上样过量"]}, "电泳或上样问题"),
            ({"abnormality": "条带弱", "text_clues": ["模板低"]}, "模板量不足"),
        ]
        for changes, expected in scenarios:
            with self.subTest(changes=changes):
                _, result = self.evaluate(**changes)
                self.assertEqual(result["top1"], expected)

    def test_all_page_symptoms_have_live_rules_and_conflicts_are_flagged(self):
        for abnormality in core.ABNORMALITY_OPTIONS:
            changes = {"abnormality": abnormality}
            if abnormality == "阴性对照有带":
                changes["negative_control_band"] = "是"
            elif abnormality == "阳性对照无带":
                changes["positive_control_normal"] = "否"
            with self.subTest(abnormality=abnormality):
                _, result = self.evaluate(**changes)
                self.assertEqual(result["status"], "ok")
                self.assertIsNotNone(result["top1"])

        _, negative_conflict = self.evaluate(abnormality="阴性对照有带", negative_control_band="否")
        _, positive_conflict = self.evaluate(abnormality="阳性对照无带", positive_control_normal="是")
        self.assertIn("记录矛盾", negative_conflict["top1"])
        self.assertIn("记录矛盾", positive_conflict["top1"])

    def test_uncertain_text_is_not_confirmed_evidence(self):
        self.assertEqual(core.extract_text_clues("怀疑模板量不足；可能污染？"), [])
        self.assertEqual(core.extract_text_clues("可能污染；确认模板浓度低"), ["模板量不足"])
        self.assertEqual(core.extract_text_clues("怀疑污染，确认模板浓度低"), ["模板量不足"])
        self.assertEqual(core.extract_text_clues("没有污染"), [])
        self.assertEqual(core.extract_text_clues("阴性对照有带"), [])

    def test_rules_are_reachable_and_combos_use_known_causes(self):
        rules = load_rules_v2()
        combos = load_rule_combos_v2()
        self.assertEqual(len(rules), 40)
        self.assertEqual(len(combos), 2)
        self.assertEqual(core.run_rules_library_check(), {"ok": True, "issues": [], "warnings": []})
        causes = set(rules["cause"])
        self.assertTrue(set(combos["cause"]).issubset(causes))

        allowed = {
            "abnormality": set(core.ABNORMALITY_OPTIONS) | {"any"},
            "band_pattern": STANDARD_BAND_PATTERNS | {"any"},
            "positive_control": {"正常", "无带", "弱带", "异常待分型", "any"},
            "negative_control": {"无带", "有带待分型", "目标大小相近带", "小片段带", "拖尾或弥散", "any"},
            "template_condition": {"偏低", "偏高", "降解或不纯", "any"},
            "annealing_temp_condition": {"偏低", "偏高", "正常", "any"},
        }
        for _, row in rules.iterrows():
            with self.subTest(rule_id=row["rule_id"]):
                case = {key: ("无条带" if key == "abnormality" else "unknown") for key in allowed}
                for field, values in allowed.items():
                    self.assertIn(row[field], values)
                    if row[field] != "any":
                        case[field] = row[field]
                hints = row["text_hint"].split("|") if row["text_hint"] != "any" else []
                self.assertTrue(set(hints).issubset(set(STANDARD_TEXT_HINTS)))
                case["text_hint"] = hints
                self.assertIsNotNone(match_rule_v2(row.to_dict(), case))

    def test_generic_and_specific_hits_do_not_double_base_score(self):
        hits = [
            {"cause": "同一原因", "base_score": 50, "priority": 40},
            {"cause": "同一原因", "base_score": 75, "priority": 80},
        ]
        self.assertEqual(aggregate_base_rule_hits(hits)["同一原因"]["total_base_score"], 75)

    def test_legacy_fallback_is_conservative(self):
        with patch("core.extract_text_clues_with_fallback", return_value=([], "本地规则抽取", {})):
            results, *_ = core.diagnose("无条带", 1.0, 60.0, 30, "", "")
        self.assertIn("待核查", results[0]["原因"])
        self.assertEqual(results[0]["诊断依据"]["模板量范围"]["加分"], 0)


if __name__ == "__main__":
    unittest.main()
