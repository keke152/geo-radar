import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import test_workspace  # Isolated runtime, no dispatch or external platform calls.
import desktop_service as service
import launcher


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='ai-geo-supervisor-test-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        for name, filename in [('STATE', 'state.json'), ('STOP', 'stop.request'), ('LOCK', 'instance.lock'), ('AUTOSTART', 'autostart.json')]:
            p = patch.object(service, name, self.root / filename)
            p.start(); self.addCleanup(p.stop)
        self.worker = MagicMock(pid=123)
        self.worker.poll.return_value = None
        self.clock = 0
        self.launch = MagicMock(return_value=self.worker)
        self.supervisor = service.Supervisor(clock=lambda: self.clock, launch=self.launch)

    def test_os_lock_excludes_second_instance_and_releases(self):
        first = service.InstanceLock(self.root / 'lock')
        second = service.InstanceLock(self.root / 'lock')
        try:
            self.assertTrue(first.acquire()); self.assertFalse(second.acquire())
            first.release(); self.assertTrue(second.acquire())
        finally:
            first.release(); second.release()

    def test_missing_service_is_started_once_while_initializing(self):
        with patch.object(service, 'healthy', return_value=False), patch.object(service, 'port_available', return_value=True):
            self.supervisor.step(); self.supervisor.step()
        self.launch.assert_called_once()
        self.assertEqual(json.loads(service.STATE.read_text())['state'], 'waiting_for_http')

    def test_existing_healthy_service_is_reused(self):
        with patch.object(service, 'healthy', return_value=True):
            self.supervisor.step()
        self.launch.assert_not_called()
        self.assertEqual(json.loads(service.STATE.read_text())['state'], 'running')

    def test_crashed_process_restarts_only_after_backoff(self):
        with patch.object(service, 'healthy', return_value=False), patch.object(service, 'port_available', return_value=True):
            self.supervisor.step()
            self.worker.poll.return_value = 1; self.worker.returncode = 1
            self.supervisor.step(); self.clock = 1; self.supervisor.step()
            self.assertEqual(self.launch.call_count, 1)
            self.clock = 2; self.worker.poll.return_value = None; self.supervisor.step()
        self.assertEqual(self.launch.call_count, 2)
        self.assertEqual(self.supervisor.restarts, 2)

    def test_backoff_is_bounded_and_resets_after_stable_minute(self):
        self.supervisor.failures = 40; self.supervisor.child = self.worker
        self.worker.poll.return_value = 1; self.worker.returncode = 1
        self.supervisor.step()
        self.assertEqual(self.supervisor.next_start, 60)
        with patch.object(service, 'healthy', return_value=True):
            self.clock = 1; self.supervisor.step()
            self.clock = 61; self.supervisor.step()
        self.assertEqual(self.supervisor.failures, 0)

    def test_live_but_unresponsive_worker_is_not_killed_or_duplicated(self):
        self.supervisor.child = self.worker
        with patch.object(service, 'healthy', return_value=False):
            self.clock = 10000; self.supervisor.step()
        self.launch.assert_not_called(); self.worker.terminate.assert_not_called()

    def test_unrelated_port_is_never_killed_or_duplicated(self):
        with patch.object(service, 'healthy', return_value=False), patch.object(service, 'port_available', return_value=False):
            self.supervisor.step()
        self.launch.assert_not_called()
        self.assertEqual(json.loads(service.STATE.read_text())['state'], 'port_conflict')

    def test_stop_marker_prevents_service_start(self):
        service.STOP.touch()
        with patch.object(service, 'InstanceLock') as lock:
            lock.return_value.acquire.return_value = True
            self.assertEqual(self.supervisor.run(), 'stopped')
        self.launch.assert_not_called(); lock.return_value.release.assert_called_once()

    def test_second_supervisor_does_not_start_any_worker(self):
        with patch.object(service, 'InstanceLock') as lock:
            lock.return_value.acquire.return_value = False
            self.assertEqual(self.supervisor.run(), 'already_running')
        self.launch.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows user startup shortcut')
    def test_autostart_paths_are_data_and_no_password_or_admin_is_requested(self):
        shortcut = self.root / 'AI GEO Background.lnk'; shortcut.touch()
        with patch.object(service, 'shortcut_path', return_value=shortcut), patch.object(service.subprocess, 'run', return_value=MagicMock(returncode=0)) as run:
            self.assertTrue(service.install_autostart())
        args = run.call_args.args[0]; options = run.call_args.kwargs
        self.assertNotIn(str(service.ROOT), args[-1])
        self.assertIn('--run --login', args[-1]); self.assertIn('-LogonType Interactive -RunLevel Limited', args[-1])
        self.assertNotIn('Password', args[-1])
        self.assertEqual(options['env']['AI_GEO_SHORTCUT'], str(shortcut))
        self.assertEqual(service.autostart_mode(), 'task')

    @unittest.skipUnless(os.name == 'nt', 'Windows fallback')
    def test_scheduler_unavailable_falls_back_to_current_user_shortcut(self):
        shortcut = self.root / 'AI GEO Background.lnk'; shortcut.touch()
        with patch.object(service, 'shortcut_path', return_value=shortcut), patch.object(service.subprocess, 'run', side_effect=[MagicMock(returncode=1), MagicMock(returncode=0)]):
            self.assertTrue(service.install_autostart())
        self.assertEqual(service.autostart_mode(), 'shortcut')

    @unittest.skipUnless(os.name == 'nt', 'Windows scheduler launch')
    def test_login_task_launch_uses_fixed_command_and_no_prompt(self):
        service.AUTOSTART.write_text('{"mode":"task"}')
        with patch.object(service.subprocess, 'run', return_value=MagicMock(returncode=0)) as run:
            self.assertTrue(service.launch_login_task())
        self.assertIn('Start-ScheduledTask', run.call_args.args[0][-1])
        self.assertEqual(run.call_args.kwargs['env']['AI_GEO_TASK'], service.TASK_NAME)

    @unittest.skipUnless(os.name == 'nt', 'Windows user startup shortcut')
    def test_disable_only_removes_our_shortcut(self):
        shortcut = self.root / 'AI GEO Background.lnk'; shortcut.touch()
        other = self.root / 'Other App.lnk'; other.touch()
        with patch.object(service, 'shortcut_path', return_value=shortcut), patch.object(service.subprocess, 'run', return_value=MagicMock(returncode=0)):
            service.remove_autostart()
        self.assertFalse(shortcut.exists()); self.assertTrue(other.exists())


class GracefulStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_marker_requests_asgi_shutdown(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'stop'; marker.touch()
            server = MagicMock(should_exit=False)
            async def serving():
                for _ in range(10):
                    if server.should_exit:
                        return
                    await asyncio.sleep(.01)
                self.fail('stop marker was ignored')
            server.serve = serving
            await launcher.serve_until_stopped(server, marker)
            self.assertTrue(server.should_exit)


if __name__ == '__main__':
    unittest.main()
