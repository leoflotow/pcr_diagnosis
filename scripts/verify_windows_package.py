"""检查白名单 ZIP 和隔离安装目录；不运行作者课堂环境或读取其配置。"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    payload=ROOT/"build/windows/payload.zip"
    with zipfile.ZipFile(payload) as archive:
        manifest=json.loads(archive.read("manifest.json"))
        for name,expected in manifest.items():
            assert ".." not in Path(name).parts and not name.startswith("/")
            if name.startswith("app/"):
                relative=name[4:]
                assert not relative.startswith(("data/","uploads/",".venv/",".git/",".launcher/")),relative
                assert Path(relative).name not in {".env","secrets.toml"},relative
            assert hashlib.sha256(archive.read(name)).hexdigest()==expected,name
        assert archive.read("app/streamlit_launcher.py")== (ROOT/"streamlit_launcher.py").read_bytes()
        assert archive.read("app/desktop/uninstall.ps1").startswith(b"\xef\xbb\xbf")
        print(f"离线包校验通过：{len(manifest)} 个文件；启动器与当前代码一致；未打包个人数据及密钥。",flush=True)
    installed=ROOT/"docs/competition/qa/windows-install-check"
    python=installed/"python/python.exe"
    if not python.is_file():raise RuntimeError("请先把离线包安装到独立验证目录。")
    env=os.environ.copy()
    env.pop("PYTHONHOME",None);env.pop("PYTHONPATH",None)
    qa=ROOT/"docs/competition/qa/windows-runtime-check";qa.mkdir(exist_ok=True)
    temporary=qa/"tmp";temporary.mkdir(exist_ok=True)
    secret=qa/"empty-secrets.toml";secret.write_text('DEEPSEEK_API_KEY=""\n',encoding="utf-8")
    env.update(PYTHONNOUSERSITE="1",PYTHON_DOTENV_DISABLED="1",DEEPSEEK_API_KEY="",TEACHER_ACCESS_CODE="qa-only",DEV_ACCESS_CODE="qa-only",PCR_DIAGNOSIS_DB_PATH=str(qa/"app.db"),PCR_DIAGNOSIS_UPLOAD_DIR=str(qa/"uploads"),PCR_DIAGNOSIS_DEMO_MODE="0")
    env.update(TEMP=str(temporary),TMP=str(temporary))
    script=f'''
import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import ssl, tkinter, pandas, PIL, openai, streamlit
import streamlit.config as config
config.set_option("secrets.files",[{str(secret)!r}])
from streamlit.testing.v1 import AppTest
assert tkinter.Tcl().eval("info patchlevel")
import streamlit_launcher as launcher
assert launcher.INSTALLED
for name in ["app.py","pages/1_学生端.py","pages/2_教师端.py"]:
    app=AppTest.from_file(name,default_timeout=25)
    if "教师端" in name:app.session_state["teacher_verified"]=True
    app.run()
    assert not app.exception,[e.message for e in app.exception]
    print("安装版页面通过："+name,flush=True)
print("独立 Python、SSL、Tk、数据处理与模型客户端导入通过。",flush=True)
import subprocess,time
command=launcher.server_command(sys.executable,8518)
command[command.index("--secrets.files")+1]={str(secret)!r}
with open({str(qa/'service.log')!r},"ab") as log:
    process=subprocess.Popen(command,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
try:
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
        assert process.poll() is None,"安装版服务提前退出"
        if launcher.healthy("http://127.0.0.1:8518"):break
        time.sleep(.3)
    else:raise AssertionError("安装版服务未就绪")
    print("包内 Python 实际本机服务就绪检查通过。",flush=True)
finally:launcher.stop_process(process)
'''
    result=subprocess.run([str(python),"-X","utf8","-c",script],cwd=installed/"app",env=env,timeout=120,capture_output=True,encoding="utf-8")
    print(result.stdout,flush=True)
    if result.returncode or "Traceback" in result.stderr:
        print(result.stderr)
        raise RuntimeError("独立运行环境验证失败。")
    print("全部使用包内 Python 与隔离数据，外部模型调用为零。")


if __name__=="__main__":main()
