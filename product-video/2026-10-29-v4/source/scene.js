let plan = await (await fetch('../plan.json')).json()
const $ = id => document.getElementById(id)
const native = $('native')
// Keep the disclosure outside the fading layer, including the transition frame.
const footer=document.querySelector('#explanation footer')
$('stage').append(footer)
const clamp = x => Math.max(0,Math.min(1,x))
const ease = x => { x=clamp(x); return x*x*(3-2*x) }
let current=0, playing=false, busy=false
const ready=(async()=>{
  if (!native.contentWindow?.sceneLoaded) await new Promise(resolve=>native.addEventListener('load',resolve,{once:true}))
  await native.contentWindow.ready
  if(new URLSearchParams(location.search).has('final')){
    native.contentDocument.querySelector('.edition').textContent='产品演示 / v4'
    document.querySelector('.edition').textContent='v4 · 产品演示'
    document.title='星图工作台 · 产品演示 v4'
  }
  await document.fonts.ready
  const mark=native.contentDocument.querySelector('.brand-mark').innerHTML
  document.querySelectorAll('.mark,.end-mark').forEach(el=>el.innerHTML=mark)
})()
const shotById=id=>plan.shots.find(s=>s.id===id)
const eventFrame=id=>plan.events.find(e=>e.id===id).frame
async function renderFrame(frame){
  await ready
  if(!Number.isInteger(frame)||frame<0||frame>=plan.video.totalFrames) throw new Error('Invalid frame '+frame)
  current=frame
  const shot=plan.shots.find(s=>frame>=s.startFrame&&frame<s.endFrameExclusive)
  const first=shotById('diagnose').startFrame, closing=shotById('brand').startFrame
  footer.style.display=frame>=first?'flex':'none'
  const fps=Number(plan.video.fps), transition=Math.round(fps*.5)
  const nativeResult=frame<first?await native.contentWindow.renderFrame(frame):null
  if(frame>=first && native.dataset.held!=='yes') {await native.contentWindow.renderFrame(first-1);native.dataset.held='yes'}
  if(frame<first) native.dataset.held='no'
  native.style.visibility=frame>=first+transition?'hidden':'visible'
  $('explanation').style.opacity=String(ease((frame-first)/transition))
  $('explanation').style.visibility=frame<first?'hidden':'visible'
  $('chapter-number').textContent=String(plan.shots.indexOf(shot)+1).padStart(2,'0')
  $('chapter-label').textContent=shot.label
  $('headline').textContent=shot.data.headline
  $('description').textContent=shot.data.description
  document.querySelectorAll('.diagram').forEach(el=>el.style.display=el.dataset.shot===shot.id?'block':'none')
  for(const el of document.querySelectorAll('[data-reveal]')){
    const progress=ease((frame-eventFrame(el.dataset.reveal))/transition)
    el.style.opacity=String(progress)
    el.style.transform=`translateY(${(1-progress)*14}px)`
  }
  for(const path of document.querySelectorAll('[data-draw]')){
    const progress=ease((frame-eventFrame(path.dataset.draw))/transition)
    path.style.opacity=String(progress)
    if(!path.classList.contains('dashed')){
      const length=path.getTotalLength()
      path.style.strokeDasharray=String(length)
      path.style.strokeDashoffset=String(length*(1-progress))
    }
  }
  const end=ease((frame-closing)/transition)
  $('end-card').style.visibility=frame>=closing?'visible':'hidden'
  $('end-card').style.opacity=String(end)
  $('end-card').style.transform=`translateY(${(1-end)*14}px)`
  $('seek').value=String(frame)
  $('time').textContent=`${(frame/fps).toFixed(1)} / ${plan.video.durationSeconds} 秒`
  await new Promise(resolve=>requestAnimationFrame(resolve))
  return {frame,shot:shot.id,planSha256:plan.planSha256,nativeResult}
}
window.demo={ready, async setPlan(value){plan=value},renderFrame}
window.renderFrame=renderFrame
window.plan=plan
function fit(){ $('stage').style.transform=`scale(${Math.min(innerWidth/plan.video.width,innerHeight/plan.video.height)})` }
fit();addEventListener('resize',fit)
if(new URLSearchParams(location.search).has('export')) document.body.dataset.export='true'
$('seek').max=plan.video.totalFrames-1
$('seek').oninput=async e=>{playing=false;if(!busy){busy=true;await renderFrame(Number(e.target.value));busy=false}}
$('play').textContent=`播放 ${plan.video.durationSeconds} 秒方案`
$('play').onclick=()=>{
  playing=!playing;if(!playing)return
  const start=performance.now(),from=current>=plan.video.totalFrames-1?0:current
  const tick=async()=>{
    if(!playing)return
    const f=Math.min(plan.video.totalFrames-1,from+Math.floor((performance.now()-start)*Number(plan.video.fps)/1000))
    if(!busy){busy=true;await renderFrame(f);busy=false}
    if(f<plan.video.totalFrames-1)requestAnimationFrame(tick);else playing=false
  };requestAnimationFrame(tick)
}
await ready
await renderFrame(Number(new URLSearchParams(location.search).get('frame')??0))
window.sceneLoaded=true
