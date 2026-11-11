"""Bounded read-only reply association and completion evidence."""
import json
from config import ROOT

def patterns(pid):
    data=json.loads((ROOT/'response_patterns.json').read_text(encoding='utf-8'))
    return {**data['default'],**data.get(pid,{})}

RESPONSE_SCAN=r'''({prompt,pattern,reply_selector='',baseline=null,diagnostic=false})=>{
 const norm=s=>(s||'').replace(/\s+/g,'').trim();
 const visible=e=>!!e&&!!e.getBoundingClientRect().width&&!!e.getBoundingClientRect().height&&getComputedStyle(e).visibility!=='hidden';
 const find=(root,css)=>{try{return [...root.querySelectorAll(css)].filter(visible)}catch{return []}};
 const roots=css=>{const list=find(document,css);return list.filter(e=>!list.some(p=>p!==e&&p.contains(e)));};
 const expected=norm(prompt);
 const hasPrompt=e=>!!expected&&!e.isContentEditable&&!e.closest('textarea,[contenteditable=true]')&&(norm(e.innerText)===expected||find(e,'div,p,span').slice(0,400).some(c=>norm(c.innerText)===expected));
 let users=roots(pattern.user);const assistants=roots(pattern.assistant);
 let singlePageBound=false,singlePageContext='';
 if(pattern.single_question_path){
  const exact=users.filter(e=>hasPrompt(e)&&!(pattern.user_exclude&&e.closest(pattern.user_exclude)));
  const canonical=new RegExp(pattern.single_question_path).test(location.pathname);
  // Zhihu can finish a one-question response without replacing /search?q=...
  // with a numeric conversation URL. Bind this form only when the single query
  // value is the complete original prompt; a keyword-only URL is insufficient.
  const values=pattern.single_question_query_param?new URLSearchParams(location.search).getAll(pattern.single_question_query_param):[];
  const queryBound=!!pattern.single_question_query_path&&new RegExp(pattern.single_question_query_path).test(location.pathname)&&values.length===1&&!!expected&&norm(values[0])===expected;
  singlePageContext=canonical?'canonical_id':queryBound?'exact_prompt_query':'unsupported';
  singlePageBound=(canonical||queryBound)&&assistants.length===1&&exact.length===1;
  users=singlePageBound?exact:[];
 }
 let user=null,index=-1;for(let i=users.length-1;i>=0;i--){if(hasPrompt(users[i])){user=users[i];index=i;break;}}
 const attr=e=>({tag:e.tagName.toLowerCase(),class:(typeof e.className==='string'?e.className:'').slice(0,180),role:e.getAttribute('role'),data_role:e.getAttribute('data-role'),message_role:e.getAttribute('data-message-role'),testid:e.getAttribute('data-testid')});
 if(diagnostic){
  // Metadata only: never return reply/prompt excerpts, editor contents, HTML,
  // storage, or account state. Hidden/virtualized rows need separate counts.
  const raw=(root,css)=>{try{return [...root.querySelectorAll(css)]}catch{return []}};
  const bounded=(list,limit)=>list.length<=limit?list:[...list.slice(0,Math.floor(limit/3)),...list.slice(-(limit-Math.floor(limit/3)))];
  const editor=e=>e.matches('input,textarea')||e.isContentEditable||!!e.closest('[contenteditable=true]');
  const promptFlags=e=>{if(editor(e))return {editor_excluded:true};const inner=norm(e.innerText),full=norm(e.textContent);return {inner_text_exact:!!expected&&inner===expected,text_content_exact:!!expected&&full===expected,inner_text_contains:!!expected&&inner.includes(expected),text_content_contains:!!expected&&full.includes(expected)};};
  const meta=e=>{const rect=e.getBoundingClientRect();return {...attr(e),id:(e.id||'').slice(0,120),message_id:(e.getAttribute('data-message-id')||'').slice(0,120),msg_id:(e.getAttribute('data-msg-id')||'').slice(0,120),item_key:(e.getAttribute('data-item-key')||'').slice(0,120),index:(e.getAttribute('data-index')||'').slice(0,80),aria_posinset:e.getAttribute('aria-posinset'),visible:visible(e),in_viewport:rect.bottom>0&&rect.right>0&&rect.top<innerHeight&&rect.left<innerWidth,...promptFlags(e)};};
  const describe=e=>({...meta(e),aria_label_present:e.hasAttribute('aria-label'),title_present:e.hasAttribute('title'),icon:(e.getAttribute('data-icon')||'').slice(0,100),chars:editor(e)?null:(e.innerText||'').length,text_content_chars:editor(e)?null:(e.textContent||'').length});
  const rawUsers=raw(document,pattern.user),rawAssistants=raw(document,pattern.assistant);
  const lists=raw(document,'[data-testid="message-list"]');
  const scrollMeta=e=>{const overflow=getComputedStyle(e).overflowY;return {...meta(e),scroll_height:e.scrollHeight,client_height:e.clientHeight,scroll_top:e.scrollTop,overflow_y:overflow,scrollable_y:e.clientHeight>0&&e.scrollHeight>e.clientHeight+2&&(['auto','scroll','overlay'].includes(overflow)||e===document.scrollingElement),message_list_relations:lists.slice(0,5).map((list,index)=>({index,relation:e===list?'self':e.contains(list)?'ancestor':list.contains(e)?'descendant':'unrelated'}))};};
  const nodeSelector='[data-message-role],[data-role],[data-testid],[role],[class*="union_message"],[class*="v_list_row"]';
  const listMetadata=lists.slice(0,5).map(list=>{const descendants=raw(list,nodeSelector);let ancestor=list.parentElement;const ancestors=[];for(let depth=0;ancestor&&depth<12;depth++,ancestor=ancestor.parentElement)ancestors.push(scrollMeta(ancestor));return {root:scrollMeta(list),node_count:descendants.length,nodes:bounded(descendants,180).map(e=>({...describe(e),...scrollMeta(e)})),ancestors};});
  const scrollContainers=bounded(raw(document,'*').filter(e=>{const overflow=getComputedStyle(e).overflowY;return visible(e)&&e.clientHeight>0&&e.scrollHeight>e.clientHeight+2&&(['auto','scroll','overlay'].includes(overflow)||e===document.scrollingElement);}),24).map(scrollMeta);
  const nodes=find(document,"[data-message-role],[data-role],[class*=markdown],[class*=message],[class*=segment],[class*=answer],[class*=agent-chat]").filter(e=>!editor(e)&&(e.innerText||'').trim().length>30).slice(-100);
  const payload=norm(prompt.split('\n问题：').at(-1));
  const questions=raw(document,'h1,h2,[role=heading],div,p,span').filter(e=>{if(editor(e))return false;const inner=norm(e.innerText),full=norm(e.textContent);return (expected&&(inner===expected||full===expected))||(payload&&(inner===payload||full===payload));}).slice(-30).map(e=>({...describe(e),exact_prompt:norm(e.innerText)===expected,ancestors:[e.parentElement,e.parentElement?.parentElement].filter(Boolean).map(meta)}));
  return {users:users.length,assistants:assistants.length,raw_user_count:rawUsers.length,visible_user_count:rawUsers.filter(visible).length,raw_assistant_count:rawAssistants.length,visible_assistant_count:rawAssistants.filter(visible).length,prompt_matched:!!user,single_page_bound:singlePageBound,single_page_context:singlePageContext,message_lists:listMetadata,scroll_containers:scrollContainers,question_candidates:questions,page_controls:find(document,'[data-testid],button,[role=button],[aria-label],[title]').slice(-200).map(describe),candidates:nodes.map(e=>({...describe(e),has_prompt:hasPrompt(e),ancestors:[e.parentElement,e.parentElement?.parentElement].filter(Boolean).map(meta)})),assistant_details:assistants.slice(-2).map(e=>({root:describe(e),nodes:[...e.querySelectorAll('div,section,article,button,svg,use,[role=button]')].filter(visible).slice(-130).map(describe),ancestor_controls:[e.parentElement,e.parentElement?.parentElement].filter(Boolean).map(p=>({root:describe(p),nodes:[...p.querySelectorAll('button,svg,use,[role=button],.ds-icon-button,.icon-button')].filter(visible).slice(-80).map(describe)}))}))};
 }
 const result={user_count:users.length,assistant_count:assistants.length,matched:false,answer:'',links:[],association:'none',busy:false,done:false,later_turns:false,user_index:index};
 if(!user)return {...result,capture_issue:users.length?'未找到与完整提示词精确对应的提问；当前挂载内容可能被折叠或属于其他轮次':'未发现已挂载的提问节点；会话可能采用虚拟列表，不能仅凭可见回答确认归属'};
 if(baseline&&index<baseline.user_count)return result;
 const after=assistants.filter(e=>!e.contains(user)&&!!(user.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING));
 const candidate=after[0];if(!candidate)return {...result,capture_issue:'已找到完整提问，但尚未发现其后的回答节点；回答可能未挂载或仍在生成'};
 const nextUser=users[index+1];
 if(nextUser&&!!(candidate.compareDocumentPosition(nextUser)&Node.DOCUMENT_POSITION_PRECEDING))return result;
 const contents=find(candidate,pattern.content);
 if(pattern.require_content&&!contents.length)return {...result,capture_issue:'未发现最终回答区域；思考和工具过程不作为回答'};
 let content=contents[0]||candidate;
 const clone=content.cloneNode(true);clone.querySelectorAll('button,textarea,input,[aria-hidden=true]').forEach(e=>e.remove());
 const textOf=n=>n.nodeType===Node.TEXT_NODE?n.textContent:n.nodeType===Node.ELEMENT_NODE?(n.tagName==='BR'?'\n':Array.from(n.childNodes).map(textOf).join('')+(/^(P|DIV|LI|TR|H[1-6]|PRE|BLOCKQUOTE)$/.test(n.tagName)?'\n':'')):'';
 const answer=textOf(clone).replace(/\n{3,}/g,'\n\n').trim();
 if(!answer||norm(answer)===expected||norm(answer).includes(expected))return result;
 const labels=e=>[e.getAttribute('aria-label'),e.getAttribute('title'),e.getAttribute('data-testid'),typeof e.className==='string'?e.className:'',e.innerText?.trim().slice(0,40)].filter(Boolean).join(' ');
 const controls=find(document,'button,[role=button],[aria-label],[title],[data-testid]');
 result.busy=controls.some(e=>/停止生成|停止回答|停止输出|stop[ _-]?(generating|response)|stop[-_](button|btn)/i.test(labels(e))&&!e.disabled);
 let scope=candidate;
 for(let depth=0;depth<2&&scope.parentElement;depth++){
  const parent=scope.parentElement;
  if(find(parent,pattern.user).length||find(parent,pattern.assistant).filter(e=>e!==candidate&&!candidate.contains(e)).length>1)break;
  scope=parent;
 }
 result.done=find(scope,'button,[role=button],[aria-label],[title]').some(e=>!content.contains(e)&&/复制|copy|重新生成|重新回答|regenerate|赞同|不赞同|点赞|点踩/i.test(labels(e))&&!e.disabled)
  ||(!!pattern.done&&find(singlePageBound?document:candidate,pattern.done).length>0)
  ||/^(complete|completed|finished|success|done)$/.test(candidate.getAttribute('data-status')||'');
 return {...result,matched:true,answer:answer.slice(0,100000),association:'structured',links:[...content.querySelectorAll('a[href]')].map(e=>e.href).filter(u=>/^https?:\/\//.test(u)),later_turns:!!nextUser};
}'''

def automatic_verification(result,enabled=True):
    """Validate capture mechanics only; never assert recommendation truth."""
    if not enabled:return False,'已关闭自动校验'
    if not result.get('answer','').strip():return False,'尚未取得非空回答'
    if not result.get('matched') or result.get('association')!='structured':return False,'无法可靠绑定这次问题与回答'
    if result.get('later_turns'):return False,'会话出现后续提问，需要检查上下文'
    if result.get('busy') or not result.get('done') or not result.get('stable'):return False,'回答结束状态尚未确认'
    return True,'已自动校验问题对应关系、非空回答与生成结束状态；未核实回答中的事实、来源真实性或推荐排名'
