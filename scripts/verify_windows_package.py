"""验证公开安装包、隔离安装及更新；不读取真实配置或教学数据。"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import struct
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    payload=ROOT/'build/windows/payload.zip'
    with zipfile.ZipFile(payload) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        for name,digest in manifest.items():
            assert '..' not in Path(name).parts and not name.startswith('/')
            if name.startswith('app/'):
                relative=name[4:]
                assert not relative.startswith(('data/','uploads/','.venv/','.git/','.launcher/','frontend/node_modules/'))
                assert Path(relative).name not in {'.env','secrets.toml'}
            assert hashlib.sha256(archive.read(name)).hexdigest()==digest,name
        for required in ['app/platform_server.py','app/experiment_business.py','app/frontend/dist/index.html','app/knowledge/network.json','app/teaching_platform/api.py']:
            assert required in manifest,required
        assert archive.read('app/desktop/uninstall.ps1').startswith(b'\xef\xbb\xbf')
    qa=ROOT/'build/qa/windows';qa.mkdir(parents=True,exist_ok=True)
    setup=ROOT/'dist/BioLabReview-Unified-Setup.exe'
    executable=setup.read_bytes();offset=executable.rfind(b'MSCF')
    assert offset>0,'安装包缺少 CAB'
    length=struct.unpack_from('<I',executable,offset+8)[0]
    cabinet=qa/'setup.cab';cabinet.write_bytes(executable[offset:offset+length])
    extracted=qa/'exe-content';extracted.mkdir(exist_ok=True)
    subprocess.run(['expand.exe','-F:*',str(cabinet),str(extracted)],check=True,capture_output=True,timeout=60)
    assert hashlib.sha256((extracted/'payload.zip').read_bytes()).digest()==hashlib.sha256(payload.read_bytes()).digest()
    assert (extracted/'install.ps1').read_bytes()==(ROOT/'build/windows/install.ps1').read_bytes()
    installed=qa/'installed'
    if '--artifact-only' in sys.argv:
        # 仅界面文案变化时，复用已实际验证的相同安装器和业务环境。
        proof=json.loads((qa/'verification.json').read_text(encoding='utf-8'))
        assert proof['initial_and_updated_runtime'] and proof['data_preserved']
        with zipfile.ZipFile(payload) as archive:
            for name,digest in manifest.items():
                if name.startswith('app/frontend/dist/'):
                    assert archive.read(name)==(ROOT/name[4:]).read_bytes(),name
                elif name.startswith('python/') or name.endswith(('.py','.ps1','.vbs')):
                    assert hashlib.sha256((installed/name).read_bytes()).hexdigest()==digest,name
        proof.update(final_payload_sha256=hashlib.sha256(payload.read_bytes()).hexdigest(),same_tested_installer_and_business=True,frontend_matches_browser_tested_build=True)
        (qa/'verification.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
        print('最终 EXE 文件一致；安装器、Python 与业务逐文件等同已验证版本，新网页等同浏览器验收版本。',flush=True)
        return
    personal=qa/'personal';personal.mkdir(exist_ok=True)
    sentinel=personal/'保留记录.txt';sentinel.write_text('更新必须保留',encoding='utf-8')
    def install():
        command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'build/windows/install.ps1'),'-Destination',str(installed),'-NoShortcut','-NoStart']
        subprocess.run(command,check=True,timeout=180,capture_output=True)
    install()
    python=installed/'python/python.exe';app=installed/'app'
    env=os.environ.copy()
    env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
    (qa/'tmp').mkdir(exist_ok=True)
    env.update(BIO_CONFIG_DISABLED='1',PYTHONNOUSERSITE='1',PYTHON_DOTENV_DISABLED='1',DEEPSEEK_API_KEY='',TEACHER_ACCESS_CODE='package-qa-only',LOCALAPPDATA=str(personal),TEMP=str(qa/'tmp'),TMP=str(qa/'tmp'))
    script="""
import json,subprocess,sys,time
from pathlib import Path
from urllib.request import ProxyHandler,build_opener
sys.path.insert(0,str(Path.cwd()))
import ssl,tkinter,fastapi,uvicorn,PIL,qrcode,streamlit,pandas,openai
assert tkinter.Tcl().eval('info patchlevel')
import streamlit_launcher as launcher
assert launcher.INSTALLED
from teaching_platform.config import ROOT
from experiment_business import build_primary_diagnosis_from_rules_v2
http=build_opener(ProxyHandler({}))
for iteration in range(2):
    command=launcher.server_command(sys.executable,8518)
    assert command[command.index('--host')+1]=='127.0.0.1'
    environment=launcher.server_environment()
    with open(Path.cwd().parent/'runtime-check.log','ab') as log:
        process=subprocess.Popen(command,env=environment,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                assert process.poll() is None,'服务提前退出'
                if launcher.healthy('http://127.0.0.1:8518'):break
                time.sleep(.2)
            else:raise AssertionError('服务未就绪')
            with http.open('http://127.0.0.1:8518/api/v1/knowledge?q=pyruvate') as response:
                assert json.load(response)['total']>0
            with http.open('http://127.0.0.1:8518/') as response:
                assert b'<div id="app">' in response.read()
            print('包内统一服务启动、知识查询、网页返回通过：'+str(iteration+1),flush=True)
        finally:launcher.stop_process(process)
# 原版页面仍可运行，配置仅指向空的隔离文件。
import streamlit.config as config
empty=Path.cwd().parent/'empty-secrets.toml';empty.write_text('',encoding='utf-8')
config.set_option('secrets.files',[str(empty)])
import os
os.environ.update(PCR_DIAGNOSIS_DB_PATH=str(launcher.HOME/'data/app.db'),PCR_DIAGNOSIS_UPLOAD_DIR=str(launcher.HOME/'uploads'))
from streamlit.testing.v1 import AppTest
for name in ['app.py','pages/1_学生端.py','pages/2_教师端.py']:
    page=AppTest.from_file(name,default_timeout=30)
    if '教师端' in name:page.session_state['teacher_verified']=True
    page.run();assert not page.exception,[e.message for e in page.exception]
print('旧版三页运行检查通过。',flush=True)
"""
    result=subprocess.run([str(python),'-X','utf8','-c',script],cwd=app,env=env,timeout=150,capture_output=True,encoding='utf-8')
    print(result.stdout,flush=True)
    if result.returncode:
        print(result.stderr);raise RuntimeError('隔离包运行验证失败')
    classroom=personal/'BioLabReview/data/app.db'
    before=hashlib.sha256(classroom.read_bytes()).hexdigest()
    install()
    assert sentinel.read_text(encoding='utf-8')=='更新必须保留'
    assert hashlib.sha256(classroom.read_bytes()).hexdigest()==before
    assert list(qa.glob('installed-previous-*'))
    result=subprocess.run([str(python),'-X','utf8','-c',script],cwd=app,env=env,timeout=150,capture_output=True,encoding='utf-8')
    assert result.returncode==0,result.stderr
    (qa/'verification.json').write_text(json.dumps({'manifest_files':len(manifest),'payload_sha256':hashlib.sha256(payload.read_bytes()).hexdigest(),'initial_and_updated_runtime':True,'data_preserved':True,'real_data_used':False,'model_calls':0},indent=2),encoding='utf-8')
    print('安装、更新保留数据、退出及再次启动验证通过；未运行快捷方式注册、未修改用户正式安装。',flush=True)


if __name__=='__main__':main()
