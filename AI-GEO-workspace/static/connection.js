/* Local-service connectivity. Only bootstrap reads are retried by the UI scheduler. */
(() => {
 const state={offline:false,problem:false,lastSuccess:0,retryMs:0,pendingWrites:0};
 const networkMessage='连接暂时中断，正在自动重连，通常无需操作。若长时间未恢复，请双击 start.bat 启动后台。';
 const banner=document.createElement('div');banner.id='workspace-connection-banner';banner.className='workspace-connection-banner';banner.hidden=true;banner.setAttribute('role','status');banner.setAttribute('aria-live','polite');
 banner.innerHTML='<span class="connection-banner-icon" aria-hidden="true">!</span><div class="connection-banner-copy"><b id="connection-banner-title"></b><p id="connection-banner-message"></p></div><button type="button" id="connection-retry">立即重连</button>';
 document.body.append(banner);
 const button=banner.querySelector('#connection-retry');button.onclick=()=>window.retryWorkspace?.();
 const initialPause=document.getElementById('pause-button');if(initialPause)initialPause.disabled=true;
 const set=(id,value)=>{const el=document.getElementById(id);if(el&&el.textContent!==value)el.textContent=value;};
 function show(message,offline=true){
  state.offline=offline;state.problem=true;banner.hidden=false;banner.classList.remove('recovered');
  document.body.classList.add('workspace-disconnected');
  set('connection-banner-title',offline?'本地服务未连接':'工作台数据暂不可用');
  const cached=state.lastSuccess?' 页面保留上次数据，服务恢复后会自动更新。':'';
  set('connection-banner-message',message+cached);
  set('service-state',offline?'服务已断开':'数据读取失败');set('landing-service',offline?'本地服务未连接':'工作台数据待刷新');
  set('geo-selected-status','连接状态暂不可用，请重连后刷新。');
  const pause=document.getElementById('pause-button');if(pause)pause.disabled=true;
 }
 function connected(){
  state.offline=false;state.problem=false;state.lastSuccess=Date.now();state.retryMs=0;
  banner.hidden=true;document.body.classList.remove('workspace-disconnected');
  const pause=document.getElementById('pause-button');if(pause)pause.disabled=false;
  button.disabled=false;button.textContent='立即重连';
 }
 function pending(){if(state.problem){button.disabled=true;button.textContent='正在重连…';}}
 function retryIn(ms){state.retryMs=ms;button.disabled=false;button.textContent='立即重连';button.title='后台将在约'+Math.round(ms/1000)+'秒后自动重连；也可立即重试';}
 async function request(url,options={}){
  const controller=new AbortController(),{timeoutMs,...config}=options;
  const writing=!['GET','HEAD'].includes((config.method||'GET').toUpperCase());if(writing)state.pendingWrites++;
  const timeout=setTimeout(()=>controller.abort(),timeoutMs??((config.method||'GET')==='GET'?12000:120000));
  let response,raw;
  try{response=await fetch(url,{...config,signal:controller.signal});raw=await response.text();}
  catch(cause){
   const error=new Error(cause.name==='AbortError'?'本地服务响应超时，请检查服务状态后重连。':networkMessage);
   error.name='WorkspaceConnectionError';error.code='LOCAL_CONNECTION';show(error.message,true);throw error;
  }finally{clearTimeout(timeout);if(writing)state.pendingWrites--;}
  let value;try{value=JSON.parse(raw);}catch{value=null;}
  if(!response.ok){
   const answerError=Array.isArray(value?.detail)&&value.detail.find(d=>(d.loc||[]).at(-1)==='answer');
   const detail=typeof value?.detail==='string'?value.detail:answerError?answerError.type==='string_too_long'?'回答内容过长，最多支持100000个字符。':'回答内容为空或格式不正确。请先获取或粘贴平台的完整回答，再保存。':Array.isArray(value?.detail)?'请求参数不完整：'+value.detail.map(d=>(d.loc||[]).filter(s=>s!=='body').join('.')+' '+d.msg).join('；'):'本地服务返回 HTTP '+response.status+'，请检查运行日志或稍后重试。';
   const error=new Error(detail);error.status=response.status;throw error;
  }
  if(value===null||typeof value!=='object')throw new Error('本地服务返回的数据格式异常，请查看 runtime/logs/server.log。');
  return value;
 }
 window.WorkspaceConnection={state,request,show,connected,pending,retryIn,isNetworkMessage:s=>s===networkMessage||String(s).startsWith('本地服务响应超时')};
})();
