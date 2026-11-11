"""Offline page-state checks with every browser request intercepted.

Run: .venv/Scripts/python tests/page_guard_checks.py
No runtime database, environment credentials, or saved browser profile is used.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from page_guard import PAGE_GUARD_SCAN, PAGE_GUARD_RESULTS
from playwright.sync_api import sync_playwright


def main():
    sentinel = 'PRIVATE_OFFLINE_ACCOUNT_AND_DRAFT_SENTINEL'
    cases = [
        ('normal_chat', 'doubao', 'https://www.doubao.com/chat/', '<h1>有什么我能帮你的吗？</h1><textarea>验证码和操作频繁只是草稿内容</textarea>', 'ready'),
        ('answer_heading_is_not_security_ui', 'deepseek', 'https://chat.deepseek.com/', '<div data-message-role="assistant"><h1>安全验证</h1><p>示例介绍，不是平台验证。</p></div><textarea></textarea>', 'ready'),
        ('markdown_alert_is_not_rate_limit', 'deepseek', 'https://chat.deepseek.com/', '<div class="ds-markdown"><h2>验证码</h2><div role="alert">请求过于频繁，请稍后再试</div></div>', 'ready'),
        ('quoted_html_is_not_login_form', 'kimi', 'https://www.kimi.com/', '<article><input type="password"><input autocomplete="one-time-code"></article>', 'ready'),
        ('generic_answer_html_form', 'deepseek', 'https://chat.deepseek.com/', '<div data-role="assistant"><input type="password"><input autocomplete="one-time-code"></div>', 'ready'),
        ('deepseek_content_heading', 'deepseek', 'https://chat.deepseek.com/', '<div class="ds-assistant-message-main-content"><h1>安全验证</h1><div role="alert">请求频率过高</div></div>', 'ready'),
        ('yuanbao_content_heading', 'yuanbao', 'https://yuanbao.tencent.com/', '<div class="hyc-content-text"><h1>安全验证</h1></div>', 'ready'),
        ('editable_html_example', 'doubao', 'https://www.doubao.com/chat/', '<div contenteditable="true"><h1>安全验证</h1><input type="password"><input autocomplete="one-time-code"></div>', 'ready'),
        ('chat_mentions_zhihu_error', 'zhihu', 'https://zhida.zhihu.com/search/123', '<div class="Render-markdown">10001:请求参数异常，请升级客户端后重试</div>', 'ready'),
        ('title_is_not_security_ui', 'doubao', 'https://www.doubao.com/chat/', '<title>安全验证</title><textarea></textarea>', 'ready'),
        ('hidden_password', 'kimi', 'https://www.kimi.com/', '<div style="display:none"><input type="password"></div>', 'ready'),
        ('transparent_login_template', 'kimi', 'https://www.kimi.com/', '<div style="opacity:0"><h1>登录</h1><input type="password"></div>', 'ready'),
        ('offscreen_password', 'kimi', 'https://www.kimi.com/', '<input type="password" style="position:fixed;left:-10000px">', 'ready'),
        ('login_link_is_not_login_page', 'qwen', 'https://www.qianwen.com/', '<a href="/signin">登录</a><textarea></textarea>', 'ready'),
        ('known_login_route', 'deepseek', 'https://chat.deepseek.com/sign_in?redirect=PRIVATE_OFFLINE_ACCOUNT_AND_DRAFT_SENTINEL', '<main></main>', 'login_required'),
        ('similar_path_is_not_login_route', 'doubao', 'https://www.doubao.com/login-help', '<p>登录教程</p>', 'ready'),
        ('foreign_host_is_not_platform', 'zhihu', 'https://fixture.invalid/signin', '<h1>登录</h1><input type="password">', 'ready'),
        ('mismatched_platform', 'zhihu', 'https://chat.deepseek.com/sign_in', '<input type="password">', 'ready'),
        ('modal_password_login', 'doubao', 'https://www.doubao.com/chat/', '<div role="dialog"><h2>账号密码登录</h2><input type="password" value="PRIVATE_OFFLINE_ACCOUNT_AND_DRAFT_SENTINEL"></div>', 'login_required'),
        ('qr_login_dialog', 'yuanbao', 'https://yuanbao.tencent.com/', '<div role="dialog" aria-modal="true"><h2>扫码登录</h2><div role="img" aria-label="登录二维码"></div></div>', 'login_required'),
        ('standalone_password', 'kimi', 'https://www.kimi.com/', '<form><input type="password"></form>', 'login_required'),
        ('one_time_code', 'qwen', 'https://www.qianwen.com/', '<form><input autocomplete="one-time-code" value="PRIVATE_OFFLINE_ACCOUNT_AND_DRAFT_SENTINEL"></form>', 'security_verification'),
        ('visible_challenge_frame', 'doubao', 'https://www.doubao.com/chat/', '<iframe src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/test?token=PRIVATE_OFFLINE_ACCOUNT_AND_DRAFT_SENTINEL"></iframe>', 'security_verification'),
        ('hidden_challenge_frame', 'doubao', 'https://www.doubao.com/chat/', '<iframe style="display:none" src="https://challenges.cloudflare.com/test"></iframe>', 'ready'),
        ('embedded_answer_frame_is_not_challenge', 'doubao', 'https://www.doubao.com/chat/', '<article><iframe src="https://challenges.cloudflare.com/example"></iframe></article>', 'ready'),
        ('recaptcha_frame', 'deepseek', 'https://chat.deepseek.com/', '<iframe src="https://www.recaptcha.net/recaptcha/api2/anchor?k=offline"></iframe>', 'security_verification'),
        ('tencent_challenge_frame', 'yuanbao', 'https://yuanbao.tencent.com/', '<iframe src="https://t.captcha.qq.com/example"></iframe>', 'security_verification'),
        ('unrelated_video_frame', 'yuanbao', 'https://yuanbao.tencent.com/', '<iframe title="如何使用验证码" src="https://video.example.invalid/captcha/tutorial"></iframe>', 'ready'),
        ('security_heading', 'doubao', 'https://www.doubao.com/chat/', '<h1>安全验证</h1><p>请在平台界面完成。</p>', 'security_verification'),
        ('security_guide_is_not_challenge', 'doubao', 'https://www.doubao.com/chat/', '<h1>安全验证方案指南</h1>', 'ready'),
        ('plain_security_dialog', 'kimi', 'https://www.kimi.com/', '<div role="dialog"><span>请完成安全验证，以继续使用</span></div>', 'security_verification'),
        ('help_dialog_is_not_challenge', 'kimi', 'https://www.kimi.com/', '<div role="dialog"><h2>帮助</h2><p>验证码用于确认身份，请阅读操作说明。</p></div>', 'ready'),
        ('visible_rate_alert', 'deepseek', 'https://chat.deepseek.com/', '<div role="alert">请求过于频繁，请稍后重试 PRIVATE_OFFLINE_ACCOUNT_AND_DRAFT_SENTINEL</div>', 'rate_limited'),
        ('rate_toast_english', 'kimi', 'https://www.kimi.com/', '<div class="toast">Too many requests. Please try again later.</div>', 'rate_limited'),
        ('rate_frequency_notice', 'qwen', 'https://www.qianwen.com/', '<div role="status">请求频率过高，请稍后再试</div>', 'rate_limited'),
        ('rate_statement_without_ui_role', 'zhihu', 'https://zhida.zhihu.com/search/123', '<p>请求过于频繁，请稍后重试</p>', 'ready'),
        ('network_alert_is_not_rate_limit', 'kimi', 'https://www.kimi.com/', '<div role="alert">网络请求失败，请检查网络连接</div>', 'ready'),
        ('hidden_rate_toast', 'kimi', 'https://www.kimi.com/', '<div class="toast" hidden>操作过于频繁</div>', 'ready'),
        ('hidden_notice_text_not_included', 'kimi', 'https://www.kimi.com/', '<div class="toast">网络状态正常<span hidden>操作过于频繁</span></div>', 'ready'),
        ('zhihu_10001_signin', 'zhihu', 'https://www.zhihu.com/signin?next=PRIVATE_OFFLINE_ACCOUNT_AND_DRAFT_SENTINEL', '<div>10001:请求参数异常，请升级客户端后重试</div>', 'zhihu_login_parameter_error'),
        ('zhihu_10001_plain_pre', 'zhihu', 'https://www.zhihu.com/signin', '<pre>10001:请求参数异常，请升级客户端后重试</pre>', 'zhihu_login_parameter_error'),
        ('zhihu_error_code_alone', 'zhihu', 'https://www.zhihu.com/signin', '<div>10001</div>', 'login_required'),
        ('zhihu_other_error', 'zhihu', 'https://www.zhihu.com/signin', '<div>10002:请求参数异常</div>', 'login_required'),
        ('custom_answer_container', 'qwen', 'https://www.qianwen.com/', '<div id="custom-answer"><h1>安全验证</h1><div role="alert">请求过于频繁</div></div>', 'ready', {'reply_selector': '#custom-answer'}),
        ('invalid_custom_selector', 'qwen', 'https://www.qianwen.com/', '<textarea>PRIVATE_OFFLINE_ACCOUNT_AND_DRAFT_SENTINEL</textarea>', 'ready', {'reply_selector': '['}),
        ('unknown_platform', 'not-a-platform', 'https://www.doubao.com/chat/', '<h1>安全验证</h1>', 'ready'),
    ]
    requests = []
    errors = []
    results = []
    markup = ['']
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(service_workers='block')
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def serve(route):
            requests.append(route.request.method)
            assert route.request.method == 'GET', 'Offline fixtures must not write'
            is_main = route.request.is_navigation_request() and route.request.frame == page.main_frame
            body = markup[0] if is_main else '<p>Offline challenge frame placeholder</p>'
            route.fulfill(content_type='text/html; charset=utf-8', body='<meta charset="utf-8">' + body)

        context.route('**/*', serve)
        for case in cases:
            name, pid, url, body, expected = case[:5]
            config = case[5] if len(case) > 5 else {}
            markup[0] = body
            page.goto(url)
            # A getter trap proves the scan does not inspect password/OTP/draft
            # values. DOM snapshots and counters check that no UI is changed.
            page.evaluate('''() => {
                window.guardValueReads=0;window.guardMutations=0;window.guardInteractions=0;
                for(const proto of [HTMLInputElement.prototype,HTMLTextAreaElement.prototype]){
                    const descriptor=Object.getOwnPropertyDescriptor(proto,'value');
                    Object.defineProperty(proto,'value',{...descriptor,get(){window.guardValueReads++;return descriptor.get.call(this);}});
                }
                new MutationObserver(records=>window.guardMutations+=records.length).observe(document.documentElement,{subtree:true,attributes:true,childList:true,characterData:true});
                for(const event of ['click','input','change','keydown','focusin'])document.addEventListener(event,()=>window.guardInteractions++,true);
            }''')
            before = page.content()
            request_count = len(requests)
            actual = page.evaluate(PAGE_GUARD_SCAN, {'pid': pid, 'config': config})
            counters = page.evaluate('({reads:window.guardValueReads,mutations:window.guardMutations,interactions:window.guardInteractions})')
            assert actual == PAGE_GUARD_RESULTS[expected], name + ': unexpected fixed result'
            assert set(actual) == {'state', 'code', 'message', 'needs_user_action'}, name
            assert sentinel not in json.dumps(actual, ensure_ascii=False), name + ': leaked private fixture data'
            assert page.content() == before, name + ': changed DOM'
            assert counters == {'reads': 0, 'mutations': 0, 'interactions': 0}, name + ': not read-only'
            assert len(requests) == request_count, name + ': made a request'
            results.append({'case': name, 'code': actual['code']})
        browser.close()
    assert not errors, errors
    print(json.dumps({'passed': len(results), 'cases': results,
                      'all_requests_intercepted': True, 'actual_platform_requests': 0,
                      'account_or_draft_values_read': 0, 'dom_mutations': 0,
                      'ui_interactions': 0, 'result_fields': sorted(PAGE_GUARD_RESULTS['ready'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
