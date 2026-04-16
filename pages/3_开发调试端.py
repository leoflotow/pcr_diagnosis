# -*- coding: utf-8 -*-
"""
开发调试端页面
"""

import os

import pandas as pd
import streamlit as st

from core import (
    BIGMODEL_DEFAULT_BASE_URL,
    BIGMODEL_MODEL,
    RULES_PATH,
    apply_common_styles,
    clear_history_records,
    clear_uploaded_images,
    init_database,
    render_card_title,
    render_page_hero,
    render_system_self_check,
    run_rules_library_check,
)


def main():
    init_database()
    apply_common_styles(theme="dev")
    render_page_hero(
        "开发调试端控制台",
        "集中查看系统状态、规则健康度与演示环境清理能力。",
        "开发调试端",
    )

    with st.container(border=True):
        render_card_title("系统自检", "快速检查规则库、数据库、环境变量与模型配置。")
        render_system_self_check()

    with st.container(border=True):
        render_card_title("API 调试信息", "用于确认本次文本线索抽取是否真正走了 AI 接口。")
        api_key_exists = bool(os.getenv("BIGMODEL_API_KEY", "").strip())
        base_url_env = os.getenv("BIGMODEL_BASE_URL", "").strip()
        base_url_exists = bool(base_url_env)
        base_url = base_url_env or BIGMODEL_DEFAULT_BASE_URL
        model = os.getenv("BIGMODEL_MODEL", BIGMODEL_MODEL)

        st.markdown(f"- 检测到 BIGMODEL_API_KEY：{'是' if api_key_exists else '否'}")
        st.markdown(f"- 检测到 BIGMODEL_BASE_URL：{'是' if base_url_exists else '否'}")
        st.markdown(f"- 当前 Base URL：{base_url}")
        st.markdown(f"- 当前模型：{model}")
        st.markdown("- 文本抽取策略：优先 AI（MiniMax），失败时回退本地规则")

        # 展示最近一次实际调用结果（如果学生端已经执行过诊断）
        last_api_debug = st.session_state.get("last_api_debug", {})
        if last_api_debug:
            st.markdown("#### 最近一次抽取调试")
            st.markdown(f"- 本次抽取方式：{last_api_debug.get('extractor_used', '未知')}")
            st.markdown(f"- API Key 掩码：{last_api_debug.get('api_key_masked', '-') or '-'}")
            st.markdown(f"- 失败原因摘要：{last_api_debug.get('fail_reason', '-') or '-'}")
            error_detail = (last_api_debug.get("error_detail", "") or "").strip()
            if error_detail:
                st.markdown(f"- 异常摘要：{error_detail}")
        else:
            st.info("当前还没有最近一次抽取调试信息，请先到“学生端”执行一次诊断。")

    with st.container(border=True):
        render_card_title("规则库查看 / 校验", "先看表，再一键做必要字段与数据质量检查。")
        try:
            rules_df = pd.read_csv(RULES_PATH)
            st.dataframe(rules_df, use_container_width=True, height=260)
        except Exception:
            st.warning("rules.csv 不存在或读取失败，暂无法展示规则表。")

        if "dev_rules_check_result" not in st.session_state:
            st.session_state["dev_rules_check_result"] = None

        if st.button("检查规则库", key="dev_check_rules"):
            st.session_state["dev_rules_check_result"] = run_rules_library_check()

        check_result = st.session_state.get("dev_rules_check_result")
        if check_result is not None:
            if check_result.get("ok"):
                st.success("规则库检查通过")
            else:
                st.error("规则库检查发现问题")

            for issue in check_result.get("issues", []):
                st.error(f"- {issue}")
            for warning in check_result.get("warnings", []):
                st.warning(f"- {warning}")

    with st.container(border=True):
        render_card_title("测试环境管理", "清空历史数据与上传文件；不删除代码、rules.csv 或表结构。")

        if "dev_confirm_cleanup" not in st.session_state:
            st.session_state["dev_confirm_cleanup"] = False
        confirm_cleanup = st.checkbox("我确认要清空测试数据", key="dev_confirm_cleanup")

        col_a, col_b, col_c = st.columns(3)

        with col_a:
            if st.button("清空历史诊断记录", key="dev_clear_history"):
                if not confirm_cleanup:
                    st.warning("请先勾选“我确认要清空测试数据”。")
                else:
                    ok, msg = clear_history_records()
                    st.session_state["student_last_payload"] = None
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

        with col_b:
            if st.button("清空上传图片", key="dev_clear_uploads"):
                if not confirm_cleanup:
                    st.warning("请先勾选“我确认要清空测试数据”。")
                else:
                    ok, msg = clear_uploaded_images()
                    if ok:
                        st.success(msg)
                    else:
                        st.warning(msg)

        with col_c:
            if st.button("恢复演示环境", key="dev_reset_demo"):
                if not confirm_cleanup:
                    st.warning("请先勾选“我确认要清空测试数据”。")
                else:
                    ok_db, msg_db = clear_history_records()
                    ok_up, msg_up = clear_uploaded_images()
                    st.session_state["student_last_payload"] = None

                    if ok_db and ok_up:
                        st.success("演示环境已重置")
                    else:
                        st.warning("演示环境重置完成，但有部分项目需要关注。")
                    st.info(msg_db)
                    st.info(msg_up)


if __name__ == "__main__":
    main()
