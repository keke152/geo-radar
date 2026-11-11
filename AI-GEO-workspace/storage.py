import json,sqlite3,uuid
from contextlib import contextmanager
from datetime import datetime,timezone
from config import HOME,DEFAULT_PROFILE,DEFAULT_SETTINGS,PLATFORMS,default_platform

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def ident():return uuid.uuid4().hex
@contextmanager
def db():
 connection=sqlite3.connect(HOME/'workspace.sqlite3',timeout=20)
 connection.row_factory=sqlite3.Row
 connection.execute('PRAGMA journal_mode=WAL')
 try:
  yield connection
  connection.commit()
 except Exception:
  connection.rollback();raise
 finally:connection.close()

def init():
 with db() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL,source TEXT NOT NULL,approved INTEGER NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS keywords(id TEXT PRIMARY KEY,text TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE,body_hash TEXT NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,batch_id TEXT NOT NULL,platform TEXT NOT NULL,channel TEXT NOT NULL,mode TEXT NOT NULL,keyword TEXT NOT NULL,prompt TEXT NOT NULL,status TEXT NOT NULL,answer TEXT NOT NULL DEFAULT '',note TEXT NOT NULL DEFAULT '',screenshot TEXT NOT NULL DEFAULT '',metrics TEXT NOT NULL DEFAULT '{}',reviewed INTEGER NOT NULL DEFAULT 0,sent_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS schedules(id TEXT PRIMARY KEY,time TEXT NOT NULL,keyword_ids TEXT NOT NULL,platforms TEXT NOT NULL,mode TEXT NOT NULL,enabled INTEGER NOT NULL,last_day TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS keyword_candidates(id TEXT PRIMARY KEY,day TEXT NOT NULL,text TEXT NOT NULL,normalized TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,score INTEGER NOT NULL,reason TEXT NOT NULL,source TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS keyword_generation_runs(day TEXT PRIMARY KEY,count INTEGER NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS platform_keywords(id TEXT PRIMARY KEY,platform TEXT NOT NULL,text TEXT NOT NULL,normalized TEXT NOT NULL,kind TEXT NOT NULL,goal TEXT NOT NULL,source_focus TEXT NOT NULL,reason TEXT NOT NULL,strategy_version TEXT NOT NULL,origin TEXT NOT NULL DEFAULT 'manual',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(platform,normalized,goal));
  CREATE INDEX IF NOT EXISTS idx_platform_keywords_platform ON platform_keywords(platform,created_at);
  CREATE TABLE IF NOT EXISTS platform_schedules(id TEXT PRIMARY KEY,time TEXT NOT NULL,items TEXT NOT NULL,mode TEXT NOT NULL,conversation_mode TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0,last_day TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS platform_keyword_generation_runs(day TEXT PRIMARY KEY,count INTEGER NOT NULL,strategy_version TEXT NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS record_delete_previews(token TEXT PRIMARY KEY,task_ids TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,committed_at TEXT);
  ''')
  columns={r['name'] for r in c.execute('PRAGMA table_info(tasks)')}
  for column in ('deleted_at','deletion_batch'):
   if column not in columns:c.execute('ALTER TABLE tasks ADD COLUMN '+column+' TEXT')
  first_boot=not c.execute("SELECT 1 FROM meta WHERE key='profile'").fetchone()
  c.execute("INSERT OR IGNORE INTO meta VALUES('profile',?)",(json.dumps(DEFAULT_PROFILE,ensure_ascii=False),))
  profile=json.loads(c.execute("SELECT value FROM meta WHERE key='profile'").fetchone()['value'])
  changed=False
  for key in ('brand_name','brand_aliases','brand_relation'):
   if key not in profile:profile[key]=DEFAULT_PROFILE[key];changed=True
  if changed:c.execute("UPDATE meta SET value=? WHERE key='profile'",(json.dumps(profile,ensure_ascii=False),))
  c.execute("INSERT OR IGNORE INTO meta VALUES('settings',?)",(json.dumps(DEFAULT_SETTINGS),))
  c.execute("INSERT OR IGNORE INTO meta VALUES('keyword_plan',?)",(json.dumps({'enabled':False,'time':'09:00','count':10}),))
  # Preserve the old shared pools/history. Their schedules need explicit review
  # because v2 routes an independently worded question to each platform.
  if not c.execute("SELECT 1 FROM meta WHERE key='platform_planning_v2_migration'").fetchone():
   legacy_ids=[row['id'] for row in c.execute('SELECT id FROM schedules WHERE enabled=1')]
   if legacy_ids:c.execute('UPDATE schedules SET enabled=0 WHERE enabled=1')
   migration={'version':'2.0.0','legacy_paused':len(legacy_ids),'schedule_ids':legacy_ids,'time':now(),
              'message':f'分平台方案已启用；已暂停 {len(legacy_ids)} 个旧版共享计划。历史问题与回答保留，请按各平台独立编辑后建立新计划。'}
   c.execute('INSERT INTO meta VALUES(?,?)',('platform_planning_v2_migration',json.dumps(migration,ensure_ascii=False)))
   if legacy_ids:c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('scheduler_notice',json.dumps(migration,ensure_ascii=False)))
  settings=json.loads(c.execute("SELECT value FROM meta WHERE key='settings'").fetchone()['value'])
  if any(key not in settings for key in ('parallel_platforms','auto_verify')):
   for key in ('parallel_platforms','auto_verify'):settings.setdefault(key,DEFAULT_SETTINGS[key])
   c.execute("UPDATE meta SET value=? WHERE key='settings'",(json.dumps(settings),))
  if settings.get('parallel_platforms',6)>len(PLATFORMS):
   settings['parallel_platforms']=len(PLATFORMS)
   c.execute("UPDATE meta SET value=? WHERE key='settings'",(json.dumps(settings),))
  for retired in ('chatgpt','gemini','grok','claude_code'):
   c.execute('DELETE FROM meta WHERE key=?',('platform:'+retired,))
   c.execute("UPDATE tasks SET status='cancelled',note='该平台已移除，未发送任务已停止；历史记录保留',updated_at=? WHERE platform=? AND status IN ('queued','waiting_setup')",(now(),retired))
  for schedule in c.execute('SELECT id,platforms,enabled FROM schedules').fetchall():
   original=json.loads(schedule['platforms']);active=[pid for pid in original if pid in PLATFORMS]
   if original!=active:c.execute('UPDATE schedules SET platforms=?,enabled=? WHERE id=?',(json.dumps(active),int(bool(active) and schedule['enabled']),schedule['id']))
  for pid in PLATFORMS:c.execute('INSERT OR IGNORE INTO meta VALUES(?,?)',('platform:'+pid,json.dumps(default_platform(pid)),))
  if first_boot and not c.execute('SELECT 1 FROM keywords LIMIT 1').fetchone():
   for text,kind in [('广州菌和生物科技有限公司官网','品牌词'),('菌和生物 益生菌食品','品牌词'),('广州益生菌食品企业有哪些','行业词'),('益生菌食品经销合作怎么选择','招商词'),('益生菌食品代理需要了解哪些资质','招商词'),('益生菌食品门店合作需要了解什么','场景词')]:
    c.execute('INSERT INTO keywords VALUES(?,?,?,?)',(ident(),text,kind,now()))
  if first_boot and not c.execute('SELECT 1 FROM documents LIMIT 1').fetchone():
   for title,body,source,approved in [
    ('已确认的企业基本信息',DEFAULT_PROFILE['public_intro'],'用户确认：2026-11-02',1),
    ('品牌与产品目录（待核验）','招商课件出现“广微·益森日纪”品牌，产品目录出现畅青、畅乐、畅动、畅护、畅润、畅悦等益生菌名称。请核对产品标签及广州菌和生物科技有限公司与该品牌的授权关系后，再允许对外发送。','招商课件第16、23–29页',0),
    ('招商合作对象摘要（待核验）','招商部分涉及经销商、代理商、门店合作、健康小屋，以及活动、素材、培训和直播支持。具体合作政策、价格、授权范围需要公司确认。','招商课件第39–48页',0),
    ('课件核验清单（不自动发送）','第38页出现旁门医疗、www.pangmenzd.vip、0451-1234567、design@gmail.com及金钟道88号，疑似模板遗留，已排除出企业公开资料。课件中的研究所、国企、CMA/CNAS、专利、临床、疾病及功效表述尚未核验，不能据此声称广州菌和生物拥有对应资质或疗效。','招商课件第4、8–12、16、19–35、38页',0)]:
    c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',(ident(),title,body,source,approved,now()))
  # Never silently resend requests that might have reached a provider before a crash.
  c.execute("UPDATE tasks SET status='interrupted',note='服务重启，执行结果不确定；请先核对平台会话再决定是否创建新任务',updated_at=? WHERE status='running'",(now(),))

def get_meta(key):
 with db() as c:return json.loads(c.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()['value'])
def set_meta(key,value):
 with db() as c:c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))
def records(table):
 if table not in {'keywords','documents','tasks','schedules'}:raise ValueError('invalid table')
 with db() as c:return [dict(row) for row in c.execute(f'SELECT * FROM {table}'+(' WHERE deleted_at IS NULL' if table=='tasks' else '')+' ORDER BY created_at DESC')]
def update_task(tid,**fields):
 allowed={'status','answer','note','screenshot','metrics','reviewed','sent_at'}
 if not set(fields)<=allowed:raise ValueError('invalid fields')
 fields['updated_at']=now()
 with db() as c:c.execute('UPDATE tasks SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),tid))
