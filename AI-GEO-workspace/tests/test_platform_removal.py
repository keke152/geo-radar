import json,unittest
from unittest.mock import AsyncMock,patch
from fastapi.testclient import TestClient
from test_workspace import app,db,init,ident,create_batch,records,update_task,now,HEADERS
from config import PLATFORMS
from storage import get_meta,set_meta

RETIRED=('chatgpt','gemini','grok','claude_code')

class PlatformRemovalTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.context=TestClient(app.app,base_url='http://127.0.0.1:8020');cls.client=cls.context.__enter__()
 @classmethod
 def tearDownClass(cls):cls.context.__exit__(None,None,None)
 def setUp(self):
  with db() as c:
   for table in ('tasks','batches','schedules','documents','keywords','meta'):c.execute('DELETE FROM '+table)
  init()
 def post(self,path,body=None):return self.client.post(path,json=body or {},headers=HEADERS)
 def legacy(self,pid,status):
  tid=ident()
  with db() as c:c.execute('INSERT INTO tasks(id,batch_id,platform,channel,mode,keyword,prompt,status,answer,reviewed,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(tid,'legacy',pid,'web','visibility','fixture','fixture',status,'preserved old answer' if status=='completed' else '',int(status=='completed'),now(),now()))
  return tid
 def test_only_six_platforms_are_exposed(self):
  b=self.client.get('/api/bootstrap').json()
  self.assertEqual([p['id'] for p in b['platforms']],['doubao','deepseek','kimi','qwen','yuanbao','zhihu'])
  self.assertNotIn('cli',b['metrics'])
  self.assertEqual(self.client.get('/api/tasks?channel=cli').status_code,422)
  self.assertEqual(self.client.get('/api/insights?channel=cli').status_code,422)
 def test_retired_connections_are_unavailable_without_browser_calls(self):
  with patch.object(app.runner.browser,'connect',new=AsyncMock()) as connect:
   for pid in RETIRED:
    self.assertEqual(self.post('/api/platforms/'+pid+'/connect').status_code,404)
    self.assertEqual(self.client.put('/api/platforms/'+pid,json={'channel':'web'},headers=HEADERS).status_code,404)
   connect.assert_not_awaited()
 def test_retired_platform_batches_are_rejected_without_creating_tasks(self):
  for pid in RETIRED:
   response=self.post('/api/batches',{'keywords':['fixture'],'platforms':[pid],'mode':'visibility','request_key':ident()})
   self.assertEqual(response.status_code,422)
  self.assertEqual(records('tasks'),[])
 def test_migration_removes_connection_settings_and_clamps_parallel_limit(self):
  for pid in RETIRED:set_meta('platform:'+pid,{'id':pid,'ready':True})
  set_meta('settings',{**get_meta('settings'),'parallel_platforms':10});init()
  self.assertEqual(get_meta('settings')['parallel_platforms'],6)
  with db() as c:
   for pid in RETIRED:self.assertIsNone(c.execute('SELECT 1 FROM meta WHERE key=?',('platform:'+pid,)).fetchone())
 def test_unexecuted_legacy_tasks_stop_but_completed_answers_are_preserved(self):
  pending=self.legacy('chatgpt','queued');completed=self.legacy('gemini','completed');init()
  all_tasks={t['id']:t for t in records('tasks')}
  self.assertEqual(all_tasks[pending]['status'],'cancelled');self.assertEqual(all_tasks[completed]['answer'],'preserved old answer')
  self.assertEqual(all_tasks[completed]['status'],'completed')
  self.assertEqual(self.client.get('/api/tasks').json()['total'],0)
  self.assertEqual(self.client.get('/api/insights').json()['totals']['samples'],0)
 def test_schedules_drop_retired_targets_and_disable_empty_schedule(self):
  first,second=ident(),ident()
  with db() as c:
   for sid,targets in [(first,['doubao','grok']),(second,['claude_code'])]:c.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?)',(sid,'09:00','[]',json.dumps(targets),'visibility',1,'',now()))
  init();schedules={s['id']:s for s in records('schedules')}
  self.assertEqual(json.loads(schedules[first]['platforms']),['doubao']);self.assertTrue(schedules[first]['enabled'])
  self.assertEqual(json.loads(schedules[second]['platforms']),[]);self.assertFalse(schedules[second]['enabled'])
 def test_uncertain_diagnostic_remains_readonly(self):
  create_batch(['fixture'],['kimi'],'visibility',ident());task=records('tasks')[0];update_task(task['id'],status='uncertain')
  with patch.object(app.runner.browser,'current_page',return_value=object()),patch.object(app.runner.browser,'inspect',new=AsyncMock(return_value={'composer_editable':True})),patch.object(app.runner.browser,'response_snapshot',new=AsyncMock(return_value={'matched':False,'answer':''})),patch.object(app.runner.browser,'send',new=AsyncMock()) as send:
   result=self.post('/api/tasks/'+task['id']+'/diagnose');send.assert_not_awaited()
  self.assertTrue(result.json()['task_unchanged']);self.assertEqual(records('tasks')[0]['status'],'uncertain')
 def test_upgrade_keeps_deleted_materials_deleted(self):
  with db() as c:c.execute('DELETE FROM documents')
  init();self.assertEqual(records('documents'),[])
