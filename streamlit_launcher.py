import os
import subprocess
import sys
from pathlib import Path

repo = str(Path(__file__).resolve().parent)
venv_python = Path(repo) / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
py = str(venv_python) if venv_python.exists() else sys.executable
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
