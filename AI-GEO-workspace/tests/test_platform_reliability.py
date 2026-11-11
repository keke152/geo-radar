"""Session reuse and human-verification barriers; no live platform requests."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock

import test_workspace
from browser_bridge import BrowserBridge,NeedsSetup
from config import default_platform,DEFAULT_SETTINGS
from engine import Runner,create_batch
from page_guard import PAGE_GUARD_RESULTS
from storage import db,init,set_meta,records,ident


class PlatformReliabilityTests(unittest.IsolatedAsyncioTestCase):
 async def test_reconnect_keeps_existing_zhihu_login_tab_without_navigation(self):
  bridge=BrowserBridge();bridge.playwright=object()
  page=SimpleNamespace(url='https://www.zhihu.com/signin?next=%2F',is_closed=lambda:False,goto=AsyncMock(),bring_to_front=AsyncMock())
  bridge.contexts['zhihu']=SimpleNamespace(pages=[page])
  self.assertIs(await bridge.connect('zhihu'),page)
  self.assertIs(await bridge.connect('zhihu'),page)
  page.goto.assert_not_awaited()
  with self.assertRaises(NeedsSetup):bridge.valid_page('zhihu',page)

 async def test_navigation_failures_back_off_instead_of_reloading_repeatedly(self):
  bridge=BrowserBridge();bridge.playwright=object()
  page=SimpleNamespace(url='about:blank',is_closed=lambda:False,goto=AsyncMock(side_effect=TimeoutError()),bring_to_front=AsyncMock())
  bridge.contexts['deepseek']=SimpleNamespace(pages=[page])
  await bridge.connect('deepseek');await bridge.connect('deepseek')
  self.assertEqual(page.goto.await_count,1)
  self.assertGreater(bridge.connection_state('deepseek')['navigation_retry_seconds'],0)
  bridge.navigation_retries['deepseek']['next']=time.monotonic()-1
  await bridge.connect('deepseek')
  self.assertEqual(page.goto.await_count,2)
  self.assertGreater(bridge.connection_state('deepseek')['navigation_retry_seconds'],50)

 async def test_login_parameter_error_blocks_before_any_send_attempt(self):
  bridge=BrowserBridge()
  page=SimpleNamespace(url='https://www.zhihu.com/signin',is_closed=lambda:False,evaluate=AsyncMock(return_value=PAGE_GUARD_RESULTS['zhihu_login_parameter_error']))
  bridge.pages['zhihu']=page
  sent,attempt=Mock(),Mock()
  cfg={**default_platform('zhihu'),'ready':True,'send_key':'Enter','new_chat_selector':'#new'}
  with self.assertRaises(NeedsSetup) as raised:
   await bridge.send('zhihu',cfg,'a question','visibility',sent,attempt)
  self.assertIn('10001',str(raised.exception))
  sent.assert_not_called();attempt.assert_not_called()

 async def test_recognized_challenge_holds_queued_tasks_for_manual_continue(self):
  init()
  with db() as c:
   c.execute('DELETE FROM tasks');c.execute('DELETE FROM batches')
  set_meta('settings',DEFAULT_SETTINGS)
  set_meta('platform:deepseek',{**default_platform('deepseek'),'ready':True,'send_key':'Enter','new_chat_selector':'#new'})
  create_batch(['fixture question'],['deepseek'],'visibility',ident())
  runner=Runner()
  runner.browser.pages['deepseek']=SimpleNamespace(url='https://chat.deepseek.com/',is_closed=lambda:False)
  runner.browser.page_guards['deepseek']=dict(PAGE_GUARD_RESULTS['security_verification'])
  runner.browser.send=AsyncMock()
  await runner.tick()
  task=records('tasks')[0]
  self.assertEqual(task['status'],'waiting_setup')
  self.assertIn('本人',task['note'])
  runner.browser.send.assert_not_awaited()


if __name__=='__main__':unittest.main()
