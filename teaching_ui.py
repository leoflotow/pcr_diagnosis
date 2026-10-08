"""教师工作区与学生教学记录面板，复用现有访问验证与视觉样式。"""

from pathlib import Path
import json

import pandas as pd
import streamlit as st

import teaching_workflow as workflow
from evidence_support import parse_json


def teacher_ok():
    return st.session_state.get("teacher_verified") is True


def notice_call(action):
    try:
        result = action()
        st.success("已保存。")
        return result
    except ValueError as exc:
        st.warning(str(exc))
        return None


def render_task_entry(db_path):
    with st.expander("加入课堂任务（可选）"):
        code = st.text_input("课堂任务编号", key="teaching_join_code")
        if st.button("查看并加入任务", key="teaching_join"):
            task = workflow.task_by_code(db_path, code)
            if not task or workflow.task_status(task) != "开放":
                st.warning("任务不存在、已关闭或已截止。")
            else:
                st.session_state["teaching_task"] = task
                st.rerun()
        task = st.session_state.get("teaching_task")
        if task:
            current = workflow.task_by_code(db_path, task["code"])
            st.write(f"当前任务：{task['title']}（{workflow.task_status(current)}）")
            st.write(task["instructions"])
            st.caption("任务编号不是私有查询码；请另行保存提交案例后显示的查询码。")
            if task["due_at"]:
                st.write("截止时间：" + task["due_at"].replace("T", " "))
            scheme = parse_json(task["scheme_json"])
            if scheme:
                st.caption(f"指定课程方案：{scheme['name']} v{scheme['version']}。请在第 2 步核对后应用。")
            if st.button("退出当前任务", key="teaching_leave"):
                st.session_state.pop("teaching_task", None)
                st.rerun()


def course_presets(db_path, fallback):
    task = st.session_state.get("teaching_task")
    task_scheme = parse_json(task["scheme_json"]) if task else None
    schemes = [task_scheme] if task_scheme else workflow.list_schemes(db_path)
    output = []
    seen = set()
    for scheme in schemes:
        if scheme["name"] in seen:
            continue
        seen.add(scheme["name"])
        output.append({**parse_json(scheme["payload_json"]), "name": f"{scheme['name']} · v{scheme['version']}",
                       "source": scheme["source"], "_snapshot": scheme})
    return output + fallback


def render_transfer(db_path, record_id, code):
    context = workflow.record_task(db_path, record_id, code)
    task, submission = context["task"], context["submission"]
    if not task:
        return
    with st.expander("课堂任务与新案例独立分析"):
        st.write("任务：" + task["title"])
        st.write(task["instructions"])
        if not task["transfer_prompt"]:
            st.caption("本次任务未安排新案例分析。")
            return
        st.markdown("**新案例题目**")
        st.write(task["transfer_prompt"])
        st.caption("请独立作答，不使用本案例的系统结论套用；此处不会生成模型答案。一次提交保留原稿。")
        if submission:
            st.write("已提交判断：" + submission["answer"])
            st.write("依据：" + submission["reasoning"])
            return
        if workflow.task_status(task) != "开放":
            st.info("任务已关闭或截止，当前只读。")
            return
        with st.form(f"transfer_{record_id}"):
            answer = st.text_area("新案例：你的独立判断", max_chars=5000)
            reasoning = st.text_area("新案例：支持判断的事实及替代解释", max_chars=5000)
            minutes = st.number_input("实际作答用时（分钟，可留空）", min_value=0.1, max_value=1440.0, value=None)
            if st.form_submit_button("提交新案例独立分析"):
                try:
                    workflow.save_transfer(db_path,record_id,code,answer,reasoning,minutes)
                    st.rerun()
                except ValueError as exc:
                    st.warning(str(exc))


