from __future__ import annotations
import asyncio,csv,io,json,os,re,zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree as ET
from fastapi import FastAPI,HTTPException,Request,UploadFile,File,Query
from fastapi.responses import FileResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from config import ROOT,HOME,VERSION,PLATFORMS,supported_channels
from storage import init,db,get_meta,set_meta,records,ident,now,update_task
from domain import make_prompt,analyze,brand_hint,public_pack
from engine import Runner,create_batch
import engine
from browser_bridge import NeedsSetup
from insights import build_insights,eligibility,markdown_report,measurement
from queries import query_tasks,daily_budget,TASK_GROUPS
from responses import automatic_verification
from desktop_service import service_status
import keyword_planner
import platform_planner
import record_archive
from record_export import build_xlsx
from datetime import date
from urllib.parse import quote

runner=Runner()
@asynccontextmanager
async def lifespan(app):
 init()
 if os.getenv('JUNHE_DISABLE_WORKER')!='1':await runner.start()
 yield
 await runner.stop()

app=FastAPI(title='AI GEO 品牌可见度工作台',version=VERSION,lifespan=lifespan)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

@app.middleware('http')
async def local_mutations(request:Request,call_next):
 # Origin is only meaningful after Host is trusted: arbitrary DNS names must
 # not become local origins merely because they resolve to the loopback server.
 hosts=request.headers.getlist('host')
 host=re.fullmatch(r'(?:127\.0\.0\.1|localhost|\[::1\])(?::([0-9]{1,5}))?',hosts[0],re.IGNORECASE) if len(hosts)==1 else None
 if host is None or (host[1] is not None and not 1<=int(host[1])<=65535):
  return Response('请通过本机地址访问工作台',status_code=403)
 if request.method in ('POST','PUT','PATCH','DELETE'):
  origin=request.headers.get('origin')
  if request.headers.get('x-workspace-request')!='junhe-local' or (origin and origin!=str(request.base_url).rstrip('/')):
   return Response('请从本机工作台执行操作',status_code=403)
 response=await call_next(request)
 if request.url.path=='/' or request.url.path.startswith(('/static/','/api/')):
  response.headers['Cache-Control']='no-store, max-age=0'
  response.headers['Pragma']='no-cache'
 return response

@app.get('/')
def home():return FileResponse(ROOT/'static/index.html')
@app.get('/api/health')
def health():return {'service':'ai-geo-workspace','status':'ok','version':VERSION,'scheduler_timezone':'Asia/Shanghai','queue':runner.snapshot(),'desktop':service_status()}

def platform_view(pid):
 data={**PLATFORMS[pid],**get_meta('platform:'+pid)}
 data['key_configured']=bool(data['env'] and os.getenv(data['env'],''))
 page=runner.browser.current_page(pid);data['browser_open']=bool(page and not page.is_closed())
 data['connection']=runner.browser.connection_state(pid)
 data['channels']=supported_channels(pid)
 return data

@app.get('/api/bootstrap')
def bootstrap():
 tasks=[t for t in records('tasks') if t['platform'] in PLATFORMS];profile=get_meta('profile');evaluated=[t for t in tasks if eligibility(t,profile)=='eligible']
 metrics={}
 for channel in ('web','api'):
  sample=[t for t in evaluated if t['channel']==channel]
  observations=[analyze(t['answer'],profile) for t in sample]
  metrics[channel]={'samples':len(sample),'brand_mentions':sum(bool(t.get('brand_mentioned')) for t in observations),
                    'official_links':sum(bool(t.get('official_link_present')) for t in observations)}
 table=[]
 for task in tasks[:150]:
  table.append({**{k:v for k,v in task.items() if k not in ('prompt','answer')},'answer_preview':task['answer'][:120],'metrics':json.loads(task['metrics'])})
 with db() as c:notice=c.execute("SELECT value FROM meta WHERE key='scheduler_notice'").fetchone()
 return {'version':VERSION,'client_counts':{group:sum(not states or t['status'] in states for t in tasks) for group,states in TASK_GROUPS.items()},
         'profile':get_meta('profile'),'settings':get_meta('settings'),'desktop':service_status(),'platforms':[platform_view(pid) for pid in PLATFORMS],
         'documents':records('documents'),'keywords':records('keywords'),'tasks':table,'schedules':records('schedules'),
         'platform_keywords':platform_planner.list_keywords()['items'],'platform_schedules':platform_planner.list_schedules()['items'],
         'planning_migration':get_meta('platform_planning_v2_migration'),'default_routing':'per_platform',
         'metrics':metrics,'daily_budget':daily_budget(),'current_task':runner.current,'queue':runner.snapshot(),'scheduler_notice':json.loads(notice['value']) if notice else None}

