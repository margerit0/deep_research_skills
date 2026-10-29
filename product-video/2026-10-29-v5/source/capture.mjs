import fs from 'node:fs/promises'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createRequire} from 'node:module'
import {createHash} from 'node:crypto'
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'..'),repo=path.resolve(here,'../../..')
const require=createRequire(path.join(repo,'frontend/package.json'))
const {chromium}=require('playwright')
const plan=JSON.parse(await fs.readFile(path.join(root,'plan.json'),'utf8'))
const hash=x=>createHash('sha256').update(x).digest('hex')
const errors=[],blocked=[],clicks=[],layouts=[]
const finalMode=process.argv.includes('--final')
if(finalMode){
 const approval=JSON.parse(await fs.readFile(path.join(root,'approval.json'),'utf8'))
 if(approval.status!=='approved'||approval.planSha256!==plan.planSha256)throw new Error('Approve this exact plan before final rendering')
 const current=JSON.parse(await fs.readFile(path.join(root,'timeline.json'),'utf8'))
 const approved=JSON.parse(await fs.readFile(path.join(root,'preview/approved-timeline.json'),'utf8'))
 if(JSON.stringify(current)!==JSON.stringify(approved))throw new Error('Approved timeline changed')
}
const url='http://127.0.0.1:5189/product-video/2026-10-29-v5/source/index.html?export'+(finalMode?'&final':'')
const browser=await chromium.launch({headless:true,args:['--no-proxy-server'],executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'})
async function open(){
 const page=await browser.newPage({viewport:{width:plan.video.width,height:plan.video.height},deviceScaleFactor:1})
 page.on('pageerror',e=>{errors.push(e.message);console.error(e.message)})
 await page.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin==='http://127.0.0.1:5189'&&!u.pathname.startsWith('/api/'))return route.continue();blocked.push(u.origin+u.pathname);return route.abort()})
 await page.goto(url,{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.sceneLoaded);return page
}
async function inspect(page,frame){
 return page.evaluate(async frame=>{
  const result=await window.demo.renderFrame(frame)
  const n=document.getElementById('native').contentWindow
  const d=n.document.getElementById('product').contentDocument
  const visible=el=>{let opacity=1;for(let p=el;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden')return false;opacity*=Number(s.opacity)}return opacity>.98}
  const first=window.plan.shots.find(s=>s.id==='method').startFrame
  const disclosure=frame<first?n.document.querySelector(frame<n.timeline.camera.copy_reveal_end?'#opening-disclosure':'footer .disclosure'):document.querySelector('footer .disclosure')
  const ownTexts=[...document.querySelectorAll('.copy h1,.copy p,.diagram-heading,.diagram-sub,.node h3,.node b,.node p,.node small,.condition,.bottom-note,.gates,.record-strip,.report-caption,.evaluation-inputs,.method-top')].filter(visible)
  const overflow=ownTexts.filter(el=>el.scrollWidth>el.clientWidth+2||el.scrollHeight>el.clientHeight+2).map(el=>({text:el.textContent,width:el.clientWidth,scroll:el.scrollWidth}))
  const box=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}}
  return {frame,shot:result.shot,disclosure:disclosure?.textContent,visible:visible(disclosure),overflow,fonts:document.fonts.check('20px "Microsoft YaHei"'),
    headline:document.getElementById('headline').textContent,nativeText:d.body.innerText,
    exactPrompt:d.querySelector('textarea')?.value===n.mediaData.prompt,
    exactReport:d.querySelector('.cw-demo-report')?.textContent===n.mediaData.demoReport,
    texts:ownTexts.map(el=>el.textContent),bridgeWindow:result.nativeWindow,
    shell:box(document.getElementById('native-shell')),methodCard:box(document.getElementById('shared-method')),
    nativeLayout:frame===0?{viewport:[n.innerWidth,n.innerHeight],appViewport:[d.defaultView.innerWidth,d.defaultView.innerHeight],elements:['.cw-sidebar','.cw-composer-wrap','.cw-graph-panel','.cw-composer'].map(selector=>{const e=d.querySelector(selector);return {selector,box:e?box(e):null,font:e?d.defaultView.getComputedStyle(e).fontSize:null}})}:null,
    clicks:result.nativeResult?.clickAudit??[],
    nodes:[...d.querySelectorAll('[data-flow-node]')].map(e=>e.getAttribute('data-flow-node')),
    wires:[...d.querySelectorAll('.cw-wire')].map(e=>({d:e.getAttribute('d'),marker:e.getAttribute('marker-end'),loop:e.classList.contains('is-loop')}))}
 },frame)
}
function validate(s){
 if(!s.visible||s.disclosure!=='合成演示 · 流程已压缩')throw new Error('Disclosure '+s.frame)
 if(s.overflow.length)throw new Error('Overflow '+JSON.stringify(s.overflow))
 if(!s.fonts||s.texts.some(x=>x.includes('\uFFFD')))throw new Error('Text/font '+s.frame)
 const shot=plan.shots.find(x=>x.id===(s.shot==='brand'?'release':s.shot))
 if(s.headline!==shot.data.headline)throw new Error('Headline mismatch')
 if(s.frame===105&&!s.exactPrompt)throw new Error('Source prompt mismatch')
 if(s.frame===435&&!s.exactReport)throw new Error('Source report mismatch')
}
try{
 const page=await open()
 if(!process.argv.includes('--clips')&&!finalMode){
  const opening=await inspect(page,0);validate(opening);layouts.push(opening)
  const data=await page.evaluate(()=>document.getElementById('native').contentWindow.mediaData)
  await fs.writeFile(path.join(root,'cache/source-texts.json'),JSON.stringify(data,null,2))
  for(const e of plan.events.filter(e=>e.kind==='click')){
   const s=await inspect(page,e.frame);validate(s)
   const c=s.clicks.findLast(c=>c.id===e.id)
   if(!c?.hit||!c.visible||!c.callbackMatches||!c.insideViewport||!c.callbacks.length)throw new Error('Click failed '+JSON.stringify(c))
   if(e.id==='choose-skill'&&!s.nativeText.includes('产品对比'))throw new Error('Skill selection missing')
   clicks.push(c)
  }
  const frames=[...new Set([...plan.keyframes.map(k=>k.frame),...plan.events.flatMap(e=>[Math.max(0,e.frame-1),e.frame]),0,285,295,420,430,479,480,487,495,510,525,540,585,600,607,615,630,645,660,690,719,720,727,735,749,750,1410,1425,1499])].sort((a,b)=>a-b)
  const manifest=[]
  await fs.mkdir(path.join(root,'cache/inspection'),{recursive:true})
  for(const frame of frames){
   const s=await inspect(page,frame);validate(s);layouts.push(s)
   const folder=plan.keyframes.some(k=>k.frame===frame)?'preview':'cache/inspection'
   const file=`${folder}/frame-${String(frame).padStart(4,'0')}.png`
   const bytes=await page.screenshot({path:path.join(root,file)})
   manifest.push({frame,file,sha256:hash(bytes)})
  }
  const another=await open(),random=[]
  for(const frame of [690,150,555,285,825,45,1455]){
   const a=await inspect(page,frame),b=await inspect(another,frame)
   const keys=['shot','headline','nativeText','texts','nodes','wires','shell','methodCard']
   const equal=keys.every(k=>JSON.stringify(a[k])===JSON.stringify(b[k]))
   if(!equal)throw new Error('Non-deterministic semantic state '+frame)
   random.push({frame,semanticEqual:equal})
  }
  await another.close()
  await fs.writeFile(path.join(root,'cache/capture-audit.json'),JSON.stringify({planSha256:plan.planSha256,errors,blocked,clicks,layouts,random,manifest},null,2))
  console.log('Keyframes, native clicks, layout and random access passed.')
 }else{
  const clips=finalMode?[{id:'final/frames',startFrame:0,endFrameExclusive:plan.video.totalFrames,frameCount:plan.video.totalFrames,durationSeconds:plan.video.durationSeconds}]:plan.previewClips
  for(const clip of clips){
   const folder=path.join(root,'cache',clip.id);await fs.mkdir(folder,{recursive:true})
   const frames=[]
   for(let f=clip.startFrame;f<clip.endFrameExclusive;f++){
    const s=await inspect(page,f);validate(s)
    if(finalMode){
     const event=plan.events.find(e=>e.kind==='click'&&e.frame===f)
     if(event){
      const c=s.clicks.findLast(c=>c.id===event.id)
      if(!c?.hit||!c.visible||!c.callbackMatches||!c.insideViewport||!c.callbacks.length)throw new Error('Final native click failed '+event.id)
      clicks.push(c)
     }
    }
    const filename=`frame-${String(f).padStart(4,'0')}.png`
    const bytes=await page.screenshot({path:path.join(folder,filename)})
    frames.push({frame:f,file:filename,sha256:hash(bytes)})
    if(f%90===0)console.log(`${clip.id}: ${f}/${clip.endFrameExclusive-1}`)
   }
   await fs.writeFile(path.join(folder,'manifest.json'),JSON.stringify({planSha256:plan.planSha256,clip,frames,errors,blocked,clicks},null,2))
  }
 }
 if(errors.length||blocked.length)throw new Error(JSON.stringify({errors,blocked}))
}finally{await browser.close()}
