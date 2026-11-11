"""Read-only, conservative recognition of page states which need human handling.

Evaluate PAGE_GUARD_SCAN with ``{'pid': platform_id}``. Optional ``config`` may
contain the saved ``reply_selector`` to exclude a custom answer container.
No editor values, account information, page text, or URLs leave the page. The
four returned fields always come from PAGE_GUARD_RESULTS. ``ready`` only means
no supported blocking UI was recognized; it does not establish a logged-in user.
This module never clicks, types, changes a page, or attempts to bypass a check.
"""
import json


PAGE_GUARD_RESULTS = {
    'ready': {
        'state': 'ready', 'code': 'ready',
        'message': '未识别到登录、安全验证或频率限制提示；这不代表账号已经登录。',
        'needs_user_action': False,
    },
    'login_required': {
        'state': 'login_required', 'code': 'login_required',
        'message': '平台当前显示登录页面或登录控件。请本人在专用窗口完成登录后再继续。',
        'needs_user_action': True,
    },
    'security_verification': {
        'state': 'verification_required', 'code': 'security_verification',
        'message': '平台当前显示安全验证。请本人在专用窗口处理；工作台不会自动绕过或重复尝试。',
        'needs_user_action': True,
    },
    'rate_limited': {
        'state': 'rate_limited', 'code': 'rate_limited',
        'message': '平台显示请求频率或次数限制。请按平台提示等待或处理后再手动继续，避免反复重试。',
        'needs_user_action': True,
    },
    'zhihu_login_parameter_error': {
        'state': 'login_required', 'code': 'zhihu_login_parameter_error',
        'message': '知乎登录页显示参数异常（10001）。请本人检查登录入口并在专用窗口处理，避免反复自动重试。',
        'needs_user_action': True,
    },
}


