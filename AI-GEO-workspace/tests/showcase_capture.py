"""Capture the real UI using isolated, clearly labelled demonstration records.

Run from the project root:
    .venv/Scripts/python tests/showcase_capture.py

All browser HTTP is intercepted and handled by an isolated FastAPI TestClient.
Its real worker and scheduler run on the TestClient event loop with the queue
paused, keyword generation disabled, and execution schedules empty. Browser/API
send methods are hard-failing mocks asserted never called. There is no listening
server, user browser profile, or external platform call.
Completed fixture records contain labelled name-matching placeholders, never
purported AI responses. The showcase ribbon is injected only by this script.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
CST = timezone(timedelta(hours=8))
ORIGIN = 'http://127.0.0.1:8020'
DEMO = '演示数据'
PROFILE = {
    'company_name': '海岚生物（演示企业）', 'domain': 'example.invalid',
    'aliases': ['海岚生物'], 'business': '益生菌食品经销合作（演示主题）',
    'audience': '经销商与零售门店（演示设定）', 'audience_confirmed': False,
    'public_intro': '演示数据：虚构企业资料，仅用于展示本地工作台，不对应实际经营主体。',
    'brand_name': '蓝禾（演示品牌）', 'brand_aliases': ['蓝禾'],
    'brand_relation': '演示数据：虚构品牌与虚构企业，仅用于界面功能说明。',
}

RIBBON = r'''
document.addEventListener('DOMContentLoaded',()=>{
 const ribbon=document.createElement('div');ribbon.id='showcase-demo-ribbon';ribbon.setAttribute('popover','manual');
 ribbon.setAttribute('role','note');
 ribbon.innerHTML='<b>演示数据</b><span>隔离本地环境 · 合成占位记录 · 非平台实际回答 · 未连接账号或发送问题</span>';
 document.body.append(ribbon);
 const style=document.createElement('style');
 style.textContent=`
 #showcase-demo-ribbon{position:fixed;inset:0 0 auto 0;margin:0;width:100%;max-width:none;height:34px;padding:0;box-sizing:border-box;z-index:2147483647;display:flex;align-items:center;justify-content:center;gap:14px;background:#123743;color:#d5eeed;border:0;border-bottom:1px solid #37626a;font:11px/1.4 'Microsoft YaHei UI','Microsoft YaHei',sans-serif;letter-spacing:.3px;pointer-events:none}
 #showcase-demo-ribbon b{font-size:11px;color:#e6ffef;background:#25534f;border:1px solid #47796d;border-radius:4px;padding:2px 9px;letter-spacing:1px}
 body>aside{top:34px!important;height:calc(100dvh - 60px)!important}
 body:not(.landing-view)>main{margin-top:34px!important;height:calc(100dvh - 60px)!important}
 body.landing-view>main{padding-top:34px!important}
 dialog{max-height:calc(100dvh - 80px)!important}
 dialog[open]{margin-top:54px!important}
 `;
 document.head.append(style);
});
'''


def seed_demo():
    """Write only the newly created disposable database."""
    from config import PLATFORMS
    from storage import db, ident, now, set_meta
    import platform_planner

    set_meta('profile', PROFILE)
    set_meta('settings', {'interval_seconds': 45, 'daily_limit': 300,
                         'paused': True, 'parallel_platforms': 6, 'auto_verify': True})
    set_meta('keyword_plan', {'enabled': False, 'time': '09:00', 'count': 10,
                             'platforms': list(PLATFORMS), 'goal': 'source_audit'})
    with db() as connection:
        for table in ('tasks', 'batches', 'documents', 'keywords', 'platform_keywords',
                      'schedules', 'platform_schedules'):
            connection.execute('DELETE FROM ' + table)
        connection.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',
                           (ident(), '企业公开简介（演示数据）', PROFILE['public_intro'],
                            '本地合成资料，不对应真实企业', 0, now()))

    topic = PROFILE['business']
    planned = platform_planner.preview_plan(topic, list(PLATFORMS), 'source_audit', 1)['items']
    for item in planned:
        platform_planner.save_keyword({**item, 'reason': '演示数据：本地模板规划，尚未向任何平台发送。'})

    today = datetime.now(CST).replace(hour=10, minute=0, second=0, microsecond=0)
    rows = []
    for day_offset, count in enumerate((4, 5, 7, 6, 8, 6, 6)):
        stamp = today - timedelta(days=6 - day_offset)
        for index in range(count):
            pid = list(PLATFORMS)[(index + day_offset) % len(PLATFORMS)]
            terms = ['【演示数据 · 非平台回答】本地统计占位文本，仅用于展示名称匹配与看板。']
            if (index + day_offset) % 3 != 0:
                terms.append('占位品牌名称：蓝禾。')
            if (index + 2 * day_offset) % 4 != 0:
                terms.append('占位企业名称：海岚生物。')
            if (index + day_offset) % 3 == 0:
                terms.append('占位链接：https://example.invalid/。')
            rows.append({
                'id': ident(), 'batch_id': 'showcase-synthetic', 'platform': pid,
                'channel': 'web', 'mode': 'visibility',
                'keyword': f'【演示】益生菌食品经销合作应核对哪些信息 · 场景{day_offset + 1}-{index + 1}',
                'prompt': '演示数据：本地占位提示词，没有调用模型或发送到平台。',
                'status': 'completed', 'answer': '\n'.join(terms),
                'note': '演示数据：本地合成记录，非平台实际回答。', 'screenshot': '',
                'metrics': json.dumps({'conversation_mode': 'fresh', 'goal': 'discovery',
                                       'verification_method': 'showcase_placeholder',
                                       'showcase_demo': True}, ensure_ascii=False),
                'reviewed': 1, 'sent_at': stamp.isoformat(),
                'created_at': stamp.isoformat(), 'updated_at': stamp.isoformat(),
            })
    pending_questions = [
        '消费者选购益生菌食品会关注哪些标签信息？',
        '益生菌食品资料的证据与发布日期如何核对？',
        '经销合作资料应如何整理为核查清单？',
        '益生菌产品对比应记录哪些规格字段？',
        '公众号中的经销合作信息如何追溯原文？',
        '问答中的产品观点如何区分经验与事实？',
    ]
    for index, pid in enumerate(PLATFORMS):
        stamp = (today + timedelta(minutes=10 + index)).isoformat()
        row = {**rows[-1], 'id': ident(), 'platform': pid,
               'keyword': '【演示】' + pending_questions[index],
               'status': ('waiting_setup', 'needs_review', 'interrupted')[index % 3],
               'answer': '', 'reviewed': 0, 'sent_at': None,
               'created_at': stamp, 'updated_at': stamp,
               'note': '演示数据：等待配置与人工核对的流程示意；没有连接平台或执行发送。'}
        rows.append(row)
    with db() as connection:
        for row in rows:
            connection.execute('INSERT INTO tasks(' + ','.join(row) + ') VALUES(' +
                               ','.join('?' for _ in row) + ')', list(row.values()))
    return {'completed_placeholders': 42, 'attention_placeholders': 6,
            'platforms': len(PLATFORMS), 'profile': PROFILE['company_name']}


def capture(output: Path):
    # Set before importing any project modules, including config and its dotenv.
    scratch = tempfile.TemporaryDirectory(prefix='geo-radar-showcase-')
    os.environ['JUNHE_HOME'] = scratch.name
    os.environ['JUNHE_DISABLE_WORKER'] = '1'
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    for variable in ('ARK_API_KEY', 'DEEPSEEK_API_KEY', 'MOONSHOT_API_KEY', 'DASHSCOPE_API_KEY'):
        os.environ.pop(variable, None)
    sys.path.insert(0, str(ROOT))

    from fastapi.testclient import TestClient
    from playwright.sync_api import sync_playwright
    import app
    from config import HOME
    from storage import db

    assert HOME == Path(scratch.name).resolve(), 'Showcase must use disposable storage'
    output.mkdir(parents=True, exist_ok=True)
    external = []
    writes = []
    page_errors = []
    shots = []
    with scratch, patch('browser_bridge.BrowserBridge.send', new_callable=AsyncMock,
                        side_effect=AssertionError('Showcase forbids browser sends')) as browser_send, \
            patch('engine.api_send', new_callable=AsyncMock,
                  side_effect=AssertionError('Showcase forbids API sends')) as api_send, \
            TestClient(app.app, base_url=ORIGIN) as client:
        fixture = seed_demo()
        # Start on the application's existing event loop only after isolation and
        # all send barriers are in place. Queue health comes from the real runner.
        client.portal.call(app.runner.start)
        initial_queue = client.get('/api/health').json()['queue']
        assert initial_queue['worker_alive'] and initial_queue['scheduler_alive']
        assert initial_queue['state'] == 'paused' and not initial_queue['error']
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 950},
                                          device_scale_factor=1, locale='zh-CN',
                                          timezone_id='Asia/Shanghai', reduced_motion='reduce')
            context.add_init_script(RIBBON)

            def route_local(route):
                request = route.request
                parsed = urlsplit(request.url)
                if parsed.scheme != 'http' or parsed.netloc != '127.0.0.1:8020':
                    external.append(request.url)
                    route.abort('blockedbyclient')
                    return
                path = parsed.path + ('?' + parsed.query if parsed.query else '')
                if request.method not in ('GET', 'HEAD'):
                    writes.append(path)
                    if path not in ('/api/platform-plans/preview', '/api/platform-prompts/preview'):
                        route.fulfill(status=403, json={'detail': 'Showcase forbids execution and account operations'})
                        return
                headers = {key: value for key, value in request.all_headers().items()
                           if key not in ('host', 'content-length', 'connection')}
                response = client.request(request.method, path, headers=headers,
                                          content=request.post_data_buffer)
                response_headers = {key: value for key, value in response.headers.items()
                                    if key not in ('content-encoding', 'content-length', 'transfer-encoding')}
                route.fulfill(status=response.status_code, headers=response_headers, body=response.content)

            context.route('**/*', route_local)
            page = context.new_page()
            page.on('pageerror', lambda error: page_errors.append(str(error)))

            def save(name, scene):
                page.evaluate('document.activeElement?.blur()')
                # A top-layer ribbon remains readable above a modal's backdrop.
                page.evaluate('()=>{const ribbon=document.querySelector("#showcase-demo-ribbon");if(ribbon.matches(":popover-open"))ribbon.hidePopover();ribbon.showPopover();}')
                page.mouse.move(1, 940)
                page.screenshot(path=str(output / name), animations='disabled')
                shots.append({'file': name, 'scene': scene, 'width': page.viewport_size['width'],
                              'height': page.viewport_size['height'], 'demo_ribbon': True})

            page.goto(ORIGIN + '/#home')
            page.wait_for_function('typeof data!=="undefined"&&data?.profile?.company_name.includes("演示企业")')
            page.wait_for_function('document.querySelector(".landing-visual").dataset.globeTexture==="ready"&&document.querySelector(".landing-visual").dataset.globeClouds==="ready"&&document.querySelector(".landing-visual").dataset.globeLand==="ready"')
            page.locator('#home-question').fill(PROFILE['business'])
            page.locator('#geo-reset').click()
            save('home.png', '真实地球产品首页；六个平台均未连接，仅展示本机连接状态')

            page.locator('#home-start').click()
            page.wait_for_selector('#task-composer[open]')
            page.set_viewport_size({'width': 1440, 'height': 1160})
            for checkbox in page.locator('#batch-platforms input').all():
                checkbox.set_checked(checkbox.input_value() in ('doubao', 'deepseek'))
            page.locator('#build-platform-plan').click()
            page.wait_for_function('PlatformPlans.items().length===2')
            page.locator('#batch-form').evaluate('(form)=>form.scrollTop=0')
            save('planner.png', '真实本地模板生成的双平台独立问题方案；未点击创建')
            page.locator('#client-compose-close').click()
            page.set_viewport_size({'width': 1440, 'height': 950})

            page.locator('[data-client-group="attention"]').click()
            page.wait_for_function('document.querySelector("#client-list-count").textContent.includes("6 条")')
            save('workspace.png', '任务工作台；演示待配置、待核对与中断状态，后台已暂停')

            page.locator('[data-view="insights"]').click()
            page.locator('#insights-days').select_option('7')
            page.wait_for_function('document.querySelector("#insight-samples").textContent==="42"&&document.querySelectorAll("#insights-platform-table tbody tr").length===6')
            page.wait_for_function('document.querySelector("#insights").getAttribute("aria-busy")==="false"')
            page.locator('main>.content').evaluate('(content)=>content.scrollTop=270')
            save('insights.png', '统计看板核心指标与六平台明细；42条名称匹配占位记录，不代表平台实测')

            page.locator('[data-view="results"]').click()
            page.locator('#task-platform').select_option('doubao')
            page.locator('#task-filter').select_option('completed')
            page.wait_for_function('document.querySelector("#task-list").getAttribute("aria-busy")==="false"&&document.querySelector("#records-count").textContent.includes("共 6 条")')
            save('records.png', '历史记录；真实分页、平台筛选与导出入口，条目均为本地演示数据')

            assert not external, f'External requests blocked: {external}'
            assert not page_errors, f'UI errors: {page_errors}'
            assert writes == ['/api/platform-plans/preview'], f'Unexpected mutations: {writes}'
            final_queue = client.get('/api/health').json()['queue']
            assert final_queue['worker_alive'] and final_queue['scheduler_alive']
            assert final_queue['state'] == 'paused' and not final_queue['error']
            with db() as connection:
                assert connection.execute('SELECT count(*) FROM batches').fetchone()[0] == 0
                assert connection.execute('SELECT count(*) FROM tasks').fetchone()[0] == 48
                assert connection.execute('SELECT count(*) FROM schedules').fetchone()[0] == 0
                assert connection.execute('SELECT count(*) FROM platform_schedules').fetchone()[0] == 0
            browser_send.assert_not_called()
            api_send.assert_not_called()
            context.close()
            browser.close()
        client.portal.call(app.runner.stop)
        runner_stopped = all(job.done() for job in app.runner.jobs)
        assert runner_stopped

    report = {'application': 'GEO Radar · 品牌雷达',
              'captured_at': datetime.now(CST).isoformat(timespec='seconds'),
              'data_label': DEMO, 'fixture': fixture, 'screenshots': shots,
              'all_http_intercepted': True, 'external_requests': 0,
              'platform_messages_sent': 0, 'created_batches': 0, 'page_errors': page_errors,
              'local_mutations': writes,
              'real_runner': {'worker_alive_during_capture': final_queue['worker_alive'],
                              'scheduler_alive_during_capture': final_queue['scheduler_alive'],
                              'queue_state': final_queue['state'], 'stopped_after_capture': runner_stopped},
              'send_barriers': {'BrowserBridge.send_calls': browser_send.call_count,
                                'engine.api_send_calls': api_send.call_count,
                                'keyword_plan_enabled': False, 'execution_schedule_count': 0},
              'sample_note': '样本为明确标注的名称匹配占位文本，并非任何平台实际回答；统计数字不能作为平台评估证据。'}
    (output / 'capture-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/images/showcase')
    capture(parser.parse_args().output.resolve())
