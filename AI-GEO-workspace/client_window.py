"""Open the local workspace as an Edge application window, with browser fallback."""
import os,subprocess
from pathlib import Path
from config import HOME

def edge_executable():
 for key in ('PROGRAMFILES(X86)','PROGRAMFILES','LOCALAPPDATA'):
  if not os.environ.get(key):continue
  path=Path(os.environ[key])/'Microsoft/Edge/Application/msedge.exe'
  if path.is_file():return path
 return None

def open_client():
 if os.name!='nt':return False
 executable=edge_executable()
 if executable is None:return False
 try:
  subprocess.Popen([str(executable),'--app=http://127.0.0.1:8020/#overview',
      '--user-data-dir='+str(HOME/'client-shell'),'--window-size=1220,820','--no-first-run'],
      stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
      creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP,close_fds=True)
  return True
 except OSError:return False
