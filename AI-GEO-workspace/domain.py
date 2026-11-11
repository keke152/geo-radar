import json,re
from urllib.parse import urlsplit
from storage import get_meta,records

def brand_names(profile):
 return [profile.get('brand_name',''),*profile.get('brand_aliases',[])]

def name_present(text,names):
 normalized=re.sub(r'[\s·•・*_`]+','',text).casefold()
 return any(len(value)>=2 and value in normalized for name in names if name
            for value in [re.sub(r'[\s·•・*_`]+','',name).casefold()])

def analyze(answer,profile):
 names=[profile['company_name'],*profile.get('aliases',[])]
 company=name_present(answer,names)
 brand=name_present(answer,brand_names(profile))
 company_matches=list(dict.fromkeys(name for name in names if name and name_present(answer,[name])))
 brand_matches=list(dict.fromkeys(name for name in brand_names(profile) if name and name_present(answer,[name])))
 urls=[url.rstrip('.,;:!?。，；、！？）》】') for url in re.findall(r'https?://[^\s<>"\]\)]+',answer)]
 domain=profile['domain'].lower().removeprefix('www.')
 matches=[]
 for url in urls:
  try:
   host=(urlsplit(url).hostname or '').lower().removeprefix('www.')
   if host==domain:matches.append(url.rstrip('。，；、'))
  except ValueError:pass
 return {'brand_mentioned':brand,'company_mentioned':company,'brand_name_mentioned':brand,'any_name_mentioned':company or brand,
         'company_matches':company_matches,'brand_matches':brand_matches,
         'official_link_present':bool(matches),'links':list(dict.fromkeys(matches)),
         'note':'仅检测回答文本中的名称与链接；否定句或复述中的出现也计为文本提及，不证明正向推荐、收录或排名'}

def make_prompt(keyword,mode):
 profile=get_meta('profile')
 if mode=='visibility':
  return ('请搜索公开网页并回答以下问题，列出可核验的来源URL；若当前无法联网，请明确说明，不要编造来源。\n问题：'+keyword)
 docs=[d for d in records('documents') if d['approved']]
 if not docs:raise ValueError('没有已允许对外发送的资料')
 evidence='\n\n'.join(f"资料：{d['title']}\n出处：{d['source']}\n内容：{d['body']}" for d in docs)
 if len(evidence)>18000:raise ValueError('公开资料合计超过18000字，请精简或关闭部分资料')
 return ('以下是企业提供的资料，仅供本次会话阅读，不代表你已永久收录或向公众推荐。请区分企业自述与独立核实的事实；不得补写医疗疗效、资质或合作背书。\n'
         +evidence+'\n\n本次问题：'+keyword+'\n请整理一份有出处的回答，并标明待核验内容。')

def brand_hint(keyword,profile):
 return name_present(keyword,[profile['company_name'],*profile.get('aliases',[]),*brand_names(profile),profile['domain'],'junheprobio'])

def public_pack(profile):
 domain=profile['domain']
 docs=[d for d in records('documents') if d['approved']]
 text='\n\n'.join(f"## {d['title']}\n{d['body']}\n\n资料来源：{d['source']}" for d in docs)
 org={'@context':'https://schema.org','@type':'Organization','name':profile['company_name'],'url':'https://'+domain+'/',
      'description':profile['business']}
 return {'company-profile.md':f"# {profile['company_name']}\n\n官网：https://{domain}/\n\n主营：{profile['business']}\n\n{text}\n\n此文件为网站内容草稿，未自动发布。",
         'organization.jsonld':json.dumps(org,ensure_ascii=False,indent=2),
         'robots.txt':f'User-agent: *\nAllow: /\nSitemap: https://{domain}/sitemap.xml\n',
         'sitemap.xml':f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://{domain}/</loc></url></urlset>',
         'README.txt':'这些是供网站维护人员审核部署的草稿。当前工具未访问网站后台，也未完成发布、搜索引擎提交或收录。robots/sitemap不是排名或AI引用保证。'}
