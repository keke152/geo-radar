"""Offline editor diagnostics checks; no real browser profile or provider URL."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from controls import CONTROL_SCAN,DOUBAO_EMPTY_HOME_SCAN
from playwright.sync_api import sync_playwright

def main():
    markup=['']
    cfg={'composer':'#editor','send_button':'#send','send_key':'','new_chat_selector':'#new','reply_selector':'#answer'}
    cases=[
        ('empty_textarea','<textarea id="editor" placeholder="输入问题"></textarea>',True),
        ('real_textarea','<textarea id="editor">PRIVATE_DRAFT_SENTINEL\n原始用户内容</textarea>',False),
        ('empty_rich_br','<div id="editor" contenteditable="true"><p><br class="ProseMirror-trailingBreak"></p></div>',True),
        ('real_rich','<div id="editor" contenteditable="true"><p>PRIVATE_DRAFT_SENTINEL</p><p>第二行</p></div>',False),
        ('literal_placeholder_text','<div id="editor" data-placeholder="输入问题" contenteditable="true">输入问题</div>',False),
        ('noneditable_mention','<div id="editor" contenteditable="true"><span contenteditable="false" data-mention="true">@PRIVATE_DRAFT_SENTINEL</span></div>',False),
        ('slate_hint','<div id="editor" contenteditable="true" data-slate-editor="true"><span data-slate-placeholder="true" contenteditable="false">请输入你的问题</span><span>\u200b</span><p><br></p></div>',True),
        ('lexical_hint','<div id="editor" contenteditable="true"><span data-lexical-placeholder="true">向千问提问</span><p>\ufeff</p></div>',True),
        ('hint_plus_typed','<div id="editor" contenteditable="true"><span data-slate-placeholder="true">请输入你的问题</span><p>PRIVATE_DRAFT_SENTINEL</p></div>',False),
        ('hidden_hint','<div id="editor" contenteditable="true"><span class="placeholder" aria-hidden="true">灰色提示</span><br></div>',True),
        ('attachment_only','<div id="editor" contenteditable="true"><span data-attachment="true" contenteditable="false" style="display:inline-block;width:30px;height:30px"></span></div>',False),
        ('typed_same_as_hint','<div id="editor" contenteditable="true" data-placeholder="向千问提问"><span data-slate-placeholder="true">向千问提问</span><p>向千问提问</p></div>',False),
    ]
    results=[];requests=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        def serve(route):
            req=route.request;requests.append({'method':req.method,'url':req.url})
            assert req.method=='GET' and req.url.startswith('http://fixture.invalid/')
            route.fulfill(content_type='text/html; charset=utf-8',body='<meta charset="utf-8"><style>#editor{min-height:40px;min-width:300px}</style>'+markup[0]+'<button id="new">新对话</button><button id="send">发送</button><div id="answer"></div>')
        page.route('**/*',serve)
        for name,body,empty in cases:
            markup[0]=body;page.goto('http://fixture.invalid/')
            before=page.locator('#editor').evaluate('(e)=>({html:e.outerHTML,value:e.value??null})')
            normal=page.evaluate(CONTROL_SCAN,{'config':cfg})
            detailed=page.evaluate(CONTROL_SCAN,{'config':cfg,'include_candidates':True})
            after=page.locator('#editor').evaluate('(e)=>({html:e.outerHTML,value:e.value??null})')
            assert before==after,name+' mutated draft'
            assert normal['composer_empty'] is empty,name
            assert 'composer_diagnostics' not in normal
            assert 'PRIVATE_DRAFT_SENTINEL' not in json.dumps(detailed),name+' leaked draft text'
            assert detailed['composer_diagnostics']['tag'] in ('textarea','div')
            results.append({'case':name,'empty':normal['composer_empty'],'draft_unchanged':True,'text_not_exposed':True})
        welcome=[]
        for name,body,expected in [
            ('known_empty_welcome','<h1>有什么我能帮你的吗？</h1><div data-testid="chat_input"><textarea></textarea></div>',True),
            ('no_welcome','<div data-testid="chat_input"><textarea></textarea></div>',False),
            ('existing_messages','<h1>有什么我能帮你的吗？</h1><div data-testid="chat_input"><textarea></textarea></div><div data-message-role="user">旧问题</div>',False),
            ('unrecognized_editor','<h1>有什么我能帮你的吗？</h1><textarea></textarea>',False),
        ]:
            markup[0]=body;page.goto('http://fixture.invalid/');actual=page.evaluate(DOUBAO_EMPTY_HOME_SCAN)
            assert actual is expected,name;welcome.append({'case':name,'fresh_welcome':actual})
        assert not errors,errors
        browser.close()
    report={'cases':results,'welcome_cases':welcome,'page_errors':errors,'requests_local_read_only':all(r['method']=='GET' and r['url'].startswith('http://fixture.invalid/') for r in requests),'actual_provider_requests':0}
    if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
