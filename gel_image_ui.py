"""学生图像核对和教师图像复核，结果不回填任何诊断表单。"""

import pandas as pd
import streamlit as st

import ai_config
import case_storage
from gel_image_assistant import (
    ROLES, PATTERNS, POSITIONS, BRIGHTNESS, CHECK_STATES, DEFAULT_SETTINGS,
    prepare_image, request_observation,
)


def observation_table(run):
    roles = {item["lane_id"]: item["role"] for item in run["mapping"]}
    return pd.DataFrame([{
        "泳道": lane["lane_id"], "人工身份": roles[lane["lane_id"]],
        "候选数量": lane["band_count"], "候选现象": lane["pattern"],
        "候选位置": lane["position"], "候选亮度": lane["brightness"],
    } for lane in run["observations"]["lanes"]])


def show_run(run):
    st.caption(f"观察记录 #{run['id']}｜{run['created_at']}｜模型 {run['model_requested']}｜提示词 {run['prompt_version']}")
    observations = run["observations"]
    st.write("AI 候选图像可读性：" + observations["quality"])
    if observations["quality_issues"]:
        st.write("需人工核对的图像问题：" + "、".join(observations["quality_issues"]))
    st.dataframe(observation_table(run), hide_index=True, width="stretch")
    st.caption("上表均为 AI 原始候选；空白数量表示未知，未见清晰条带不等于证明没有产物。")


def checks_table(check):
    return pd.DataFrame([{
        "泳道": entry["lane_id"], "核对状态": entry["state"], "条带数量": entry["band_count"],
        "条带现象": entry["pattern"], "相对位置": entry["position"],
        "相对亮度": entry["brightness"], "人工备注": entry["note"],
    } for entry in check["entries"]])


def render_check_editor(db_path, record_id, run, checks, prefix, code=None, teacher=False):
    related = [item for item in checks if item["run_id"] == run["id"]]
    latest_student = next((item for item in related if item["actor"] == "student"), None)
    own = next((item for item in related if item["actor"] == ("teacher" if teacher else "student")), None)
    if teacher and latest_student:
        st.markdown("**学生最近一次核对**")
        st.caption(f"核对记录 #{latest_student['id']}｜{latest_student['created_at']}")
        st.dataframe(checks_table(latest_student), hide_index=True, width="stretch")
    if teacher and own:
        st.caption(f"已保存教师图像复核 #{own['id']}｜{own['created_at']}")
        if own["source_student_check_id"] != (latest_student["id"] if latest_student else None):
            st.warning("学生图像核对已有新版本；此前教师图像复核保留，需重新查看。")
    # 初次复核不默认接受 AI 或学生的观察。
    if own:
        rows = own["entries"]
    else:
        rows = [{**lane, "state": "未核对", "note": ""} for lane in run["observations"]["lanes"]]
    columns = {
        "lane_id": st.column_config.NumberColumn("泳道", disabled=True),
        "state": st.column_config.SelectboxColumn("核对状态", options=CHECK_STATES, required=True),
        "band_count": st.column_config.NumberColumn("条带数量", min_value=0, max_value=100, step=1),
        "pattern": st.column_config.SelectboxColumn("条带现象", options=PATTERNS, required=True),
        "position": st.column_config.SelectboxColumn("相对位置", options=POSITIONS, required=True),
        "brightness": st.column_config.SelectboxColumn("相对亮度", options=BRIGHTNESS, required=True),
        "note": st.column_config.TextColumn("人工备注", max_chars=500),
    }
    edit_key = f"{prefix}_check_{run['id']}_{own['id'] if own else 0}_{latest_student['id'] if teacher and latest_student else 0}"
    st.markdown("**教师图像复核**" if teacher else "**逐项核对原图**")
    st.caption("核对状态初始为未核对；改动观察请选择已修正，看不清请选择无法确认。手机可横向滑动表格。")
    with st.form(edit_key):
        edited = st.data_editor(pd.DataFrame(rows), column_config=columns, hide_index=True,
                                column_order=["lane_id", "state", "band_count", "pattern", "position", "brightness", "note"],
                                width="stretch", num_rows="fixed", key=edit_key + "_editor")
        submitted = st.form_submit_button("保存图像复核" if teacher else "保存核对记录")
    if submitted:
        try:
            entries = edited.to_dict("records")
            for entry in entries:
                entry["lane_id"] = int(entry["lane_id"])
                value = entry["band_count"]
                if not pd.isna(value) and float(value) != int(value):
                    raise ValueError("条带数量必须是整数；看不清时请留空。")
                entry["band_count"] = None if pd.isna(value) else int(value)
                entry["note"] = "" if pd.isna(entry["note"]) else str(entry["note"])
            case_storage.save_gel_check(db_path, record_id, run["id"], run["context_key"], entries,
                "teacher" if teacher else "student", code=code,
                teacher_authorized=bool(teacher and st.session_state.get("teacher_verified")),
                source_student_check_id=latest_student["id"] if teacher and latest_student else None)
            st.session_state[prefix + "_notice"] = "图像核对已保存，现有诊断与评分未改变。"
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def render_history(history, prefix):
    if not history["runs"]:
        return
    with st.expander("历次图像观察与核对", expanded=False):
        options = {run["id"]: run for run in history["runs"]}
        selected = st.selectbox("图像观察版本", list(options),
            format_func=lambda value: f"#{value}｜{options[value]['created_at']}｜{'已保存候选' if options[value]['status'] == 'success' else '识别未完成'}",
            key=prefix + "_history")
        run = options[selected]
        st.caption("历史版本只读，对应保存时的图片、裁剪与泳道设置，不能套用到其他版本。")
        settings = run["settings"]
        st.write(f"保存时的图片设置：顺时针旋转 {settings['rotation']}°；"
                 f"左 {settings['left']}%、上 {settings['top']}%、右 {settings['right']}%、下 {settings['bottom']}%。")
        st.write("原图指纹：" + run["image_sha"][:16])
        if run["status"] != "success":
            st.info(run["error"] or "本次未保存有效观察。")
            return
        show_run(run)
        for check in history["checks"]:
            if check["run_id"] == run["id"]:
                st.caption(f"{'教师复核' if check['actor'] == 'teacher' else '学生核对'} #{check['id']}｜{check['created_at']}")
                st.dataframe(checks_table(check), hide_index=True, width="stretch")


