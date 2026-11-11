/* Export template and recoverable deletion. No automatic provider actions. */
(() => {
 const filters=()=>Object.fromEntries(['q','status','platform','channel','mode'].map((name,i)=>[name,$(['#task-search','#task-filter','#task-platform','#task-channel','#task-mode'][i]).value.trim()]));
 window.openRecordDeletion=ids=>{
  const scope=filters();let token=null,revision=0;
  const summary=[scope.q||'全部关键词',...['#task-filter','#task-platform','#task-channel','#task-mode'].map(s=>$(s).selectedOptions[0].textContent)].join(' · ');
  showModal(ids?'删除这条记录':'清理历史记录',`<p class="archive-intro">记录将移入回收站，可随时恢复。进行中和排队中的任务不会删除。</p>${ids?'':`<p class="archive-scope">按记录页当前筛选处理：${esc(summary)}</p><label>创建日期截止至（含当天，可留空）<input type="date" id="archive-before"></label>`}<div id="archive-preview" class="archive-preview" role="status">先预览将删除的记录数量，再确认。</div><div class="form-footer"><button type="button" class="btn" id="archive-check">预览数量</button><button type="button" class="btn danger" id="archive-confirm" disabled>确认移入回收站</button></div>`);
  const dialog=$('#modal'),feedback=$('#archive-preview'),check=$('#archive-check'),confirm=$('#archive-confirm'),beforeInput=$('#archive-before');
  const active=()=>dialog.open&&feedback.isConnected&&$('#archive-preview')===feedback;
  const invalidate=()=>{revision++;token=null;confirm.disabled=true;feedback.textContent='条件已变化，请重新预览数量。';};
  beforeInput?.addEventListener('input',invalidate);beforeInput?.addEventListener('change',invalidate);
  check.onclick=async()=>{
   const ticket=++revision,before=beforeInput?.value||null;token=null;confirm.disabled=true;check.disabled=true;
   try{const result=await post('/api/records/delete-preview',{filters:ids?{}:scope,ids:ids||[],before});
    if(!active()||ticket!==revision||(beforeInput?.value||null)!==before)return;
    token=result.token;feedback.textContent=`将移入回收站 ${result.count} 条；跳过 ${result.skipped_active} 条进行中或排队任务。预览10分钟内有效。`;
    confirm.disabled=!result.count;
   }catch(e){if(active()&&ticket===revision)feedback.textContent=e.message;}finally{if(active())check.disabled=false;}
  };
  confirm.onclick=async()=>{
   if(!token)return;confirm.disabled=true;check.disabled=true;if(beforeInput)beforeInput.disabled=true;
   try{const result=await post('/api/records/delete',{token});if(active())dialog.close();toast(`已移入回收站 ${result.deleted} 条，可在“回收站”恢复。`);await load();window.refreshInsights?.();}
   catch(e){if(active()){feedback.textContent=e.message;check.disabled=false;if(beforeInput)beforeInput.disabled=false;}token=null;}
  };
 };
 $('#records-cleanup').onclick=()=>window.openRecordDeletion();
 document.addEventListener('click',event=>{const button=event.target.closest('[data-delete-record]');if(button){$('#modal').close();window.openRecordDeletion([button.dataset.deleteRecord]);}});
 let trashPage=1;
 async function showTrash(){
  try{
   const result=await api('/api/records/trash?page='+trashPage);trashPage=result.page;
   showModal('记录回收站',`<p class="archive-intro">共 ${result.total} 条已删除记录。恢复后重新出现在列表、导出与统计中，不会重新发送问题。</p><div class="trash-list">${result.items.map(r=>`<div class="trash-row"><div><b>${esc(data.platforms.find(p=>p.id===r.platform)?.name||r.platform)}</b><p>${esc(r.keyword)}</p><small>删除于 ${esc(new Date(r.deleted_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))}</small></div><button type="button" class="btn" data-restore-record="${esc(r.id)}">恢复</button></div>`).join('')||'<div class="empty">回收站为空</div>'}</div><div class="trash-pagination"><button type="button" class="btn" id="trash-prev" ${result.page<=1?'disabled':''}>上一页</button><span>${result.page} / ${result.pages}</span><button type="button" class="btn" id="trash-next" ${result.page>=result.pages?'disabled':''}>下一页</button></div>`);
   $('#trash-prev').onclick=()=>{trashPage--;showTrash();};$('#trash-next').onclick=()=>{trashPage++;showTrash();};
   for(const b of document.querySelectorAll('[data-restore-record]'))b.onclick=async()=>{b.disabled=true;try{await post('/api/records/restore',{ids:[b.dataset.restoreRecord]});await load();await showTrash();}catch(e){toast(e.message);b.disabled=false;}};
  }catch(e){toast(e.message);}
 }
 $('#records-trash').onclick=()=>{trashPage=1;showTrash();};
})();
