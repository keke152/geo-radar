"""Offline DOM checks for conservative React div new-chat calibration.

Every HTTP request is intercepted. No account profile or live platform is used.
Run: .venv/Scripts/python tests/new_chat_control_checks.py
"""
import ast
import json
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def javascript_constant(filename, name):
    # Read only the JS constant: importing browser_bridge would load config/runtime.
    tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
    return next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and
                any(isinstance(target, ast.Name) and target.id == name for target in node.targets))


SCAN = javascript_constant('controls.py', 'CONTROL_SCAN')
PICKER = javascript_constant('browser_bridge.py', 'PICKER')
HTML = '''<!doctype html><meta charset="utf-8"><style>
div.frame{width:650px;min-height:50px}.entry{width:180px;height:44px;cursor:pointer;display:flex;align-items:center;gap:8px;border:1px solid #aaa;border-radius:20px}
.entry svg{width:24px;height:24px}.entry span{display:inline-block}
</style><div class="frame"><div class="entry" id="fresh-entry"><svg id="fresh-svg" viewBox="0 0 24 24"><path id="fresh-path" d="M2 2H22V22H2Z"/></svg><span id="fresh-label">开启新对话</span><span id="fresh-shortcut">Ctrl+J</span></div></div>
<div class="entry" id="ordinary">产品说明</div><textarea id="composer">PRIVATE_DRAFT_FIXTURE</textarea>
<button id="native-send" aria-label="发送" disabled><svg id="send-svg" width="24" height="24"><path d="M2 2H22V22H2Z"/></svg></button>
<script>window.originalClicks=0;document.querySelector('#fresh-entry').addEventListener('click',()=>window.originalClicks++);</script>'''


