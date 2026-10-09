"""调试权限隔离与规则维护验证；只写临时规则副本和临时数据库。"""
from pathlib import Path
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from teaching_platform.api import create_app
from teaching_platform.config import ROOT


class DeveloperConsoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.rule_file = root / 'rules.csv'
        shutil.copy2(ROOT / 'rules.csv', self.rule_file)
        self.env = patch.dict(os.environ, {'BIO_CONFIG_DISABLED': '1', 'PYTHON_DOTENV_DISABLED': '1',
            'DEV_ACCESS_CODE': 'isolated-dev', 'TEACHER_ACCESS_CODE': 'isolated-teacher',
            'DEEPSEEK_API_KEY': 'isolated-fake-key-never-send'})
        self.env.start()
        self.client = TestClient(create_app(root / 'records.db', root / 'images', dev_rules_path=self.rule_file))
        self.client.__enter__()
        self.client.headers['X-Teaching-Request'] = '1'

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        self.tmp.cleanup()

    def login(self, role='dev', code='isolated-dev'):
        return self.client.post('/api/v1/session', json={'role': role, 'code': code})

    def test_developer_permission_is_independent_and_revoked_on_logout(self):
        self.assertEqual(self.client.get('/api/v1/dev/status').status_code, 401)
        self.assertEqual(self.login(code='wrong').status_code, 401)
        self.assertEqual(self.login('teacher', 'isolated-teacher').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/dev/rules').status_code, 403)
        self.assertEqual(self.login().status_code, 200)
        response = self.client.get('/api/v1/dev/status')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('isolated-fake-key', response.text)
        self.assertEqual(response.json()['model'], 'deepseek-flash')
        self.assertEqual(self.client.get('/api/v1/teacher/cases').status_code, 403)
        self.assertEqual(self.client.post('/api/v1/cases', json={'request_id': 'x'*32,
            'abnormality': '无条带', 'student_initial_hypothesis': '待核对'}).status_code, 400)
        self.assertEqual(self.client.post('/api/v1/logout', json={}).status_code, 200)
        self.assertEqual(self.client.get('/api/v1/dev/status').status_code, 401)

    def test_rule_check_backup_and_stale_version(self):
        self.login()
        rules = self.client.get('/api/v1/dev/rules').json()
        row = {k: v for k, v in rules['rows'][0].items() if k != 'rule_id'}
        body = {'rule': row, 'version': rules['version']}
        before = self.rule_file.read_bytes()
        self.assertEqual(self.client.post('/api/v1/dev/rules/check', json=body).status_code, 400)
        row['cause'] = '隔离规则检查候选'
        row['enabled'] = 0
        self.assertEqual(self.client.post('/api/v1/dev/rules/check', json=body).status_code, 200)
        self.assertEqual(self.rule_file.read_bytes(), before)
        self.assertEqual(self.client.post('/api/v1/dev/rules', json=body).status_code, 400)
        added = self.client.post('/api/v1/dev/rules', json={**body, 'confirmed': True})
        self.assertEqual(added.status_code, 200, added.text)
        backups = list(self.rule_file.parent.glob('.rule-backups/*.bak'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        self.assertEqual(self.client.post('/api/v1/dev/rules', json={**body, 'confirmed': True}).status_code, 400)

    def test_invalid_rule_values_do_not_write(self):
        self.login()
        rules = self.client.get('/api/v1/dev/rules').json()
        row = {k: v for k, v in rules['rows'][0].items() if k != 'rule_id'}
        row.update(cause='隔离候选', base_score='nan')
        before = self.rule_file.read_bytes()
        response = self.client.post('/api/v1/dev/rules', json={
            'rule': row, 'version': rules['version'], 'confirmed': True})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(before, self.rule_file.read_bytes())


if __name__ == '__main__':
    unittest.main()
