"""双击启动本机应用；安装版把个人数据保存在用户目录。"""
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parent
INSTALLED = (ROOT.parent / 'python/python.exe').is_file()
HOME = Path(os.getenv('LOCALAPPDATA', str(ROOT))) / 'BioLabReview' if INSTALLED else ROOT
RUNTIME = HOME / '.launcher'
HTTP = build_opener(ProxyHandler({}))


def python_path():
    choices = [ROOT.parent/'python/python.exe', ROOT/'.venv/Scripts/python.exe'] if os.name == 'nt' else [ROOT/'.venv/bin/python']
    return str(next((p for p in choices if p.is_file()), Path(sys.executable).with_name('python.exe') if os.name == 'nt' else Path(sys.executable)))


def server_command(python, port, app=None):
    command = [python, '-m', 'streamlit', 'run', str(app or ROOT/'app.py'), '--server.address', '127.0.0.1', '--server.port', str(port), '--server.headless', 'true', '--browser.gatherUsageStats', 'false']
    if INSTALLED:
        command += ['--secrets.files', str(HOME/'.streamlit/secrets.toml')]
    return command


def server_environment():
    env = os.environ.copy()
    if INSTALLED:
        (HOME/'data').mkdir(parents=True, exist_ok=True)
        (HOME/'uploads').mkdir(exist_ok=True)
        env.update(PCR_DIAGNOSIS_DB_PATH=str(HOME/'data/app.db'), PCR_DIAGNOSIS_UPLOAD_DIR=str(HOME/'uploads'), PCR_DIAGNOSIS_DEMO_MODE='0')
        env.pop('PYTHONHOME',None)
        env.pop('PYTHONPATH',None)
        env['PYTHONNOUSERSITE']='1'
    return env


def healthy(url):
    try:
        with HTTP.open(url+'/_stcore/health', timeout=1) as response:
            return response.status == 200 and response.read(32).strip() == b'ok'
    except (OSError, ValueError):
        return False


def free_port():
    for port in (8501,8502,8503,8504,8505,8514,8516,8517):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1',port))
                return port
            except OSError:
                continue
    raise RuntimeError('可用端口已占用，请先退出此前打开的系统后重试。')


def acquire_lock():
    RUNTIME.mkdir(parents=True,exist_ok=True)
    handle=(RUNTIME/'instance.lock').open('a+b')
    handle.seek(0,2)
    if handle.tell()==0:
        handle.write(b'0');handle.flush()
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return handle
    except OSError:
        handle.close()
        return None


def existing_url(timeout=45):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            state=json.loads((RUNTIME/'instance.json').read_text(encoding='utf-8'))
            port=state['port']
            if type(port) is int and 1024<=port<=65535:
                url=f'http://127.0.0.1:{port}'
                if state.get('ready') is True and healthy(url):return url
        except (OSError,ValueError,KeyError):pass
        time.sleep(0.3)
    return None


def stop_process(process):
    if process and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=3)


