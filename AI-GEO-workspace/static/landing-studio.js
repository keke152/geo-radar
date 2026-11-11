(() => {
 const input=document.getElementById('home-question'),button=document.getElementById('home-start'),feedback=document.getElementById('home-question-feedback');
 if(!input||!button)return;
 button.onclick=()=>{
  const value=input.value.trim();if(!value){input.setAttribute('aria-invalid','true');if(feedback)feedback.textContent='先输入要研究的业务主题。';input.focus();return;}
  input.removeAttribute('aria-invalid');if(feedback)feedback.textContent='';
  window.PlatformPlans?.setTopic(value);
  location.hash='overview';window.openTaskComposer?.();
 };
 input.addEventListener('input',()=>{input.removeAttribute('aria-invalid');if(feedback)feedback.textContent='';});
 input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();button.click();}};
})();
