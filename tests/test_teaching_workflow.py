"""六项教学升级的权限、独立性、版本与不确定性检验，全部使用临时库。"""
from contextlib import closing
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch,MagicMock
import json
import sqlite3
import tempfile
import unittest
from PIL import Image
import core
import teaching_workflow as w
from gel_image_assistant import prepare_image


class TeachingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=str(Path(self.temp.name)/"test.db")
        self.patch=patch.object(core,"DB_PATH",self.db);self.patch.start();core.init_database()
        self.code="student-private-code"
        self.rid=self.record()

    def tearDown(self):
        self.patch.stop();self.temp.cleanup()

    def record(self,task="",origin="真实课堂"):
        return core.save_diagnosis_record("无条带",1,60,30,"未观察","未观察","原始记录","1. 系统候选 (总分:80);",
            student_access_code=self.code,student_initial_hypothesis="初判依据",initial_results=[{"原因":"系统候选","总分":80}],
            raw_case={"data_origin":origin,"teaching_task_code":task,"group_code":"G01"})

    def raw(self,rid=None):
        return core.load_record_by_id(rid or self.rid)

    def task(self):
        return w.create_task(self.db,"课堂任务","按实际记录","新案例：阳性正常、样本无带，应补什么证据？",teacher_authorized=True)

    def test_task_permission_and_deadline(self):
        with self.assertRaises(ValueError): w.create_task(self.db,"a","b","")
        with self.assertRaises(ValueError): w.create_task(self.db,"a","b","","2000-01-01",teacher_authorized=True)
        code=self.task();self.assertEqual(w.task_status(w.task_by_code(self.db,code.lower())),"开放")
        w.set_task_active(self.db,w.task_by_code(self.db,code)["id"],False,True)
        with self.assertRaises(ValueError):self.record(code)

    def test_changed_independent_judgment_requires_reason(self):
        w.save_independent_review(self.db,self.rid,"模板不足","待核对浓度","经验复核",True)
        self.assertFalse(core.save_teacher_confirmation(self.rid,"污染",""))
        self.assertTrue(core.save_teacher_confirmation(self.rid,"污染","新增对照记录支持污染"))
        self.assertEqual(w.independent_record(self.db,self.rid,True)["review"]["cause"],"模板不足")

    def test_task_link_is_atomic(self):
        with w.connection(self.db) as c: before=c.execute("SELECT COUNT(*) FROM diagnosis_records").fetchone()[0]
        with self.assertRaises(ValueError):self.record("NO-SUCH-TASK")
        with w.connection(self.db) as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM diagnosis_records").fetchone()[0],before)

    def test_transfer_private_and_once(self):
        code=self.task();rid=self.record(code)
        with self.assertRaises(ValueError):w.save_transfer(self.db,rid,"wrong","a","b")
        w.save_transfer(self.db,rid,self.code,"判断","引用具体事实",3.5)
        with self.assertRaises(ValueError):w.save_transfer(self.db,rid,self.code,"覆盖","b")
        result=w.record_task(self.db,rid,self.code)
        self.assertEqual(result["submission"]["minutes"],3.5)
        with self.assertRaises(ValueError):w.record_task(self.db,rid,"wrong")

    def test_transfer_unknown_minutes_and_internal_exclusion(self):
        code=self.task();rid=self.record(code)
        with self.assertRaises(ValueError):w.save_transfer(self.db,rid,self.code,"a","b",float("nan"))
        w.save_transfer(self.db,rid,self.code,"a","b")
        internal=self.record(origin="模拟演示")
        with self.assertRaises(ValueError):w.save_transfer(self.db,internal,self.code,"a","b")

    def test_evaluations_missing_and_paired_export(self):
        code=self.task();rid=self.record(code);task=w.task_by_code(self.db,code)
        before=self.raw(rid);rubric={d:None for d in w.DIMENSIONS};rubric["证据引用"]=1
        with self.assertRaises(ValueError):w.save_learning_evaluation(self.db,rid,"transfer",rubric,teacher_authorized=True)
        w.save_learning_evaluation(self.db,rid,"initial",rubric,teacher_authorized=True)
        self.assertEqual(before,self.raw(rid))
        rows=w.task_export(self.db,task["id"],True);self.assertEqual(rows[0]["初判·证据引用"],1);self.assertIsNone(rows[0]["新案例·证据引用"])
        with self.assertRaises(ValueError):w.save_learning_evaluation(self.db,rid,"initial",{d:True for d in w.DIMENSIONS},teacher_authorized=True)

    def test_independent_never_returns_candidates_before_submission(self):
        result=w.independent_record(self.db,self.rid,True)
        self.assertTrue(result["eligible"])
        self.assertNotIn("系统候选",json.dumps(result,ensure_ascii=False))
        before=self.raw()
        w.save_independent_review(self.db,self.rid,"原因待核实","原图待补","原因待核实",True)
        self.assertEqual(before,self.raw())
        self.assertIn("系统候选",w.independent_record(self.db,self.rid,True)["review"]["snapshot_json"])
        with self.assertRaises(ValueError):w.save_independent_review(self.db,self.rid,"a","b","经验复核",True)

    def test_prior_exposure_or_review_prevents_blind_claim(self):
        w.mark_exposed(self.db,self.rid,True)
        self.assertFalse(w.independent_record(self.db,self.rid,True)["eligible"])
        with self.assertRaises(ValueError):w.save_independent_review(self.db,self.rid,"a","b","经验复核",True)
        other=self.record();core.save_teacher_confirmation(other,"待核实","记录缺失")
        with self.assertRaises(ValueError):w.save_independent_review(self.db,other,"a","b","经验复核",True)

    def test_scheme_versions_and_task_snapshot(self):
        payload={"template_type":"质粒","reaction_volume":50.0,"template_concentration":None,"cycles":30}
        sid=w.save_scheme(self.db,"PCR",payload,"教师提供",teacher_authorized=True)
        code=w.create_task(self.db,"a","b","",scheme_id=sid,teacher_authorized=True)
        payload["reaction_volume"]=25.0
        w.save_scheme(self.db,"PCR",payload,"更新",1,True)
        frozen=json.loads(w.task_by_code(self.db,code)["scheme_json"])
        self.assertEqual(json.loads(frozen["payload_json"])["reaction_volume"],50.0)
        with self.assertRaises(ValueError):w.save_scheme(self.db,"PCR",payload,"并发旧版本",1,True)
        with self.assertRaises(ValueError):w.save_scheme(self.db,"X",{"template_type":"质粒","reaction_volume":float("nan")},"来源",teacher_authorized=True)

    def retest_payload(self):
        return {"performed_at":"2026-01-01 14:30","changed":"核对配液后重配","kept":"模板和热循环条件一致","controls":"阳性恢复、阴性无带","sample_result":"有带","expected_comparison":"符合预期","conclusion":"支持原假设"}

    def test_retest_requires_actual_plan_and_private_code(self):
        with self.assertRaises(ValueError):w.save_retest(self.db,self.rid,self.code,self.retest_payload())
        core.save_verification_plan(self.rid,self.code,{f:"内容" for f in ("hypothesis","variable","controls","expected_result","interpretation")})
        before=self.raw();rt=w.save_retest(self.db,self.rid,self.code,self.retest_payload());self.assertEqual(before,self.raw())
        w.review_retest(self.db,rt,"仍无法判断","不能只凭有带证明原因",teacher_authorized=True)
        with self.assertRaises(ValueError):w.review_retest(self.db,rt,"支持原假设","覆盖",teacher_authorized=True)
        with self.assertRaises(ValueError):w.load_retests(self.db,self.rid,"wrong")
        self.assertEqual(w.load_retests(self.db,self.rid,self.code)[0]["review"]["conclusion"],"仍无法判断")

    def test_retest_future_rejected(self):
        payload=self.retest_payload();payload["performed_at"]=(datetime.now()+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):w.save_retest(self.db,self.rid,self.code,payload)

    def test_issues_are_grounded_and_internal_excluded(self):
        self.record(origin="模拟演示")
        ctx=w.build_issues(self.db,teacher_authorized=True)
        self.assertEqual(ctx["denominator"],1)
        issues={i["code"]:i for i in ctx["issues"]}
        self.assertEqual(issues["controls"]["case_ids"],[self.rid])
        self.assertNotIn("evidence",issues)
        self.assertNotIn("原始记录",json.dumps(ctx,ensure_ascii=False))

    def test_suggestion_whitelist_and_stale_context(self):
        ctx=w.build_issues(self.db,teacher_authorized=True)
        response={"suggestions":[{"code":i["code"],"action":w.ISSUE_ACTIONS[i["code"]]["actions"][0]} for i in ctx["issues"]],"model":"deepseek-flash","usage":{}}
        before=self.raw();w.save_suggestions(self.db,ctx,response,True);self.assertEqual(before,self.raw())
        self.assertTrue(w.latest_suggestions(self.db,ctx,True))
        bad={**response,"suggestions":[{"code":"invented","action":"能力不足"}]}
        with self.assertRaises(ValueError):w.save_suggestions(self.db,ctx,bad,True)
        self.record()
        with self.assertRaises(ValueError):w.save_suggestions(self.db,ctx,response,True)

    def test_suggestion_request_uses_only_aggregate_and_fixed_api(self):
        ctx=w.build_issues(self.db,teacher_authorized=True)
        client=MagicMock()
        response=MagicMock()
        response.choices[0].finish_reason="stop"
        response.choices[0].message.content=json.dumps({"suggestions":[{"code":i["code"],"action":w.ISSUE_ACTIONS[i["code"]]["actions"][0]} for i in ctx["issues"]]})
        response.model="deepseek-flash";response.usage=None
        client.chat.completions.create.return_value=response
        with patch("ai_config.api_key",return_value="not-a-real-key"),patch("openai.OpenAI",return_value=client) as factory:
            result=w.request_teaching_suggestions(ctx)
            self.assertEqual(result["model"],"deepseek-flash")
            self.assertEqual(factory.call_args.kwargs["base_url"],"https://api.deepseek.com")
            self.assertEqual(factory.call_args.kwargs["timeout"],8)
            self.assertEqual(factory.call_args.kwargs["max_retries"],0)
            options=client.chat.completions.create.call_args.kwargs
            self.assertEqual(options["model"],"deepseek-flash")
            sent=json.dumps(options["messages"],ensure_ascii=False)
            for forbidden in ("原始记录",self.code,"case_ids","group_code"):
                self.assertNotIn(forbidden,sent)
            response.choices[0].message.content='{"suggestions":[{"code":"controls","action":"学生能力不足"}]}'
            with self.assertRaises(ValueError):w.request_teaching_suggestions(ctx)

    def eval_sample(self,count=1,family="F1",split="独立验收集",disputed=None):
        path=Path(self.temp.name)/"gel.png"
        if not path.exists():Image.new("RGB",(50,50),"black").save(path)
        prepared=prepare_image(path,[{"lane_id":1,"role":"样本"}])
        ref={"quality":"可辨","quality_issues":[],"lanes":[{"lane_id":1,"band_count":count,"pattern":"无法确认" if count is None else "单条" if count==1 else "多条","position":"中部","brightness":"较弱"}]}
        sid=w.save_evaluation_sample(self.db,path,prepared,ref,disputed or [],family,split,"弱带",True)
        return sid,prepared,ref

    def eval_run(self,sid,prepared,ref,count):
        observed=json.loads(json.dumps(ref));observed["lanes"][0]["band_count"]=count;observed["lanes"][0]["pattern"]="无法确认" if count is None else "单条" if count==1 else "多条"
        response={"status":"success","observations":observed,"raw_response":json.dumps(observed),"model_returned":"deepseek-flash","usage":{}}
        return w.save_evaluation_run(self.db,sid,prepared,response,True)

    def test_evaluation_split_and_reference_frozen(self):
        sid,prepared,ref=self.eval_sample()
        with self.assertRaises(ValueError):self.eval_sample(family="another",split="校准集")
        self.eval_run(sid,prepared,ref,2)
        with self.assertRaises(ValueError):self.eval_sample()
        self.assertEqual(len(w.evaluation_samples(self.db,True)),1)

    def test_evaluation_unknown_not_zero_and_dispute_exclusion(self):
        sid,prepared,ref=self.eval_sample(count=None);self.eval_run(sid,prepared,ref,None)
        rows=w.evaluation_comparison(w.evaluation_samples(self.db,True)[0],w.evaluation_runs(self.db,sid,True)[0])
        self.assertIsNone(rows[0]["数量少于参考"]);self.assertTrue(rows[0]["参考未知时保留未知"])
        with w.connection(self.db,True) as c:c.execute("UPDATE gel_evaluation_samples SET disputed_json='[1]' WHERE id=?",(sid,))
        rows=w.evaluation_comparison(w.evaluation_samples(self.db,True)[0],w.evaluation_runs(self.db,sid,True)[0])
        self.assertIsNone(rows[0]["参考未知时保留未知"])

    def test_evaluation_quantity_and_manual_mismatch_separate(self):
        sid,prepared,ref=self.eval_sample(count=3);run_id=self.eval_run(sid,prepared,ref,1)
        sample=w.evaluation_samples(self.db,True)[0];run=w.evaluation_runs(self.db,sid,True)[0]
        row=w.evaluation_comparison(sample,run)[0];self.assertEqual(row["数量少于参考"],2);self.assertIsNone(row["泳道错配人工标记"])
        w.save_evaluation_audit(self.db,run_id,[1],"人工确认错配",True)
        row=w.evaluation_comparison(sample,w.evaluation_runs(self.db,sid,True)[0])[0]
        self.assertTrue(row["泳道错配人工标记"]);self.assertFalse(row["数量可比较"])

    def test_changed_evaluation_image_rejected(self):
        sid,prepared,ref=self.eval_sample()
        Image.new("RGB",(50,50),"white").save(Path(self.temp.name)/"gel.png")
        with self.assertRaises(ValueError):w.prepare_evaluation(w.evaluation_samples(self.db,True)[0])
        with self.assertRaises(ValueError):self.eval_run(sid,prepared,ref,1)

    def test_teacher_only_queries_and_new_migration_backup(self):
        for operation in [lambda:w.list_tasks(self.db),lambda:w.evaluation_samples(self.db),lambda:w.independent_record(self.db,self.rid),lambda:w.build_issues(self.db)]:
            with self.assertRaises(ValueError):operation()
        with w.connection(self.db,True) as c:c.execute("DROP TABLE teaching_tasks")
        core.init_database()
        self.assertTrue(Path(self.db+".before-teaching-workflow.bak").exists())
        self.assertEqual(self.raw()["student_initial_hypothesis"],"初判依据")

    def test_real_course_preserves_unknowns_and_per_tube_volume(self):
        data=json.loads(Path("course_presets.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(data["reaction_volume"],50.0);self.assertEqual(data["template_amount"],1.0)
        self.assertIsNone(data["template_concentration"]);self.assertIsNone(data["recommended_temp"]);self.assertIsNone(data["target_size"])
        self.assertEqual(data["cycles"],30)


if __name__=="__main__":unittest.main()
