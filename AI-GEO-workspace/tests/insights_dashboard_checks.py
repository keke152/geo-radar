"""Offline browser acceptance for the read-only insights dashboard.

Run: .venv/Scripts/python tests/insights_dashboard_checks.py
Optional: append --screenshot docs/images/showcase/insights-dashboard.png

The real HTML/CSS/JavaScript is loaded with every HTTP request intercepted.
Only synthetic aggregate fixtures are returned: this script does not import
the application, read runtime/.env, open an account, or create/send tasks.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import mimetypes
from pathlib import Path
import re
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'http://127.0.0.1:8020'
TODAY = date(2026, 11, 19)
NAMES = {'doubao': '豆包', 'deepseek': 'DeepSeek', 'kimi': 'Kimi',
         'qwen': '千问', 'yuanbao': '腾讯元宝', 'zhihu': '知乎直答'}
METRICS = ('brand_mentions', 'company_mentions', 'official_links', 'samples')
SCREENSHOT_PATH = None
PROFILE = {'company_name': '看板验收演示企业', 'domain': 'example.invalid',
           'aliases': ['演示企业'], 'business': '离线看板验收', 'audience': '',
           'audience_confirmed': False, 'public_intro': '合成验收数据，非平台回答。',
           'brand_name': '演示品牌', 'brand_aliases': [], 'brand_relation': '离线夹具'}
REASONS = {'materials': '资料研读', 'branded': '指名问题', 'unreviewed': '未完成或未核对',
           'empty_answer': '空回答', 'continuation': '连续会话', 'source_directed': '来源核验'}


def fixture_rows():
    rows = []

    def add(platform, brand=0, company=0, link=0, *, offset=0, channel='web', reason='eligible'):
        rows.append({'platform': platform, 'brand_mentions': brand, 'company_mentions': company,
                     'official_links': link, 'date': (TODAY - timedelta(days=offset)).isoformat(),
                     'channel': channel, 'reason': reason})

    # Seven recent natural samples: deliberately different platform denominators.
    add('doubao', 1, 1, offset=3)
    add('doubao', company=1, offset=2)
    add('doubao', offset=1)
    add('doubao')
    add('deepseek', 1, 1, 1, offset=1)
    add('deepseek', company=1)
    add('kimi')  # A real sample with zero hits must differ from no samples.
    add('doubao', 1, link=1, reason='source_directed')
    add('deepseek', 1, reason='branded')
    add('kimi', company=1, reason='materials')
    add('doubao', 1, 1, reason='continuation')
    add('qwen', reason='unreviewed')
    add('qwen', reason='unreviewed')
    add('yuanbao', reason='empty_answer')
    add('doubao', 1, 1, 1, offset=15)  # Only visible in 30/90-day reports.
    add('qwen', 1, 1, 1, channel='api')
    add('qwen', channel='api')
    add('deepseek', channel='api')
    add('doubao', channel='api', reason='unreviewed')
    return rows


ROWS = fixture_rows()


def report_fixture(params):
    days = int(params.get('days', '30'))
    channel = params.get('channel', 'web')
    platform = params.get('platform', 'all')
    scope = params.get('scope', 'all')
    start = TODAY - timedelta(days=days - 1)
    selected = [row for row in ROWS if row['channel'] == channel and
                (platform == 'all' or row['platform'] == platform) and
                start.isoformat() <= row['date'] <= TODAY.isoformat()]
    platforms = [{'id': pid, 'name': name, 'samples': 0, 'brand_mentions': 0,
                  'company_mentions': 0, 'official_links': 0, 'total_tasks': 0,
                  'recorded_answers': 0, 'last_sample_at': None, 'exclusions': {}}
                 for pid, name in NAMES.items() if platform == 'all' or pid == platform]
    by_platform = {row['id']: row for row in platforms}
    trend = [{'date': (start + timedelta(days=index)).isoformat(), 'samples': 0,
              'brand_mentions': 0, 'company_mentions': 0, 'official_links': 0}
             for index in range(days)]
    by_day = {row['date']: row for row in trend}
    excluded = dict.fromkeys(REASONS, 0)
    included = []
    for row in selected:
        counter = by_platform[row['platform']]
        counter['total_tasks'] += 1
        reason = row['reason']
        if reason not in ('unreviewed', 'empty_answer'):
            counter['recorded_answers'] += 1
            if scope == 'all':
                reason = 'eligible'
        if reason != 'eligible':
            excluded[reason] += 1
            counter['exclusions'][reason] = counter['exclusions'].get(reason, 0) + 1
            continue
        included.append(row)
        for target in (counter, by_day[row['date']]):
            target['samples'] += 1
            for metric in METRICS[:-1]:
                target[metric] += row[metric]
        counter['last_sample_at'] = row['date'] + 'T10:00:00+08:00'
    totals = {metric: len(included) if metric == 'samples' else sum(row[metric] for row in included)
              for metric in METRICS}
    totals['questions'] = len(included)
    totals['brand_rate'] = round(totals['brand_mentions'] * 100 / totals['samples'], 1) if included else None
    return {'filters': {'start_date': start.isoformat(), 'end_date': TODAY.isoformat(),
                        'channel': channel, 'platform': platform, 'scope': scope},
            'generated_at': '2026-11-19T10:00:00+08:00', 'brand_name': PROFILE['brand_name'],
            'company_name': PROFILE['company_name'], 'totals': totals, 'platforms': platforms,
            'trend': trend, 'task_count': len(selected), 'excluded': excluded,
            'statuses': {'completed': len(included)}, 'actions': [], 'questions': [],
            'comparison': [], 'evidence': [],
            'matching_rules': {'company_names': [PROFILE['company_name']],
                               'brand_names': [PROFILE['brand_name']]},
            'measurement_note': '离线合成验收夹具；不代表任何平台实际回答或表现。'}


def bootstrap_fixture():
    return {'version': '2.0.0', 'profile': PROFILE,
            'settings': {'paused': True, 'interval_seconds': 45, 'daily_limit': 300,
                         'parallel_platforms': 6, 'auto_verify': True},
            'platforms': [{'id': pid, 'name': name, 'channel': 'web', 'model': '', 'env': None,
                           'api': None, 'docs': 'https://example.invalid/', 'key_configured': False,
                           'browser_open': False, 'ready': False, 'connection': {}, 'composer': '',
                           'send_button': '', 'send_key': '', 'reply_selector': '',
                           'new_chat_selector': '', 'search_enabled': False}
                          for pid, name in NAMES.items()],
            'queue': {'state': 'paused', 'error': '', 'worker_alive': True, 'scheduler_alive': True,
                      'active_count': 0, 'queued': 0, 'waiting_setup': 0, 'positions': {}},
            'client_counts': {'all': 0, 'running': 0, 'attention': 0, 'completed': 0},
            'metrics': {channel: {'samples': 0, 'brand_mentions': 0, 'official_links': 0}
                        for channel in ('web', 'api')},
            'daily_budget': {'used': 0, 'remaining': 300, 'limit': 300}, 'current_task': None,
            'tasks': [], 'documents': [], 'keywords': [], 'schedules': [], 'desktop': {},
            'platform_keywords': [], 'platform_schedules': [], 'scheduler_notice': None}


class InsightsDashboardChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel='msedge', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.external_requests = []
        self.writes = []
        self.page_errors = []
        self.insight_requests = []
        self.hold_next_insights = False
        self.pending_response = None
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1100},
                                                locale='zh-CN', timezone_id='Asia/Shanghai',
                                                reduced_motion='reduce')
        self.addCleanup(self.context.close)
        self.context.route('**/*', self.route)
        self.page = self.context.new_page()
        self.page.set_default_timeout(8000)
        self.page.on('pageerror', lambda error: self.page_errors.append(str(error)))
        self.page.goto(ORIGIN + '/#insights')
        self.page.wait_for_selector('#insights-dashboard')
        self.wait_ready()
        self.set_filter('days', '7')
        self.set_filter('scope', 'natural')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.external_requests, [], 'The dashboard must stay entirely offline')
        self.assertEqual(self.writes, [], 'Read-only dashboard interactions must not create any HTTP writes')
        self.assertEqual(self.page_errors, [], 'Unexpected page JavaScript errors')

    def route(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.scheme != 'http' or parsed.netloc != '127.0.0.1:8020':
            self.external_requests.append(request.url)
            route.abort('blockedbyclient')
            return
        if request.method not in ('GET', 'HEAD'):
            self.writes.append(request.method + ' ' + parsed.path)
            route.fulfill(status=403, json={'detail': 'Offline dashboard checks forbid all mutations'})
            return
        if parsed.path == '/api/bootstrap':
            route.fulfill(json=bootstrap_fixture())
        elif parsed.path == '/api/insights':
            params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            self.insight_requests.append(params)
            response = report_fixture(params)
            if self.hold_next_insights:
                self.hold_next_insights = False
                self.pending_response = (route, response)
            else:
                route.fulfill(json=response)
        elif parsed.path == '/api/platform-strategies':
            route.fulfill(json={'items': []})
        elif parsed.path == '/api/tasks':
            route.fulfill(json={'items': [], 'total': 0, 'page': 1, 'pages': 1, 'page_size': 20})
        elif parsed.path == '/' or parsed.path.startswith('/static/'):
            target = ROOT / ('static/index.html' if parsed.path == '/' else parsed.path.lstrip('/'))
            target = target.resolve()
            if (ROOT / 'static').resolve() not in target.parents or not target.is_file():
                route.fulfill(status=404, body='Fixture asset not found')
                return
            route.fulfill(content_type=mimetypes.guess_type(target.name)[0] or 'application/octet-stream',
                          body=target.read_bytes())
        else:
            route.fulfill(status=404, json={'detail': 'Unexpected fixture endpoint'})

    def params(self):
        return {name: self.page.locator('#insights-' + name).input_value()
                for name in ('days', 'channel', 'platform', 'scope')}

    def current_report(self):
        return report_fixture(self.params())

    def wait_ready(self):
        self.page.wait_for_function('document.querySelector("#insights").getAttribute("aria-busy")==="false"&&document.querySelector("#insight-samples").textContent!=="—"')
        expected = self.current_report()['totals']['samples']
        self.page.wait_for_function('expected=>document.querySelector("#insight-samples").textContent===String(expected)', arg=expected)

    def set_filter(self, name, value):
        control = self.page.locator('#insights-' + name)
        if control.input_value() == value:
            return
        with self.page.expect_response(lambda response: urlsplit(response.url).path == '/api/insights'):
            control.select_option(value)
        self.wait_ready()

    def set_metric(self, metric):
        self.page.locator('#insights-dashboard [data-dashboard-metric="' + metric + '"]').click()
        self.page.wait_for_function('metric=>document.querySelector(`[data-dashboard-metric="${metric}"]`)?.getAttribute("aria-pressed")==="true"', arg=metric)

    def platform_row(self, platform):
        return self.page.locator('#insights-platform-chart [data-dashboard-platform="' + platform + '"]').first

    def capture_default_screenshot(self):
        if SCREENSHOT_PATH is None:
            return
        for name, value in (('channel', 'web'), ('platform', 'all'), ('scope', 'all'), ('days', '30')):
            self.set_filter(name, value)
        self.set_metric('brand_mentions')
        self.page.set_viewport_size({'width': 1440, 'height': 1200})
        self.page.evaluate('''()=>{
            const banner=document.createElement('div');banner.id='dashboard-fixture-label';
            banner.textContent='演示数据 · 全HTTP隔离验收夹具 · 统计占位数据，非平台真实回答 · 未发送任何问题';
            document.body.append(banner);
            const style=document.createElement('style');style.textContent=`
                #dashboard-fixture-label{position:fixed;inset:0 0 auto 0;height:32px;z-index:99999;display:flex;align-items:center;justify-content:center;background:#123b43;color:#e6fff5;border-bottom:1px solid #4d7b78;font:600 12px/1.4 'Microsoft YaHei',sans-serif;letter-spacing:.4px}
                body>aside{top:32px!important;height:calc(100dvh - 58px)!important}
                body:not(.landing-view)>main{margin-top:32px!important;height:calc(100dvh - 58px)!important}
            `;document.head.append(style);
            document.querySelector('main>.content').scrollTop=0;
            document.activeElement?.blur();
        }''')
        self.page.mouse.move(1, 1190)
        SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(SCREENSHOT_PATH), animations='disabled')

    def assert_chart(self, metric):
        report = self.current_report()
        max_samples = max((row['samples'] for row in report['platforms']), default=0)
        for platform in report['platforms']:
            with self.subTest(metric=metric, platform=platform['id']):
                row = self.platform_row(platform['id'])
                self.assertEqual(row.count(), 1)
                bar = row.locator('[role="progressbar"]')
                if platform['samples'] == 0:
                    self.assertEqual(bar.count(), 0)
                    self.assertRegex(row.inner_text(), r'暂无样本|无样本')
                    continue
                self.assertEqual(bar.count(), 1)
                numerator = platform[metric]
                denominator = max_samples if metric == 'samples' else platform['samples']
                self.assertEqual(float(bar.get_attribute('aria-valuenow')), numerator)
                self.assertEqual(float(bar.get_attribute('aria-valuemax')), denominator)
                ratio = bar.evaluate('''el=>{
                    const marked=el.querySelector('[data-dashboard-fill]')||el.querySelector('[style*="width"]');
                    const fill=marked||el.firstElementChild||el;
                    const track=fill===el?el.parentElement:el;
                    return {width:fill.getBoundingClientRect().width,track:track.getBoundingClientRect().width};
                }''')
                self.assertGreater(ratio['track'], 0)
                self.assertAlmostEqual(ratio['width'] / ratio['track'], numerator / denominator, delta=0.025,
                                       msg='The visible fill must match the platform-specific denominator')
                if metric != 'samples':
                    self.assertRegex(row.inner_text(), re.escape(str(numerator)) + r'\s*/\s*' + str(denominator))
                    self.assertIn('%', row.inner_text())

    def test_dashboard_renders_three_sections_and_exact_platform_denominators(self):
        self.assertEqual(self.current_report()['totals']['samples'], 7)
        for selector in ('#insights-trend', '#insights-platform-chart', '#insights-coverage'):
            self.assertEqual(self.page.locator('#insights-dashboard ' + selector).count(), 1)
        self.set_metric('brand_mentions')
        self.assert_chart('brand_mentions')  # Doubao 1/4, DeepSeek 1/2, Kimi 0/1.
        self.capture_default_screenshot()

    def test_zero_hits_with_samples_differs_from_zero_sample_empty_state(self):
        self.set_metric('brand_mentions')
        kimi = self.platform_row('kimi')
        self.assertEqual(kimi.locator('[role="progressbar"]').get_attribute('aria-valuenow'), '0')
        self.assertRegex(kimi.inner_text(), r'0\s*/\s*1')
        self.assertIn('0%', kimi.inner_text())
        qwen = self.platform_row('qwen')
        self.assertEqual(qwen.locator('[role="progressbar"]').count(), 0)
        self.assertRegex(qwen.inner_text(), r'暂无样本|无样本')

    def test_all_four_metrics_switch_and_keep_selection_after_refresh(self):
        for metric in METRICS:
            self.set_metric(metric)
            self.assert_chart(metric)
        with self.page.expect_response(lambda response: urlsplit(response.url).path == '/api/insights'):
            self.page.locator('#insights-refresh').click()
        self.wait_ready()
        self.assertEqual(self.page.locator('[data-dashboard-metric="samples"]').get_attribute('aria-pressed'), 'true')
        self.assert_chart('samples')

    def test_global_platform_scope_channel_and_date_filters_apply_to_dashboard(self):
        self.set_metric('official_links')
        self.set_filter('scope', 'all')
        self.assertEqual(self.current_report()['totals']['samples'], 11)
        self.assert_chart('official_links')
        self.set_filter('platform', 'deepseek')
        self.assertEqual(self.current_report()['totals']['samples'], 3)
        self.assertEqual(self.page.locator('#insights-platform-chart [role="progressbar"]').count(), 1)
        self.assert_chart('official_links')
        self.set_filter('channel', 'api')
        self.assertEqual(self.current_report()['totals']['samples'], 1)
        self.assert_chart('official_links')
        self.set_filter('platform', 'all')
        self.assertEqual(self.current_report()['totals']['samples'], 3)
        self.assert_chart('official_links')
        self.set_filter('channel', 'web')
        self.set_filter('scope', 'natural')
        self.set_filter('days', '30')
        self.assertEqual(self.current_report()['totals']['samples'], 8)
        self.assert_chart('official_links')
        self.assertEqual(self.insight_requests[-1], self.params())

    def test_platform_name_button_updates_the_global_platform_filter(self):
        with self.page.expect_response(lambda response: urlsplit(response.url).path == '/api/insights'):
            self.page.locator('#insights-platform-chart').get_by_role('button', name=re.compile('豆包')).click()
        self.wait_ready()
        self.assertEqual(self.page.locator('#insights-platform').input_value(), 'doubao')
        self.assertEqual(self.page.locator('#insight-samples').inner_text(), '4')

    def test_day_range_has_one_focus_stop_and_updates_daily_detail(self):
        trend = self.page.locator('#insights-trend')
        slider = trend.locator('input[type="range"][data-dashboard-day]')
        self.assertEqual(slider.count(), 1)
        self.assertEqual(trend.locator('svg [tabindex="0"]').count(), 0)
        last = int(slider.get_attribute('max'))
        slider.evaluate('(el,value)=>{el.value=String(value);el.dispatchEvent(new Event("input",{bubbles:true}));}', last - 1)
        detail = trend.locator('[data-dashboard-day-detail]')
        self.assertIn((TODAY - timedelta(days=1)).isoformat(), detail.inner_text())
        self.assertRegex(detail.inner_text(), r'计入样本\s*2\s*条')
        self.assertRegex(detail.inner_text(), r'提及品牌\s*1\s*条')
        self.assertRegex(detail.inner_text(), r'提及企业\s*1\s*条')
        self.assertRegex(detail.inner_text(), r'官网链接\s*1\s*条')
        slider.focus()
        self.page.keyboard.press('ArrowRight')
        self.assertEqual(int(slider.input_value()), last)
        self.assertIn(TODAY.isoformat(), detail.inner_text())
        self.assertRegex(detail.inner_text(), r'计入样本\s*3\s*条')

    def test_day_selection_and_chart_stay_visible_during_unchanged_read_refresh(self):
        self.set_metric('official_links')
        slider = self.page.locator('#insights-trend input[data-dashboard-day]')
        index = int(slider.get_attribute('max')) - 1
        slider.evaluate('(el,value)=>{el.value=String(value);el.dispatchEvent(new Event("input",{bubbles:true}));}', index)
        before = self.page.locator('[data-dashboard-day-detail]').inner_text()
        self.hold_next_insights = True
        self.page.locator('#insights-refresh').dispatch_event('click')
        self.page.wait_for_function('document.querySelector("#insights").getAttribute("aria-busy")==="true"')
        self.assertIsNotNone(self.pending_response)
        self.assertEqual(self.page.locator('#insights-dashboard').get_attribute('data-state'), 'ready')
        self.assertTrue(self.platform_row('doubao').is_visible())
        self.assertEqual(self.page.locator('[data-dashboard-day-detail]').inner_text(), before)
        route, response = self.pending_response
        route.fulfill(json=response)
        self.wait_ready()
        self.assertEqual(self.page.locator('[data-dashboard-day-detail]').inner_text(), before)
        self.assertEqual(self.page.locator('[data-dashboard-metric="official_links"]').get_attribute('aria-pressed'), 'true')
        self.assert_chart('official_links')

    def test_coverage_contains_included_counts_and_only_current_exclusions(self):
        coverage = self.page.locator('#insights-coverage')
        natural = coverage.inner_text()
        self.assertIn('7', natural)
        for pattern in ('资料', '指名|品牌', '未完成|未核对', '空回答', '连续', '来源'):
            self.assertRegex(natural, pattern)
        summary = coverage.locator('[role="img"]').get_attribute('aria-label')
        self.assertRegex(summary, r'共\s*14\s*条任务.*计入\s*7\s*条.*未计入\s*7\s*条')
        self.set_filter('scope', 'all')
        all_scope = coverage.inner_text()
        self.assertIn('11', all_scope)
        self.assertRegex(all_scope, r'3|未完成|未核对')
        reasons = coverage.locator('li').all_inner_texts()
        self.assertEqual(len(reasons), 2)
        self.assertTrue(any(re.search(r'未完成|未核对', reason) and '2' in reason for reason in reasons))
        self.assertTrue(any('空回答' in reason and '1' in reason for reason in reasons))

    def test_empty_selected_platform_has_explicit_trend_and_platform_empty_states(self):
        self.set_filter('platform', 'zhihu')
        self.assertEqual(self.page.locator('#insight-samples').inner_text(), '0')
        self.assertRegex(self.page.locator('#insights-trend').inner_text(), r'暂无|没有|无符合')
        self.assertRegex(self.page.locator('#insights-platform-chart').inner_text(), r'暂无样本|无样本')
        self.assertEqual(self.page.locator('#insights-platform-chart [role="progressbar"]').count(), 0)
        self.assertEqual(self.page.locator('#insights-trend input[type="range"][data-dashboard-day]').count(), 0)

    def test_dashboard_stays_within_responsive_viewports(self):
        for width in (1440, 768, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 1000})
                dimensions = self.page.locator('#insights-dashboard').evaluate('''el=>({
                    left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right,
                    client:el.clientWidth,scroll:el.scrollWidth,viewport:innerWidth,
                    pageScroll:document.documentElement.scrollWidth
                })''')
                self.assertGreater(dimensions['client'], 0)
                self.assertGreaterEqual(dimensions['left'], -1)
                self.assertLessEqual(dimensions['right'], dimensions['viewport'] + 1)
                self.assertLessEqual(dimensions['scroll'], dimensions['client'] + 2)
                self.assertLessEqual(dimensions['pageScroll'], dimensions['viewport'] + 2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--screenshot', type=Path)
    options, arguments = parser.parse_known_args()
    SCREENSHOT_PATH = options.screenshot.resolve() if options.screenshot else None
    unittest.main(argv=[sys.argv[0], *arguments], verbosity=2)
