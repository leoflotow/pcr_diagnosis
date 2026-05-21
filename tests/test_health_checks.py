import os
import importlib.util
import shutil
import tempfile
import unittest
from unittest.mock import patch

import core


class HealthCheckRegressionTests(unittest.TestCase):
    def test_dev_page_exposes_rule_editor_helpers(self):
        page_path = os.path.join(os.getcwd(), "pages", "3_开发调试端.py")
        spec = importlib.util.spec_from_file_location("dev_page_for_test", page_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertTrue(callable(module.append_rule_to_csv))
        self.assertTrue(callable(module.check_rule_duplicate))
        self.assertTrue(callable(module.check_rule_conflict))

    def test_system_checks_read_current_rules_encoding(self):
        checks = core.run_system_self_check()
        self.assertEqual(checks["rules_csv"]["level"], "success")

        rules_check = core.run_rules_library_check()
        self.assertTrue(rules_check["ok"], rules_check)
        self.assertEqual(rules_check["warnings"], [])

    def test_bigmodel_uses_default_base_url_when_env_is_missing(self):
        original_key = os.environ.get("BIGMODEL_API_KEY")
        original_base_url = os.environ.get("BIGMODEL_BASE_URL")
        try:
            os.environ["BIGMODEL_API_KEY"] = "fake-key-for-test"
            os.environ.pop("BIGMODEL_BASE_URL", None)

            with patch.object(core, "extract_text_clues_with_bigmodel", return_value=(["污染"], {})) as mocked:
                clues, source, debug = core.extract_text_clues_with_fallback("阴性对照有带，怀疑污染")

            self.assertEqual(clues, ["污染"])
            self.assertEqual(source, "AI（BigModel）抽取")
            mocked.assert_called_once()
            self.assertEqual(mocked.call_args.args[2], core.BIGMODEL_DEFAULT_BASE_URL)
            self.assertEqual(debug["base_url"], core.BIGMODEL_DEFAULT_BASE_URL)
        finally:
            if original_key is None:
                os.environ.pop("BIGMODEL_API_KEY", None)
            else:
                os.environ["BIGMODEL_API_KEY"] = original_key

            if original_base_url is None:
                os.environ.pop("BIGMODEL_BASE_URL", None)
            else:
                os.environ["BIGMODEL_BASE_URL"] = original_base_url

    def test_append_rule_preserves_rules_v2_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_rules_path = os.path.join(tmpdir, "rules.csv")
            shutil.copyfile(core.RULES_PATH, temp_rules_path)

            before_df = core.read_csv_with_fallback(temp_rules_path)
            new_rule = {
                "rule_id": "R_TEST",
                "abnormality": "无条带",
                "band_pattern": "no_band",
                "cause": "测试规则",
                "priority": 1,
                "positive_control": "any",
                "negative_control": "any",
                "template_condition": "any",
                "annealing_temp_condition": "any",
                "text_hint": "any",
                "required_fields": "abnormality",
                "base_score": 1,
                "evidence_text": "测试证据",
                "suggestion": "测试建议",
                "enabled": 1,
            }

            success, message = core.append_rule_to_csv(new_rule, rules_path=temp_rules_path)

            self.assertTrue(success, message)
            after_df = core.read_csv_with_fallback(temp_rules_path)
            self.assertEqual(list(after_df.columns), list(before_df.columns))
            self.assertEqual(len(after_df), len(before_df) + 1)


if __name__ == "__main__":
    unittest.main()
