/* Safe UI upgrade detection; never replays a request or discards an edited form. */
(() => {
 const current=document.documentElement.dataset.uiVersion||'',dirty=new Set();let timer=0;
 const newer=(a,b)=>{const aa=a.split('.').map(Number),bb=b.split('.').map(Number);for(let i=0;i<3;i++){if((aa[i]||0)!==(bb[i]||0))return (aa[i]||0)>(bb[i]||0);}return false;};
 for(const type of ['input','change'])document.addEventListener(type,event=>{const form=event.target.closest('form');if(event.isTrusted&&form)dirty.add(form);});
 const safe=()=>!dirty.size&&!document.querySelector('dialog[open]')&&!window.WorkspaceConnection?.state.pendingWrites;
 function check(version){
  if(!version||!newer(version,current))return;
  let box=document.getElementById('client-update');
  if(!box){box=document.createElement('div');box.id='client-update';box.className='client-update';box.setAttribute('role','status');box.innerHTML='<span></span><button type="button">加载新版</button>';document.body.append(box);box.querySelector('button').onclick=()=>{if(safe())location.reload();};}
  box.querySelector('span').textContent=dirty.size?'新界面已就绪，请先保存当前表单；未保存输入会保留。':'新界面已就绪，正在更新…';
  box.querySelector('button').disabled=!safe();
  if(!safe()||timer)return;
  let attempted=0;try{attempted=Number(sessionStorage.getItem('geo-ui-reload-at')||0);}catch{}
  if(Date.now()-attempted<60000){box.querySelector('span').textContent='新界面正在发布，可稍后加载；不会连续刷新。';return;}
  timer=setTimeout(()=>{timer=0;if(safe()){try{sessionStorage.setItem('geo-ui-reload-at',String(Date.now()));}catch{}location.reload();}},1200);
 }
 window.WorkspaceVersion={check,saved:form=>dirty.delete(form),current};
})();
