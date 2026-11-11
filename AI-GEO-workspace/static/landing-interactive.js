/* Decorative, offline Earth and orbital network. No platform API or task requests. */
(() => {
 'use strict';
 const canvas=document.querySelector('#geo-network'),visual=document.querySelector('.landing-visual');if(!canvas||!visual)return;
 const ctx=canvas.getContext('2d');if(!ctx)return;
 const assetBase=document.currentScript?.src||location.href,landURL=new URL('globe-land.json',assetBase),earthURL=new URL('globe-earth.jpg',assetBase),cloudURL=new URL('globe-clouds.jpg',assetBase);
 const reduced=matchMedia('(prefers-reduced-motion: reduce)'),TAU=Math.PI*2,INITIAL_ANGLE=1.72,INITIAL_PITCH=-.28;
 let frame=0,last=0,visible=true,paused=false,angle=INITIAL_ANGLE,pitch=INITIAL_PITCH,drag=null,velocity=0,platforms=[],selected='doubao',hovered=null,focused=null,buttons=[],orbitPhase=0,orbitDirection=1,viewAngle=0,viewPitch=0,photoPixels=null,cloudPixels=null,cityPixels=null;
 const surface=document.createElement('canvas'),surfaceCtx=surface.getContext('2d');
 let raster=null,landPixels=null,texturePixels=null,surfaceAngle=NaN,surfacePitch=NaN;
 // Bundled Natural Earth 110m real land polygons, public domain. Terrain fields only
 // add lighting and texture: every continent shape comes from the local geography.
 const mapW=2048,mapH=1024;
 const cities=[[116.4,39.9,1],[121.5,31.2,1.3],[113.3,23.1,1.3],[114.1,22.5,1.1],[104.1,30.7,.85],[106.6,29.6,.7],[114.3,30.6,.8],[108.9,34.3,.6],[118.8,32.1,.85],[120.2,30.3,.85],[117.2,39.1,.7],[123.4,41.8,.55],[126.6,45.8,.45],[87.6,43.8,.4],[91.1,29.6,.2],[139.7,35.7,1.4],[135.5,34.7,1],[127,37.6,1.1],[121.6,25,.75],[120.98,14.6,.8],[100.5,13.8,.9],[106.7,10.8,.65],[105.8,21,.55],[103.8,1.35,.9],[106.8,-6.2,.9],[101.7,3.1,.6],[77.2,28.6,1.3],[72.9,19.1,1.2],[88.4,22.6,.85],[80.3,13.1,.8],[77.6,13,.85],[90.4,23.8,.75],[67,24.9,.75],[74.3,31.6,.6],[55.3,25.2,.65],[51.4,35.7,.75],[44.4,33.3,.5],[46.7,24.7,.65],[28.98,41,1],[37.6,55.8,1],[30.3,59.9,.65],[31.2,30,.9],[3.4,6.5,.8],[28.1,-26.2,.6],[18.4,-33.9,.5],[36.8,-1.3,.45],[2.35,48.85,1],[-.12,51.5,1],[4.9,52.4,.8],[13.4,52.5,.85],[12.5,41.9,.7],[9.2,45.5,.85],[-3.7,40.4,.75],[21,52.2,.7],[-74,40.7,1.3],[-71.1,42.4,.7],[-77,38.9,.8],[-87.6,41.9,1],[-118.2,34.1,1.2],[-122.4,37.8,.9],[-122.3,47.6,.6],[-95.4,29.8,.8],[-99.1,19.4,1],[-79.4,43.7,.8],[-46.6,-23.5,1],[-43.2,-22.9,.8],[-58.4,-34.6,.85],[-70.7,-33.5,.65],[-77,-12,.65],[151.2,-33.9,.8],[144.96,-37.8,.7],[153,-27.5,.5],[115.9,-31.95,.5],[174.8,-36.9,.4]];
 // Preserve the Fibonacci triangle network, now lifted into low orbit.
 const points=Array.from({length:82},(_,i)=>{const y=1-2*(i+.5)/82,r=Math.sqrt(1-y*y),a=i*2.39996323;return {x:r*Math.cos(a),y,z:r*Math.sin(a)};});
 const edges=[];points.forEach((a,i)=>points.forEach((b,j)=>{if(j>i&&Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z)<.48)edges.push([i,j]);}));
 const stars=Array.from({length:83},(_,i)=>({x:((i*73.137)%997)/997,y:((i*137.731+43)%991)/991,r:i%17===0?1:.35+(i%4)*.13,a:.19+(i%7)*.065}));
 const orbits=[{tilt:.47,turn:.23,r:1.21,phase:-2.49,speed:1},{tilt:1.12,turn:1.46,r:1.30,phase:-.83,speed:-.76},{tilt:-.82,turn:2.65,r:1.25,phase:.82,speed:1.22},{tilt:.76,turn:3.41,r:1.33,phase:2.05,speed:-.92},{tilt:-1.20,turn:4.25,r:1.27,phase:3.62,speed:.65},{tilt:.98,turn:5.20,r:1.31,phase:4.81,speed:-1.08}];
 function prepareLand(geo){
  const map=document.createElement('canvas');map.width=mapW;map.height=mapH;const m=map.getContext('2d',{willReadFrequently:true});
  m.fillStyle='#000';m.fillRect(0,0,mapW,mapH);m.fillStyle='#ff0000';m.strokeStyle='#ff9b00';m.lineWidth=.8;
  // Unwrap rings at the antimeridian before drawing wrapped copies in texture space.
  geo.coordinates.forEach(polygon=>{
   const rings=polygon.map(ring=>{let last=null;return ring.map(([lon,lat])=>{let x=(lon+180)/360*mapW;if(last!==null){while(x-last>mapW/2)x-=mapW;while(last-x>mapW/2)x+=mapW;}last=x;return [x,(90-lat)/180*mapH];});});
   for(const shift of [-mapW,0,mapW]){m.beginPath();rings.forEach(ring=>{ring.forEach(([x,y],i)=>i?m.lineTo(x+shift,y):m.moveTo(x+shift,y));m.closePath();});m.fill('evenodd');m.stroke();}
  });
  landPixels=m.getImageData(0,0,mapW,mapH).data;
  const city=document.createElement('canvas');city.width=mapW;city.height=mapH;const c=city.getContext('2d',{willReadFrequently:true});c.fillStyle='#000';c.fillRect(0,0,mapW,mapH);
  cities.forEach(([lon,lat,power],i)=>{
   const x=(lon+180)/360*mapW,y=(90-lat)/180*mapH,r=3.6+power*3.7,glow=c.createRadialGradient(x,y,0,x,y,r);
   glow.addColorStop(0,`rgba(255,255,255,${.6*power})`);glow.addColorStop(.18,'rgba(220,220,220,.35)');glow.addColorStop(1,'rgba(0,0,0,0)');c.fillStyle=glow;c.fillRect(x-r,y-r,2*r,2*r);
   for(let j=0;j<16;j++){const a=j*2.399+i*.73,rr=(j%5+.8)*r*.27,px=x+Math.cos(a)*rr,py=y+Math.sin(a)*rr*.65,s=(Math.floor(py)*mapW+((Math.floor(px)+mapW)%mapW))*4;if(landPixels[s]>150){c.fillStyle=`rgba(255,255,255,${.3+(j%4)*.15})`;c.fillRect(px,py,.5+(j%3)*.3,.55);}}
  });
  cityPixels=c.getImageData(0,0,mapW,mapH).data;composeTexture();
 }
 function composeTexture(){
  if(!landPixels||!cityPixels)return;texturePixels=new Uint8ClampedArray(mapW*mapH*4);
  // Terrain, coast, cloud wisps and illustrative city lights are computed once.
  // Rotation then needs only a texture lookup per pixel.
  for(let y=0;y<mapH;y++)for(let x=0;x<mapW;x++){
   const i=(y*mapW+x)*4,lon=(x/mapW-.5)*TAU,lat=(.5-y/mapH)*Math.PI,land=landPixels[i]/255,coast=landPixels[i+1]/255;
   const terrain=land*(.94+.06*Math.sin(lon*31+Math.sin(lat*23))*Math.cos(lat*37));
   // Historical NASA Blue Marble terrain plus a bundled NASA Blue Marble cloud
   // composite. These are illustrative layers, never live weather.
   const blend=cloudPixels?Math.pow(cloudPixels[i]/255,1.25)*.72:0;
   const base=photoPixels||null;
   const red=base?base[i]:2+terrain*15+coast*5,green=base?base[i+1]:22+terrain*48+coast*19,blue=base?base[i+2]:53+terrain*36+coast*29;
   texturePixels[i]=red*(1-blend)+238*blend;texturePixels[i+1]=green*(1-blend)+245*blend;texturePixels[i+2]=blue*(1-blend)+255*blend;texturePixels[i+3]=cityPixels[i]*land;
  }
  surfaceAngle=NaN;draw();
 }
 // Both assets are bundled; no external imagery or platform request is made.
 const earthPhoto=new Image();earthPhoto.decoding='async';earthPhoto.onload=()=>{const photo=document.createElement('canvas');photo.width=mapW;photo.height=mapH;const pc=photo.getContext('2d',{willReadFrequently:true});pc.drawImage(earthPhoto,0,0,mapW,mapH);photoPixels=pc.getImageData(0,0,mapW,mapH).data;visual.dataset.globeTexture='ready';composeTexture();};earthPhoto.onerror=()=>{visual.dataset.globeTexture='fallback';};earthPhoto.src=earthURL.href;
 const cloudPhoto=new Image();cloudPhoto.decoding='async';cloudPhoto.onload=()=>{const cloud=document.createElement('canvas');cloud.width=mapW;cloud.height=mapH;const cc=cloud.getContext('2d',{willReadFrequently:true});cc.drawImage(cloudPhoto,0,0,mapW,mapH);cloudPixels=cc.getImageData(0,0,mapW,mapH).data;visual.dataset.globeClouds='ready';composeTexture();};cloudPhoto.onerror=()=>{visual.dataset.globeClouds='unavailable';};cloudPhoto.src=cloudURL.href;
 fetch(landURL,{cache:'force-cache'}).then(r=>{if(!r.ok)throw Error('Local globe data unavailable');return r.json();}).then(prepareLand).catch(()=>{visual.dataset.globeLand='unavailable';});
 const text=(id,value)=>{const el=document.querySelector(id);if(el&&el.textContent!==value)el.textContent=value;};
 function status(p){
  if(p.channel==='api')return p.key_configured&&p.model?'API已配置 · 待实际调用验证':'API未配置 · 请填写Key与模型';
  return p.browser_open?'专用窗口已打开 · 请确认登录':p.ready&&p.connection?.profile_saved?'标定已保存 · 可恢复会话':'尚未连接 · 需要本人登录';
 }
 function update(){
  const p=platforms.find(p=>p.id===selected)||platforms[0];if(!p)return;selected=p.id;
  text('#geo-selected-name',p.name);text('#geo-selected-status',status(p));document.querySelector('#geo-selected-status').title=status(p);text('#geo-core-label','EARTH · PLATFORM NETWORK');text('#geo-selected-channel',p.channel==='api'?'官方 API':'网页通道');
  document.querySelector('#geo-configure').disabled=false;
  buttons.forEach((b,i)=>{const on=platforms[i].id===selected;b.classList.toggle('selected',on);b.setAttribute('aria-pressed',String(on));});
 }
 function select(pid){selected=pid;update();visual.classList.remove('map-ping');void visual.offsetWidth;visual.classList.add('map-ping');draw();}
 function buildRaster(size){
  surface.width=surface.height=size;const data=surfaceCtx.createImageData(size,size),normals=[],indices=[],lighting=[];
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){const nx=(x+.5)/size*2-1,ny=(y+.5)/size*2-1,z2=1-nx*nx-ny*ny;if(z2<=0)continue;const nz=Math.sqrt(z2),light=Math.max(0,-nx*.46-ny*.33+nz*.83),i=(y*size+x)*4;normals.push(nx,ny,nz);indices.push(i);lighting.push((.31+light*.77)*(.77+nz*.23),Math.pow(1-light,3)*.64,Math.pow(1-nz,5));data.data[i+3]=Math.min(255,nz*size*80);}
  raster={size,data,normals:new Float32Array(normals),indices:new Uint32Array(indices),lighting:new Float32Array(lighting),u:new Float32Array(indices.length),rows:new Uint32Array(indices.length),pitch:NaN};surfaceAngle=NaN;
 }
 function paintSurface(r){
  // The sphere is rasterized at a bounded independent resolution; the UI canvas stays crisp.
  const size=Math.min(480,Math.max(240,Math.round(r*2*Math.min(devicePixelRatio||1,1.4))));if(raster?.size!==size)buildRaster(size);
  if(surfaceAngle===angle&&surfacePitch===pitch)return;
  const {data,normals,indices,lighting,u,rows}=raster,out=data.data;
  // Latitude and base longitude depend only on pitch. Yaw is a wrapped texture
  // offset, so normal automatic rotation performs no per-pixel trigonometry.
  if(raster.pitch!==pitch){const cp=Math.cos(pitch),sp=Math.sin(pitch);for(let k=0;k<indices.length;k++){const j=k*3,py=normals[j+1]*cp+normals[j+2]*sp,pz=-normals[j+1]*sp+normals[j+2]*cp;u[k]=(Math.atan2(normals[j],pz)/TAU+.5)*mapW;rows[k]=Math.min(mapH-1,Math.max(0,Math.floor((.5+Math.asin(Math.max(-1,Math.min(1,py)))/Math.PI)*mapH)))*mapW;}raster.pitch=pitch;}
  const shift=((angle/TAU*mapW)%mapW+mapW)%mapW;
  for(let k=0;k<indices.length;k++){
   const j=k*3,x=u[k]+shift,ti=(rows[k]+Math.floor(x>=mapW?x-mapW:x))*4;
   const shade=lighting[j],city=(texturePixels?texturePixels[ti+3]:0)*lighting[j+1],rim=lighting[j+2],i=indices[k];
   const water=landPixels?1-landPixels[ti]/255:0,specular=water*Math.pow(Math.max(0,-normals[j]*.23-normals[j+1]*.16+normals[j+2]*.96),26)*23;
   out[i]=(texturePixels?texturePixels[ti]:2)*shade+city*.718+specular*.66;
   out[i+1]=(texturePixels?texturePixels[ti+1]:22)*shade+city*.8+rim*11+specular*.83;
   out[i+2]=(texturePixels?texturePixels[ti+2]:53)*shade+city*.725+rim*32+specular;
  }
  surfaceCtx.putImageData(data,0,0);surfaceAngle=angle;surfacePitch=pitch;
 }
 function draw(){
  const box=canvas.getBoundingClientRect();if(!box.width||!box.height)return;
  const w=box.width,h=box.height,dpr=Math.min(devicePixelRatio||1,2),cx=w/2;
  const instruction=document.querySelector('.map-instructions'),floor=instruction?instruction.offsetTop-13:h-75,roof=52,cy=(roof+floor)/2,r=Math.min(w*.325,(floor-roof)*.39);
  visual.style.setProperty('--geo-diameter',(r*2)+'px');visual.style.setProperty('--geo-center-y',cy+'px');
  if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  stars.forEach(s=>{ctx.fillStyle=`rgba(167,206,241,${s.a})`;ctx.beginPath();ctx.arc(s.x*w,s.y*h*.82,s.r,0,TAU);ctx.fill();});
  const ca=Math.cos(angle),sa=Math.sin(angle),cp=Math.cos(pitch),sp=Math.sin(pitch);
  const project=(p,alt=1)=>{const x=p.x*ca-p.z*sa,z=p.x*sa+p.z*ca,y=p.y*cp-z*sp,depth=p.y*sp+z*cp;return {x:cx+x*r*alt,y:cy+y*r*alt,z:depth};};
  const projected=points.map(p=>project(p,1.065));
  const orbitPoint=(o,t)=>{const x=Math.cos(t),z=Math.sin(t),y=z*Math.sin(o.tilt),zz=z*Math.cos(o.tilt),c=Math.cos(o.turn),s=Math.sin(o.turn);return {x:(x*c-zz*s)*o.r,y:y*o.r,z:(x*s+zz*c)*o.r};};
  const cv=Math.cos(viewAngle),sv=Math.sin(viewAngle),pv=Math.cos(viewPitch),ps=Math.sin(viewPitch);
  const projectOrbit=p=>{const x=p.x*cv-p.z*sv,z=p.x*sv+p.z*cv;return {x:cx+x*r,y:cy+(p.y*pv-z*ps)*r*.86,z:p.y*ps+z*pv};};
  const orbitPaths=orbits.map(o=>Array.from({length:97},(_,i)=>projectOrbit(orbitPoint(o,i/96*TAU))));
  function orbitLines(front){ctx.lineWidth=.7;ctx.strokeStyle=front?'rgba(105,189,246,.23)':'rgba(67,135,202,.12)';orbitPaths.forEach(path=>{ctx.beginPath();for(let i=1;i<path.length;i++){const a=path[i-1],b=path[i];if((a.z+b.z>=0)===front){ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);}}ctx.stroke();});}
  function network(front){for(const [i,j] of edges){const a=projected[i],b=projected[j],z=(a.z+b.z)/2;if((z>=0)!==front||(front&&(a.z<-.03||b.z<-.03)))continue;ctx.strokeStyle=front?`rgba(80,172,234,${.048+z*.075})`:'rgba(63,134,198,.07)';ctx.lineWidth=front?.62+Math.max(0,z)*.25:.55;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();}}
  orbitLines(false);network(false);
  const halo=ctx.createRadialGradient(cx,cy,r*.88,cx,cy,r*1.17);halo.addColorStop(0,'rgba(28,124,231,0)');halo.addColorStop(.53,'rgba(42,147,247,.17)');halo.addColorStop(.7,'rgba(27,109,233,.08)');halo.addColorStop(1,'rgba(20,91,215,0)');ctx.fillStyle=halo;ctx.beginPath();ctx.arc(cx,cy,r*1.17,0,TAU);ctx.fill();
  paintSurface(r);ctx.drawImage(surface,cx-r,cy-r,r*2,r*2);
  const rim=ctx.createLinearGradient(cx-r,cy-r,cx+r,cy+r);rim.addColorStop(0,'rgba(117,210,255,.88)');rim.addColorStop(.46,'rgba(48,147,244,.46)');rim.addColorStop(1,'rgba(15,76,162,.08)');ctx.strokeStyle=rim;ctx.lineWidth=1.05;ctx.beginPath();ctx.arc(cx,cy,r+.3,0,TAU);ctx.stroke();
  orbitLines(true);
  // Keep the constellation around the limb, leaving the photographic surface clear.
  ctx.save();ctx.beginPath();ctx.rect(0,0,w,h);ctx.arc(cx,cy,r*1.01,0,TAU,true);ctx.clip('evenodd');network(true);
  projected.forEach((p,i)=>{if(p.z<0)return;const bright=i%9===0,size=bright?1.9:.9+p.z*.24;if(bright){const glow=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,7);glow.addColorStop(0,'rgba(129,216,255,.58)');glow.addColorStop(1,'rgba(47,153,255,0)');ctx.fillStyle=glow;ctx.fillRect(p.x-7,p.y-7,14,14);}ctx.fillStyle=bright?'#c3edff':`rgba(103,192,245,${.4+p.z*.42})`;ctx.beginPath();ctx.arc(p.x,p.y,size,0,TAU);ctx.fill();});
  ctx.restore();
  // Each model has its own inclination, altitude, phase and signed speed.
  // Drags rotate this orbital camera too. Labels are separated for readability;
  // short leader lines keep their association with the true orbital positions.
  const layouts=buttons.map((b,i)=>{
   const o=orbits[i%orbits.length],t=o.phase+orbitPhase*o.speed,p=projectOrbit(orbitPoint(o,t)),scale=.88+(Math.max(-1,Math.min(1,p.z/o.r))+1)*.06;
   let x=p.x,y=p.y;const d=Math.hypot(x-cx,y-cy),minimum=r*.83;if(d<minimum){const a=d<1?t:Math.atan2(y-cy,x-cx);x=cx+Math.cos(a)*minimum;y=cy+Math.sin(a)*minimum;}
   return {b,i,o,t,p,x,y,scale,hw:b.offsetWidth*scale/2+4,hh:b.offsetHeight*scale/2+3};
  });
  const bound=n=>{n.x=Math.max(n.hw+2,Math.min(w-n.hw-2,n.x));n.y=Math.max(roof+n.hh,Math.min(floor-n.hh,n.y));};
  layouts.forEach(bound);
  for(let pass=0;pass<24;pass++){
   for(let i=0;i<layouts.length;i++)for(let j=i+1;j<layouts.length;j++){
    const a=layouts[i],b=layouts[j],dx=b.x-a.x,dy=b.y-a.y,ox=a.hw+b.hw-Math.abs(dx),oy=a.hh+b.hh-Math.abs(dy);
    if(ox<=0||oy<=0)continue;
    if(ox<oy){const push=(ox+.4)/2*(dx>=0?1:-1);a.x-=push;b.x+=push;}else{const push=(oy+.4)/2*(dy>=0?1:-1);a.y-=push;b.y+=push;}bound(a);bound(b);
   }
  }
  layouts.forEach(n=>{
   const {b,i,o,t,p,x,y,scale}=n,on=platforms[i].id===selected,over=platforms[i].id===hovered||platforms[i].id===focused;
   b.style.transform=`translate(${x}px,${y}px) translate(-50%,-50%) scale(${scale.toFixed(3)})`;b.style.zIndex=String(on||over?16:10+Math.round((p.z/o.r+1)*2));b.style.opacity=String(on||over?1:.78+(p.z/o.r+1)*.10);b.classList.toggle('is-far',p.z<0);b.style.setProperty('--orbit-depth',p.z.toFixed(3));b.dataset.orbitDepth=p.z.toFixed(3);b.dataset.orbitPhase=t.toFixed(5);b.dataset.orbitSpeed=String(o.speed*orbitDirection);
   const isOccluded=p.z<0&&Math.hypot(p.x-cx,p.y-cy)<r;
   if(!isOccluded){const tail=projectOrbit(orbitPoint(o,t-.09*Math.sign(o.speed*orbitDirection)));ctx.strokeStyle=on?'rgba(171,232,255,.7)':'rgba(120,191,239,.3)';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(tail.x,tail.y);ctx.lineTo(p.x,p.y);ctx.stroke();ctx.fillStyle=on?'#d2f2ff':'#8ccff8';ctx.beginPath();ctx.arc(p.x,p.y,on?2.3:1.6,0,TAU);ctx.fill();
    if(Math.hypot(x-p.x,y-p.y)>14){ctx.strokeStyle='rgba(136,199,238,.3)';ctx.lineWidth=.6;ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(x,y);ctx.stroke();}
   }
  });
  visual.dataset.globeLand=landPixels?'ready':'loading';
 }
 function active(){return document.body.classList.contains('landing-view')&&!document.hidden&&visible&&!reduced.matches&&!paused;}
 function animate(stamp){frame=0;if(!active())return;if(!last||stamp-last>=42){const dt=Math.min(65,last?stamp-last:42);if(!drag&&!hovered&&!focused){angle+=.000020*dt+velocity;orbitPhase+=.00011*dt*orbitDirection;velocity*=.93;}last=stamp;draw();}frame=requestAnimationFrame(animate);}
 function sync(){if(frame)cancelAnimationFrame(frame);frame=0;last=0;draw();if(active())frame=requestAnimationFrame(animate);}
 visual.addEventListener('pointerdown',e=>{if(e.target.closest('button,a')||e.button!==0)return;visual.focus({preventScroll:true});drag={id:e.pointerId,x:e.clientX,y:e.clientY};velocity=0;visual.setPointerCapture(e.pointerId);visual.classList.add('dragging');});
 visual.addEventListener('pointermove',e=>{
  const rect=visual.getBoundingClientRect();visual.style.setProperty('--pointer-x',((e.clientX-rect.left)/rect.width*100)+'%');visual.style.setProperty('--pointer-y',((e.clientY-rect.top)/rect.height*100)+'%');
  if(!drag||drag.id!==e.pointerId)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;angle+=dx*.008;viewAngle+=dx*.008;pitch=Math.max(-.85,Math.min(.85,pitch+dy*.004));viewPitch=Math.max(-1.15,Math.min(1.15,viewPitch+dy*.006));velocity=dx*.0005;drag.x=e.clientX;drag.y=e.clientY;draw();
 });
 const release=e=>{if(drag?.id!==e.pointerId)return;drag=null;visual.classList.remove('dragging');if(visual.hasPointerCapture(e.pointerId))visual.releasePointerCapture(e.pointerId);};
 visual.addEventListener('pointerup',release);visual.addEventListener('pointercancel',release);
 visual.addEventListener('keydown',e=>{if(e.target.closest('button,a'))return;if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();angle+=e.key==='ArrowLeft'?-.16:e.key==='ArrowRight'?.16:0;pitch=Math.max(-.85,Math.min(.85,pitch+(e.key==='ArrowUp'?-.1:e.key==='ArrowDown'?.1:0)));viewAngle+=e.key==='ArrowLeft'?-.16:e.key==='ArrowRight'?.16:0;viewPitch=Math.max(-1.15,Math.min(1.15,viewPitch+(e.key==='ArrowUp'?-.1:e.key==='ArrowDown'?.1:0)));draw();}});
 document.querySelector('#geo-pause').onclick=()=>{paused=!paused;const b=document.querySelector('#geo-pause');b.textContent=paused?'▶':'Ⅱ';b.setAttribute('aria-label',paused?'恢复自动旋转':'暂停自动旋转');b.setAttribute('aria-pressed',String(paused));sync();};
 document.querySelector('#geo-reset').onclick=()=>{angle=INITIAL_ANGLE;pitch=INITIAL_PITCH;orbitPhase=0;viewAngle=0;viewPitch=0;velocity=0;sync();};
 const directionButton=document.querySelector('#geo-direction');if(directionButton)directionButton.onclick=()=>{orbitDirection*=-1;directionButton.setAttribute('aria-pressed',String(orbitDirection<0));directionButton.title=orbitDirection<0?'当前已反向，点击恢复卫星原方向':'反转卫星运行方向';draw();};
 document.querySelector('#geo-configure').onclick=()=>{if(platforms.length&&typeof configModal==='function')configModal(selected);};
 window.renderLanding=state=>{
  const changed=state.platforms.map(p=>p.id).join(',')!==platforms.map(p=>p.id).join(',');platforms=state.platforms;
  text('#landing-platform-count',String(platforms.length));text('#landing-service',state.queue?.error?'本地执行器待检查':'本地工作空间已就绪');
  if(changed){
   const host=document.querySelector('#geo-platform-nodes');host.replaceChildren();buttons=platforms.map(p=>{const b=document.createElement('button');b.type='button';b.className='geo-node';b.dataset.platform=p.id;const icon=document.createElement('span');icon.className='geo-node-satellite';icon.setAttribute('aria-hidden','true');const mark=document.createElement('img');mark.src=new URL('platform-icons/'+p.id+'.svg',assetBase).href;mark.alt='';mark.draggable=false;icon.append(mark);const name=document.createElement('span');name.className='geo-node-name';name.textContent=p.name;b.append(icon,name);b.title='仅查看'+p.name+'连接状态，不选择发送目标';b.setAttribute('aria-label','查看'+p.name+'连接状态，不选择发送目标');b.onclick=()=>select(p.id);b.onpointerenter=()=>{hovered=p.id;draw();};b.onpointerleave=()=>{hovered=null;draw();};b.onfocus=()=>{focused=p.id;draw();};b.onblur=()=>{focused=null;draw();};host.append(b);return b;});
   document.querySelector('#landing-platform-list').innerHTML=platforms.map(p=>`<button type="button" data-home-platform="${esc(p.id)}" aria-label="设置${esc(p.name)}连接">${esc(p.name)}<span aria-hidden="true">↗</span></button>`).join('');
   document.querySelectorAll('[data-home-platform]').forEach(b=>b.onclick=()=>configModal(b.dataset.homePlatform));
  }
  update();draw();
 };
 const earlier=window.onWorkspaceView;window.onWorkspaceView=name=>{earlier?.(name);sync();};
 // Bootstrap can finish before this deferred page enhancement loads.
 if(typeof data!=='undefined'&&data?.platforms)window.renderLanding(data);
 new ResizeObserver(sync).observe(canvas);new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;sync();}).observe(canvas);
 document.addEventListener('visibilitychange',sync);reduced.addEventListener('change',sync);sync();
})();


