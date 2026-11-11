import asyncio,hashlib,json,time,logging,re
from datetime import datetime,timezone,timedelta
import httpx
from config import PLATFORMS,ROOT
from storage import db,ident,now,get_meta,update_task
from domain import make_prompt,analyze,brand_hint
from browser_bridge import BrowserBridge,NeedsSetup
from providers import api_send
from responses import automatic_verification

CST=timezone(timedelta(hours=8))
def day_window():
 local=datetime.now(CST);start=local.replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
 return start.isoformat(timespec='seconds'),(start+timedelta(days=1)).isoformat(timespec='seconds')

def prepare_targeted_items(items,mode,conversation_mode='fresh'):
 """Validate explicit routes and snapshot server-built prompts, without writes."""
 if mode not in ('visibility','materials'):raise ValueError('任务模式无效')
 if conversation_mode not in ('fresh','continue'):raise ValueError('会话方式无效')
 if not isinstance(items,list) or not 1<=len(items)<=30:raise ValueError('每批请配置1至30条平台专属问题')
 catalog=json.loads((ROOT/'platform_strategy_catalog.json').read_text(encoding='utf-8'))
 strategies={row['id']:row for row in catalog['items']}
 profile=get_meta('profile');counts={};seen={};prepared=[]
 for item in items:
  if hasattr(item,'model_dump'):item=item.model_dump()
  if not isinstance(item,dict):raise ValueError('平台问题格式无效')
  pid=item.get('platform');text=item.get('text','');goal=item.get('goal','source_audit')
  if pid not in PLATFORMS or pid not in strategies:raise ValueError('请选择有效平台')
  if not isinstance(text,str) or not 1<=len(text.strip())<=160:raise ValueError('每条平台问题需为1至160字')
  text=text.strip();normal=re.sub(r'[\W_]+','',text).casefold()
  if not normal:raise ValueError('问题不能只包含标点或空白')
  if normal in seen:
   if seen[normal]!=pid:raise ValueError('不同平台不能分发同一个问题，请按平台的资料线索分别改写后再创建')
   raise ValueError('同一平台存在重复问题，请合并后再创建')
  seen[normal]=pid;counts[pid]=counts.get(pid,0)+1
  if counts[pid]>5:raise ValueError('每个平台每批最多5条问题')
  if goal not in ('source_audit','discovery','brand_check'):raise ValueError('请选择资料渠道核查、自然发现或指名核对')
  hinted=brand_hint(text,profile)
  if goal=='discovery' and hinted:raise ValueError('自然发现问题不能包含本企业、品牌或官网，请改用行业或客户问题')
  if goal=='discovery' and re.search(r'site\s*:|(?:只|仅|优先|限定|指定)(?:搜索|检索|查找|参考|引用|核查|从|在|使用|看).{0,15}(?:公众号|视频号|微信|知乎|淘宝|官网|网站|文档|论文|信源|来源)',text,re.I):
   raise ValueError('自然发现问题不能限定资料来源，请改选来源核验')
  strategy=strategies[pid];source_directed=goal=='source_audit'
  if item.get('source_focus') and item['source_focus']!=strategy['focus']:raise ValueError('资料方向与平台策略不一致，请重新预览方案')
  prompt=make_prompt(text,mode)
  if source_directed:
   instruction=strategy.get('source_prompt') or ('优先核查与以下资料线索相关的公开来源：'+strategy.get('summary',strategy['focus']))
   prompt+='\n\n本次为资料渠道核查，查询方向：'+instruction+'\n仅引用实际可访问并核验的来源；无法访问的渠道请明确说明。来源偏好不代表平台的排他收录或推荐权重。'
  metrics={'brand_hint':hinted,'conversation_mode':conversation_mode,'context_contaminated':conversation_mode=='continue',
   'planning_mode':'per_platform','query_design':'platform_adapted','platform_strategy':pid,
   'strategy_version':catalog.get('version','2.0.0'),'goal':goal,'source_focus':strategy['focus'],'source_directed':source_directed}
  prepared.append({'platform':pid,'text':text,'goal':goal,'source_focus':strategy['focus'],'kind':str(item.get('kind','行业词'))[:30],
   'reason':str(item.get('reason',''))[:500],'prompt':prompt,'strategy_version':metrics['strategy_version'],'metrics':metrics})
 return prepared

