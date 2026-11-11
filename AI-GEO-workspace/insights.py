"""Read-only measurements. No provider calls, task writes, or ranking inference."""
import json
from datetime import date, datetime, time, timedelta, timezone
from config import PLATFORMS
from domain import analyze, brand_hint

CST = timezone(timedelta(hours=8))


def date_window(days=30, start_date=None, end_date=None, today=None):
    today = today or datetime.now(CST).date()
    try:
        end = date.fromisoformat(end_date) if end_date else today
        start = date.fromisoformat(start_date) if start_date else end - timedelta(days=days - 1)
    except (ValueError, TypeError) as exc:
        raise ValueError('日期请使用YYYY-MM-DD格式') from exc
    if start > end or (end - start).days > 365:
        raise ValueError('开始日期不得晚于结束日期，范围最多366天')
    return start, end


def event_time(task):
    raw = task.get('sent_at') or task['created_at']
    try:
        stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).astimezone(CST)
    except (ValueError, TypeError):
        return None


REASONS={'eligible':'已计入','branded':'问题含公司或品牌名称，属于指名核对','materials':'附带公司资料的研读任务',
         'continuation':'连续会话带有历史上下文','source_directed':'指定资料渠道的核查任务，不计入自然发现',
         'unreviewed':'任务未完成或回答尚未核对','empty_answer':'未保存非空回答'}

def eligibility(task, profile):
    if task['mode'] != 'visibility':
        return 'materials'
    stored = task.get('metrics', {})
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except (ValueError, TypeError):
            stored = {}
    if stored.get('context_contaminated') or stored.get('conversation_mode')=='continue':
        return 'continuation'
    if stored.get('source_directed') or stored.get('goal')=='source_audit':
        return 'source_directed'
    if stored.get('goal')=='brand_check' or stored.get('brand_hint') or brand_hint(task['keyword'], profile):
        return 'branded'
    if task['status'] != 'completed' or not task.get('reviewed'):
        return 'unreviewed'
    if not task.get('answer', '').strip():
        return 'empty_answer'
    return 'eligible'


def measurement(task,profile,scope='natural'):
    reason=eligibility(task,profile)
    if scope=='all':
        if task['status']!='completed' or not task.get('reviewed'):reason='unreviewed'
        elif not task.get('answer','').strip():reason='empty_answer'
        else:reason='eligible'
    return {'included':reason=='eligible','reason':reason,'description':REASONS[reason],
            'natural_reason':eligibility(task,profile),'analysis':analyze(task.get('answer',''),profile)}


