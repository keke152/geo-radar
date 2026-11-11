const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data=null,initialized=false,pickTimer=null,pickPlatform=null,batchKey=crypto.randomUUID(),toastTimer,loading=false,modalRevision=0,taskModalRequest=0,pendingTaskModal=null;
const connectingPlatforms=new Set();
const labels={queued:'待执行',running:'执行中',waiting_setup:'待配置',needs_review:'待核对',sent:'已发送，回答未确认',completed:'已记录回答',failed:'执行失败',interrupted:'执行中断',uncertain:'结果不确定',cancelled:'已取消'};
const channelLabel=c=>({web:'消费端网页',api:'官方API'}[c]||c);
const views={home:'产品介绍',overview:'任务',insights:'统计',keywords:'关键词',materials:'资料',platforms:'平台',results:'记录',schedule:'计划',company:'设置'};
async function api(url,options={}){return WorkspaceConnection.request(url,{...options,headers:{'X-Workspace-Request':'junhe-local',...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...options.headers}});}
const post=(url,body={})=>api(url,{method:'POST',body:JSON.stringify(body)});
const put=(url,body)=>api(url,{method:'PUT',body:JSON.stringify(body)});
function toast(s){if(WorkspaceConnection.isNetworkMessage(s))return;clearTimeout(toastTimer);$('#toast').textContent=s;$('#toast').classList.add('show');toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),5000);}
function showModal(title,body){modalRevision++;taskModalRequest++;pendingTaskModal=null;$('#modal-title').textContent=title;$('#modal-body').innerHTML=body;$('#modal').showModal();}
$('#modal-close').onclick=()=>$('#modal').close();
// Invalidate before the native close event is queued, so a rapid new detail
// request is not cancelled later by the previous dialog's delayed close event.
$('#modal').addEventListener('beforetoggle',event=>{if(event.newState==='closed'){modalRevision++;taskModalRequest++;pendingTaskModal=null;}});
$('#modal').addEventListener('close',()=>{cancelActivePick().catch(()=>{});});
function view(){let name=location.hash.slice(1)||'overview';if(!Object.hasOwn(views,name))name='overview';document.querySelectorAll('.view').forEach(s=>s.hidden=s.id!==name);document.querySelectorAll('[data-view]').forEach(a=>{a.classList.toggle('active',a.dataset.view===name);a.setAttribute('aria-current',a.dataset.view===name?'page':'false');a.title=views[a.dataset.view];});document.body.classList.toggle('landing-view',name==='home');$('#breadcrumb').textContent=views[name];document.title=views[name]+' · GEO Radar · 品牌雷达';window.scrollTo(0,0);document.querySelector('main>.content')?.scrollTo(0,0);window.onWorkspaceView?.(name);}
if('scrollRestoration' in history)history.scrollRestoration='manual';
addEventListener('hashchange',()=>{view();requestAnimationFrame(()=>window.scrollTo(0,0));});
addEventListener('load',()=>requestAnimationFrame(()=>window.scrollTo(0,0)));view();
function choices(container,defaults=true){const element=$(container);const previous=[...element.querySelectorAll('input:checked')].map(x=>x.value);const first=!element.childElementCount;element.innerHTML=data.platforms.map(p=>`<label class="platform-choice"><input type="checkbox" value="${p.id}" ${(first&&defaults)||previous.includes(p.id)?'checked':''}><span>${esc(p.name)}<small>${channelLabel(p.channel)}</small></span></label>`).join('');}
const selected=selector=>[...document.querySelectorAll(selector+' input:checked')].map(i=>i.value);
function taskStatusLabel(t){
 if(t.status==='completed'&&t.metrics?.verification_method==='automatic_dom')return '已自动校验';
 if(t.status==='completed'&&t.metrics?.verification_method==='human')return '已人工核对';
 if(t.status==='completed'&&t.metrics?.verification_method==='api_response')return 'API已返回';
 if(t.status==='queued'&&data.queue?.positions?.[t.id])return '同平台排队 · 第'+data.queue.positions[t.id]+'位';
 if(t.status==='uncertain'&&!t.sent_at)return '发送结果需核实';
 if(t.status==='needs_review'){
  const evidence=t.metrics?.capture_evidence;
  if(t.metrics?.answer_matched_to_prompt===false)return '回答待匹配';
  if(evidence&&(evidence.busy||!evidence.done||!evidence.stable))return '回答结束待确认';
 }
 if(t.status==='waiting_setup'){
  if(t.metrics?.execution_error?.retry_safe)return '准备未完成';
  const p=data.platforms.find(p=>p.id===t.platform);
  if(p?.channel==='web'&&p.browser_open)return '窗口已连接 · 待继续';
  if(p?.channel==='web'&&p.ready&&p.connection?.profile_saved)return '待恢复会话';
  if(/窗口未连接|专用浏览器|请先打开/.test(t.note))return '待连接';
 }
 return labels[t.status]||t.status;
}
function taskWaitDescription(t){
 if(t.status==='waiting_setup'&&t.metrics?.execution_error?.retry_safe)return t.note||'页面准备未完成，尚未触发发送。检查后可继续此任务。';
 if(t.status==='uncertain'&&!t.sent_at&&t.metrics?.execution_error?.type==='TimeoutError'&&!t.metrics.execution_error.stage_evidence_version)return '上次网页操作超时，旧版没有准确记录发送步骤。请检查原平台会话；不会自动重发。';
 if(['uncertain','interrupted'].includes(t.status))return t.sent_at?'已有发送记录，但回答尚未确认。请打开详情检查原会话；不会自动重发。':'未取得发送确认，也未保存回答；请先在平台查找这条问题。仅恢复连接不会重发。';
 if(t.status==='needs_review'&&t.metrics?.answer_matched_to_prompt===false)return '已经取得内容，但还未确认对应本次完整问题。可重新采集校验原回答，不会重发问题。';
 if(t.status==='needs_review')return t.metrics?.verification_note||t.note||'回答结束状态或上下文尚未确认，可检查原回答后重新校验。';
 if(t.status==='sent')return '已有发送记录，尚未取得完整回答。请检查原对话，再重新采集，不会重发问题。';
 if(t.status==='waiting_setup'){
  const p=data.platforms.find(p=>p.id===t.platform);
  if(p?.channel==='web'&&p.browser_open)return '窗口已经恢复。此任务尚未发送，点击“继续此任务”后检查并执行；不用重复创建。';
  if(p?.channel==='web'&&p.ready&&p.connection?.profile_saved)return '标定和本机登录资料已保存。点击“继续此任务”会尝试恢复窗口；登录过期时仍需本人处理。';
 }
 if(t.status!=='queued')return '';
 const q=data.queue;
 if(q?.state==='paused')return '队列已暂停，点击页面顶部“继续队列”后处理。';
 if(['error','not_started'].includes(q?.state)||q?.error)return q.error||'后台执行器未运行，请检查本地服务。';
 const position=q?.positions?.[t.id];
 if(position===1&&(q.platform_cooldowns?.[t.platform]||q.cooldown_seconds)>0)return '等待同平台发送间隔，约'+(q.platform_cooldowns?.[t.platform]||q.cooldown_seconds)+'秒；其他平台独立执行。';
 return position?'同一平台前面还有'+(position-1)+'条任务；不同平台可并行执行。':'等待可用的平台执行通道。';
}
function renderQueueStatus(){
 let box=$('#queue-status');if(!box){box=document.createElement('div');box.id='queue-status';box.className='queue-notice';box.setAttribute('role','status');$('#recent-tasks').before(box);}
 const q=data.queue;let message='正在读取后台队列状态…';
 if(q){
  if(q.error||['error','not_started'].includes(q.state))message=q.error||'后台执行器未运行，任务尚未开始，请检查本地服务。';
  else if(q.state==='paused')message=`队列已暂停，${q.queued}条任务等待继续。`;
  else if(q.state==='reconnecting')message=`正在恢复${data.platforms.find(p=>p.id===q.reconnecting_platform)?.name||'平台'}的已保存会话，尚未发送问题；其余任务按顺序等待。`;
  else if(q.state==='running')message=`${q.active_count||1}个平台正在并行处理（最多${q.parallel_limit||6}个），${q.queued}条等待所属平台可用。`;
  else if(q.state==='cooldown')message=`同平台发送间隔约剩${q.cooldown_seconds}秒；${q.queued}条任务等待，平台之间互不阻塞。`;
  else if(q.queued)message=`后台正在调度，共${q.queued}条待执行任务。`;
  else message=`当前没有待执行任务；${q.waiting_setup}条旧任务尚未继续，请查看各条提示后继续。`;
 }
 box.innerHTML=`<span>${esc(message)}</span><a class="text-link" href="#platforms">连接平台 →</a>`;
 box.classList.toggle('queue-warning',Boolean(q?.error||['error','not_started','paused'].includes(q?.state)));
}
function taskTable(tasks){if(!tasks.length)return '<div class="empty"><b>从连接第一个平台开始</b><p>打开专用Edge → 本人登录 → 标定控件并保存 → 创建任务</p><a class="btn primary" href="#platforms">连接平台 →</a></div>';return `<div class="table-wrap"><table class="task-table"><thead><tr><th>平台 / 通道</th><th>关键词 / 模式</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>${tasks.map(t=>{const p=data.platforms.find(p=>p.id===t.platform);return `<tr><td>${esc(p?.name||t.platform)}<small>${channelLabel(t.channel)}</small></td><td><div class="keyword">${esc(t.keyword)}</div><small>${t.mode==='visibility'?'搜索检查':'资料研读'}${t.metrics.brand_hint?' · 带品牌提示':''}${t.metrics.conversation_mode==='continue'?' · 连续会话（独立统计排除）':''}</small></td><td><span class="pill ${t.status==='completed'?'green':['failed','uncertain','interrupted'].includes(t.status)?'red':'amber'}">${esc(taskStatusLabel(t))}</span><small>${esc(t.status==='completed'?'完整回答已保存':taskWaitDescription(t)||t.note.slice(0,70))}</small></td><td>${new Date(t.created_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}</td><td><div class="row-actions"><button class="btn small" data-task="${t.id}">查看</button>${t.status==='waiting_setup'?`<button class="btn small" data-resume-task="${t.id}">继续此任务</button>`:''}</div></td></tr>`;}).join('')}</tbody></table></div>`;}
function renderTasks(){renderQueueStatus();if(window.refreshClientTasks)window.refreshClientTasks();else $('#recent-tasks').innerHTML=taskTable(data.tasks.slice(0,5));if(window.refreshTaskRecords)window.refreshTaskRecords();else{const filter=$('#task-filter').value;$('#task-list').innerHTML=taskTable(data.tasks.filter(t=>!filter||t.status===filter));}}
function render(){
 $('#web-samples').textContent=data.metrics.web.samples;$('#web-mentions').textContent=data.metrics.web.samples?data.metrics.web.brand_mentions+' / '+data.metrics.web.samples:'—';$('#api-samples').textContent=data.metrics.api.samples;$('#pending-count').textContent=data.tasks.filter(t=>['queued','waiting_setup'].includes(t.status)).length;
 $('#draft-count').textContent=data.documents.filter(d=>!d.approved).length;$('#service-state').textContent=data.settings.paused?'队列已暂停':data.queue?.error||data.queue?.state==='error'?'后台执行器异常':data.queue?.state==='reconnecting'?'正在恢复已保存会话':data.queue?.state==='cooldown'?'发送间隔等待中':'本地服务正常';$('#worker-label').textContent=data.queue?.active_count>1?data.queue.active_count+'个平台并行处理':data.current_task?'正在执行任务':data.queue?.state==='cooldown'?'间隔约'+data.queue.cooldown_seconds+'秒':data.queue?.queued?'等待调度 '+data.queue.queued+'条':'本机队列就绪';$('#pause-button').textContent=data.settings.paused?'继续队列':'暂停队列';
 choices('#batch-platforms');choices('#schedule-platforms');
 $('#keyword-list').innerHTML=data.keywords.map(k=>`<div class="list-row"><span class="pill">${esc(k.kind)}</span><div class="grow">${esc(k.text)}</div></div>`).join('')||'<div class="empty">暂无历史共享关键词</div>';
 $('#document-list').innerHTML=data.documents.map(d=>`<article class="document-card"><div class="actions"><span class="pill ${d.approved?'green':'amber'}">${d.approved?'允许对外发送':'待核验，不发送'}</span></div><h3>${esc(d.title)}</h3><p class="excerpt">${esc(d.body)}</p><p class="source">出处：${esc(d.source)}</p><div class="row-actions"><button class="btn small" data-edit-document="${d.id}">编辑与核验</button><button class="btn small" data-delete-document="${d.id}">移除</button></div></article>`).join('');
 $('#platform-list').innerHTML=data.platforms.map(p=>`<article class="platform-card"><div class="platform-top"><span class="platform-symbol">${esc(p.name.slice(0,2))}</span><div><h3>${esc(p.name)}</h3><small>${p.channel==='api'?'官方 API':'专用浏览器'}</small></div></div><p class="platform-status">${p.channel==='api'?(p.model&&p.key_configured?'API已配置 · 待实际调用验证':'待配置模型ID与本机Key'):connectingPlatforms.has(p.id)?'正在打开专用Edge，请稍候…':p.connection?.navigation_error?'浏览器已打开 · 网页加载待检查':p.browser_open?(p.ready?'已保存标定 · 执行前请确认登录有效':'已打开 · 请本人登录，再完成标定'):p.ready&&p.connection?.profile_saved?'标定已保存 · 当前窗口已断开，可恢复会话':'未连接 · 第一步：打开专用Edge'}</p><div class="connection-mini-steps"><span class="${p.browser_open?'done':''}">1 打开</span><span>2 本人登录</span><span class="${p.ready?'done':''}">3 标定保存</span></div><div class="row-actions">${p.channel==='web'?`<button class="btn light" data-connect="${p.id}" ${connectingPlatforms.has(p.id)?'disabled':''}>${connectingPlatforms.has(p.id)?'正在打开…':p.browser_open?'切换到登录窗口':p.ready&&p.connection?.profile_saved?'恢复连接':'打开登录'}</button>`:''}<button class="btn primary" data-configure="${p.id}">连接向导</button></div><p class="platform-hint">${p.api?'网页与API回答分别记录，不混同App搜索表现。':'当前仅保留网页，不以其他模型API替代。'}</p></article>`).join('');
 if(!initialized){const p=data.profile;$('#company-name').value=p.company_name;$('#company-domain').value=p.domain;$('#company-aliases').value=p.aliases.join('\n');$('#company-business').value=p.business;$('#company-audience').value=p.audience;$('#company-intro').value=p.public_intro;$('#audience-confirmed').checked=p.audience_confirmed;$('#interval').value=data.settings.interval_seconds;$('#daily-limit').value=data.settings.daily_limit;initialized=true;}
 renderTasks();window.renderImprovements?.();window.renderLanding?.(data);
 let notice=$('#scheduler-notice');
 if(data.scheduler_notice){
  if(!notice){notice=document.createElement('div');notice.id='scheduler-notice';notice.className='notice amber';$('#schedule').insertBefore(notice,$('#schedule .home-grid'));}
  notice.textContent='最近计划提示：'+data.scheduler_notice.message;
 }
}
let refreshTimer=0,refreshFailures=0;
function scheduleRefresh(delay){clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>{if(document.hidden){scheduleRefresh(6000);return;}load();},delay);}
async function load(){
 if(loading)return;clearTimeout(refreshTimer);loading=true;WorkspaceConnection.pending();
 try{const fresh=await api('/api/bootstrap');window.WorkspaceVersion?.check(fresh.version);data=fresh;render();refreshFailures=0;WorkspaceConnection.connected();}
 catch(e){refreshFailures++;WorkspaceConnection.show(e.message,e.code==='LOCAL_CONNECTION');}
 finally{loading=false;const delay=refreshFailures?Math.min(60000,6000*2**Math.min(refreshFailures-1,4)):6000;WorkspaceConnection.retryIn(delay);scheduleRefresh(delay);}
}
window.retryWorkspace=()=>load();
addEventListener('online',()=>{if(WorkspaceConnection.state.problem)load();});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
function guard(form,handler){form.addEventListener('submit',async event=>{event.preventDefault();if(!data||WorkspaceConnection.state.problem){WorkspaceConnection.show(WorkspaceConnection.state.offline?'本地服务尚未连接，请启动后重连；填写的内容会保留。':'工作台数据尚未就绪，请先点击“立即重连”；填写的内容会保留。',WorkspaceConnection.state.offline);return;}const button=form.querySelector('button[type=submit],button:not([type])');if(button?.disabled)return;if(button)button.disabled=true;try{await handler();window.WorkspaceVersion?.saved(form);}catch(e){toast(e.message);}finally{if(button)button.disabled=false;}});}
$('#pause-button').onclick=async()=>{try{await put('/api/settings',{...data.settings,paused:!data.settings.paused});await load();}catch(e){toast(e.message);}};
function documentModal(document={}){showModal(document.id?'资料核验':'新增资料',`<form id="document-form"><label>标题<input id="doc-title" required maxlength="160" value="${esc(document.title||'')}"></label><label>出处 / 页码<input id="doc-source" required maxlength="500" value="${esc(document.source||'')}"></label><label>内容<textarea id="doc-body" required maxlength="20000" rows="9">${esc(document.body||'')}</textarea></label><label class="check"><input type="checkbox" id="doc-approved" ${document.approved?'checked':''}>我已核对内容，允许将本条发送到所选外部平台</label><p>勾选后仅用于资料研读及内容草稿；资质、品牌关系和功效表述应有对应证据。</p><div class="form-footer"><button class="btn primary">保存资料</button></div></form>`);guard($('#document-form'),async()=>{const body={title:$('#doc-title').value,source:$('#doc-source').value,body:$('#doc-body').value,approved:$('#doc-approved').checked};if(document.id)await put('/api/documents/'+document.id,body);else await post('/api/documents',body);$('#modal').close();await load();});}
$('#add-document').onclick=()=>documentModal();
$('#document-file').onchange=async()=>{const file=$('#document-file').files[0];if(!file)return;const form=new FormData();form.append('file',file);toast('正在提取文字，较大PPTX需要一些时间…');try{const r=await api('/api/documents/import',{method:'POST',body:form});toast(r.message);await load();}catch(e){toast(e.message);}finally{$('#document-file').value='';}};
function connectionFeedback(message,isError=false){
 const box=$('#connection-feedback');if(!box)return;
 box.textContent=message;box.classList.toggle('connection-error',isError);
}
async function cancelActivePick(){
 clearInterval(pickTimer);pickTimer=null;
 const pid=pickPlatform;pickPlatform=null;
 if(pid)await post(`/api/platforms/${pid}/cancel-pick`);
}
function platformFormValue(){
 const value={channel:$('#cfg-channel').value,model:$('#cfg-model').value,send_key:$('#cfg-send_key').value,ready:$('#cfg-ready').checked,search_enabled:$('#cfg-search').checked};
 for(const key of ['composer','send_button','new_chat_selector','reply_selector'])value[key]=$('#cfg-'+key).value.trim();
 return value;
}
function saveFeedback(message,state='error'){
 const box=$('#save-feedback');if(!box)return;
 box.hidden=false;box.textContent=message;box.className='save-feedback '+state;
 if(state==='error')box.focus({preventScroll:true});
}
function controlFingerprint(){return JSON.stringify(['composer','send_button','new_chat_selector','reply_selector','send_key'].map(key=>$('#cfg-'+key)?.value||''));}
function refreshCalibrationStatus(inspection=null){
 const form=$('#platform-form');if(!form)return;
 if(inspection)form._inspection={result:inspection,fingerprint:controlFingerprint()};
 const result=form._inspection?.fingerprint===controlFingerprint()?form._inspection.result:null;
 const fields={composer:'输入框',send_button:'发送方式',new_chat_selector:'新对话',reply_selector:'回答区域'};
 for(const [key,title] of Object.entries(fields)){
  const el=$('#status-'+key);if(!el)continue;
  const configured=Boolean($('#cfg-'+key).value.trim());
  const shortcut=key==='send_button'&&$('#cfg-send_key').value;
  const checked=result?.controls?.[key];
  const optionalReplyMissing=key==='reply_selector'&&checked&&['missing','hidden'].includes(checked.state);
  el.textContent=title+'：'+(optionalReplyMissing?'当前页未匹配，出现回答后再检查（可选）':checked?.message|| (shortcut?'使用 '+shortcut+' 快捷键':configured?'规则已填写，尚未检测':'尚未配置'+(key==='reply_selector'?'（可选）':'')));
  el.classList.toggle('done',Boolean(checked?.found));el.classList.toggle('pending',!checked||optionalReplyMissing||['shortcut','awaiting_text','missing_when_empty','hidden'].includes(checked.state));
  el.classList.toggle('invalid',Boolean(checked&&['wrong_target','invalid','missing','unconfigured','disabled'].includes(checked.state)&&key!=='reply_selector'));
 }
 if(!$('#connection-states'))return;
 const p=data.platforms.find(p=>p.id===form.dataset.platformId),opened=result?result.open:p?.browser_open;
 $('#connection-states').innerHTML=`<span class="${opened?'done':''}">窗口：${opened?'已连接':'未连接'}</span><span class="${result?.composer_editable?'done':''}">输入框：${result?result.composer_editable?'可用':'未就绪':'待检查'}</span><span class="${form._loginConfirmed?'done':''}">登录：${form._loginConfirmed?'你已确认':'由本人确认'}</span><span>发送：${$('#cfg-send_key').value?'使用 '+esc($('#cfg-send_key').value):result?.controls?.send_button?.message||'待第三步检查'}</span>`;
 const steps=form.querySelectorAll('.connection-steps li');steps[0]?.classList.toggle('complete',Boolean(opened));steps[1]?.classList.toggle('complete',Boolean(form._loginConfirmed&&result?.composer_editable));
}
function configModal(pid){
 cancelActivePick().catch(()=>{});
 const p=data.platforms.find(p=>p.id===pid);
 const initial=p.browser_open?'专用窗口已连接，标定规则仍在。请检查当前登录和控件；旧任务可在记录中继续，无需重复创建。':p.ready&&p.connection?.profile_saved?'标定配置和本机登录资料仍在，当前窗口已断开。点击第一步恢复原会话；不需要重新填写规则。':'点击“打开登录窗口”，系统会另开一个专用Edge窗口。请在该窗口登录，然后回到这里。';
 showModal(p.name+' · 连接向导',`<form id="platform-form" data-platform-id="${pid}">
  <label>选择接入方式<select id="cfg-channel"><option value="web" ${p.channel==='web'?'selected':''}>网页：专用Edge登录后自动发送</option>${p.api?`<option value="api" ${p.channel==='api'?'selected':''}>API：配置自己的Key与模型</option>`:''}</select></label>
  <div id="web-guide" ${p.channel==='api'?'hidden':''}>
   <ol class="connection-steps"><li><b>1</b><span>打开窗口</span></li><li><b>2</b><span>本人登录</span></li><li><b>3</b><span>点选标定</span></li><li><b>4</b><span>保存连接</span></li></ol>
   <div id="connection-feedback" class="connection-feedback" role="status">${esc(initial)}</div>
   <div id="connection-states" class="connection-states" aria-label="各阶段连接状态"></div>
   <section class="guide-section"><h3>第一步：打开独立的登录窗口</h3><p>不是当前工作台内的弹窗。请留意Windows任务栏里的新Edge窗口；这里不会读取你普通浏览器的登录。</p><div class="pick-row"><button type="button" class="btn primary" data-connect="${pid}">${p.ready&&p.connection?.profile_saved?'恢复已保存会话':'打开登录窗口'}</button><button type="button" class="btn light" id="close-platform">关闭专用窗口</button></div></section>
   <section class="guide-section"><h3>第二步：在新窗口中本人登录</h3><p>选择自己的账号，完成短信、扫码或安全验证。回到问答页后检查页面。专用窗口现在按实际窗口大小显示。</p><div class="pick-row"><button type="button" class="btn light" id="inspect-platform">我已登录，检查页面</button><button type="button" class="btn light" id="reveal-composer">看不到输入框？定位输入框</button></div><p id="guide-inspect">定位只滚动到输入区域，不输入文字、不发送内容。检测到输入框也不等于账号已登录。</p></section>
   <section class="guide-section"><h3>第三步：识别输入和发送控件</h3><p>优先自动识别，再检查控件是否可用。需要手动点选时，点击下面对应按钮并切换到专用Edge。按ESC或点“取消标定”恢复网页正常点击。</p><div class="pick-row"><button type="button" class="btn primary" id="detect-controls">自动识别控件（不发送）</button><button type="button" class="btn light" id="inspect-controls">检查发送与新对话</button></div><div class="pick-row">${[['composer','① 输入框'],['send_button','② 发送按钮'],['new_chat_selector','③ 新对话按钮'],['reply_selector','④ 回答区域（可选）']].map(([kind,title])=>`<button type="button" class="btn light" data-pick="${kind}">${title}</button>`).join('')}<button type="button" class="btn light" id="cancel-pick">取消标定</button></div><p id="pick-status" role="status">空输入时，某些平台会隐藏或禁用发送按钮。窗口已连接和发送控件未配置是两种状态。检查不会填入或发送文字。</p><div class="calibration-status">${['composer','send_button','new_chat_selector','reply_selector'].map(key=>`<span id="status-${key}"></span>`).join('')}</div>
   <label>发送方式：找不到发送按钮时，可选择平台支持的快捷键<select id="cfg-send_key"><option value="">使用标定的发送按钮</option><option value="Enter" ${p.send_key==='Enter'?'selected':''}>Enter 发送（请先确认平台支持）</option><option value="Control+Enter" ${p.send_key==='Control+Enter'?'selected':''}>Ctrl+Enter 发送（请先确认平台支持）</option></select></label>
   <details><summary>高级设置：查看或手动修改控件</summary>${[['composer','输入框'],['send_button','发送按钮'],['new_chat_selector','新对话按钮'],['reply_selector','单条AI回答区域']].map(([key,title])=>`<label>${title}<input id="cfg-${key}" value="${esc(p[key])}" maxlength="600"></label>`).join('')}</details>
   </section><section class="guide-section"><h3>第四步：确认并保存</h3><label class="check"><input type="checkbox" id="cfg-ready" ${p.ready?'checked':''}>我已本人登录并检查控件，允许任务自动发送</label><p>保存后回“每日任务”，先选这一个平台试一个关键词。窗口保持打开；需要联网搜索时请本人在平台中开启。</p></section>
  </div>
  <div id="api-guide" ${p.channel==='web'?'hidden':''}>
   <div class="notice"><span>API模式不需要打开网页登录。需要对应开放平台的Key和控制台有效模型ID，与消费端App回答分开记录。</span></div>
   <label>模型ID<input id="cfg-model" value="${esc(p.model)}" placeholder="从对应平台控制台复制模型ID"></label>
   <p>${p.env?`本机变量：<b>${esc(p.env)}</b> · ${p.key_configured?'已配置Key':'尚未配置Key'}。复制项目.env.example为.env，在本机填写Key，重启服务。不要将Key放进任务或资料。`:'此平台暂未配置API通道。'}</p>
   <label class="check"><input type="checkbox" id="cfg-search" ${p.search_enabled?'checked':''}>千问API启用联网搜索参数（需模型支持；其他平台不生效）</label>
   <a href="${esc(p.docs)}" target="_blank" rel="noopener" class="text-link">查看官方接入文档 ↗</a>
  </div>
  <div id="saved-summary" hidden></div>
  <div class="save-area"><div id="save-feedback" class="save-feedback" role="status" aria-live="polite" tabindex="-1" hidden></div><div class="form-footer"><button type="submit" class="btn primary" id="save-platform-config">保存连接配置</button><button type="button" class="btn light" id="return-to-tasks" hidden>回每日任务</button><span class="small-note">结果会显示在此处；保存不会创建新任务。</span></div></div>
 </form>`);
 const form=$('#platform-form'),current=()=>$('#platform-form')===form;
 refreshCalibrationStatus();
 $('#cfg-channel').onchange=()=>{const web=$('#cfg-channel').value==='web';$('#web-guide').hidden=!web;$('#api-guide').hidden=web;};
 $('#cfg-send_key').addEventListener('change',()=>{if($('#cfg-send_key').value)$('#cfg-send_button').value='';$('#cfg-ready').checked=false;refreshCalibrationStatus();});
 $('#platform-form').addEventListener('input',event=>{if(['cfg-composer','cfg-send_button','cfg-new_chat_selector','cfg-reply_selector'].includes(event.target.id))$('#cfg-ready').checked=false;$('#saved-summary').hidden=true;$('#return-to-tasks').hidden=true;refreshCalibrationStatus();saveFeedback('配置已修改，请检查后保存。','neutral');});
 $('#platform-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=$('#save-platform-config');if(button.disabled)return;
  button.disabled=true;button.textContent='正在核对并保存…';saveFeedback('正在保存，请稍候…','neutral');
  $('#saved-summary').hidden=true;$('#return-to-tasks').hidden=true;
  try{
   await cancelActivePick();const body=platformFormValue();
   if(body.channel==='web'&&body.ready&&(!body.composer||(!body.send_button&&!body.send_key)))throw new Error('尚未保存：缺少'+(!body.composer?'输入框；':'')+(!body.send_button&&!body.send_key?'发送按钮或快捷键。':'')+'请完成标定，或取消勾选允许自动发送，先保存草稿。');
   const result=await put('/api/platforms/'+pid,body);if(!current()){await load();return;}
   const stamp=new Date(result.saved_at).toLocaleString('zh-CN');
   saveFeedback(result.message+' · '+stamp,'success');
   const cfg=result.config,missing=result.readiness.missing;
   for(const key of ['composer','send_button','new_chat_selector','reply_selector'])$('#cfg-'+key).value=cfg[key];
   if(result.inspection)refreshCalibrationStatus(result.inspection);
   $('#saved-summary').innerHTML=`<h3>已保存的配置</h3><dl class="saved-config"><dt>平台 / 通道</dt><dd>${esc(p.name)} / ${cfg.channel==='web'?'专用Edge网页':'API'}</dd><dt>自动发送</dt><dd>${result.readiness.enabled?'已启用（本人已确认）':cfg.channel==='api'?'通过API任务调用':'未启用，当前为草稿'}</dd><dt>发送方式</dt><dd>${esc(cfg.send_button?'已记录发送按钮':cfg.send_key||'尚未配置')}</dd><dt>搜索检查</dt><dd>${result.readiness.visibility_ready?'配置已就绪，先测试一个关键词':esc(cfg.channel==='api'?'API与网页分别统计':missing.length?'仍需：'+missing.join('、'):'请勾选允许自动发送后保存')}</dd></dl><details><summary>查看保存的规则值</summary><pre class="prompt-box">${esc(JSON.stringify(cfg,null,2))}</pre></details>`;
   $('#saved-summary').hidden=false;$('#return-to-tasks').hidden=false;
   await load();
  }catch(error){saveFeedback(error.message,'error');}
  finally{button.disabled=false;button.textContent='保存连接配置';}
 });
 $('#return-to-tasks').onclick=()=>{$('#modal').close();location.hash='#overview';};
 async function inspectCurrent(confirmLogin=false){
  if(!current()||form._checking)return;form._checking=true;
  const buttons=[$('#inspect-platform'),$('#inspect-controls')];buttons.forEach(b=>b.disabled=true);
  const fingerprint=controlFingerprint();
  try{const r=await post(`/api/platforms/${pid}/inspect`,{config:platformFormValue()});
   if(!current()||fingerprint!==controlFingerprint())return;
   if(confirmLogin&&r.open)form._loginConfirmed=true;
   refreshCalibrationStatus(r);
   const message=r.open?(r.composer_editable?'连接检查通过：工作台已接管窗口，输入框可用。第二步已完成，可以继续第三步配置发送方式。':'窗口已经连接，输入框尚未就绪。请等待平台加载、本人完成登录后再次检查。'):r.connection_error||'工作台尚未接管该平台专用窗口，请在第一步重新连接。';
   $('#guide-inspect').textContent=message;
   if(confirmLogin||!r.open)connectionFeedback(message,!r.open);
  }catch(e){if(current())connectionFeedback(e.message,true);}finally{form._checking=false;buttons.forEach(b=>b.disabled=false);}
 }
 $('#inspect-platform').onclick=()=>inspectCurrent(true);
 $('#inspect-controls').onclick=()=>inspectCurrent(false);
 form._inspect=inspectCurrent;
 $('#detect-controls').onclick=async()=>{
  const button=$('#detect-controls');button.disabled=true;
  try{await cancelActivePick();const r=await post(`/api/platforms/${pid}/diagnose`,{config:platformFormValue()});if(!current())return;
   if(!r.open)throw new Error(r.connection_error||'请先在第一步连接专用窗口');
   const changed=[];for(const [key,selector] of Object.entries(r.suggestions||{})){
    if(!$('#cfg-'+key)||!selector)continue;
    if(r.controls?.[key]?.found&&!r.controls[key].normalized)continue;
    if($('#cfg-'+key).value!==selector){$('#cfg-'+key).value=selector;changed.push(key);}
   }
   if(changed.length){$('#cfg-ready').checked=false;$('#saved-summary').hidden=true;saveFeedback('已填入识别建议，尚未保存。请检查后勾选允许自动发送并保存。','neutral');}
   refreshCalibrationStatus();$('#pick-status').textContent=changed.length?'已填入识别建议。正在重新检查；识别过程没有输入或发送文字。':'没有需要替换的唯一控件。若发送按钮被隐藏，可本人先输入文字再检查；也可明确选择平台支持的快捷键。';
   await inspectCurrent(false);
  }catch(e){if(current()){$('#pick-status').textContent=e.message;connectionFeedback(e.message,true);}}finally{button.disabled=false;}
 };
 $('#reveal-composer').onclick=async()=>{
  const button=$('#reveal-composer');button.disabled=true;
  try{await cancelActivePick();const r=await post(`/api/platforms/${pid}/reveal`,{config:platformFormValue()});
   $('#guide-inspect').textContent=r.composer_in_view?'已将输入框定位到专用窗口内。现在可切换到Edge查看。':'找到了输入区域，但尚未完全显示；请在专用窗口调整大小或重新进入新对话。';
   connectionFeedback($('#guide-inspect').textContent,!r.composer_in_view);$('#pick-status').textContent='已取消点选模式，可正常操作平台。定位没有输入或发送文字。';
  }catch(e){connectionFeedback(e.message,true);}finally{button.disabled=false;}
 };
 $('#cancel-pick').onclick=async()=>{try{await cancelActivePick();await post(`/api/platforms/${pid}/cancel-pick`);$('#pick-status').textContent='已取消标定，现在可以正常操作专用网页。';}catch(e){connectionFeedback(e.message,true);}};
 $('#close-platform').onclick=async()=>{try{const r=await post(`/api/platforms/${pid}/close`);if(current()){connectionFeedback(r.message);form._inspection=null;form._loginConfirmed=false;}await load();if(current())refreshCalibrationStatus();}catch(e){if(current())connectionFeedback(e.message,true);}};
 document.querySelectorAll('[data-pick]').forEach(button=>button.onclick=async()=>{
  try{await cancelActivePick();await post(`/api/platforms/${pid}/pick`,{kind:button.dataset.pick});pickPlatform=pid;$('#pick-status').textContent='请切换到专用Edge，点击对应控件。ESC可取消这次点选。';
   pickTimer=setInterval(async()=>{try{const r=await post(`/api/platforms/${pid}/picked`);if(!current())return;if(r.result){if(r.result.invalid){$('#pick-status').textContent=r.result.error;return;}clearInterval(pickTimer);pickTimer=null;pickPlatform=null;if(r.result.cancelled){$('#pick-status').textContent='已取消点选';return;}$('#cfg-'+r.result.kind).value=r.result.selector;$('#cfg-ready').checked=false;refreshCalibrationStatus();$('#saved-summary').hidden=true;saveFeedback('已记录控件，尚未保存。请完成其他标定后保存。','neutral');$('#pick-status').textContent='已记录这个控件（尚未保存）。请继续标定其他控件，最后勾选第四步并保存。';await inspectCurrent(false);}}catch(e){clearInterval(pickTimer);pickTimer=null;if(current())connectionFeedback(e.message,true);}},1200);
  }catch(e){connectionFeedback(e.message,true);}
 });
 if(p.browser_open)inspectCurrent(false);
}
async function openConnection(pid){
 if(connectingPlatforms.has(pid))return;
 if(!$('#modal').open||$('#platform-form')?.dataset.platformId!==pid)configModal(pid);
 const activeForm=$('#platform-form');
 connectingPlatforms.add(pid);
 document.querySelectorAll(`[data-connect="${pid}"]`).forEach(b=>{b.disabled=true;b.textContent='正在打开Edge…';});
 connectionFeedback('正在启动专用Edge并加载平台，通常需要几秒；网络较慢时最多等待约一分钟。请留意任务栏里的新窗口。');
 try{
  const result=await post('/api/platforms/'+pid+'/connect');
  if($('#platform-form')===activeForm)connectionFeedback(result.message,Boolean(result.connection?.navigation_error));
  const platform=data.platforms.find(p=>p.id===pid);
  if(result.connection){platform.connection=result.connection;platform.browser_open=result.connection.open;if($('#platform-form')===activeForm){activeForm._inspection=null;refreshCalibrationStatus();}}
 }catch(error){if($('#platform-form')===activeForm)connectionFeedback(error.message,true);toast(error.message);}
 finally{
  connectingPlatforms.delete(pid);
  document.querySelectorAll(`[data-connect="${pid}"]`).forEach(b=>{b.disabled=false;b.textContent='重新打开 / 切换窗口';});
  await load();
  if($('#platform-form')===activeForm&&data.platforms.find(p=>p.id===pid)?.browser_open)await activeForm._inspect?.(false);
 }
}

