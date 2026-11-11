"""Per-user desktop supervisor. Restarts the HTTP process, never replays requests."""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

from config import HOME, ROOT

URL = 'http://127.0.0.1:8020'
STOP = HOME / 'desktop-stop.request'
STATE = HOME / 'desktop-service.json'
LOCK = HOME / 'desktop-supervisor.lock'
SHORTCUT = 'AI GEO Background.lnk'
TASK_NAME = 'AI GEO Background'
AUTOSTART = HOME / 'desktop-autostart.json'
LOG = logging.getLogger('ai_geo.supervisor')
_open = build_opener(ProxyHandler({})).open


class InstanceLock:
    """An OS-owned file lock is released even if the process is killed."""
    def __init__(self, path=None):
        self.path, self.file = Path(path or LOCK), None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open('a+b')
        if not self.path.stat().st_size:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.file = handle
        return True

    def release(self):
        if self.file:
            self.file.close()
            self.file = None


def supervisor_running():
    if not LOCK.exists():
        return False
    probe = InstanceLock()
    if not probe.acquire():
        return True
    probe.release()
    return False


def healthy():
    try:
        with _open(URL + '/api/health', timeout=2) as response:
            return json.load(response).get('service') == 'ai-geo-workspace'
    except (OSError, ValueError):
        return False


def port_available():
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', 8020))
            return True
        except OSError:
            return False


def shortcut_path():
    return Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup' / SHORTCUT


def autostart_mode():
    try:
        return json.loads(AUTOSTART.read_text(encoding='utf-8')).get('mode', '')
    except (OSError, ValueError):
        return ''


def install_autostart():
    """Current user interactive login task, with a Startup-folder fallback."""
    if os.name != 'nt':
        return False
    target = Path(sys.executable).with_name('pythonw.exe')
    if not target.is_file():
        raise RuntimeError('未找到pythonw.exe，无法设置自动启动')
    shortcut = shortcut_path()
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, 'AI_GEO_SHORTCUT': str(shortcut), 'AI_GEO_PYTHONW': str(target),
                   'AI_GEO_PROJECT': str(ROOT), 'AI_GEO_SUPERVISOR': str(ROOT / 'desktop_service.py'),
                   'AI_GEO_TASK': TASK_NAME}
    options = dict(env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW, timeout=25)
    # The task runs only in the signed-in user's desktop, never as SYSTEM or elevated.
    # Scheduler ownership also keeps the supervisor independent of a terminal's process lifetime.
    task_program = ("$ErrorActionPreference='Stop'; "
                    "$u=[Security.Principal.WindowsIdentity]::GetCurrent().Name; "
                    "$a=New-ScheduledTaskAction -Execute $env:AI_GEO_PYTHONW "
                    "-Argument ('\"'+$env:AI_GEO_SUPERVISOR+'\" --run --login') -WorkingDirectory $env:AI_GEO_PROJECT; "
                    "$t=New-ScheduledTaskTrigger -AtLogOn -User $u; "
                    "$p=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited; "
                    "$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) "
                    "-MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) "
                    "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable; "
                    "Register-ScheduledTask -TaskName $env:AI_GEO_TASK -Action $a -Trigger $t "
                    "-Principal $p -Settings $s -Description 'AI GEO local background recovery' -Force | Out-Null")
    try:
        task_result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', task_program], **options)
        if task_result.returncode == 0:
            AUTOSTART.write_text(json.dumps({'mode': 'task', 'task_name': TASK_NAME}), encoding='utf-8')
            shortcut.unlink(missing_ok=True)
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    # A fixed PowerShell program; all paths are passed as environment data.
    program = ("$ErrorActionPreference='Stop'; $s=New-Object -ComObject WScript.Shell; "
               "$l=$s.CreateShortcut($env:AI_GEO_SHORTCUT); $l.TargetPath=$env:AI_GEO_PYTHONW; "
               "$l.Arguments=('\"'+$env:AI_GEO_SUPERVISOR+'\" --run --login'); "
               "$l.WorkingDirectory=$env:AI_GEO_PROJECT; $l.WindowStyle=7; "
               "$l.Description='AI GEO local background and automatic recovery'; $l.Save()")
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', program],
        **options)
    if result.returncode or not shortcut.is_file():
        raise RuntimeError('当前用户自动启动设置失败，请查看Windows启动文件夹权限')
    AUTOSTART.write_text(json.dumps({'mode': 'shortcut'}), encoding='utf-8')
    return True


def launch_login_task():
    if os.name != 'nt' or autostart_mode() != 'task':
        return False
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
         "$ErrorActionPreference='Stop'; Start-ScheduledTask -TaskName $env:AI_GEO_TASK"],
        env={**os.environ, 'AI_GEO_TASK': TASK_NAME}, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
    return result.returncode == 0