@app.get('/api/insights')
def insights(days:int=Query(30,ge=1,le=366),channel:str='web',platform:str='all',start_date:str|None=None,end_date:str|None=None,scope:str='natural'):
 try:return build_insights(records('tasks'),get_meta('profile'),days,channel,platform,start_date,end_date,scope=scope)
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.get('/api/export/visibility.md')
def export_visibility(days:int=Query(30,ge=1,le=366),channel:str='web',platform:str='all',start_date:str|None=None,end_date:str|None=None,scope:str='natural'):
 report=insights(days,channel,platform,start_date,end_date,scope)
 return Response(markdown_report(report).encode('utf-8-sig'),media_type='text/markdown; charset=utf-8',
                 headers={'Content-Disposition':'attachment; filename="junhe-visibility-report.md"'})

@app.get('/api/tasks')
def task_list(q:str=Query('',max_length=160),status:str='',platform:str='',channel:str='',mode:str='',page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),group:str='all'):
 try:return query_tasks(q,status,platform,channel,mode,page,page_size,group=group)
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc

class Profile(BaseModel):
 company_name:str=Field(min_length=2,max_length=100)
 domain:str=Field(min_length=4,max_length=200)
 aliases:list[str]=Field(default_factory=list,max_length=20)
 business:str=Field(min_length=1,max_length=500)
 audience:str=Field(default='',max_length=1000)
 public_intro:str=Field(min_length=1,max_length=5000)
 audience_confirmed:bool=False
 brand_name:str=Field(default='',max_length=100)
 brand_aliases:list[str]=Field(default_factory=list,max_length=20)
 brand_relation:str=Field(default='',max_length=1000)
@app.put('/api/profile')
def save_profile(body:Profile):
 value=body.model_dump();domain=value['domain'].strip().lower()
 if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}',domain):raise HTTPException(422,'域名只填写主机名，例如www.junheprobio.com，不含路径')
 if any(len(alias)>80 for alias in [*body.aliases,*body.brand_aliases]):raise HTTPException(422,'别名过长')
 existing=get_meta('profile')
 for key in ('brand_name','brand_aliases','brand_relation'):
  if key not in body.model_fields_set:value[key]=existing.get(key,value[key])
 value['domain']=domain;set_meta('profile',value)
 return {'message':'企业资料已保存；已确认公开资料卡请单独维护，旧任务提示词不会改写'}

class Document(BaseModel):
 title:str=Field(min_length=1,max_length=160)
 body:str=Field(min_length=1,max_length=20000)
 source:str=Field(min_length=1,max_length=500)
 approved:bool=False

class SeekableUpload:
 """Python 3.10 SpooledTemporaryFile lacks seekable(), which ZipFile expects."""
 def __init__(self,file):self.file=file
 def read(self,*args):return self.file.read(*args)
 def seek(self,*args):return self.file.seek(*args)
 def tell(self):return self.file.tell()
 def seekable(self):return True
@app.post('/api/documents')
def add_document(body:Document):
 did=ident()
 with db() as c:c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',(did,body.title,body.body,body.source,int(body.approved),now()))
 return {'id':did}
@app.put('/api/documents/{did}')
def edit_document(did:str,body:Document):
 with db() as c:
  if not c.execute('UPDATE documents SET title=?,body=?,source=?,approved=? WHERE id=?',(body.title,body.body,body.source,int(body.approved),did)).rowcount:raise HTTPException(404,'资料不存在')
 return {'message':'资料已更新'}
@app.delete('/api/documents/{did}')
def delete_document(did:str):
 with db() as c:c.execute('DELETE FROM documents WHERE id=?',(did,))
 return {'message':'资料已移除，历史任务快照保留'}

@app.post('/api/documents/import')
async def import_document(file:UploadFile=File(...)):
 filename=Path((file.filename or '').replace('\\','/')).name;suffix=Path(filename).suffix.lower()
 if suffix not in ('.txt','.md','.pptx'):raise HTTPException(422,'支持TXT、Markdown和PPTX；图片扫描页需另行整理文字')
 limit=400*1024*1024 if suffix=='.pptx' else 2*1024*1024
 size=0
 while chunk:=await file.read(1024*1024):
  size+=len(chunk)
  if size>limit:raise HTTPException(413,'文件超出限制：PPTX400MB，文本2MB')
 await file.seek(0);entries=[]
 try:
  if suffix=='.pptx':
   with zipfile.ZipFile(SeekableUpload(file.file)) as archive:
    names=sorted((n for n in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)),key=lambda n:int(re.search(r'(\d+)\.xml',n).group(1)))
    if len(names)>200:raise ValueError('最多200页')
    for name in names:
     if archive.getinfo(name).file_size>2*1024*1024:raise ValueError('单页XML过大')
     root=ET.fromstring(archive.read(name))
     text='\n'.join(t.text or '' for t in root.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}t'))
     page_number=re.search(r'(\d+)\.xml',name).group(1)
     if text.strip():entries.append((f"{filename} 第{page_number}页",text[:20000]))
  else:
   text=(await file.read()).decode('utf-8-sig')
   entries=[(filename+f' 片段{i//18000+1}',text[i:i+18000]) for i in range(0,len(text),18000)]
  if not entries:raise ValueError('未提取到文字；图片页请先提供可复制文本')
  if len(entries)>200:raise ValueError('文本过长')
 except (ValueError,zipfile.BadZipFile,ET.ParseError,UnicodeDecodeError) as exc:raise HTTPException(422,str(exc)) from exc
 with db() as c:
  for title,text in entries:c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',(ident(),title,text,filename,0,now()))
 return {'message':f'提取{len(entries)}条文字资料，全部为待核验，不会自动发送；原文件不存入项目'}