async function taskModal(tid){const requestId=++taskModalRequest,previousRevision=modalRevision;pendingTaskModal=requestId;let t;try{t=await api('/api/tasks/'+tid);}catch(e){if(pendingTaskModal===requestId)pendingTaskModal=null;throw e;}if(requestId!==taskModalRequest||previousRevision!==modalRevision){if(pendingTaskModal===requestId)pendingTaskModal=null;return;}showModal((data.platforms.find(p=>p.id===t.platform)?.name||t.platform)+' · 任务记录',`<p><b>${esc(taskStatusLabel(t))}</b> · ${channelLabel(t.channel)} · ${t.mode==='visibility'?'搜索检查':'资料研读'}</p><p>${esc(taskWaitDescription(t)||t.note)}</p>${t.status==='waiting_setup'&&taskWaitDescription(t)?`<details><summary>上次阻塞原因（历史记录）</summary><p>${esc(t.note)}</p></details>`:''}<details><summary>查看实际发送的提示词快照</summary><pre class="prompt-box">${esc(t.prompt)}</pre></details><label class="field-label">平台回答<textarea id="task-answer" rows="10" maxlength="100000" aria-describedby="task-answer-feedback" placeholder="先自动采集回答，或从原对话粘贴完整回答">${esc(t.answer)}</textarea></label><p id="task-answer-feedback" class="record-answer-feedback" role="status" aria-live="polite"></p>${t.screenshot?`<a class="screenshot-link" href="/api/screenshots/${t.screenshot}" target="_blank" rel="noopener">查看本机截图 ↗</a>`:''}<div class="form-footer">${t.channel==='web'&&['sent','needs_review','completed'].includes(t.status)?'<button class="btn primary" id="review-answer">人工修正并保存</button>':''}${t.status==='waiting_setup'?'<button class="btn primary" id="retry-task">配置完成，重新排队</button>':''}${['queued','waiting_setup'].includes(t.status)?'<button class="btn danger" id="cancel-task">取消任务</button>':''}${!['queued','running'].includes(t.status)?`<button class="btn danger" type="button" data-delete-record="${t.id}">删除记录</button>`:''}</div><p>正常回答会自动校验问题对应与生成结束状态；异常采集可在此修正。自动校验不验证回答事实或推荐排名。</p>`);
 const dialog=$('#modal'),answerField=$('#task-answer'),answerFeedback=$('#task-answer-feedback'),currentRevision=modalRevision;
 const current=()=>dialog.open&&modalRevision===currentRevision&&answerField.isConnected&&$('#task-answer')===answerField;
 const canNavigate=()=>current()&&pendingTaskModal===null;
 let answerBusy=false,reviewButton=null;
 const emptyMessage='尚未保存回答。请先自动采集回答，或粘贴平台的完整回答后再保存。';
 const feedback=(message,kind='')=>{if(!current())return;answerFeedback.textContent=message;answerFeedback.dataset.kind=kind;};
 const syncReview=()=>{if(!current())return;const blank=!answerField.value.trim();if(reviewButton){reviewButton.disabled=answerBusy||blank;reviewButton.title=blank?'请先获取或粘贴完整回答':'';}if(blank&&!answerBusy&&answerFeedback.dataset.kind!=='error')feedback(emptyMessage,'empty');else if(!blank&&answerFeedback.dataset.kind==='empty')feedback('');};
 const setAnswerBusy=busy=>{answerBusy=busy;if(!current())return;answerField.readOnly=busy;dialog.querySelectorAll('[data-answer-action]').forEach(b=>b.disabled=busy);syncReview();};
 answerField.addEventListener('input',()=>{answerField.removeAttribute('aria-invalid');feedback('');syncReview();});
 if(t.measurement){
  const m=t.measurement,a=m.analysis,box=document.createElement('div');box.className='task-measurement';
  box.innerHTML=`<b>这条回答的统计依据</b><p>合作品牌：${a.brand_name_mentioned?'命中 '+esc(a.brand_matches.join('、')):'未命中已配置的品牌名称'}<br>企业：${a.company_mentioned?'命中 '+esc(a.company_matches.join('、')):'未命中已配置的企业名称或别名'}<br>自然发现：${esc(m.description)}<br>全部已核对回答：${t.status==='completed'&&t.reviewed&&t.answer.trim()?'已计入':'未完成/未核对，不计入'}</p><small>提及只代表回答里出现名称，不代表平台认定、正向推荐或优先排名。</small>`;
  $('#modal-body').insertBefore(box,$('#modal-body details'));
  if(t.metrics.verification_method==='human'&&t.metrics.verification_note){const p=document.createElement('p');p.textContent='人工核对前的自动采集诊断：'+t.metrics.verification_note;box.after(p);}
 }
 if(t.channel==='web'&&['uncertain','interrupted'].includes(t.status)){
  const diagnose=document.createElement('button');diagnose.className='btn primary';diagnose.type='button';diagnose.id='diagnose-task';diagnose.textContent='恢复连接并检查（不发送）';
  const detail=document.createElement('p');detail.id='task-diagnostic';detail.setAttribute('role','status');detail.textContent=t.sent_at?'有发送确认，回答未完整保存。':'未保存发送确认、会话链接或完整回答时，不能据此断言平台没有收到请求。';
  $('#modal-body .form-footer').prepend(diagnose);$('#modal-body .form-footer').after(detail);
  diagnose.onclick=async()=>{diagnose.disabled=true;detail.textContent='正在恢复连接并检查当前会话，不会填入或发送问题…';try{const r=await post('/api/tasks/'+tid+'/diagnose');detail.textContent=r.message;await load();}catch(e){detail.textContent=e.message;}finally{diagnose.disabled=false;}};
 }
 if(t.channel==='web'&&t.sent_at&&['sent','needs_review','completed'].includes(t.status)){
  const verify=document.createElement('button');verify.className='btn primary';verify.type='button';verify.id='verify-capture';verify.textContent='自动采集并校验（不重发）';
  $('#modal-body .form-footer').prepend(verify);
  verify.dataset.answerAction='true';verify.onclick=async()=>{if(answerBusy||!current())return;setAnswerBusy(true);verify.textContent='正在匹配原问题与回答…';try{const r=await post('/api/tasks/'+tid+'/verify');toast(r.message);await load();if(canNavigate())await taskModal(tid);}catch(e){if(current())feedback(e.message,'error');}finally{if(current())verify.textContent='自动采集并校验（不重发）';setAnswerBusy(false);}};
 }
 if(t.platform==='doubao'&&t.channel==='web'&&t.sent_at&&['sent','needs_review','completed'].includes(t.status)){
  const button=document.createElement('button');button.type='button';button.className='btn light';button.id='capture-answer';button.textContent='重新获取回答（不重发）';
  const feedback=document.createElement('p');feedback.id='capture-feedback';feedback.setAttribute('role','status');
  $('#modal-body .form-footer').prepend(button);$('#modal-body .form-footer').after(feedback);
  button.dataset.answerAction='true';button.onclick=async()=>{if(answerBusy||!current())return;setAnswerBusy(true);feedback.textContent='正在按原问题获取对应回答，问题不会重发…';try{const r=await post('/api/tasks/'+tid+'/capture');const fresh=await api('/api/tasks/'+tid);if(!canNavigate())return;answerField.value=fresh.answer;answerField.removeAttribute('aria-invalid');$('#modal-body>p:first-child b').textContent=labels[fresh.status];const link=dialog.querySelector('.screenshot-link');if(link&&fresh.screenshot)link.href='/api/screenshots/'+fresh.screenshot;feedback.textContent=`已获取 ${r.answer_length} 字。${r.message}`;await load();}catch(e){if(current())feedback.textContent=e.message;}finally{setAnswerBusy(false);}};
 }
 reviewButton=$('#review-answer');if(reviewButton){reviewButton.type='button';reviewButton.dataset.answerAction='true';reviewButton.onclick=async()=>{
  if(answerBusy||!current())return;const answer=answerField.value;
  if(!answer.trim()){answerField.setAttribute('aria-invalid','true');feedback(emptyMessage,'error');reviewButton.disabled=true;answerField.focus();return;}
  setAnswerBusy(true);reviewButton.textContent='正在保存…';feedback('正在保存已核对的回答…');
  try{const r=await post('/api/tasks/'+tid+'/review',{answer});if(canNavigate())dialog.close();toast(r.message);await load();}
  catch(e){if(current())feedback(e.message,'error');}
  finally{if(current())reviewButton.textContent='人工修正并保存';setAnswerBusy(false);}
 };}syncReview();
 if($('#retry-task'))$('#retry-task').onclick=async()=>{try{await post('/api/tasks/'+tid+'/retry');$('#modal').close();await load();}catch(e){toast(e.message);}};
 if($('#cancel-task'))$('#cancel-task').onclick=async()=>{try{await post('/api/tasks/'+tid+'/cancel');$('#modal').close();await load();}catch(e){toast(e.message);}};
}
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;try{
 if(b.dataset.task)await taskModal(b.dataset.task);
 if(b.dataset.resumeTask){b.disabled=true;try{await post('/api/tasks/'+b.dataset.resumeTask+'/retry');toast('已继续这条任务；会先恢复已保存会话并检查控件。');await load();}finally{b.disabled=false;}}

 if(b.dataset.configure)configModal(b.dataset.configure);
 if(b.dataset.connect)await openConnection(b.dataset.connect);
 
 if(b.dataset.deleteKeyword){await api('/api/keywords/'+b.dataset.deleteKeyword,{method:'DELETE'});await load();}
 if(b.dataset.editDocument)documentModal(data.documents.find(d=>d.id===b.dataset.editDocument));
 if(b.dataset.deleteDocument&&confirm('移除这条资料？已创建任务的提示词快照仍保留。')){await api('/api/documents/'+b.dataset.deleteDocument,{method:'DELETE'});await load();}
 if(b.dataset.deleteSchedule){await api('/api/schedules/'+b.dataset.deleteSchedule,{method:'DELETE'});await load();}
 }catch(error){toast(error.message);}});
$('#task-filter').onchange=()=>window.onTaskFilterChange?.();
guard($('#settings-form'),async()=>{await put('/api/settings',{interval_seconds:Number($('#interval').value),daily_limit:Number($('#daily-limit').value),parallel_platforms:Number($('#parallel-platforms').value),auto_verify:$('#auto-verify').checked,paused:data.settings.paused});toast('队列设置已保存');await load();});
guard($('#company-form'),async()=>{const r=await put('/api/profile',{company_name:$('#company-name').value,domain:$('#company-domain').value,aliases:$('#company-aliases').value.split('\n').map(s=>s.trim()).filter(Boolean),business:$('#company-business').value,audience:$('#company-audience').value,public_intro:$('#company-intro').value,brand_name:$('#company-brand').value,brand_aliases:$('#company-brand-aliases').value.split('\n').map(s=>s.trim()).filter(Boolean),brand_relation:$('#company-brand-relation').value,audience_confirmed:$('#audience-confirmed').checked});toast(r.message);await load();});
load();
