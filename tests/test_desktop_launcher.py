"""启动器的端口、环境隔离与单实例检查，不读取课堂数据。"""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import streamlit_launcher as launcher


class DesktopLauncherTests(unittest.TestCase):
    def test_command_is_local_and_accepts_paths_with_spaces(self):
        with patch.object(launcher,"INSTALLED",False):
            command=launcher.server_command("C:/Test Space/python.exe",8502,Path("C:/Test Space/app.py"))
        self.assertEqual(command[0],"C:/Test Space/python.exe")
        self.assertIn("127.0.0.1",command)
        self.assertIn("8502",command)
        self.assertIn("C:\\Test Space\\app.py",command)

    def test_installed_environment_preserves_existing_classroom_files(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(launcher,"HOME",Path(directory)),patch.object(launcher,"INSTALLED",True):
            with patch.dict("os.environ",{"PYTHONHOME":"wrong","PYTHONPATH":"wrong","DEEPSEEK_API_KEY":"key-not-real"}):
                env=launcher.server_environment()
            self.assertNotIn("PYTHONHOME",env)
            self.assertNotIn("PYTHONPATH",env)
            self.assertEqual(env["DEEPSEEK_API_KEY"],"key-not-real")
            self.assertEqual(env["PCR_DIAGNOSIS_DB_PATH"],str(Path(directory)/"data/app.db"))
            self.assertFalse((Path(directory)/"data/app.db").exists())
            command=launcher.server_command("python.exe",8501)
            self.assertIn(str(Path(directory)/".streamlit/secrets.toml"),command)
            self.assertIn('--secrets-path',command)

    def test_single_instance_lock_releases(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(launcher,"RUNTIME",Path(directory)):
            lock=launcher.acquire_lock()
            self.assertIsNotNone(lock)
            self.assertIsNone(launcher.acquire_lock())
            lock.close()
            again=launcher.acquire_lock()
            self.assertIsNotNone(again)
            again.close()

    def test_unified_web_is_local_unless_lan_is_explicit(self):
        local=launcher.server_command('python.exe',8501)
        self.assertIn('127.0.0.1',local);self.assertTrue(any('platform_server.py' in p for p in local))
        self.assertNotIn('streamlit',local)
        self.assertIn('0.0.0.0',launcher.server_command('python.exe',8501,lan=True))

    def test_reopen_only_ready_local_service(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(launcher,"RUNTIME",Path(directory)),patch.object(launcher,"healthy",return_value=True):
            state=Path(directory)/"instance.json"
            state.write_text(json.dumps({"port":8501,"ready":True}))
            self.assertEqual(launcher.existing_url(.1),"http://127.0.0.1:8501")
            state.write_text(json.dumps({"port":"https://elsewhere","ready":True}))
            self.assertIsNone(launcher.existing_url(.1))


if __name__=="__main__":unittest.main()
