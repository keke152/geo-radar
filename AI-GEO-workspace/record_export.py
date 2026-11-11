"""Fill the bundled Excel template using standard OpenXML, no Excel installation.

The reusable template is authored with Artifact Tool. User text is inline text,
never a formula; long originals are segmented instead of discarded.
"""
from copy import deepcopy
from datetime import datetime,timezone
from io import BytesIO
from urllib.parse import urlparse
from xml.etree import ElementTree as E
from zipfile import ZipFile,ZIP_DEFLATED
import json,re,unicodedata
from config import ROOT,PLATFORMS
from engine import CST
from domain import analyze
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
E.register_namespace('',NS)
def tag(name):return '{'+NS+'}'+name
def clean(text):return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]','',str(text or ''))
def col(n):
 name=''
 while n:n,i=divmod(n-1,26);name=chr(65+i)+name
 return name
def chunks(text):
 # Excel counts UTF-16 code units, including two for supplementary characters.
 result=[];part=[];size=0
 for char in clean(text):
  units=2 if ord(char)>65535 else 1
  if size+units>30000:result.append(''.join(part));part=[];size=0
  part.append(char);size+=units
 result.append(''.join(part));return result
def readable_chunks(text,width):
 """Keep each original segment within a readable 12-line cell, losslessly."""
 result=[];part=[];lines=1;used=0
 for char in clean(text):
  units=2 if unicodedata.east_asian_width(char) in ('W','F') else 1
  if char!='\n' and used+units>width:
   if lines>=12:result.append(''.join(part));part=[];lines=1
   else:lines+=1
   used=0
  part.append(char)
  if char=='\n':
   if lines>=12:result.append(''.join(part));part=[];lines=1
   else:lines+=1
   used=0
  else:used+=units
 if part or not result:result.append(''.join(part))
 return result
def stamp(task):
 dt=datetime.fromisoformat(task.get('sent_at') or task['created_at'])
 if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
 return dt.astimezone(CST).replace(tzinfo=None)
def serial(dt):return (dt-datetime(1899,12,30)).total_seconds()/86400
def hostname(value):
 try:return (urlparse(value if '://' in value else 'https://'+value).hostname or '').lower().removeprefix('www.')
 except ValueError:return ''
def rows_for(tasks,profile):
 main=[];raw=[];links=[]
 for task in tasks:
  metrics=task['metrics'] if isinstance(task['metrics'],dict) else json.loads(task['metrics'])
  answer=task['answer'];audit=metrics.get('report_annotation',{});analysis=analyze(answer,profile)
  sources=list(dict.fromkeys(u for u in metrics.get('source_links',[]) if isinstance(u,str) and u.startswith(('https://','http://'))))
  own=[u for u in sources if hostname(u)==hostname(profile['domain'])]
  others=[u for u in sources if u not in own]
  mention='无已保存回答' if not answer else '待核对' if not task['reviewed'] else ('是（'+('品牌、企业' if analysis['brand_mentioned'] and analysis['company_mentioned'] else '品牌' if analysis['brand_mentioned'] else '企业')+'）') if analysis['any_name_mentioned'] else '否'
  raw_start=len(raw)+2;question_parts=readable_chunks(task['prompt'],62);answer_parts=readable_chunks(answer or '尚无已保存回答',108);source_parts=readable_chunks('\n'.join(sources),74)
  for part in range(max(len(question_parts),len(answer_parts),len(source_parts))):
   raw.append([serial(stamp(task)),task['id'],question_parts[part] if part<len(question_parts) else '',answer_parts[part] if part<len(answer_parts) else '',part+1,PLATFORMS[task['platform']]['name']+' / '+('网页' if task['channel']=='web' else 'API'),source_parts[part] if part<len(source_parts) else ''])
  prompt_parts=chunks(task['prompt']);prompt=prompt_parts[0]+('（完整问题已分段保存在“原始回答”）' if len(prompt_parts)>1 else '')
  values=[serial(stamp(task)),PLATFORMS[task['platform']]['name'],audit.get('online','未核实'),task['id'],prompt,
   '是' if metrics.get('conversation_mode')=='fresh' else '否' if metrics.get('conversation_mode')=='continue' else '未记录',mention,
   audit.get('recommended','未判定'),audit.get('rank',''),('是' if own else '未发现' if sources else '未采集到来源'),
   chunks('\n'.join(others))[0]+('（完整来源见原始回答页）' if len(chunks('\n'.join(others)))>1 else ''),audit.get('errors',''),audit.get('competitors',''),audit.get('quote',''),f'原始回答!D{raw_start}',audit.get('changes',''),
   ' / '.join([{'completed':'已记录回答','queued':'待执行','running':'执行中','waiting_setup':'待连接或配置','needs_review':'待核对','sent':'已发送待确认','uncertain':'结果不确定','interrupted':'执行中断','failed':'执行失败','cancelled':'已取消'}.get(task['status'],task['status']),'网页' if task['channel']=='web' else 'API',task.get('note','')])]
  main.append(values);links.append((len(main)+2,raw_start))
 return main,raw,links