def render_tasks(db_path):
    st.subheader("课堂任务与学习过程评价")
    st.caption("按案例记录三个阶段；同案例修订与新案例独立分析分别评价，不自动评分。")
    schemes = workflow.list_schemes(db_path)
    with st.expander("创建课堂任务"):
        with st.form("create_teaching_task"):
            title = st.text_input("任务名称", max_chars=120)
            instructions = st.text_area("任务说明", max_chars=5000)
            scheme_id = st.selectbox("指定课程方案（可不选）", [None]+[s["id"] for s in schemes],
                                     format_func=lambda i: "暂不指定" if i is None else next(f"{s['name']} v{s['version']}" for s in schemes if s["id"] == i))
            due = st.text_input("截止时间（可空，如 2026-10-25 18:00）")
            prompt = st.text_area("新案例独立分析题目（可空）", max_chars=5000)
            st.caption("发布后题目和方案快照固定；需要更改时创建新任务，旧记录保留。")
            if st.form_submit_button("发布课堂任务"):
                code = notice_call(lambda: workflow.create_task(db_path,title,instructions,prompt,due,scheme_id,teacher_ok()))
                if code:
                    st.success("课堂任务编号：" + code)
    tasks = workflow.list_tasks(db_path,teacher_ok())
    if not tasks:
        st.info("尚无课堂任务。")
        return
    task_id = st.selectbox("查看任务", [t["id"] for t in tasks], format_func=lambda i: next(f"{t['title']} · {t['code']}" for t in tasks if t["id"] == i))
    task = next(t for t in tasks if t["id"] == task_id)
    st.write(f"任务状态：{workflow.task_status(task)}；截止：{task['due_at'] or '未设置'}")
    if st.button("关闭任务" if task["active"] else "重新开放任务", key=f"task_active_{task_id}"):
        workflow.set_task_active(db_path,task_id,not task["active"],teacher_ok())
        st.rerun()
    rows = workflow.task_export(db_path,task_id,teacher_ok())
    if not rows:
        st.info("该任务尚无案例提交。")
        return
    frame = pd.DataFrame(rows)
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button("导出任务学习记录（CSV）", frame.to_csv(index=False).encode("utf-8-sig"), f"task_{task_id}.csv", "text/csv")
    for dimension in workflow.DIMENSIONS:
        initial = f"初判·{dimension}"
        revised = f"修订·{dimension}"
        paired = frame[[initial,revised]].dropna()
        transfer_count = int(frame[f"新案例·{dimension}"].notna().sum())
        st.caption(f"{dimension}：初判/修订配对评价 {len(paired)}/{len(rows)} 例；新案例已评价 {transfer_count}/{len(rows)} 例。")
    record_id = st.selectbox("人工评价案例", [r["案例编号"] for r in rows])
    selected = next(r for r in rows if r["案例编号"] == record_id)
    st.write({k: selected[k] for k in ("初判","修订","修订依据","新案例判断","新案例依据")})
    with st.form(f"learning_eval_{task_id}_{record_id}"):
        stage = st.selectbox("评价阶段", ["initial","revised","transfer"], format_func=lambda s: {"initial":"独立初判","revised":"反馈后修订","transfer":"新案例独立分析"}[s])
        rubric = {d: st.selectbox(d,[None,0,1,2],format_func=lambda n:"未评价" if n is None else str(n),key=f"learn_{record_id}_{d}") for d in workflow.DIMENSIONS}
        st.caption("0：未体现；1：部分体现；2：有具体依据。未评价留空。保存为独立评价版本，不改原因反馈。")
        note = st.text_area("评价备注")
        if st.form_submit_button("保存过程评价"):
            notice_call(lambda: workflow.save_learning_evaluation(db_path,record_id,stage,rubric,note,teacher_ok()))


