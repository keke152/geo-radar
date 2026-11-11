"""Offline DOM regression. Run with Python after installing requirements and Edge.

All requests are intercepted; no account session or real platform is used.
"""
from pathlib import Path
import json,sys
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from responses import RESPONSE_SCAN,patterns,automatic_verification

def main():
 prompt='请搜索公开网页并回答以下问题。问题：示例公司'
 history=f'<div data-testid="Button:find_page_history_record_word_btn"><div class="css-146c3p1 r-dnmrzs">{prompt}</div></div>'
 question=f'<div class="css-146c3p1">{prompt}</div>'
 answer='<div class="Render-markdown"><p>唯一最终回答</p></div>'
 done='<div data-testid="Button:zhida_message_copy_btn">复制</div>'
 with sync_playwright() as playwright:
  browser=playwright.chromium.launch(channel='msedge',headless=True)
  page=browser.new_page();markup=['']
  page.route('**/*',lambda route:route.fulfill(content_type='text/html; charset=utf-8',body='<meta charset="utf-8"><style>div{min-height:3px}</style>'+markup[0]))
  def scan(body,path='/search/123'):
   markup[0]=body;page.goto('http://fixture.invalid'+path)
   return page.evaluate(RESPONSE_SCAN,{'prompt':prompt,'pattern':patterns('zhihu')})
  r=scan(history+question+answer+done);assert r['matched'] and r['done'] and r['answer']=='唯一最终回答'
  assert not scan(history+'<div class="css-146c3p1">其他问题</div>'+answer+done)['matched']
  assert not scan(question+answer+done,'/other/123')['matched']
  assert not scan(question+answer+answer+done)['matched']
  r=scan(question+answer);assert r['matched'] and not r['done']
  assert scan(question+answer+done+'<div data-testid="Button:stop_btn">停止生成</div>')['busy']
  assert scan(history+question+'<div data-testid="Block:thinking_blcok">中间过程</div>'+answer+done)['answer']=='唯一最终回答'
  query='/search?q='+quote(prompt,safe='')
  r=scan(history+question+'<div data-testid="Block:thinking_blcok">完成回答，用时6秒</div>'+answer+done,query)
  assert r['matched'] and r['done'] and r['answer']=='唯一最终回答'
  assert automatic_verification({**r,'stable':True})[0]
  # URL evidence supplements, but never replaces, a unique visible original
  # question and a unique final answer. History, partial questions and duplicate
  # query values do not establish the association.
  assert not scan(question+answer+done,'/search?q='+quote('其他问题',safe=''))['matched']
  assert not scan(question+answer+done,'/search')['matched']
  assert not scan(question+answer+done,'/search?q=')['matched']
  assert not scan(question+answer+done,query+'&q='+quote(prompt,safe=''))['matched']
  assert not scan(question+answer+done,'/other?q='+quote(prompt,safe=''))['matched']
  assert not scan(history+answer+done,query)['matched']
  assert not scan('<div class="css-146c3p1">示例公司</div>'+answer+done,query)['matched']
  assert not scan(question+question+answer+done,query)['matched']
  assert not scan(question+answer+answer+done,query)['matched']
  r=scan(question+answer,query);assert r['matched'] and not r['done']
  assert not automatic_verification({**r,'stable':True})[0]
  r=scan(question+answer+done+'<div data-testid="Button:stop_btn">停止生成</div>',query)
  assert r['matched'] and r['busy'] and not automatic_verification({**r,'stable':True})[0]
  r=scan(question+answer+done,query)
  assert not automatic_verification({**r,'stable':False})[0]
  diagnostic=page.evaluate(RESPONSE_SCAN,{'prompt':prompt,'pattern':patterns('zhihu'),'diagnostic':True})
  assert diagnostic['single_page_bound'] and diagnostic['single_page_context']=='exact_prompt_query'
  browser.close()
 print(json.dumps({'passed':21,'network':'intercepted offline fixtures','platform_messages_sent':0,'query_url_requires_exact_full_prompt':True,'busy_unstable_incomplete_rejected':True}))

if __name__=='__main__':main()