class NewChatControlChecks(unittest.TestCase):
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
        self.page.route('**/*', lambda route: route.fulfill(content_type='text/html; charset=utf-8', body=HTML))
        self.page.goto('https://fixture.invalid/')

    def scan(self, **config):
        return self.page.evaluate(SCAN, {'config': {'composer': '#composer', **config}, 'include_candidates': True})

    def pick(self, selector, kind='new_chat_selector'):
        self.page.evaluate(PICKER, kind)
        self.page.locator(selector).dispatch_event('click')
        return self.page.evaluate('window.__junhePick')

    def test_react_div_without_dom_onclick_is_discovered(self):
        self.assertTrue(self.page.locator('#fresh-entry').evaluate('(el)=>el.onclick===null&&!el.hasAttribute("role")'))
        result = self.scan()
        self.assertEqual(result['suggestions']['new_chat_selector'], '#fresh-entry')
        self.assertEqual(len(result['candidates']['new_chat']), 1)
        self.assertTrue(result['candidates']['new_chat_labels'])
        self.assertNotIn('PRIVATE_DRAFT_FIXTURE', json.dumps(result))

    def test_text_shortcut_svg_and_path_all_normalize_to_outer_entry(self):
        for selector in ('#fresh-entry', '#fresh-label', '#fresh-shortcut', '#fresh-svg', '#fresh-path'):
            with self.subTest(selector=selector):
                result = self.scan(new_chat_selector=selector)
                self.assertTrue(result['new_chat_found'])
                self.assertEqual(result['controls']['new_chat_selector']['selector'], '#fresh-entry')
                picked = self.pick(selector)
                self.assertNotIn('invalid', picked)
                self.assertEqual(picked['selector'], '#fresh-entry')
                self.assertEqual(self.page.evaluate('window.originalClicks'), 0)
                self.assertEqual(self.page.locator('#composer').input_value(), 'PRIVATE_DRAFT_FIXTURE')

    def test_semantic_div_rule_does_not_accept_a_send_target(self):
        result = self.scan(send_button='#fresh-entry')
        self.assertEqual(result['controls']['send_button']['state'], 'wrong_target')
        picked = self.pick('#fresh-label', 'send_button')
        self.assertTrue(picked['invalid'])
        self.assertIn('发送', picked['error'])
        self.assertEqual(self.page.evaluate('window.originalClicks'), 0)

    def test_ordinary_pointer_region_and_editor_are_rejected_with_new_chat_hint(self):
        for selector in ('#ordinary', '#composer'):
            with self.subTest(selector=selector):
                result = self.scan(new_chat_selector=selector)
                self.assertEqual(result['controls']['new_chat_selector']['state'], 'wrong_target')
                self.assertIn('新对话', result['controls']['new_chat_selector']['message'])
                picked = self.pick(selector)
                self.assertTrue(picked['invalid'])
                self.assertIn('新对话', picked['error'])
                self.assertNotIn('发送', picked['error'])

    def test_only_full_short_action_labels_are_accepted(self):
        for label in ('新对话', '开启新对话', 'New chat', 'New chat Ctrl+J', '开启新对话 Ctrl + J'):
            with self.subTest(label=label):
                self.page.locator('#fresh-entry').evaluate('(el,text)=>el.textContent=text', label)
                self.assertTrue(self.scan(new_chat_selector='#fresh-entry')['new_chat_found'])
                self.assertEqual(self.pick('#fresh-entry')['selector'], '#fresh-entry')
        for label in ('查看新对话说明', '开启新对话后会清空草稿', 'New chat documentation', '新建群聊'):
            with self.subTest(label=label):
                self.page.locator('#fresh-entry').evaluate('(el,text)=>el.textContent=text', label)
                self.assertFalse(self.scan(new_chat_selector='#fresh-entry')['new_chat_found'])
                self.assertTrue(self.pick('#fresh-entry')['invalid'])

    def test_non_pointer_tiny_oversized_or_editor_wrappers_are_not_controls(self):
        for style in ('cursor:auto', 'height:18px', 'width:600px', 'height:200px'):
            with self.subTest(style=style):
                self.page.locator('#fresh-entry').evaluate('(el,style)=>el.style.cssText=style', style)
                self.assertFalse(self.scan(new_chat_selector='#fresh-entry')['new_chat_found'])
                self.assertTrue(self.pick('#fresh-label')['invalid'])
        self.page.locator('#fresh-entry').evaluate('(el)=>{el.style.cssText="";el.innerHTML="<div contenteditable=true>开启新对话</div>";}')
        self.assertFalse(self.scan(new_chat_selector='#fresh-entry')['new_chat_found'])
        self.assertTrue(self.pick('#fresh-entry [contenteditable]')['invalid'])

    def test_disabled_div_is_found_but_not_enabled(self):
        self.page.locator('#fresh-entry').evaluate('(el)=>el.setAttribute("aria-disabled","true")')
        result = self.scan(new_chat_selector='#fresh-shortcut')
        self.assertTrue(result['new_chat_found'])
        self.assertFalse(result['controls']['new_chat_selector']['enabled'])
        self.assertEqual(result['controls']['new_chat_selector']['state'], 'disabled')

    def test_ambiguous_entries_are_not_suggested_automatically(self):
        self.page.evaluate('()=>{const second=document.querySelector("#fresh-entry").cloneNode(true);second.id="other-entry";document.body.append(second);}')
        result = self.scan()
        self.assertNotIn('new_chat_selector', result['suggestions'])
        self.assertEqual(len(result['candidates']['new_chat']), 2)

    def test_native_buttons_and_svg_normalization_keep_existing_behavior(self):
        self.page.evaluate('()=>{const native=document.createElement("button"),label=document.createElement("span");native.id="native-new";label.id="native-label";label.textContent="新对话";native.append(label);document.body.append(native);}')
        result = self.scan(new_chat_selector='#native-label', send_button='#send-svg')
        self.assertEqual(result['controls']['new_chat_selector']['selector'], '#native-new')
        self.assertTrue(result['controls']['send_button']['found'])
        self.assertFalse(result['controls']['send_button']['enabled'])
        self.assertEqual(self.pick('#native-label')['selector'], '#native-new')


if __name__ == '__main__':
    unittest.main(verbosity=2)
