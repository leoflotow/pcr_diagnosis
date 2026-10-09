"""读取个人配置，测试可彻底关闭文件读取；不依赖 Streamlit。"""
import os
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def setting(name, default=""):
    if name in os.environ:
        return os.environ[name].strip()
    if os.getenv("BIO_CONFIG_DISABLED") == "1":
        return default
    path = Path(os.getenv("BIO_SECRETS_PATH", str(ROOT / '.streamlit/secrets.toml')))
    if path.is_file():
        try:
            value = tomllib.loads(path.read_text(encoding='utf-8-sig')).get(name, default)
            return str(value).strip()
        except (ValueError, OSError):
            pass
    return default


def initialize_environment():
    if os.getenv('BIO_CONFIG_DISABLED') != '1':
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env', override=False)


def brand():
    from branding import PRODUCT_NAME, PRODUCT_SUBTITLE, KNOWLEDGE_MODULE_NAME, KNOWLEDGE_MODULE_DESCRIPTION, EXPERIMENT_MODULE_NAME, EXPERIMENT_MODULE_DESCRIPTION
    return {'name': PRODUCT_NAME,
            'subtitle': PRODUCT_SUBTITLE,
            'modules': {
                'knowledge': {'name': KNOWLEDGE_MODULE_NAME, 'description': KNOWLEDGE_MODULE_DESCRIPTION},
                'experiment': {'name': EXPERIMENT_MODULE_NAME, 'description': EXPERIMENT_MODULE_DESCRIPTION}}}
