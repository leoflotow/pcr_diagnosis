"""文字和图片共用的 DeepSeek 配置，不接受其他模型或服务商覆盖。"""

import os

MODEL = "deepseek-flash"
BASE_URL = "https://api.deepseek.com"
TEXT_TIMEOUT = 8
VISION_TIMEOUT = 30


def setting(name, default=""):
    if name in os.environ:
        return os.environ[name].strip()
    try:
        import streamlit as st
        return str(st.secrets.get(name, default)).strip()
    except Exception:
        return default


def api_key():
    # 隔离流程验证环境始终不发送在线请求。
    if os.getenv("PCR_DIAGNOSIS_DEMO_MODE") == "1":
        return ""
    return setting("DEEPSEEK_API_KEY")


def vision_enabled():
    return setting("DEEPSEEK_VISION_ENABLED", "true").lower() not in {"0", "false", "no", "off"}


def request_options(max_tokens=1000):
    # 明确关闭默认思考模式，限制课堂等待时间及计费输出长度。
    return {"model": MODEL, "max_tokens": max_tokens,
            "extra_body": {"thinking": {"type": "disabled"}}}
