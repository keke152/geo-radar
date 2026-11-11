"""Local, source-aware question planning with explicit per-platform routing.

This module never opens provider pages or calls a model. A platform's focus is
an editable planning hypothesis, not an assertion about search ranking.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone

from config import PLATFORMS, ROOT
from domain import brand_hint
from storage import db, get_meta, ident, now, records

CST = timezone(timedelta(hours=8))
GOALS = {'source_audit': '来源核验', 'discovery': '自然发现', 'brand_check': '品牌信息核对'}
KINDS = {'source_audit': '来源核验词', 'discovery': '行业词', 'brand_check': '品牌词'}
ITEM_FIELDS = ('platform', 'text', 'kind', 'goal', 'source_focus', 'reason', 'strategy_version')
TIME_PATTERN = re.compile(r'(?:[01]\d|2[0-3]):[0-5]\d')
DAILY_TOPICS = (
    '品牌运营方与实际生产主体', '产品标签和菌株标识', '配料与包装规格', '储存条件与运输条件',
    '保质期与门店库存周转', '批次检测材料的可核验性', '产品追溯与售后责任',
    '品牌授权链条', '经销合同中的退换货条款', '首次采购与试销安排', '区域合作边界',
    '起订量与补货周期', '供货责任和交付时效', '宣传素材与公开证据', '招商费用与结算方式',
    '门店上架资料准备', '培训与运营支持的具体范围', '线上与线下渠道的合作条件',
    '供应商准入材料', '合作终止与剩余库存处理', '客服资料与产品说明的一致性',
    '独立来源与企业自述的区分', '公开信息中的时间与适用范围', '试运营后的合作复盘',
)


def normalize(text):
    return re.sub(r'[\W_]+', '', text).casefold()


def catalog():
    try:
        data = json.loads((ROOT / 'platform_strategy_catalog.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('平台策略资料暂不可用，请检查本地平台策略文件') from exc
    if {item.get('id') for item in data.get('items', [])} != set(PLATFORMS):
        raise ValueError('平台策略与当前支持的平台不一致')
    return data


def strategies():
    data = catalog()
    return {**data, 'goals': [{'id': key, 'label': label} for key, label in GOALS.items()],
            'note': '已核验能力与选题策略分别说明。来源侧重不等于独占来源，也不是品牌推荐权重。'}


def _platforms(values):
    if not isinstance(values, list) or not values or len(values) > len(PLATFORMS):
        raise ValueError('请选择 1 至 6 个平台')
    if any(pid not in PLATFORMS for pid in values):
        raise ValueError('包含不支持的平台')
    if len(set(values)) != len(values):
        raise ValueError('平台不能重复选择')
    return values


def _goal(value):
    if value not in GOALS:
        raise ValueError('请选择来源核验、自然发现或品牌信息核对')
    return value


def _text(value, label, limit, required=True):
    if not isinstance(value, str):
        raise ValueError(label + '必须是文字')
    value = value.strip()
    if (required and not normalize(value)) or len(value) > limit:
        raise ValueError(f'{label}须为 1 至 {limit} 字的有效文字' if required else f'{label}不能超过 {limit} 字')
    return value


def _catalog_map():
    data = catalog()
    return data, {item['id']: item for item in data['items']}


def normalize_item(value, data=None, mapping=None):
    if not isinstance(value, dict):
        raise ValueError('每条关键词须独立填写平台与问题')
    if data is None or mapping is None:
        data, mapping = _catalog_map()
    pid = value.get('platform')
    _platforms([pid])
    goal = _goal(value.get('goal', 'source_audit'))
    text = _text(value.get('text', ''), '问题', 160)
    if goal == 'discovery' and brand_hint(text, get_meta('profile')):
        raise ValueError('自然发现问题不能带本企业、品牌或官网提示；请改为品牌信息核对')
    strategy = mapping[pid]
    focus = strategy['focus']
    if value.get('source_focus') and value['source_focus'] != focus:
        raise ValueError('来源侧重与该平台策略不一致，请重新预览方案')
    return {'platform': pid, 'text': text, 'kind': _text(value.get('kind') or KINDS[goal], '词类', 30),
            'goal': goal, 'source_focus': focus,
            'reason': _text(value.get('reason') or strategy.get('strategy_hypothesis') or strategy['summary'], '选题理由', 1000),
            'strategy_version': data['version']}


def _no_broadcast(items):
    by_text = {}
    for item in items:
        key = normalize(item['text'])
        if key in by_text and by_text[key] != item['platform']:
            raise ValueError('请为每个平台独立编辑问题，不能将同一问题统一分发')
        by_text[key] = item['platform']


def _draft_items(topic, platforms, goal, count_per_platform):
    topic = _text(topic, '选题', 160)
    platforms = _platforms(platforms)
    goal = _goal(goal)
    if not isinstance(count_per_platform, int) or isinstance(count_per_platform, bool) or not 1 <= count_per_platform <= 5:
        raise ValueError('每个平台请选择 1 至 5 个问题')
    profile = get_meta('profile')
    if goal == 'discovery' and brand_hint(topic, profile):
        raise ValueError('自然发现选题不能带企业、品牌或官网提示，请改选品牌信息核对')
    data, mapping = _catalog_map()
    values = {'topic': topic, 'business': profile['business'].strip(), 'brand': profile.get('brand_name') or profile['company_name'],
              'company': profile['company_name'], 'domain': profile['domain']}
    items = []
    for pid in platforms:
        strategy = mapping[pid]
        templates = strategy.get('templates', {}).get(goal, [])
        if len(templates) < count_per_platform:
            raise ValueError(f'{PLATFORMS[pid]["name"]}的有效选题不足，请减少数量')
        for template in templates[:count_per_platform]:
            try:
                text = template.format(**values)
            except (KeyError, ValueError) as exc:
                raise ValueError('本地问题模板格式有误') from exc
            if len(text) > 160:
                raise ValueError('主题展开后的问题超过160字，请缩短主题，或在平台词库单独填写完整问题')
            items.append(normalize_item({'platform': pid, 'text': text, 'goal': goal}, data, mapping))
    _no_broadcast(items)
    return topic, items


def preview_plan(topic, platforms, goal='source_audit', count_per_platform=1):
    topic, items = _draft_items(topic, platforms, goal, count_per_platform)
    # Engine owns final prompt construction/validation. Import locally to keep
    # schedule integration independent of module import order.
    from engine import prepare_targeted_items
    prepared = prepare_targeted_items(items, 'visibility', 'fresh')
    return {'topic': topic, 'goal': goal, 'items': [{key: item[key] for key in (*ITEM_FIELDS, 'prompt')} for item in prepared],
            'count': len(items), 'routing': 'per_platform',
            'note': '本地草案，尚未保存或发送。每个平台使用独立问题；来源核验不计入自然发现率。'}


def list_keywords(platform=''):
    if platform:
        _platforms([platform])
    with db() as c:
        query = 'SELECT * FROM platform_keywords' + (' WHERE platform=?' if platform else '') + ' ORDER BY created_at DESC,id'
        rows = [dict(row) for row in c.execute(query, (platform,) if platform else ())]
        last = c.execute('SELECT * FROM platform_keyword_generation_runs ORDER BY day DESC LIMIT 1').fetchone()
    return {'items': rows, 'count': len(rows), 'legacy_items': records('keywords'),
            'settings': get_meta('keyword_plan'), 'last_run': dict(last) if last else None,
            'note': '关键词按平台保存。旧版共享关键词仅作参考，不会自动统一分发。'}


def _insert_keyword(c, item, origin='manual'):
    existing = c.execute('SELECT * FROM platform_keywords WHERE platform=? AND normalized=? AND goal=?',
                         (item['platform'], normalize(item['text']), item['goal'])).fetchone()
    if existing:
        return dict(existing), False
    timestamp = now()
    row = {'id': ident(), **item, 'normalized': normalize(item['text']), 'origin': origin,
           'created_at': timestamp, 'updated_at': timestamp}
    c.execute('INSERT INTO platform_keywords(' + ','.join(row) + ') VALUES(' + ','.join('?' for _ in row) + ')', tuple(row.values()))
    return row, True


def save_keyword(value):
    item = normalize_item(value)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row, created = _insert_keyword(c, item)
    return {'id': row['id'], 'item': row, 'created': created,
            'message': '已保存该平台关键词，没有发送问题' if created else '该平台已保存相同关键词，未重复添加'}


def update_keyword(kid, value):
    item = normalize_item(value)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        existing = c.execute('SELECT id FROM platform_keywords WHERE id=?', (kid,)).fetchone()
        if not existing:
            raise KeyError('关键词不存在')
        duplicate = c.execute('SELECT id FROM platform_keywords WHERE platform=? AND normalized=? AND goal=? AND id<>?',
                              (item['platform'], normalize(item['text']), item['goal'], kid)).fetchone()
        if duplicate:
            raise ValueError('该平台已有相同问题与目标，请修改问题或使用已有记录')
        fields = {**item, 'normalized': normalize(item['text']), 'updated_at': now()}
        c.execute('UPDATE platform_keywords SET ' + ','.join(key + '=?' for key in fields) + ' WHERE id=?', (*fields.values(), kid))
    return {'id': kid, 'message': '关键词已更新；既有任务与计划的问题快照保留'}


def delete_keyword(kid):
    with db() as c:
        changed = c.execute('DELETE FROM platform_keywords WHERE id=?', (kid,)).rowcount
    if not changed:
        raise KeyError('关键词不存在')
    return {'message': '关键词已删除，历史回答与已保存计划保留'}


def generate_keywords(topic, platforms, goal='source_audit', count_per_platform=1):
    topic, items = _draft_items(topic, platforms, goal, count_per_platform)
    rows, created = [], 0
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        for item in items:
            row, added = _insert_keyword(c, item, 'preview')
            rows.append(row)
            created += int(added)
    return {'topic': topic, 'goal': goal, 'items': rows, 'count': len(rows), 'created': created,
            'reused': len(rows) - created, 'routing': 'per_platform',
            'message': f'已保存 {created} 条分平台关键词，复用 {len(rows) - created} 条；没有创建或发送任务'}


def generate_daily(day=None):
    """Generate a balanced local pool, with one atomic generation per CST day."""
    settings = get_meta('keyword_plan')
    day = day or datetime.now(CST).date().isoformat()
    try:
        date.fromisoformat(day)
    except (TypeError, ValueError) as exc:
        raise ValueError('生成日期无效') from exc
    # The scheduler calls every 15 seconds. Avoid rebuilding the local pool once
    # this day's run is complete; the write transaction below rechecks races.
    with db() as c:
        previous = c.execute('SELECT count FROM platform_keyword_generation_runs WHERE day=?', (day,)).fetchone()
    if previous:
        return {'created': 0, 'already_generated': True, 'day': day, 'previous_count': previous['count'], 'routing': 'per_platform'}
    count = settings.get('count', 10)
    platforms = _platforms(settings.get('platforms') or list(PLATFORMS))
    goal = _goal(settings.get('goal', 'source_audit'))
    data = catalog()
    profile = get_meta('profile')
    business = _text(profile['business'], '主营业务', 50)
    pools = {pid: [] for pid in platforms}
    for detail in DAILY_TOPICS:
        _, items = _draft_items(business + '：' + detail, platforms, goal, 5)
        for item in items:
            pools[item['platform']].append(item)
    created_rows = []
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        previous = c.execute('SELECT count FROM platform_keyword_generation_runs WHERE day=?', (day,)).fetchone()
        if previous:
            return {'created': 0, 'already_generated': True, 'day': day, 'previous_count': previous['count'], 'routing': 'per_platform'}
        known = {(row['platform'], row['normalized'], row['goal']) for row in c.execute('SELECT platform,normalized,goal FROM platform_keywords')}
        for pid, pool in pools.items():
            unique = {normalize(item['text']): item for item in pool}
            pools[pid] = [item for key, item in unique.items() if (pid, key, goal) not in known]
            pools[pid].sort(key=lambda item: hashlib.sha256((day + item['text']).encode()).hexdigest())
        order = sorted(platforms, key=lambda pid: hashlib.sha256((day + pid).encode()).hexdigest())
        chosen, per_platform = [], {pid: 0 for pid in platforms}
        target = min(int(count), len(platforms) * 5, 30)
        while len(chosen) < target:
            progressed = False
            for pid in order:
                if pools[pid] and per_platform[pid] < 5 and len(chosen) < target:
                    chosen.append(pools[pid].pop())
                    per_platform[pid] += 1
                    progressed = True
            if not progressed:
                break
        _no_broadcast(chosen)
        for item in chosen:
            row, added = _insert_keyword(c, item, 'daily:' + day)
            if added:
                created_rows.append(row)
        c.execute('INSERT INTO platform_keyword_generation_runs VALUES(?,?,?,?)', (day, len(created_rows), data['version'], now()))
    return {'created': len(created_rows), 'items': created_rows, 'already_generated': False, 'day': day,
            'routing': 'per_platform', 'note': '仅生成分平台本地关键词，没有创建或发送任务；不会制造搜索量或实时热词。'}


def _decode_schedule(row):
    row = dict(row)
    row['items'] = json.loads(row['items'])
    row['enabled'] = bool(row['enabled'])
    return row


def list_schedules():
    with db() as c:
        rows = [_decode_schedule(row) for row in c.execute('SELECT * FROM platform_schedules ORDER BY created_at DESC,id')]
        migration = c.execute("SELECT value FROM meta WHERE key='platform_planning_v2_migration'").fetchone()
    notice = json.loads(migration['value']) if migration else {}
    return {'items': rows, 'legacy_paused': notice.get('legacy_paused', 0), 'migration_notice': notice,
            'legacy_items': records('schedules'), 'routing': 'per_platform'}


def save_schedule(time, items, mode='visibility', conversation_mode='fresh', enabled=False):
    if not isinstance(time, str) or not TIME_PATTERN.fullmatch(time):
        raise ValueError('计划时间须为 00:00 至 23:59')
    from engine import prepare_targeted_items
    prepared = prepare_targeted_items(items, mode, conversation_mode)
    snapshot = [{key: item[key] for key in ITEM_FIELDS} for item in prepared]
    sid, timestamp = ident(), now()
    with db() as c:
        c.execute('INSERT INTO platform_schedules VALUES(?,?,?,?,?,?,?,?,?)',
                  (sid, time, json.dumps(snapshot, ensure_ascii=False), mode, conversation_mode, int(enabled), '', timestamp, timestamp))
    return {'id': sid, 'enabled': bool(enabled), 'routing': 'per_platform',
            'message': '分平台计划已保存' + ('并启用；工作台运行时按北京时间每日执行一次' if enabled else '，当前未启用；请核对各平台问题后启用')}


def enable_schedule(sid, enabled):
    with db() as c:
        changed = c.execute('UPDATE platform_schedules SET enabled=?,updated_at=? WHERE id=?', (int(enabled), now(), sid)).rowcount
    if not changed:
        raise KeyError('计划不存在')
    return {'id': sid, 'enabled': bool(enabled), 'message': '计划已启用' if enabled else '计划已停用'}


def delete_schedule(sid):
    with db() as c:
        changed = c.execute('DELETE FROM platform_schedules WHERE id=?', (sid,)).rowcount
    if not changed:
        raise KeyError('计划不存在')
    return {'message': '分平台计划已删除，历史任务与回答保留'}


def due_schedules(current=None):
    current = current or datetime.now(CST)
    current = current.astimezone(CST) if current.tzinfo else current.replace(tzinfo=CST)
    with db() as c:
        return [_decode_schedule(row) for row in c.execute(
            'SELECT * FROM platform_schedules WHERE enabled=1 AND time<=? AND last_day<>? ORDER BY time,created_at,id',
            (current.strftime('%H:%M'), current.date().isoformat()))]


def claim_schedule(sid, day):
    try:
        date.fromisoformat(day)
    except (TypeError, ValueError) as exc:
        raise ValueError('计划执行日期无效') from exc
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        changed = c.execute('UPDATE platform_schedules SET last_day=?,updated_at=? WHERE id=? AND enabled=1 AND last_day<>?',
                            (day, now(), sid, day)).rowcount
    return bool(changed)