class Keyword(BaseModel):
 text:str=Field(min_length=1,max_length=160)
 kind:str=Field(default='自定义',max_length=30)
@app.post('/api/keywords')
def add_keyword(body:Keyword):
 if not body.text.strip():raise HTTPException(422,'关键词不能为空')
 with db() as c:c.execute('INSERT OR IGNORE INTO keywords VALUES(?,?,?,?)',(ident(),body.text.strip(),body.kind,now()))
 return {'message':'关键词已保存'}
@app.delete('/api/keywords/{kid}')
def delete_keyword(kid:str):
 with db() as c:c.execute('DELETE FROM keywords WHERE id=?',(kid,))
 return {'message':'已删除'}
@app.get('/api/keyword-suggestions')
def suggestions():
 p=get_meta('profile');business=p['business']
 return {'basis':'根据已填写主营业务生成的检索问题模板，未声称搜索量或竞争难度',
         'items':[p['company_name']+' 官网',business+'企业有哪些',business+'经销合作怎么选择',business+'代理需要核对哪些资质',business+'门店合作需要了解什么',business+'产品标签应该关注什么信息']}

class KeywordPlan(BaseModel):
 enabled:bool=False
 time:str='09:00'
 count:int=Field(default=10,ge=1,le=30)
 goal:Literal['source_audit','discovery','brand_check']='source_audit'
 platforms:list[str]=Field(default_factory=lambda:list(PLATFORMS),min_length=1,max_length=len(PLATFORMS))
@app.get('/api/keyword-candidates')
def keyword_candidates():return keyword_planner.candidates()
@app.put('/api/keyword-plan')
def save_keyword_plan(body:KeywordPlan):
 if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',body.time):raise HTTPException(422,'时间请使用HH:MM格式')
 if len(set(body.platforms))!=len(body.platforms) or any(pid not in PLATFORMS for pid in body.platforms):raise HTTPException(422,'平台无效或重复')
 set_meta('keyword_plan',body.model_dump());return {'message':'每日分平台本地关键词计划已保存，不会自动创建或发送任务'}
@app.post('/api/keyword-candidates/generate')
def generate_keywords():return keyword_planner.generate()
@app.post('/api/keyword-candidates/{kid}/accept')
def accept_keyword(kid:str):
 try:return keyword_planner.accept(kid)
 except ValueError as exc:raise HTTPException(409,str(exc)) from exc
@app.delete('/api/keyword-candidates/{kid}')
def dismiss_keyword(kid:str):
 with db() as c:c.execute("UPDATE keyword_candidates SET state='dismissed' WHERE id=? AND state='pending'",(kid,))
 return {'message':'已忽略，之后不会重复生成同一问题'}

# A local strategy preview is deliberately separate from execution. The user
# reviews one explicitly routed row per question; no shared cross-product.
class PlatformPlan(BaseModel):
 model_config={'extra':'forbid'}
 topic:str=Field(min_length=1,max_length=160)
 platforms:list[str]=Field(min_length=1,max_length=len(PLATFORMS))
 goal:Literal['source_audit','discovery','brand_check']='source_audit'
 count_per_platform:int=Field(default=1,ge=1,le=5)

class PlatformKeyword(BaseModel):
 model_config={'extra':'forbid'}
 platform:str
 text:str=Field(min_length=1,max_length=160)
 kind:str=Field(default='',max_length=30)
 goal:Literal['source_audit','discovery','brand_check']='source_audit'
 source_focus:str=Field(default='',max_length=80)
 reason:str=Field(default='',max_length=1000)
 id:str|None=None
 strategy_version:str|None=Field(default=None,max_length=40)

class PlatformItems(BaseModel):
 model_config={'extra':'forbid'}
 items:list[PlatformKeyword]=Field(min_length=1,max_length=30)
 mode:Literal['visibility','materials']='visibility'
 conversation_mode:Literal['fresh','continue']='fresh'

class PlatformBatch(PlatformItems):
 request_key:str=Field(min_length=8,max_length=120)

class PlatformSchedule(PlatformItems):
 time:str
 enabled:bool=False

