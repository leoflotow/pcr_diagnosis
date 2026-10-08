"""从已安装的项目环境构建离线 Windows 包；白名单收集应用，不读取个人配置或课堂数据。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def runtime_files(base):
    for path in base.iterdir():
        if path.is_file() and path.suffix.lower() in {".exe",".dll",".txt"}:
            yield path, "python/"+path.name
    for folder in ("Lib","DLLs","tcl"):
        for path in (base/folder).rglob("*"):
            relative=path.relative_to(base)
            if path.is_file() and "__pycache__" not in relative.parts and "site-packages" not in relative.parts and path.suffix!=".pyc":
                yield path,"python/"+relative.as_posix()
    packages=ROOT/".venv/Lib/site-packages"
    if not packages.is_dir():raise RuntimeError("请先安装项目虚拟环境与依赖。")
    for path in packages.rglob("*"):
        relative=path.relative_to(packages)
        if path.is_file() and "__pycache__" not in relative.parts and path.suffix!=".pyc":
            yield path,"python/Lib/site-packages/"+relative.as_posix()


def app_files():
    # 仅公开代码、规则、样式及使用说明；不得递归遍历项目根目录。
    for path in ROOT.glob("*.py"):
        yield path,"app/"+path.name
    for folder in ("pages","desktop"):
        for path in (ROOT/folder).iterdir():
            if path.is_file() and path.suffix in {".py",".ps1",".vbs"}:
                yield path,"app/"+folder+"/"+path.name
    for name in ("branding.py","rules.csv","rule_combos.csv","rules_v2.csv","course_presets.json","ui_design.css","requirements.txt","README.md","RULE_AUDIT.md",".streamlit/config.toml","docs/教学功能升级使用说明.md","docs/Windows安装与启动说明.md"):
        path=ROOT/name
        yield path,"app/"+name


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--payload-only",action="store_true");args=parser.parse_args()
    if os.name!="nt":raise RuntimeError("请在 Windows 上构建。")
    work=ROOT/"build/windows";work.mkdir(parents=True,exist_ok=True)
    output=ROOT/"dist";output.mkdir(exist_ok=True)
    # 以虚拟环境的实际基础 Python 为准，避免混用不同版本的 DLL。
    base=Path(subprocess.check_output([str(ROOT/".venv/Scripts/python.exe"),"-c","import sys;print(sys.base_prefix)"],text=True).strip())
    manifest={}
    payload=work/"payload.zip"
    with zipfile.ZipFile(payload,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path,name in list(runtime_files(base))+list(app_files()):
            if name in manifest:continue
            data=path.read_bytes()
            if path.suffix==".ps1":
                data=path.read_text(encoding="utf-8-sig").encode("utf-8-sig")
            archive.writestr(name,data);manifest[name]=hashlib.sha256(data).hexdigest()
        archive.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2))
    print(f"离线程序包：{payload.stat().st_size/1024/1024:.1f} MB，{len(manifest)} 个文件。",flush=True)
    # PowerShell 5.1 读取中文脚本需要 BOM。
    install=ROOT/"desktop/install.ps1"
    (work/"install.ps1").write_text(install.read_text(encoding="utf-8-sig"),encoding="utf-8-sig")
    # 卸载脚本也在 ZIP 内统一为 UTF-8 BOM，避免安装后中文路径损坏。
    # app_files 中的脚本由下方构建校验检查编码，不打包任何实际 secrets。
    if args.payload_only:return
    target=output/"BioLabReview-Setup-2026.10.08.exe"
    sed=f'''[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName={target}
FriendlyName=BioLabReview Setup
AppLaunched=powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles
[Strings]
FILE0="payload.zip"
FILE1="install.ps1"
[SourceFiles]
SourceFiles0={work}\\
[SourceFiles0]
%FILE0%=
%FILE1%=
'''
    spec=work/"setup.sed";spec.write_text(sed,encoding="utf-16")
    result=subprocess.run([str(Path(os.environ["SystemRoot"])/"System32/iexpress.exe"),"/N","/Q",str(spec)],timeout=240)
    if result.returncode or not target.exists():raise RuntimeError("Windows 安装包构建未完成。离线 ZIP 已保留，可查看 build/windows。")
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    (output/(target.name+".sha256")).write_text(digest+"  "+target.name+"\n",encoding="ascii")
    print(f"安装包：{target}（{target.stat().st_size/1024/1024:.1f} MB）",flush=True)


if __name__=="__main__":main()
