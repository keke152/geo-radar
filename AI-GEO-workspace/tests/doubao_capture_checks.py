"""Offline virtual-list recovery, full-prompt binding, scroll/draft preservation."""
import asyncio,json,os,sys,tempfile
from pathlib import Path

scratch=tempfile.TemporaryDirectory(prefix='geo-doubao-capture-')
os.environ['JUNHE_HOME']=scratch.name
os.environ['PYTHON_DOTENV_DISABLED']='1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.async_api import async_playwright
from browser_bridge import BrowserBridge
from responses import RESPONSE_SCAN,patterns

PROMPT='完整的原问题\n请列出真实来源。'
HTML='''<!doctype html><meta charset="utf-8"><style>#side{height:70px;overflow:auto}#viewport{height:130px;overflow:auto}#slot{height:140px}.answer{min-height:100px}textarea{height:35px}</style>
<div id="side"><div style="height:600px">unrelated sidebar</div></div>
<div data-testid="message-list"><div id="viewport"><div id="slot"></div><div style="height:550px"></div><div data-message-role="assistant" class="answer"><div data-testid="message_text_content">唯一的完整原回答。<a href="https://example.invalid/source">来源</a></div><button data-testid="message_action_copy">复制</button></div></div></div>
<textarea>PRIVATE_DRAFT_SENTINEL</textarea><script>
const prompt=__PROMPT__,viewport=document.querySelector('#viewport'),slot=document.querySelector('#slot');
function mount(){slot.innerHTML='';if(viewport.scrollTop<40){const user=document.createElement('div');user.dataset.messageRole='user';const body=document.createElement('div');body.textContent=prompt;user.append(body);slot.append(user);}}
viewport.addEventListener('scroll',mount);viewport.scrollTop=viewport.scrollHeight;mount();document.querySelector('#side').scrollTop=100;
</script>'''.replace('__PROMPT__',json.dumps(PROMPT,ensure_ascii=False))

async def main():
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True)
  page=await browser.new_page(viewport={'width':1000,'height':700})
  await page.route('**/*',lambda route:route.fulfill(content_type='text/html; charset=utf-8',body=HTML))
  await page.goto('https://www.doubao.com/chat/12345')
  bridge=BrowserBridge();bridge.pages['doubao']=page
  arguments={'prompt':PROMPT,'pattern':patterns('doubao')}
  first=await page.evaluate(RESPONSE_SCAN,arguments)
  assert first['user_count']==0 and first['assistant_count']==1 and not first['matched']
  before=await page.evaluate('()=>({top:viewport.scrollTop,side:document.querySelector("#side").scrollTop,draft:document.querySelector("textarea").value})')
  result=await bridge.response_snapshot('doubao',{},PROMPT)
  assert result['matched'] and result['viewport_recovered'] and result['done']
  assert '唯一的完整原回答' in result['answer'] and len(result['links'])==1
  after=await page.evaluate('()=>({top:viewport.scrollTop,side:document.querySelector("#side").scrollTop,draft:document.querySelector("textarea").value})')
  assert before==after,'Recovery changed scroll position or draft'
  wrong=await bridge.response_snapshot('doubao',{},'另一个问题')
  assert not wrong['matched'] and not wrong['answer'],'Unrelated answer was accepted'
  keyword=await bridge.response_snapshot('doubao',{},'完整的原问题')
  assert not keyword['matched'],'Partial prompt was accepted'
  await page.evaluate('()=>{viewport.scrollTop=0;mount()}')
  captured=await bridge.capture_existing('doubao',{},PROMPT)
  assert captured['answer']==result['answer'],'Legacy/manual capture does not share the same extractor'
  assert await page.locator('textarea').input_value()=='PRIVATE_DRAFT_SENTINEL'
  await browser.close()
 print(json.dumps({'passed':6,'virtualized_question_recovered':True,'full_prompt_required':True,'scroll_and_draft_preserved':True,'manual_and_verified_share_extractor':True,'platform_messages_sent':0,'network':'all intercepted offline fixtures'}))

if __name__=='__main__':asyncio.run(main())
