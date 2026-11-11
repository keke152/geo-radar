"""Dedicated, visible Edge profiles. Human login and selector calibration are required."""
import asyncio,os,time
from pathlib import Path
from urllib.parse import urlsplit
from config import HOME,PLATFORMS
from controls import CONTROL_SCAN,DOUBAO_EMPTY_HOME_SCAN
from responses import RESPONSE_SCAN,patterns
from capture_viewport import REPLY_VIEWPORT
from page_guard import PAGE_GUARD_SCAN,PAGE_GUARD_RESULTS

class NeedsSetup(Exception):pass


def preparation_failure(step,error):
 """Preparation is before the send boundary, so its failure is safe to resume."""
 timed_out=type(error).__name__=='TimeoutError'
 reason='操作超时' if timed_out else '操作未完成'
 failure=NeedsSetup(f'{step}{reason}。本次尚未触发发送，请检查该平台页面或重新识别控件后继续原任务。')
 failure.phase=step
 failure.send_attempted=False
 return failure

def browser_launch_failure(error):
 text=str(error).lower()
 if any(marker in text for marker in ('processsingleton','user data directory is already in use','exitcode=21','exitcode= 21')):
  return 'profile_busy','豆包等平台的这份专用浏览器资料正由另一个进程使用，工作台尚未接管。请关闭该平台的旧专用Edge窗口，再点打开登录；无需重装Edge。'
 if any(marker in text for marker in ('executable doesn\'t exist','executable does not exist','distribution \'msedge\' is not found')):
  return 'edge_missing','未找到Microsoft Edge程序，请安装Edge后重新打开。'
 return 'launch_failed','未能连接到工作台管理的专用Edge会话。若平台窗口已经开着，请关闭旧的该平台专用窗口后重试；这不代表没有安装Edge。'

# Read the assistant immediately following the exact submitted prompt, never
# the final answer in a conversation which the user may have continued.
PROMPT_REPLY=r'''prompt=>{
 const normalize=s=>(s||'').replace(/\s+/g,'').trim();
 const list=document.querySelector('[data-testid="message-list"]');
 if(!list)return {matched:false,answer:'',links:[]};
 const messages=[...list.querySelectorAll('[data-message-role="user"],[data-message-role="assistant"]')];
 for(let i=0;i<messages.length;i++){
  const user=messages[i];
  if(user.getAttribute('data-message-role')!=='user')continue;
  const body=user.querySelector('[data-testid="message_text_content"]');
  if(!body||normalize(body.innerText)!==normalize(prompt))continue;
  const next=messages[i+1];
  if(!next||next.getAttribute('data-message-role')!=='assistant')return {matched:true,answer:'',links:[]};
  const answer=next.querySelector('[data-testid="message_text_content"]');
  return {matched:true,answer:answer?.innerText||'',links:[...next.querySelectorAll('a[href]')].map(a=>a.href).filter(u=>/^https?:\/\//.test(u)),later_turns:messages.length>i+2};
 }
 return {matched:false,answer:'',links:[]};
}'''

