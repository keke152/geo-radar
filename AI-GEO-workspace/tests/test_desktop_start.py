import unittest
from io import BytesIO
from unittest.mock import patch,MagicMock
from urllib.error import URLError
import test_workspace  # Configures an isolated temporary runtime before importing the launcher.
import start_desktop
from config import HOME

class DesktopStartupTests(unittest.TestCase):
 def setUp(self):
  (HOME/'desktop-start.lock').unlink(missing_ok=True)
  self.autostart=patch('start_desktop.install_autostart',return_value=True);self.autostart.start();self.addCleanup(self.autostart.stop)
  self.supervised=patch('start_desktop.supervisor_running',return_value=False);self.supervised.start();self.addCleanup(self.supervised.stop)
  self.task=patch('start_desktop.launch_login_task',return_value=False);self.task.start();self.addCleanup(self.task.stop)
 def tearDown(self):(HOME/'desktop-start.lock').unlink(missing_ok=True)
 def test_existing_service_is_reused_without_spawn_or_browser(self):
  with patch('start_desktop.healthy',return_value=True),patch('start_desktop.supervisor_running',return_value=True),patch('start_desktop.spawn') as spawn,patch('start_desktop.webbrowser.open') as browser:
   result=start_desktop.start(False)
  self.assertEqual(result['status'],'already_running');spawn.assert_not_called();browser.assert_not_called()
 def test_health_connection_failure_is_not_ready(self):
  with patch('start_desktop.urlopen',side_effect=URLError('fixture offline')):self.assertFalse(start_desktop.healthy())
 def test_unrelated_health_response_is_rejected(self):
  response=MagicMock();response.__enter__.return_value=BytesIO(b'{"status":"ok","service":"other-app"}')
  with patch('start_desktop.urlopen',return_value=response):self.assertFalse(start_desktop.healthy())
 def test_port_conflict_does_not_start_second_service(self):
  probe=MagicMock();probe.__enter__.return_value.bind.side_effect=OSError('fixture port occupied')
  with patch('start_desktop.healthy',return_value=False),patch('start_desktop.socket.socket',return_value=probe),patch('start_desktop.spawn') as spawn:
   with self.assertRaisesRegex(RuntimeError,'8020'):start_desktop.start(False,timeout=0)
   spawn.assert_not_called()
  self.assertFalse((HOME/'desktop-start.lock').exists())
 def test_startup_failure_has_log_hint_and_releases_lock(self):
  process=MagicMock();process.poll.return_value=1
  with patch('start_desktop.healthy',return_value=False),patch('start_desktop.socket.socket'),patch('start_desktop.spawn',return_value=process):
   with self.assertRaisesRegex(RuntimeError,'startup.log'):start_desktop.start(False,timeout=1)
  self.assertFalse((HOME/'desktop-start.lock').exists())
 def test_concurrent_start_does_not_spawn_or_remove_other_lock(self):
  lock=HOME/'desktop-start.lock';lock.write_text('fixture',encoding='utf-8')
  with patch('start_desktop.healthy',return_value=False),patch('start_desktop.spawn') as spawn:
   with self.assertRaisesRegex(RuntimeError,'启动进程'):start_desktop.start(False,timeout=0)
   spawn.assert_not_called()
  self.assertTrue(lock.exists())
 @unittest.skipUnless(start_desktop.os.name=='nt','Windows desktop integration')
 def test_windows_process_is_delegated_to_desktop_with_paths_as_data(self):
  completed=MagicMock();completed.returncode=0
  with patch('start_desktop.subprocess.run',return_value=completed) as run:
   self.assertIsNone(start_desktop.spawn(HOME/'logs'))
  args=run.call_args.args[0];options=run.call_args.kwargs
  self.assertEqual(args[0],'powershell.exe');self.assertIn('ShellExecute',args[-1])
  self.assertNotIn(str(start_desktop.ROOT),args[-1]);self.assertEqual(options['env']['AI_GEO_PROJECT'],str(start_desktop.ROOT))
  self.assertNotIn('shell',options)
  self.assertIn('desktop_service.py',args[-1]);self.assertIn('--run',args[-1])
 def test_existing_unsupervised_http_is_adopted_without_a_second_worker(self):
  with patch('start_desktop.healthy',return_value=True),patch('start_desktop.supervisor_running',side_effect=[False,False,False,True]),patch('start_desktop.spawn') as spawn,patch('start_desktop.socket.socket') as socket:
   result=start_desktop.start(False)
  spawn.assert_called_once();socket.assert_not_called();self.assertEqual(result['status'],'started')
 def test_autostart_install_failure_still_reuses_working_service(self):
  with patch('start_desktop.install_autostart',side_effect=OSError('fixture')),patch('start_desktop.healthy',return_value=True),patch('start_desktop.supervisor_running',return_value=True):
   result=start_desktop.start(False)
  self.assertFalse(result['auto_start']);self.assertIn('自动启动设置失败',result['warning'])
 @unittest.skipUnless(start_desktop.os.name=='nt','Windows scheduler integration')
 def test_scheduler_owned_process_is_preferred(self):
  with patch('start_desktop.launch_login_task',return_value=True),patch('start_desktop.subprocess.run') as run:
   self.assertIsNone(start_desktop.spawn(HOME/'logs'))
  run.assert_not_called()
