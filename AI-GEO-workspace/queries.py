"""Shared record filters and quota information for UI and exports."""
import json
from datetime import datetime
from config import PLATFORMS
from engine import day_window, CST
from storage import db, get_meta

STATUSES = {'queued', 'running', 'waiting_setup', 'needs_review', 'sent', 'completed',
            'failed', 'interrupted', 'uncertain', 'cancelled'}
TASK_GROUPS={'all':(), 'running':('queued','running'),
             'attention':('waiting_setup','needs_review','sent','failed','uncertain','interrupted'),
             'completed':('completed',)}


def task_filter(q='', status='', platform='', channel='', mode='',group='all'):
    if group not in TASK_GROUPS:raise ValueError('任务分组无效')
    if status and status not in STATUSES:
        raise ValueError('任务状态无效')
    if platform and platform not in PLATFORMS:
        raise ValueError('平台无效')
    if channel and channel not in ('web', 'api'):
        raise ValueError('通道无效')
    if mode and mode not in ('visibility', 'materials'):
        raise ValueError('模式无效')
    parts, args = ['deleted_at IS NULL','platform IN ('+','.join('?' for _ in PLATFORMS)+')'], list(PLATFORMS)
    if TASK_GROUPS[group]:
        parts.append('status IN ('+','.join('?' for _ in TASK_GROUPS[group])+')')
        args.extend(TASK_GROUPS[group])
    for key, value in [('status', status), ('platform', platform), ('channel', channel), ('mode', mode)]:
        if value:
            parts.append(key + '=?')
            args.append(value)
    if q.strip():
        term = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        parts.append("keyword LIKE ? ESCAPE '\\'")
        args.append('%' + term + '%')
    return (' WHERE ' + ' AND '.join(parts)) if parts else '', args


def query_tasks(q='', status='', platform='', channel='', mode='', page=1, page_size=20, export=False,group='all'):
    where, args = task_filter(q, status, platform, channel, mode,group)
    with db() as c:
        total = c.execute('SELECT count(*) FROM tasks' + where, args).fetchone()[0]
        pages = max(1, (total + page_size - 1) // page_size)
        current = min(page, pages)
        sql = 'SELECT * FROM tasks' + where + ' ORDER BY created_at DESC,rowid DESC'
        if not export:
            sql += ' LIMIT ? OFFSET ?'
            args = [*args, page_size, (current - 1) * page_size]
        rows = [dict(row) for row in c.execute(sql, args)]
    if export:
        return rows
    items = []
    for row in rows:
        items.append({**{k: v for k, v in row.items() if k not in ('prompt', 'answer')},
                      'answer_preview': row['answer'][:120], 'metrics': json.loads(row['metrics'])})
    return {'items': items, 'total': total, 'page': current, 'pages': pages, 'page_size': page_size}


def daily_budget():
    start, end = day_window()
    with db() as c:
        used = c.execute('SELECT count(*) FROM tasks WHERE created_at>=? AND created_at<?', (start, end)).fetchone()[0]
    limit = get_meta('settings')['daily_limit']
    return {'used': used, 'limit': limit, 'remaining': max(0, limit - used),
            'resets_at': datetime.fromisoformat(end).astimezone(CST).isoformat(),
            'note': '按北京时间当天创建的任务计数；1个关键词×1个平台为1条，取消任务不退回创建额度。'}