def build_insights(tasks, profile, days=30, channel='web', platform='all', start_date=None, end_date=None, today=None,scope='natural'):
    if channel not in ('web', 'api') or platform not in ('all', *PLATFORMS) or scope not in ('natural','all'):
        raise ValueError('请选择有效通道和平台')
    start, end = date_window(days, start_date, end_date, today)
    platform_ids = list(PLATFORMS) if platform == 'all' else [platform]
    selected = []
    for task in tasks:
        stamp = event_time(task)
        if task['channel'] == channel and task['platform'] in platform_ids and stamp and start <= stamp.date() <= end:
            selected.append((task, stamp))
    selected.sort(key=lambda item: (item[1], item[0]['created_at'], item[0]['id']), reverse=True)
    excluded = dict.fromkeys(('materials', 'branded', 'unreviewed', 'empty_answer', 'continuation', 'source_directed'), 0)
    counters = {pid: {'id': pid, 'name': PLATFORMS[pid]['name'], 'samples': 0, 'brand_mentions': 0,'total_tasks':0,'recorded_answers':0,'exclusions':{},
                      'company_mentions': 0, 'official_links': 0, 'last_sample_at': None} for pid in platform_ids}
    trend = {}
    for offset in range((end - start).days + 1):
        key = (start + timedelta(days=offset)).isoformat()
        trend[key] = {'date': key, 'samples': 0, 'brand_mentions': 0, 'company_mentions': 0, 'official_links': 0}
    eligible = []
    questions = {}
    comparison={}
    for task, stamp in selected:
        info=measurement(task,profile,scope);reason=info['reason'];counter=counters[task['platform']]
        counter['total_tasks']+=1
        if task['status']=='completed' and task.get('reviewed') and task.get('answer','').strip():counter['recorded_answers']+=1
        group=comparison.setdefault(task['keyword'],{'keyword':task['keyword'],'platforms':{},'task_count':0})
        group['task_count']+=1
        group['platforms'].setdefault(task['platform'],{'id':task['id'],'at':stamp.isoformat(),'status':task['status'],
           'included':info['included'],'reason':reason,'reason_text':info['description'],'natural_reason':info['natural_reason'],
           'brand_mentioned':info['analysis']['brand_name_mentioned'],'company_mentioned':info['analysis']['company_mentioned'],
           'official_link_present':info['analysis']['official_link_present'],'answer_preview':task.get('answer','')[:160]})
        if reason != 'eligible':
            excluded[reason] += 1
            counter['exclusions'][reason]=counter['exclusions'].get(reason,0)+1
            continue
        result = analyze(task['answer'], profile)
        row = {'id': task['id'], 'keyword': task['keyword'], 'platform': task['platform'], 'channel': channel,
               'at': stamp.isoformat(), 'brand_mentioned': result['brand_name_mentioned'],
               'company_mentioned': result['company_mentioned'], 'official_link_present': result['official_link_present'],
               'official_links': result['links'], 'answer_preview': task['answer'][:240]}
        eligible.append(row)
        counter = counters[task['platform']]
        counter['last_sample_at'] = counter['last_sample_at'] or row['at']
        for target in (counter, trend[stamp.date().isoformat()]):
            target['samples'] += 1
            target['brand_mentions'] += int(row['brand_mentioned'])
            target['company_mentions'] += int(row['company_mentioned'])
            target['official_links'] += int(row['official_link_present'])
        keyword = task['keyword'].strip()
        question = questions.setdefault(keyword, {'keyword': keyword, 'platforms': {}, 'sample_count': 0})
        question['sample_count'] += 1
        # The newest reviewed response for exactly this question/platform.
        question['platforms'].setdefault(task['platform'], row)
    totals = {'samples': len(eligible), 'questions': len(questions),
              'brand_mentions': sum(row['brand_mentioned'] for row in eligible),
              'company_mentions': sum(row['company_mentioned'] for row in eligible),
              'official_links': sum(row['official_link_present'] for row in eligible)}
    totals['brand_rate'] = round(totals['brand_mentions'] * 100 / len(eligible), 1) if eligible else None
    status_counts = {}
    for task, _ in selected:
        status_counts[task['status']] = status_counts.get(task['status'], 0) + 1
    actions = []
    pending = status_counts.get('needs_review', 0) + status_counts.get('sent', 0)
    if pending:
        actions.append({'title': f'{pending}条网页回答尚未核对' if channel == 'web' else f'{pending}条回答尚未确认',
                        'body': '先核对对应平台的完整回答和原始问题，再保存为检查样本。', 'target': 'results'})
    waiting = status_counts.get('waiting_setup', 0)
    if waiting:
        actions.append({'title': f'{waiting}条旧任务尚未继续', 'body': '查看各任务的平台与控件状态。窗口已恢复时，可在记录中继续指定任务，不必重复创建。', 'target': 'results'})
    if not eligible:
        actions.append({'title': '当前范围还没有可统计的回答', 'body': '切换“全部已核对回答”可查看指名问题；自然发现只计算不带公司或品牌名的独立检查。未完成的回答仍不计入。', 'target': 'overview'})
    elif totals['brand_mentions'] == 0:
        actions.append({'title': '当前样本尚未提及品牌', 'body': '先检查公司与合作品牌的公开介绍、产品事实及来源是否完整；官网备案完成后再按相同问题复测。', 'target': 'company'})
    elif totals['official_links'] == 0:
        actions.append({'title': '已有品牌提及，尚未出现官网链接', 'body': '核对完整回答的来源；备案完成并发布可访问内容后，继续用同一组问题观察。', 'target': 'results'})
    return {'filters': {'start_date': start.isoformat(), 'end_date': end.isoformat(), 'channel': channel, 'platform': platform,'scope':scope},
            'generated_at': datetime.now(CST).isoformat(timespec='seconds'), 'brand_name': profile.get('brand_name', ''),
            'company_name': profile['company_name'], 'totals': totals, 'platforms': list(counters.values()),
            'trend': list(trend.values()), 'questions': list(questions.values()),'comparison':list(comparison.values())[:50], 'evidence': eligible[:30],
            'matching_rules':{'company_names':[profile['company_name'],*profile.get('aliases',[])],
                              'brand_names':[profile.get('brand_name',''),*profile.get('brand_aliases',[])],
                              'rule':'只分析保存的回答，不把问题或思考过程作为品牌推荐；忽略空白、间隔点和Markdown强调符号，按当前名称/别名匹配。'},
            'task_count': len(selected), 'statuses': status_counts, 'excluded': excluded, 'actions': actions,
            'measurement_note': ('当前为全部已核对回答，包含指名核对、资料研读与连续会话，不能据此判断自然推荐率。' if scope=='all' else '当前为自然发现，只含不带公司或品牌名、未附带资料的独立检查。')+'按发送时间统计，未发送任务按创建时间；只统计已完成、核对通过的非空回答。自动校验仅验证采集对应和结束状态，不核实事实。名称在否定句中出现也算文本提及。品牌、企业和官网链接分别计算，API与网页分开。同题对比另外列出最新任务及未计入原因，不再把未计入显示为未检查。'}


