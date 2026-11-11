/* Read-only reports, paginated records and local batch feedback. */
(() => {
 let executionSettingsInitialized=false,brandFieldsInitialized=false, recordsPage=1, recordsPages=1, recordRequest=0, insightRequest=0;
 let searchTimer=null, platformOptionsInitialized=false;
 const dateText=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'尚无样本';
 const recordParams=()=>new URLSearchParams({q:$('#task-search').value.trim(),status:$('#task-filter').value,platform:$('#task-platform').value,channel:$('#task-channel').value,mode:$('#task-mode').value});
 const insightParams=()=>new URLSearchParams({days:$('#insights-days').value,channel:$('#insights-channel').value,platform:$('#insights-platform').value,scope:$('#insights-scope').value});

 window.refreshTaskRecords=async(force=false)=>{
  if(!data||(!force&&location.hash!=='#results'))return;
  const ticket=++recordRequest, params=recordParams();params.set('page',recordsPage);params.set('page_size','20');
  $('#results-export').href='/api/export/tasks.xlsx?'+recordParams();
  $('#results-export-csv').href='/api/export/tasks.csv?'+recordParams();
  $('#task-list').setAttribute('aria-busy','true');
  try{
   const result=await api('/api/tasks?'+params);if(ticket!==recordRequest)return;
   recordsPage=result.page;recordsPages=result.pages;
   $('#task-list').innerHTML=result.items.length?taskTable(result.items):'<div class="empty"><b>当前条件下没有记录</b><p>可以清空关键词或调整平台、状态和模式。</p><button class="btn light" id="clear-record-filters">清空筛选</button></div>';
   $('#records-count').textContent=`共 ${result.total} 条记录 · 每页 ${result.page_size} 条`;
   $('#records-page').textContent=`${recordsPage} / ${recordsPages}`;
   $('#records-prev').disabled=recordsPage<=1;$('#records-next').disabled=recordsPage>=recordsPages;
   $('#records-feedback').textContent='筛选与导出使用相同条件，已发送或结果不确定的任务不会自动重发。';
  }catch(error){if(ticket===recordRequest)$('#records-feedback').textContent='读取失败：'+error.message;}
  finally{if(ticket===recordRequest)$('#task-list').setAttribute('aria-busy','false');}
 };
 window.onTaskFilterChange=()=>{recordsPage=1;window.refreshTaskRecords(true);};
 $('#task-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(window.onTaskFilterChange,300);});
 for(const id of ['task-platform','task-channel','task-mode'])$('#'+id).addEventListener('change',window.onTaskFilterChange);
 $('#records-prev').onclick=()=>{if(recordsPage>1){recordsPage--;window.refreshTaskRecords(true);}};
 $('#records-next').onclick=()=>{if(recordsPage<recordsPages){recordsPage++;window.refreshTaskRecords(true);}};
 document.addEventListener('click',event=>{if(event.target.closest('#clear-record-filters')){for(const id of ['task-search','task-filter','task-platform','task-channel','task-mode'])$('#'+id).value='';window.onTaskFilterChange();}});

 function updateBudget(){window.PlatformPlans?.updateBudget();}
 document.addEventListener('input',event=>{if(event.target.id==='batch-keywords')updateBudget();});
 document.addEventListener('change',event=>{if(event.target.closest('#batch-platforms'))updateBudget();});

 function showInsights(report){
  const t=report.totals,f=report.filters;
  $('#insights-brand').textContent=report.brand_name||'尚未设置品牌名称';$('#insights-company').textContent=report.company_name;
  $('#insight-samples').textContent=t.samples;$('#insight-questions').textContent=`覆盖 ${t.questions} 个不同问题`;
  $('#insight-brand-rate').textContent=t.brand_rate===null?'—':t.brand_rate+'%';
  $('#insight-brand-count').textContent=t.samples?`${t.brand_mentions} / ${t.samples} 条回答提及品牌`:'尚无符合口径样本';
  $('#insight-company-count').textContent=t.samples?t.company_mentions+' / '+t.samples:'—';
  $('#insight-link-count').textContent=t.samples?t.official_links+' / '+t.samples:'—';
  $('#insights-feedback').textContent=`${f.start_date} 至 ${f.end_date} · 北京时间 · ${channelLabel(f.channel)} · 读取 ${report.task_count} 条记录 · 更新于 ${dateText(report.generated_at)}`;
  $('#insights-scope-note').textContent=f.scope==='all'?'当前显示全部已核对回答，包括直接询问公司/品牌的记录。这是名称出现情况，不是自然推荐率。':'当前显示自然发现：排除指名核对、指定资料渠道、附带资料和连续会话。下方对比仍显示最新任务及未计入原因。';
  $('#insights-rules').innerHTML=`<b>企业名称匹配：</b>${esc(report.matching_rules.company_names.join('、'))}<br><b>合作品牌匹配：</b>${esc(report.matching_rules.brand_names.join('、'))}<br>只检查回答，不因问题里有名称就算提及；简称须在企业设置中登记。名称出现在否定句中也属于文本提及，不等于推荐。`;
  const count=(n,total)=>total?`${n} / ${total}`:'—';
  const reasonLabels={branded:'指名问题',materials:'资料研读',continuation:'连续会话',unreviewed:'未完成/未核对',empty_answer:'空回答',source_directed:'来源核验'};
  $('#insights-platform-table').innerHTML='<div class="table-wrap"><table class="task-table insight-table"><thead><tr><th>平台 / 记录情况</th><th>计入样本</th><th>提及品牌</th><th>提及企业</th><th>官网链接</th><th>最近样本</th></tr></thead><tbody>'+report.platforms.map(p=>`<tr><td><b>${esc(p.name)}</b><small>共${p.total_tasks}条 · 已核对${p.recorded_answers}条</small>${p.samples===0?`<small>${esc(Object.entries(p.exclusions).map(([k,v])=>`${reasonLabels[k]||k} ${v}条`).join('；')||'当前筛选没有任务')}</small>`:''}</td><td>${p.samples}</td><td>${count(p.brand_mentions,p.samples)}</td><td>${count(p.company_mentions,p.samples)}</td><td>${count(p.official_links,p.samples)}</td><td>${esc(dateText(p.last_sample_at))}</td></tr>`).join('')+'</tbody></table></div>';
  $('#insights-trend').innerHTML=window.renderVisibilityTrend(report);
  $('#insights-actions').innerHTML=report.actions.length?report.actions.map(a=>`<a class="insight-action" href="#${esc(a.target)}"><b>${esc(a.title)} <span>→</span></b><p>${esc(a.body)}</p></a>`).join(''):'<p class="empty">本区间已有检查记录，可以继续用相同问题观察变化。</p>';
  const comparison=report.comparison||report.questions;
  if(!comparison.length){$('#insights-questions').innerHTML='<div class="empty"><b>当前筛选没有任务</b><p>创建任务后，这里自动显示该问题在各平台的最新进度。</p><a class="btn light" href="#overview">创建检查任务 →</a></div>';}
  else{
   $('#insights-questions').innerHTML='<div class="table-wrap"><table class="task-table question-matrix"><thead><tr><th>同一问题 / 最新任务</th>'+report.platforms.map(p=>`<th>${esc(p.name)}</th>`).join('')+'</tr></thead><tbody>'+comparison.map(q=>'<tr><td>'+esc(q.keyword)+`<small>共 ${q.task_count||q.sample_count} 条任务记录</small></td>`+report.platforms.map(p=>{const s=q.platforms[p.id];if(!s)return '<td><span class="not-measured">无此题记录</span></td>';const saved=s.status==='completed';return `<td><button class="matrix-answer ${s.brand_mentioned&&saved?'has-brand':''}" data-task="${esc(s.id)}"><b>${saved?(s.brand_mentioned?'提及合作品牌':s.company_mentioned?'提及企业':'未提及品牌/企业'):(labels[s.status]||'待确认')}</b><small>${s.included?'已计入当前范围':esc(s.reason_text||'未计入')}</small><small>${esc(dateText(s.at))}</small></button></td>`;}).join('')+'</tr>').join('')+'</tbody></table></div>';
  }
  $('#insights-method').textContent=report.measurement_note;
  const e=report.excluded;$('#insights-exclusions').textContent=`本区间排除：资料研读 ${e.materials} 条，带品牌提示 ${e.branded} 条，未完成或未核对 ${e.unreviewed} 条，空回答 ${e.empty_answer} 条，连续会话 ${e.continuation||0} 条，来源核验 ${e.source_directed||0} 条。`;
 }
 async function refreshInsights(){
  if(!data||location.hash!=='#insights')return;
  const ticket=++insightRequest,params=insightParams();$('#insights-export').href='/api/export/visibility.md?'+params;
  $('#insights').setAttribute('aria-busy','true');
  try{const report=await api('/api/insights?'+params);if(ticket===insightRequest)showInsights(report);}
  catch(error){if(ticket===insightRequest)$('#insights-feedback').textContent='读取失败：'+error.message;}
  finally{if(ticket===insightRequest)$('#insights').setAttribute('aria-busy','false');}
 }
 for(const id of ['insights-days','insights-channel','insights-platform','insights-scope'])$('#'+id).addEventListener('change',refreshInsights);
 $('#insights-refresh').onclick=refreshInsights;
 window.refreshInsights=refreshInsights;
 window.renderImprovements=()=>{
  if(!data)return;
  if(!platformOptionsInitialized){for(const id of ['task-platform','insights-platform'])for(const p of data.platforms){const o=document.createElement('option');o.value=p.id;o.textContent=p.name;$('#'+id).append(o);}platformOptionsInitialized=true;}
  if(!brandFieldsInitialized){$('#company-brand').value=data.profile.brand_name||'';$('#company-brand-aliases').value=(data.profile.brand_aliases||[]).join('\n');$('#company-brand-relation').value=data.profile.brand_relation||'';brandFieldsInitialized=true;}
  if(!executionSettingsInitialized){$('#parallel-platforms').value=data.settings.parallel_platforms||6;$('#auto-verify').checked=data.settings.auto_verify!==false;executionSettingsInitialized=true;}
  updateBudget();refreshInsights();
 };
 window.onWorkspaceView=name=>{if(name==='insights')refreshInsights();if(name==='results')window.refreshTaskRecords(true);};
 if(data){window.renderImprovements();window.onWorkspaceView(location.hash.slice(1));}
})();
