import os,httpx
from config import PLATFORMS
from browser_bridge import NeedsSetup

async def api_send(pid,config,prompt,client=None,messages=None):
 provider=PLATFORMS[pid]
 if not provider['api']:raise NeedsSetup('该平台仅保留网页通道；不把其他模型API当作该消费端的结果')
 key=os.getenv(provider['env'],'').strip()
 if not key or not config['model'].strip():raise NeedsSetup(f"请在本机.env配置{provider['env']}，并填写该平台控制台可用的模型ID")
 payload={'model':config['model'],'messages':messages or [{'role':'user','content':prompt}],'stream':False,'max_tokens':2200}
 endpoint=provider['api'];headers={'Authorization':'Bearer '+key}
 if pid=='qwen' and config['search_enabled']:payload['enable_search']=True
 async def request(session):
  response=await session.post(endpoint,json=payload,headers=headers)
  if response.status_code>=400:raise RuntimeError(f'平台返回HTTP {response.status_code}，请检查密钥、模型、权限或额度（密钥不会写入日志）')
  data=response.json()
  try:text=data['choices'][0]['message']['content']
  except (KeyError,IndexError,TypeError) as exc:raise RuntimeError('平台响应格式不符合聊天接口，请检查模型协议') from exc
  if not isinstance(text,str) or not text.strip():raise RuntimeError('平台未返回可读取的回答文本')
  return text[:100000]
 if client:return await request(client)
 async with httpx.AsyncClient(timeout=65,follow_redirects=False,trust_env=False) as session:return await request(session)