class PlatformScheduleState(BaseModel):
 model_config={'extra':'forbid'}
 enabled:bool

def planner_result(call):
 try:return call()
 except KeyError as exc:raise HTTPException(404,str(exc.args[0])) from exc
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.get('/api/platform-strategies')
def platform_strategies():return planner_result(platform_planner.strategies)

@app.post('/api/platform-plans/preview')
def platform_plan_preview(body:PlatformPlan):
 return planner_result(lambda:platform_planner.preview_plan(**body.model_dump()))

@app.get('/api/platform-keywords')
def platform_keyword_list(platform:str=''):
 return planner_result(lambda:platform_planner.list_keywords(platform))

@app.post('/api/platform-keywords')
def platform_keyword_add(body:PlatformKeyword):
 return planner_result(lambda:platform_planner.save_keyword(body.model_dump()))

@app.put('/api/platform-keywords/{kid}')
def platform_keyword_update(kid:str,body:PlatformKeyword):
 return planner_result(lambda:platform_planner.update_keyword(kid,body.model_dump()))

@app.delete('/api/platform-keywords/{kid}')
def platform_keyword_delete(kid:str):
 return planner_result(lambda:platform_planner.delete_keyword(kid))

@app.post('/api/platform-keywords/generate')
def platform_keyword_generate(body:PlatformPlan):
 return planner_result(lambda:platform_planner.generate_keywords(**body.model_dump()))

@app.post('/api/platform-prompts/preview')
def platform_prompt_preview(body:PlatformItems):
 def preview_items():
  prepared=engine.prepare_targeted_items([item.model_dump() for item in body.items],body.mode,body.conversation_mode)
  return {'items':[{key:row[key] for key in (*platform_planner.ITEM_FIELDS,'prompt')} for row in prepared],
          'count':len(prepared),'routing':'per_platform','note':'仅预览，没有保存或发送'}
 return planner_result(preview_items)

@app.post('/api/platform-batches')
def platform_batch(body:PlatformBatch):
 def create_items():
  result=engine.create_targeted_batch([item.model_dump() for item in body.items],body.mode,body.request_key,body.conversation_mode)
  if not get_meta('settings')['paused']:runner.block_unready()
  with db() as c:waiting=c.execute("SELECT count(*) FROM tasks WHERE batch_id=? AND status='waiting_setup'",(result['batch_id'],)).fetchone()[0]
  return {**result,'waiting_setup':waiting,'queue':runner.snapshot(),'routing':'per_platform'}
 return planner_result(create_items)

@app.get('/api/platform-schedules')
def platform_schedule_list():return platform_planner.list_schedules()

@app.post('/api/platform-schedules')
def platform_schedule_add(body:PlatformSchedule):
 return planner_result(lambda:platform_planner.save_schedule(body.time,[item.model_dump() for item in body.items],body.mode,body.conversation_mode,body.enabled))

@app.put('/api/platform-schedules/{sid}')
def platform_schedule_enable(sid:str,body:PlatformScheduleState):
 return planner_result(lambda:platform_planner.enable_schedule(sid,body.enabled))

@app.delete('/api/platform-schedules/{sid}')
def platform_schedule_delete(sid:str):
 return planner_result(lambda:platform_planner.delete_schedule(sid))

class PlatformConfig(BaseModel):
 channel:str='web'
 model:str=Field(default='',max_length=150)
 composer:str=Field(default='textarea, [contenteditable="true"]',max_length=600)
 send_button:str=Field(default='',max_length=600)
 reply_selector:str=Field(default='',max_length=600)
 new_chat_selector:str=Field(default='',max_length=600)
 send_key:str=''
 ready:bool=False
 search_enabled:bool=False
