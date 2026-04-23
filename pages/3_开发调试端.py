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
    DB_PATH,
    RULES_PATH,
    UPLOAD_DIR,
    apply_common_styles,
    clear_history_records,
    clear_uploaded_images,
    ensure_page_config,
    init_access_state,
    init_database,
    read_csv_with_fallback,
    render_card_title,
    render_entry_guard,
    render_page_hero,
    render_soft_notice,
)


LEGACY_RULE_COLUMNS = {
    "abnormality",
    "cause",
    "positive_control_normal",
    "negative_control_band",
    "min_template",
    "max_template",
    "min_temp",
    "max_temp",
    "score",
    "suggestion",
}

V2_RULE_COLUMNS = {
    "rule_id",
    "abnormality",
    "band_pattern",
    "cause",
    "priority",
    "positive_control",
    "negative_control",
    "template_condition",
    "annealing_temp_condition",
    "text_hint",
    "required_fields",
}


def validate_rules_dataframe(rules_df):
    """同时兼容旧版 rules.csv 和新版规则表结构。"""
    result = {
        "ok": True,
        "schema_name": "unknown",
        "issues": [],
        "warnings": [],
    }

    columns = set(rules_df.columns)
    missing_legacy = sorted(LEGACY_RULE_COLUMNS - columns)
    missing_v2 = sorted(V2_RULE_COLUMNS - columns)

    if not missing_v2:
        result["schema_name"] = "v2"
    elif not missing_legacy:
        result["schema_name"] = "legacy"
    else:
        result["ok"] = False
        result["issues"].append(
            "规则表字段不匹配。"
            f"旧版缺少：{', '.join(missing_legacy)}；"
            f"新版缺少：{', '.join(missing_v2)}"
        )
        return result

    if rules_df.empty:
        result["ok"] = False
        result["issues"].append("rules.csv 为空")
        return result

    if result["schema_name"] == "v2":
        invalid_priority = pd.to_numeric(rules_df["priority"], errors="coerce").isna().sum()
        if invalid_priority:
            result["warnings"].append(f"存在 {invalid_priority} 条无法解析的 priority 值")
    else:
        invalid_score = pd.to_numeric(rules_df["score"], errors="coerce").isna().sum()
        if invalid_score:
            result["warnings"].append(f"存在 {invalid_score} 条无法解析的 score 值")

    return result


def get_self_check_items():
    """生成系统自检项。"""
    items = []

    try:
        rules_df = read_csv_with_fallback(RULES_PATH)
        validation = validate_rules_dataframe(rules_df)
        if validation["ok"]:
            items.append(("success", "规则文件（rules.csv）", f"读取正常，识别为 {validation['schema_name']} 结构，共 {len(rules_df)} 条规则"))
        else:
            items.append(("error", "规则文件（rules.csv）", "；".join(validation["issues"])))
    except Exception as exc:
        items.append(("error", "规则文件（rules.csv）", f"读取失败：{exc}"))

    if os.path.exists(DB_PATH):
        items.append(("success", "SQLite 数据库", f"连接文件可用：{DB_PATH}"))
    else:
        items.append(("warning", "SQLite 数据库", f"未找到数据库文件：{DB_PATH}"))

    if os.path.isdir(UPLOAD_DIR):
        items.append(("success", "上传目录", f"目录可用：{UPLOAD_DIR}"))
    else:
        items.append(("warning", "上传目录", f"未找到目录：{UPLOAD_DIR}"))

    api_key_exists = bool(os.getenv("BIGMODEL_API_KEY", "").strip())
    items.append(("success" if api_key_exists else "warning", "模型访问凭据", "已配置 BIGMODEL_API_KEY" if api_key_exists else "未配置 BIGMODEL_API_KEY"))
    return items


def render_self_check_items():
    """使用原生卡片布局渲染系统自检。"""
    items = get_self_check_items()
    cols = st.columns(2)
    for index, (level, title, detail) in enumerate(items):
        with cols[index % 2]:
            with st.container(border=True):
                st.markdown(f"**{title}**")
                if level == "success":
                    st.success(detail)
                elif level == "warning":
                    st.warning(detail)
                else:
                    st.error(detail)


