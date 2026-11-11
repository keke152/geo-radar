"""Enable per-user auto-start and supervise the local HTTP service."""
import argparse,json,os,socket,subprocess,sys,time,webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import build_opener,ProxyHandler
from desktop_service import STOP, install_autostart, supervisor_running, launch_login_task

ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:8020'
urlopen=build_opener(ProxyHandler({})).open
PREFER_BROWSER=False

def open_workspace():
 from client_window import open_client
 if not PREFER_BROWSER and open_client():return
 webbrowser.open(URL+'/#overview')

def spawn(logs):
 if os.name=='nt':
  if launch_login_task():return None
  executable=Path(sys.executable).with_name('pythonw.exe')
  if not executable.is_file():raise RuntimeError('未找到pythonw.exe，请修复Python安装；也可手动运行python launcher.py')
  # Explorer owns this process, outside the command runner's process lifetime.
  # Paths are environment data; the PowerShell program is a fixed literal.
  script="$ErrorActionPreference='Stop'; $desktop=New-Object -ComObject Shell.Application; $desktop.ShellExecute($env:AI_GEO_PYTHONW, ('\"' + (Join-Path $env:AI_GEO_PROJECT 'desktop_service.py') + '\" --run'), $env:AI_GEO_PROJECT, 'open', 0)"
  result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],env={**os.environ,'AI_GEO_PYTHONW':str(executable),'AI_GEO_PROJECT':str(ROOT)},stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
  if result.returncode:raise RuntimeError('Windows桌面后台启动失败；请手动运行python launcher.py并查看运行日志')
  return None
 with (logs/'startup.log').open('ab') as output:
  return subprocess.Popen([sys.executable,str(ROOT/'desktop_service.py'),'--run'],cwd=str(ROOT),stdin=subprocess.DEVNULL,stdout=output,stderr=output,close_fds=True,start_new_session=True)

def healthy():
 try:
  with urlopen(URL+'/api/health',timeout=1) as response:data=json.load(response)
  return data.get('service')=='ai-geo-workspace' or (data.get('status')=='ok' and data.get('scheduler_timezone')=='Asia/Shanghai' and isinstance(data.get('queue'),dict))
 except (OSError,ValueError,URLError):return False

def start(open_browser=True,timeout=35):
 # Install once on each normal start so moving the project updates the shortcut.
 # Failure to enable login startup must not prevent using the workspace today.
 warning=''
 try:automatic=install_autostart()
 except Exception:
  automatic=False;warning='本机后台可启动，但登录自动启动设置失败；请查看启动文件夹权限。'
 STOP.unlink(missing_ok=True)
 if healthy() and supervisor_running():
  if open_browser:open_workspace()
  return {'status':'already_running','url':URL,'auto_start':automatic,'warning':warning}
 # Load only local runtime configuration; never log environment variables or keys.
 from config import HOME
 logs=HOME/'logs';logs.mkdir(parents=True,exist_ok=True)
 lock=HOME/'desktop-start.lock'
 try:descriptor=os.open(str(lock),os.O_CREAT|os.O_EXCL|os.O_WRONLY)
 except FileExistsError:
  if time.time()-lock.stat().st_mtime>90:lock.unlink();return start(open_browser,timeout)
  deadline=time.monotonic()+timeout
  while time.monotonic()<deadline:
   if healthy() and supervisor_running():
    if open_browser:open_workspace()
    return {'status':'already_starting','url':URL,'auto_start':automatic,'warning':warning}
   time.sleep(.3)
  raise RuntimeError('另一个启动进程尚未就绪，请查看runtime/logs；请勿连续重复点击')
 os.close(descriptor)
 try:
  if healthy() and supervisor_running():
   if open_browser:open_workspace()
   return {'status':'already_running','url':URL,'auto_start':automatic,'warning':warning}
  if not healthy():
   with socket.socket() as probe:
    try:probe.bind(('127.0.0.1',8020))
    except OSError as exc:raise RuntimeError('8020端口已被其他服务占用，请先检查占用程序') from exc
  process=None if supervisor_running() else spawn(logs)
  deadline=time.monotonic()+timeout
  while time.monotonic()<deadline:
   if healthy() and supervisor_running():
    if open_browser:open_workspace()
    return {'status':'started','method':'supervised_desktop','url':URL,'auto_start':automatic,'warning':warning}
   if process is not None and process.poll() is not None:raise RuntimeError('后台启动失败，请查看runtime/logs/startup.log和server.log')
   time.sleep(.3)
  raise RuntimeError('后台尚未在规定时间内就绪，请查看runtime/logs；未重复启动第二个服务')
 finally:lock.unlink(missing_ok=True)

def main():
 global PREFER_BROWSER
 parser=argparse.ArgumentParser();parser.add_argument('--no-browser',action='store_true');parser.add_argument('--browser',action='store_true');args=parser.parse_args();PREFER_BROWSER=args.browser
 try:print(json.dumps(start(not args.no_browser),ensure_ascii=False))
 except Exception as exc:print(str(exc),file=sys.stderr);return 1
 return 0

if __name__=='__main__':sys.exit(main())