def render_student_panel(db_path, record_id, code):
    record = case_storage.authorized_gel_record(db_path, record_id, code)
    if not record or not record["gel_image_path"]:
        return
    prefix = f"gel_student_{record_id}"
    history = case_storage.load_gel_history(db_path, record_id, code)
    latest = next((run for run in history["runs"] if run["status"] == "success"), None)
    with st.expander("电泳图 AI 辅助观察", expanded=False):
        st.caption("AI 结果可能出现漏识别或误识别，请逐项对照原图核对；系统不会将其直接作为诊断依据。")
        if st.session_state.get(prefix + "_notice"):
            st.success(st.session_state.pop(prefix + "_notice"))
        st.image(record["gel_image_path"], caption="原始凝胶图（人工核对依据）", width="stretch")
        st.markdown("**发送区域与泳道设置**")
        st.caption("仅发送处理后的图像和匿名泳道身份；旋转后按从左到右编号，泳道身份由你指定。")
        previous_settings = latest["settings"] if latest else DEFAULT_SETTINGS
        cols = st.columns(2)
        rotation = cols[0].selectbox("顺时针旋转", [0, 90, 180, 270],
            index=[0, 90, 180, 270].index(previous_settings["rotation"]), key=prefix + "_rotation")
        count = cols[1].number_input("泳道数量（人工指定）", min_value=1, max_value=30,
            value=len(latest["mapping"]) if latest else 1, step=1, key=prefix + "_lane_count")
        crop_cols = st.columns(4)
        settings = {"rotation": rotation}
        for col, name, label in zip(crop_cols, ["left", "top", "right", "bottom"],
                                   ["左边界 %", "上边界 %", "右边界 %", "下边界 %"]):
            settings[name] = col.number_input(label, min_value=0, max_value=100,
                value=previous_settings[name], step=1, key=prefix + "_" + name)
        old_roles = {item["lane_id"]: item["role"] for item in latest["mapping"]} if latest else {}
        mapping_df = st.data_editor(pd.DataFrame([
            {"lane_id": index, "role": old_roles.get(index, "身份未确认")} for index in range(1, count + 1)]),
            column_config={"lane_id": st.column_config.NumberColumn("从左到右泳道编号", disabled=True),
                           "role": st.column_config.SelectboxColumn("人工指定身份", options=ROLES, required=True)},
            hide_index=True, width="stretch", num_rows="fixed", key=f"{prefix}_mapping_{count}")
        mapping = [{"lane_id": int(row["lane_id"]), "role": row["role"]} for row in mapping_df.to_dict("records")]
        try:
            prepared = prepare_image(record["gel_image_path"], mapping, settings)
        except ValueError as exc:
            st.warning(str(exc))
            render_history(history, prefix)
            return
        st.image(prepared["image_bytes"], caption="将发送至 DeepSeek 的图像区域（请核对）", width="stretch")
        current = latest if latest and latest["context_key"] == prepared["context_key"] else None
        if latest and not current:
            st.info("图片或泳道设置已变化，旧观察仅保留在历史中；当前设置尚无有效观察。")
        configured = bool(ai_config.api_key())
        enabled = ai_config.vision_enabled()
        if not configured:
            st.info("尚未配置 DEEPSEEK_API_KEY，请联系管理员；可继续人工观察与复盘。")
        elif not enabled:
            st.info("管理员已关闭图像辅助观察；原有功能可继续使用。")
        consent = st.checkbox("我已确认发送区域不含姓名等身份信息，同意发送至 DeepSeek 辅助观察",
                              key=prefix + "_consent_" + prepared["context_key"][:16])
        repeat = st.checkbox("重新识别（会产生一次新调用）", key=prefix + "_repeat") if current else False
        if st.button("AI 辅助观察", key=prefix + "_request", disabled=not (configured and enabled and consent)):
            if current and not repeat:
                st.info("已展示当前设置的已保存观察，本次未重复调用。")
            else:
                with st.spinner("正在辅助观察，请保留人工判断…"):
                    response = request_observation(prepared)
                if response["status"] in {"success", "failed"}:
                    try:
                        case_storage.save_gel_run(db_path, record_id, code, prepared, response)
                        if response["status"] == "success":
                            st.session_state[prefix + "_notice"] = "辅助观察已保存，请逐项对照原图核对。"
                            st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                if response["status"] != "success":
                    st.warning(response["error"])
        if current:
            show_run(current)
            render_check_editor(db_path, record_id, current, history["checks"], prefix, code=code)
            own = next((item for item in history["checks"] if item["run_id"] == current["id"] and item["actor"] == "teacher"), None)
            if own:
                st.markdown("**教师图像复核记录**")
                st.dataframe(checks_table(own), hide_index=True, width="stretch")
        render_history(history, prefix)


