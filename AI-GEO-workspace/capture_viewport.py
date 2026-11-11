"""Bounded, message-list-only viewport recovery. Never types or clicks."""

REPLY_VIEWPORT = r'''({action='top',top=0})=>{
 const lists=[...document.querySelectorAll('[data-testid="message-list"]')];
 if(lists.length!==1)return {moved:false,reason:'message_list_not_unique'};
 const list=lists[0];
 const scrollable=e=>e.clientHeight>0&&e.scrollHeight>e.clientHeight+2&&/^(auto|scroll|overlay)$/.test(getComputedStyle(e).overflowY);
 // Doubao's virtual-list viewport is INSIDE message-list, not its ancestor.
 // Never scroll unrelated navigation, the editor, or a sidebar.
 let candidates=[list,...list.querySelectorAll('*')].filter(scrollable).filter(e=>!e.closest('textarea,input,[contenteditable=true]'));
 candidates=candidates.filter(e=>!candidates.some(parent=>parent!==e&&parent.contains(e)));
 if(!candidates.length){for(let p=list.parentElement,depth=0;p&&depth<8;p=p.parentElement,depth++){if(scrollable(p)){candidates=[p];break;}}}
 if(candidates.length!==1)return {moved:false,reason:'reply_viewport_not_unique'};
 const viewport=candidates[0],before=viewport.scrollTop;
 const target=action==='restore'?Math.max(0,Number(top)||0):0;
 viewport.scrollTop=target;
 return {moved:Math.abs(before-viewport.scrollTop)>1,previous_top:before,current_top:viewport.scrollTop};
}'''
