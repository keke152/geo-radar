import json
from datetime import datetime
import unittest
from unittest.mock import AsyncMock,patch
import test_workspace
from fastapi.testclient import TestClient
import app,keyword_planner
from domain import analyze
from config import DEFAULT_PROFILE,DEFAULT_SETTINGS
from storage import db,init,set_meta,get_meta,records,ident,now
from insights import build_insights,measurement

HEADERS={'X-Workspace-Request':'junhe-local'}

class MeasurementPlannerTests(unittest.TestCase):
 def setUp(self):
  self.context=TestClient(app.app,base_url='http://127.0.0.1:8020');self.client=self.context.__enter__();self.addCleanup(lambda:self.context.__exit__(None,None,None))
  with db() as c:
   for table in ('tasks','batches','schedules','documents','keywords','meta','keyword_candidates','keyword_generation_runs'):c.execute('DELETE FROM '+table)
  init()
 def task(self,**changes):
  row={'id':ident(),'batch_id':'fixture','platform':'kimi','channel':'web','mode':'visibility','keyword':DEFAULT_PROFILE['company_name'],
       'prompt':'fixture','answer':DEFAULT_PROFILE['company_name']+'主营益生菌食品。','status':'completed','reviewed':1,'metrics':'{}','created_at':now(),'updated_at':now(),'sent_at':now()}
  row.update(changes)
  with db() as c:c.execute('INSERT INTO tasks('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
  return row
 def test_company_query_is_visible_in_all_scope_but_not_natural(self):
  self.task()
  natural=self.client.get('/api/insights?scope=natural').json();all_answers=self.client.get('/api/insights?scope=all').json()
  self.assertEqual(natural['totals']['samples'],0);self.assertEqual(all_answers['totals']['company_mentions'],1)
  self.assertEqual(all_answers['totals']['brand_mentions'],0)
  self.assertEqual(natural['platforms'][2]['recorded_answers'],1)
  self.assertEqual(natural['comparison'][0]['platforms']['kimi']['reason'],'branded')
 def test_company_does_not_inflate_brand_metric(self):
  result=analyze('广州**菌和生物科技**有限公司',DEFAULT_PROFILE)
  self.assertTrue(result['company_mentioned']);self.assertFalse(result['brand_mentioned'])
  self.assertIn(DEFAULT_PROFILE['company_name'],result['company_matches'])
 def test_source_audit_is_separate_from_natural_discovery(self):
  self.task(keyword='合作材料是否有原文依据',metrics=json.dumps({'goal':'source_audit','source_directed':True}))
  natural=self.client.get('/api/insights?scope=natural');self.assertEqual(natural.status_code,200)
  self.assertEqual(natural.json()['totals']['samples'],0)
  self.assertEqual(natural.json()['excluded']['source_directed'],1)
  self.assertEqual(self.client.get('/api/insights?scope=all').json()['totals']['samples'],1)
 def test_brand_check_without_name_still_is_not_natural(self):
  self.task(keyword='运营主体是什么',metrics=json.dumps({'goal':'brand_check'}))
  report=self.client.get('/api/insights?scope=natural').json()
  self.assertEqual(report['totals']['samples'],0);self.assertEqual(report['excluded']['branded'],1)
 def test_brand_and_company_have_separate_match_evidence(self):
  result=analyze('广微·益森日纪，由菌和生物运营。',DEFAULT_PROFILE)
  self.assertTrue(result['brand_mentioned']);self.assertTrue(result['company_mentioned'])
  self.assertIn('益森日纪',result['brand_matches']);self.assertIn('菌和生物',result['company_matches'])
 def test_question_alone_does_not_count_as_answer_mention(self):
  self.task(answer='没有找到对应信息')
  report=self.client.get('/api/insights?scope=all').json()
  self.assertEqual(report['totals']['company_mentions'],0)
 def test_all_scope_still_excludes_unverified_or_empty(self):
  self.task(status='needs_review',reviewed=0);self.task(answer='')
  report=self.client.get('/api/insights?scope=all').json()
  self.assertEqual(report['totals']['samples'],0)
  self.assertEqual(report['excluded']['unreviewed'],1);self.assertEqual(report['excluded']['empty_answer'],1)
 def test_comparison_shows_latest_unreviewed_progress_without_losing_verified_sample(self):
  first=self.task(keyword='行业问题',sent_at='2026-11-04T01:00:00+00:00')
  latest=self.task(keyword='行业问题',status='needs_review',reviewed=0,sent_at='2026-11-04T02:00:00+00:00')
  report=self.client.get('/api/insights?scope=all').json()
  self.assertEqual(report['questions'][0]['platforms']['kimi']['id'],first['id'])
  self.assertEqual(report['comparison'][0]['platforms']['kimi']['id'],latest['id'])
  self.assertEqual(report['comparison'][0]['platforms']['kimi']['status'],'needs_review')
 def test_scope_validation_export_and_detail_agree(self):
  row=self.task()
  self.assertEqual(self.client.get('/api/insights?scope=bogus').status_code,422)
  self.assertIn('全部已核对回答',self.client.get('/api/export/visibility.md?scope=all').text)
  detail=self.client.get('/api/tasks/'+row['id']).json()
  self.assertEqual(detail['measurement']['reason'],'branded');self.assertTrue(detail['measurement']['analysis']['company_mentioned'])
 def test_daily_candidates_are_grounded_balanced_and_local_only(self):
  before=records('tasks')
  result=keyword_planner.generate('2026-11-04');items=keyword_planner.candidates()['items']
  self.assertEqual(result['created'],10);self.assertEqual(len(items),10)
  self.assertEqual({item['kind'] for item in items},{'行业词','招商词','场景词'})
  self.assertTrue(all(DEFAULT_PROFILE['business'] in item['text'] for item in items))
  self.assertTrue(all('热搜' not in item['source'] for item in items));self.assertEqual(records('tasks'),before)
 def test_generation_is_idempotent_per_china_day_and_no_duplicate_tomorrow(self):
  keyword_planner.generate('2026-11-04');first={x['text'] for x in keyword_planner.candidates()['items']}
  self.assertEqual(keyword_planner.generate('2026-11-04')['created'],0)
  keyword_planner.generate('2026-11-05');new={x['text'] for x in keyword_planner.candidates()['items']}
  self.assertEqual(len(new-first),10)
 def test_existing_keywords_are_not_generated_and_candidate_acceptance_does_not_send(self):
  target=keyword_planner.pool(DEFAULT_PROFILE)[0]
  with db() as c:c.execute('INSERT INTO keywords VALUES(?,?,?,?)',(ident(),target['text'],target['kind'],now()))
  keyword_planner.generate('2026-11-04');items=keyword_planner.candidates()['items']
  self.assertNotIn(target['text'],[x['text'] for x in items])
  keyword_planner.accept(items[0]['id']);self.assertIn(items[0]['text'],[x['text'] for x in records('keywords')])
  self.assertEqual(len(records('tasks')),0)
  with self.assertRaises(ValueError):keyword_planner.accept(items[0]['id'])
 def test_disabled_plan_and_before_time_do_not_generate(self):
  self.assertIsNone(keyword_planner.daily_tick())
  set_meta('keyword_plan',{'enabled':True,'time':'09:00','count':5})
  self.assertIsNone(keyword_planner.daily_tick(datetime(2026,11,4,8,59,tzinfo=keyword_planner.CST)))
  self.assertEqual(keyword_planner.daily_tick(datetime(2026,11,4,9,0,tzinfo=keyword_planner.CST))['created'],5)
 def test_exhausted_candidate_pool_does_not_fabricate_more(self):
  set_meta('keyword_plan',{'enabled':True,'time':'09:00','count':30})
  for day in range(1,5):keyword_planner.generate(f'2026-11-{day:02}')
  self.assertEqual(keyword_planner.generate('2026-11-05')['created'],0)
 def test_keyword_plan_validation_and_mutation_header(self):
  self.assertEqual(self.client.put('/api/keyword-plan',json={'enabled':True}).status_code,403)
  for bad in ({'time':'25:00'},{'count':31},{'count':0}):self.assertEqual(self.client.put('/api/keyword-plan',headers=HEADERS,json=bad).status_code,422)
 def test_daily_limit_accepts_300_and_1000_but_not_1001(self):
  for limit in (300,1000):self.assertEqual(self.client.put('/api/settings',headers=HEADERS,json={**DEFAULT_SETTINGS,'daily_limit':limit}).status_code,200)
  self.assertEqual(self.client.put('/api/settings',headers=HEADERS,json={**DEFAULT_SETTINGS,'daily_limit':1001}).status_code,422)
 def test_diagnostic_reads_existing_chat_without_sending(self):
  row=self.task()
  with patch.object(app.runner.browser,'open_conversation',new=AsyncMock()),patch.object(app.runner.browser,'response_snapshot',new=AsyncMock(return_value={'prompt_matched':True})),patch.object(app.runner.browser,'send',new=AsyncMock()) as send:
   response=self.client.post('/api/tasks/'+row['id']+'/capture-diagnostics',headers=HEADERS)
  self.assertEqual(response.status_code,200);send.assert_not_called()

if __name__=='__main__':unittest.main()
