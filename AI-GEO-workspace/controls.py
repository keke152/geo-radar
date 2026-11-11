"""Read-only DOM diagnostics: never fill editors, click controls or infer login."""

DOUBAO_EMPTY_HOME_SCAN=r'''()=>{
 const visible=e=>!!e&&!!e.getBoundingClientRect().width&&!!e.getBoundingClientRect().height&&getComputedStyle(e).visibility!=='hidden';
 const input=[...document.querySelectorAll('[data-testid="chat_input"] textarea,[data-testid="chat_input"] [contenteditable=true]')].find(visible);
 const welcome=[...document.querySelectorAll('h1,h2,h3,[role=heading],[class*=welcome],[class*=title]')].some(e=>visible(e)&&(e.innerText||'').trim()==='有什么我能帮你的吗？');
 const messages=[...document.querySelectorAll('[data-message-role="user"],[data-message-role="assistant"],[data-testid="message_text_content"]')].some(visible);
 return !!input&&welcome&&!messages;
}'''

CONTROL_SCAN=r'''({config,include_candidates=false})=>{
 const visible=e=>!!e&&!!e.getBoundingClientRect().width&&!!e.getBoundingClientRect().height&&getComputedStyle(e).visibility!=='hidden';
 const editor=e=>!!e&&(e.matches('textarea,input:not([type]),input[type=text],input[type=search]')||e.isContentEditable);
 const attr=e=>Object.fromEntries(['id','class','data-testid','aria-label','title','placeholder','role','type','disabled','aria-disabled','contenteditable','data-placeholder','data-slate-placeholder','data-slate-editor','data-lexical-editor','aria-hidden'].filter(k=>e.hasAttribute(k)).map(k=>[k,e.getAttribute(k)]));
 const label=e=>[e.getAttribute('data-testid'),e.id,e.getAttribute('aria-label'),e.getAttribute('title'),typeof e.className==='string'?e.className:'',e.textContent?.trim().slice(0,55)].filter(Boolean).join(' ');
 const selector=e=>{
  const tag=e.tagName.toLowerCase();
  for(const key of ['data-testid','aria-label','title','placeholder']){
   const value=e.getAttribute(key);if(!value||value.length>140)continue;
   const css=tag+'['+key+'='+JSON.stringify(value)+']';if(document.querySelectorAll(css).length===1)return css;
  }
  if(e.id&&document.querySelectorAll('#'+CSS.escape(e.id)).length===1)return '#'+CSS.escape(e.id);
  const classes=[...e.classList].filter(s=>/^[a-zA-Z_][a-zA-Z0-9_-]*$/.test(s)&&!/(^|[-_])(disabled|active|loading|hover|selected)([-_]|$)/i.test(s));
  for(const name of classes){const css=tag+'.'+CSS.escape(name);if(document.querySelectorAll(css).length===1)return css;}
  let node=e,parts=[];while(node&&node!==document.body){let n=1;for(let s=node.previousElementSibling;s;s=s.previousElementSibling)if(s.tagName===node.tagName)n++;parts.unshift(node.tagName.toLowerCase()+':nth-of-type('+n+')');node=node.parentElement;}
  return 'body > '+parts.join(' > ');
 };
 const action=e=>{
  for(let node=e,depth=0;node&&node!==document.body&&depth<7;node=node.parentElement,depth++){
   if(editor(node))return null;
   if(node.matches('button,[role=button],a[href],input[type=submit],input[type=button]'))return node;
   const name=typeof node.className==='string'?node.className:'';
   if(node.tagName.toLowerCase()!=='svg'&&node.tagName.toLowerCase()!=='path'&&(/send|submit|enter[-_](button|icon)|icon[-_]?(button|btn)|(^|[-_ ])btn([-_ ]|$)|button/i.test(name)||node.onclick)&&(getComputedStyle(node).cursor==='pointer'||node.getAttribute('aria-disabled')==='true'||/disabled/i.test(name)||getComputedStyle(node).pointerEvents==='none'))return node;
  }
  return null;
 };
 const disabled=e=>!!(e.disabled||e.getAttribute('aria-disabled')==='true'||/(^|[ _-])disabled([ _-]|$)/i.test(typeof e.className==='string'?e.className:'')||getComputedStyle(e).pointerEvents==='none');
 const meta=e=>({tag:e.tagName.toLowerCase(),attrs:attr(e),selector:selector(e)});
 const editors=[...document.querySelectorAll('textarea,input:not([type]),input[type=text],[contenteditable=true]')].filter(e=>visible(e)&&editor(e)&&!e.disabled&&!e.readOnly&&!/搜索|search/i.test((e.getAttribute('placeholder')||'')+' '+(e.getAttribute('aria-label')||'')));
 let composer=null;
 try{composer=[...document.querySelectorAll(config.composer||'textarea,[contenteditable=true]')].find(visible)||null;}catch{}
 const composerEditable=!!composer&&editor(composer)&&!composer.disabled&&!composer.readOnly;
 // Read semantic editor content without deleting or changing any DOM. Rich
 // editors often render their grey hint as real text alongside zero-width
 // scaffolding; it is not an unsent draft. Explicit chips/attachments ARE.
 const meaningful=s=>String(s||'').replace(/[\u200B\uFEFF]/g,'').trim();
 const decoration=e=>!!e.closest('[data-slate-placeholder], [data-lexical-placeholder], [data-editor-placeholder], [data-placeholder-node]')||
  !!e.closest('[aria-hidden=true][class*=placeholder], [aria-hidden=true][class*=Placeholder], [contenteditable=false][class*=placeholder], [contenteditable=false][class*=Placeholder]');
 const hasDraft=e=>{
  if(!e)return false;
  if(typeof e.value==='string')return !!meaningful(e.value);
  const walker=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);
  let node;while(node=walker.nextNode()){
   const parent=node.parentElement;if(!parent||decoration(parent))continue;
   if(getComputedStyle(parent).display==='none'||getComputedStyle(parent).visibility==='hidden')continue;
   if(meaningful(node.nodeValue))return true;
  }
  return [...e.querySelectorAll('img,video,audio,[data-attachment],[data-mention],[contenteditable=false]')].some(n=>!decoration(n)&&visible(n));
 };
 const empty=!hasDraft(composer);
 const inspect=(css,kind)=>{
  if(kind==='send_button'&&!css&&config.send_key)return {state:'shortcut',message:'使用 '+config.send_key+' 快捷键（未点击发送）',found:false,enabled:false};
  if(!css)return {state:'unconfigured',message:kind==='reply_selector'?'未配置（可选）':'尚未配置',found:false,enabled:false};
  let nodes;try{nodes=[...document.querySelectorAll(css)];}catch{return {state:'invalid',message:'规则格式无效，请重新识别',found:false,enabled:false};}
  const el=nodes.find(visible);
  if(!el)return {state:nodes.length?'hidden':kind==='send_button'&&empty?'missing_when_empty':'missing',message:nodes.length?'控件暂未显示':kind==='send_button'&&empty?'空输入时未找到，输入文字后再检查':'未找到，请重新识别',found:false,enabled:false};
  if(kind==='composer')return {state:composerEditable?'found':'wrong_target',message:composerEditable?'已找到可编辑输入框':'选中区域不能输入，请重新识别',found:composerEditable,enabled:composerEditable,selector:selector(el)};
  if(kind==='reply_selector')return {state:editor(el)?'wrong_target':'found',message:editor(el)?'选中了输入框，请重新标定回答区域':'已找到区域，仍需实际回答验证',found:!editor(el),enabled:true,selector:selector(el)};
  const target=action(el);
  if(!target)return {state:'wrong_target',message:editor(el)?'选中了输入框，并非发送按钮':'只命中图标或普通区域，请选择外层按钮',found:false,enabled:false,tag:el.tagName.toLowerCase()};
  const inactive=disabled(target);
  return {state:inactive?(empty&&kind==='send_button'?'awaiting_text':'disabled'):'found',message:inactive?(empty&&kind==='send_button'?'按钮已找到，输入文字后才启用':'按钮已找到，当前不可用'):'已找到可点击控件',found:true,enabled:!inactive,selector:selector(target),normalized:target!==el,tag:target.tagName.toLowerCase()};
 };
 const controls=Object.fromEntries(['composer','send_button','new_chat_selector','reply_selector'].map(key=>[key,inspect(config[key]||'',key)]));
 const rect=composer?.getBoundingClientRect();
 const suggestions={};
 if(controls.send_button.normalized)suggestions.send_button=controls.send_button.selector;
 if(controls.new_chat_selector.normalized)suggestions.new_chat_selector=controls.new_chat_selector.selector;
 const candidateNodes=[...document.querySelectorAll('button,[role=button],a[href],[class*=send],[class*=Send],[class*=submit],[class*=Submit],[aria-label],[title],svg use')];
 const actions=[...new Set(candidateNodes.filter(visible).map(action).filter(Boolean))];
 const send=actions.filter(e=>/send|发送|submit|enter[-_](button|icon)/i.test(label(e))&&!/upload|share|上传|分享|转发|发送文件|发送给/i.test(label(e)));
 const fresh=actions.filter(e=>/新对话|新建对话|开启新对话|new[-_ ]?chat|create[-_ ]?conversation/i.test(label(e)));
 if(editors.length===1)suggestions.composer=selector(editors[0]);
 if(send.length===1&&!controls.send_button.found)suggestions.send_button=selector(send[0]);
 if(fresh.length===1&&!controls.new_chat_selector.found)suggestions.new_chat_selector=selector(fresh[0]);
 const result={composer_found:!!composer,composer_editable:composerEditable,composer_in_view:!!rect&&rect.top>=0&&rect.left>=0&&rect.bottom<=innerHeight&&rect.right<=innerWidth,
  composer_empty:empty,viewport:{width:innerWidth,height:innerHeight},composer_box:rect?{x:Math.round(rect.x),y:Math.round(rect.y),width:Math.round(rect.width),height:Math.round(rect.height)}:null,
  send_found:controls.send_button.found,send_enabled:controls.send_button.enabled,send_state:controls.send_button.state,new_chat_found:controls.new_chat_selector.found,reply_found:controls.reply_selector.found,controls,suggestions};
 if(include_candidates){
  // Structural diagnostics deliberately exclude draft text. A nonempty editor
  // may contain real user content, an old task, or decorative placeholder DOM.
  // Lengths and explicit placeholder markers let the local connection guide
  // distinguish these cases without putting the draft into logs/bootstrap.
  const raw=composer?(composer.value??composer.innerText??''):'';
  result.composer_diagnostics=composer?{tag:composer.tagName.toLowerCase(),attrs:attr(composer),value_chars:typeof composer.value==='string'?composer.value.length:null,inner_text_chars:(composer.innerText||'').length,text_content_chars:(composer.textContent||'').length,raw_trimmed_chars:raw.trim().length,editable_descendants:[...composer.querySelectorAll('textarea,input,[contenteditable=true]')].slice(0,6).map(meta),placeholder_nodes:[...composer.querySelectorAll('[data-placeholder],[data-slate-placeholder],[placeholder],[aria-hidden=true]')].slice(0,16).map(e=>({...meta(e),text_chars:(e.textContent||'').length,text_equals_placeholder:!!e.getAttribute('data-placeholder')&&(e.textContent||'').trim()===e.getAttribute('data-placeholder').trim(),editable:e.isContentEditable}))}:null;
  let area=composer;for(let depth=0;area?.parentElement&&depth<4;depth++){if(area.querySelector('button,[role=button],svg'))break;area=area.parentElement;}
  result.candidates={editors:editors.slice(0,6).map(meta),send:send.slice(0,8).map(meta),new_chat:fresh.slice(0,6).map(meta),near_editor:area?[...area.querySelectorAll('button,[role=button],[class*=icon],svg')].slice(0,24).map(meta):[],configured_send:config.send_button?[...(()=>{try{return document.querySelectorAll(config.send_button)}catch{return []}})()].slice(0,1).map(e=>({element:meta(e),ancestors:[e.parentElement,e.parentElement?.parentElement].filter(Boolean).map(meta)})):[]};
 }
 return result;
}'''