def render_teacher_panel(db_path, record_id):
    if not st.session_state.get("teacher_verified"):
        return
    record = case_storage.authorized_gel_record(db_path, record_id, teacher_authorized=True)
    if not record or not record["gel_image_path"]:
        return
    history = case_storage.load_gel_history(db_path, record_id, teacher_authorized=True)
    prefix = f"gel_teacher_{record_id}"
    with st.expander("电泳图辅助观察与人工复核", expanded=False):
        st.caption("图像观察复核与原因确认分别保存，不改变现有评分、反馈版本和课堂统计。")
        if st.session_state.get(prefix + "_notice"):
            st.success(st.session_state.pop(prefix + "_notice"))
        latest = next((run for run in history["runs"] if run["status"] == "success"), None)
        if latest:
            try:
                prepared = prepare_image(record["gel_image_path"], latest["mapping"], latest["settings"])
                st.image(record["gel_image_path"], caption="原始凝胶图", width="stretch")
                if prepared["context_key"] == latest["context_key"]:
                    st.image(prepared["image_bytes"], caption="本次辅助观察对应的发送区域", width="stretch")
                    show_run(latest)
                    render_check_editor(db_path, record_id, latest, history["checks"], prefix, teacher=True)
                else:
                    st.warning("当前原图与已保存观察不一致，旧记录只读，不能用于当前图片。")
            except ValueError as exc:
                st.warning(str(exc))
        else:
            st.info("学生尚未保存有效的 AI 图像观察，可按原有流程人工复核原图。")
        render_history(history, prefix)
