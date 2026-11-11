/* Client workspace shell. Navigation and reads never create provider tasks. */
(() => {
 let group='all',page=1,pages=1,ticket=0,searchTimer;
 const composer=$('#task-composer'),input=$('#batch-keywords');
 function openComposer(){
  if(!composer.open)composer.showModal();
  window.PlatformPlans?.open();input.focus();
 }
 window.openTaskComposer=openComposer;
 $('#client-new-task').onclick=openComposer;
 $('#client-compose-close').onclick=()=>composer.close();
 $('#client-refresh').onclick=()=>load();
 $('#client-menu-toggle').onclick=()=>{
  const compact=document.body.classList.toggle('nav-compact');
  $('#client-menu-toggle').setAttribute('aria-expanded',String(!compact));
  try{localStorage.setItem('geo-compact-nav',compact?'1':'0');}catch{}
 };
 try{if(localStorage.getItem('geo-compact-nav')==='1'){document.body.classList.add('nav-compact');$('#client-menu-toggle').setAttribute('aria-expanded','false');}}catch{}
 $('#client-help').onclick=()=>showModal('使用帮助',`<div class="client-help"><h3>开始一次检查</h3><p>先连接平台，再输入主题。生成各平台独立问题，逐条编辑、预览后，再确认创建。</p><h3>三种检查目标</h3><p>渠道证据检查使用可调整的来源线索；自然发现不注入公司与品牌；品牌核对直接询问已确认的企业或品牌。不同问题不作为同题推荐排名。</p><h3>自动运行</h3><p>词库按平台保存；每日计划执行独立问题快照，只有启用后才发送。</p><p><a href="#home" id="client-product-help">产品介绍 →</a></p></div>`);
 document.addEventListener('click',event=>{if(event.target.closest('#client-product-help'))$('#modal').close();if(event.target.closest('[data-use-keyword]'))openComposer();});
 window.onBatchCreated=()=>{composer.close();group='all';page=1;for(const tab of document.querySelectorAll('[data-client-group]')){const active=tab.dataset.clientGroup==='all';tab.classList.toggle('selected',active);tab.setAttribute('aria-selected',String(active));}refresh();};
 async function refresh(){
  if(!data||(location.hash&&location.hash!=='#overview'))return;
  const id=++ticket,q=$('#client-task-search').value.trim();
  const params=new URLSearchParams({group,page:String(page),page_size:'15',q});
  $('#recent-tasks').setAttribute('aria-busy','true');
  try{
   const result=await api('/api/tasks?'+params);if(id!==ticket)return;
   page=result.page;pages=result.pages;
   $('#recent-tasks').innerHTML=result.items.length?taskTable(result.items):'<div class="client-empty"><b>此分组暂无任务</b><p>可以切换分组、清空搜索，或新建一次检查。</p><button class="btn" type="button" data-client-create>新建任务</button></div>';
   $('#client-list-count').textContent=`${result.total} 条 · 第 ${page} / ${pages} 页`;
   $('#client-page-prev').disabled=page<=1;$('#client-page-next').disabled=page>=pages;
   $('#client-task-feedback').textContent='更新于 '+new Date().toLocaleTimeString('zh-CN',{hour12:false});
  }catch(e){$('#client-task-feedback').textContent=e.message;}
  finally{if(id===ticket)$('#recent-tasks').setAttribute('aria-busy','false');}
 }
 window.refreshClientTasks=refresh;
 $('#client-task-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{page=1;refresh();},250);};
 $('#client-page-prev').onclick=()=>{if(page>1){page--;refresh();}};
 $('#client-page-next').onclick=()=>{if(page<pages){page++;refresh();}};
 for(const tab of document.querySelectorAll('[data-client-group]'))tab.onclick=()=>{
  group=tab.dataset.clientGroup;page=1;
  for(const item of document.querySelectorAll('[data-client-group]')){const active=item===tab;item.classList.toggle('selected',active);item.setAttribute('aria-selected',String(active));}
  refresh();
 };
 document.addEventListener('click',event=>{if(event.target.closest('[data-client-create]'))openComposer();});
 const previous=window.renderImprovements;
 window.renderImprovements=()=>{
  previous?.();if(!data)return;
  const counts=data.client_counts||{};
  for(const name of ['all','running','attention','completed']){
   const element=$('#client-count-'+name);if(element)element.textContent=counts[name]??0;
   const badge=document.querySelector(`[data-client-group="${name}"] em`);if(badge)badge.textContent=counts[name]??0;
  }
  $('#client-today').textContent=data.daily_budget.used;
  $('#client-status-text').textContent=data.current_task?'任务执行中':data.settings.paused?'队列已暂停':'就绪';
  $('#client-status-meta').textContent=`今日 ${data.daily_budget.used} / ${data.daily_budget.limit} · 数据保存在此电脑`;
 };
 const onView=window.onWorkspaceView;
 window.onWorkspaceView=name=>{onView?.(name);if(name==='overview')refresh();};
})();