def render_api_debug_panel():
    """渲染 API 调试信息面板。"""
    api_key_exists = bool(os.getenv("BIGMODEL_API_KEY", "").strip())
    base_url_env = os.getenv("BIGMODEL_BASE_URL", "").strip()
    base_url_exists = bool(base_url_env)
    base_url = base_url_env or BIGMODEL_DEFAULT_BASE_URL
    model = os.getenv("BIGMODEL_MODEL", BIGMODEL_MODEL)

    render_card_title("API 调试信息", "用于核验文本线索抽取是否实际调用模型接口，并查看最近一次接口调试记录。")
    render_soft_notice(
        "当前接口配置概览",
        f"BIGMODEL_API_KEY：{'已检测到' if api_key_exists else '未检测到'}；BIGMODEL_BASE_URL：{'已检测到' if base_url_exists else '未检测到'}。",
    )
    st.markdown(f"- 当前接口地址：{base_url}")
    st.markdown(f"- 当前模型标识：{model}")
    st.markdown("- 文本线索抽取策略：优先调用大模型接口，失败时自动回退本地规则。")

    last_api_debug = st.session_state.get("last_api_debug", {})
    if last_api_debug:
        st.markdown("#### 最近一次抽取记录")
        st.markdown(f"- 抽取方式：{last_api_debug.get('extractor_used', '未知')}")
        st.markdown(f"- API Key 掩码：{last_api_debug.get('api_key_masked', '-') or '-'}")
        st.markdown(f"- 失败原因摘要：{last_api_debug.get('fail_reason', '-') or '-'}")
        error_detail = (last_api_debug.get("error_detail", "") or "").strip()
        if error_detail:
            st.markdown(f"- 异常详情：{error_detail}")
    else:
        st.info("当前暂无最近一次接口调试记录。请先在“学生端”完成一次诊断，以生成抽取日志。")


def run_rules_library_check():
    """规则库检查，统一使用编码兼容读取。"""
    result = {"ok": True, "issues": [], "warnings": []}

    if not os.path.exists(RULES_PATH):
        result["ok"] = False
        result["issues"].append("rules.csv 不存在")
        return result

    try:
        rules_df = read_csv_with_fallback(RULES_PATH)
    except Exception as exc:
        result["ok"] = False
        result["issues"].append(f"rules.csv 读取失败：{exc}")
        return result

    validation = validate_rules_dataframe(rules_df)
    result["ok"] = validation["ok"]
    result["issues"].extend(validation["issues"])
    result["warnings"].extend(validation["warnings"])
    return result


def main():
    ensure_page_config("开发调试端控制台")
    init_access_state()
    if not st.session_state.get("dev_verified"):
        apply_common_styles(theme="dev")
        st.session_state["current_role"] = "home"
        render_page_hero(
            "开发调试端控制台",
            "当前页面需要先从首页开发调试入口完成访问码验证。",
            "开发调试端",
        )
        render_entry_guard("开发调试端")
        return

    init_database()
    apply_common_styles(theme="dev")
    st.session_state["current_role"] = "dev"
    render_page_hero(
        "开发调试端控制台",
        "集中查看系统状态、规则健康度与演示环境清理能力。",
        "开发调试端",
    )

    top_col_left, top_col_right = st.columns([1, 1])

    with top_col_left:
        with st.container(border=True):
            render_card_title("系统自检", "用于核验规则文件、数据库、上传目录及关键运行配置是否处于可用状态。")
            render_self_check_items()

    with top_col_right:
        with st.container(border=True):
            render_api_debug_panel()
            st.markdown("<div style='height: 1.2rem;'></div>", unsafe_allow_html=True)

    with st.container(border=True):
        render_card_title("规则库查看 / 校验", "先看表，再一键做必要字段与数据质量检查。")
        try:
            rules_df = read_csv_with_fallback(RULES_PATH)
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
