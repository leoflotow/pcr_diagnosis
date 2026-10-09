"""受限调试控制台；只返回配置状态与调用元数据，不返回密钥或学生原文。"""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import math
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading

import pandas as pd
import ai_config
from diagnosis_rule_engine_v2 import BASE_RULE_COLUMNS, MATCH_FIELDS
from .config import ROOT


class DeveloperTools:
    def __init__(self, service, rules_path=None):
        self.service = service
        self.path = Path(rules_path or ROOT / 'rules.csv')
        self.lock = threading.RLock()

    def rules(self):
        with self.lock:
            raw = self.path.read_bytes()
            for encoding in ('utf-8-sig', 'gb18030'):
                try:
                    from io import StringIO
                    frame = pd.read_csv(StringIO(raw.decode(encoding)), keep_default_na=False)
                    break
                except UnicodeError:
                    continue
            else:
                raise ValueError('规则文件编码无法识别。')
            issues = []
            missing = sorted(set(BASE_RULE_COLUMNS) - set(frame.columns))
            if missing:
                issues.append('缺少字段：' + '、'.join(missing))
            if frame.empty:
                issues.append('规则文件为空。')
            if not missing:
                if frame['rule_id'].duplicated().any():
                    issues.append('存在重复规则编号。')
                for column in ('priority', 'base_score', 'enabled'):
                    values = pd.to_numeric(frame[column], errors='coerce')
                    if values.isna().any() or not all(math.isfinite(float(v)) for v in values):
                        issues.append(column + ' 存在无效数值。')
            return {'version': hashlib.sha256(raw).hexdigest(), 'columns': list(frame.columns),
                    'rows': frame.to_dict('records'), 'issues': issues, 'ok': not issues}

    def status(self):
        checks = []
        try:
            rules = self.rules()
            checks.append({'name': '规则文件', 'ok': rules['ok'],
                           'detail': '；'.join(rules['issues']) or f"读取正常，共 {len(rules['rows'])} 条规则"})
        except (OSError, ValueError, pd.errors.ParserError):
            checks.append({'name': '规则文件', 'ok': False, 'detail': '文件缺失或无法读取，请检查规则文件。'})
        calls = []
        try:
            uri = Path(self.service.db).resolve().as_uri() + '?mode=ro'
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                connection.execute('SELECT 1 FROM diagnosis_records LIMIT 1').fetchone()
                connection.row_factory = sqlite3.Row
                calls = [dict(row) for row in connection.execute('''
                    SELECT g.id,g.record_id,g.created_at,g.status,g.model_requested,g.usage_json
                    FROM gel_observation_runs g JOIN diagnosis_records r ON r.id=g.record_id
                    WHERE coalesce(r.data_origin,'') NOT IN ('模拟演示','规则回归')
                    ORDER BY g.id DESC LIMIT 20''')]
            checks.append({'name': 'SQLite 数据库', 'ok': True, 'detail': '只读连接正常'})
        except sqlite3.Error:
            checks.append({'name': 'SQLite 数据库', 'ok': False, 'detail': '数据库或调用记录暂不可读。'})
        checks.append({'name': '上传目录', 'ok': self.service.uploads.is_dir(),
                       'detail': '目录可用' if self.service.uploads.is_dir() else '目录尚未创建'})
        configured = bool(ai_config.api_key())
        checks.append({'name': '模型访问凭据', 'ok': configured,
                       'detail': '已配置 DEEPSEEK_API_KEY' if configured else '未配置，使用本地与人工流程'})
        # 只保留使用量，不将接口原始响应或错误堆栈送往浏览器。
        import json
        for call in calls:
            try:
                usage = json.loads(call.pop('usage_json') or '{}')
                total = usage.get('total_tokens') if isinstance(usage, dict) else None
                call['total_tokens'] = total if isinstance(total, (int, float)) else None
            except (ValueError, TypeError):
                call['total_tokens'] = None
        return {'checks': checks, 'model': ai_config.MODEL, 'base_url': ai_config.BASE_URL,
                'key_configured': configured, 'vision_enabled': ai_config.vision_enabled(),
                'text_timeout': ai_config.TEXT_TIMEOUT, 'vision_timeout': ai_config.VISION_TIMEOUT,
                'calls': calls}

    def prepare(self, payload, version):
        current = self.rules()
        if current['version'] != version:
            raise ValueError('规则库已变化，请刷新后重新检查。')
        if not current['ok']:
            raise ValueError('现有规则库校验未通过，不能追加规则。')
        if not isinstance(payload, dict) or set(payload) - (set(current['columns']) - {'rule_id'}):
            raise ValueError('规则字段无效，规则编号由系统生成。')
        row = {column: str(payload.get(column, '')).strip() for column in current['columns']}
        if any(len(value) > 2000 for value in row.values()):
            raise ValueError('规则字段过长。')
        for field in ('abnormality', 'cause', 'evidence_text', 'suggestion'):
            if not row[field]:
                raise ValueError('请完整填写实验现象、原因、证据描述和建议措施。')
        for field, upper in (('priority', 1000), ('base_score', 100), ('enabled', 1)):
            try:
                value = float(row[field])
                if not math.isfinite(value) or not 0 <= value <= upper:
                    raise ValueError()
                if field != 'base_score' and not value.is_integer():
                    raise ValueError()
                row[field] = int(value) if field != 'base_score' else value
            except ValueError:
                raise ValueError(f'{field} 数值无效。') from None
        conditions = MATCH_FIELDS + ['text_hint', 'required_fields']
        if row['required_fields'].lower() == 'any':
            row['required_fields'] = ''
        if row['required_fields'].lower() not in ('', 'any'):
            if set(row['required_fields'].split('|')) - set(MATCH_FIELDS + ['text_hint']):
                raise ValueError('必需证据字段包含未知字段，请使用竖线分隔标准字段名。')
        normalize = lambda value: str(value).strip() or 'any'
        warnings = []
        for old in current['rows']:
            if all(normalize(old.get(k, '')) == normalize(row[k]) for k in conditions):
                if str(old['cause']).strip() == row['cause']:
                    raise ValueError('已有相同条件和原因的规则，不能重复添加。')
                warnings.append(f"与 {old['rule_id']} 的匹配条件相同，原因不同，请核对判断依据。")
        identifiers = [int(str(r['rule_id'])[1:]) for r in current['rows']
                       if str(r['rule_id']).startswith('R') and str(r['rule_id'])[1:].isdigit()]
        row['rule_id'] = f'R{max(identifiers, default=0) + 1:03d}'
        return current, row, warnings

    def add(self, payload, version, confirmed):
        if confirmed is not True:
            raise ValueError('请先检查规则并确认保存。')
        with self.lock:
            current, row, warnings = self.prepare(payload, version)
            backup_dir = self.path.parent / '.rule-backups'
            backup_dir.mkdir(exist_ok=True)
            backup = backup_dir / (self.path.name + '.' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.bak')
            shutil.copy2(self.path, backup)
            descriptor, temporary = tempfile.mkstemp(prefix='.rules-', suffix='.tmp', dir=self.path.parent)
            os.close(descriptor)
            try:
                pd.DataFrame(current['rows'] + [row], columns=current['columns']).to_csv(temporary, index=False, encoding='utf-8-sig')
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return {'id': row['rule_id'], 'warnings': warnings, 'backup_created': True}