PICKER=r'''(kind)=>{
 if(window.__junhePickerCleanup)window.__junhePickerCleanup();
 window.__junhePick=null;
 const note=document.createElement('div');note.id='junhe-picker-notice';
 const titles={composer:'输入框',send_button:'发送按钮',new_chat_selector:'新对话按钮',reply_selector:'回答区域'};
 note.textContent='正在标定'+titles[kind]+'：请点击对应控件，只记录位置，不发送。按ESC取消后可正常操作网页。';
 Object.assign(note.style,{position:'fixed',top:'12px',left:'50%',transform:'translateX(-50%)',maxWidth:'calc(100vw - 32px)',boxSizing:'border-box',zIndex:2147483647,padding:'12px 18px',borderRadius:'10px',background:'#123d32',color:'white',font:'14px/1.6 sans-serif',boxShadow:'0 8px 30px #0003',pointerEvents:'none'});
 document.documentElement.appendChild(note);
 let hovered;
 const over=e=>{if(hovered)hovered.style.outline=hovered.__junheOutline||'';hovered=e.target;hovered.__junheOutline=hovered.style.outline;hovered.style.outline='2px solid #e39832';};
 const cleanup=()=>{document.removeEventListener('click',click,true);document.removeEventListener('mouseover',over,true);document.removeEventListener('keydown',key,true);if(hovered)hovered.style.outline=hovered.__junheOutline||'';note.remove();window.__junhePickerCleanup=null;};
 const key=e=>{if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();window.__junhePick={cancelled:true};cleanup();}};
 const freshLabel=e=>/^(?:新对话|开启新对话|newchat)(?:ctrl\+?j)?$/i.test((e.innerText||'').replace(/[\s\u200B\uFEFF]/g,''));
 const freshTarget=e=>{
  let target=null;
  for(let node=e,depth=0;node&&node!==document.body&&depth<7;node=node.parentElement,depth++){
   if(node.matches('textarea,input,[contenteditable=true]')||node.isContentEditable||node.closest('[contenteditable=true]'))break;
   if(node.matches('button,[role=button],a[href],input[type=submit],input[type=button]'))return null;
   const rect=node.getBoundingClientRect(),style=getComputedStyle(node);
   if(node.tagName==='DIV'&&rect.width&&rect.height&&style.visibility!=='hidden'&&freshLabel(node)&&style.cursor==='pointer'&&rect.width>=72&&rect.width<=480&&rect.height>=28&&rect.height<=96&&!node.querySelector('textarea,input,[contenteditable=true]'))target=node;
  }
  return target;
 };
 const click=e=>{
  e.preventDefault();e.stopImmediatePropagation();
  let el=e.target;
  if(kind==='send_button'||kind==='new_chat_selector'){
   let target=kind==='new_chat_selector'?freshTarget(el):null;
   for(let node=el,depth=0;!target&&node&&node!==document.body&&depth<7;node=node.parentElement,depth++){
    if(node.matches('textarea,input,[contenteditable=true]'))break;
    if(node.matches('button,[role=button],a[href]')){target=node;break;}
    if(!node.matches('svg,path,use')&&/send|submit|button|btn|enter[-_](button|icon)/i.test(typeof node.className==='string'?node.className:'')&&getComputedStyle(node).cursor==='pointer'){target=node;break;}
   }
   if(!target){const error=kind==='new_chat_selector'?'这个位置不是可识别的新对话入口。请点击“开启新对话”等完整按钮区域，或按ESC取消后重新选择。':'这个位置不是可点击按钮。请点发送图标外层的按钮，或取消后在工作台明确选择发送快捷键。';window.__junhePick={kind,invalid:true,error};note.textContent=error;return;}
   el=target;
  }
  if(kind==='composer'){
   el=el.closest('textarea,input:not([type]),input[type=text],input[type=search],[contenteditable=true],[role=textbox]');
   if(!el||el.disabled||el.readOnly||(!(el instanceof HTMLTextAreaElement)&&!(el instanceof HTMLInputElement)&&!el.isContentEditable)){
    const error='这里不是可编辑输入框，请点击能输入文字的区域。看不到时按ESC取消，再使用工作台的“定位输入框”。';
    window.__junhePick={kind,invalid:true,error};note.textContent=error;return;
   }
  }
  const tag=el.tagName.toLowerCase();let selector='';
  for(const attr of ['data-testid','aria-label','placeholder','title']){const value=el.getAttribute(attr);if(value&&value.length<100){const trial=tag+'['+attr+'="'+CSS.escape(value)+'"]';if(document.querySelectorAll(trial).length===1){selector=trial;break;}}}
  if(!selector&&el.id&&document.querySelectorAll('#'+CSS.escape(el.id)).length===1)selector='#'+CSS.escape(el.id);
  if(!selector){let node=el,parts=[];while(node&&node!==document.body){let n=1;for(let s=node.previousElementSibling;s;s=s.previousElementSibling)if(s.tagName===node.tagName)n++;parts.unshift(node.tagName.toLowerCase()+':nth-of-type('+n+')');node=node.parentElement;}selector='body > '+parts.join(' > ');}
  window.__junhePick={kind,selector};cleanup();
 };
 window.__junhePickerCleanup=cleanup;document.addEventListener('click',click,true);document.addEventListener('mouseover',over,true);document.addEventListener('keydown',key,true);
}'''