def append_rows(sheet,values,start,sample):
 data=sheet.find(tag('sheetData'))
 for row in list(data):
  if int(row.get('r'))>=start:data.remove(row)
 styles={re.sub(r'\d','',c.get('r')):c.get('s') for c in sample} if sample is not None else {}
 for number,record in enumerate(values,start):
  row=E.SubElement(data,tag('row'),{'r':str(number),'ht':'110' if start==3 else '220','customHeight':'1'})
  for index,value in enumerate(record,1):
   c=E.SubElement(row,tag('c'),{'r':col(index)+str(number)})
   if styles.get(col(index)):c.set('s',styles[col(index)])
   if isinstance(value,(int,float)):
    E.SubElement(c,tag('v')).text=str(value)
   else:
    c.set('t','inlineStr');t=E.SubElement(E.SubElement(c,tag('is')),tag('t'));t.set('{http://www.w3.org/XML/1998/namespace}space','preserve');t.text=clean(value)
 dimension=sheet.find(tag('dimension'))
 if dimension is None:dimension=E.Element(tag('dimension'));sheet.insert(1 if sheet.find(tag('sheetPr')) is not None else 0,dimension)
 dimension.set('ref',f'A1:{col(len(values[0]) if values else (17 if start==3 else 7))}{max(start-1,start+len(values)-1)}')
 old=sheet.find(tag('autoFilter'))
 if old is not None:sheet.remove(old)
 # autoFilter belongs immediately after sheetData, before mergeCells/hyperlinks.
 index=list(sheet).index(data)+1
 sheet.insert(index,E.Element(tag('autoFilter'),{'ref':f'A{start-1}:{"Q" if start==3 else "G"}{max(start-1,start+len(values)-1)}'}))
 return sheet
def build_xlsx(tasks,profile):
 main,raw,links=rows_for(tasks,profile);output=BytesIO()
 with ZipFile(ROOT/'assets/answer-record-template.xlsx') as template,ZipFile(output,'w',ZIP_DEFLATED) as target:
  for item in template.infolist():
   content=template.read(item.filename)
   if item.filename in ('xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml'):
    sheet=E.fromstring(content);is_main=item.filename.endswith('sheet1.xml');start=3 if is_main else 2
    sample=sheet.find(tag('sheetData')).find(tag('row')+f"[@r='{start}']")
    sheet=append_rows(sheet,main if is_main else raw,start,sample)
    if is_main and links:
     old=sheet.find(tag('hyperlinks'))
     if old is not None:sheet.remove(old)
     hyperlink=E.Element(tag('hyperlinks'))
     for row,raw_row in links:E.SubElement(hyperlink,tag('hyperlink'),{'ref':f'O{row}','location':f"'原始回答'!D{raw_row}",'display':f'原始回答!D{raw_row}'})
     anchor=sheet.find(tag('mergeCells'))
     if anchor is None:anchor=sheet.find(tag('autoFilter'))
     sheet.insert(list(sheet).index(anchor)+1,hyperlink)
    content=E.tostring(sheet,encoding='utf-8',xml_declaration=True)
   elif item.filename=='xl/workbook.xml':
    workbook=E.fromstring(content)
    for name in workbook.findall(tag('definedNames')+'/'+tag('definedName')):
     if name.get('name')=='_xlnm._FilterDatabase':name.text=f"Sheet1!$A$2:$Q${len(main)+2}"
    content=E.tostring(workbook,encoding='utf-8',xml_declaration=True)
   target.writestr(item,content)
 return output.getvalue()