def render_independent(db_path, records):
    st.subheader("教师独立复核")
    st.caption("本模式先显示原始记录，提交独立判断后才展开系统候选。共用教师入口无法区分教师个人身份；任一教师查看过建议的案例都不再记为独立判断。")
    if not records:
        st.info("尚无课堂案例。")
        return
    ids = [r["id"] for r in records]
    record_id = st.selectbox("选择独立复核案例",ids,format_func=lambda i:f"案例 {i}")
    context = workflow.independent_record(db_path,record_id,teacher_ok())
    raw = context["raw"]
    for field,label in [("abnormality","实验现象"),("positive_control_normal","阳性对照"),("negative_control_band","阴性对照"),("template_amount","模板体积 μL"),("annealing_temp","退火温度 ℃"),("cycles","循环数"),("description","原始描述")]:
        st.write(f"{label}：{raw[field] if raw[field] is not None else '未填写'}")
    parameters = parse_json(raw["input_json"])
    labels = {"course_name":"课程", "experiment_name":"实验", "template_type":"模板类型",
              "template_concentration":"模板浓度 ng/μL", "reaction_volume":"每管反应体积 μL",
              "target_size":"目标片段 bp", "recommended_temp":"推荐退火温度 ℃",
              "polymerase":"聚合酶", "controls":"对照设置", "protocol_notes":"程序与电泳条件",
              "lane_notes":"人工泳道说明"}
    details = [{"实验条件":label,"原始记录":parameters[field]} for field,label in labels.items()
               if parameters.get(field) not in (None, "")]
    if details:
        with st.expander("补充实验条件与泳道记录"):
            st.dataframe(pd.DataFrame(details),hide_index=True,width="stretch")
    if raw["gel_image_path"] and Path(raw["gel_image_path"]).is_file():
        st.image(raw["gel_image_path"],caption="原始凝胶图",width="stretch")
    if context["eligible"]:
        with st.form(f"blind_{record_id}"):
            cause = st.text_input("教师独立判断（可填原因待核实）",max_chars=500)
            reason = st.text_area("独立判断的原始依据")
            evidence = st.selectbox("独立判断证据等级",["经验复核","原始记录支持","复测验证","原因待核实"])
            confirm = st.checkbox("我此前未查看该案例的系统建议，也未由其他途径获知候选排序")
            if st.form_submit_button("保存独立判断并查看建议"):
                if not confirm:
                    st.warning("请如实确认未提前查看建议；已查看的案例可用常规复核。")
                else:
                    try:
                        workflow.save_independent_review(db_path,record_id,cause,reason,evidence,teacher_ok())
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))
    elif not context["review"]:
        st.info("该案例已查看过建议或完成常规原因复核，不再补记为独立判断。")
    if context["review"]:
        st.write("已保存独立判断："+context["review"]["cause"])
        st.write(context["review"]["reason"])
        snapshot = parse_json(context["review"]["snapshot_json"])
        st.markdown("**当时保存的系统候选**")
        candidates = snapshot.get("followup",{}).get("final_results") or snapshot.get("initial",{}).get("results",[])
        st.dataframe(pd.DataFrame(candidates),hide_index=True,width="stretch")
        st.caption("独立判断不自动成为最终原因。请在常规案例复核中结合原始记录保存最终判断和修改理由。")


