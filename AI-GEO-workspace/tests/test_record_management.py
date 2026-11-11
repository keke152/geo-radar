import io,json,unittest,zipfile
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from unittest.mock import patch,AsyncMock
from xml.etree import ElementTree as E
import test_workspace
from fastapi.testclient import TestClient
import app
from storage import db,init,records,update_task,now,set_meta
from record_export import build_xlsx,rows_for,NS
from config import DEFAULT_PROFILE,DEFAULT_SETTINGS
from queries import daily_budget
from engine import Runner
import record_archive
HEADERS={'X-Workspace-Request':'junhe-local'}
class RecordManagementTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.context=TestClient(app.app,base_url='http://127.0.0.1:8020');cls.client=cls.context.__enter__()
 @classmethod
 def tearDownClass(cls):cls.context.__exit__(None,None,None)
 def setUp(self):
  with db() as c:
   for table in ('tasks','batches','schedules','documents','keywords','meta','record_delete_previews'):c.execute('DELETE FROM '+table)
  init()
 task=test_workspace.InsightsTests.task
 def post(self,url,body):return self.client.post(url,json=body,headers=HEADERS)
 def preview(self,**body):return self.post('/api/records/delete-preview',body).json()
 def remove(self,**body):return self.post('/api/records/delete',{'token':self.preview(**body)['token']})
 def cells(self,raw,sheet=1):
  with zipfile.ZipFile(io.BytesIO(raw)) as z:
   strings=[]
   if 'xl/sharedStrings.xml' in z.namelist():strings=[''.join(x.itertext()) for x in E.fromstring(z.read('xl/sharedStrings.xml'))]
   root=E.fromstring(z.read(f'xl/worksheets/sheet{sheet}.xml'))
   values={}
   for c in root.findall('.//{'+NS+'}c'):
    v=c.find('{'+NS+'}v');value=v.text if v is not None else ''.join(c.itertext())
    values[c.get('r')]=strings[int(value)] if c.get('t')=='s' else value
   return root,values
 def test_export_keeps_all_17_template_headers_and_numeric_date(self):
  self.task();r=self.client.get('/api/export/tasks.xlsx');self.assertEqual(r.status_code,200)
  root,cells=self.cells(r.content)
  headers=['日期','平台','是否联网','问题编号','完整问题','是否新对话','有没有提到我','有没有推荐我','排第几','来源里有没有我的网页','应用了哪些其他来源','说错了什么','提到了哪些竞品','AI推荐语原话','原始回答保存位置','本轮变动','备注']
  self.assertEqual([cells[chr(65+i)+'2'] for i in range(17)],headers)
  self.assertGreater(float(cells['A3']),45000);self.assertEqual(cells['B3'],'豆包')
  self.assertEqual(root.find('{'+NS+'}autoFilter').get('ref'),'A2:Q3')
 def test_recommendation_rank_and_network_are_not_invented(self):
  task=self.task();main,_,_=rows_for([task],DEFAULT_PROFILE)
  self.assertEqual(main[0][2],'未核实');self.assertEqual(main[0][7],'未判定');self.assertEqual(main[0][8],'')
  self.assertEqual(main[0][6],'是（品牌、企业）')
 def test_cited_official_url_is_distinct_from_body_url(self):
  task=self.task(metrics=json.dumps({'source_links':['https://example.org/x']}))
  main,_,_=rows_for([task],DEFAULT_PROFILE);self.assertEqual(main[0][9],'未发现');self.assertEqual(main[0][10],'https://example.org/x')
 def test_untrusted_formula_like_text_is_not_executed(self):
  task=self.task(prompt='=HYPERLINK("https://example.org")',answer='+SUM(1,2)')
  raw=build_xlsx([task],DEFAULT_PROFILE)
  for sheet in (1,2):
   root,_=self.cells(raw,sheet);self.assertEqual(root.findall('.//{'+NS+'}f'),[])
 def test_long_unicode_original_is_lossless_across_segments(self):
  original='测试🧪'*16000;task=self.task(answer=original,prompt='问题'*17000)
  raw=build_xlsx([task],DEFAULT_PROFILE);_,cells=self.cells(raw,2)
  answer=''.join(value for key,value in cells.items() if key.startswith('D') and key!='D1')
  prompt=''.join(value for key,value in cells.items() if key.startswith('C') and key!='C1')
  self.assertEqual(answer,original);self.assertEqual(prompt,task['prompt'])
  self.assertTrue(all(len(v.encode('utf-16-le'))//2<=32767 for k,v in cells.items()))
 def test_preview_skips_queued_and_running(self):
  self.task(status='queued');self.task(status='running');self.task(status='completed')
  p=self.preview();self.assertEqual((p['count'],p['skipped_active']),(1,2))
 def test_deleted_record_disappears_from_reads_statistics_and_exports(self):
  task=self.task();self.assertEqual(self.remove(ids=[task['id']]).status_code,200)
  self.assertEqual(len(records('tasks')),0);self.assertEqual(self.client.get('/api/tasks').json()['total'],0)
  self.assertEqual(self.client.get('/api/bootstrap').json()['client_counts']['all'],0)
  self.assertEqual(self.client.get('/api/insights?scope=all').json()['totals']['samples'],0)
  self.assertEqual(self.client.get('/api/tasks/'+task['id']).status_code,404)
  self.assertNotIn(task['id'],self.client.get('/api/export/tasks.csv').text)
  _,values=self.cells(self.client.get('/api/export/tasks.xlsx').content);self.assertNotIn('D3',values)
 def test_restore_preserves_original_state_and_does_not_send(self):
  task=self.task(status='waiting_setup');self.remove(ids=[task['id']])
  self.assertEqual(self.post('/api/tasks/'+task['id']+'/retry',{}).status_code,409)
  with patch.object(app.runner.browser,'send',new=AsyncMock()) as send:
   self.assertEqual(self.post('/api/records/restore',{'ids':[task['id']]}).json()['restored'],1)
  send.assert_not_called();restored=records('tasks')[0]
  for key in task:self.assertEqual(restored[key],task[key])
 def test_retry_rechecks_eligibility_atomically_after_a_concurrent_change(self):
  for conflict in ('archive','complete'):
   with self.subTest(conflict=conflict):
    task=self.task(status='waiting_setup');stamp=now()
    class ConcurrentChange:
     def __init__(self,connection):self.connection=connection
     def execute(self,sql,args=()):
      if sql.startswith("UPDATE tasks SET status='queued'"):
       # Commit the competing operation after any old SELECT, before retry writes.
       with db() as other:
        if conflict=='archive':other.execute('UPDATE tasks SET deleted_at=?,deletion_batch=? WHERE id=?',(stamp,'fixture-batch',task['id']))
        else:other.execute("UPDATE tasks SET status='completed' WHERE id=?",(task['id'],))
      return self.connection.execute(sql,args)
    @contextmanager
    def concurrent_db():
     with db() as connection:yield ConcurrentChange(connection)
    with patch('app.db',concurrent_db):response=self.post('/api/tasks/'+task['id']+'/retry',{})
    self.assertEqual(response.status_code,409)
    with db() as c:saved=c.execute('SELECT status,deleted_at FROM tasks WHERE id=?',(task['id'],)).fetchone()
    self.assertEqual(saved['status'],'waiting_setup' if conflict=='archive' else 'completed')
    self.assertEqual(saved['deleted_at'],stamp if conflict=='archive' else None)
 def test_archived_queued_records_are_excluded_from_queue_and_setup_checks(self):
  stamp=now();web=self.task(status='queued',deleted_at=stamp,deletion_batch='fixture-batch')
  api=self.task(status='queued',channel='api',platform='deepseek',deleted_at=stamp,deletion_batch='fixture-batch')
  runner=Runner();snapshot=runner.snapshot()
  self.assertEqual(snapshot['queued'],0);self.assertEqual(snapshot['positions'],{})
  self.assertEqual(runner.block_unready(),0)
  with db() as c:
   states={r['id']:r['status'] for r in c.execute('SELECT id,status FROM tasks WHERE deleted_at IS NOT NULL')}
  self.assertEqual(states,{web['id']:'queued',api['id']:'queued'})
 def test_cutoff_uses_china_midnight_inclusively(self):
  a=self.task(created_at='2026-11-03T15:59:59+00:00');self.task(created_at='2026-11-03T16:00:00+00:00')
  self.assertEqual(self.preview(before='2026-11-03')['count'],1)
  self.remove(before='2026-11-03');self.assertEqual(self.client.get('/api/records/trash').json()['items'][0]['id'],a['id'])
 def test_preview_filters_and_explicit_ids_intersect(self):
  a=self.task(platform='kimi');self.task(platform='doubao')
  self.assertEqual(self.preview(filters={'platform':'doubao'},ids=[a['id']])['count'],0)
 def test_delete_is_idempotent_and_does_not_refund_creation_quota(self):
  self.task();budget=daily_budget()['used'];p=self.preview()
  first=self.post('/api/records/delete',{'token':p['token']});second=self.post('/api/records/delete',{'token':p['token']})
  self.assertEqual(first.json()['deleted'],1);self.assertTrue(second.json()['reused']);self.assertEqual(daily_budget()['used'],budget)
  with db() as c:self.assertEqual(c.execute('SELECT count(*) FROM tasks').fetchone()[0],1)
 def test_expired_preview_is_rejected_without_deleting(self):
  self.task();p=self.preview()
  with db() as c:c.execute('UPDATE record_delete_previews SET expires_at=?',((datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),))
  self.assertEqual(self.post('/api/records/delete',{'token':p['token']}).status_code,409);self.assertEqual(len(records('tasks')),1)
 def test_becoming_queued_after_preview_aborts_whole_batch(self):
  a=self.task(status='waiting_setup');self.task();p=self.preview();update_task(a['id'],status='queued')
  self.assertEqual(self.post('/api/records/delete',{'token':p['token']}).status_code,409);self.assertEqual(len(records('tasks')),2)
 def test_mutations_require_local_header_and_validate_inputs(self):
  self.assertEqual(self.client.post('/api/records/delete-preview',json={}).status_code,403)
  self.assertEqual(self.post('/api/records/delete-preview',{'filters':{'platform':'unknown'}}).status_code,422)
  self.assertEqual(self.post('/api/records/delete',{'token':'invalid'}).status_code,422)
 def test_xlsx_filter_matches_csv_and_keeps_all_selected_rows(self):
  a=self.task(platform='kimi');self.task(platform='doubao')
  _,cells=self.cells(self.client.get('/api/export/tasks.xlsx?platform=kimi').content)
  self.assertEqual(cells['D3'],a['id']);self.assertNotIn('D4',cells)

class ArchivedDispatchTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  init()
  with db() as c:
   for table in ('tasks','batches','schedules'):c.execute('DELETE FROM '+table)
  set_meta('settings',DEFAULT_SETTINGS)
 task=test_workspace.InsightsTests.task
 async def test_archived_queued_record_is_never_dispatched(self):
  task=self.task(status='queued',channel='api',platform='deepseek',deleted_at=now(),deletion_batch='fixture-batch')
  runner=Runner()
  with patch.object(runner,'execute',new=AsyncMock()) as execute:
   await runner.tick();execute.assert_not_awaited()
  self.assertEqual(runner.active_jobs,{})
  with db() as c:row=c.execute('SELECT status,deleted_at FROM tasks WHERE id=?',(task['id'],)).fetchone()
  self.assertEqual(row['status'],'queued');self.assertIsNotNone(row['deleted_at'])
 async def test_restore_of_legacy_active_records_waits_for_manual_confirmation(self):
  tasks=[self.task(status=status,channel='api',platform=platform,deleted_at=now(),deletion_batch='fixture-batch')
         for status,platform in (('queued','deepseek'),('running','kimi'))]
  self.assertEqual(record_archive.restore([task['id'] for task in tasks]),{'restored':2})
  runner=Runner()
  with patch.object(runner,'execute',new=AsyncMock()) as execute,patch('engine.api_send',new=AsyncMock()) as api_send,patch.object(runner.browser,'send',new=AsyncMock()) as web_send:
   await runner.tick();execute.assert_not_awaited();api_send.assert_not_awaited();web_send.assert_not_awaited()
  for saved in records('tasks'):
   self.assertEqual(saved['status'],'waiting_setup');self.assertIsNone(saved['deleted_at'])
   self.assertIn('核对平台会话',saved['note']);self.assertIn('手动',saved['note'])

if __name__=='__main__':unittest.main()
