"""Recoverable record deletion. Queued and running tasks cannot be archived."""
import json
from datetime import datetime,timedelta,timezone,time
from engine import CST
from storage import db,ident,now
from queries import task_filter

def preview(filters,ids=None,before=None):
 where,args=task_filter(**filters)
 if before:
  cutoff=datetime.combine(before+timedelta(days=1),time(),CST).astimezone(timezone.utc).isoformat(timespec='seconds')
  where+=' AND created_at<?';args.append(cutoff)
 if ids:
  where+=' AND id IN ('+','.join('?' for _ in ids)+')';args.extend(ids)
 with db() as c:
  rows=c.execute('SELECT id,status FROM tasks'+where,args).fetchall()
  eligible=[r['id'] for r in rows if r['status'] not in ('queued','running')]
  token=ident();expires=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(timespec='seconds')
  c.execute('INSERT INTO record_delete_previews VALUES(?,?,?,?,NULL)',(token,json.dumps(eligible),now(),expires))
 return {'token':token,'count':len(eligible),'skipped_active':len(rows)-len(eligible),'matched':len(rows),'expires_at':expires}

def commit(token):
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  row=c.execute('SELECT * FROM record_delete_previews WHERE token=?',(token,)).fetchone()
  if not row:raise ValueError('删除预览不存在，请重新预览')
  ids=json.loads(row['task_ids'])
  if row['committed_at']:return {'deleted':len(ids),'reused':True,'batch':token}
  if row['expires_at']<now():raise ValueError('预览已超过10分钟，请重新预览')
  if not ids:raise ValueError('没有可删除的记录')
  eligible=[]
  for offset in range(0,len(ids),400):
   group=ids[offset:offset+400]
   eligible.extend(c.execute('SELECT id,status,deleted_at FROM tasks WHERE id IN ('+','.join('?' for _ in group)+')',group).fetchall())
  if len(eligible)!=len(ids) or any(r['deleted_at'] or r['status'] in ('queued','running') for r in eligible):
   raise ValueError('记录状态已变化，请重新预览后再删除')
  stamp=now()
  c.executemany('UPDATE tasks SET deleted_at=?,deletion_batch=? WHERE id=?',[(stamp,token,tid) for tid in ids])
  c.execute('UPDATE record_delete_previews SET committed_at=? WHERE token=?',(stamp,token))
 return {'deleted':len(ids),'reused':False,'batch':token}

def trash(page=1,page_size=20):
 with db() as c:
  total=c.execute('SELECT count(*) FROM tasks WHERE deleted_at IS NOT NULL').fetchone()[0]
  pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
  rows=[dict(r) for r in c.execute('SELECT id,platform,keyword,status,deleted_at FROM tasks WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC,rowid DESC LIMIT ? OFFSET ?',(page_size,(page-1)*page_size))]
 return {'items':rows,'total':total,'page':page,'pages':pages}

def restore(ids):
 with db() as c:
  c.execute('BEGIN IMMEDIATE');restored=0
  for tid in dict.fromkeys(ids):
   restored+=c.execute("""UPDATE tasks SET deleted_at=NULL,deletion_batch=NULL,
    status=CASE WHEN status IN ('queued','running') THEN 'waiting_setup' ELSE status END,
    note=CASE WHEN status IN ('queued','running') THEN '恢复时检测到原任务处于排队或执行中，已停止自动执行；请先核对平台会话，确认后再手动继续此任务' ELSE note END,
    updated_at=CASE WHEN status IN ('queued','running') THEN ? ELSE updated_at END
    WHERE id=? AND deleted_at IS NOT NULL""",(now(),tid)).rowcount
 return {'restored':restored}
