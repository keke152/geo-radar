from pathlib import Path
import os
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env',override=False)
HOME=Path(os.getenv('JUNHE_HOME',str(ROOT/'runtime'))).resolve()
HOME.mkdir(parents=True,exist_ok=True)
VERSION='2.0.0'
APP_NAME='GEO Radar · 品牌雷达'
PLATFORMS={
 'doubao':{'name':'豆包','url':'https://www.doubao.com/chat/','api':'https://ark.cn-beijing.volces.com/api/v3/chat/completions','env':'ARK_API_KEY','docs':'https://www.volcengine.com/docs/82379'},
 'deepseek':{'name':'DeepSeek','url':'https://chat.deepseek.com/','api':'https://api.deepseek.com/chat/completions','env':'DEEPSEEK_API_KEY','docs':'https://api-docs.deepseek.com/zh-cn/'},
 'kimi':{'name':'Kimi','url':'https://www.kimi.com/','api':'https://api.moonshot.cn/v1/chat/completions','env':'MOONSHOT_API_KEY','docs':'https://platform.moonshot.cn/docs/'},
 'qwen':{'name':'千问','url':'https://www.qianwen.com/','api':'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions','env':'DASHSCOPE_API_KEY','docs':'https://help.aliyun.com/zh/model-studio/'},
 'yuanbao':{'name':'腾讯元宝','url':'https://yuanbao.tencent.com/','api':None,'env':None,'docs':'https://yuanbao.tencent.com/'},
 'zhihu':{'name':'知乎直答','url':'https://zhida.zhihu.com/','api':None,'env':None,'docs':'https://zhida.zhihu.com/'},
}
DEFAULT_PROFILE={'company_name':'广州菌和生物科技有限公司','domain':'www.junheprobio.com','aliases':['菌和生物'],
 'business':'益生菌食品','audience':'益生菌食品经销商、代理商及门店合作方（依据招商课件第39–48页整理，待公司确认）',
 'public_intro':'广州菌和生物科技有限公司，主营益生菌食品。公司提供的官网域名为 www.junheprobio.com，目前备案中。',
 'audience_confirmed':False,
 'brand_name':'广微 益森日纪','brand_aliases':['广微·益森日纪','广微益森日纪','益森日纪'],
 'brand_relation':'广微 益森日纪是广州菌和与广微集团合作的品牌。广州菌和主要开展品牌运营和招商业务。'}
DEFAULT_SETTINGS={'interval_seconds':45,'daily_limit':300,'paused':False,'parallel_platforms':6,'auto_verify':True}

def default_platform(pid):
 return {'id':pid,'channel':'web','model':'','composer':'textarea, [contenteditable="true"][role="textbox"], [contenteditable="true"]',
 'send_button':'','reply_selector':'','new_chat_selector':'','send_key':'','ready':False,'search_enabled':False}

def supported_channels(pid):
 return ('web','api') if PLATFORMS[pid]['api'] else ('web',)
