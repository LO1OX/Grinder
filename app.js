
const devices = [
  {id:'big',name:'Große Lampe',room:'Wohnzimmer',type:'light',on:true,brightness:46,hue:43,online:true,favorite:true},
  {id:'small',name:'Kleine Lampe',room:'Wohnzimmer',type:'light',on:true,brightness:46,hue:43,online:true,favorite:true},
  {id:'sphere',name:'Kugel',room:'Wohnzimmer',type:'light',on:true,brightness:1,hue:285,online:true,favorite:false},
  {id:'lowboard',name:'Lowboard',room:'Wohnzimmer',type:'light',on:true,brightness:100,hue:38,online:true,favorite:true},
  {id:'atom',name:'Atom-Kern',room:'Wohnzimmer',type:'light',on:true,brightness:72,hue:0,online:true,favorite:false},
  {id:'hall',name:'Flur Lampe',room:'Flur',type:'light',on:false,brightness:0,hue:50,online:false,favorite:false},
  {id:'kitchen',name:'Küchenlicht',room:'Küche',type:'light',on:false,brightness:0,hue:50,online:false,favorite:false},
  {id:'fan',name:'Ceiling Fan 2',room:'Wohnzimmer',type:'fan',on:false,brightness:0,hue:0,online:true,favorite:true},
  {id:'media',name:'PC & Fernseher',room:'Wohnzimmer',type:'switch',on:true,brightness:100,hue:0,online:true,favorite:true}
];

const scenes = [
  {name:'Filmabend',desc:'Lowboard 20 %, Rest aus',action:()=>setScene({lowboard:[true,20,28],big:[false],small:[false],sphere:[false],atom:[false]})},
  {name:'Chillen',desc:'Warm, weich und dunkel',action:()=>setAllLights(true,34,28)},
  {name:'Gaming',desc:'Lila und Blau',action:()=>setScene({big:[true,45,275],small:[true,45,225],lowboard:[true,65,300],sphere:[true,25,250]})},
  {name:'Alles hell',desc:'Alle Lampen 100 %',action:()=>setAllLights(true,100,45)},
  {name:'Nacht',desc:'Kugel 1 %, Rest aus',action:()=>setScene({sphere:[true,1,25],big:[false],small:[false],lowboard:[false],atom:[false]})},
  {name:'Alles aus',desc:'Wohnung ausschalten',action:()=>setAllLights(false,0,0)}
];

function hsl(h){ return `hsl(${h} 100% 50%)`; }

function deviceCard(d){
  const card = document.createElement('article');
  card.className = `device-card ${d.on?'on':'off'} ${d.online?'':'offline'}`;
  card.dataset.id = d.id;
  const controls = d.type === 'light' ? `
    <div class="slider-row">
      <input class="brightness" type="range" min="0" max="100" value="${d.brightness}" ${!d.online?'disabled':''}>
      <strong class="brightnessValue">${d.brightness}%</strong>
    </div>
    <div class="color-strip">
      <input class="hue" type="range" min="0" max="360" value="${d.hue}" ${!d.online?'disabled':''}>
    </div>
    <div class="color-preview" style="background:${hsl(d.hue)}"></div>
  ` : `<div class="device-meta">${d.type==='fan'?'Ventilator':'Steckdose / Medien'}</div>`;
  card.innerHTML = `
    <div class="device-head">
      <div>
        <div class="device-name">${d.name}</div>
        <div class="device-meta">${d.room} · ${d.online?(d.on?'An':'Aus'):'Offline'}</div>
      </div>
      <button class="power" ${!d.online?'disabled':''}>⏻</button>
    </div>
    ${controls}
  `;
  card.querySelector('.power')?.addEventListener('click',()=>{
    d.on=!d.on;
    renderAll();
  });
  card.querySelector('.brightness')?.addEventListener('input',e=>{
    d.brightness=+e.target.value;
    d.on=d.brightness>0;
    card.querySelector('.brightnessValue').textContent=d.brightness+'%';
    card.classList.toggle('on',d.on); card.classList.toggle('off',!d.on);
  });
  card.querySelector('.hue')?.addEventListener('input',e=>{
    d.hue=+e.target.value;
    card.querySelector('.color-preview').style.background=hsl(d.hue);
  });
  return card;
}

function renderGrid(el, list){
  el.innerHTML='';
  list.forEach(d=>el.appendChild(deviceCard(d)));
}

function renderScenes(){
  const grid=document.getElementById('sceneGrid');
  grid.innerHTML='';
  scenes.forEach(s=>{
    const b=document.createElement('button');
    b.className='scene';
    b.innerHTML=`<strong>${s.name}</strong><span>${s.desc}</span>`;
    b.onclick=()=>{s.action();toast(`${s.name} aktiviert`)};
    grid.appendChild(b);
  });
}

function renderCalibrationSelect(){
  const sel=document.getElementById('calDevice');
  sel.innerHTML=devices.filter(d=>d.type==='light').map(d=>`<option value="${d.id}">${d.name}</option>`).join('');
}

function renderAll(){
  renderGrid(document.getElementById('favoriteGrid'), devices.filter(d=>d.favorite));
  renderGrid(document.getElementById('lightsGrid'), devices.filter(d=>d.type==='light'));
  renderGrid(document.getElementById('livingGrid'), devices.filter(d=>d.room==='Wohnzimmer'));
  document.getElementById('livingCount').textContent=devices.filter(d=>d.room==='Wohnzimmer'&&d.type==='light'&&d.on).length;
}