@app.put('/api/platforms/{pid}')
async def configure_platform(pid:str,body:PlatformConfig):
 if pid not in PLATFORMS:raise HTTPException(404,'平台不存在')
 if body.channel not in supported_channels(pid) or body.send_key not in ('','Enter','Control+Enter'):raise HTTPException(422,'该平台不支持此通道，或快捷键无效')
 if body.channel=='api' and not PLATFORMS[pid]['api']:raise HTTPException(422,'该平台只有网页通道')
 if runner.busy(pid):raise HTTPException(409,'该平台正在执行任务，请等待完成后再修改连接配置')
 value=body.model_dump()
 for key in ('composer','send_button','new_chat_selector','reply_selector','model'):value[key]=value[key].strip()
 missing=[]
 if not value['composer']:missing.append('输入框')
 if not value['send_button'] and not value['send_key']:missing.append('发送按钮或发送快捷键')
 inspection=None
 if body.channel=='web' and body.ready:
  if missing:raise HTTPException(422,'尚未保存：请先配置'+ '、'.join(missing)+'；也可以取消勾选允许自动发送，先保存草稿。')
  try:inspection=await runner.browser.inspect(pid,value)
  except NeedsSetup as exc:raise HTTPException(409,'尚未保存：'+str(exc)) from exc
  except Exception as exc:raise HTTPException(409,'尚未保存：页面控件检查失败，请检查专用窗口或重新标定。') from exc
  if not inspection['open']:raise HTTPException(409,'尚未保存：专用Edge未打开，请先打开窗口并本人登录。')
  if not inspection['composer_found'] or not inspection['composer_editable']:raise HTTPException(409,'尚未保存：没有找到可编辑输入框，请使用“定位输入框”或重新标定。')
  if value['send_button'] and not inspection['send_found']:raise HTTPException(409,'尚未保存：'+inspection.get('controls',{}).get('send_button',{}).get('message','未找到发送按钮')+'。请重新识别，或明确选择平台支持的发送快捷键。')
  if value['send_button'] and inspection.get('controls',{}).get('send_button',{}).get('normalized'):value['send_button']=inspection['controls']['send_button']['selector']
  if value['new_chat_selector'] and not inspection['new_chat_found']:raise HTTPException(409,'尚未保存：新对话按钮已失效，请重新标定。')
 set_meta('platform:'+pid,{'id':pid,**value})
 core_ready=bool(value['composer'] and (value['send_button'] or value['send_key']))
 if not value['new_chat_selector']:missing.append('新对话按钮（搜索检查需要）')
 enabled=body.channel=='web' and body.ready
 message='已保存并启用网页连接' if enabled else '已保存草稿，尚未启用自动发送' if body.channel=='web' else 'API配置已保存，实际调用时验证Key和模型'
 if enabled and not value['new_chat_selector']:message+='；搜索检查还需标定新对话按钮'
 return {'message':message,'saved_at':now(),'config':value,
         'readiness':{'enabled':enabled,'core_ready':core_ready,'visibility_ready':enabled and bool(value['new_chat_selector']),'missing':missing},'inspection':inspection}
class Pick(BaseModel):
 kind:str=Field(default='',max_length=40)
 config:PlatformConfig|None=None
@app.get('/api/platforms/{pid}/response-layout')
async def response_layout(pid:str,open_last:bool=False):
 if pid not in PLATFORMS:raise HTTPException(404,'平台不存在')
 if runner.busy(pid):raise HTTPException(409,'该平台正在执行，稍后查看只读布局')
 with db() as c:row=c.execute('SELECT prompt,metrics FROM tasks WHERE platform=? AND sent_at IS NOT NULL ORDER BY sent_at DESC,rowid DESC LIMIT 1',(pid,)).fetchone()
 try:
  cfg=get_meta('platform:'+pid)
  if open_last and row:await runner.browser.open_conversation(pid,cfg,json.loads(row['metrics']).get('conversation_url',''))
  return await runner.browser.response_snapshot(pid,cfg,row['prompt'] if row else '',diagnostic=True)
 except NeedsSetup as exc:raise HTTPException(409,str(exc)) from exc
@app.post('/api/platforms/{pid}/{action}')
async def platform_action(pid:str,action:str,body:Pick|None=None):
 if pid not in PLATFORMS:raise HTTPException(404,'平台不存在')
 if runner.busy(pid):raise HTTPException(409,'该平台正在执行任务，请等待完成后再标定；其他平台不受影响')
 try:
  if action=='connect':
   await runner.browser.connect(pid)
   state=runner.browser.connection_state(pid)
   cfg=get_meta('platform:'+pid)
   message='已恢复专用Edge和原登录资料。已保存的标定规则仍在，请检查登录和控件。旧的待配置任务需在记录中继续排队，不必重复创建。' if cfg['ready'] and state.get('profile_saved') else '已打开专用Edge窗口。请切换到该窗口，由本人完成登录，然后回到这里继续标定。'
   if state['navigation_error']:message='专用Edge已打开，但平台网页尚未正常加载。请在该窗口检查网络或刷新，窗口会保留。'
   return {'message':message,'connection':state}
  if action=='close':
   owned=pid in runner.browser.contexts
   await runner.browser.close(pid)
   return {'message':'工作台管理的浏览器已关闭，登录资料仍保存在本机' if owned else '工作台当前未接管该平台窗口。若旧专用Edge仍开着，请先关闭那个旧窗口，再重新连接。'}
  if action in ('inspect','reveal','diagnose'):
   cfg=body.config.model_dump() if body and body.config else get_meta('platform:'+pid)
   if action=='diagnose':return await runner.browser.inspect(pid,cfg,include_candidates=True)
   return await (runner.browser.reveal(pid,cfg) if action=='reveal' else runner.browser.inspect(pid,cfg))
  if action=='cancel-pick':await runner.browser.cancel_pick(pid);return {'message':'已取消标定，现在可以正常操作专用网页'}
  if action=='pick':
   if not body or body.kind not in ('composer','send_button','reply_selector','new_chat_selector'):raise HTTPException(422,'标定类型无效')
   await runner.browser.pick(pid,body.kind);return {'message':'请在专用浏览器点击对应控件；该次点击只记录，不触发原操作'}
  if action=='picked':
   result=await runner.browser.picked(pid)
   return {'result':result}
 except NeedsSetup as exc:raise HTTPException(409,str(exc)) from exc
 except HTTPException:raise
 except Exception as exc:raise HTTPException(409,'浏览器操作未完成。请检查专用Edge是否仍打开；遇到登录或安全验证时请本人处理，再重试连接。') from exc
 raise HTTPException(404,'操作不存在')

