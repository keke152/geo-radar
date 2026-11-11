import asyncio,io,json,os,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace
import httpx

temporary=tempfile.TemporaryDirectory(prefix='junhe-tests-')
os.environ['JUNHE_HOME']=temporary.name
os.environ['JUNHE_DISABLE_WORKER']='1'
from fastapi.testclient import TestClient
import app,engine
from config import DEFAULT_PROFILE,DEFAULT_SETTINGS,PLATFORMS,default_platform
from storage import db,init,ident,now,get_meta,set_meta,records,update_task
from domain import analyze,make_prompt,brand_hint,public_pack
from engine import create_batch,Runner
from browser_bridge import browser_launch_failure
from providers import api_send

HEADERS={'X-Workspace-Request':'junhe-local'}

class InsightsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.context=TestClient(app.app,base_url='http://127.0.0.1:8020');cls.client=cls.context.__enter__()
 @classmethod
 def tearDownClass(cls):cls.context.__exit__(None,None,None)
 def setUp(self):
  with db() as c:
   for table in ('tasks','batches','schedules','documents','keywords','meta'):c.execute('DELETE FROM '+table)
  init()
 def task(self,**changes):
  task={'id':ident(),'batch_id':'fixture','platform':'doubao','channel':'web','mode':'visibility',
        'keyword':'益生菌食品合作品牌怎么选择','prompt':'fixture','status':'completed',
        'answer':'广微·益森日纪，由广州菌和生物科技有限公司开展品牌运营。https://www.junheprobio.com/。',
        'note':'','screenshot':'','metrics':'{}','reviewed':1,'sent_at':now(),'created_at':now(),'updated_at':now()}
  task.update(changes)
  with db() as c:
   c.execute('INSERT INTO tasks('+','.join(task)+') VALUES('+','.join('?' for _ in task)+')',list(task.values()))
  return task
 def test_brand_and_company_are_independent(self):
  brand=analyze('广微 益森日纪',DEFAULT_PROFILE)
  self.assertTrue(brand['brand_name_mentioned']);self.assertFalse(brand['company_mentioned'])
  company=analyze('菌和生物',DEFAULT_PROFILE)
  self.assertTrue(company['company_mentioned']);self.assertFalse(company['brand_name_mentioned'])
  self.assertFalse(analyze('广微集团',DEFAULT_PROFILE)['brand_name_mentioned'])
  for name in ['广微·益森日纪','广微益森日纪','益森日纪']:
   self.assertTrue(analyze(name,DEFAULT_PROFILE)['brand_name_mentioned'])
   self.assertTrue(brand_hint(name+'官网',DEFAULT_PROFILE))
 def test_official_link_punctuation_and_spoofed_host(self):
  self.assertTrue(analyze('来源 https://www.junheprobio.com。',DEFAULT_PROFILE)['official_link_present'])
  self.assertFalse(analyze('https://www.junheprobio.com.evil.example/',DEFAULT_PROFILE)['official_link_present'])
 def test_only_reviewed_natural_completed_answers_count(self):
  self.task()
  self.task(answer='菌和生物',platform='kimi')
  self.task(status='needs_review',reviewed=0)
  self.task(status='failed',reviewed=1)
  self.task(mode='materials')
  self.task(keyword='益森日纪怎么样',metrics='{"brand_hint":false}')
  self.task(keyword='行业问题',metrics='{"brand_hint":true}')
  self.task(answer=' ')
  self.task(channel='api',platform='deepseek')
  report=self.client.get('/api/insights').json()
  self.assertEqual(report['totals']['samples'],2)
  self.assertEqual(report['totals']['brand_mentions'],1)
  self.assertEqual(report['totals']['company_mentions'],2)
  self.assertEqual(report['totals']['official_links'],1)
  self.assertEqual(report['totals']['brand_rate'],50.0)
  self.assertEqual(report['excluded'],{'materials':1,'branded':2,'unreviewed':2,'empty_answer':1,'continuation':0,'source_directed':0})
  self.assertEqual(self.client.get('/api/insights?channel=api').json()['totals']['samples'],1)
 def test_empty_report_has_no_fabricated_rate(self):
  report=self.client.get('/api/insights').json()
  self.assertIsNone(report['totals']['brand_rate'])
  self.assertEqual(report['totals']['samples'],0)
  self.assertEqual(len(report['platforms']),len(PLATFORMS))
  self.assertTrue(report['actions'])
 def test_same_question_uses_newest_reviewed_response_only(self):
  from insights import build_insights
  from datetime import date
  old=self.task(sent_at='2026-11-01T01:00:00+00:00',answer='未提及')
  latest=self.task(sent_at='2026-11-02T01:00:00+00:00')
  self.task(sent_at='2026-11-03T01:00:00+00:00',status='needs_review',reviewed=0)
  self.task(sent_at='2026-11-02T02:00:00+00:00',platform='kimi')
  self.task(sent_at='2026-11-02T02:00:00+00:00',keyword='另一个行业问题')
  r=build_insights(records('tasks'),DEFAULT_PROFILE,today=date(2026,11,3))
  self.assertEqual(r['totals']['questions'],2)
  q=next(q for q in r['questions'] if q['keyword']==old['keyword'])
  self.assertEqual(q['sample_count'],3)
  self.assertEqual(q['platforms']['doubao']['id'],latest['id'])
 def test_china_midnight_and_sent_date_define_report_window(self):
  self.task(created_at='2026-10-01T00:00:00+00:00',sent_at='2026-11-02T16:00:00+00:00')
  self.task(sent_at='2026-11-02T15:59:59+00:00')
  r=self.client.get('/api/insights?start_date=2026-11-03&end_date=2026-11-03').json()
  self.assertEqual(r['totals']['samples'],1)
  self.assertEqual(r['trend'][0]['samples'],1)
 def test_invalid_insight_filters_are_explained(self):
  for query in ['channel=other','platform=none','days=0','days=367','start_date=bad','start_date=2026-11-03&end_date=2026-11-02','start_date=2020-01-01&end_date=2026-11-03']:
   with self.subTest(query=query):self.assertEqual(self.client.get('/api/insights?'+query).status_code,422)
 def test_report_and_read_only_endpoints_never_send_or_change_tasks(self):
  self.task();before=records('tasks')
  with patch.object(app.runner.browser,'send',new=AsyncMock()) as send:
   self.assertEqual(self.client.get('/api/insights').status_code,200)
   response=self.client.get('/api/export/visibility.md')
   self.assertEqual(response.status_code,200)
   self.assertIn('广微 益森日纪',response.text)
   self.assertIn('统计口径',response.text)
   self.client.get('/api/tasks')
   self.assertEqual(before,records('tasks'));send.assert_not_awaited()
 def test_records_are_paginated_beyond_previous_150_limit(self):
  for i in range(165):self.task(keyword=f'问题 {i}',platform='kimi')
  first=self.client.get('/api/tasks?page_size=20').json()
  last=self.client.get('/api/tasks?page=9&page_size=20').json()
  self.assertEqual((first['total'],first['pages'],len(first['items'])),(165,9,20))
  self.assertEqual(len(last['items']),5)
  self.assertNotIn('prompt',first['items'][0]);self.assertNotIn('answer',first['items'][0])
  self.assertFalse(set(t['id'] for t in first['items']) & set(t['id'] for t in last['items']))
 def test_record_filters_and_csv_export_match_and_escape_wildcards(self):
  target=self.task(keyword='合作_100%检查',platform='kimi',status='waiting_setup',reviewed=0)
  self.task(keyword='合作X100ABC检查',platform='kimi')
  self.task(keyword=target['keyword'],platform='doubao')
  response=self.client.get('/api/tasks',params={'q':'_100%','platform':'kimi','status':'waiting_setup'}).json()
  self.assertEqual(response['total'],1);self.assertEqual(response['items'][0]['id'],target['id'])
  csv=self.client.get('/api/export/tasks.csv',params={'q':'_100%','platform':'kimi','status':'waiting_setup'}).text
  self.assertIn(target['keyword'],csv);self.assertNotIn('合作X100ABC检查',csv)
  for query in ['status=bad','platform=bad','channel=bad','mode=bad','page=0','page_size=101']:
   self.assertEqual(self.client.get('/api/tasks?'+query).status_code,422)
 def test_migration_adds_brand_fields_without_overwriting_existing_profile(self):
  old={k:v for k,v in DEFAULT_PROFILE.items() if not k.startswith('brand_')};old['business']='已修改的主营'
  set_meta('profile',old);before=get_meta('settings');self.task(status='waiting_setup',reviewed=0)
  tasks=records('tasks');init()
  self.assertEqual(get_meta('profile')['business'],'已修改的主营')
  self.assertEqual(get_meta('profile')['brand_name'],'广微 益森日纪')
  self.assertEqual(before,get_meta('settings'));self.assertEqual(tasks,records('tasks'))
 def test_profile_brand_fields_survive_older_client_save(self):
  profile={**DEFAULT_PROFILE,'brand_name':'自定义合作品牌','brand_aliases':['合作品牌']}
  self.assertEqual(self.client.put('/api/profile',json=profile,headers=HEADERS).status_code,200)
  legacy={k:v for k,v in DEFAULT_PROFILE.items() if not k.startswith('brand_')}
  self.client.put('/api/profile',json=legacy,headers=HEADERS)
  self.assertEqual(get_meta('profile')['brand_name'],'自定义合作品牌')
  self.assertEqual(get_meta('profile')['brand_aliases'],['合作品牌'])
 def test_daily_budget_counts_created_tasks_even_if_cancelled(self):
  set_meta('settings',{**DEFAULT_SETTINGS,'daily_limit':5})
  self.task(status='cancelled');self.task(status='waiting_setup')
  self.task(created_at='2020-01-01T00:00:00+00:00')
  budget=self.client.get('/api/bootstrap').json()['daily_budget']
  self.assertEqual((budget['used'],budget['remaining'],budget['limit']),(2,3,5))

class WorkspaceTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.context=TestClient(app.app,base_url='http://127.0.0.1:8020');cls.client=cls.context.__enter__()
 @classmethod
 def tearDownClass(cls):cls.context.__exit__(None,None,None)
 def setUp(self):
  with db() as c:
   for table in ('tasks','batches','schedules','documents','keywords','meta'):c.execute('DELETE FROM '+table)
  init()
 def post(self,url,body):return self.client.post(url,json=body,headers=HEADERS)
 def make(self,keyword='广州益生菌食品企业有哪些',mode='visibility',platforms=None):
  return create_batch([keyword],platforms or ['deepseek'],mode,ident())
 def test_health_and_seed_facts(self):
  self.assertEqual(self.client.get('/api/health').status_code,200)
  data=self.client.get('/api/bootstrap').json()
  self.assertEqual(data['profile']['company_name'],'广州菌和生物科技有限公司')
  self.assertEqual(len(data['platforms']),len(PLATFORMS))
  self.assertEqual(sum(d['approved'] for d in data['documents']),1)
 def test_login_button_empty_body_reaches_all_web_connectors(self):
  for pid in PLATFORMS:
   if PLATFORMS[pid].get('cli'):continue
   with self.subTest(platform=pid),patch.object(app.runner.browser,'connect',new=AsyncMock()) as connect:
    response=self.post('/api/platforms/'+pid+'/connect',{})
    self.assertEqual(response.status_code,200,response.text)
    connect.assert_awaited_once_with(pid)
    self.assertFalse(response.json()['connection']['login_verified'])
 def test_inspect_close_and_pick_poll_accept_empty_body(self):
  for action in ('inspect','close','picked'):
   response=self.post('/api/platforms/deepseek/'+action,{})
   self.assertEqual(response.status_code,200,response.text)
 def test_pick_still_requires_a_valid_kind(self):
  self.assertEqual(self.post('/api/platforms/deepseek/pick',{}).status_code,422)
  self.assertEqual(self.post('/api/platforms/deepseek/pick',{'kind':'unknown'}).status_code,422)
 def test_browser_startup_error_remains_actionable(self):
  from browser_bridge import NeedsSetup
  with patch.object(app.runner.browser,'connect',new=AsyncMock(side_effect=NeedsSetup('请安装Microsoft Edge'))):
   response=self.post('/api/platforms/deepseek/connect',{})
  self.assertEqual(response.status_code,409)
  self.assertEqual(response.json()['detail'],'请安装Microsoft Edge')
 def test_navigation_failure_reports_open_window_instead_of_login_success(self):
  state={'open':True,'url':'about:blank','navigation_error':'network','login_verified':False}
  with patch.object(app.runner.browser,'connect',new=AsyncMock()),patch.object(app.runner.browser,'connection_state',return_value=state):
   result=self.post('/api/platforms/doubao/connect',{}).json()
  self.assertIn('网页尚未正常加载',result['message'])
  self.assertFalse(result['connection']['login_verified'])
 def test_mutation_guard(self):
  self.assertEqual(self.client.post('/api/keywords',json={'text':'x'}).status_code,403)
  self.assertEqual(self.client.post('/api/keywords',json={'text':'x'},headers={**HEADERS,'Origin':'https://evil.example'}).status_code,403)
 def test_visibility_has_no_company_context(self):
  prompt=make_prompt('益生菌食品企业有哪些','visibility')
  self.assertNotIn('广州菌和',prompt);self.assertNotIn('junheprobio',prompt)
 def test_materials_excludes_unapproved_claims(self):
  prompt=make_prompt('整理资料','materials')
  self.assertIn('广州菌和',prompt)
  for text in ('旁门医疗','广微·益森日纪','CMA','CNAS','专利','治疗'):
   self.assertNotIn(text,prompt)
 def test_empty_approved_docs_blocks_materials(self):
  with db() as c:c.execute('UPDATE documents SET approved=0')
  with self.assertRaises(ValueError):make_prompt('x','materials')
 def test_brand_hint(self):
  self.assertTrue(brand_hint('广州菌和生物科技有限公司 官网',DEFAULT_PROFILE))
  self.assertFalse(brand_hint('益生菌食品经销合作',DEFAULT_PROFILE))
 def test_domain_matching_is_exact(self):
  self.assertTrue(analyze('广州菌和生物科技有限公司 https://www.junheprobio.com/about',DEFAULT_PROFILE)['official_link_present'])
  self.assertFalse(analyze('https://www.junheprobio.com.evil.example/',DEFAULT_PROFILE)['official_link_present'])
 def test_batch_idempotency(self):
  key=ident();first=create_batch(['x'],['deepseek'],'visibility',key);second=create_batch(['x'],['deepseek'],'visibility',key)
  self.assertEqual(first['batch_id'],second['batch_id']);self.assertEqual(len(records('tasks')),1)
  with self.assertRaises(ValueError):create_batch(['y'],['deepseek'],'visibility',key)
 def test_api_batch_immediately_explains_unconnected_platforms(self):
  result=self.post('/api/batches',{'keywords':['测试排队原因'],'platforms':['deepseek'],'mode':'visibility','request_key':ident()})
  self.assertEqual(result.status_code,200,result.text)
  self.assertEqual(result.json()['waiting_setup'],1)
  self.assertEqual(result.json()['queue']['queued'],0)
  self.assertTrue(all(t['status']=='waiting_setup' and '专用窗口未连接' in t['note'] for t in records('tasks')))
 def test_queue_positions_follow_creation_order_for_equal_timestamps(self):
  create_batch(['问题一'],['deepseek','kimi','doubao'],'visibility',ident())
  state=Runner().snapshot()
  with db() as c:ordered=[dict(r) for r in c.execute('SELECT id,platform FROM tasks ORDER BY created_at,rowid')]
  self.assertEqual([r['platform'] for r in ordered],['deepseek','kimi','doubao'])
  self.assertEqual([state['positions'][r['id']] for r in ordered],[1,1,1])
 def test_daily_limit_and_atomicity(self):
  set_meta('settings',{**DEFAULT_SETTINGS,'daily_limit':1})
  with self.assertRaises(ValueError):create_batch(['x'],['deepseek','kimi'],'visibility',ident())
  self.assertEqual(len(records('tasks')),0)
  self.make()
  with self.assertRaises(ValueError):self.make()
 def test_unsupported_api_is_not_substituted(self):
  response=self.client.put('/api/platforms/yuanbao',json={'channel':'api'},headers=HEADERS)
  self.assertEqual(response.status_code,422)
 def test_ready_save_without_send_rule_is_rejected_and_not_persisted(self):
  before=get_meta('platform:doubao')
  response=self.client.put('/api/platforms/doubao',json={**before,'ready':True},headers=HEADERS)
  self.assertEqual(response.status_code,422)
  self.assertIn('发送按钮或发送快捷键',response.json()['detail'])
  self.assertEqual(get_meta('platform:doubao'),before)
 def test_draft_save_returns_values_timestamp_and_missing_items(self):
  response=self.client.put('/api/platforms/doubao',json={**default_platform('doubao'),'new_chat_selector':'#new'},headers=HEADERS)
  self.assertEqual(response.status_code,200,response.text)
  result=response.json()
  self.assertEqual(result['config']['new_chat_selector'],'#new')
  self.assertTrue(result['saved_at'])
  self.assertFalse(result['readiness']['enabled'])
  self.assertIn('发送按钮或发送快捷键',result['readiness']['missing'])
  self.assertIn('草稿',result['message'])
 def test_ready_save_checks_actual_editable_composer_before_persisting(self):
  before=get_meta('platform:doubao');cfg={**before,'composer':'#wrong','send_key':'Enter','ready':True}
  state={'open':True,'composer_found':True,'composer_editable':False,'send_found':False,'new_chat_found':False}
  with patch.object(app.runner.browser,'inspect',new=AsyncMock(return_value=state)):
   response=self.client.put('/api/platforms/doubao',json=cfg,headers=HEADERS)
  self.assertEqual(response.status_code,409)
  self.assertIn('可编辑输入框',response.json()['detail'])
  self.assertEqual(get_meta('platform:doubao'),before)
 def test_ready_save_returns_verified_config_without_sending(self):
  cfg={**default_platform('doubao'),'composer':'#text','send_key':'Enter','new_chat_selector':'#new','ready':True}
  state={'open':True,'composer_found':True,'composer_editable':True,'composer_in_view':True,'send_found':False,'new_chat_found':True}
  with patch.object(app.runner.browser,'inspect',new=AsyncMock(return_value=state)) as inspect,patch.object(app.runner.browser,'send',new=AsyncMock()) as send:
   response=self.client.put('/api/platforms/doubao',json=cfg,headers=HEADERS)
   inspect.assert_awaited_once();send.assert_not_awaited()
  self.assertEqual(response.status_code,200,response.text)
  result=response.json();self.assertTrue(result['readiness']['visibility_ready'])
  self.assertEqual(result['config']['send_key'],'Enter')
  self.assertEqual(get_meta('platform:doubao')['composer'],'#text')
 def test_ready_save_with_stale_new_chat_does_not_overwrite_config(self):
  cfg={**default_platform('doubao'),'send_key':'Enter','new_chat_selector':'#stale','ready':True}
  state={'open':True,'composer_found':True,'composer_editable':True,'send_found':False,'new_chat_found':False}
  with patch.object(app.runner.browser,'inspect',new=AsyncMock(return_value=state)):
   response=self.client.put('/api/platforms/doubao',json=cfg,headers=HEADERS)
  self.assertEqual(response.status_code,409)
  self.assertIn('新对话按钮已失效',response.json()['detail'])
  self.assertFalse(get_meta('platform:doubao')['ready'])
 def test_send_rule_matching_editor_cannot_enable_platform(self):
  cfg={**default_platform('kimi'),'composer':'#editor','send_button':'#editor','ready':True}
  state={'open':True,'composer_found':True,'composer_editable':True,'send_found':False,'controls':{'send_button':{'state':'wrong_target','message':'选中了输入框，并非发送按钮'}}}
  with patch.object(app.runner.browser,'inspect',new=AsyncMock(return_value=state)):
   result=self.client.put('/api/platforms/kimi',json=cfg,headers=HEADERS)
  self.assertEqual(result.status_code,409)
  self.assertIn('并非发送按钮',result.json()['detail'])
  self.assertFalse(get_meta('platform:kimi')['ready'])
 def test_save_normalizes_svg_to_real_outer_button(self):
  cfg={**default_platform('kimi'),'composer':'#editor','send_button':'#send-svg','ready':True}
  state={'open':True,'composer_found':True,'composer_editable':True,'send_found':True,'controls':{'send_button':{'state':'awaiting_text','normalized':True,'selector':'button[data-testid="send"]','found':True}}}
  with patch.object(app.runner.browser,'inspect',new=AsyncMock(return_value=state)):
   result=self.client.put('/api/platforms/kimi',json=cfg,headers=HEADERS)
  self.assertEqual(result.status_code,200,result.text)
  self.assertEqual(get_meta('platform:kimi')['send_button'],'button[data-testid="send"]')
 def test_diagnose_is_read_only_and_uses_current_form(self):
  before=get_meta('platform:kimi');cfg={**before,'send_button':'#svg'}
  state={'open':True,'suggestions':{'send_button':'#button'}}
  with patch.object(app.runner.browser,'inspect',new=AsyncMock(return_value=state)) as inspect,patch.object(app.runner.browser,'send',new=AsyncMock()) as send:
   response=self.post('/api/platforms/kimi/diagnose',{'config':cfg})
   inspect.assert_awaited_once_with('kimi',{k:v for k,v in cfg.items() if k!='id'},include_candidates=True)
   send.assert_not_awaited()
  self.assertEqual(response.status_code,200)
  self.assertEqual(get_meta('platform:kimi'),before)
 def test_inspect_uses_unsaved_form_rules(self):
  cfg={**default_platform('doubao'),'composer':'#unsaved-input'}
  with patch.object(app.runner.browser,'inspect',new=AsyncMock(return_value={'open':True})) as inspect:
   response=self.post('/api/platforms/doubao/inspect',{'config':cfg})
   inspect.assert_awaited_once_with('doubao',{k:v for k,v in cfg.items() if k!='id'})
  self.assertEqual(response.status_code,200)
  self.assertNotEqual(get_meta('platform:doubao')['composer'],'#unsaved-input')
 def test_picker_only_returns_draft_and_cannot_silently_overwrite_saved_config(self):
  before=get_meta('platform:doubao')
  for result in ({'kind':'composer','invalid':True,'error':'not editable'},{'kind':'composer','selector':'#draft'}):
   with patch.object(app.runner.browser,'picked',new=AsyncMock(return_value=result)):
    response=self.post('/api/platforms/doubao/picked',{})
   self.assertEqual(response.status_code,200)
   self.assertEqual(get_meta('platform:doubao'),before)
 def test_cancel_picker_endpoint_accepts_empty_body(self):
  with patch.object(app.runner.browser,'cancel_pick',new=AsyncMock()) as cancel:
   response=self.post('/api/platforms/doubao/cancel-pick',{})
   cancel.assert_awaited_once_with('doubao')
  self.assertEqual(response.status_code,200)
 def test_profile_busy_error_is_not_reported_as_missing_edge(self):
  code,message=browser_launch_failure(RuntimeError('process did exit: exitCode=21'))
  self.assertEqual(code,'profile_busy')
  self.assertIn('另一个进程',message)
  self.assertNotIn('请安装',message)
 def test_edge_missing_is_reported_only_for_missing_executable(self):
  code,message=browser_launch_failure(RuntimeError("Executable doesn't exist"))
  self.assertEqual(code,'edge_missing')
  self.assertIn('请安装',message)
 def test_close_does_not_claim_to_have_closed_an_unowned_window(self):
  result=self.post('/api/platforms/doubao/close',{})
  self.assertIn('未接管',result.json()['message'])
 def test_capture_cannot_read_or_complete_an_unsent_task(self):
  self.make(platforms=['doubao']);task=records('tasks')[0]
  with patch.object(app.runner.browser,'capture_existing',new=AsyncMock()) as capture:
   result=self.post('/api/tasks/'+task['id']+'/capture',{})
   capture.assert_not_awaited()
  self.assertEqual(result.status_code,409)
 def test_verify_complete_capture_records_without_resending(self):
  self.make(platforms=['doubao']);task=records('tasks')[0]
  url='https://www.doubao.com/chat/12345'
  update_task(task['id'],status='sent',sent_at=now(),metrics=json.dumps({'conversation_url':url}))
  result={'answer':'complete fixture','matched':True,'association':'structured','done':True,'busy':False,'stable':True,'conversation_url':url}
  with patch.object(app.runner.browser,'capture_verified',new=AsyncMock(return_value=result)) as capture,patch.object(app.runner.browser,'send',new=AsyncMock()) as send:
   response=self.post('/api/tasks/'+task['id']+'/verify',{})
   capture.assert_awaited_once_with('doubao',get_meta('platform:doubao'),task['prompt'],url);send.assert_not_awaited()
  self.assertTrue(response.json()['verified']);self.assertEqual(records('tasks')[0]['status'],'completed')
 def test_verify_partial_capture_preserves_existing_answer(self):
  self.make(platforms=['doubao']);task=records('tasks')[0]
  update_task(task['id'],status='completed',sent_at=now(),answer='original reviewed answer',reviewed=1)
  result={'answer':'partial fixture','matched':True,'association':'structured','done':False,'busy':True,'stable':False}
  with patch.object(app.runner.browser,'capture_verified',new=AsyncMock(return_value=result)):
   response=self.post('/api/tasks/'+task['id']+'/verify',{})
  self.assertFalse(response.json()['verified']);saved=records('tasks')[0]
  self.assertEqual(saved['answer'],'original reviewed answer');self.assertEqual(saved['status'],'completed');self.assertTrue(saved['reviewed'])
 def test_capture_uses_original_prompt_and_never_sends(self):
  self.make(platforms=['doubao']);task=records('tasks')[0]
  url='https://www.doubao.com/chat/12345'
  update_task(task['id'],status='sent',sent_at=now(),metrics=json.dumps({'brand_hint':False,'conversation_url':url}))
  captured={'answer':'原始问题的回答','conversation_url':url,'links':[],'later_turns':True,'note':'没有重新发送'}
  with patch.object(app.runner.browser,'capture_existing',new=AsyncMock(return_value=captured)) as capture,patch.object(app.runner.browser,'send',new=AsyncMock()) as send:
   result=self.post('/api/tasks/'+task['id']+'/capture',{})
   capture.assert_awaited_once_with('doubao',get_meta('platform:doubao'),task['prompt'],url)
   send.assert_not_awaited()
  self.assertEqual(result.status_code,200,result.text)
  saved=records('tasks')[0]
  self.assertEqual(saved['answer'],'原始问题的回答')
  self.assertEqual(saved['status'],'needs_review')
  self.assertFalse(saved['reviewed'])
 def test_review_keeps_conversation_link_for_capture_without_resend(self):
  self.make(platforms=['doubao']);task=records('tasks')[0]
  url='https://www.doubao.com/chat/12345'
  update_task(task['id'],status='needs_review',sent_at=now(),metrics=json.dumps({'brand_hint':False,'conversation_url':url,'answer_matched_to_prompt':True}))
  response=self.post('/api/tasks/'+task['id']+'/review',{'answer':'已核对的回答'})
  self.assertEqual(response.status_code,200)
  metrics=json.loads(records('tasks')[0]['metrics'])
  self.assertEqual(metrics['conversation_url'],url)
  self.assertTrue(metrics['answer_matched_to_prompt'])
 def test_waiting_task_can_retry_but_sent_cannot(self):
  self.make();task=records('tasks')[0]
  update_task(task['id'],status='sent')
  self.assertEqual(self.post('/api/tasks/'+task['id']+'/retry',{}).status_code,409)
  update_task(task['id'],status='waiting_setup')
  self.assertEqual(self.post('/api/tasks/'+task['id']+'/retry',{}).status_code,200)
 def test_review_cannot_fake_unexecuted_success(self):
  self.make();tid=records('tasks')[0]['id']
  self.assertEqual(self.post('/api/tasks/'+tid+'/review',{'answer':'fake'}).status_code,409)
 def test_materials_and_brand_queries_excluded_from_metrics(self):
  for keyword,mode in [('广州菌和生物科技有限公司 官网','visibility'),('企业有哪些','materials'),('企业有哪些','visibility')]:
   batch=self.make(keyword,mode)
   with db() as c:tid=c.execute('SELECT id FROM tasks WHERE batch_id=?',(batch['batch_id'],)).fetchone()['id']
   update_task(tid,status='sent')
   response=self.post('/api/tasks/'+tid+'/review',{'answer':'广州菌和生物科技有限公司 https://www.junheprobio.com/'})
   self.assertEqual(response.status_code,200,response.text)
  data=self.client.get('/api/bootstrap').json()
  self.assertEqual(data['metrics']['web']['samples'],1)
  self.assertEqual(data['metrics']['api']['samples'],0)
 def test_document_approval_roundtrip(self):
  response=self.post('/api/documents',{'title':'测试','body':'公开资料','source':'用户确认','approved':False})
  did=response.json()['id'];self.assertNotIn('公开资料',make_prompt('x','materials'))
  self.client.put('/api/documents/'+did,json={'title':'测试','body':'公开资料','source':'用户确认','approved':True},headers=HEADERS)
  self.assertIn('公开资料',make_prompt('x','materials'))
 def test_ppt_import_is_draft_and_does_not_keep_original(self):
  stream=io.BytesIO()
  with zipfile.ZipFile(stream,'w') as z:z.writestr('ppt/slides/slide1.xml','<a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>测试招商文字</a:t></a:p>')
  result=self.client.post('/api/documents/import',files={'file':('test.pptx',stream.getvalue())},headers=HEADERS)
  self.assertEqual(result.status_code,200)
  document=next(d for d in records('documents') if '测试招商文字' in d['body'])
  self.assertFalse(document['approved']);self.assertFalse((Path(temporary.name)/'test.pptx').exists())
 def test_profile_rejects_bad_domain(self):
  result=self.client.put('/api/profile',json={**DEFAULT_PROFILE,'domain':'https://localhost/a'},headers=HEADERS)
  self.assertEqual(result.status_code,422)
 def test_website_pack_has_no_unapproved_claims(self):
  result=self.client.get('/api/export/website-pack.zip')
  with zipfile.ZipFile(io.BytesIO(result.content)) as z:
   text=z.read('company-profile.md').decode()
   self.assertNotIn('旁门医疗',text);self.assertNotIn('广微·益森日纪',text)
   self.assertIn('广州菌和',text)
 def test_export_formula_escape(self):
  self.make('=1+1')
  self.assertIn("'=1+1",self.client.get('/api/export/tasks.csv').text)
 def test_restart_marks_running_as_interrupted(self):
  self.make();tid=records('tasks')[0]['id'];update_task(tid,status='running');init()
  self.assertEqual(records('tasks')[0]['status'],'interrupted')
 def test_screenshot_traversal_rejected(self):
  self.assertEqual(self.client.get('/api/screenshots/.env').status_code,404)
 def test_schedule_validation(self):
  kid=records('keywords')[0]['id']
  for time in ('25:00','9:00','09:61'):
   self.assertEqual(self.post('/api/schedules',{'time':time,'keyword_ids':[kid],'platforms':['kimi']}).status_code,422)

class AsyncTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  init()
  with db() as c:
   for table in ('tasks','batches','schedules'):c.execute('DELETE FROM '+table)
  set_meta('settings',DEFAULT_SETTINGS)
  for pid in PLATFORMS:set_meta('platform:'+pid,default_platform(pid))
 def task(self):
  create_batch(['益生菌食品企业有哪些'],['deepseek'],'visibility',ident());return records('tasks')[0]
 def ready_web(self,runner,pid):
  cfg={**default_platform(pid),'ready':True,'composer':'#input','send_key':'Enter','new_chat_selector':'#new'}
  set_meta('platform:'+pid,cfg);runner.browser.pages[pid]=SimpleNamespace(is_closed=lambda:False)
 async def test_disconnected_jobs_all_move_to_setup_in_one_tick(self):
  create_batch(['测试问题'],list(PLATFORMS),'visibility',ident())
  runner=Runner()
  with patch.object(runner,'execute',new=AsyncMock()) as execute:
   await runner.tick();execute.assert_not_awaited()
  self.assertEqual(len(records('tasks')),len(PLATFORMS))
  self.assertTrue(all(t['status']=='waiting_setup' for t in records('tasks')))
  self.assertEqual(runner.next_dispatch_at,0)
 async def test_setup_is_classified_during_a_real_send_cooldown(self):
  import time
  runner=Runner();runner.next_dispatch_at=time.time()+45
  self.task();await runner.tick()
  self.assertEqual(records('tasks')[0]['status'],'waiting_setup')
  self.assertEqual(runner.snapshot()['queued'],0)
 async def test_unready_job_does_not_delay_a_following_ready_platform(self):
  create_batch(['测试问题'],['deepseek','kimi'],'visibility',ident())
  runner=Runner();self.ready_web(runner,'kimi')
  async def send(pid,cfg,prompt,mode,on_sent,on_attempt=None):
   self.assertEqual(pid,'kimi');on_sent();return {'answer':'本地模拟回答','screenshot':'','note':'fixture'}
  with patch.object(runner.browser,'send',new=AsyncMock(side_effect=send)) as sender:
   await runner.tick();self.assertEqual(sender.await_count,1)
  states={t['platform']:t['status'] for t in records('tasks')}
  self.assertEqual(states,{'deepseek':'waiting_setup','kimi':'needs_review'})
 async def test_setup_failure_adds_no_dispatch_delay(self):
  from browser_bridge import NeedsSetup
  runner=Runner();self.ready_web(runner,'deepseek');self.task()
  with patch.object(runner.browser,'send',new=AsyncMock(side_effect=NeedsSetup('控件未准备好'))):await runner.tick()
  self.assertEqual(records('tasks')[0]['status'],'waiting_setup')
  self.assertEqual(runner.next_dispatch_at,0)
 async def test_successful_attempt_preserves_interval_before_next_ready_job(self):
  import time
  create_batch(['同平台问题一','同平台问题二'],['deepseek'],'visibility',ident())
  runner=Runner();self.ready_web(runner,'deepseek');self.ready_web(runner,'kimi')
  async def send(pid,cfg,prompt,mode,on_sent,on_attempt=None):
   on_sent();return {'answer':'本地模拟回答','screenshot':'','note':'fixture'}
  with patch.object(runner.browser,'send',new=AsyncMock(side_effect=send)) as sender:
   await runner.tick();self.assertGreater(runner.next_dispatch_at,time.time()+40)
   await runner.tick();self.assertEqual(sender.await_count,1)
  self.assertEqual(sum(t['status']=='queued' for t in records('tasks')),1)
 async def test_paused_tick_keeps_unexecuted_jobs_queued(self):
  self.task();set_meta('settings',{**DEFAULT_SETTINGS,'paused':True});runner=Runner()
  with patch.object(runner,'execute',new=AsyncMock()) as execute:
   await runner.tick();execute.assert_not_awaited()
  self.assertEqual(records('tasks')[0]['status'],'queued')
 async def test_missing_browser_is_waiting_not_success(self):
  task=self.task();await Runner().execute(task)
  self.assertEqual(records('tasks')[0]['status'],'waiting_setup')
 async def test_navigation_timeout_keeps_open_window(self):
  from browser_bridge import BrowserBridge
  bridge=BrowserBridge();bridge.playwright=object()
  page=SimpleNamespace(url='about:blank',is_closed=lambda:False,goto=AsyncMock(side_effect=TimeoutError()),bring_to_front=AsyncMock())
  bridge.contexts['deepseek']=SimpleNamespace(pages=[page])
  result=await bridge.connect('deepseek')
  self.assertIs(result,page)
  self.assertTrue(bridge.connection_state('deepseek')['open'])
  self.assertTrue(bridge.connection_state('deepseek')['navigation_error'])
  self.assertFalse(bridge.connection_state('deepseek')['login_verified'])
 async def test_inspection_clears_stale_navigation_error(self):
  from browser_bridge import BrowserBridge
  bridge=BrowserBridge()
  bridge.pages['deepseek']=SimpleNamespace(url=PLATFORMS['deepseek']['url'],is_closed=lambda:False,evaluate=AsyncMock(return_value={'composer_found':True,'composer_editable':True}))
  bridge.navigation_errors['deepseek']='old network timeout'
  result=await bridge.inspect('deepseek',default_platform('deepseek'))
  self.assertTrue(result['composer_found'])
  self.assertEqual(result['navigation_error'],'')
 async def test_inspect_explains_an_unowned_busy_session(self):
  from browser_bridge import BrowserBridge
  bridge=BrowserBridge();bridge.connection_errors['doubao']={'code':'profile_busy','message':'专用资料被另一进程占用'}
  result=await bridge.inspect('doubao',default_platform('doubao'))
  self.assertFalse(result['open'])
  self.assertEqual(result['reason'],'profile_busy')
  self.assertIn('另一进程',result['connection_error'])
 async def test_missing_key_does_not_call_network(self):
  cfg=default_platform('deepseek');cfg['channel']='api';set_meta('platform:deepseek',cfg)
  with patch.dict(os.environ,{'DEEPSEEK_API_KEY':''}):
   await Runner().execute(self.task())
  self.assertEqual(records('tasks')[0]['status'],'waiting_setup')
 async def test_api_adapter_transport_and_api_record(self):
  cfg={**default_platform('deepseek'),'model':'test-model'}
  async def handler(request):
   self.assertEqual(request.url.host,'api.deepseek.com')
   self.assertEqual(json.loads(request.content)['model'],'test-model')
   return httpx.Response(200,json={'choices':[{'message':{'content':'测试回答'}}]})
  with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'local-test-key'}):
   async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    self.assertEqual(await api_send('deepseek',cfg,'test',client),'测试回答')
  set_meta('platform:deepseek',{**cfg,'channel':'api'})
  with patch('engine.api_send',new=AsyncMock(return_value='广州菌和 https://www.junheprobio.com/')):
   await Runner().execute(self.task())
  self.assertEqual(records('tasks')[0]['status'],'completed')
 async def test_timeout_stays_uncertain(self):
  cfg={**default_platform('deepseek'),'channel':'api'};set_meta('platform:deepseek',cfg)
  with patch('engine.api_send',new=AsyncMock(side_effect=httpx.ReadTimeout('test'))):await Runner().execute(self.task())
  self.assertEqual(records('tasks')[0]['status'],'uncertain')
 async def test_daily_schedule_only_once(self):
  kid=records('keywords')[0]['id']
  with db() as c:c.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?)',(ident(),'00:00',json.dumps([kid]),json.dumps(['deepseek']),'visibility',1,'',now()))
  r=Runner();await r.schedule_tick();await r.schedule_tick()
  self.assertEqual(len(records('tasks')),1)

 async def test_configured_saved_profile_recovers_before_new_task_send(self):
  runner=Runner();task=self.task()
  cfg={**default_platform('deepseek'),'ready':True,'send_key':'Enter','new_chat_selector':'#new'};set_meta('platform:deepseek',cfg)
  async def restore(pid,config):
   self.assertEqual(runner.reconnecting,'deepseek')
   self.assertEqual(runner.snapshot()['reconnecting_platform'],'deepseek')
  async def send(pid,config,prompt,mode,on_sent,on_attempt=None):
   on_sent();return {'answer':'mock answer','screenshot':'','note':'fixture'}
  with patch.object(runner.browser,'profile_saved',return_value=True),patch.object(runner.browser,'restore_session',new=AsyncMock(side_effect=restore)) as recover,patch.object(runner.browser,'send',new=AsyncMock(side_effect=send)) as sender:
   await runner.tick();recover.assert_awaited_once();sender.assert_awaited_once()
  self.assertEqual(records('tasks')[0]['status'],'needs_review')
  self.assertIsNone(runner.reconnecting)

 async def test_expired_saved_session_does_not_send_or_claim_success(self):
  from browser_bridge import NeedsSetup
  runner=Runner();self.task();set_meta('platform:deepseek',{**default_platform('deepseek'),'ready':True,'send_key':'Enter','new_chat_selector':'#new'})
  with patch.object(runner.browser,'profile_saved',return_value=True),patch.object(runner.browser,'restore_session',new=AsyncMock(side_effect=NeedsSetup('本人登录已过期，问题未发送'))),patch.object(runner.browser,'send',new=AsyncMock()) as sender:
   await runner.tick();sender.assert_not_awaited()
  task=records('tasks')[0]
  self.assertEqual(task['status'],'waiting_setup');self.assertIsNone(task['sent_at'])
  self.assertIn('登录已过期',task['note']);self.assertEqual(runner.next_dispatch_at,0)

 async def test_old_waiting_tasks_are_not_automatically_requeued(self):
  task=self.task();update_task(task['id'],status='waiting_setup');runner=Runner()
  with patch.object(runner.browser,'profile_saved',return_value=True),patch.object(runner.browser,'restore_session',new=AsyncMock()) as recover,patch.object(runner.browser,'send',new=AsyncMock()) as send:
   await runner.tick();recover.assert_not_awaited();send.assert_not_awaited()
  self.assertEqual(records('tasks')[0]['status'],'waiting_setup')

 async def test_closed_primary_tab_recovers_live_tab_in_owned_context(self):
  from browser_bridge import BrowserBridge
  bridge=BrowserBridge()
  closed=SimpleNamespace(is_closed=lambda:True)
  unrelated=SimpleNamespace(is_closed=lambda:False,url='https://example.com/')
  live=SimpleNamespace(is_closed=lambda:False,url=PLATFORMS['kimi']['url'])
  bridge.pages['kimi']=closed;bridge.contexts['kimi']=SimpleNamespace(pages=[live,unrelated])
  self.assertIs(bridge.current_page('kimi'),live)
  self.assertTrue(bridge.connection_state('kimi')['open'])

 async def test_saved_rules_without_profile_do_not_automatically_launch(self):
  runner=Runner();self.task();set_meta('platform:deepseek',{**default_platform('deepseek'),'ready':True,'send_key':'Enter','new_chat_selector':'#new'})
  with patch.object(runner.browser,'profile_saved',return_value=False),patch.object(runner.browser,'connect',new=AsyncMock()) as connect:
   await runner.tick();connect.assert_not_awaited()
  self.assertEqual(records('tasks')[0]['status'],'waiting_setup')

 async def test_session_restore_checks_controls_without_sending(self):
  from browser_bridge import BrowserBridge
  bridge=BrowserBridge();cfg={**default_platform('kimi'),'ready':True,'send_button':'#send','new_chat_selector':'#new'}
  state={'open':True,'composer_editable':True,'send_found':True,'new_chat_found':True}
  with patch.object(bridge,'profile_saved',return_value=True),patch.object(bridge,'connect',new=AsyncMock()) as connect,patch.object(bridge,'inspect',new=AsyncMock(return_value=state)),patch.object(bridge,'send',new=AsyncMock()) as send:
   self.assertEqual(await bridge.restore_session('kimi',cfg),state);connect.assert_awaited_once_with('kimi');send.assert_not_awaited()

 async def test_restore_rejects_invalid_send_controls_before_any_send(self):
  from browser_bridge import BrowserBridge,NeedsSetup
  bridge=BrowserBridge();cfg={**default_platform('kimi'),'ready':True,'send_button':'#wrong','new_chat_selector':'#new'}
  state={'open':True,'composer_editable':True,'send_found':False,'new_chat_found':True}
  with patch.object(bridge,'profile_saved',return_value=True),patch.object(bridge,'connect',new=AsyncMock()),patch.object(bridge,'inspect',new=AsyncMock(return_value=state)),patch.object(bridge,'send',new=AsyncMock()) as send:
   with self.assertRaises(NeedsSetup):await bridge.restore_session('kimi',cfg)
   send.assert_not_awaited()

 async def test_connection_separates_saved_profile_from_live_window(self):
  from browser_bridge import BrowserBridge
  bridge=BrowserBridge()
  with patch.object(bridge,'profile_saved',return_value=True):state=bridge.connection_state('doubao')
  self.assertTrue(state['profile_saved']);self.assertFalse(state['open']);self.assertFalse(state['login_verified'])

 async def test_different_platforms_start_before_either_finishes(self):
  create_batch(['并行问题'],['deepseek','kimi','doubao'],'visibility',ident());runner=Runner()
  for pid in ['deepseek','kimi','doubao']:self.ready_web(runner,pid)
  gate=asyncio.Event();started=[]
  async def send(pid,cfg,prompt,mode,on_sent,on_attempt=None):
   started.append(pid);on_sent();await gate.wait()
   return {'answer':'fixture','screenshot':'','note':'fixture'}
  with patch.object(runner.browser,'send',new=AsyncMock(side_effect=send)):
   await runner.tick();self.assertCountEqual(started,['deepseek','kimi','doubao'])
   self.assertEqual(runner.snapshot()['active_count'],3)
   gate.set();await asyncio.gather(*list(runner.active_jobs.values()))
  self.assertTrue(all(t['status']=='needs_review' for t in records('tasks')))
 async def test_parallel_limit_and_same_platform_single_flight(self):
  create_batch(['问题一','问题二'],['deepseek','kimi','doubao'],'visibility',ident());runner=Runner()
  for pid in ['deepseek','kimi','doubao']:self.ready_web(runner,pid)
  set_meta('settings',{**DEFAULT_SETTINGS,'parallel_platforms':2});gate=asyncio.Event();started=[]
  async def send(pid,cfg,prompt,mode,on_sent,on_attempt=None):
   started.append(pid);on_sent();await gate.wait();return {'answer':'fixture','screenshot':'','note':'fixture'}
  with patch.object(runner.browser,'send',new=AsyncMock(side_effect=send)):
   await runner.tick();await runner.tick()
   self.assertEqual(len(started),2);self.assertEqual(len(set(started)),2)
   gate.set();await asyncio.gather(*list(runner.active_jobs.values()))
 async def test_long_answer_does_not_add_extra_post_completion_delay(self):
  import time
  self.task();runner=Runner();self.ready_web(runner,'deepseek')
  async def send(pid,cfg,prompt,mode,on_sent,on_attempt=None):
   on_sent()
   # Simulate answer generation taking longer than the same-platform interval.
   clock.return_value+=60
   return {'answer':'fixture','screenshot':'','note':'fixture'}
  stamp=time.time()
  with patch('engine.time.time',return_value=stamp) as clock,patch.object(runner.browser,'send',new=AsyncMock(side_effect=send)):await runner.tick()
  self.assertLess(runner.next_by_platform['deepseek'],stamp+60)
 async def test_complete_bound_answer_is_automatically_recorded(self):
  self.task();runner=Runner();self.ready_web(runner,'deepseek')
  result={'answer':'菌和生物','screenshot':'','note':'fixture','matched':True,'association':'structured','done':True,'busy':False,'stable':True,'later_turns':False}
  with patch.object(runner.browser,'send',new=AsyncMock(return_value=result)):await runner.tick()
  task=records('tasks')[0]
  self.assertEqual(task['status'],'completed');self.assertTrue(task['reviewed'])
  self.assertEqual(json.loads(task['metrics'])['verification_method'],'automatic_dom')
 async def test_unfinished_answer_cannot_pass_automatic_verification(self):
  self.task();runner=Runner();self.ready_web(runner,'deepseek')
  result={'answer':'partial','screenshot':'','note':'fixture','matched':True,'association':'structured','done':True,'busy':True,'stable':True}
  with patch.object(runner.browser,'send',new=AsyncMock(return_value=result)):await runner.tick()
  self.assertEqual(records('tasks')[0]['status'],'needs_review');self.assertFalse(records('tasks')[0]['reviewed'])
 async def test_continuation_is_excluded_from_independent_metrics(self):
  from insights import eligibility
  create_batch(['行业问题'],['deepseek'],'visibility',ident(),'continue')
  task=records('tasks')[0];task.update(status='completed',reviewed=1,answer='fixture')
  self.assertEqual(eligibility(task,DEFAULT_PROFILE),'continuation')
 async def test_api_continuation_passes_prior_messages(self):
  first=self.task();update_task(first['id'],status='completed',answer='上一轮回答',reviewed=1)
  with db() as c:c.execute("UPDATE tasks SET channel='api' WHERE id=?",(first['id'],))
  cfg={**default_platform('deepseek'),'channel':'api'};set_meta('platform:deepseek',cfg)
  with db() as c:c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',(ident(),'fixture material','fixture public text','fixture',1,now()))
  create_batch(['继续分析'],['deepseek'],'materials',ident(),'continue')
  with db() as c:task=dict(c.execute("SELECT * FROM tasks WHERE keyword='继续分析'").fetchone())
  with patch('engine.api_send',new=AsyncMock(return_value='new answer')) as sender:
   await Runner().execute(task)
   messages=sender.call_args.kwargs['messages']
   self.assertEqual(messages[0]['role'],'user');self.assertEqual(messages[1]['content'],'上一轮回答')
 async def test_cancelling_parallel_runner_marks_active_tasks_interrupted(self):
  self.task();runner=Runner();self.ready_web(runner,'deepseek');gate=asyncio.Event()
  async def send(*args):
   args[5]();await gate.wait()
  with patch.object(runner.browser,'send',new=AsyncMock(side_effect=send)):
   await runner.tick();await runner.stop()
  self.assertEqual(records('tasks')[0]['status'],'interrupted')

if __name__=='__main__':unittest.main()