class DesktopApp:
    def __init__(self,window):
        import tkinter as tk
        from tkinter import ttk
        from branding import PRODUCT_NAME
        self.window=window;self.process=None;self.url=None
        self.closed=threading.Event();self.events=queue.Queue()
        window.title(PRODUCT_NAME);window.geometry('530x240');window.resizable(False,False)
        pane=ttk.Frame(window,padding=22);pane.pack(fill='both',expand=True)
        ttk.Label(pane,text=PRODUCT_NAME,font=('Microsoft YaHei',17,'bold')).pack(anchor='w')
        self.status=tk.StringVar(value='正在启动，请稍候……')
        ttk.Label(pane,textvariable=self.status,wraplength=480).pack(anchor='w',pady=(16,5))
        ttk.Label(pane,text='自动打开浏览器。使用时保留此窗口，结束后点击“退出系统”。',wraplength=480).pack(anchor='w')
        row=ttk.Frame(pane);row.pack(fill='x',pady=(18,0))
        self.open_button=ttk.Button(row,text='打开系统页面',command=self.open_page,state='disabled');self.open_button.pack(side='left')
        if INSTALLED:ttk.Button(row,text='首次使用配置',command=self.configure).pack(side='left',padx=10)
        ttk.Button(row,text='退出系统',command=self.close).pack(side='right')
        window.protocol('WM_DELETE_WINDOW',self.close)
        threading.Thread(target=self.start,daemon=True).start();window.after(150,self.poll)

    def publish(self,port,ready=False):
        (RUNTIME/'instance.json').write_text(json.dumps({'port':port,'ready':ready}),encoding='utf-8')

    def start(self):
        try:
            python=python_path()
            if not Path(python).is_file() or not (ROOT/'app.py').is_file():raise RuntimeError('未找到完整运行环境，请保留项目文件夹或重新安装。')
            port=free_port();self.publish(port)
            if self.closed.is_set():return
            with (RUNTIME/'service.log').open('ab',buffering=0) as log:
                self.process=subprocess.Popen(server_command(python,port),cwd=ROOT,env=server_environment(),stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            url=f'http://127.0.0.1:{port}';deadline=time.monotonic()+60
            while not self.closed.wait(0.3):
                if self.process.poll() is not None:raise RuntimeError('服务未能启动。详细信息见数据目录中的 .launcher/service.log。')
                if healthy(url):self.publish(port,True);self.events.put(('ready',url));return
                if time.monotonic()>deadline:raise RuntimeError('启动超过一分钟，请退出后重试。详细信息见 .launcher/service.log。')
            stop_process(self.process)
        except Exception as exc:
            stop_process(self.process);self.events.put(('error',str(exc)))

    def poll(self):
        if self.closed.is_set():return
        try:
            kind,value=self.events.get_nowait()
            if kind=='ready':
                self.url=value;self.status.set('系统已启动：'+value);self.open_button.configure(state='normal');self.open_page()
            else:self.status.set(value)
        except queue.Empty:pass
        if self.url and self.process and self.process.poll() is not None:
            self.status.set('服务已停止，请退出此窗口后重新启动。');self.open_button.configure(state='disabled');self.url=None
        self.window.after(300,self.poll)

    def open_page(self):
        if self.url:webbrowser.open(self.url)

    def configure(self):
        import tkinter as tk
        from tkinter import ttk,messagebox
        import toml
        dialog=tk.Toplevel(self.window);dialog.title('首次使用配置');dialog.geometry('530x320');dialog.transient(self.window);dialog.grab_set()
        pane=ttk.Frame(dialog,padding=20);pane.pack(fill='both',expand=True)
        path=HOME/'.streamlit/secrets.toml'
        values=toml.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        entries={}
        for key,label in [('DEEPSEEK_API_KEY','DeepSeek API Key（可留空，使用人工流程）'),('TEACHER_ACCESS_CODE','教师访问码（自己设定，保护教师入口）'),('DEV_ACCESS_CODE','调试访问码（可留空）')]:
            ttk.Label(pane,text=label).pack(anchor='w',pady=(6,0));entry=ttk.Entry(pane,show='*',width=66);entry.insert(0,values.get(key,''));entry.pack(fill='x');entries[key]=entry
        def save():
            values.update({key:entry.get().strip() for key,entry in entries.items()})
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(toml.dumps(values),encoding='utf-8')
            messagebox.showinfo('已保存','请退出系统后重新双击桌面图标，配置即可生效。',parent=dialog);dialog.destroy()
        ttk.Button(pane,text='保存配置',command=save).pack(pady=18)

    def close(self):
        from tkinter import messagebox
        if not messagebox.askyesno('退出系统','请先保存页面中尚未提交的内容。退出后本机服务将停止，是否继续？',parent=self.window):return
        self.closed.set();self.status.set('正在退出……');self.window.update_idletasks();stop_process(self.process);self.window.destroy()


def main():
    import tkinter as tk
    from tkinter import messagebox
    window=tk.Tk();window.withdraw();lock=acquire_lock()
    if not lock:
        url=existing_url()
        if url:webbrowser.open(url)
        else:messagebox.showinfo('生物实验智析助手','系统仍在启动或未正常退出，请检查已打开的启动窗口。',parent=window)
        window.destroy();return
    try:
        DesktopApp(window);window.deiconify();window.mainloop()
    finally:lock.close()


if __name__=='__main__':main()