class Preview(BaseModel):keyword:str=Field(min_length=1,max_length=160);mode:str
@app.post('/api/prompt-preview')
def preview(body:Preview):
 if body.mode not in ('visibility','materials'):raise HTTPException(422,'任务模式无效')
 try:return {'prompt':make_prompt(body.keyword,body.mode),'brand_hint':brand_hint(body.keyword,get_meta('profile'))}
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
class Batch(BaseModel):
 keywords:list[str]=Field(min_length=1,max_length=5)
 platforms:list[str]=Field(min_length=1,max_length=len(PLATFORMS))
 mode:str
 request_key:str=Field(min_length=8,max_length=120)
 conversation_mode:str='fresh'
@app.post('/api/batches')
def batch(body:Batch):
 if len(set(body.platforms))>1:raise HTTPException(422,'请使用分平台关键词方案，不能将同一问题统一分发')
 try:
  result=create_batch(body.keywords,body.platforms,body.mode,body.request_key,body.conversation_mode)
  if not get_meta('settings')['paused']:runner.block_unready()
  with db() as c:waiting=c.execute("SELECT count(*) FROM tasks WHERE batch_id=? AND status='waiting_setup'",(result['batch_id'],)).fetchone()[0]
  return {**result,'waiting_setup':waiting,'queue':runner.snapshot()}
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
@app.get('/api/tasks/{tid}')
def task_detail(tid:str):
 with db() as c:row=c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
 if not row or row['deleted_at']:raise HTTPException(404,'任务不存在或已移入回收站')
 task=dict(row);task['metrics']=json.loads(task['metrics']);task['measurement']=measurement(task,get_meta('profile'));return task
@app.post('/api/tasks/{tid}/capture-diagnostics')
async def capture_diagnostics(tid:str):
 task=task_detail(tid);pid=task['platform']
 if task['channel']!='web' or not task['sent_at']:raise HTTPException(409,'此检查仅用于已发送的网页记录')
 if runner.busy(pid):raise HTTPException(409,'请等待该平台任务结束')
 cfg=get_meta('platform:'+pid)
 try:
  await runner.browser.open_conversation(pid,cfg,task['metrics'].get('conversation_url',''))
  return await runner.browser.response_snapshot(pid,cfg,task['prompt'],diagnostic=True)
 except NeedsSetup as exc:raise HTTPException(409,str(exc)) from exc
@app.post('/api/tasks/{tid}/capture')
async def capture_answer(tid:str):
 task=task_detail(tid)
 if task['platform']!='doubao' or task['channel']!='web' or not task['sent_at'] or task['status'] not in ('sent','needs_review','completed'):raise HTTPException(409,'仅支持已发送的豆包网页任务；获取回答不会发送或重发问题')
 if runner.busy(task['platform']):raise HTTPException(409,'请等待该平台任务结束后再获取已发送回答')
 try:result=await runner.browser.capture_existing('doubao',get_meta('platform:doubao'),task['prompt'],task['metrics'].get('conversation_url',''))
 except NeedsSetup as exc:raise HTTPException(409,str(exc)) from exc
 except Exception as exc:raise HTTPException(409,'获取回答未完成，原问题没有重发。请检查豆包窗口和原对话是否仍可打开。') from exc
 metrics={**task['metrics'],'conversation_url':result['conversation_url'],'answer_matched_to_prompt':True,'later_turns_present':result['later_turns'],'source_links':result['links']}
 name=ident()+'.png';folder=HOME/'screenshots';folder.mkdir(exist_ok=True)
 try:await runner.browser.pages['doubao'].screenshot(path=str(folder/name),full_page=False)
 except Exception:name=task['screenshot']
 update_task(tid,answer=result['answer'],screenshot=name,status='needs_review',reviewed=0,metrics=json.dumps(metrics,ensure_ascii=False),note=result['note'])
 return {'message':result['note'],'task_id':tid,'answer_length':len(result['answer']),'status':'needs_review'}
