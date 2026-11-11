"""Grounded local question planning; no invented search-volume or external sends."""
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from storage import db, get_meta, ident, now

CST=timezone(timedelta(hours=8))
DEFAULT_PLAN={'enabled':False,'time':'09:00','count':10}

# Each template has a distinct decision to investigate, rather than date/synonym padding.
TOPICS={
 '招商词':[
  '经销合作前需要核对哪些企业资质','代理合同里需要明确哪些退换货条款','首次进货怎样评估库存风险',
  '品牌方通常需要提供哪些招商支持材料','经销商如何核实品牌授权链条','门店合作前如何核对供货与售后责任',
  '渠道合作怎样比较起订量和补货周期','怎样评估经销合作的区域保护条款','招商政策中哪些费用应在签约前确认',
  '线上和线下渠道合作需要分别确认什么','如何审核产品宣传素材的依据','经销合作的样品测试流程如何安排',
  '品牌运营方与生产企业的责任如何区分','经销合作试销阶段应跟踪哪些指标','供应商交货延迟时合同应怎样约定',
  '招商合作如何核对产品批次与追溯信息','门店选品如何评估包装规格与陈列需求','经销商如何设计首批采购清单',
  '经销商如何核对进货价格与结算方式','合作终止时如何处理剩余库存与授权',
 ],
 '行业词':[
  '选择供应商时应该核对哪些公开信息','怎样比较不同品牌的产品信息完整度','如何区分品牌运营方和实际生产方',
  '采购时如何建立供应商筛选清单','如何核对企业官网与产品标签的主体一致性','采购前怎样核对商品标识和规格',
  '如何评估品牌提供的产品检测材料','哪些公开信息有助于判断供货稳定性','选择合作品牌时如何核对售后流程',
  '如何区分独立来源与企业自述信息','从哪些渠道核对品牌的商标与授权信息','怎样记录不同供应商的比较依据',
  '供应商准入审核需要保存哪些资料','采购合同怎样列明质量验收标准','如何对比品牌的培训与运营支持',
 ],
 '场景词':[
  '门店首次选品应准备哪些核查问题','电商渠道上架前需要整理哪些产品资料','线下活动选品怎样核对宣传内容',
  '社区门店如何评估试销后的复购情况','新经销商如何安排产品知识培训','门店如何保存批次验收和售后记录',
  '采购人员如何制作不同品牌的对比表','首次合作如何安排样品和正式供货验收','渠道负责人怎样确认补货和发货时效',
  '客服团队需要掌握哪些产品标签信息','门店促销前怎样核对品牌授权范围','多门店采购如何统一商品资料管理',
  '线上招商咨询应该向品牌方询问什么','线下招商洽谈前需要带哪些核验清单','品牌合作试运营结束后如何复盘',
 ],
}
FOOD_QUESTIONS=[
 '产品标签上的菌株信息应该怎样核对','产品储存条件和运输条件应如何核对','购买时如何查看配料表与食用提示',
 '产品标签与招商资料不一致时应该核对什么','食品生产许可证与产品实际生产主体如何对应',
 '如何区分普通食品信息与未经证实的功效宣传','批次检测报告需要核对哪些基本信息',
 '渠道选品时怎样比较保质期与周转周期','包装标注的适用提示应如何向客户说明','经销商如何核对食品召回与售后联系方式',
]

def plan_settings():
 return {**DEFAULT_PLAN,**get_meta('keyword_plan')}

def normalize(text):return re.sub(r'[\W_]+','',text).casefold()

def pool(profile):
 business=profile['business'].strip().rstrip('。；;')
 if not business or len(business)>50:
  return []  # Ask for a concise actual business; never invent one.
 topics={kind:list(items) for kind,items in TOPICS.items()}
 if '食品' in business:topics['行业词']+=FOOD_QUESTIONS
 rows=[]
 for kind,questions in topics.items():
  for question in questions:
   text=business+'，'+question+'？'
   rows.append({'text':text,'kind':kind,'score':90 if kind=='招商词' else 86,
                'reason':'明确合作决策与核验对象；基于已填写主营业务，未预设功效或行业排名。',
                'source':'企业设置中的主营业务 + 本地问题模板','normalized':normalize(text)})
 return rows

def generate(day=None):
 settings=plan_settings();day=day or datetime.now(CST).date().isoformat()
 candidates=pool(get_meta('profile'))
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  previous=c.execute('SELECT count FROM keyword_generation_runs WHERE day=?',(day,)).fetchone()
  if previous:return {'created':0,'already_generated':True,'day':day,'previous_count':previous['count']}
  known={normalize(row['text']) for row in c.execute('SELECT text FROM keywords')}
  known.update(row['normalized'] for row in c.execute('SELECT normalized FROM keyword_candidates'))
  remaining=[item for item in candidates if item['normalized'] not in known]
  # Balanced intents, daily deterministic order; never fake trending phrases.
  groups={kind:[] for kind in TOPICS}
  for item in remaining:groups[item['kind']].append(item)
  for group in groups.values():group.sort(key=lambda item:hashlib.sha256((day+item['text']).encode()).hexdigest())
  chosen=[]
  while len(chosen)<settings['count'] and any(groups.values()):
   for group in groups.values():
    if group and len(chosen)<settings['count']:chosen.append(group.pop())
  for item in chosen:
   c.execute('INSERT INTO keyword_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',
      (ident(),day,item['text'],item['normalized'],item['kind'],item['score'],item['reason'],item['source'],'pending',now()))
  c.execute('INSERT INTO keyword_generation_runs VALUES(?,?,?)',(day,len(chosen),now()))
 return {'created':len(chosen),'already_generated':False,'day':day,
         'note':'无新候选时保留现有词，不用改日期、堆同义词来凑数。' if not chosen else '仅生成本机候选，没有创建或发送平台任务。'}

def daily_tick(current=None):
 settings=plan_settings();current=current or datetime.now(CST)
 current=current.astimezone(CST) if current.tzinfo else current.replace(tzinfo=CST)
 if settings['enabled'] and current.strftime('%H:%M')>=settings['time']:
  from platform_planner import generate_daily
  return generate_daily(current.date().isoformat())
 return None

def candidates():
 with db() as c:
  rows=[dict(row) for row in c.execute("SELECT * FROM keyword_candidates WHERE state='pending' ORDER BY day DESC,score DESC,created_at DESC LIMIT 100")]
  last=c.execute('SELECT * FROM keyword_generation_runs ORDER BY day DESC LIMIT 1').fetchone()
 return {'items':rows,'settings':plan_settings(),'last_run':dict(last) if last else None,
         'basis':'本地规则评分代表问题具体性与核验意图，不是搜索量、竞争度或实时热度；候选不会自动发送。'}

def accept(candidate_id):
 with db() as c:
  c.execute('BEGIN IMMEDIATE')
  row=c.execute("SELECT * FROM keyword_candidates WHERE id=? AND state='pending'",(candidate_id,)).fetchone()
  if not row:raise ValueError('候选不存在或已处理')
  c.execute('INSERT OR IGNORE INTO keywords VALUES(?,?,?,?)',(ident(),row['text'],row['kind'],now()))
  c.execute("UPDATE keyword_candidates SET state='accepted' WHERE id=?",(candidate_id,))
 return {'message':'已加入关键词库；没有创建平台任务'}