def render_schemes(db_path):
    st.subheader("课程方案与依据")
    schemes = workflow.list_schemes(db_path)
    names = list(dict.fromkeys(s["name"] for s in schemes))
    selected = st.selectbox("维护课程方案",["新建方案"]+names)
    latest = next((s for s in schemes if s["name"] == selected),None)
    from evidence_support import load_course_presets
    preset = next(iter(load_course_presets()), {})
    payload = parse_json(latest["payload_json"]) if latest else preset
    with st.form("course_scheme_edit"):
        name = st.text_input("方案名称",value=latest["name"] if latest else preset.get("name", ""),max_chars=120,disabled=bool(latest))
        data = {}
        for field,label in [("course_name","课程名称"),("experiment_name","实验名称"),("polymerase","聚合酶名称"),("controls","对照设置")]:
            data[field] = st.text_input(label,value=payload.get(field, ""),max_chars=2000)
        types = ["待确认","质粒","基因组 DNA","cDNA","其他"]
        data["template_type"] = st.selectbox("方案模板类型",types,index=types.index(payload.get("template_type","待确认")))
        for field,label in [("template_concentration","模板浓度 ng/μL"),("reaction_volume","反应体积 μL"),("target_size","目标片段 bp"),("recommended_temp","推荐退火温度 ℃")]:
            data[field] = st.number_input(label,value=float(payload[field]) if payload.get(field) else None,min_value=0.01)
        data["template_amount"] = st.number_input("每管模板加入体积 μL",value=float(payload["template_amount"]) if payload.get("template_amount") else None,min_value=0.01)
        data["cycles"] = st.number_input("方案循环数",value=int(payload["cycles"]) if payload.get("cycles") else None,min_value=1,step=1)
        data["protocol_notes"] = st.text_area("完整程序、配制与电泳条件说明",value=payload.get("protocol_notes", ""),max_chars=2000)
        source = st.text_area("方案依据（讲义版本、试剂说明或教师核定记录）",value=latest["source"] if latest else preset.get("source", ""),max_chars=2000)
        st.caption("未知数值留空。保存时追加版本，已发布任务与旧案例不会随之改变。")
        if st.form_submit_button("保存课程方案新版本"):
            saved = notice_call(lambda: workflow.save_scheme(db_path,name,data,source,latest["version"] if latest else 0,teacher_ok()))
            if saved:
                st.rerun()
    if schemes:
        st.dataframe(pd.DataFrame([{k:s[k] for k in ("id","name","version","source","created_at")} for s in schemes]).rename(columns={"id":"方案编号","name":"方案名称","version":"版本","source":"方案依据","created_at":"保存时间"}),hide_index=True,width="stretch")



def render_retests(db_path,record_id,code=None,teacher=False):
    records=workflow.load_retests(db_path,record_id,code,teacher and teacher_ok())
    with st.expander("实际复测记录与解释"):
        st.caption("仅记录已实施的复测；计划不计作结果。新图另存，不覆盖原案例。复测记录和人工解释不自动改变原因排序或成绩。")
        if not teacher:
            with st.form(f"retest_{record_id}"):
                payload={}
                for field,label in [("performed_at","实际复测时间（如 2026-10-08 14:30）"),("changed","实际改变的条件"),("kept","保持不变的条件"),("controls","本次对照及实际结果"),("sample_result","样本实际结果"),("expected_comparison","实际结果与原先预期的比较")]:
                    payload[field]=st.text_area(label,max_chars=5000)
                payload["conclusion"]=st.selectbox("你对原假设的解释",workflow.RETEST_CONCLUSIONS,index=2)
                image=st.file_uploader("复测电泳图（可选）",type=["png","jpg","jpeg"],key=f"retest_image_{record_id}")
                confirmed=st.checkbox("本次确已实施，以上为实际记录；我已检查图片不含身份信息")
                if st.form_submit_button("追加实际复测记录"):
                    if not confirmed:
                        st.warning("请先确认是已实施的实际记录。")
                    else:
                        from core import save_uploaded_image
                        image_path,error=save_uploaded_image(image)
                        if error:
                            st.warning(error)
                        else:
                            try:
                                workflow.save_retest(db_path,record_id,code,payload,image_path)
                                st.rerun()
                            except ValueError as exc:
                                st.warning(str(exc))
        for item in records:
            st.markdown(f"**实际复测 #{item['id']} · {item['created_at']}**")
            for key,label in [("performed_at","实施时间"),("changed","改变条件"),("kept","保持条件"),("controls","对照结果"),("sample_result","样本结果"),("expected_comparison","与预期比较"),("conclusion","学生解释")]:
                st.write(label+"："+item["payload"][key])
            if item["image_path"] and Path(item["image_path"]).is_file():
                st.image(item["image_path"],caption="本次复测图片",width="stretch")
            review=item["review"]
            if review:
                st.write("教师解释："+review["conclusion"]+"；依据："+review["note"])
            else:
                st.caption("尚无教师复测复核。")
            with st.expander(f"复测 #{item['id']} 对应的计划快照"):
                st.write(parse_json(item["plan_json"]))
            if teacher:
                with st.form(f"retest_review_{item['id']}_{review['id'] if review else 0}"):
                    conclusion=st.selectbox("教师复测解释",workflow.RETEST_CONCLUSIONS,index=workflow.RETEST_CONCLUSIONS.index(review["conclusion"]) if review else 2)
                    note=st.text_area("复测复核依据")
                    if st.form_submit_button("保存复测解释"):
                        notice_call(lambda:workflow.review_retest(db_path,item["id"],conclusion,note,review["id"] if review else None,teacher_ok()))