@app.post('/api/tasks/{tid}/retry')
def retry(tid:str):
 with db() as c:
  changed=c.execute("UPDATE tasks SET status='queued',updated_at=? WHERE id=? AND deleted_at IS NULL AND status='waiting_setup'",(now(),tid)).rowcount
  if not changed:raise HTTPException(409,'仅未删除的待配置任务可重试；已发送/不确定任务需先核对，不能自动重发')
 return {'message':'已重新排队'}
@app.post('/api/tasks/{tid}/verify')
async def verify_capture(tid:str):
 task=task_detail(tid)
 if task['channel']!='web' or not task['sent_at'] or task['status'] not in ('sent','needs_review','completed'):raise HTTPException(409,'只能采集已发送的网页回答，不会重新提问')
 if runner.busy(task['platform']):raise HTTPException(409,'该平台正在执行任务，完成后可重新采集')
 try:result=await runner.browser.capture_verified(task['platform'],get_meta('platform:'+task['platform']),task['prompt'],task['metrics'].get('conversation_url',''))
 except NeedsSetup as exc:raise HTTPException(409,str(exc)) from exc
 except Exception as exc:raise HTTPException(409,'此次采集未完成，原记录保留，没有重新发送问题；请检查原会话是否可访问') from exc
 verified,reason=automatic_verification(result)
 if not verified:return {'verified':False,'message':reason+'；原记录已保留，没有重新发送问题','answer_length':len(result['answer'])}
 metrics={**task['metrics'],**analyze(result['answer'],get_meta('profile')),'verification_method':'automatic_dom' if verified else 'unverified',
          'verification_note':reason,'answer_matched_to_prompt':result.get('matched',False),'conversation_url':result['conversation_url'],
          'source_links':result.get('links',[]),'capture_evidence':{key:result.get(key) for key in ('association','done','busy','stable','later_turns')}}
 update_task(tid,answer=result['answer'],metrics=json.dumps(metrics,ensure_ascii=False),status='completed' if verified else 'needs_review',reviewed=int(verified),
             screenshot=result.get('screenshot') or task['screenshot'],note=reason+'；此次只重新采集，原问题未重发')
 return {'verified':verified,'message':reason,'answer_length':len(result['answer'])}
@app.post('/api/tasks/{tid}/diagnose')
async def diagnose_task(tid:str):
 task=task_detail(tid);pid=task['platform']
 if task['channel']!='web' or task['status'] not in ('uncertain','interrupted','sent','needs_review'):raise HTTPException(409,'此检查用于发送或采集状态待确认的网页任务')
 if runner.busy(pid):raise HTTPException(409,'该平台正在执行任务，完成后再检查原会话')
 cfg=get_meta('platform:'+pid)
 try:
  if runner.browser.current_page(pid) is None:await runner.browser.connect(pid)
  state=await runner.browser.inspect(pid,cfg)
  sample=await runner.browser.response_snapshot(pid,cfg,task['prompt'])
 except NeedsSetup as exc:raise HTTPException(409,str(exc)) from exc
 except Exception as exc:raise HTTPException(409,'连接检查未完成，请在专用窗口确认网络与登录；本次没有发送问题') from exc
 message='当前会话找到了这条问题；请查看该会话的完整回答后再核对记录。' if sample.get('matched') else '当前打开的会话没有找到这条问题；这不代表历史会话从未发送过，请按原提示词在平台历史中查找。'
 return {'message':message+' 本次只检查，没有填入或发送问题。','send_confirmed_at':task['sent_at'],'matched_in_current_chat':bool(sample.get('matched')),'answer_length':len(sample.get('answer','')),'composer_editable':state.get('composer_editable',False),'task_unchanged':True}
@app.post('/api/tasks/{tid}/cancel')
def cancel(tid:str):
 with db() as c:
  changed=c.execute("UPDATE tasks SET status='cancelled',updated_at=? WHERE id=? AND deleted_at IS NULL AND status IN ('queued','waiting_setup')",(now(),tid)).rowcount
 if not changed:raise HTTPException(409,'当前任务已在执行或已结束，不能撤回已发送内容')
 return {'message':'已取消'}
class Review(BaseModel):
 answer:str|None=Field(default=None,max_length=100000)
@app.post('/api/tasks/{tid}/review')
def review(tid:str,body:Review):
 task=task_detail(tid)
 if task['channel']!='web' or task['status'] not in ('sent','needs_review','completed'):raise HTTPException(409,'仅对已发送的网页任务核对回答')
 if body.answer is None or not body.answer.strip():
  raise HTTPException(422,'回答内容不能为空。请先自动采集回答，或粘贴平台完整回答后再保存。')
 metrics={**task['metrics'],**analyze(body.answer,get_meta('profile')),'brand_hint':brand_hint(task['keyword'],get_meta('profile'))}
 metrics['verification_method']='human'
 update_task(tid,answer=body.answer,status='completed',reviewed=1,metrics=json.dumps(metrics,ensure_ascii=False),note='操作者已核对网页回答；只统计名称/链接出现，不证明被平台永久收录')
 return {'message':'回答已核对记录'}

