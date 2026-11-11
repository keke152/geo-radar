"""Preparation/send boundary checks use mocks and never open provider sites."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import test_workspace
from browser_bridge import BrowserBridge,NeedsSetup
from config import default_platform,PLATFORMS


class BrowserPreparationTests(unittest.IsolatedAsyncioTestCase):
 def make_bridge(self,send_key=''):
  bridge=BrowserBridge()
  page=SimpleNamespace(url=PLATFORMS['deepseek']['url'],is_closed=lambda:False,screenshot=AsyncMock())
  bridge.pages['deepseek']=page
  new=SimpleNamespace(click=AsyncMock())
  editor=SimpleNamespace(is_editable=AsyncMock(return_value=True),fill=AsyncMock(),press=AsyncMock())
  button=SimpleNamespace(is_enabled=AsyncMock(return_value=True),click=AsyncMock())
  controls={'composer_empty':True,'send_found':True,'controls':{'new_chat_selector':{'found':True,'selector':'#new'},'send_button':{'selector':'#send'}}}
  bridge.inspect=AsyncMock(return_value=controls)
  bridge.first_visible=AsyncMock(side_effect=lambda p,css:{'#new':new,'#input':editor,'#send':button}.get(css))
  bridge.response_snapshot=AsyncMock(return_value={'user_count':0,'answer':'fixture answer','matched':True,'done':True,'busy':False,'association':'structured','links':[]})
  cfg={**default_platform('deepseek'),'ready':True,'composer':'#input','new_chat_selector':'#new','send_button':'' if send_key else '#send','send_key':send_key}
  return bridge,cfg,new,editor,button

 async def test_minimized_native_window_is_restored_without_changing_bounds(self):
  bridge=BrowserBridge();page=object()
  session=SimpleNamespace(send=AsyncMock(return_value={'windowId':31,'bounds':{'windowState':'minimized','width':800,'height':600}}),detach=AsyncMock())
  bridge.contexts['kimi']=SimpleNamespace(new_cdp_session=AsyncMock(return_value=session))
  result=await bridge._ensure_interactable_window('kimi',page)
  self.assertTrue(result['restored']);self.assertEqual(result['previous_state'],'minimized')
  self.assertEqual(session.send.await_args_list[0].args,('Browser.getWindowForTarget',))
  self.assertEqual(session.send.await_args_list[1].args,('Browser.setWindowBounds',{'windowId':31,'bounds':{'windowState':'normal'}}))
  session.detach.assert_awaited_once()

 async def test_normal_or_maximized_native_window_is_not_resized(self):
  for state in ('normal','maximized','fullscreen'):
   with self.subTest(state=state):
    bridge=BrowserBridge();page=object()
    session=SimpleNamespace(send=AsyncMock(return_value={'windowId':31,'bounds':{'windowState':state}}),detach=AsyncMock())
    bridge.contexts['kimi']=SimpleNamespace(new_cdp_session=AsyncMock(return_value=session))
    result=await bridge._ensure_interactable_window('kimi',page)
    self.assertFalse(result['restored']);self.assertEqual(result['state'],state)
    session.send.assert_awaited_once_with('Browser.getWindowForTarget');session.detach.assert_awaited_once()

 async def test_unsupported_native_window_protocol_does_not_break_diagnostics(self):
  bridge=BrowserBridge();page=object()
  session=SimpleNamespace(send=AsyncMock(side_effect=RuntimeError('not supported')),detach=AsyncMock())
  bridge.contexts['kimi']=SimpleNamespace(new_cdp_session=AsyncMock(return_value=session))
  result=await bridge._ensure_interactable_window('kimi',page)
  self.assertFalse(result['checked']);session.detach.assert_awaited_once()

 async def test_minimized_window_restore_failure_explains_no_send(self):
  bridge=BrowserBridge();page=object()
  session=SimpleNamespace(send=AsyncMock(side_effect=[{'windowId':31,'bounds':{'windowState':'minimized'}},RuntimeError('fixture')]),detach=AsyncMock())
  bridge.contexts['kimi']=SimpleNamespace(new_cdp_session=AsyncMock(return_value=session))
  with self.assertRaisesRegex(NeedsSetup,'最小化.*尚未触发发送'):await bridge._ensure_interactable_window('kimi',page)
  session.detach.assert_awaited_once()

 async def test_empty_editor_hidden_send_button_does_not_block_session_restore(self):
  bridge=BrowserBridge();cfg={**default_platform('kimi'),'ready':True,'send_button':'#send','new_chat_selector':'#new'}
  state={'composer_editable':True,'composer_empty':True,'send_found':False,'new_chat_found':True,'controls':{'send_button':{'state':'missing_when_empty'}}}
  with patch.object(bridge,'profile_saved',return_value=True),patch.object(bridge,'connect',new=AsyncMock()),patch.object(bridge,'inspect',new=AsyncMock(return_value=state)):
   self.assertEqual(await bridge.restore_session('kimi',cfg),state)

 async def test_missing_send_button_with_existing_text_still_blocks_restore(self):
  bridge=BrowserBridge();cfg={**default_platform('kimi'),'ready':True,'send_button':'#send','new_chat_selector':'#new'}
  state={'composer_editable':True,'composer_empty':False,'send_found':False,'new_chat_found':True,'controls':{'send_button':{'state':'missing'}}}
  with patch.object(bridge,'profile_saved',return_value=True),patch.object(bridge,'connect',new=AsyncMock()),patch.object(bridge,'inspect',new=AsyncMock(return_value=state)):
   with self.assertRaises(NeedsSetup):await bridge.restore_session('kimi',cfg)

 async def test_restore_timeout_has_specific_unsent_error(self):
  bridge=BrowserBridge();cfg={**default_platform('kimi'),'ready':True}
  with patch.object(bridge,'profile_saved',return_value=True),patch.object(bridge,'connect',new=AsyncMock(side_effect=TimeoutError('fixture'))):
   with self.assertRaisesRegex(NeedsSetup,'恢复浏览器与检查输入框操作超时') as caught:await bridge.restore_session('kimi',cfg)
  self.assertFalse(caught.exception.send_attempted)

 async def test_existing_draft_is_not_overwritten_or_sent(self):
  bridge,cfg,new,editor,button=self.make_bridge();bridge.inspect.return_value={'composer_empty':False}
  sent=[];attempt=[]
  with self.assertRaisesRegex(NeedsSetup,'未发送草稿'):await bridge.send('deepseek',cfg,'fixture','visibility',lambda:sent.append(1),lambda:attempt.append(1))
  self.assertEqual(sent,[]);self.assertEqual(attempt,[])
  new.click.assert_not_awaited();editor.fill.assert_not_awaited();button.click.assert_not_awaited()

 async def test_continue_mode_also_preserves_existing_draft(self):
  bridge,cfg,new,editor,button=self.make_bridge();cfg['conversation_mode']='continue';bridge.inspect.return_value={'composer_empty':False}
  with self.assertRaisesRegex(NeedsSetup,'未发送草稿'):await bridge.send('deepseek',cfg,'fixture','visibility',lambda:None)
  new.click.assert_not_awaited();editor.fill.assert_not_awaited();button.click.assert_not_awaited()

 async def test_draft_appearing_during_preparation_is_not_overwritten(self):
  bridge,cfg,new,editor,button=self.make_bridge();bridge.inspect.side_effect=[bridge.inspect.return_value,{'composer_empty':False}]
  attempts=[]
  with self.assertRaisesRegex(NeedsSetup,'准备期间输入框出现了未发送草稿'):await bridge.send('deepseek',cfg,'fixture','visibility',lambda:None,lambda:attempts.append(1))
  editor.fill.assert_not_awaited();button.click.assert_not_awaited();self.assertEqual(attempts,[])

 async def test_fresh_mode_waits_for_old_conversation_to_clear_before_fill(self):
  bridge,cfg,new,editor,button=self.make_bridge();bridge.response_snapshot.return_value={'user_count':2,'assistant_count':2,'answer':''}
  attempts=[]
  with patch('browser_bridge.asyncio.sleep',new=AsyncMock()):
   with self.assertRaisesRegex(NeedsSetup,'新对话.*尚未就绪'):await bridge.send('deepseek',cfg,'fixture','visibility',lambda:None,lambda:attempts.append(1))
  editor.fill.assert_not_awaited();button.click.assert_not_awaited();self.assertEqual(attempts,[])

 async def test_new_chat_timeout_never_crosses_send_boundary(self):
  bridge,cfg,new,editor,button=self.make_bridge();new.click.side_effect=TimeoutError('fixture')
  sent=[];attempt=[]
  with self.assertRaisesRegex(NeedsSetup,'打开新对话操作超时'):await bridge.send('deepseek',cfg,'fixture','visibility',lambda:sent.append(1),lambda:attempt.append(1))
  new.click.assert_awaited_once_with(timeout=8000,no_wait_after=True)
  editor.fill.assert_not_awaited();button.click.assert_not_awaited()
  self.assertEqual(sent,[]);self.assertEqual(attempt,[])

 async def test_filling_timeout_is_unsent_with_step_name(self):
  bridge,cfg,new,editor,button=self.make_bridge();editor.fill.side_effect=TimeoutError('fixture')
  sent=[];attempt=[]
  with self.assertRaisesRegex(NeedsSetup,'读取原会话与填写问题操作超时'):await bridge.send('deepseek',cfg,'fixture','visibility',lambda:sent.append(1),lambda:attempt.append(1))
  self.assertEqual(sent,[]);self.assertEqual(attempt,[]);button.click.assert_not_awaited()

 async def test_doubao_known_empty_welcome_does_not_click_redundant_new_chat(self):
  bridge,cfg,new,editor,button=self.make_bridge();page=bridge.pages.pop('deepseek');bridge.pages['doubao']=page
  page.url=PLATFORMS['doubao']['url'];page.evaluate=AsyncMock(return_value=True)
  bridge.inspect.return_value['composer_editable']=True
  editor.fill.side_effect=TimeoutError('stop before any send')
  with self.assertRaisesRegex(NeedsSetup,'读取原会话与填写问题操作超时'):
   await bridge.send('doubao',cfg,'fixture','visibility',lambda:None)
  new.click.assert_not_awaited();button.click.assert_not_awaited();page.evaluate.assert_awaited_once()

 async def test_doubao_existing_conversation_or_query_never_skips_new_chat(self):
  for url,probe in [(PLATFORMS['doubao']['url']+'?session=old',True),(PLATFORMS['doubao']['url'],False)]:
   with self.subTest(url=url,probe=probe):
    bridge,cfg,new,editor,button=self.make_bridge();page=bridge.pages.pop('deepseek');bridge.pages['doubao']=page
    page.url=url;page.evaluate=AsyncMock(return_value=probe);bridge.inspect.return_value['composer_editable']=True
    new.click.side_effect=TimeoutError('stop before send')
    with self.assertRaisesRegex(NeedsSetup,'打开新对话操作超时'):await bridge.send('doubao',cfg,'fixture','visibility',lambda:None)
    new.click.assert_awaited_once();editor.fill.assert_not_awaited();button.click.assert_not_awaited()

 async def test_send_click_timeout_is_not_retried_or_labelled_preparation(self):
  bridge,cfg,new,editor,button=self.make_bridge();button.click.side_effect=TimeoutError('fixture')
  sent=[];attempt=[]
  with self.assertRaises(TimeoutError):await bridge.send('deepseek',cfg,'fixture','visibility',lambda:sent.append(1),lambda:attempt.append(1))
  button.click.assert_awaited_once_with(timeout=10000,no_wait_after=True)
  self.assertEqual(attempt,[1]);self.assertEqual(sent,[])

 async def test_send_shortcut_timeout_also_crosses_boundary_once(self):
  bridge,cfg,new,editor,button=self.make_bridge(send_key='Enter');editor.press.side_effect=TimeoutError('fixture')
  sent=[];attempt=[]
  with self.assertRaises(TimeoutError):await bridge.send('deepseek',cfg,'fixture','visibility',lambda:sent.append(1),lambda:attempt.append(1))
  editor.press.assert_awaited_once_with('Enter',timeout=10000,no_wait_after=True)
  button.click.assert_not_awaited();self.assertEqual(attempt,[1]);self.assertEqual(sent,[])

 async def test_successful_send_reports_attempt_before_action_and_confirmation_after(self):
  bridge,cfg,new,editor,button=self.make_bridge();events=[]
  button.click.side_effect=lambda **kwargs:events.append('action')
  counter=iter(range(100))
  with patch('browser_bridge.asyncio.sleep',new=AsyncMock()),patch('browser_bridge.time.monotonic',side_effect=lambda:next(counter)):
   result=await bridge.send('deepseek',cfg,'fixture','visibility',lambda:events.append('confirmed'),lambda:events.append('attempt'))
  self.assertEqual(events,['attempt','action','confirmed']);self.assertEqual(result['answer'],'fixture answer')
  button.click.assert_awaited_once();editor.fill.assert_awaited_once_with('fixture',timeout=10000)