BASIS_CARDS=[
    {"name":"先核对对照，再解释样本", "when":"所有 PCR 与电泳异常", "why":"阳性、阴性对照的观察与设置决定本批结果可以支持哪些解释。", "missing":"对照未设置或未观察时如实记录；两个不同温度的同一样本不是阳性/阴性对照。", "source":"项目规则审查与对照分型规则；课程讲义条件由教师核定。"},
    {"name":"体积不能直接证明模板量", "when":"考虑模板不足或过量时", "why":"输入质量需要模板浓度与加入体积；合适范围还取决于模板、反应体系和试剂。", "missing":"当前讲义约100 ng/100 μL是配制要求；原液浓度未知时不等于本次实际输入质量。", "source":"教师提供的课程条件及项目输入边界。"},
    {"name":"梯度温度用于比较，不能预先指定最佳值", "when":"50–63℃梯度退火课程方案", "why":"保存每管实际采用温度并结合条带判读；单一绝对温度不能证明过高或过低。", "missing":"最佳温度、目标片段与试剂品牌未知时保留待确认。", "source":"教师提供的梯度方案及项目温度归一化边界。"},
    {"name":"观察条带不等于确定原因", "when":"所有图像辅助观察", "why":"模型候选只描述图像，人工核对后仍需结合对照与操作记录解释原因。", "missing":"DL5000名称本身不等于已标定条带；系统不自动测精确bp或浓度。", "source":"图像模块受限观察白名单及项目规则审查。"},
]


def render_basis_cards(payload):
    with st.expander("排查依据与适用边界"):
        st.caption("以下为课程记录与程序边界说明，不是模型临时生成的出处。课程资料补全后再核定具体参数范围。")
        for card in BASIS_CARDS:
            st.markdown("**"+card["name"]+"**")
            st.write("适用："+card["when"])
            st.write(card["why"])
            st.write("仍需核对："+card["missing"])
            st.caption("依据："+card["source"])
        st.markdown("[项目规则审查所引用的 NEB 排错资料](https://www.neb.com/en-us/tools-and-resources/troubleshooting-guides/taq-pcr-kit-troubleshooting-guide)")
        scheme=payload.get("course_scheme_snapshot",{})
        if scheme:
            st.write("本次采用的方案版本："+scheme.get("name", ""))
            st.caption(scheme.get("source",""))


