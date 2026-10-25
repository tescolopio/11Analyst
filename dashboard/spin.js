(function(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ElevenSpin = api;
})(globalThis, function() {
  "use strict";
  const TAU = 2 * Math.PI;
  const presets = {
    top: {name: "Topspin", x: 1, text: "The top surface rotates in the incoming travel direction (+Z)."},
    back: {name: "Backspin", x: -1, text: "The top surface rotates against the incoming travel direction."},
    clockwise: {name: "Clockwise sidespin (viewed from above)", y: -1, text: "Viewed from above, the surface rotates clockwise. The angular-velocity axis is -Y."},
    counterclockwise: {name: "Counterclockwise sidespin (viewed from above)", y: 1, text: "Viewed from above, the surface rotates counterclockwise. The angular-velocity axis is +Y."},
    topClockwise: {name: "Topspin + clockwise sidespin", x: 1, y: -1, text: "Topspin and overhead-clockwise sidespin combine around a tilted axis."},
    topCounterclockwise: {name: "Topspin + counterclockwise sidespin", x: 1, y: 1, text: "Topspin and overhead-counterclockwise sidespin combine around a tilted axis."},
    backClockwise: {name: "Backspin + clockwise sidespin", x: -1, y: -1, text: "Backspin and overhead-clockwise sidespin combine around a tilted axis."},
    backCounterclockwise: {name: "Backspin + counterclockwise sidespin", x: -1, y: 1, text: "Backspin and overhead-counterclockwise sidespin combine around a tilted axis."},
    zero: {name: "Negligible spin (synthetic zero)", text: "A valid zero vector: no rotation and no axis-direction claim. Missing measurements are different from zero."},
    axial: {name: "Axial rotation (+Z, advanced)", z: 1, text: "Rotation is around the travel direction. This third component is preserved independently of top/back and sidespin."},
  };
  const dot = (a,b) => a.reduce((sum,value,i) => sum+value*b[i],0);
  const cross = (a,b) => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const unit = a => {const n=Math.hypot(...a); return n ? a.map(v=>v/n) : a.map(()=>0);};
  const xyz = v => ({x:v[0],y:v[1],z:v[2]});
  const array = v => [v.x,v.y,v.z];
  const vector = v => v && ["x","y","z"].every(k=>Number.isFinite(v[k]));
  function multiply(a,b) {
    return [a[0]*b[0]-dot(a.slice(1),b.slice(1)),
      ...cross(a.slice(1),b.slice(1)).map((v,i)=>v+a[0]*b[i+1]+b[0]*a[i+1])];
  }
  function integrate(q, omega, seconds) {
    if (!q.every(Number.isFinite) || q.length!==4 || !Math.hypot(...q)
      || !omega.every(Number.isFinite) || omega.length!==3 || !Number.isFinite(seconds) || seconds<0) throw new Error("Invalid rotation state");
    const speed=Math.hypot(...omega), half=speed*seconds/2;
    if (!Number.isFinite(half)) throw new Error("Rotation step exceeds numeric range");
    const delta=[Math.cos(half),...unit(omega).map(v=>v*Math.sin(half))];
    return unit(multiply(delta,q));
  }
  function rotate(q,v) {return multiply(multiply(q,[0,...v]),[q[0],-q[1],-q[2],-q[3]]).slice(1);}
  function camera(name) {
    const position={receiver:[.25,.2,1],side:[1,.2,0],overhead:[0,1,0]}[name];
    if(!position)throw new Error("Unknown camera");
    const forward=unit(position), right=unit(cross(name==="overhead"?[0,0,-1]:[0,1,0],forward));
    return {forward,right,up:cross(forward,right)};
  }
  function project(v, basis) {return [dot(v,basis.right),-dot(v,basis.up),dot(v,basis.forward)];}
  function record(preset, rate, balance, speed) {
    const p=presets[preset];
    if(!p || ![rate,balance,speed].every(Number.isFinite) || rate<0 || speed<0 || balance<0 || balance>1) throw new Error("Invalid synthetic spin controls");
    const angle=balance*Math.PI/2, mixed=p.x&&p.y;
    const omega=[(p.x||0)*(mixed?Math.cos(angle):1),(p.y||0)*(mixed?Math.sin(angle):1),p.z||0].map(v=>v*rate*TAU);
    return {schemaVersion:"1",conventionVersion:"receiver-rh-1",sourceKind:"synthetic",
      angularVelocityRadPerSec:xyz(omega),linearVelocityMPerSec:xyz([0,0,speed]),
      spinLabel:p.name,evidenceStatus:"illustrative",measurementEvent:"synthetic example"};
  }
  function validate(value) {
    if(value.schemaVersion!=="1" || value.conventionVersion!=="receiver-rh-1" || value.sourceKind!=="synthetic"
      || !vector(value.linearVelocityMPerSec) || value.linearVelocityMPerSec.x!==0 || value.linearVelocityMPerSec.y!==0
      || value.linearVelocityMPerSec.z<0)throw new Error("Unsupported spin record or units; this prototype supports synthetic +Z travel only");
    if(value.angularVelocityRadPerSec==null)return {unknown:true};
    if(!vector(value.angularVelocityRadPerSec))throw new Error("Angular velocity must contain finite x/y/z values");
    return {unknown:false,zero:Math.hypot(...array(value.angularVelocityRadPerSec))===0};
  }
  function advance(state,value,elapsed) {
    const check=validate(value), seconds=elapsed*state.timeScale;
    if(check.unknown)throw new Error("Cannot animate unknown spin");
    if(!Number.isFinite(seconds)||seconds<0)throw new Error("Invalid playback interval");
    return {...state,q:integrate(state.q,array(value.angularVelocityRadPerSec),seconds),time:state.time+seconds,
      distance:state.distance+(state.mode==="travel"?seconds*value.linearVelocityMPerSec.z:0)};
  }
  function draw(canvas, value, state) {
    const ctx=canvas.getContext("2d");
    if(!ctx)throw new Error("Canvas rendering is unavailable");
    const check=validate(value), w=canvas.width, h=canvas.height;
    ctx.clearRect(0,0,w,h);ctx.fillStyle="#f4f7f1";ctx.fillRect(0,0,w,h);
    ctx.font="15px Segoe UI, sans-serif";ctx.fillStyle="#203630";
    if(check.unknown){ctx.fillText("Spin unknown: no rotation or direction is inferred.",25,h/2);return;}
    const basis=camera(state.camera), radius=83;
    const distance=state.mode==="travel"?(state.distance%3)-1.5:0;
    const shift=project([0,0,distance],basis), cx=w/2+shift[0]*90, cy=h/2+shift[1]*90;
    const screen=v=>{const p=project(v,basis);return [cx+p[0]*radius,cy+p[1]*radius,p[2]];};
    const line=(a,b,color,width=2)=>{
      ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();
    };
    const arrow=(a,b,color)=>{
      line(a,b,color,3);const angle=Math.atan2(b[1]-a[1],b[0]-a[0]);
      ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(b[0],b[1]);
      for(const offset of [-.5,.5])ctx.lineTo(b[0]-10*Math.cos(angle+offset),b[1]-10*Math.sin(angle+offset));
      ctx.closePath();ctx.fill();
    };
    // The ground and travel distance are orientation aids, not a flight or bounce simulation.
    const corners=[[-2,-1.2,-1.5],[2,-1.2,-1.5],[2,-1.2,1.5],[-2,-1.2,1.5]];
    corners.forEach((v,i)=>line(screen(v),screen(corners[(i+1)%4]),"#c9d6c6"));
    if(state.labels){
      ctx.fillText("+X: receiver right   +Y: up   +Z: incoming travel",20,25);
      ctx.fillText(`Camera: ${state.camera} | Opponent -Z / Receiver +Z`,20,47);
    }
    if(state.travel){arrow(screen([-2,0,-.7]),screen([-2,0,.7]),"#387d99");ctx.fillStyle="#387d99";ctx.fillText("Travel +Z",25,h-28);}
    const gradient=ctx.createRadialGradient(cx-25,cy-30,5,cx,cy,radius);
    gradient.addColorStop(0,"#ffffff");gradient.addColorStop(.7,"#f5f0de");gradient.addColorStop(1,"#aab6a5");
    ctx.fillStyle=gradient;ctx.beginPath();ctx.arc(cx,cy,radius,0,TAU);ctx.fill();
    ctx.save();ctx.beginPath();ctx.arc(cx,cy,radius,0,TAU);ctx.clip();
    ctx.strokeStyle="#243d32";ctx.lineWidth=7;ctx.beginPath();let active=false;
    for(let i=0;i<=240;i++){
      const t=i/240*TAU,p=screen(rotate(state.q,unit([Math.cos(t),.22,Math.sin(t)])));
      if(p[2]<0){active=false;continue;}
      if(active)ctx.lineTo(p[0],p[1]);else ctx.moveTo(p[0],p[1]);active=true;
    }
    ctx.stroke();
    for(const [v,color,size] of [[[.2,.9,.35],"#a4472e",11],[[-.6,.25,.75],"#2f7693",8],[[.5,-.6,.4],"#243d32",5]]){
      const p=screen(rotate(state.q,unit(v)));
      if(p[2]>0){ctx.fillStyle=color;ctx.beginPath();ctx.ellipse(p[0],p[1],size,size*(.3+.7*p[2]),0,0,TAU);ctx.fill();}
    }
    ctx.restore();
    const axis=unit(array(value.angularVelocityRadPerSec));
    if(!check.zero&&state.axis){
      arrow(screen(axis.map(v=>-1.3*v)),screen(axis.map(v=>1.3*v)),"#8e582b");
      ctx.fillStyle="#8e582b";ctx.fillText("Angular-velocity axis (right-hand rule)",20,h-7);
    }
    if(!check.zero&&state.rotation){
      const u=unit(cross(axis,Math.abs(axis[0])<.8?[1,0,0]:[0,1,0])),v=cross(axis,u);
      let previous;
      for(let i=0;i<=65;i++){
        const t=.4+i/65*Math.PI*1.3,p=screen(u.map((n,j)=>1.28*(n*Math.cos(t)+v[j]*Math.sin(t))));
        if(previous){if(i===65)arrow(previous,p,"#a4472e");else line(previous,p,"#a4472e",2);}
        previous=p;
      }
    }
    ctx.fillStyle="#203630";
    ctx.fillText(state.mode==="travel"?`Straight-travel loop ${Math.floor(state.distance/3)+1} (resets at path end)`:"Inspect mode: ball centered; no flight simulated",20,h-50);
  }
  function initialize(onError) {
    const $=id=>document.getElementById(id), reduced=matchMedia("(prefers-reduced-motion: reduce)");
    const state={camera:"receiver",mode:"inspect",axis:true,rotation:true,travel:true,labels:true,timeScale:1,time:0,distance:0,q:[1,0,0,0],playing:false};
    let value,frame=null,last=null;
    for(const [id,preset] of Object.entries(presets)){
      const option=document.createElement("option");option.value=id;option.textContent=preset.name;$("spin-preset").append(option);
    }
    function render() {
      draw($("spin-canvas"),value,state);
      $("spin-play").textContent=state.playing?"Pause":"Play";
      $("spin-play").disabled=reduced.matches;
      $("spin-clock").textContent=`Illustrative | ${state.playing?"Playing":"Paused"} | ${state.time.toFixed(1)} synthetic seconds | playback ${state.timeScale}x`;
      $("spin-canvas").setAttribute("aria-label",`Illustrative ${value.spinLabel}. ${presets[$("spin-preset").value].text}`);
    }
    function stop(){state.playing=false;last=null;if(frame!==null)cancelAnimationFrame(frame);frame=null;}
    function sync() {
      value=record($("spin-preset").value,Number($("spin-rate").value),Number($("spin-balance").value)/100,Number($("spin-speed").value));
      const p=presets[$("spin-preset").value];
      $("spin-explanation").textContent=`Illustrative. ${p.text} Camera changes do not change the physical vector or the overhead naming convention.`;
      const magnitude=Math.hypot(...array(value.angularVelocityRadPerSec));
      $("spin-rate-value").textContent=`${(magnitude/TAU).toFixed(1)} rev/s (${magnitude.toFixed(2)} rad/s)`;
      $("spin-balance").disabled=!(p.x&&p.y);$("spin-rate").disabled=$("spin-preset").value==="zero";
      $("spin-balance-value").textContent=`${$("spin-balance").value}% toward sidespin; total magnitude stays constant`;
      $("spin-speed").disabled=state.mode==="inspect";$("spin-speed-value").textContent=`${$("spin-speed").value} m/s (synthetic)`;
      $("spin-speed-help").textContent=state.mode==="inspect"?"Travel speed is disabled in inspect mode; choose straight travel to translate the ball.":"Straight translation only; no spin-induced curve or bounce prediction.";
      $("spin-accessibility").textContent=reduced.matches?"Reduced motion: animation is disabled. Use Step for static inspection; explanations remain available.":"Starts paused. Step advances 0.1 displayed seconds. Playback scaling does not change stored physical values.";
      $("spin-alias").hidden=Number($("spin-rate").value)*state.timeScale<=3 || $("spin-preset").value==="zero";
      $("spin-contract").textContent=JSON.stringify({...value,viewState:{camera:state.camera,mode:state.mode,timeScale:state.timeScale,overlays:{axis:state.axis,rotation:state.rotation,travel:state.travel,labels:state.labels},playing:state.playing}},null,2);
      render();
    }
    function tick(now){
      try{
        if(!state.playing)return;
        if(last!==null)Object.assign(state,advance(state,value,(now-last)/1000));
        last=now;render();frame=requestAnimationFrame(tick);
      }catch(error){stop();onError(error);}
    }
    function reset(){stop();state.q=[1,0,0,0];state.time=0;state.distance=0;state.camera="receiver";state.timeScale=1;state.mode="inspect";$("spin-camera").value="receiver";$("spin-mode").value="inspect";$("spin-playback").value="1";$("spin-rate").value="1";$("spin-speed").value="2";$("spin-balance").value="50";sync();}
    const listen=(id,event,action)=>$(id).addEventListener(event,()=>{try{action();}catch(error){stop();onError(error);}});
    listen("spin-preset","change",reset);
    for(const id of ["spin-rate","spin-balance","spin-speed"])listen(id,"input",sync);
    listen("spin-camera","change",()=>{state.camera=$("spin-camera").value;sync();});
    listen("spin-reset-view","click",()=>{state.camera="receiver";$("spin-camera").value="receiver";sync();});
    listen("spin-mode","change",()=>{state.mode=$("spin-mode").value;sync();});
    listen("spin-playback","change",()=>{state.timeScale=Number($("spin-playback").value);sync();});
    for(const name of ["axis","rotation","travel","labels"])listen(`spin-${name}`,"change",()=>{state[name]=$(`spin-${name}`).checked;sync();});
    listen("spin-play","click",()=>{if(state.playing)stop();else if(!reduced.matches){state.playing=true;last=null;frame=requestAnimationFrame(tick);}sync();});
    listen("spin-step","click",()=>{stop();Object.assign(state,advance(state,value,.1));sync();});
    listen("spin-reset","click",reset);
    listen("spin-advanced","change",()=>{
      const option=$("spin-preset").querySelector('[value="axial"]');option.hidden=!$("spin-advanced").checked;option.disabled=option.hidden;
      if(option.hidden&&$("spin-preset").value==="axial"){$("spin-preset").value="top";reset();}
    });
    $("spin-preset").querySelector('[value="axial"]').hidden=true;
    $("spin-preset").querySelector('[value="axial"]').disabled=true;
    reduced.addEventListener("change",()=>{stop();sync();});
    document.addEventListener("visibilitychange",()=>{if(document.hidden){stop();sync();}});
    reset();
    return {snapshot:()=>({record:structuredClone(value),viewState:structuredClone(state)})};
  }
  return {presets,record,validate,integrate,rotate,cross,camera,project,advance,draw,initialize};
});
