import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
import test_workspace
from fastapi.testclient import TestClient
import app,client_window,start_desktop
from config import ROOT,PLATFORMS,VERSION
from storage import init,db,ident,now

class ClientShellTests(unittest.TestCase):
 def setUp(self):
  self.context=TestClient(app.app,base_url='http://127.0.0.1:8020');self.client=self.context.__enter__();self.addCleanup(lambda:self.context.__exit__(None,None,None))
  with db() as c:
   for table in ('tasks','batches','schedules','documents','keywords','meta'):c.execute('DELETE FROM '+table)
  init()
 def task(self,status='completed',platform='kimi'):
  key=ident()
  with db() as c:c.execute('INSERT INTO tasks(id,batch_id,platform,channel,mode,keyword,prompt,status,answer,reviewed,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
   (key,'fixture',platform,'web','visibility','fixture','fixture',status,'fixture',int(status=='completed'),now(),now()))
  return key
 def test_html_and_static_scripts_are_never_cached(self):
  for url in ('/','/static/client.js','/static/client.css','/api/bootstrap'):
   response=self.client.get(url);self.assertEqual(response.status_code,200);self.assertIn('no-store',response.headers['cache-control'])
 def test_page_contains_client_shell_and_a_single_composer(self):
  body=self.client.get('/').text
  self.assertEqual(body.count('id="batch-form"'),1);self.assertEqual(body.count('id="task-composer"'),1)
  self.assertIn(f'data-ui-version="{VERSION}"',body);self.assertIn('client-menu-toggle',body)
  self.assertNotIn('让品牌，被准确看见。',body)
 def test_bootstrap_version_and_counts_come_from_all_records(self):
  for _ in range(153):self.task('waiting_setup')
  self.task('completed');self.task('queued');self.task('running')
  data=self.client.get('/api/bootstrap').json()
  self.assertEqual(data['version'],VERSION);self.assertEqual(data['client_counts'],{'all':156,'running':2,'attention':153,'completed':1})
 def test_task_groups_are_paginated_with_full_database_counts(self):
  for _ in range(18):self.task('waiting_setup')
  self.task('completed');self.task('needs_review');self.task('queued')
  response=self.client.get('/api/tasks?group=attention&page=2&page_size=15').json()
  self.assertEqual(response['total'],19);self.assertEqual(response['pages'],2);self.assertEqual(len(response['items']),4)
  self.assertTrue(all(x['status']=='waiting_setup' for x in response['items']))
 def test_group_and_text_filter_are_combined(self):
  self.task('completed');self.task('running')
  data=self.client.get('/api/tasks?group=running&q=fixture').json()
  self.assertEqual(data['total'],1);self.assertEqual(data['items'][0]['status'],'running')
 def test_invalid_group_is_rejected_and_retired_platform_not_exposed(self):
  self.assertEqual(self.client.get('/api/tasks?group=invalid').status_code,422)
  self.task('completed','chatgpt');self.assertEqual(self.client.get('/api/tasks?group=completed').json()['total'],0)
 def test_client_reads_do_not_send_or_create_tasks(self):
  self.task();
  with patch.object(app.runner.browser,'send') as send:
   before=self.client.get('/api/tasks').json()['total'];self.client.get('/api/tasks?group=completed');self.client.get('/api/bootstrap')
   self.assertEqual(self.client.get('/api/tasks').json()['total'],before)
  send.assert_not_called()

class ClientWindowTests(unittest.TestCase):
 def test_missing_edge_uses_browser_fallback(self):
  with patch('client_window.edge_executable',return_value=None):self.assertFalse(client_window.open_client())
 def test_edge_opens_only_local_app_with_a_separate_shell_profile(self):
  with patch('client_window.edge_executable',return_value=Path('C:/fixture/msedge.exe')),patch('client_window.subprocess.Popen') as launch:
   self.assertTrue(client_window.open_client())
  args=launch.call_args.args[0]
  self.assertIn('--app=http://127.0.0.1:8020/#overview',args)
  self.assertTrue(any(x.startswith('--user-data-dir=') and x.endswith('client-shell') for x in args))
  self.assertNotIn('shell',launch.call_args.kwargs)
 def test_window_start_failure_does_not_prevent_browser_fallback(self):
  with patch('client_window.edge_executable',return_value=Path('C:/fixture/msedge.exe')),patch('client_window.subprocess.Popen',side_effect=OSError('fixture')):
   self.assertFalse(client_window.open_client())
 def test_explicit_browser_mode_does_not_open_a_client_window(self):
  with patch.object(start_desktop,'PREFER_BROWSER',True),patch('client_window.open_client') as client,patch('start_desktop.webbrowser.open') as browser:
   start_desktop.open_workspace()
  client.assert_not_called();browser.assert_called_once_with('http://127.0.0.1:8020/#overview')

if __name__=='__main__':unittest.main()
