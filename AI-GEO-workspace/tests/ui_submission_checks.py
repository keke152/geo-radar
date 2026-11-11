"""Offline Edge checks for draft preservation and idempotent creation recovery.

Every HTTP request is intercepted. No server, account, or AI platform is used.
Run: .venv/Scripts/python tests/ui_submission_checks.py
"""
from pathlib import Path
import json
import re
import unittest

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HTML = re.sub(r'<script\b[^>]*>.*?</script>', '',
              (ROOT / 'static/index.html').read_text(encoding='utf-8'), flags=re.S)
SCRIPT = (ROOT / 'static/platform-plans.js').read_text(encoding='utf-8')
GLOBALS = r'''
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data={daily_budget:{remaining:300,limit:300}},batchKey=crypto.randomUUID();
const selected=s=>[...document.querySelectorAll(s+' input:checked')].map(x=>x.value);
const WorkspaceConnection={state:{problem:false}};
async function api(url,options={}){const r=await fetch(url,options),value=await r.json();if(!r.ok){const e=Error(value.detail);e.status=r.status;throw e;}return value;}
const post=(url,body)=>api(url,{method:'POST',body:JSON.stringify(body)}),put=(url,body)=>api(url,{method:'PUT',body:JSON.stringify(body)});
function guard(){}
function toast(message){window.lastToast=message;}
function showModal(title,body){window.preview={title,body};}
async function load(){}
window.createdCallbacks=0;
window.onBatchCreated=()=>{window.createdCallbacks++;$('#task-composer').close();};
window.openTaskComposer=()=>{if(!$('#task-composer').open)$('#task-composer').showModal();};
for(const container of ['#batch-platforms','#schedule-platforms'])$(container).innerHTML='<label><input type="checkbox" value="doubao" checked>豆包</label>';
'''


class SubmissionChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel='msedge', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.batches = {}
        self.requests = []
        self.previews = []
        self.held = []
        self.action = 'success'
        self.page.route('**/*', self.route)
        self.open()

    def route(self, route):
        path = route.request.url.split('fixture.invalid', 1)[-1]
        if path == '/':
            document = HTML + '<script>' + GLOBALS + '</script><script>' + SCRIPT + '</script><script>window.renderImprovements?.();</script>'
            route.fulfill(content_type='text/html; charset=utf-8', body=document)
        elif path == '/api/platform-strategies':
            route.fulfill(json={'items': []})
        elif path == '/api/platform-prompts/preview':
            body = route.request.post_data_json
            self.previews.append(body)
            route.fulfill(json={'items': [{**item, 'prompt': item['text']} for item in body['items']]})
        elif path == '/api/platform-batches':
            body = route.request.post_data_json
            self.requests.append(body)
            if self.action == 'reject':
                route.fulfill(status=400, json={'detail': 'fixture validation rejected'})
                return
            key = body['request_key']
            signature = json.dumps({k: body[k] for k in ('items', 'mode', 'conversation_mode')}, sort_keys=True)
            reused = key in self.batches
            if reused and self.batches[key] != signature:
                route.fulfill(status=400, json={'detail': 'same key with different contents'})
                return
            self.batches[key] = signature
            result = {'created': 0 if reused else len(body['items']), 'reused': reused}
            if self.action == 'hold':
                self.held.append((route, result))
            elif self.action == 'drop':
                route.abort()
            elif self.action == 'server_error':
                route.fulfill(status=500, json={'detail': 'fixture response failed after commit'})
            else:
                route.fulfill(json=result)
        else:
            # CSS, images, and any other asset are also served offline.
            route.fulfill(content_type='text/plain', body='')

    def open(self):
        self.page.goto('https://fixture.invalid/')
        self.page.wait_for_function('Boolean(window.PlatformPlans)')

    def add(self, text='原始问题'):
        self.page.evaluate('text=>PlatformPlans.add({platform:"doubao",text,goal:"source_audit",source_focus:"consumer_scenarios"})', text)

    def edit(self, text):
        self.page.locator('#platform-plan-items textarea').fill(text)

    def submit(self):
        self.page.locator('#create-batch').click()

    def wait_idle(self):
        self.page.wait_for_function('!document.querySelector("#create-batch").disabled')

    def saved(self):
        return self.page.evaluate('JSON.parse(sessionStorage.getItem("geo-platform-plan-draft-v2"))')

    def test_success_clears_only_unchanged_draft(self):
        self.add()
        self.submit()
        self.page.wait_for_function('window.createdCallbacks===1')
        self.assertEqual(self.page.evaluate('PlatformPlans.items()'), [])
        self.assertIsNone(self.saved()['pending_batch'])
        self.assertEqual(len(self.batches), 1)
        self.assertFalse(self.page.locator('#task-composer').evaluate('(el)=>el.open'))

    def test_edits_during_submission_remain_until_next_confirmation(self):
        self.action = 'hold'
        self.add()
        self.submit()
        self.page.wait_for_function('document.querySelector("#create-batch").disabled')
        self.assertEqual(len(self.held), 1)
        self.edit('等待响应期间修改的问题')
        route, result = self.held.pop()
        route.fulfill(json=result)
        self.wait_idle()
        self.assertEqual(self.page.evaluate('PlatformPlans.items()[0].text'), '等待响应期间修改的问题')
        self.assertEqual(self.page.evaluate('window.createdCallbacks'), 0)
        self.assertTrue(self.page.locator('#task-composer').evaluate('(el)=>el.open'))
        self.assertEqual(self.requests[0]['items'][0]['text'], '原始问题')
        self.assertEqual(len(self.batches), 1)
        self.action = 'success'
        self.submit()
        self.page.wait_for_function('window.createdCallbacks===1')
        self.assertEqual(len(self.batches), 2)
        self.assertNotEqual(self.requests[0]['request_key'], self.requests[1]['request_key'])

    def test_lost_response_reload_retries_snapshot_despite_new_invalid_draft_and_quota(self):
        self.action = 'drop'
        self.add()
        self.submit()
        self.wait_idle()
        self.assertIn('重试上次确认', self.page.locator('#create-batch').inner_text())
        first_key = self.requests[0]['request_key']
        self.edit('刷新之前的新草稿')
        self.page.reload()
        self.page.wait_for_function('Boolean(window.PlatformPlans)')
        self.assertEqual(self.page.evaluate('PlatformPlans.items()[0].text'), '刷新之前的新草稿')
        self.page.evaluate('openTaskComposer()')
        self.edit('')
        self.page.evaluate('data.daily_budget.remaining=0;PlatformPlans.updateBudget()')
        self.assertTrue(self.page.locator('#create-batch').is_enabled())
        self.page.locator('#preview-prompt').click()
        self.page.wait_for_function('Boolean(window.preview)')
        self.assertEqual(self.previews[-1]['items'][0]['text'], '原始问题')
        self.action = 'success'
        self.submit()
        self.page.wait_for_function('document.querySelector("#platform-plan-feedback").textContent.includes("修改后的草稿已保留")')
        self.assertEqual(len(self.batches), 1)
        self.assertEqual(first_key, self.requests[1]['request_key'])
        self.assertEqual(self.requests[1]['items'][0]['text'], '原始问题')
        self.assertEqual(self.page.evaluate('PlatformPlans.items()[0].text'), '')
        self.assertEqual(self.page.evaluate('window.createdCallbacks'), 0)
        self.assertIsNone(self.saved()['pending_batch'])

    def test_server_error_preserves_pending_key(self):
        self.action = 'server_error'
        self.add()
        self.submit()
        self.wait_idle()
        key = self.saved()['pending_batch']['request']['request_key']
        self.action = 'success'
        self.submit()
        self.page.wait_for_function('window.createdCallbacks===1')
        self.assertEqual(self.requests[1]['request_key'], key)
        self.assertEqual(len(self.batches), 1)

    def test_explicit_validation_rejection_releases_request_for_corrected_draft(self):
        self.action = 'reject'
        self.add()
        self.submit()
        self.wait_idle()
        self.assertIsNone(self.saved()['pending_batch'])
        self.edit('修正后的问题')
        self.action = 'success'
        self.submit()
        self.page.wait_for_function('window.createdCallbacks===1')
        self.assertNotEqual(self.requests[0]['request_key'], self.requests[1]['request_key'])
        self.assertEqual(self.requests[1]['items'][0]['text'], '修正后的问题')
        self.assertEqual(len(self.batches), 1)

    def test_storage_failure_prevents_unrecoverable_submission(self):
        self.page.evaluate('()=>{Storage.prototype.setItem=function(){throw new DOMException("fixture quota exceeded","QuotaExceededError")};}')
        self.add()
        self.submit()
        self.assertIn('无法保存本次请求编号', self.page.locator('#platform-plan-feedback').inner_text())
        self.assertEqual(self.requests, [])
        self.assertEqual(self.page.evaluate('PlatformPlans.items()[0].text'), '原始问题')


if __name__ == '__main__':
    unittest.main(verbosity=2)
