"""六项教学功能的页面交互回归；只使用临时库和生成图片，不调用外部接口。"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import core
import teaching_workflow as w
from gel_image_assistant import prepare_image
from PIL import Image
from streamlit.testing.v1 import AppTest
from verify_competition_ui import check, labelled


def main():
    with tempfile.TemporaryDirectory() as directory, patch.object(core,"DB_PATH",str(Path(directory)/"ui.db")), patch.dict(os.environ,{"DEEPSEEK_API_KEY":"","PCR_DIAGNOSIS_DEMO_MODE":"0"}):
        core.init_database()
        db=core.DB_PATH
        task=w.create_task(db,"梯度退火课堂任务","核对对照与实际记录","新案例：样本无带、阳性正常，先补充哪些事实？",teacher_authorized=True)
        rid=core.save_diagnosis_record("无条带",1,60,30,"未观察","未观察","样本无带，待核对配液记录","系统候选待核实",
            student_access_code="private",student_initial_hypothesis="先检查配液记录",initial_results=[{"原因":"模板不足","总分":20}],raw_case={"data_origin":"真实课堂","teaching_task_code":task})
        teacher=AppTest.from_file("pages/2_教师端.py",default_timeout=20)
        teacher.session_state["teacher_verified"]=True
        check(teacher.run())
        assert teacher.radio(key="teacher_workspace").value=="独立复核"
        assert not teacher.dataframe
        labelled(teacher.text_input,"教师独立判断（可填原因待核实）").set_value("原因待核实")
        labelled(teacher.text_area,"独立判断的原始依据").set_value("尚未观察对照，证据不足")
        labelled(teacher.checkbox,"我此前未查看该案例的系统建议，也未由其他途径获知候选排序").check()
        check(labelled(teacher.button,"保存独立判断并查看建议").click().run())
        assert teacher.dataframe
        check(teacher.radio(key="teacher_workspace").set_value("课程方案").run())
        check(labelled(teacher.button,"保存课程方案新版本").click().run())
        assert len(w.list_schemes(db))==1
        wizard=check(AppTest.from_file("pages/1_学生端.py",default_timeout=20).run())
        wizard.text_input(key="teaching_join_code").set_value(task)
        check(wizard.button(key="teaching_join").click().run())
        check(wizard.button(key="student_next_step_1").click().run())
        wizard.checkbox(key="student_scheme_confirm").check().run()
        check(wizard.button(key="student_apply_preset").click().run())
        assert wizard.session_state["student_data_storage"]["student_form_reaction_volume"]==50.0
        assert wizard.session_state["student_scheme_snapshot"]["version"]==1
        assert wizard.session_state["teaching_task"]["code"]==task
        check(teacher.radio(key="teacher_workspace").set_value("课堂任务").run())
        labelled(teacher.text_input,"任务名称").set_value("第二次课堂任务")
        labelled(teacher.text_area,"任务说明").set_value("记录实际条件")
        check(labelled(teacher.button,"发布课堂任务").click().run())
        assert len(w.list_tasks(db,True))==2
        # 学生表单通过私有查询码写入，与教师工作区复用同一组件。
        student=AppTest.from_string(f"import teaching_ui as ui\nui.render_transfer({db!r},{rid},'private')",default_timeout=15)
        check(student.run())
        labelled(student.text_area,"新案例：你的独立判断").set_value("先核对样本配液，保留其他解释")
        labelled(student.text_area,"新案例：支持判断的事实及替代解释").set_value("阳性正常仅支持批次扩增可用，不能排除样本问题")
        check(labelled(student.button,"提交新案例独立分析").click().run())
        assert w.record_task(db,rid,"private")["submission"]
        core.save_verification_plan(rid,"private",{f:"核对并记录" for f in ("hypothesis","variable","controls","expected_result","interpretation")})
        retest=AppTest.from_string(f"import teaching_ui as ui\nui.render_retests({db!r},{rid},'private')",default_timeout=15)
        check(retest.run())
        for item in retest.text_area:
            item.set_value("2026-01-01 10:00" if "时间" in item.label else "已记录的实际观察")
        labelled(retest.checkbox,"本次确已实施，以上为实际记录；我已检查图片不含身份信息").check()
        check(labelled(retest.button,"追加实际复测记录").click().run())
        assert len(w.load_retests(db,rid,"private"))==1
        check(teacher.radio(key="teacher_workspace").set_value("复测记录").run())
        labelled(teacher.text_area,"复测复核依据").set_value("对照信息尚不足以确认原因")
        check(labelled(teacher.button,"保存复测解释").click().run())
        assert w.load_retests(db,rid,teacher_authorized=True)[0]["review"]
        check(teacher.radio(key="teacher_workspace").set_value("教学建议").run())
        assert labelled(teacher.button,"AI 整理教学建议").disabled
        context=w.build_issues(db,teacher_authorized=True)
        w.save_suggestions(db,context,{"suggestions":[{"code":i["code"],"action":w.ISSUE_ACTIONS[i["code"]]["actions"][0]} for i in context["issues"]],"model":"deepseek-flash","usage":{}},True)
        check(teacher.run())
        # 先建立参考，再保存受控响应；不把生成图片称为真实准确率样本。
        image=Path(directory)/"gel.png"
        Image.new("RGB",(80,60),"black").save(image)
        prepared=prepare_image(image,[{"lane_id":1,"role":"样本"}])
        reference={"quality":"可辨","quality_issues":[],"lanes":[{"lane_id":1,"band_count":1,"pattern":"单条","position":"中部","brightness":"较弱"}]}
        sid=w.save_evaluation_sample(db,image,prepared,reference,[],"F01","独立验收集","弱带",True)
        run=w.save_evaluation_run(db,sid,prepared,{"status":"success","observations":reference,"raw_response":json.dumps(reference),"model_returned":"deepseek-flash","usage":{}},True)
        check(teacher.radio(key="teacher_workspace").set_value("图像评估").run())
        assert labelled(teacher.button,"运行评估图辅助观察").disabled
        labelled(teacher.multiselect,"人工发现泳道错配的编号").set_value([1])
        labelled(teacher.text_area,"人工评估备注（不是修改AI原始观察）").set_value("人工核对泳道对应")
        check(labelled(teacher.button,"保存泳道对应核验").click().run())
        assert w.evaluation_runs(db,sid,True)[0]["audit"]
        # 回到原任务评分；其它新任务保持独立。
        check(teacher.radio(key="teacher_workspace").set_value("课堂任务").run())
        labelled(teacher.selectbox,"查看任务").set_value(w.task_by_code(db,task)["id"]).run()
        for dimension in w.DIMENSIONS:
            teacher.selectbox(key=f"learn_{rid}_{dimension}").set_value(1)
        check(labelled(teacher.button,"保存过程评价").click().run())
        assert w.task_export(db,w.task_by_code(db,task)["id"],True)[0]["初判·"+w.DIMENSIONS[0]]==1
        print("六项升级页面通过：独立复核、方案保存、任务发布与评分、新案例提交、实际复测与解释、教学建议展示、图像评估核验；外部接口调用为零。")


if __name__=="__main__":
    main()
