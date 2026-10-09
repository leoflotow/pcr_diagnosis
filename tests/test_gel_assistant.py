import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
from io import BytesIO
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import ai_config
import case_storage
import core
import followup_agent
import gel_image_assistant as gel


def observations(count=1):
    return {"quality": "可辨", "quality_issues": [], "lanes": [
        {"lane_id": 1, "band_count": count, "pattern": "单条" if count == 1 else "无法确认",
         "position": "中部", "brightness": "较弱"}]}


class ImageFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.image = Path(self.temp.name) / "gel.png"
        Image.new("RGB", (200, 120), "black").save(self.image)
        self.mapping = [{"lane_id": 1, "role": "身份未确认"}]
        self.prepared = gel.prepare_image(self.image, self.mapping)

    def tearDown(self):
        self.temp.cleanup()

class GelAssistantTests(ImageFixture, unittest.TestCase):
    def test_model_and_endpoint_cannot_be_overridden_by_old_or_new_environment(self):
        with patch.dict(os.environ, {"BIGMODEL_MODEL": "glm-5", "BIGMODEL_BASE_URL": "https://other.invalid",
                                     "DEEPSEEK_MODEL": "other", "DEEPSEEK_BASE_URL": "https://other.invalid"}):
            self.assertEqual(ai_config.request_options()["model"], "deepseek-flash")
            self.assertEqual(ai_config.BASE_URL, "https://api.deepseek.com")
            self.assertEqual(core.BIGMODEL_MODEL, "deepseek-flash")
            self.assertEqual(followup_agent.MODEL_BASE_URL, ai_config.BASE_URL)

    def test_config_allows_secrets_and_empty_environment_explicitly_disables_calls(self):
        with patch.dict(os.environ, {"PCR_DIAGNOSIS_DEMO_MODE": "0", "BIO_CONFIG_DISABLED": "0", "BIO_WEB_MODE": "0"}), patch.object(core.st, "secrets", {"DEEPSEEK_API_KEY": "fake-test"}):
            with patch.dict(os.environ, clear=False):
                os.environ.pop("DEEPSEEK_API_KEY", None)
                self.assertEqual(ai_config.api_key(), "fake-test")
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
                self.assertEqual(ai_config.api_key(), "")
        with patch.dict(os.environ, {"PCR_DIAGNOSIS_DEMO_MODE": "1", "DEEPSEEK_API_KEY": "fake-test"}):
            self.assertEqual(ai_config.api_key(), "")

    def test_image_settings_and_mapping_change_fingerprint_without_changing_original(self):
        before = hashlib.sha256(self.image.read_bytes()).hexdigest()
        cropped = gel.prepare_image(self.image, self.mapping, dict(gel.DEFAULT_SETTINGS, right=50))
        renamed = gel.prepare_image(self.image, [{"lane_id": 1, "role": "阴性对照"}])
        self.assertNotEqual(cropped["context_key"], self.prepared["context_key"])
        self.assertNotEqual(renamed["context_key"], self.prepared["context_key"])
        self.assertEqual(before, hashlib.sha256(self.image.read_bytes()).hexdigest())
        self.assertEqual(cropped["image_sha"], before)

    def test_corrupt_image_and_invalid_crop_are_rejected_before_request(self):
        self.image.write_bytes(b"invalid")
        with self.assertRaises(ValueError):
            gel.prepare_image(self.image, self.mapping)
        with self.assertRaises(ValueError):
            gel.normalize_settings(dict(gel.DEFAULT_SETTINGS, left=100))

    def test_request_copy_removes_exif_metadata_and_preserves_original_file(self):
        path = Path(self.temp.name) / "tagged.jpg"
        image = Image.new("RGB", (200, 120), "black")
        exif = Image.Exif()
        exif[315] = "private-identity-tag"
        image.save(path, exif=exif)
        original = path.read_bytes()
        prepared = gel.prepare_image(path, self.mapping)
        with Image.open(BytesIO(prepared["image_bytes"])) as sent:
            self.assertEqual(dict(sent.getexif()), {})
            self.assertNotIn("exif", sent.info)
        self.assertEqual(path.read_bytes(), original)

    def test_diagnosis_confidence_extra_fields_and_wrong_lanes_are_rejected(self):
        for bad in [dict(observations(), cause="污染"), dict(observations(), confidence=0.99)]:
            with self.assertRaises(ValueError):
                gel.validate_observations(bad, self.mapping)
        for field, value in [("bp", 500), ("band_count", True), ("lane_id", 2), ("band_count", 5)]:
            bad = copy.deepcopy(observations())
            bad["lanes"][0][field] = value
            with self.assertRaises(ValueError):
                gel.validate_observations(bad, self.mapping)

    def test_unknown_is_not_converted_to_zero_and_unreadable_image_must_abstain(self):
        data = observations(None)
        self.assertIsNone(gel.validate_observations(data, self.mapping)["lanes"][0]["band_count"])
        data["quality"] = "无法判读"
        with self.assertRaises(ValueError):
            gel.validate_observations(data, self.mapping)
        data["lanes"][0].update(position="无法确认", brightness="无法确认")
        self.assertIsNone(gel.validate_observations(data, self.mapping)["lanes"][0]["band_count"])

    def test_request_sends_only_image_and_anonymous_mapping_and_disables_thinking(self):
        content = json.dumps(observations(), ensure_ascii=False)
        response = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))],
                                   model="deepseek-flash", usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20))
        with patch.object(ai_config, "api_key", return_value="fake-test"), patch.object(gel, "OpenAI") as client:
            client.return_value.chat.completions.create.return_value = response
            result = gel.request_observation(self.prepared)
            request = client.return_value.chat.completions.create.call_args.kwargs
            self.assertEqual(result["status"], "success")
            self.assertEqual(request["model"], "deepseek-flash")
            self.assertEqual(request["extra_body"]["thinking"]["type"], "disabled")
            self.assertEqual(client.call_args.kwargs["base_url"], ai_config.BASE_URL)
            self.assertEqual(client.call_args.kwargs["max_retries"], 0)
            self.assertTrue(request["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
            self.assertNotIn("student_access", json.dumps(request))

    def test_unconfigured_failure_and_invalid_json_do_not_return_observations_or_leak_exception(self):
        with patch.object(ai_config, "api_key", return_value=""), patch.object(gel, "OpenAI") as client:
            result = gel.request_observation(self.prepared)
            client.assert_not_called()
            self.assertEqual(result["status"], "unconfigured")
        with patch.object(ai_config, "api_key", return_value="fake-test"), patch.object(gel, "OpenAI") as client:
            client.return_value.chat.completions.create.side_effect = RuntimeError("sensitive-key-image")
            result = gel.request_observation(self.prepared)
            self.assertNotIn("observations", result)
            self.assertNotIn("sensitive-key-image", json.dumps(result))
            client.return_value.chat.completions.create.side_effect = None
            client.return_value.chat.completions.create.return_value = SimpleNamespace(choices=[
                SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{"cause":"污染"}'))])
            self.assertEqual(gel.request_observation(self.prepared)["status"], "failed")


class GelPersistenceTests(ImageFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = str(Path(self.temp.name) / "cases.db")
        self.db_patch = patch.object(core, "DB_PATH", self.db)
        self.db_patch.start()
        core.init_database()
        self.code = "private-query-code"
        results, *_ = core.diagnose("无条带", 1, 60, 30, "是", "否", confirmed_text_hints=[])
        self.record_id = core.save_diagnosis_record("无条带", 1, 60, 30, "是", "否", "", core.format_diagnosis_result_text(results),
            gel_image_path=str(self.image), student_access_code=self.code, initial_results=results,
            raw_case={"data_origin": "真实课堂"})
        self.response = {"status": "success", "observations": observations(),
                         "raw_response": json.dumps(observations()), "model_returned": "deepseek-flash", "usage": {}}

    def tearDown(self):
        self.db_patch.stop()
        super().tearDown()

    def save_run(self):
        return case_storage.save_gel_run(self.db, self.record_id, self.code, self.prepared, self.response)

    def entries(self, state="未核对"):
        return [{**self.response["observations"]["lanes"][0], "state": state, "note": ""}]

    def test_student_authorization_and_raw_response_whitelist(self):
        with self.assertRaises(ValueError):
            case_storage.save_gel_run(self.db, self.record_id, "wrong", self.prepared, self.response)
        self.assertEqual(case_storage.load_gel_history(self.db, self.record_id, "wrong")["runs"], [])
        with self.assertRaises(ValueError):
            case_storage.save_gel_run(self.db, self.record_id, self.code, self.prepared,
                dict(self.response, raw_response='{"cause":"污染"}'))

    def test_ai_and_both_human_reviews_leave_diagnosis_record_completely_unchanged(self):
        original = core.load_record_by_id(self.record_id)
        run_id = self.save_run()
        check_id = case_storage.save_gel_check(self.db, self.record_id, run_id, self.prepared["context_key"],
            self.entries("与原图一致"), "student", code=self.code)
        case_storage.save_gel_check(self.db, self.record_id, run_id, self.prepared["context_key"],
            self.entries("无法确认"), "teacher", teacher_authorized=True, source_student_check_id=check_id)
        self.assertEqual(core.load_record_by_id(self.record_id), original)
        history = case_storage.load_gel_history(self.db, self.record_id, self.code)
        self.assertEqual(len(history["checks"]), 2)
        self.assertIsNone(history["checks"][0]["entries"][0]["band_count"])
        with patch.object(gel, "request_observation", side_effect=AssertionError("导出不能请求模型")):
            report = core.build_case_review_report({"record_id": self.record_id})
        self.assertIn("AI 原始候选", report)
        self.assertIn("学生核对", report)
        self.assertIn("教师图像复核", report)

    def test_correction_requires_explicit_state_and_original_candidate_is_preserved(self):
        run_id = self.save_run()
        corrected = self.entries()
        corrected[0].update(band_count=2, pattern="多条")
        with self.assertRaises(ValueError):
            case_storage.save_gel_check(self.db,self.record_id,run_id,self.prepared["context_key"],corrected,"student",code=self.code)
        corrected[0]["state"] = "已修正"
        case_storage.save_gel_check(self.db,self.record_id,run_id,self.prepared["context_key"],corrected,"student",code=self.code)
        history = case_storage.load_gel_history(self.db,self.record_id,self.code)
        self.assertEqual(history["runs"][0]["observations"]["lanes"][0]["band_count"], 1)
        self.assertEqual(history["checks"][0]["entries"][0]["band_count"], 2)

    def test_new_run_and_changed_image_make_old_check_read_only(self):
        old_id = self.save_run()
        self.save_run()
        with self.assertRaises(ValueError):
            case_storage.save_gel_check(self.db,self.record_id,old_id,self.prepared["context_key"],self.entries(),"student",code=self.code)
        history = case_storage.load_gel_history(self.db,self.record_id,self.code)
        new_id = history["runs"][0]["id"]
        Image.new("RGB", (200,120), "white").save(self.image)
        with self.assertRaises(ValueError):
            case_storage.save_gel_check(self.db,self.record_id,new_id,self.prepared["context_key"],self.entries(),"student",code=self.code)
        self.assertEqual(len(case_storage.load_gel_history(self.db,self.record_id,self.code)["runs"]), 2)

    def test_teacher_review_rejects_concurrent_student_update_and_requires_teacher_access(self):
        run_id = self.save_run()
        check_id = case_storage.save_gel_check(self.db,self.record_id,run_id,self.prepared["context_key"],self.entries(),"student",code=self.code)
        with self.assertRaises(ValueError):
            case_storage.save_gel_check(self.db,self.record_id,run_id,self.prepared["context_key"],self.entries(),"teacher")
        case_storage.save_gel_check(self.db,self.record_id,run_id,self.prepared["context_key"],self.entries(),"student",code=self.code)
        with self.assertRaises(ValueError):
            case_storage.save_gel_check(self.db,self.record_id,run_id,self.prepared["context_key"],self.entries(),"teacher",
                teacher_authorized=True,source_student_check_id=check_id)

    def test_migration_backs_up_existing_database_before_adding_image_tables(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DROP TABLE gel_observation_checks")
            conn.execute("DROP TABLE gel_observation_runs")
        core.init_database()
        backup = self.db + ".before-gel-observation.bak"
        self.assertTrue(Path(backup).is_file())
        with closing(sqlite3.connect(backup)) as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='gel_observation_runs'").fetchone())
        self.assertEqual(core.load_record_by_id(self.record_id)["student_access_hash"], hashlib.sha256(self.code.encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
