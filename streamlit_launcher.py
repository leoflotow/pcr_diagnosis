import os
import subprocess
import sys

repo = r"E:\12-软件安装包\实验复盘智能助手\pcr_diagnosis"
py = os.path.join(repo, ".venv", "Scripts", "python.exe")
out_path = os.path.join(repo, "streamlit.out.log")
err_path = os.path.join(repo, "streamlit.err.log")
with open(out_path, "ab", buffering=0) as out, open(err_path, "ab", buffering=0) as err:
    proc = subprocess.Popen(
        [py, "-m", "streamlit", "run", "app.py", "--server.port", "8501", "--server.headless", "true"],
        cwd=repo,
        stdout=out,
        stderr=err,
        stdin=subprocess.DEVNULL,
    )
    sys.exit(proc.wait())