function setAllLights(on, brightness, hue){
  devices.filter(d=>d.type==='light'&&d.online).forEach(d=>{
    d.on=on; d.brightness=on?brightness:0; if(on)d.hue=hue;
  });
  renderAll();
}
function setScene(map){
  Object.entries(map).forEach(([id,v])=>{
    const d=devices.find(x=>x.id===id); if(!d)return;
    d.on=v[0]; if(v.length>1)d.brightness=v[1]; if(v.length>2)d.hue=v[2];
  });
  renderAll();
}
function toast(msg){
  const t=document.getElementById('toast');
  t.textContent=msg;t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),1500);
}

document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(btn.dataset.page).classList.add('active');
}));

document.getElementById('allOffBtn').onclick=()=>{setAllLights(false,0,0);toast('Alle Lampen ausgeschaltet')};
document.getElementById('roomToggle').onclick=()=>{
  const living=devices.filter(d=>d.room==='Wohnzimmer'&&d.type==='light'&&d.online);
  const any= living.some(d=>d.on);
  living.forEach(d=>{d.on=!any;d.brightness=!any?48:0});
  renderAll();
};
document.getElementById('roomBrightness').oninput=e=>{
  devices.filter(d=>d.room==='Wohnzimmer'&&d.type==='light'&&d.online).forEach(d=>{d.brightness=+e.target.value;d.on=d.brightness>0});
  renderAll();
};
document.getElementById('editBtn').onclick=()=>{
  document.body.classList.toggle('editing');
  document.getElementById('editBtn').textContent=document.body.classList.contains('editing')?'Fertig':'Bearbeiten';
  toast(document.body.classList.contains('editing')?'Bearbeitungsmodus aktiv':'Layout gespeichert');
};

// Camera calibration
const steps = [
  {name:'Rot',rgb:[255,0,0],css:'#ff0000'},
  {name:'Grün',rgb:[0,255,0],css:'#00ff00'},
  {name:'Blau',rgb:[0,0,255],css:'#0000ff'},
  {name:'Lila',rgb:[170,0,255],css:'#aa00ff'},
  {name:'Orange',rgb:[255,110,0],css:'#ff6e00'},
  {name:'Warmweiß',rgb:[255,190,120],css:'#ffbe78'},
  {name:'Kaltweiß',rgb:[190,220,255],css:'#bedcff'}
];
let stepIndex=0, stream=null, measurements=[];
const video=document.getElementById('camera');
const swatch=document.getElementById('referenceSwatch');
const stepName=document.getElementById('calStepName');
function updateStep(){
  const s=steps[stepIndex];
  stepName.textContent=s.name; swatch.style.background=s.css;
}
async function startCamera(){
  try{
    stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});
    video.srcObject=stream;
    document.getElementById('captureBtn').disabled=false;
    toast('Kamera gestartet');
  }catch(e){toast('Kamera konnte nicht gestartet werden');}
}
function captureAverage(){
  const canvas=document.getElementById('captureCanvas');
  const w=video.videoWidth,h=video.videoHeight;
  if(!w||!h)return;
  canvas.width=w;canvas.height=h;
  const ctx=canvas.getContext('2d');
  ctx.drawImage(video,0,0,w,h);
  const size=Math.min(w,h)*0.3;
  const x=(w-size)/2,y=(h-size)/2;
  const data=ctx.getImageData(x,y,size,size).data;
  let r=0,g=0,b=0,c=0;
  for(let i=0;i<data.length;i+=16){r+=data[i];g+=data[i+1];b+=data[i+2];c++}
  const avg=[Math.round(r/c),Math.round(g/c),Math.round(b/c)];
  measurements[stepIndex]={name:steps[stepIndex].name,target:steps[stepIndex].rgb,measured:avg};
  renderMeasurements();
  document.getElementById('nextStep').disabled=false;
  if(stepIndex===steps.length-1)document.getElementById('saveProfile').disabled=false;
}
function renderMeasurements(){
  const el=document.getElementById('measurements');
  el.innerHTML=measurements.map(m=>`<div class="measurement"><span>${m.name}</span><strong>${m.measured.join(' / ')}</strong></div>`).join('');
}
document.getElementById('cameraStart').onclick=startCamera;
document.getElementById('captureBtn').onclick=captureAverage;
document.getElementById('nextStep').onclick=()=>{
  if(stepIndex<steps.length-1){stepIndex++;updateStep();document.getElementById('nextStep').disabled=true;}
};
document.getElementById('saveProfile').onclick=()=>{
  const id=document.getElementById('calDevice').value;
  const diag=measurements.slice(0,3);
  const gains=[0,1,2].map(i=>{
    const m=diag[i];
    const peak=Math.max(...m.measured,1);
    return +(255/peak).toFixed(3);
  });
  const profile={
    device:id,
    created:new Date().toISOString(),
    rgbGain:{red:gains[0],green:gains[1],blue:gains[2]},
    measurements
  };
  localStorage.setItem('monohome-profile-'+id,JSON.stringify(profile));
  document.getElementById('profileOutput').textContent=JSON.stringify(profile,null,2);
  toast('Kalibrierungsprofil gespeichert');
};

updateStep();
renderAll();renderScenes();renderCalibrationSelect();

if('serviceWorker' in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('./sw.js'))}