def markdown_report(report):
    def cell(value):
        return str(value).replace('\\', '\\\\').replace('|', '\\|').replace('<', '&lt;').replace('>', '&gt;').replace('\n', ' ')
    f, t = report['filters'], report['totals']
    lines = ['# AI品牌可见度检查报告', '', f"品牌：{cell(report['brand_name'])}",
             f"企业：{cell(report['company_name'])}", f"时间：{f['start_date']} 至 {f['end_date']}（北京时间）",
             '通道：' + {'web':'消费端网页','api':'官方API问答'}[f['channel']], '',
             '统计范围：'+('全部已核对回答（含指名提问）' if f.get('scope')=='all' else '自然发现（不带公司或品牌词）'),'',
             f"符合口径样本 {t['samples']} 条，覆盖 {t['questions']} 个问题。",
             f"提及品牌 {t['brand_mentions']} 条；提及企业 {t['company_mentions']} 条；出现官网链接 {t['official_links']} 条。", '',
             '| 平台 | 样本 | 提及品牌 | 提及企业 | 官网链接 |', '| --- | ---: | ---: | ---: | ---: |']
    for p in report['platforms']:
        lines.append(f"| {p['name']} | {p['samples']} | {p['brand_mentions']} | {p['company_mentions']} | {p['official_links']} |")
    lines += ['', '## 同题对比', '', '各单元格为同一问题、同一平台最近一次符合口径的回答；多次回答不等于独立用户覆盖。', '']
    for q in report['questions']:
        lines.append('问题：' + cell(q['keyword']))
        for pid, sample in q['platforms'].items():
            lines.append(f"- {PLATFORMS[pid]['name']}：品牌{'出现' if sample['brand_mentioned'] else '未出现'}，企业{'出现' if sample['company_mentioned'] else '未出现'}，官网链接{'出现' if sample['official_link_present'] else '未出现'}；时间 {sample['at']}；记录 {sample['id']}")
        lines.append('')
    lines += ['## 下一步', ''] + [f"- {cell(a['title'])}：{cell(a['body'])}" for a in report['actions']]
    lines += ['', '## 统计口径', '', report['measurement_note'], '',
              '排除项：' + '；'.join(f'{key}={value}' for key, value in report['excluded'].items()), '',
              '报告仅导出本机观测记录，未执行公开发布、搜索引擎提交或资料收录。']
    return '\n'.join(lines) + '\n'
