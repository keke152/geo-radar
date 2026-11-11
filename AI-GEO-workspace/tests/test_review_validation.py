import json,unittest
import test_workspace
from fastapi.testclient import TestClient
import app
from storage import db,init,records,now

HEADERS={'X-Workspace-Request':'junhe-local'}

class ReviewValidationTests(unittest.TestCase):
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
 def post(self,tid,body):return self.client.post('/api/tasks/'+tid+'/review',json=body,headers=HEADERS)
 def saved(self,tid):
  with db() as c:return dict(c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone())
 def assert_rejected_unchanged(self,tid,body):
  before=self.saved(tid);response=self.post(tid,body)
  self.assertEqual(response.status_code,422,response.text)
  self.assertIsInstance(response.json()['detail'],str)
  self.assertIn('回答内容不能为空',response.json()['detail'])
  self.assertIn('采集',response.json()['detail'])
  self.assertEqual(self.saved(tid),before)
 def test_empty_review_does_not_erase_answer_or_mark_unreviewed_task_complete(self):
  for status in ('sent','needs_review','completed'):
   with self.subTest(status=status):
    t=self.task(status=status,reviewed=int(status=='completed'),answer='保留已有回答')
    self.assert_rejected_unchanged(t['id'],{'answer':''})
 def test_whitespace_only_review_is_rejected_without_any_record_change(self):
  t=self.task(status='needs_review',reviewed=0,answer='')
  for answer in (' ','\t\r\n','\u3000\u00a0 '):
   with self.subTest(answer=repr(answer)):self.assert_rejected_unchanged(t['id'],{'answer':answer})
 def test_missing_or_null_answer_has_actionable_chinese_response_and_keeps_saved_data(self):
  t=self.task(answer='已保存的完整原文')
  for body in ({},{'answer':None}):
   with self.subTest(body=body):self.assert_rejected_unchanged(t['id'],body)
 def test_valid_review_keeps_exact_text_and_capture_provenance(self):
  t=self.task(status='needs_review',reviewed=0,answer='',metrics=json.dumps({'conversation_url':'https://www.doubao.com/chat/fixture','answer_matched_to_prompt':True}))
  text='  原始回答首行\n\n完整结尾。\n '
  response=self.post(t['id'],{'answer':text})
  self.assertEqual(response.status_code,200,response.text)
  saved=self.saved(t['id']);self.assertEqual(saved['answer'],text)
  self.assertEqual(saved['status'],'completed');self.assertEqual(saved['reviewed'],1)
  metrics=json.loads(saved['metrics']);self.assertEqual(metrics['verification_method'],'human')
  self.assertEqual(metrics['conversation_url'],'https://www.doubao.com/chat/fixture')
  self.assertTrue(metrics['answer_matched_to_prompt'])
 def test_review_limit_still_rejects_oversized_text_without_erasing_previous_answer(self):
  t=self.task(answer='保留原文');before=self.saved(t['id'])
  self.assertEqual(self.post(t['id'],{'answer':'字'*100001}).status_code,422)
  self.assertEqual(self.saved(t['id']),before)
 def test_validation_does_not_weaken_task_channel_status_or_trash_guards(self):
  for changes,expected in (({'status':'queued'},409),({'status':'waiting_setup'},409),({'channel':'api'},409),({'deleted_at':now()},404)):
   with self.subTest(changes=changes):
    t=self.task(**changes);before=self.saved(t['id'])
    self.assertEqual(self.post(t['id'],{'answer':'有效回答'}).status_code,expected)
    self.assertEqual(self.saved(t['id']),before)