def remove_autostart():
    if os.name == 'nt':
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
             "$ErrorActionPreference='Stop'; $t=Get-ScheduledTask -TaskName $env:AI_GEO_TASK -ErrorAction SilentlyContinue; if($t){Unregister-ScheduledTask -TaskName $env:AI_GEO_TASK -Confirm:$false}"],
            env={**os.environ, 'AI_GEO_TASK': TASK_NAME}, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
        if result.returncode:
            raise RuntimeError('自动启动任务未能移除，请在Windows任务计划程序中检查AI GEO Background')
        shortcut_path().unlink(missing_ok=True)
        AUTOSTART.unlink(missing_ok=True)


def service_status():
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    return {**state, 'supervised': supervisor_running(), 'auto_start_method': autostart_mode(),
            'auto_start': os.name == 'nt' and (autostart_mode() == 'task' or shortcut_path().is_file()),
            'stopped': STOP.exists()}


def configure_logging():
    folder = HOME / 'logs'; folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / 'supervisor.log', maxBytes=1_000_000,
                                  backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    LOG.setLevel(logging.INFO); LOG.addHandler(handler)


def launch_worker():
    logs = HOME / 'logs'; logs.mkdir(parents=True, exist_ok=True)
    with (logs / 'startup.log').open('ab') as output:
        return subprocess.Popen([sys.executable, str(ROOT / 'launcher.py')], cwd=str(ROOT),
                                stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


class Supervisor:
    def __init__(self, clock=time.monotonic, launch=launch_worker):
        self.clock, self.launch = clock, launch
        self.child = None
        self.failures = self.restarts = 0
        self.next_start = 0
        self.healthy_since = None
        self.last_state = None

    def record(self, phase, **extra):
        state = {'state': phase, 'pid': os.getpid(),
                 'worker_pid': self.child.pid if self.child else None,
                 'restart_count': self.restarts, 'heartbeat': time.time(), **extra}
        temporary = STATE.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        temporary.replace(STATE)
        if phase != self.last_state:
            LOG.info('state=%s worker=%s restarts=%s', phase, state['worker_pid'], self.restarts)
            self.last_state = phase

    def step(self):
        now = self.clock()
        if self.child is not None and self.child.poll() is not None:
            code = self.child.returncode
            self.child = None; self.failures += 1; self.healthy_since = None
            delay = min(60, 2 ** min(self.failures, 6))
            self.next_start = now + delay
            LOG.warning('HTTP process exited code=%s; restart in %ss', code, delay)
            self.record('recovering', exit_code=code, retry_seconds=delay)
            return
        if healthy():
            if self.healthy_since is None:
                self.healthy_since = now
            if now - self.healthy_since >= 60:
                self.failures = 0
            self.record('running')
            return
        self.healthy_since = None
        if self.child is not None:
            # A slow request or startup must not produce a duplicate service or kill a live send.
            self.record('waiting_for_http')
            return
        if now < self.next_start:
            self.record('recovering', retry_seconds=round(self.next_start - now))
            return
        if not port_available():
            self.next_start = now + 15
            self.record('port_conflict', retry_seconds=15)
            return
        self.child = self.launch(); self.restarts += 1
        self.record('starting')

    def run(self):
        lock = InstanceLock()
        if not lock.acquire():
            return 'already_running'
        try:
            LOG.info('Supervisor started')
            while not STOP.exists():
                try:
                    self.step()
                except Exception:
                    LOG.exception('Supervisor check failed; retrying without resending requests')
                for _ in range(6):
                    if STOP.exists():
                        break
                    time.sleep(.5)
            # launcher.py observes the same stop marker and shuts down ASGI/Playwright gracefully.
            if self.child is not None:
                try:
                    self.child.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    # Do not force-kill a live browser/send; remain available for the next start.
                    LOG.warning('HTTP process is still shutting down; no forced termination')
            self.record('stopped')
            return 'stopped'
        finally:
            lock.release()


def main():
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--run', action='store_true')
    actions.add_argument('--stop', action='store_true')
    actions.add_argument('--disable-autostart', action='store_true')
    actions.add_argument('--status', action='store_true')
    parser.add_argument('--login', action='store_true', help='Resume after Windows login')
    args = parser.parse_args()
    if args.status:
        print(json.dumps(service_status(), ensure_ascii=False)); return
    if args.stop or args.disable_autostart:
        STOP.write_text('User requested stop\n', encoding='utf-8')
        if args.disable_autostart:
            remove_autostart()
        print('已请求停止本机后台；再次运行start.bat可恢复。'); return
    if args.login:
        STOP.unlink(missing_ok=True)
    configure_logging()
    Supervisor().run()


if __name__ == '__main__':
    main()
