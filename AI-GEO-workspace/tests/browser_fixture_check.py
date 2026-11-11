"""A real Edge end-to-end test against an isolated local fixture, not live platforms."""
import asyncio,json,os,tempfile,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

scratch=tempfile.TemporaryDirectory(prefix='junhe-browser-fixture-')
os.environ['JUNHE_HOME']=scratch.name;os.environ['JUNHE_BROWSER_HEADLESS']='1'
from browser_bridge import BrowserBridge,PROMPT_REPLY
from config import PLATFORMS,default_platform

HTML='''<!doctype html><meta charset="utf-8"><button id="new" onclick="document.querySelector('#answer').textContent=''">新对话</button><div id="wrong" style="height:1200px">非输入区域</div><textarea id="composer"></textarea><button id="send" aria-label="发送" onclick="window.sends=(window.sends||0)+1;document.querySelector('#answer').textContent='这是本地测试回答，不是真实平台。'">发送</button><div id="answer"></div>'''
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(HTML.encode())
 def log_message(self,*args):pass

async def main():
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 original=PLATFORMS['deepseek']['url'];PLATFORMS['deepseek']['url']='http://127.0.0.1:'+str(server.server_port)+'/'
 bridge=BrowserBridge()
 try:
  page=await bridge.connect('deepseek')
  assert page.viewport_size is None,'Native window must not have a fixed emulated viewport'
  config={**default_platform('deepseek'),'composer':'#composer','send_button':'#send','reply_selector':'#answer','new_chat_selector':'#new','ready':True}
  before=await bridge.inspect('deepseek',config)
  assert before['composer_found'] and not before['composer_in_view']
  after=await bridge.reveal('deepseek',config)
  assert after['composer_in_view'] and after['composer_editable']
  assert await page.locator('#composer').input_value()==''
  assert await page.evaluate('window.sends||0')==0,'Reveal must not type or send'
  await bridge.pick('deepseek','composer');await page.locator('#wrong').click(position={'x':10,'y':10})
  rejected=await bridge.picked('deepseek')
  assert rejected['invalid'] and 'selector' not in rejected
  await page.locator('#composer').click()
  valid=await bridge.picked('deepseek')
  assert valid['kind']=='composer' and valid['selector']=='#composer'
  await bridge.pick('deepseek','composer');await bridge.cancel_pick('deepseek')
  assert await page.locator('#junhe-picker-notice').count()==0
  assert await bridge.picked('deepseek') is None
  await bridge.pick('deepseek','send_button');await page.locator('#send').click()
  picked=await bridge.picked('deepseek')
  assert picked['kind']=='send_button'
  assert await page.evaluate('window.sends||0')==0,'Calibration must not send'
  markers=[]
  result=await bridge.send('deepseek',config,'测试关键词','visibility',lambda:markers.append('sent'))
  assert markers==['sent']
  assert '本地测试回答' in result['answer']
  assert result['screenshot']
  assert await page.evaluate('window.sends')==1
  assert await page.locator('#composer').input_value()=='测试关键词'
  await page.evaluate('''()=>{const list=document.createElement('div');list.dataset.testid='message-list';for(const [role,text] of [['user','测试问题'],['assistant','对应的原始回答'],['user','后续品牌问题'],['assistant','后续回答不可串入']]){const row=document.createElement('div');row.dataset.messageRole=role;const body=document.createElement('div');body.dataset.testid='message_text_content';body.textContent=text;row.append(body);list.append(row);}document.body.append(list);}''')
  bound=await page.evaluate(PROMPT_REPLY,'测试问题')
  assert bound['answer']=='对应的原始回答' and bound['later_turns']
  missing=await page.evaluate(PROMPT_REPLY,'不存在的问题')
  assert not missing['matched'] and not missing['answer']
  wrong=await bridge.inspect('deepseek',{**config,'send_button':'#composer'})
  assert wrong['open'] and wrong['composer_editable'] and not wrong['send_found']
  assert wrong['controls']['send_button']['state']=='wrong_target'
  await page.evaluate('''()=>{const button=document.createElement('button');button.dataset.testid='fixture-send';button.disabled=true;button.innerHTML='<svg id="send-svg" width="20" height="20"><path d="M0 0 L20 20"/></svg>';document.body.append(button);document.querySelector('#composer').value='';}''')
  normalized=await bridge.inspect('deepseek',{**config,'send_button':'#send-svg'},include_candidates=True)
  assert normalized['send_found'] and not normalized['send_enabled']
  assert normalized['send_state']=='awaiting_text'
  assert normalized['controls']['send_button']['normalized']
  assert normalized['suggestions']['send_button']=='button[data-testid="fixture-send"]'
  shortcut=await bridge.inspect('deepseek',{**config,'send_button':'','send_key':'Enter'})
  assert shortcut['send_state']=='shortcut' and not shortcut['send_found']
  # The picker must reject the editor as a send target without submitting.
  await bridge.pick('deepseek','send_button');await page.locator('#composer').click()
  rejected_send=await bridge.picked('deepseek')
  assert rejected_send['invalid'] and 'selector' not in rejected_send
  await bridge.cancel_pick('deepseek')
  assert await page.evaluate('window.sends')==1
  assert await page.locator('#composer').input_value()==''
  print(json.dumps({'fixture':'local-only','native_viewport':True,'offscreen_input_revealed':True,'invalid_pick_rejected':True,'cancel_restores_page':True,'calibration_did_not_send':True,'send_count':1,'response_captured':True,'screenshot_created':True,'reply_bound_to_original_prompt':True,'editor_not_send_button':True,'svg_normalized_to_button':True,'empty_input_disabled_state':True,'diagnostics_do_not_type_or_send':True},ensure_ascii=False))
 finally:
  await bridge.close();PLATFORMS['deepseek']['url']=original;server.shutdown()

if __name__=='__main__':asyncio.run(main())