class BrowserBridge:
 def __init__(self):
  self.playwright=None;self.contexts={};self.pages={};self.lock=asyncio.Lock();self.platform_locks={}
  self.connection_locks={};self.startup_lock=asyncio.Lock();self.navigation_errors={};self.connection_errors={}
  self.window_recovery={};self.page_guards={};self.navigation_retries={}
 def login_page(self,pid,url):
  target=urlsplit(url)
  return pid=='zhihu' and target.scheme=='https' and target.hostname in ('www.zhihu.com','zhihu.com') and target.path.rstrip('/') in ('/signin','/login')
 async def page_guard(self,pid,page,config=None):
  result=await page.evaluate(PAGE_GUARD_SCAN,{'pid':pid,'config':config or {}})
  if not isinstance(result,dict) or result.get('code') not in PAGE_GUARD_RESULTS:result=dict(PAGE_GUARD_RESULTS['ready'])
  self.page_guards[pid]=result
  return result
 def profile_saved(self,pid):
  return (HOME/'browser-profiles'/pid/'Default').is_dir()
 def current_page(self,pid):
  page=self.pages.get(pid)
  if page is not None and not page.is_closed():return page
  context=self.contexts.get(pid)
  for candidate in reversed(getattr(context,'pages',[]) if context else []):
   if candidate.is_closed():continue
   try:self.valid_page(pid,candidate)
   except NeedsSetup:
    if not self.login_page(pid,candidate.url):continue
   self.pages[pid]=candidate;return candidate
  return None
 def connection_state(self,pid):
  page=self.current_page(pid);opened=page is not None
  return {'open':opened,'url':page.url if opened else '',
          'navigation_error':self.navigation_errors.get(pid,'') if opened else '',
          'connection_error':self.connection_errors.get(pid,{}).get('message','') if not opened else '',
          'reason':self.connection_errors.get(pid,{}).get('code','not_connected') if not opened else 'connected',
          'profile_saved':self.profile_saved(pid),
          'window_recovery':self.window_recovery.get(pid,{}),'page_guard':self.page_guards.get(pid,{}),
          'navigation_retry_seconds':max(0,int(self.navigation_retries.get(pid,{}).get('next',0)-time.monotonic()+.999)),
          'login_verified':False,'note':'已保存登录资料可尝试恢复；窗口连接和账号登录分别检查'}
 async def _ensure_interactable_window(self,pid,page=None):
  """Restore only a minimized owned Chromium window; preserve other bounds.

  bring_to_front alone can leave an Edge native window minimized. Its page is
  connected but animation-frame/actionability checks can then stall. The CDP
  call changes no account settings, contents, ordinary size or maximized state.
  """
  page=page or self.current_page(pid)
  context=self.contexts.get(pid) or getattr(page,'context',None)
  if page is None or not context or not callable(getattr(context,'new_cdp_session',None)):
   return {'checked':False,'restored':False,'state':'unsupported'}
  session=None;state='unknown'
  try:
   session=await asyncio.wait_for(context.new_cdp_session(page),timeout=3)
   info=await asyncio.wait_for(session.send('Browser.getWindowForTarget'),timeout=3)
   state=info.get('bounds',{}).get('windowState','unknown')
   if state=='minimized':
    await asyncio.wait_for(session.send('Browser.setWindowBounds',{'windowId':info['windowId'],'bounds':{'windowState':'normal'}}),timeout=3)
    result={'checked':True,'restored':True,'state':'normal','previous_state':'minimized'}
   else:result={'checked':True,'restored':False,'state':state}
   self.window_recovery[pid]=result
   return result
  except Exception as exc:
   result={'checked':False,'restored':False,'state':state}
   self.window_recovery[pid]=result
   if state=='minimized':raise NeedsSetup('该平台专用Edge已最小化，自动恢复窗口未完成。请在任务栏还原该窗口，再继续原任务；本次尚未触发发送。') from exc
   # CDP window controls may be unsupported by a non-Chromium fixture or host.
   # Preserve existing behavior; normal page diagnostics remain available.
   return result
  finally:
   if session:
    try:await asyncio.wait_for(session.detach(),timeout=2)
    except Exception:pass
 async def connect(self,pid):
  async with self.connection_locks.setdefault(pid,asyncio.Lock()):
   return await self._connect(pid)
 async def _connect(self,pid):
  from playwright.async_api import async_playwright
  async with self.startup_lock:
   if self.playwright is None:self.playwright=await async_playwright().start()
  context=self.contexts.get(pid)
  if context and not context.pages:
   try:await context.close()
   except Exception:pass
   self.contexts.pop(pid,None);context=None
  if context is None:
   try:
    # Use the actual native client size: a fixed emulated height can place a
    # bottom-fixed composer below the physical Edge window on smaller screens.
    context=await self.playwright.chromium.launch_persistent_context(str(HOME/'browser-profiles'/pid),channel='msedge',headless=os.getenv('JUNHE_BROWSER_HEADLESS')=='1',no_viewport=True,args=['--start-maximized'],accept_downloads=False)
   except Exception as exc:
    code,message=browser_launch_failure(exc);self.connection_errors[pid]={'code':code,'message':message}
    raise NeedsSetup(message) from exc
   self.contexts[pid]=context
  self.connection_errors.pop(pid,None)
  page=self.current_page(pid);navigate=False
  if page is None or page.is_closed():
   page=context.pages[0] if context.pages else await context.new_page();self.pages[pid]=page
   navigate=True
  if page.url in ('about:blank','') or self.navigation_errors.get(pid):navigate=True
  if self.login_page(pid,page.url):navigate=False
  if navigate and time.monotonic()<self.navigation_retries.get(pid,{}).get('next',0):navigate=False
  if navigate:
   try:
    await page.goto(PLATFORMS[pid]['url'],wait_until='domcontentloaded',timeout=25000)
    self.navigation_errors.pop(pid,None)
    self.navigation_retries.pop(pid,None)
   except Exception:
    if page.is_closed():raise NeedsSetup('专用Edge窗口已关闭，请重新点击打开登录')
    self.navigation_errors[pid]='网页加载未确认，请在专用Edge中检查网络/刷新；没有登录或发送任何内容'
    failures=self.navigation_retries.get(pid,{}).get('failures',0)+1
    self.navigation_retries[pid]={'failures':failures,'next':time.monotonic()+min(30*2**min(failures-1,4),300)}
  await self._ensure_interactable_window(pid,page)
  await page.bring_to_front()
  return page
 async def restore_session(self,pid,config):
  if not config['ready'] or not self.profile_saved(pid):raise NeedsSetup('请先在平台连接中本人登录并保存标定配置')
  try:
   await self.connect(pid)
   for attempt in range(5):
    result=await self.inspect(pid,config)
    if result.get('needs_user_action'):raise NeedsSetup(result['message'])
    if result.get('composer_editable'):break
    if attempt<4:await asyncio.sleep(.5)
  except NeedsSetup:raise
  except Exception as exc:raise preparation_failure('恢复浏览器与检查输入框',exc) from exc
  if not result.get('composer_editable'):raise NeedsSetup('已恢复专用窗口和本机资料，但输入框尚不可用。请本人确认登录是否过期，或重新识别输入框；问题未发送。')
  # Several consumer pages only mount the send button after the editor has text.
  # Its absence in that explicit empty-editor state is checked again after fill,
  # never treated as proof of logout or permission to send without a control.
  send_state=result.get('controls',{}).get('send_button',{}).get('state')
  awaiting_text=result.get('composer_empty') and send_state=='missing_when_empty'
  if config['send_button'] and not result.get('send_found') and not awaiting_text:raise NeedsSetup('已恢复窗口，发送控件需要重新检查；请到连接向导自动识别控件。问题未发送。')
  if config['new_chat_selector'] and not result.get('new_chat_found'):raise NeedsSetup('已恢复窗口，新对话入口需要重新识别；问题未发送。')
  return result
 def valid_page(self,pid,page):
  host=(urlsplit(page.url).hostname or '').lower()
  allowed=(urlsplit(PLATFORMS[pid]['url']).hostname or '').lower()
  root=allowed.removeprefix('www.')
  if host.removeprefix('www.')!=root and not host.endswith('.'+root):raise NeedsSetup('当前页面仍在登录或跳转，请完成登录并回到平台问答页')
 async def first_visible(self,page,selector):
  try:
   candidates=page.locator(selector)
   for i in range(min(await candidates.count(),20)):
    item=candidates.nth(i)
    if await item.is_visible():return item
  except Exception:pass
  return None
 async def inspect(self,pid,config,include_candidates=False):
  page=self.current_page(pid)
  if page is None or page.is_closed():return {**self.connection_state(pid),'composer_found':False,'composer_editable':False,'composer_in_view':False,'send_found':False,'new_chat_found':False,'reply_found':False}
  guard=await self.page_guard(pid,page,config)
  if guard['needs_user_action']:
   return {**self.connection_state(pid),**guard,'composer_found':False,'composer_editable':False,'composer_in_view':False,'send_found':False,'new_chat_found':False,'reply_found':False,'suggestions':{},'controls':{key:{'state':'blocked','found':False,'enabled':False,'message':guard['message']} for key in ('composer','send_button','new_chat_selector','reply_selector')}}
  self.valid_page(pid,page)
  result=await page.evaluate(CONTROL_SCAN,{'config':config,'include_candidates':include_candidates})
  if result['composer_found']:self.navigation_errors.pop(pid,None);self.navigation_retries.pop(pid,None)
  return {**self.connection_state(pid),**guard,**result}
 async def cancel_pick(self,pid):
  page=self.current_page(pid)
  if page and not page.is_closed():
   await page.evaluate('()=>{if(window.__junhePickerCleanup)window.__junhePickerCleanup();window.__junhePick=null;}')
 async def reveal(self,pid,config):
  page=self.current_page(pid)
  if page is None or page.is_closed():raise NeedsSetup('请先打开专用Edge窗口')
  self.valid_page(pid,page);await self._ensure_interactable_window(pid,page);await self.cancel_pick(pid)
  composer=await self.first_visible(page,config['composer'])
  if not composer:raise NeedsSetup('当前问答页未找到输入框。请本人确认已登录、已进入新对话；若布局变更，请重新点选输入框。')
  await composer.scroll_into_view_if_needed(timeout=5000);await page.bring_to_front()
  return await self.inspect(pid,config)
 async def pick(self,pid,kind):
  page=await self.connect(pid);self.valid_page(pid,page)
  if kind=='composer':
   composer=await self.first_visible(page,'textarea, [contenteditable="true"]')
   if composer:await composer.scroll_into_view_if_needed(timeout=5000)
  await page.evaluate(PICKER,kind)
 async def picked(self,pid):
  page=self.current_page(pid)
  if page is None or page.is_closed():return None
  result=await page.evaluate('window.__junhePick || null')
  if result:await page.evaluate('window.__junhePick=null')
  return result
 async def capture_existing(self,pid,config,prompt,conversation_url=''):
  if pid!='doubao':raise NeedsSetup('当前按问题恢复回答仅支持已校准的豆包网页')
  async with self.platform_locks.setdefault(pid,asyncio.Lock()):
   page=self.current_page(pid)
   if page is None or page.is_closed():raise NeedsSetup('请先连接工作台管理的豆包专用窗口')
   self.valid_page(pid,page)
   if conversation_url:
    target=urlsplit(conversation_url);allowed=urlsplit(PLATFORMS[pid]['url'])
    import re
    if target.scheme!='https' or target.hostname!=allowed.hostname or not re.fullmatch(r'/chat/\d+',target.path) or target.query or target.fragment:raise NeedsSetup('会话链接必须是当前豆包站点的具体对话地址')
    if page.url!=conversation_url:await page.goto(conversation_url,wait_until='domcontentloaded',timeout=25000)
   await page.wait_for_selector('[data-testid="message-list"]',state='attached',timeout=20000)
   answer='';last='';stable=0;sample={}
   for _ in range(30):
    sample=await self.response_snapshot(pid,config,prompt)
    current=sample.get('answer','')
    if current:
     stable=stable+1 if current==last else 0;last=current;answer=current
     if stable>=3:break
    await asyncio.sleep(1)
   if not answer.strip():raise NeedsSetup('没有找到这条测试问题对应的回答，未改用后续提问的回答，也没有重发。请在该会话回到原问题后重试获取。')
   return {'answer':answer[:100000],'conversation_url':page.url,'links':list(dict.fromkeys(sample.get('links',[]))),
           'later_turns':sample.get('later_turns',False),'note':'按原始测试问题匹配到其后一条AI回答；没有重新发送问题。'}
 async def response_snapshot(self,pid,config,prompt,baseline=None,diagnostic=False):
  page=self.current_page(pid)
  if page is None:raise NeedsSetup('专用窗口未连接')
  arguments={'prompt':prompt,'pattern':patterns(pid),'reply_selector':config.get('reply_selector',''),'baseline':baseline,'diagnostic':diagnostic}
  result=await page.evaluate(RESPONSE_SCAN,arguments)
  if diagnostic or pid!='doubao' or result.get('matched') or result.get('user_count') or not result.get('assistant_count'):return result
  # A long answer can virtualize the preceding question. Recover only the
  # conversation viewport and still require the full original prompt plus its
  # adjacent answer; a lone visible assistant is never accepted as evidence.
  original_url=page.url
  viewport=await page.evaluate(REPLY_VIEWPORT,{'action':'top'})
  if not viewport.get('moved'):return result
  try:
   for _ in range(4):
    await asyncio.sleep(.2)
    if page.url!=original_url:return result
    recovered=await page.evaluate(RESPONSE_SCAN,arguments)
    if recovered.get('matched'):
     return {**recovered,'viewport_recovered':True}
    result=recovered
   return result
  finally:
   if not page.is_closed() and page.url==original_url:
    try:await page.evaluate(REPLY_VIEWPORT,{'action':'restore','top':viewport['previous_top']})
    except Exception:pass
 async def open_conversation(self,pid,config,url):
  page=self.current_page(pid)
  if page is None:await self.restore_session(pid,config);page=self.current_page(pid)
  await self._ensure_interactable_window(pid,page)
  if not url or page.url==url:return page
  target=urlsplit(url);root=(urlsplit(PLATFORMS[pid]['url']).hostname or '').removeprefix('www.')
  host=(target.hostname or '').removeprefix('www.')
  if target.scheme!='https' or target.username or target.password or (host!=root and not host.endswith('.'+root)):raise NeedsSetup('原会话地址不属于当前平台，未切换页面')
  state=await self.inspect(pid,config)
  if not state.get('composer_empty',True):raise NeedsSetup('当前平台有未发送内容，未切换会话，请先保存或清空草稿')
  await page.goto(url,wait_until='domcontentloaded',timeout=25000)
  return page
 async def capture_verified(self,pid,config,prompt,url):
  async with self.platform_locks.setdefault(pid,asyncio.Lock()):
   page=await self.open_conversation(pid,config,url)
   last='';changed=time.monotonic();result={};began=time.monotonic()
   while time.monotonic()-began<30:
    result=await self.response_snapshot(pid,config,prompt)
    answer=result.get('answer','')
    if answer:
     if answer!=last:changed=time.monotonic();last=answer
     result['stable']=time.monotonic()-changed>=2.4
     if result.get('done') and not result.get('busy') and result['stable']:break
    await asyncio.sleep(.8)
   if not result.get('answer','').strip():raise NeedsSetup((result.get('capture_issue') or '没有可靠匹配到原问题与回答')+'；未覆盖原记录，也没有重新提问')
   from storage import ident
   folder=HOME/'screenshots';folder.mkdir(exist_ok=True);name=ident()+'.png'
   try:await page.screenshot(path=str(folder/name),timeout=5000)
   except Exception:name=''
   return {**result,'conversation_url':page.url,'screenshot':name}
 async def send(self,pid,config,prompt,mode,on_sent,on_attempt=None):
  async with self.platform_locks.setdefault(pid,asyncio.Lock()):
   page=self.current_page(pid)
   if page is None or page.is_closed():raise NeedsSetup('请先打开该平台的专用浏览器，并由本人完成登录')
   if not config['ready']:raise NeedsSetup('请先标定输入框、发送按钮，并确认平台已校准')
   step='检查输入框与未发送草稿'
   try:
    await self._ensure_interactable_window(pid,page)
    initial=await self.inspect(pid,config)
    if initial.get('needs_user_action'):raise NeedsSetup(initial['message'])
    self.valid_page(pid,page)
    if not initial.get('composer_empty',True):raise NeedsSetup('当前平台输入框有未发送草稿，未覆盖文字或发送。请先在平台保存、发送或清空该草稿，再继续原任务。')
    fresh=config.get('conversation_mode','fresh')=='fresh'
    previous_url=page.url;previous_messages=None
    # Doubao's empty welcome page already IS a fresh conversation. The inner
    # new-chat role button can be inert there; do not click it redundantly.
    home=urlsplit(page.url);empty_home=False
    if fresh and pid=='doubao' and home.scheme=='https' and home.hostname in ('www.doubao.com','doubao.com') and home.path in ('/chat/','/chat') and not home.query and not home.fragment and initial.get('composer_empty') and initial.get('composer_editable'):
     empty_home=bool(await page.evaluate(DOUBAO_EMPTY_HOME_SCAN))
    if fresh and config['new_chat_selector'] and not empty_home:
     step='打开新对话'
     previous_messages=await self.response_snapshot(pid,config,prompt)
     # Prefer the actionable outer control found by the scanner. Its selector
     # is used for this execution only; saved calibration is not rewritten.
     control=initial.get('controls',{}).get('new_chat_selector',{})
     selector=control.get('selector') if control.get('found') else config['new_chat_selector']
     new=await self.first_visible(page,selector)
     if not new:raise NeedsSetup('未找到新对话按钮，请重新识别该入口；本次尚未发送问题')
     await new.click(timeout=8000,no_wait_after=True)
    elif fresh and mode=='visibility' and not empty_home:raise NeedsSetup('独立检查需要新对话入口；连续会话可在创建时另行选择')
    step='等待新对话输入框'
    composer=None
    for attempt in range(16):
     composer=await self.first_visible(page,config['composer'])
     if composer and await composer.is_editable():
      # A newly clicked SPA route can briefly retain the old editable composer.
      # If messages were observable, wait until that conversation is gone (or
      # the page has changed) before placing a fresh question into the editor.
      prior_content=previous_messages and (previous_messages.get('user_count',0) or previous_messages.get('assistant_count',0))
      if not prior_content or page.url!=previous_url:break
      current_messages=await self.response_snapshot(pid,config,prompt)
      if not current_messages.get('user_count',0) and not current_messages.get('assistant_count',0):break
     composer=None
     if attempt<15:await asyncio.sleep(.25)
    if not composer:raise NeedsSetup('新对话或可编辑输入框尚未就绪，可能需要登录、完成验证码或重新识别；本次尚未发送问题')
    step='读取原会话与填写问题'
    ready=await self.inspect(pid,config)
    if ready.get('needs_user_action'):raise NeedsSetup(ready['message'])
    if not ready.get('composer_empty',True):raise NeedsSetup('准备期间输入框出现了未发送草稿，未覆盖文字或发送。请先处理平台中的草稿，再继续原任务。')
    baseline=await self.response_snapshot(pid,config,prompt)
    await composer.fill(prompt,timeout=10000)
    old_text='';old_count=0
    if config['reply_selector']:
     try:
      reply=page.locator(config['reply_selector'])
      old_count=await reply.count()
      if old_count:old_text=await reply.last.inner_text(timeout=2000)
     except Exception:pass
    step='检查发送控件'
    button=None
    if config['send_button']:
     checked=await self.inspect(pid,config)
     if not checked['send_found']:raise NeedsSetup(checked['controls']['send_button']['message'])
     button=await self.first_visible(page,checked['controls']['send_button'].get('selector') or config['send_button'])
     if button is None or not await button.is_enabled():raise NeedsSetup('发送按钮不可用，请检查登录/额度或重新识别；本次尚未发送问题')
    elif config['send_key'] not in ('Enter','Control+Enter'):raise NeedsSetup('尚未标定发送按钮或指定发送快捷键')
   except NeedsSetup:raise
   except Exception as exc:raise preparation_failure(step,exc) from exc
   # The engine can distinguish a preparation failure from an action whose
   # effect may already have reached the platform. No action below is retried.
   if on_attempt:on_attempt()
   if button is not None:await button.click(timeout=10000,no_wait_after=True)
   else:await composer.press(config['send_key'],timeout=10000,no_wait_after=True)
   on_sent()
   answer='';last='';changed=time.monotonic();sample={};began=time.monotonic()
   while time.monotonic()-began<90:
    await asyncio.sleep(.8)
    try:
     sample=await self.response_snapshot(pid,config,prompt,baseline)
     current=sample.get('answer','')
     if not current and config['reply_selector'] and not patterns(pid).get('require_content'):
      reply=page.locator(config['reply_selector']);count=await reply.count()
      if count:
       fallback=await reply.nth(old_count if count>old_count else count-1).inner_text()
       if fallback!=old_text and prompt not in fallback and fallback!=prompt:current=fallback[:100000]
     if current:
      if current!=last:changed=time.monotonic();last=current
      answer=current[:100000]
      sample['stable']=time.monotonic()-changed>=2.4
      if sample.get('matched') and sample.get('done') and not sample.get('busy') and sample['stable']:break
      if not sample.get('matched') and time.monotonic()-changed>=8 and time.monotonic()-began>=12:break
    except Exception:pass
   folder=HOME/'screenshots';folder.mkdir(exist_ok=True)
   from storage import ident
   screenshot=ident()+'.png'
   try:await page.screenshot(path=str(folder/screenshot),full_page=False,timeout=5000)
   except Exception:screenshot=''
   return {**sample,'answer':answer,'screenshot':screenshot,'conversation_url':page.url,'note':'已保留回答与截图；未能确认完整性或问题对应时才需要人工检查。'}
 async def close(self,pid=None):
  targets=[pid] if pid else list(self.contexts)
  for key in targets:
   context=self.contexts.pop(key,None);self.pages.pop(key,None)
   self.navigation_errors.pop(key,None)
   self.window_recovery.pop(key,None);self.page_guards.pop(key,None);self.navigation_retries.pop(key,None)
   if context:
    try:await context.close()
    except Exception:pass
  if not pid and self.playwright:await self.playwright.stop();self.playwright=None