class Settings(BaseModel):
 interval_seconds:int=Field(default=45,ge=30,le=600)
 daily_limit:int=Field(default=300,ge=1,le=1000)
 paused:bool=False
 parallel_platforms:int=Field(default=6,ge=1,le=len(PLATFORMS))
 auto_verify:bool=True
@app.put('/api/settings')
def settings(body:Settings):set_meta('settings',body.model_dump());return {'message':'队列设置已保存；暂停阻止下一个任务，不撤回正在发送的请求'}
class Schedule(BaseModel):
 time:str
 keyword_ids:list[str]=Field(min_length=1,max_length=5)
 platforms:list[str]=Field(min_length=1,max_length=len(PLATFORMS))
 mode:str='visibility'
 enabled:bool=False
@app.post('/api/schedules')
def add_schedule(body:Schedule):
 if len(set(body.platforms))>1:raise HTTPException(422,'请使用分平台关键词方案，不能将同一问题统一分发')
 if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',body.time) or body.mode not in ('visibility','materials') or any(p not in PLATFORMS for p in body.platforms):raise HTTPException(422,'时间、平台或模式无效')
 existing={k['id'] for k in records('keywords')}
 if any(k not in existing for k in body.keyword_ids):raise HTTPException(422,'关键词不存在')
 with db() as c:c.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?)',(ident(),body.time,json.dumps(body.keyword_ids),json.dumps(body.platforms),body.mode,int(body.enabled),'',now()))
 return {'message':'计划已保存。仅工作台服务保持运行时执行，每个计划每日最多触发一次'}
@app.delete('/api/schedules/{sid}')
def delete_schedule(sid:str):
 with db() as c:c.execute('DELETE FROM schedules WHERE id=?',(sid,))
 return {'message':'计划已删除'}

@app.get('/api/screenshots/{name}')
def screenshot(name:str):
 if not re.fullmatch(r'[a-f0-9]{32}\.png',name):raise HTTPException(404)
 path=HOME/'screenshots'/name
 if not path.is_file():raise HTTPException(404)
 return FileResponse(path,media_type='image/png')
class RecordFilters(BaseModel):
 q:str=Field(default='',max_length=160)
 status:str=''
 platform:str=''
 channel:str=''
 mode:str=''
class RecordDeletePreview(BaseModel):
 filters:RecordFilters=Field(default_factory=RecordFilters)
 ids:list[str]=Field(default_factory=list,max_length=1000)
 before:date|None=None
class RecordDeleteCommit(BaseModel):token:str=Field(pattern=r'^[a-f0-9]{32}$')
class RecordRestore(BaseModel):ids:list[str]=Field(min_length=1,max_length=1000)

@app.post('/api/records/delete-preview')
def record_delete_preview(body:RecordDeletePreview):
 try:return record_archive.preview(body.filters.model_dump(),body.ids,body.before)
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
@app.post('/api/records/delete')
def record_delete(body:RecordDeleteCommit):
 try:return record_archive.commit(body.token)
 except ValueError as exc:raise HTTPException(409,str(exc)) from exc
@app.get('/api/records/trash')
def record_trash(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
 return record_archive.trash(page,page_size)
@app.post('/api/records/restore')
def record_restore(body:RecordRestore):return record_archive.restore(body.ids)

@app.get('/api/export/tasks.xlsx')
def export_tasks_xlsx(q:str=Query('',max_length=160),status:str='',platform:str='',channel:str='',mode:str=''):
 try:tasks=query_tasks(q,status,platform,channel,mode,export=True)
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
 return Response(build_xlsx(tasks,get_meta('profile')),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  headers={'Content-Disposition':"attachment; filename=ai-answer-records.xlsx; filename*=UTF-8''"+quote('AI回答记录.xlsx')})

@app.get('/api/export/tasks.csv')
def export_tasks(q:str=Query('',max_length=160),status:str='',platform:str='',channel:str='',mode:str=''):
 try:tasks=query_tasks(q,status,platform,channel,mode,export=True)
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc
 stream=io.StringIO(newline='');writer=csv.writer(stream)
 fields=['platform','channel','mode','keyword','status','reviewed','created_at','answer','note'];writer.writerow(fields)
 for task in tasks:
  row=[]
  for key in fields:
   value=str(task[key]);row.append("'"+value if value.lstrip().startswith(('=','+','-','@')) else value)
  writer.writerow(row)
 return Response(('\ufeff'+stream.getvalue()).encode(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="junhe-tasks.csv"'})
@app.get('/api/export/website-pack.zip')
def export_pack():
 stream=io.BytesIO()
 with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
  for name,text in public_pack(get_meta('profile')).items():archive.writestr(name,text)
 return Response(stream.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="junhe-website-drafts.zip"'})
