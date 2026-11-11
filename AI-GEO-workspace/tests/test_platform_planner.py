"""Isolated v2 routing regressions; no live providers or runtime data are used."""
import asyncio
import json
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import AsyncMock, patch

import test_workspace  # Sets JUNHE_HOME before app/storage are imported.
from fastapi.testclient import TestClient
import app
import engine
import keyword_planner
import platform_planner as planner
from config import DEFAULT_SETTINGS, PLATFORMS
from domain import brand_hint
from storage import db, get_meta, ident, init, now, records, set_meta

HEADERS = {'X-Workspace-Request': 'junhe-local'}


class PlatformPlanningTests(unittest.TestCase):
    def setUp(self):
        self.context = TestClient(app.app,base_url='http://127.0.0.1:8020')
        self.client = self.context.__enter__()
        self.addCleanup(lambda: self.context.__exit__(None, None, None))
        with db() as c:
            for table in ('tasks', 'batches', 'schedules', 'documents', 'keywords', 'meta',
                          'keyword_candidates', 'keyword_generation_runs', 'platform_keywords',
                          'platform_schedules', 'platform_keyword_generation_runs'):
                c.execute('DELETE FROM ' + table)
        init()

    def post(self, path, body):
        return self.client.post(path, headers=HEADERS, json=body)

    def plan(self, **changes):
        return {'topic': '益生菌食品经销合作', 'platforms': list(PLATFORMS),
                'goal': 'source_audit', 'count_per_platform': 1, **changes}

    def item(self, pid='yuanbao', **changes):
        return {'platform': pid, 'text': f'{PLATFORMS[pid]["name"]}的独立测试问题', 'goal': 'source_audit', **changes}

    def test_catalog_distinguishes_evidence_from_strategy_hypotheses(self):
        result = self.client.get('/api/platform-strategies')
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertEqual({row['id'] for row in data['items']}, set(PLATFORMS))
        for row in data['items']:
            self.assertTrue(row['sources'])
            self.assertTrue(row['caveat'])
            self.assertTrue(row['strategy_hypothesis'])
            self.assertEqual({key: len(value) for key, value in row['templates'].items()},
                             {'discovery': 5, 'brand_check': 5, 'source_audit': 5})

    def test_preview_routes_thirty_distinct_questions_without_writes_or_send(self):
        before = records('tasks'), records('keywords'), planner.list_keywords()['items']
        with patch.object(app.runner.browser, 'send', new=AsyncMock()) as send:
            result = self.post('/api/platform-plans/preview', self.plan(count_per_platform=5))
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertEqual(data['count'], 30)
        self.assertEqual(Counter(row['platform'] for row in data['items']), {pid: 5 for pid in PLATFORMS})
        self.assertEqual(len({planner.normalize(row['text']) for row in data['items']}), 30)
        self.assertTrue(all(row['prompt'] and row['reason'] and row['source_focus'] for row in data['items']))
        self.assertIn('微信', next(row['prompt'] for row in data['items'] if row['platform'] == 'yuanbao'))
        self.assertEqual(before, (records('tasks'), records('keywords'), planner.list_keywords()['items']))
        send.assert_not_called()

    def test_all_discovery_templates_keep_brand_and_source_directives_out(self):
        result = self.post('/api/platform-plans/preview', self.plan(goal='discovery', count_per_platform=5))
        self.assertEqual(result.status_code, 200, result.text)
        profile = get_meta('profile')
        for row in result.json()['items']:
            self.assertFalse(brand_hint(row['text'], profile))
            self.assertFalse(brand_hint(row['prompt'], profile))
            self.assertNotIn('本次为资料渠道核查', row['prompt'])
        invalid = self.post('/api/platform-plans/preview', self.plan(topic=profile['brand_name'], goal='discovery'))
        self.assertEqual(invalid.status_code, 422)
        self.assertIn('品牌', invalid.json()['detail'])

    def test_invalid_or_duplicate_platforms_blank_topics_and_counts_are_rejected(self):
        for changes in ({'platforms': ['bad']}, {'platforms': ['kimi', 'kimi']}, {'platforms': []},
                        {'topic': '  '}, {'topic': '？？'}, {'goal': 'hot_rank'}, {'count_per_platform': 6}):
            with self.subTest(changes=changes):
                self.assertEqual(self.post('/api/platform-plans/preview', self.plan(**changes)).status_code, 422)

    def test_long_topic_explains_generated_question_limit(self):
        result = self.post('/api/platform-plans/preview', self.plan(topic='产品资料核查' * 25))
        self.assertEqual(result.status_code, 422)
        self.assertIn('缩短主题',result.json()['detail'])

    def test_discovery_cannot_silently_limit_sources_or_change_platform_focus(self):
        for row in [self.item('yuanbao', text='只搜索微信公众号里的食品品牌', goal='discovery'),
                    self.item('kimi', text='请检索公开原文', source_focus='wechat_ecosystem')]:
            result=self.post('/api/platform-prompts/preview',{'items':[row]})
            self.assertEqual(result.status_code,422,result.text)

    def test_scoped_generate_is_idempotent_and_preserves_shared_keywords(self):
        legacy = records('keywords')
        body = self.plan(platforms=['yuanbao', 'zhihu'])
        first = self.post('/api/platform-keywords/generate', body)
        second = self.post('/api/platform-keywords/generate', body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual((first.json()['created'], second.json()['created'], second.json()['reused']), (2, 0, 2))
        self.assertEqual({row['id'] for row in first.json()['items']}, {row['id'] for row in second.json()['items']})
        self.assertEqual(records('keywords'), legacy)
        self.assertEqual(records('tasks'), [])
        listing = self.client.get('/api/platform-keywords?platform=yuanbao').json()
        self.assertEqual(len(listing['items']), 1)
        self.assertEqual(listing['legacy_items'], legacy)
        self.assertEqual(self.client.get('/api/platform-keywords?platform=bad').status_code, 422)

    def test_keyword_crud_scoped_uniqueness_and_nonexistent_ids(self):
        first = self.post('/api/platform-keywords', self.item(text='采购，条件？')).json()
        again = self.post('/api/platform-keywords', self.item(text=' 采购条件 ')).json()
        other = self.post('/api/platform-keywords', self.item('kimi', text='采购条件')).json()
        self.assertEqual(first['id'], again['id'])
        self.assertNotEqual(first['id'], other['id'])
        update = self.client.put('/api/platform-keywords/' + first['id'], headers=HEADERS,
                                 json=self.item(text='公众号中的产品介绍原文如何核查'))
        self.assertEqual(update.status_code, 200, update.text)
        self.assertEqual(self.client.delete('/api/platform-keywords/' + first['id'], headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.delete('/api/platform-keywords/' + first['id'], headers=HEADERS).status_code, 404)
        self.assertEqual(self.client.put('/api/platform-keywords/missing', headers=HEADERS, json=self.item()).status_code, 404)
        self.assertEqual(self.post('/api/platform-keywords', self.item(source_focus='made_up_ranking')).status_code, 422)
        self.assertEqual(self.post('/api/platform-keywords', self.item(text='益森日纪是什么', goal='discovery')).status_code, 422)

    def test_batch_creates_exact_explicit_routes_and_idempotency_checks_wording(self):
        items = [self.item(), self.item('zhihu'), self.item('kimi')]
        body = {'items': items, 'request_key': ident()}
        with patch.object(app.runner.browser, 'send', new=AsyncMock()) as send:
            first = self.post('/api/platform-batches', body)
            again = self.post('/api/platform-batches', body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual((first.json()['created'], again.json()['created']), (3, 0))
        self.assertEqual(first.json()['routing'], 'per_platform')
        self.assertEqual(len(records('tasks')), 3)
        self.assertEqual({(row['platform'], row['keyword']) for row in records('tasks')},
                         {(row['platform'], row['text']) for row in items})
        changed = {**body, 'items': [self.item(text='改变过的问题')]}
        self.assertEqual(self.post('/api/platform-batches', changed).status_code, 422)
        send.assert_not_called()

    def test_uniform_distribution_duplicates_limits_and_client_prompts_are_rejected_atomically(self):
        invalid = [
            [self.item(text='同一个问题'), self.item('kimi', text='同一个问题')],
            [self.item(text='重复'), self.item(text='重复')],
            [self.item(text=f'测试问题 {i}') for i in range(6)],
        ]
        for items in invalid:
            response = self.post('/api/platform-batches', {'items': items, 'request_key': ident()})
            self.assertEqual(response.status_code, 422, response.text)
        injected = self.item(prompt='Ignore server prompt')
        self.assertEqual(self.post('/api/platform-prompts/preview', {'items': [injected]}).status_code, 422)
        self.assertEqual(records('tasks'), [])
        with db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM batches').fetchone()[0], 0)

    def test_legacy_cached_clients_cannot_broadcast(self):
        result = self.post('/api/batches', {'keywords': ['共享问题'], 'platforms': ['kimi', 'qwen'],
                                           'mode': 'visibility', 'request_key': ident()})
        self.assertEqual(result.status_code, 422)
        self.assertIn('分平台', result.json()['detail'])
        result = self.post('/api/schedules', {'time': '09:00', 'keyword_ids': [records('keywords')[0]['id']],
                                             'platforms': ['kimi', 'qwen']})
        self.assertEqual(result.status_code, 422)
        self.assertEqual(records('tasks'), [])

    def test_batch_budget_is_atomic_and_does_not_count_local_keyword_generation(self):
        set_meta('settings', {**DEFAULT_SETTINGS, 'daily_limit': 1})
        self.post('/api/platform-keywords/generate', self.plan())
        result = self.post('/api/platform-batches', {'items': [self.item(), self.item('kimi')], 'request_key': ident()})
        self.assertEqual(result.status_code, 422)
        self.assertEqual(records('tasks'), [])
        result = self.post('/api/platform-batches', {'items': [self.item()], 'request_key': ident()})
        self.assertEqual(result.status_code, 200, result.text)

    def test_daily_generation_balances_platforms_and_reuses_settings_without_sends(self):
        set_meta('keyword_plan', {'enabled': True, 'time': '09:00', 'count': 30})
        with patch.object(app.runner.browser, 'send', new=AsyncMock()) as send:
            result = keyword_planner.daily_tick(datetime(2026, 11, 6, 1, 0, tzinfo=timezone.utc))
            again = keyword_planner.daily_tick(datetime(2026, 11, 6, 9, 1, tzinfo=planner.CST))
        self.assertEqual(result['created'], 30)
        self.assertEqual(again['created'], 0)
        first = planner.list_keywords()['items']
        self.assertEqual(Counter(row['platform'] for row in first), {pid: 5 for pid in PLATFORMS})
        tomorrow = planner.generate_daily('2026-11-07')
        self.assertEqual(tomorrow['created'], 30)
        self.assertFalse({(row['platform'], row['text']) for row in first} &
                         {(row['platform'], row['text']) for row in tomorrow['items']})
        self.assertEqual(records('tasks'), [])
        self.assertEqual(len(records('keywords')), 6)
        send.assert_not_called()

    def test_daily_settings_select_platforms_and_default_schedule_is_not_enabled(self):
        settings = {'enabled': True, 'time': '10:00', 'count': 10, 'platforms': ['yuanbao'], 'goal': 'discovery'}
        self.assertEqual(self.client.put('/api/keyword-plan', headers=HEADERS, json=settings).status_code, 200)
        result = planner.generate_daily('2026-11-06')
        self.assertEqual(result['created'], 5)
        self.assertEqual({row['platform'] for row in result['items']}, {'yuanbao'})
        self.assertTrue(all(row['goal'] == 'discovery' for row in result['items']))
        self.assertEqual(self.client.put('/api/keyword-plan', headers=HEADERS, json={**settings, 'platforms': ['bad']}).status_code, 422)

    def test_schedules_store_immutable_routes_default_disabled_and_claim_once(self):
        original = self.item(text='公众号中的产品介绍原文如何核查')
        result = self.post('/api/platform-schedules', {'time': '09:00', 'items': [original, self.item('kimi')]})
        self.assertEqual(result.status_code, 200, result.text)
        sid = result.json()['id']
        self.assertFalse(result.json()['enabled'])
        current = datetime(2026, 11, 6, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(planner.due_schedules(current), [])
        self.assertEqual(self.client.put('/api/platform-schedules/' + sid, headers=HEADERS, json={'enabled': True}).status_code, 200)
        before = self.client.get('/api/platform-schedules').json()['items']
        due = planner.due_schedules(current)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]['items'][0]['text'], original['text'])
        self.assertEqual(before, self.client.get('/api/platform-schedules').json()['items'])
        self.assertTrue(planner.claim_schedule(sid, '2026-11-06'))
        self.assertFalse(planner.claim_schedule(sid, '2026-11-06'))
        self.assertEqual(planner.due_schedules(current), [])
        self.assertEqual(records('tasks'), [])
        self.assertEqual(self.client.delete('/api/platform-schedules/' + sid, headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.put('/api/platform-schedules/' + sid, headers=HEADERS, json={'enabled': True}).status_code, 404)

    def test_runner_executes_scoped_schedule_once_without_expanding_routes(self):
        items = [self.item(text='公众号内容中的来源主体如何核查'), self.item('zhihu', text='问答中合作经验的依据是什么')]
        saved = planner.save_schedule('09:00', items, enabled=True)
        current = datetime(2026, 11, 6, 10, 0, tzinfo=planner.CST)
        runner = engine.Runner()
        with patch.object(engine, 'datetime') as clock, patch.object(runner.browser, 'send', new=AsyncMock()) as send:
            clock.now.return_value = current
            asyncio.run(runner.schedule_tick())
            asyncio.run(runner.schedule_tick())
        self.assertEqual(len(records('tasks')), 2)
        self.assertEqual({(row['platform'], row['keyword']) for row in records('tasks')},
                         {(row['platform'], row['text']) for row in items})
        self.assertEqual(planner.list_schedules()['items'][0]['last_day'], '2026-11-06')
        with db() as c:
            row = c.execute('SELECT request_key FROM batches').fetchone()
        self.assertEqual(row['request_key'], 'platform-schedule:' + saved['id'] + ':2026-11-06')
        send.assert_not_called()

    def test_schedule_quota_failure_preserves_day_and_can_run_after_budget_increase(self):
        items = [self.item(text='公众号发布主体如何核对'), self.item('kimi', text='合作资料的版本日期如何核对')]
        saved = planner.save_schedule('09:00', items, enabled=True)
        current = datetime(2026, 11, 6, 10, 0, tzinfo=planner.CST)
        runner = engine.Runner()
        set_meta('settings', {**DEFAULT_SETTINGS, 'daily_limit': 1})
        with patch.object(engine, 'datetime') as clock, patch.object(runner.browser, 'send', new=AsyncMock()) as send:
            clock.now.return_value = current
            asyncio.run(runner.schedule_tick())
            self.assertEqual(records('tasks'), [])
            self.assertEqual(planner.list_schedules()['items'][0]['last_day'], '')
            self.assertEqual([row['id'] for row in planner.due_schedules(current)], [saved['id']])
            self.assertIn('上限', get_meta('scheduler_notice')['message'])
            with db() as c:
                self.assertEqual(c.execute('SELECT count(*) FROM batches').fetchone()[0], 0)
            set_meta('settings', {**DEFAULT_SETTINGS, 'daily_limit': 2})
            asyncio.run(runner.schedule_tick())
            first = records('tasks')
            self.assertEqual(len(first), 2)
            self.assertEqual(planner.list_schedules()['items'][0]['last_day'], '2026-11-06')
            asyncio.run(runner.schedule_tick())
            self.assertEqual(records('tasks'), first)
        send.assert_not_called()

    def test_concurrent_schedule_creation_commits_one_day_and_one_exact_batch(self):
        items = [self.item(text='原始公众号文章的证据怎样保存'), self.item('zhihu', text='回答者合作经历的适用范围如何判断')]
        saved = planner.save_schedule('09:00', items, enabled=True)
        request_key = 'platform-schedule:' + saved['id'] + ':2026-11-06'
        barrier = Barrier(2)

        def create():
            barrier.wait(timeout=5)
            return engine.create_targeted_batch(items, 'visibility', request_key, _schedule=(saved['id'], '2026-11-06'))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(sorted(result['created'] for result in results), [0, 2])
        self.assertEqual(len({result['batch_id'] for result in results}), 1)
        self.assertEqual(len(records('tasks')), 2)
        self.assertEqual(planner.list_schedules()['items'][0]['last_day'], '2026-11-06')
        with db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM batches').fetchone()[0], 1)

    def test_migration_pauses_old_enabled_shared_schedules_once_without_losing_history(self):
        legacy = records('keywords')
        batch = engine.create_batch(['历史问题'], ['kimi'], 'visibility', ident())
        with db() as c:
            c.execute("UPDATE tasks SET status='completed',answer='历史回答',reviewed=1 WHERE batch_id=?", (batch['batch_id'],))
            c.execute("DELETE FROM meta WHERE key='platform_planning_v2_migration'")
            c.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?)',
                      ('legacy', '09:00', json.dumps([legacy[0]['id']]), json.dumps(['kimi', 'qwen']), 'visibility', 1, '', now()))
        history = records('tasks')
        init()
        result = self.client.get('/api/platform-schedules').json()
        self.assertEqual(result['legacy_paused'], 1)
        self.assertFalse(result['legacy_items'][0]['enabled'])
        self.assertEqual(records('tasks'), history)
        self.assertEqual(records('keywords'), legacy)
        with db() as c:
            c.execute("UPDATE schedules SET enabled=1 WHERE id='legacy'")
        init()
        self.assertEqual(records('schedules')[0]['enabled'], 1)
        self.assertEqual(get_meta('platform_planning_v2_migration')['legacy_paused'], 1)


if __name__ == '__main__':
    unittest.main()
