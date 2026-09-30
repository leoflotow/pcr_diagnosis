import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

import core


class LearningLoopTests(unittest.TestCase):
    def test_existing_database_migrates_and_student_can_complete_one_revision(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(core, "DB_PATH", os.path.join(temp_dir, "cases.db")):
            with closing(sqlite3.connect(core.DB_PATH)) as conn:
                conn.execute("""CREATE TABLE diagnosis_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    abnormality TEXT, template_amount REAL, annealing_temp REAL, cycles INTEGER,
                    positive_control_normal TEXT, negative_control_band TEXT, description TEXT,
                    diagnosis_result TEXT, diagnosis_time TEXT, gel_image_path TEXT,
                    teacher_final_cause TEXT, teacher_note TEXT, teacher_confirm_time TEXT
                )""")
            core.init_database()

            access_code = "private-case-code"
            record_id = core.save_diagnosis_record(
                "无条带", 1.0, 60.0, 30, "是", "否", "样本无条带", "1. 模板量不足 (总分:80)",
                student_initial_hypothesis="我认为模板量不足，因为样本无带",
                student_access_code=access_code,
                initial_results=[{"原因": "模板量不足", "总分": 80}],
            )
            self.assertIsNone(core.load_student_record("wrong-code"))
            record = core.load_student_record(access_code)
            self.assertEqual(record["id"], record_id)
            self.assertNotIn(access_code, str(record))
            self.assertEqual(record["student_initial_hypothesis"], "我认为模板量不足，因为样本无带")
            self.assertEqual(core.load_recent_records()[0]["Top1 原因"], "模板量不足")
            self.assertFalse(core.save_student_revision(record_id, access_code, "模板量不足", "尚未复核"))

            core.save_teacher_confirmation(record_id, "PCR体系漏加", "复核操作记录后确认漏加")
            self.assertFalse(core.save_student_revision(record_id, "wrong-code", "PCR体系漏加", "教师反馈"))
            self.assertFalse(core.save_student_revision(record_id, access_code, "PCR体系漏加", ""))
            self.assertTrue(core.save_student_revision(record_id, access_code, "PCR体系漏加", "教师指出漏加聚合酶"))
            self.assertFalse(core.save_student_revision(record_id, access_code, "其他原因", "再次修改"))

            saved = core.load_student_record(access_code)
            self.assertEqual(saved["student_revised_cause"], "PCR体系漏加")
            self.assertEqual(core.load_recent_records()[0]["学生修订依据"], "教师指出漏加聚合酶")
            report = core.build_case_review_report({"record_id": record_id})
            self.assertIn("学生诊断前判断：我认为模板量不足", report)
            self.assertIn("教师反馈后修订原因：PCR体系漏加", report)
            self.assertIn("修订依据：教师指出漏加聚合酶", report)


if __name__ == "__main__":
    unittest.main()