def render_insights(db_path):
    st.subheader("班级共性问题与教学建议")
    tasks=workflow.list_tasks(db_path,teacher_ok())
    task_id=st.selectbox("建议统计范围",[None]+[t["id"] for t in tasks],format_func=lambda i:"全部课堂记录" if i is None else next(t["title"] for t in tasks if t["id"]==i))
    context=workflow.build_issues(db_path,task_id,teacher_ok())
    st.caption(f"当前包含 {context['denominator']} 个真实课堂案例；统计单位为案例，不能当作学生人数。缺少记录不等于学生不会。")
    if not context["issues"]:
        st.info("暂无满足当前规则的问题记录；这不代表已经验证教学效果。")
        return
    st.dataframe(pd.DataFrame([{"问题":i["label"],"案例数":i["count"],"对应案例":", ".join(map(str,i["case_ids"]))} for i in context["issues"]]),hide_index=True,width="stretch")
    for issue in context["issues"]:
        st.write(issue["label"]+"："+workflow.ISSUE_ACTIONS[issue["code"]]["actions"][0])
    st.caption("AI 仅从上述固定教学动作中选择；只发送聚合数量与问题代码，不发送学生描述、班级名、图片或案例查询码。")
    import ai_config
    consent=st.checkbox("同意发送上述匿名聚合数量至 DeepSeek 整理教学建议")
    saved=workflow.latest_suggestions(db_path,context,teacher_ok())
    repeat=st.checkbox("重新整理建议（新增一次接口调用）") if saved else False
    if st.button("AI 整理教学建议",disabled=not(consent and ai_config.api_key())):
        if saved and not repeat:
            st.info("已有当前记录对应的建议，未重复调用。")
        else:
            try:
                response=workflow.request_teaching_suggestions(context)
                workflow.save_suggestions(db_path,context,response,teacher_ok())
                st.rerun()
            except ValueError as exc:
                st.warning(str(exc))
    if saved:
        st.markdown("**已保存的 AI 辅助选择（教师核对后使用）**")
        st.caption(f"模型：{saved['model']}；记录时间：{saved['created_at']}")
        for item in json.loads(saved["result_json"]):
            st.write(workflow.ISSUE_ACTIONS[item["code"]]["label"]+"："+item["action"])
    export={"统计":context,"建议":json.loads(saved["result_json"]) if saved else [],"说明":"案例统计不代表人数或能力评估；AI建议由教师核对后使用。"}
    st.download_button("导出教学建议与依据",json.dumps(export,ensure_ascii=False,indent=2),"teaching_suggestions.json","application/json")


def lane_editor(mapping,key):
    from gel_image_assistant import PATTERNS,POSITIONS,BRIGHTNESS
    frame=pd.DataFrame([{"lane_id":i["lane_id"],"band_count":None,"pattern":"无法确认","position":"无法确认","brightness":"无法确认"} for i in mapping])
    return st.data_editor(frame,hide_index=True,width="stretch",key=key,column_config={
        "lane_id":st.column_config.NumberColumn("泳道",disabled=True),
        "band_count":st.column_config.NumberColumn("参考条带数（未知留空）",min_value=0,max_value=100,step=1),
        "pattern":st.column_config.SelectboxColumn("参考形态",options=PATTERNS,required=True),
        "position":st.column_config.SelectboxColumn("参考位置",options=POSITIONS,required=True),
        "brightness":st.column_config.SelectboxColumn("参考亮度",options=BRIGHTNESS,required=True)})


def clean_lanes(frame):
    output=[]
    for row in frame.to_dict("records"):
        raw=row["band_count"]
        if pd.isna(raw):
            row["band_count"]=None
        elif float(raw).is_integer():
            row["band_count"]=int(raw)
        else:
            raise ValueError("条带数量必须为整数或未知。")
        row["lane_id"]=int(row["lane_id"])
        output.append(row)
    return output