PAGE_GUARD_SCAN = r'''({pid,config={}}={})=>{
 const results=''' + json.dumps(PAGE_GUARD_RESULTS, ensure_ascii=False) + r''';
 const result=code=>({...results[code]});
 const hosts={
  doubao:['www.doubao.com','doubao.com'],
  deepseek:['chat.deepseek.com'],
  kimi:['www.kimi.com','kimi.com','kimi.moonshot.cn'],
  qwen:['www.qianwen.com','qianwen.com','chat.qwen.ai'],
  yuanbao:['yuanbao.tencent.com'],
  zhihu:['zhida.zhihu.com','www.zhihu.com','zhihu.com']
 };
 // A response shown on another site or a mismatched platform is not evidence
 // about this account. BrowserBridge must enforce its own allowed-page policy.
 if(!Object.hasOwn(hosts,pid)||!hosts[pid].includes(location.hostname.toLowerCase()))return result('ready');
 const loginRoute=/^\/(?:login|signin|sign_in|sign-in|signup|sign_up|sign-up)(?:\/|$)/i.test(location.pathname);
 const transcriptSelector='[data-message-role],[data-message-author-role],[data-role=user],[data-role=assistant],'+
  '[data-testid="message-list"],[data-testid="message_text_content"],[data-testid=user-message],[data-testid=assistant-message],'+
  '.user-message,.assistant-message,.message.user,.message.assistant,.segment-user,.segment-assistant,'+
  '.ds-message,.ds-assistant-message-main-content,[class*=message-select-wrapper-question-],[class*=message-select-wrapper-answer-],'+
  '.agent-chat__list__item--human,.agent-chat__list__item--ai,.agent-chat__bubble--ai,.hyc-content-text,[class*=markdown],[class*=Markdown]';
 const contentSelector='textarea,input,[contenteditable=true],[contenteditable=""],[role=textbox],pre,code,article,blockquote,'+transcriptSelector;
 let answerRoots=[];
 if(typeof config?.reply_selector==='string'&&config.reply_selector){
  try{answerRoots=[...document.querySelectorAll(config.reply_selector)].filter(e=>e!==document.body&&e!==document.documentElement);}catch{}
 }
 const inAnswer=e=>!!e.closest(contentSelector)||answerRoots.some(root=>root.contains(e));
 const visible=e=>{
  if(!e)return false;
  const rect=e.getBoundingClientRect();
  if(!rect.width||!rect.height||rect.right<=0||rect.bottom<=0||rect.left>=innerWidth||rect.top>=innerHeight)return false;
  for(let node=e;node;node=node.parentElement){
   const css=getComputedStyle(node);
   if(node.hidden||node.hasAttribute('inert')||node.getAttribute('aria-hidden')==='true'||css.display==='none'||css.visibility==='hidden'||css.visibility==='collapse'||Number(css.opacity)===0)return false;
  }
  return true;
 };
 const ui=e=>visible(e)&&!inAnswer(e);
 const text=e=>typeof e.innerText==='string'?e.innerText.replace(/[\u200B\uFEFF]/g,'').replace(/\s+/g,' ').trim():'';
 const nodes=selector=>[...document.querySelectorAll(selector)];
 const shortText=e=>{const value=text(e);return value.length<=320?value:'';};
 // This particular error is only recognized on a known Zhihu login URL.
 // A provider answer quoting the error, or its code alone, is not sufficient.
 if(pid==='zhihu'&&loginRoute){
  const errorNodes=[document.body,...nodes('h1,h2,h3,p,span,div,pre,[role=alert],[role=status]')];
  if(errorNodes.some(e=>visible(e)&&/\b10001\b/.test(shortText(e))&&/请求参数异常/.test(shortText(e))))return result('zhihu_login_parameter_error');
 }
 const dialogs=nodes('dialog,[role=dialog],[aria-modal=true],.signFlowModal,.LoginModal,.login-modal,.login-dialog').filter(ui);
 const headings=nodes('h1,h2,h3,[role=heading]').filter(ui);
 const securityCaption=/^(?:(?:请(?:先)?)(?:完成(?:下方)?|进行|通过)(?:安全|人机|身份)?验证|安全验证|人机验证|验证身份|安全检查|验证您是(?:真人|人类)|verify (?:that )?you are human|security verification|verification required|complete (?:the )?(?:security )?verification)(?:\s|[，。:：!！]|$)/i;
 const loginCaption=/^(?:登录|扫码登录|手机号登录|账号密码登录|登录或注册|注册或登录|登录后继续|登录以继续|欢迎登录|log in|sign in)(?:\s|[，。:：!！]|$)/i;
 const credential=e=>visible(e)&&!inAnswer(e.parentElement)&&!answerRoots.some(root=>root.contains(e));
 const password=nodes('input[type=password],input[autocomplete=current-password],input[autocomplete=new-password]').some(credential);
 const otp=nodes('input[autocomplete=one-time-code]').some(credential);
 const challengeFrames=nodes('iframe').filter(ui).some(frame=>{
  // Inspect only frame attributes; never enter a challenge or read its form.
  try{
   const url=new URL(frame.getAttribute('src')||'',location.href);
   return /(?:^|\.)(?:recaptcha\.net|google\.com)$/.test(url.hostname)&&/^\/recaptcha\/(?:api2|enterprise)\/(?:anchor|bframe)/.test(url.pathname)||
    url.hostname==='challenges.cloudflare.com'||
    /(?:^|\.)(?:captcha\.qq\.com|captcha\.gtimg\.com)$/.test(url.hostname)||
    url.origin===location.origin&&/\/(?:captcha|challenge|security-verification)(?:\/|$)/i.test(url.pathname);
  }catch{return false;}
 });
 const challengeWidgets=nodes('.geetest_panel,.geetest_holder,.tcaptcha-transform,#tcaptcha_iframe,[data-testid=captcha],[data-testid=security-verification],#aliyunCaptcha-window-popup').some(ui);
 const challengeHeading=headings.some(e=>securityCaption.test(shortText(e)));
 const challengeDialog=dialogs.some(e=>!e.querySelector(transcriptSelector)&&securityCaption.test(shortText(e)));
 if(challengeFrames||challengeWidgets||challengeHeading||challengeDialog||otp)return result('security_verification');
 // Only structured platform notices qualify. Do not search the page body,
 // chat transcript, composer text, document title, or arbitrary paragraphs.
 const notices=nodes('[role=alert],[role=status],[aria-live=assertive],[data-testid=toast],[class*=toast],[class*=Toast],.ant-message-notice-content,.ant-notification-notice-message,.semi-toast-content,.ds-toast__content').filter(ui);
 const rateNotice=/(?:操作|请求|访问|发送)(?:过于|太过|太)?频繁|请求次数过多|请求过多|频率(?:限制|过高)|速率限制|超出(?:本日|今日|每日|每小时)?(?:请求|消息|发送)?次数限制|too many requests|rate limit(?:ed| exceeded)?|quota exceeded|(?:request|message) limit reached/i;
 if(notices.some(e=>rateNotice.test(shortText(e))))return result('rate_limited');
 const loginHeading=headings.some(e=>loginCaption.test(shortText(e))&&(e.tagName==='H1'||!!e.closest('dialog,[role=dialog],[aria-modal=true],form,.signFlowModal,.LoginModal,.login-modal,.login-dialog')));
 const loginDialog=dialogs.some(e=>!e.querySelector(transcriptSelector)&&loginCaption.test(shortText(e)));
 if(loginRoute||password||loginHeading||loginDialog)return result('login_required');
 return result('ready');
}'''
