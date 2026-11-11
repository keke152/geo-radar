import asyncio,json,unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import httpx
import test_workspace
from browser_bridge import NeedsSetup
from config import DEFAULT_SETTINGS,PLATFORMS,default_platform
from engine import Runner,create_batch
from storage import db,ident,init,records,set_meta,update_task


class ExecutionStageTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  init()
  with db() as c:
   for table in ('tasks','batches','schedules'):c.execute('DELETE FROM '+table)
  set_meta('settings',DEFAULT_SETTINGS)
  self.cfg={**default_platform('deepseek'),'ready':True,'composer':'#input','send_key':'Enter','new_chat_selector':'#new'}
  set_meta('platform:deepseek',self.cfg)
 def make(self,runner,restore=False):
  if not restore:runner.browser.pages['deepseek']=SimpleNamespace(is_closed=lambda:False,url=PLATFORMS['deepseek']['url'])
  create_batch(['独立阶段验证'],['deepseek'],'visibility',ident())
  return records('tasks')[0]
 def saved(self):return records('tasks')[0]
 def evidence(self):return json.loads(self.saved()['metrics'])['execution_error']
 async def test_restore_timeout_is_known_unsent_and_does_not_call_sender(self):
  r=Runner();task=self.make(r,restore=True)
  with patch.object(r.browser,'profile_saved',return_value=True),patch.object(r.browser,'restore_session',new=AsyncMock(side_effect=TimeoutError('fixture'))),patch.object(r.browser,'send',new=AsyncMock()) as send:
   self.assertFalse(await r.execute(task));send.assert_not_awaited()
  self.assertEqual(self.saved()['status'],'waiting_setup');self.assertIsNone(self.saved()['sent_at'])
  self.assertEqual(self.evidence()['phase'],'restoring');self.assertTrue(self.evidence()['retry_safe'])
  self.assertFalse(self.evidence()['send_attempted']);self.assertEqual(r.next_dispatch_at,0)
 async def test_successful_restore_resets_stage_before_preparing_sender(self):
  r=Runner();task=self.make(r,restore=True)
  async def sender(pid,cfg,prompt,mode,on_sent,on_attempt):
   self.assertEqual(r.phases[task['id']],'preparing');raise TimeoutError('preflight')
  with patch.object(r.browser,'profile_saved',return_value=True),patch.object(r.browser,'restore_session',new=AsyncMock()),patch.object(r.browser,'send',new=AsyncMock(side_effect=sender)):
   await r.execute(task)
  self.assertEqual(self.saved()['status'],'waiting_setup');self.assertEqual(self.evidence()['phase'],'preparing')
  self.assertFalse(self.evidence()['send_attempted']);self.assertIn('问题尚未发送',self.saved()['note'])
 async def test_preparation_failure_does_not_become_uncertain_or_add_send_cooldown(self):
  r=Runner();task=self.make(r)
  with patch.object(r.browser,'send',new=AsyncMock(side_effect=RuntimeError('bad selector'))):
   self.assertFalse(await r.execute(task))
  self.assertEqual(self.saved()['status'],'waiting_setup');self.assertTrue(self.evidence()['retry_safe'])
  self.assertEqual(r.next_dispatch_at,0);self.assertFalse(self.saved()['reviewed'])
 async def test_dispatch_timeout_is_uncertain_and_keeps_dispatch_evidence(self):
  r=Runner();task=self.make(r)
  async def sender(pid,cfg,prompt,mode,on_sent,on_attempt):on_attempt();raise TimeoutError('click result unknown')
  with patch.object(r.browser,'send',new=AsyncMock(side_effect=sender)):
   self.assertTrue(await r.execute(task))
  self.assertEqual(self.saved()['status'],'uncertain');self.assertIsNone(self.saved()['sent_at'])
  self.assertEqual(self.evidence()['phase'],'sending');self.assertTrue(self.evidence()['send_attempted'])
  self.assertFalse(self.evidence()['retry_safe']);self.assertGreater(r.next_dispatch_at,0)
 async def test_confirmed_send_capture_timeout_preserves_sent_status(self):
  r=Runner();task=self.make(r)
  async def sender(pid,cfg,prompt,mode,on_sent,on_attempt):on_attempt();on_sent();raise TimeoutError('capture timeout')
  with patch.object(r.browser,'send',new=AsyncMock(side_effect=sender)):await r.execute(task)
  self.assertEqual(self.saved()['status'],'sent');self.assertTrue(self.saved()['sent_at'])
  self.assertEqual(self.evidence()['phase'],'awaiting_answer');self.assertTrue(self.evidence()['send_confirmed'])
  self.assertEqual(self.saved()['answer'],'');self.assertFalse(self.saved()['reviewed'])
 async def test_needs_setup_after_dispatch_attempt_cannot_be_retried_as_unsent(self):
  r=Runner();task=self.make(r)
  async def sender(pid,cfg,prompt,mode,on_sent,on_attempt):on_attempt();raise NeedsSetup('lost control after click')
  with patch.object(r.browser,'send',new=AsyncMock(side_effect=sender)):await r.execute(task)
  self.assertEqual(self.saved()['status'],'uncertain');self.assertFalse(self.evidence()['retry_safe'])
  self.assertIn('核查原会话',self.saved()['note'])
 async def test_cancellation_during_preparation_is_safely_resumable(self):
  r=Runner();task=self.make(r);started=asyncio.Event();gate=asyncio.Event()
  async def sender(*args):started.set();await gate.wait()
  with patch.object(r.browser,'send',new=AsyncMock(side_effect=sender)):
   job=asyncio.create_task(r.execute(task));await started.wait();job.cancel()
   with self.assertRaises(asyncio.CancelledError):await job
  self.assertEqual(self.saved()['status'],'waiting_setup');self.assertTrue(self.evidence()['retry_safe'])
  self.assertEqual(r.next_dispatch_at,0);self.assertEqual(r.active,{})
 async def test_cancellation_after_dispatch_stays_interrupted_without_safe_retry(self):
  r=Runner();task=self.make(r);started=asyncio.Event();gate=asyncio.Event()
  async def sender(pid,cfg,prompt,mode,on_sent,on_attempt):on_attempt();started.set();await gate.wait()
  with patch.object(r.browser,'send',new=AsyncMock(side_effect=sender)):
   job=asyncio.create_task(r.execute(task));await started.wait();job.cancel()
   with self.assertRaises(asyncio.CancelledError):await job
  self.assertEqual(self.saved()['status'],'interrupted');self.assertFalse(self.evidence()['retry_safe'])
  self.assertTrue(self.evidence()['send_attempted']);self.assertFalse(self.evidence()['send_confirmed'])
 async def test_web_preparation_transport_error_is_waiting_while_api_timeout_is_uncertain(self):
  r=Runner();task=self.make(r)
  with patch.object(r.browser,'send',new=AsyncMock(side_effect=httpx.ConnectError('fixture'))):await r.execute(task)
  self.assertEqual(self.saved()['status'],'waiting_setup');self.assertTrue(self.evidence()['retry_safe'])
  with db() as c:c.execute('DELETE FROM tasks');c.execute('DELETE FROM batches')
  set_meta('platform:deepseek',{**self.cfg,'channel':'api'})
  create_batch(['API阶段验证'],['deepseek'],'visibility',ident());task=self.saved()
  with patch('engine.api_send',new=AsyncMock(side_effect=httpx.ReadTimeout('fixture'))):await Runner().execute(task)
  self.assertEqual(self.saved()['status'],'uncertain');self.assertFalse(self.evidence()['retry_safe']);self.assertTrue(self.evidence()['send_attempted'])
 async def test_successful_manual_resume_clears_stale_execution_error(self):
  r=Runner();task=self.make(r)
  update_task(task['id'],metrics=json.dumps({'execution_error':{'phase':'restoring','retry_safe':True}}))
  task=self.saved()
  async def sender(pid,cfg,prompt,mode,on_sent,on_attempt):
   on_attempt();on_sent();return {'answer':'完整模拟回答','screenshot':'','note':'fixture','matched':True,'association':'structured','done':True,'busy':False,'stable':True}
  with patch.object(r.browser,'send',new=AsyncMock(side_effect=sender)):await r.execute(task)
  self.assertEqual(self.saved()['status'],'completed');self.assertTrue(self.saved()['reviewed'])
  self.assertNotIn('execution_error',json.loads(self.saved()['metrics']))
 async def test_existing_uncertain_history_is_not_reclassified_or_automatically_resent(self):
  r=Runner();task=self.make(r)
  old={'execution_error':{'type':'TimeoutError','phase':'restoring','send_confirmed':False}}
  update_task(task['id'],status='uncertain',metrics=json.dumps(old));before=self.saved()
  with patch.object(r.browser,'send',new=AsyncMock()) as send:await r.tick();send.assert_not_awaited()
  self.assertEqual(self.saved(),before)


if __name__=='__main__':unittest.main()