def render_image_evaluation(db_path):
    from gel_image_assistant import ROLES,QUALITIES,ISSUES,prepare_image,request_observation
    from core import save_uploaded_image,validate_uploaded_image
    import ai_config
    st.subheader("电泳图识别独立评估")
    st.caption("先保存教师参考标注，再调用模型。原始AI表现与人工核对分开；参考标注有争议的泳道不强设正确答案。此入口不会改变课堂诊断或成绩。")
    with st.expander("添加图片与独立参考标注"):
        upload=st.file_uploader("上传获准评估的脱敏电泳图",type=["png","jpg","jpeg"],key="eval_upload")
        if upload:
            error=validate_uploaded_image(upload)
            if error:
                st.warning(error)
            else:
                import hashlib
                sha=hashlib.sha256(upload.getvalue()).hexdigest()
                stored=st.session_state.get("eval_uploaded_path",{})
                if stored.get("sha")!=sha:
                    path,error=save_uploaded_image(upload)
                    if error:
                        st.warning(error)
                        return
                    st.session_state["eval_uploaded_path"]={"sha":sha,"path":path}
                path=st.session_state["eval_uploaded_path"]["path"]
                family=st.text_input("原图族编号（同一原图所有变体沿用同一编号）",max_chars=100)
                split=st.selectbox("评估集合",workflow.EVALUATION_SPLITS)
                quality=st.selectbox("教师质量分组",workflow.EVALUATION_QUALITIES)
                rotation=st.selectbox("评估图顺时针旋转",[0,90,180,270])
                crop=st.columns(4)
                settings={"rotation":rotation}
                for col,field,label,default in zip(crop,["left","top","right","bottom"],["左 %","上 %","右 %","下 %"],[0,0,100,100]):
                    settings[field]=col.number_input(label,min_value=0,max_value=100,value=default,step=1,key="eval_"+field)
                count=st.number_input("评估图泳道数量",min_value=1,max_value=30,value=1,step=1)
                mapping_frame=st.data_editor(pd.DataFrame([{"lane_id":i,"role":"身份未确认"} for i in range(1,count+1)]),hide_index=True,width="stretch",key=f"eval_mapping_{sha}_{count}",column_config={"lane_id":st.column_config.NumberColumn("泳道",disabled=True),"role":st.column_config.SelectboxColumn("身份",options=ROLES,required=True)})
                mapping=[{"lane_id":int(r["lane_id"]),"role":r["role"]} for r in mapping_frame.to_dict("records")]
                try:
                    prepared=prepare_image(path,mapping,settings)
                except ValueError as exc:
                    st.warning(str(exc))
                    return
                st.image(prepared["image_bytes"],caption="参考标注对应的发送区域",width="stretch")
                context=prepared["context_key"]
                reference_quality=st.selectbox("参考可读性",QUALITIES,key=f"eval_ref_quality_{context}")
                reference_issues=st.multiselect("参考质量问题",ISSUES,key=f"eval_ref_issues_{context}")
                reference_frame=lane_editor(mapping,f"eval_reference_{context}")
                disputed=st.multiselect("有争议的泳道",list(range(1,count+1)),key=f"eval_disputed_{context}")
                confirm=st.checkbox("我已获准使用此图，未看本图的模型候选而独立标注；同源变体已归入相同原图族",key=f"eval_ref_confirm_{context}")
                if st.button("保存独立参考标注",disabled=not confirm):
                    try:
                        reference={"quality":reference_quality,"quality_issues":reference_issues,"lanes":clean_lanes(reference_frame)}
                        sample_id=workflow.save_evaluation_sample(db_path,path,prepared,reference,disputed,family,split,quality,teacher_ok())
                        st.success(f"已保存参考样本 #{sample_id}，现在可以进行辅助观察。")
                    except ValueError as exc:
                        st.warning(str(exc))
    samples=workflow.evaluation_samples(db_path,teacher_ok())
    if not samples:
        st.info("尚无参考样本。需要实际图片后再开展识别表现评估。")
        return
    sample_id=st.selectbox("选择已保存参考样本",[s["id"] for s in samples],format_func=lambda i:next(f"#{s['id']} · {s['family']} · {s['split']} · {s['quality']}" for s in samples if s["id"]==i))
    sample=next(s for s in samples if s["id"]==sample_id)
    try:
        prepared=workflow.prepare_evaluation(sample)
    except ValueError as exc:
        st.warning(str(exc))
        return
    st.image(prepared["image_bytes"],caption="已保存的评估发送区域",width="stretch")
    st.dataframe(pd.DataFrame(parse_json(sample["reference_json"])["lanes"]).rename(columns={"lane_id":"泳道","band_count":"参考条带数","pattern":"参考形态","position":"参考位置","brightness":"参考亮度"}),hide_index=True,width="stretch")
    runs=workflow.evaluation_runs(db_path,sample_id,teacher_ok())
    consent=st.checkbox("我已检查发送区域不含身份信息，同意发送至 DeepSeek 进行本次评估",key=f"eval_send_{sample_id}")
    repeat=st.checkbox("追加一次新观察（产生新增用量）",key=f"eval_repeat_{sample_id}") if runs else False
    if st.button("运行评估图辅助观察",disabled=not(consent and ai_config.api_key() and ai_config.vision_enabled())):
        if runs and not repeat:
            st.info("已有保存版本，未重复请求。")
        else:
            response=request_observation(prepared)
            if response["status"] in {"success","failed"}:
                try:
                    workflow.save_evaluation_run(db_path,sample_id,prepared,response,teacher_ok())
                    st.rerun()
                except ValueError as exc:
                    st.warning(str(exc))
            else:
                st.warning(response["error"])
    if runs:
        run_id=st.selectbox("查看观察版本",[r["id"] for r in runs])
        run=next(r for r in runs if r["id"]==run_id)
        response=parse_json(run["response_json"])
        if response["status"]!="success":
            st.warning("此版本请求未完成，不计入识别表现。")
        else:
            comparison=workflow.evaluation_comparison(sample,run)
            st.dataframe(pd.DataFrame(comparison),hide_index=True,width="stretch")
            with st.form(f"eval_audit_{run_id}"):
                mismatches=st.multiselect("人工发现泳道错配的编号",[r["lane_id"] for r in json.loads(sample["mapping_json"])],default=json.loads(run["audit"]["mismatch_json"]) if run["audit"] else [])
                note=st.text_area("人工评估备注（不是修改AI原始观察）",value=run["audit"]["note"] if run["audit"] else "")
                if st.form_submit_button("保存泳道对应核验"):
                    notice_call(lambda:workflow.save_evaluation_audit(db_path,run_id,mismatches,note,teacher_ok()))
    all_runs=workflow.evaluation_runs(db_path,teacher_authorized=teacher_ok())
    all_rows=[]
    samples_by_id={s["id"]:s for s in samples}
    for run in all_runs:
        all_rows.extend(workflow.evaluation_comparison(samples_by_id[run["sample_id"]],run))
    if all_rows:
        data=pd.DataFrame(all_rows)
        st.markdown("**按集合、质量与模型版本核对原始表现**")
        st.caption("数量差是与参考标注的条带数差，不能定位具体漏检条带；错配需人工核验。重复请求不是独立样本，争议/错配泳道不计数量差，不把模型未知当作零条带。不同提示词版本分别汇总。")
        for group, frame in data.groupby(["集合","质量","返回模型","提示词"],dropna=False):
            comparable=frame[frame["数量可比较"]]
            st.write(f"{' / '.join(map(str,group))}：{frame['原图族'].nunique()} 个原图族，{frame['观察版本'].nunique()} 次成功观察，{len(comparable)}/{len(frame)} 个观察泳道数量可比较；少于参考 {int(comparable['数量少于参考'].sum())} 条，多于参考 {int(comparable['数量多于参考'].sum())} 条。")
            known=frame["参考已知时AI未知"].dropna()
            unknown=frame["参考未知时保留未知"].dropna()
            mismatches=frame["泳道错配人工标记"].dropna()
            st.caption(f"参考已知时AI未知：{int(known.sum())}/{len(known)}；参考未知时保留未知：{int(unknown.sum())}/{len(unknown)}；人工核验错配：{int(mismatches.sum())}/{len(mismatches)}。分母为观察泳道，不是学生人数或独立图片数。")
        st.download_button("导出原始图像评估明细",data.to_csv(index=False).encode("utf-8-sig"),"gel_evaluation.csv","text/csv")


def render_teacher_workspace(db_path,workspace,records):
    if not teacher_ok():
        st.warning("请先完成教师访问验证。")
        return
    if workspace=="课堂任务":
        render_tasks(db_path)
    elif workspace=="独立复核":
        render_independent(db_path,records)
    elif workspace=="课程方案":
        render_schemes(db_path)
    elif workspace=="复测记录":
        st.subheader("实际复测与教师解释")
        if not records:
            st.info("尚无课堂案例。")
            return
        record_id=st.selectbox("复测案例",[r["id"] for r in records])
        render_retests(db_path,record_id,teacher=True)
    elif workspace=="教学建议":
        render_insights(db_path)
    elif workspace=="图像评估":
        render_image_evaluation(db_path)