def create_targeted_batch(items,mode,request_key,conversation_mode='fresh',_schedule=None):
 """One task per reviewed platform/question row; never expand a cross product."""
 if not isinstance(request_key,str) or not 1<=len(request_key)<=160:raise ValueError('请求编号无效，请刷新后重试')
 rows=prepare_targeted_items(items,mode,conversation_mode)
 signature=hashlib.sha256(json.dumps({'routing':'per_platform','items':[{k:r[k] for k in ('platform','text','goal')} for r in rows],
  'mode':mode,'conversation_mode':conversation_mode},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  existing=c.execute('SELECT * FROM batches WHERE request_key=?',(request_key,)).fetchone()
  if existing:
   if existing['body_hash']!=signature:raise ValueError('同一请求编号不能用于不同平台或问题，请重新预览')
   return {'batch_id':existing['id'],'created':0,'reused':True,'routing':'per_platform'}
  start,end=day_window();count=c.execute('SELECT count(*) FROM tasks WHERE created_at>=? AND created_at<?',(start,end)).fetchone()[0]
  if count+len(rows)>get_meta('settings')['daily_limit']:raise ValueError('超过今日任务上限，请减少平台问题或调整每日额度')
  channels={}
  for row in rows:
   pid=row['platform'];channel=get_meta('platform:'+pid)['channel']
   if channel=='api' and not PLATFORMS[pid]['api']:raise ValueError('该平台不支持API通道，请使用已配置的网页连接')
   channels[pid]=channel
  if _schedule:
   sid,day=_schedule
   if not c.execute('UPDATE platform_schedules SET last_day=?,updated_at=? WHERE id=? AND enabled=1 AND last_day<>?',(day,now(),sid,day)).rowcount:
    return {'batch_id':None,'created':0,'reused':False,'routing':'per_platform','skipped':True}
  bid=ident();stamp=now();c.execute('INSERT INTO batches VALUES(?,?,?,?)',(bid,request_key,signature,stamp))
  for row in rows:
   c.execute('INSERT INTO tasks(id,batch_id,platform,channel,mode,keyword,prompt,status,metrics,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
    (ident(),bid,row['platform'],channels[row['platform']],mode,row['text'],row['prompt'],'queued',json.dumps(row['metrics'],ensure_ascii=False),stamp,stamp))
 return {'batch_id':bid,'created':len(rows),'reused':False,'routing':'per_platform'}

def create_batch(keyword_texts,platforms,mode,request_key,conversation_mode='fresh'):
 keywords=list(dict.fromkeys(k.strip() for k in keyword_texts if k.strip()))
 if not keywords or len(keywords)>5 or any(len(k)>160 for k in keywords):raise ValueError('每批1至5个关键词，每个不超过160字')
 platforms=list(dict.fromkeys(platforms))
 if not platforms or any(pid not in PLATFORMS for pid in platforms):raise ValueError('请选择有效平台')
 if mode not in ('visibility','materials'):raise ValueError('任务模式无效')
 if conversation_mode not in ('fresh','continue'):raise ValueError('会话方式无效')
 signature=hashlib.sha256(json.dumps([keywords,platforms,mode]+([conversation_mode] if conversation_mode!='fresh' else []),ensure_ascii=False).encode()).hexdigest()
 prompts={keyword:make_prompt(keyword,mode) for keyword in keywords}
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  existing=c.execute('SELECT * FROM batches WHERE request_key=?',(request_key,)).fetchone()
  if existing:
   if existing['body_hash']!=signature:raise ValueError('同一请求编号不能用于不同内容')
   return {'batch_id':existing['id'],'created':0,'reused':True}
  start,end=day_window()
  count=c.execute('SELECT count(*) FROM tasks WHERE created_at>=? AND created_at<?',(start,end)).fetchone()[0]
  settings=get_meta('settings')
  if count+len(keywords)*len(platforms)>settings['daily_limit']:raise ValueError('超过今日任务上限，请减少关键词/平台或等待明天')
  bid=ident();stamp=now();c.execute('INSERT INTO batches VALUES(?,?,?,?)',(bid,request_key,signature,stamp))
  for keyword in keywords:
   for pid in platforms:
    channel=get_meta('platform:'+pid)['channel']
    if channel=='api' and not PLATFORMS[pid]['api']:raise ValueError('该平台没有配置API通道')
    metrics={'brand_hint':brand_hint(keyword,get_meta('profile')),'conversation_mode':conversation_mode,'context_contaminated':conversation_mode=='continue'}
    c.execute('INSERT INTO tasks(id,batch_id,platform,channel,mode,keyword,prompt,status,metrics,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
              (ident(),bid,pid,channel,mode,keyword,prompts[keyword],'queued',json.dumps(metrics),stamp,stamp))
 return {'batch_id':bid,'created':len(keywords)*len(platforms),'reused':False}

class Runner:
 def __init__(self):
  self.browser=BrowserBridge();self.jobs=[];self.active={};self.active_jobs={};self.phases={}
  self.next_by_platform={};self.restoring={};self._legacy_current=None
  self.heartbeat='';self.worker_error='';self.scheduler_error='';self.started=False
 @property
 def current(self):return next(iter(self.active),self._legacy_current)
 @current.setter
 def current(self,value):self._legacy_current=value
 @property
 def reconnecting(self):return next(iter(self.restoring.values()),None)
 @property
 def next_dispatch_at(self):return min(self.next_by_platform.values(),default=0)
 @next_dispatch_at.setter
 def next_dispatch_at(self,value):self.next_by_platform={pid:value for pid in PLATFORMS}
 def busy(self,pid):return pid in self.active.values() or pid in self.active_jobs and not self.active_jobs[pid].done()
 async def start(self):
  if self.jobs and any(not job.done() for job in self.jobs):return
  self.started=True
  self.jobs=[asyncio.create_task(self.loop(),name='junhe-dispatch'),asyncio.create_task(self.schedule_loop(),name='junhe-schedule')]
 async def stop(self):
  for job in self.jobs:job.cancel()
  await asyncio.gather(*self.jobs,return_exceptions=True)
  workers=list(self.active_jobs.values())
  for worker in workers:worker.cancel()
  await asyncio.gather(*workers,return_exceptions=True)
  await self.browser.close()
 async def execute(self,task):
  tid=task['id'];pid=task['platform'];self.active[tid]=pid;self.phases[tid]='preparing';sent=False;attempted=False;send_attempted=False
  began=time.time()
  def mark_attempt():
   nonlocal attempted,send_attempted
   attempted=True;send_attempted=True;self.phases[tid]='sending'
  def mark_sent():
   nonlocal sent
   mark_attempt();sent=True;self.phases[tid]='awaiting_answer'
   self.next_by_platform[pid]=time.time()+get_meta('settings')['interval_seconds']
   update_task(tid,sent_at=now(),note='已发送，正在自动获取回答；同一平台的后续任务会等本条结束')
  def fail(exc,status,message):
   with db() as c:stored=c.execute('SELECT metrics FROM tasks WHERE id=?',(tid,)).fetchone()
   error_metrics=json.loads(stored['metrics'])
   error_metrics['execution_error']={'type':type(exc).__name__,'phase':self.phases.get(tid,'unknown'),
      'send_attempted':send_attempted if task['channel']=='web' else attempted,'send_confirmed':sent,'retry_safe':task['channel']=='web' and not send_attempted,
      'stage_evidence_version':1}
   logging.getLogger(__name__).warning('Task execution blocked: platform=%s phase=%s type=%s send_attempted=%s send_confirmed=%s',
                                     pid,self.phases.get(tid,'unknown'),type(exc).__name__,send_attempted,sent)
   update_task(tid,status=status,note=message,metrics=json.dumps(error_metrics,ensure_ascii=False))
  def web_failure_status():return 'sent' if sent else 'uncertain' if send_attempted else 'waiting_setup'
  try:
   cfg=get_meta('platform:'+pid);settings=get_meta('settings')
   metrics=json.loads(task['metrics'])
   if task['channel']=='web':
    if self.browser.current_page(pid) is None and cfg['ready'] and self.browser.profile_saved(pid):
     self.restoring[tid]=pid;self.phases[tid]='restoring'
     update_task(tid,note='正在恢复本机保存的专用浏览器会话，尚未发送问题')
     try:await self.browser.restore_session(pid,cfg)
     finally:self.restoring.pop(tid,None)
    self.phases[tid]='preparing'
    cfg={**cfg,'conversation_mode':metrics.get('conversation_mode','fresh')}
    result=await self.browser.send(pid,cfg,task['prompt'],task['mode'],mark_sent,mark_attempt)
    verified,reason=automatic_verification(result,settings.get('auto_verify',True))
    metrics.pop('execution_error',None)
    metrics.update({'conversation_url':result.get('conversation_url',''),'source_links':result.get('links',[]),
                    'answer_matched_to_prompt':bool(result.get('matched')),'verification_method':'automatic_dom' if verified else 'unverified',
                    'verification_note':reason,'capture_evidence':{key:result.get(key) for key in ('association','done','busy','stable','later_turns')}})
    if verified:metrics.update(analyze(result['answer'],get_meta('profile')))
    update_task(tid,status='completed' if verified else 'needs_review' if result['answer'] else 'sent',
                reviewed=int(verified),answer=result['answer'],screenshot=result['screenshot'],
                note=reason if verified else reason+'；'+result['note'],metrics=json.dumps(metrics,ensure_ascii=False))
   else:
    history=None
    if metrics.get('conversation_mode')=='continue':
     with db() as c:
      previous=[dict(r) for r in c.execute("SELECT prompt,answer FROM tasks WHERE deleted_at IS NULL AND platform=? AND channel=? AND status='completed' AND id<>? ORDER BY created_at DESC,rowid DESC LIMIT 5",(pid,task['channel'],tid))]
     history=[]
     for row in reversed(previous):history.extend([{'role':'user','content':row['prompt'][:12000]},{'role':'assistant','content':row['answer'][:12000]}])
     history.append({'role':'user','content':task['prompt']})
    attempted=True;self.phases[tid]='sending'
    answer=await api_send(pid,cfg,task['prompt'],messages=history) if history else await api_send(pid,cfg,task['prompt'])
    mark_sent()
    self.next_by_platform[pid]=began+settings['interval_seconds']
    metrics.pop('execution_error',None);metrics.update(analyze(answer,get_meta('profile')));metrics['verification_method']='api_response'
    update_task(tid,status='completed',answer=answer,metrics=json.dumps(metrics,ensure_ascii=False),reviewed=1,
                note='API返回成功；API与消费端网页结果分开统计，未验证事实真实性或推荐排名')
  except NeedsSetup as exc:
   attempted=sent or send_attempted
   status=web_failure_status() if task['channel']=='web' else 'sent' if sent else 'waiting_setup'
   message=str(exc)
   if task['channel']=='web' and not send_attempted:message+='；问题尚未发送，检查页面后可继续此任务'
   elif not sent:message+='；已尝试触发发送，请先核查原会话，不自动重发'
   fail(exc,status,message)
  except httpx.TimeoutException as exc:
   fail(exc,web_failure_status() if task['channel']=='web' else 'uncertain',
        '网页准备响应超时，问题尚未发送；检查连接后可继续此任务' if task['channel']=='web' and not send_attempted else '请求响应超时，可能已收到请求；不自动重发')
  except httpx.RequestError as exc:
   fail(exc,web_failure_status() if task['channel']=='web' else 'uncertain',
        '网页准备连接失败，问题尚未发送；检查连接后可继续此任务' if task['channel']=='web' and not send_attempted else '网络请求结果未确认；不自动重发')
  except asyncio.CancelledError as exc:
   unsent=task['channel']=='web' and not send_attempted
   fail(exc,'waiting_setup' if unsent else 'interrupted','服务在准备页面时停止，问题尚未发送；可继续此任务' if unsent else '服务停止，结果可能不完整；请先核对平台，不自动重发');raise
  except Exception as exc:
   message=str(exc) if isinstance(exc,RuntimeError) and str(exc).startswith(('平台返回','平台响应','平台未返回')) else '执行未完成，请检查连接、控件或网络；未自动重发'
   if task['channel']=='web' and not send_attempted:
    message=('页面准备超时' if type(exc).__name__=='TimeoutError' else '页面准备未完成')+'，问题尚未发送；请检查窗口、登录与控件后继续此任务'
   elif type(exc).__name__=='TimeoutError':message='页面操作超时；'+('已取得发送确认，回答采集未完成' if sent else '已尝试触发发送但没有取得确认，请先核查平台会话')+'；未自动重发'
   fail(exc,web_failure_status() if task['channel']=='web' else 'failed',message)
  finally:
   if attempted:self.next_by_platform[pid]=max(self.next_by_platform.get(pid,0),began+get_meta('settings')['interval_seconds'])
   self.active.pop(tid,None);self.restoring.pop(tid,None);self.phases.pop(tid,None)
  return attempted
 async def _run_one(self,task):
  pid=task['platform']
  try:await self.execute(task)
  finally:self.active_jobs.pop(pid,None)
 def block_unready(self):
  configs={pid:get_meta('platform:'+pid) for pid in PLATFORMS}
  with db() as c:
   c.execute('BEGIN IMMEDIATE')
   rows=c.execute("SELECT id,platform,mode,metrics FROM tasks WHERE deleted_at IS NULL AND status='queued' AND channel='web'").fetchall()
   changed=0
   for row in rows:
    pid=row['platform'];cfg=configs[pid];page=self.browser.current_page(pid);reason=''
    if page is None and not (cfg['ready'] and self.browser.profile_saved(pid)):reason=f"{PLATFORMS[pid]['name']}专用窗口未连接。请连接并本人登录后继续此任务。"
    elif not cfg['ready']:reason='尚未允许自动发送，请检查控件并保存配置后继续。'
    elif not cfg['composer'] or not (cfg['send_button'] or cfg['send_key'] in ('Enter','Control+Enter')):reason='输入框或发送方式尚未配置，请检查后继续。'
    elif row['mode']=='visibility' and json.loads(row['metrics']).get('conversation_mode','fresh')=='fresh' and not cfg['new_chat_selector']:reason='独立检查缺少新对话入口，请配置后继续。'
    if reason:changed+=c.execute("UPDATE tasks SET status='waiting_setup',note=?,updated_at=? WHERE id=? AND deleted_at IS NULL AND status='queued'",(reason,now(),row['id'])).rowcount
  return changed
 def snapshot(self):
  with db() as c:
   counts={r['status']:r['count'] for r in c.execute('SELECT status,count(*) AS count FROM tasks WHERE deleted_at IS NULL GROUP BY status')}
   rows=[dict(r) for r in c.execute("SELECT id,platform FROM tasks WHERE deleted_at IS NULL AND status='queued' ORDER BY created_at,rowid")]
  positions={};platform_counts={};cooldowns={pid:max(0,int(t-time.time()+.999)) for pid,t in self.next_by_platform.items()}
  for row in rows:
   pid=row['platform'];platform_counts[pid]=platform_counts.get(pid,0)+1;positions[row['id']]=platform_counts[pid]
  settings=get_meta('settings');healthy=bool(self.jobs and not self.jobs[0].done())
  scheduler_alive=bool(len(self.jobs)>1 and not self.jobs[1].done())
  scheduler_stopped=len(self.jobs)>1 and not scheduler_alive
  scheduler_error=self.scheduler_error or ('每日计划执行器已停止，请重启本机后台。' if scheduler_stopped else '')
  waits=[cooldowns.get(r['platform'],0) for r in rows if not self.busy(r['platform'])]
  cooldown=min(waits,default=0)
  if not self.started:phase='not_started'
  elif not healthy or scheduler_stopped:phase='error'
  elif settings['paused']:phase='paused'
  elif self.active:phase='running'
  elif rows and cooldown:phase='cooldown'
  elif rows:phase='dispatching'
  else:phase='idle'
  return {'state':phase,'worker_alive':healthy,'scheduler_alive':scheduler_alive,'current_task':self.current,'reconnecting_platform':self.reconnecting,
          'active':[{'id':tid,'platform':pid,'phase':self.phases.get(tid,'sending')} for tid,pid in self.active.items()],
          'active_count':len(self.active),'parallel_limit':settings.get('parallel_platforms',6),
          'queued':len(rows),'waiting_setup':counts.get('waiting_setup',0),'positions':positions,
          'platform_cooldowns':cooldowns,'cooldown_seconds':cooldown,
          'next_dispatch_at':datetime.fromtimestamp(self.next_dispatch_at,timezone.utc).isoformat() if self.next_dispatch_at else '',
          'heartbeat':self.heartbeat,'error':'；'.join(message for message in (self.worker_error,scheduler_error) if message)}
 async def tick(self):
  self.heartbeat=now();settings=get_meta('settings')
  if settings['paused']:return 1
  self.block_unready();capacity=settings.get('parallel_platforms',6)-len(self.active_jobs)
  claimed=[];busy=set(self.active.values())|set(self.active_jobs)
  with db() as c:
   c.execute('BEGIN IMMEDIATE')
   rows=c.execute("SELECT * FROM tasks WHERE deleted_at IS NULL AND status='queued' ORDER BY created_at,rowid").fetchall()
   for row in rows:
    if len(claimed)>=capacity:break
    pid=row['platform']
    if pid in busy or self.next_by_platform.get(pid,0)>time.time():continue
    if c.execute("UPDATE tasks SET status='running',updated_at=? WHERE id=? AND deleted_at IS NULL AND status='queued'",(now(),row['id'])).rowcount:
     claimed.append(dict(row));busy.add(pid)
  for task in claimed:
   self.active[task['id']]=task['platform'];self.phases[task['id']]='preparing'
   self.active_jobs[task['platform']]=asyncio.create_task(self._run_one(task),name='junhe-'+task['platform'])
  await asyncio.sleep(0)
  return .2 if claimed else 1
 async def loop(self):
  while True:
   try:
    delay=await self.tick();self.worker_error='';await asyncio.sleep(delay)
   except asyncio.CancelledError:raise
   except Exception as exc:
    self.worker_error='后台调度暂时异常，将自动重试；未确认的请求不会自动重发。'
    logging.getLogger(__name__).warning('Queue tick failed: %s',type(exc).__name__);await asyncio.sleep(3)
 async def schedule_tick(self):
  current=datetime.now(CST);today=current.date().isoformat();clock=current.strftime('%H:%M')
  with db() as c:rows=[dict(r) for r in c.execute('SELECT * FROM schedules WHERE enabled=1 AND last_day<>?',(today,))]
  for row in rows:
   if row['time']>clock:continue
   with db() as c:
    c.execute('BEGIN IMMEDIATE')
    if not c.execute('UPDATE schedules SET last_day=? WHERE id=? AND last_day<>?',(today,row['id'],today)).rowcount:continue
    ids=json.loads(row['keyword_ids']);keywords=[r['text'] for r in c.execute('SELECT id,text FROM keywords') if r['id'] in ids]
   try:create_batch(keywords,json.loads(row['platforms']),row['mode'],f"schedule:{row['id']}:{today}")
   except ValueError as exc:
    from storage import set_meta
    set_meta('scheduler_notice',{'time':now(),'message':str(exc)})
  from platform_planner import due_schedules
  for row in due_schedules(current):
   try:create_targeted_batch(row['items'],row['mode'],f"platform-schedule:{row['id']}:{today}",row.get('conversation_mode','fresh'),_schedule=(row['id'],today))
   except ValueError as exc:
    from storage import set_meta
    set_meta('scheduler_notice',{'time':now(),'message':str(exc)})
 async def schedule_loop(self):
  while True:
   errors=[]
   try:
    from keyword_planner import daily_tick
    daily_tick()
   except asyncio.CancelledError:raise
   except Exception as exc:
    errors.append('每日关键词整理暂时异常，将在下一轮重试')
    logging.getLogger(__name__).warning('Local keyword generation failed; will retry next tick: %s',type(exc).__name__)
   try:
    if not get_meta('settings')['paused']:await self.schedule_tick()
   except asyncio.CancelledError:raise
   except Exception as exc:
    errors.append('每日计划执行暂时异常，将在下一轮重试；已创建的任务不会重复创建')
    logging.getLogger(__name__).warning('Schedule tick failed; will retry next tick: %s',type(exc).__name__)
   self.scheduler_error='；'.join(errors)
   await asyncio.sleep(15)
