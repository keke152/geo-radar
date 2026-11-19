/* Bind this page to one brand project. Switching always creates a fresh page. */
(() => {
 const byId=id=>document.getElementById(id);
 const state={id:null,projects:[],legacy:false,stale:false,switching:false,error:''};
 const requestHeaders=()=>({'X-Workspace-Request':'junhe-local','Content-Type':'application/json',...(state.id?{'X-Workspace-Project':state.id}:{})});
 const error=message=>Object.assign(new Error(message),{code:'PROJECT_CHANGED'});
 let readyPromise=null,channel=null;
 function storageKey(base){if(!state.id)throw Error('品牌项目尚未就绪');return `geo-project:${encodeURIComponent(state.id)}:${base}`;}
 function assertCurrent(){if(!state.id)throw Error('品牌项目尚未就绪，请先重连。');if(state.stale)throw error('品牌项目已切换，请重新加载后继续；本页草稿仍属于原项目。');if(state.switching)throw Error('正在切换品牌项目，请稍候。');return state.id;}
 function scopeURL(value){if(!state.id)return value;const url=new URL(value,location.href);if(url.origin!==location.origin||!/^\/api\/(?:export\/|screenshots\/)/.test(url.pathname))return value;url.searchParams.set('project',state.id);return url.pathname+url.search+url.hash;}
 function bindLinks(root=document){if(!state.id)return;const links=[...(root.matches?.('a[href]')?[root]:[]),...root.querySelectorAll?.('a[href]')||[]];for(const link of links){const scoped=scopeURL(link.getAttribute('href'));if(scoped!==link.getAttribute('href'))link.setAttribute('href',scoped);}}
 function checkpoint(){return !window.PlatformPlans?.hasDraft?.()||window.PlatformPlans.checkpoint();}
 function markChanged(activeId){
  if(state.stale)return;state.stale=true;state.error='品牌项目已切换，本页保留原项目内容，已停止读写。';
  document.body.classList.add('workspace-project-stale');byId('project-current-status').textContent='已切换 · 请重新加载';
  document.querySelector('main').inert=true;
  const banner=byId('project-change-banner');banner.hidden=false;
  const modal=document.querySelector('dialog[open]');if(modal&&!modal.querySelector('.project-inline-change')){const copy=banner.cloneNode(true);copy.removeAttribute('id');copy.classList.add('project-inline-change');modal.prepend(copy);}
  window.dispatchEvent(new CustomEvent('workspace-project-changed',{detail:{page_project_id:state.id,active_project_id:activeId||null}}));
 }
 function inspectResponse(response,value,{projectControl=false,allowProjectChange=false}={}){
  if(!state.id||allowProjectChange)return;
  const detail=value?.detail,active=value?.active_project_id||detail?.active_project_id||response.headers.get('X-Workspace-Project');
  if(detail?.code==='PROJECT_CHANGED'||(active&&active!==state.id)){markChanged(active);throw error(typeof detail?.message==='string'?detail.message:state.error);}
  if(!projectControl&&response.url&&new URL(response.url).pathname==='/api/bootstrap'&&!state.legacy&&!active)throw Error('品牌项目响应缺少项目编号，请重连后重试。');
 }
 async function control(url,options={}){return WorkspaceConnection.request(url,{...options,headers:requestHeaders(),projectControl:true});}
 function validateRegistry(value){if(!value||typeof value.active_project_id!=='string'||!value.active_project_id||!Array.isArray(value.projects)||!value.projects.some(p=>p?.id===value.active_project_id)||value.projects.some(p=>typeof p?.id!=='string'||!p.id||typeof p.name!=='string'))throw Error('项目列表格式异常，已停止加载，避免进入错误的品牌项目。');return value;}
 function render(){
  const current=state.projects.find(project=>project.id===state.id);
  byId('project-current-name').textContent=current?.name||(state.id==='default'?'默认品牌项目':'正在读取项目…');
  byId('project-current-status').textContent=state.stale?'已切换 · 请重新加载':state.id?'当前品牌项目':'尚未连接';
  byId('project-open').disabled=!state.id;
  byId('project-close').disabled=state.switching;
  byId('project-new-toggle').disabled=state.legacy||state.stale||state.switching;
  const list=byId('project-list');list.replaceChildren();
  for(const project of state.projects){const button=document.createElement('button');button.type='button';button.className='project-option';button.dataset.projectId=project.id;button.disabled=project.id===state.id||state.switching||state.stale;button.setAttribute('aria-current',project.id===state.id?'true':'false');const name=document.createElement('strong');name.textContent=project.name;const detail=document.createElement('small');detail.textContent=project.id===state.id?'当前项目':project.brand_name||project.company_name||'切换后进入独立工作区';button.append(name,detail);list.append(button);}
 }
 async function discover(){
  let result;
  try{result=await control('/api/projects');}
  catch(cause){if(cause.status!==404&&cause.status!==405)throw cause;result={active_project_id:'default',projects:[{id:'default',name:'默认品牌项目'}]};state.legacy=true;}
  validateRegistry(result);
  if(state.id&&result.active_project_id!==state.id){markChanged(result.active_project_id);throw error(state.error);}
  const first=!state.id;state.id=result.active_project_id;state.projects=result.projects;state.error='';render();bindLinks();
  document.body.classList.remove('workspace-project-pending');if(!state.stale)document.querySelector('main').inert=false;
  if(first)window.dispatchEvent(new CustomEvent('workspace-project-ready',{detail:{project_id:state.id}}));return state.id;
 }
 function ensureReady(){if(state.id)return state.stale?Promise.reject(error(state.error)):Promise.resolve(state.id);if(!readyPromise)readyPromise=discover().catch(cause=>{readyPromise=null;state.error=cause.message;byId('project-current-name').textContent='项目读取失败';byId('project-current-status').textContent='请点击立即重连';throw cause;});return readyPromise;}
 function busyReason(){
  if(WorkspaceConnection.state.pendingWrites||window.PlatformPlans?.busy?.())return '当前操作尚未结束，请稍后再切换项目。';
  if(window.PlatformPlans?.hasPending?.())return '上次创建结果尚未确认，请先在本项目重试核实，再切换项目。';
  if((typeof connectingPlatforms!=='undefined'&&connectingPlatforms.size)||(typeof pickPlatform!=='undefined'&&pickPlatform)||document.querySelector('#platform-form')?._checking)return '平台连接或检查尚未结束，请完成后再切换项目。';
  if(typeof data!=='undefined'&&(data?.current_task||data?.queue?.active_count))return '当前任务正在执行，请结束后再切换项目。';
  return '';
 }
 async function activate(id){
  assertCurrent();if(id===state.id)return;const reason=busyReason();if(reason)throw Error(reason);
  if(!checkpoint())throw Error('任务草稿未能保存到本机，请检查浏览器存储后再切换。');
  const dirty=[...(window.WorkspaceVersion?.dirtySet||[])].some(form=>form.isConnected);
  if(dirty&&!confirm('当前有未保存的修改。任务草稿会留在原项目，其他未保存表单会丢失。继续切换？'))return;
  state.switching=true;render();byId('project-feedback').textContent='正在切换品牌项目…';
  try{const result=await control('/api/projects/'+encodeURIComponent(id)+'/activate',{method:'POST',body:'{}',allowProjectChange:true});if(result.active_project_id!==id)throw Error('切换结果与所选项目不一致，请重连后检查。');channel?.postMessage({active_project_id:id});markChanged(id);location.reload();}
  catch(cause){if(cause.code==='LOCAL_CONNECTION'||cause.status>=500){try{const registry=validateRegistry(await control('/api/projects',{allowProjectChange:true}));if(registry.active_project_id!==state.id)markChanged(registry.active_project_id);}catch{}}throw cause;}
  finally{state.switching=false;render();}
 }
 byId('project-open').onclick=()=>{const dialog=byId('project-dialog');if(!dialog.open)dialog.showModal();byId('project-feedback').textContent=state.stale?state.error:state.legacy?'此版本未提供项目管理，当前使用默认项目。':'';if(!state.legacy&&!state.stale)discover().catch(cause=>byId('project-feedback').textContent=cause.message);};
 byId('project-close').onclick=()=>byId('project-dialog').close();
 byId('project-dialog').addEventListener('cancel',event=>{if(state.switching)event.preventDefault();});
 byId('project-new-toggle').onclick=()=>{byId('project-create-form').hidden=!byId('project-create-form').hidden;if(!byId('project-create-form').hidden)byId('project-new-name').focus();};
 byId('project-list').onclick=event=>{const button=event.target.closest('[data-project-id]');if(button)activate(button.dataset.projectId).catch(cause=>byId('project-feedback').textContent=cause.message);};
 byId('project-create-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget,button=byId('project-create-submit');if(button.disabled)return;button.disabled=true;
  try{assertCurrent();const result=await control('/api/projects',{method:'POST',body:JSON.stringify({name:byId('project-new-name').value.trim(),company_name:byId('project-new-company').value.trim(),brand_name:byId('project-new-brand').value.trim(),domain:byId('project-new-domain').value.trim()})});if(!result.project?.id)throw Error('项目创建结果异常，请刷新项目列表后检查。');await discover();WorkspaceVersion.saved(form);form.reset();form.hidden=true;byId('project-feedback').textContent='新项目已创建，请在列表中选择进入。';}
  catch(cause){byId('project-feedback').textContent=cause.message;}finally{button.disabled=false;}
 });
 document.addEventListener('click',event=>{if(event.target.closest('[data-project-reload]')){checkpoint();location.reload();return;}const link=event.target.closest('a[href]');if(link&&new URL(link.href).origin===location.origin&&new URL(link.href).pathname.startsWith('/api/')){if(state.stale||state.switching){event.preventDefault();return;}bindLinks(link);}},true);
 const observer=new MutationObserver(records=>{for(const record of records){if(record.type==='attributes')bindLinks(record.target);else for(const node of record.addedNodes)if(node.nodeType===Node.ELEMENT_NODE)bindLinks(node);}});observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['href']});
 try{channel=new BroadcastChannel('geo-workspace-projects');channel.onmessage=event=>{const id=event.data?.active_project_id;if(state.id&&typeof id==='string'&&id!==state.id)markChanged(id);};}catch{}
 window.WorkspaceProjects={state,ensureReady,assertCurrent,inspectResponse,storageKey,url:scopeURL,bindLinks,markChanged,get ready(){return ensureReady();}};
 document.body.classList.add('workspace-project-pending');document.querySelector('main').inert=true;
 ensureReady().catch(()=>{});
})();
