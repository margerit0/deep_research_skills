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
const finalMode=process.argv.includes('--final'),auditMode=process.argv.includes('--audit')
// The report card's fixed copy lives in the components; read it from source instead of retyping it.
const component=async name=>fs.readFile(path.join(repo,'frontend/src/components',name),'utf8')
const disclaimer=(await component('Conversation.tsx')).match(/disclaimer="([^"]+)"/)[1]
const demoStatus=(await component('ReportCard.tsx')).match(/demo: \['\w+', '([^']+)'\]/)[1]
const eventFrame=id=>plan.events.find(e=>e.id===id).frame
const reportHold=plan.holds.find(h=>h.shot==='report')
let expected
// Independent of the app's outline parser: "# title", "## section" blocks, the last block is the conclusion.
function reportOutline(markdown){
 const [head,...blocks]=markdown.split(/\n(?=## )/)
 const sections=blocks.map(block=>{const [heading,...body]=block.split('\n');return {heading:heading.replace(/^## /,'').trim(),body:body.join('\n').trim()}})
 return {title:head.replace(/^# /,'').trim(),sections:sections.slice(0,-1),conclusion:sections.at(-1)}
}
if(finalMode){
 const approval=JSON.parse(await fs.readFile(path.join(root,'approval.json'),'utf8'))
 // The plan digest covers the compiled timeline, so any timeline edit invalidates the approval.
 if(approval.status!=='approved'||approval.planSha256!==plan.planSha256)throw new Error('Approve this exact plan before final rendering')
}
const url='http://127.0.0.1:5192/product-video/2026-10-31-v8/source/index.html?export'+(finalMode?'&final':'')
// Grayscale glyphs: LCD text flips with layer changes between frames, and yuv420p would smear its colour fringes anyway.
const browser=await chromium.launch({headless:true,args:['--no-proxy-server','--disable-lcd-text'],executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'})
async function open(){
 const page=await browser.newPage({viewport:{width:plan.video.width,height:plan.video.height},deviceScaleFactor:1})
 page.on('pageerror',e=>{errors.push(e.message);console.error(e.message)})
 await page.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin==='http://127.0.0.1:5192'&&!u.pathname.startsWith('/api/'))return route.continue();blocked.push(u.origin+u.pathname);return route.abort()})
 // A cold Vite cache spends the first load scanning and bundling dependencies.
 await page.goto(url,{waitUntil:'domcontentloaded',timeout:180000});await page.waitForFunction(()=>window.sceneLoaded,null,{timeout:180000});return page
}
async function inspect(page,frame){
 return page.evaluate(async frame=>{
  const result=await window.demo.renderFrame(frame)
  const n=document.getElementById('native').contentWindow
  const d=n.document.getElementById('product').contentDocument
  const visible=el=>{let opacity=1;for(let p=el;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden')return false;opacity*=Number(s.opacity)}return opacity>.98}
  const first=window.plan.shots.find(s=>s.id==='chapter-card').startFrame
  const disclosure=frame<first?n.document.querySelector(frame<n.timeline.camera.copy_reveal_end?'#opening-disclosure':'footer .disclosure'):document.querySelector('footer .disclosure')
  const ownTexts=[...document.querySelectorAll('.copy h1,.copy p,.diagram-heading,.diagram-sub,.node h3,.node b,.node p,.node small,.condition,.bottom-note,.gates,.record-strip,.report-caption,.evaluation-inputs,.method-top,#section-eyebrow,#section-heading,#section-subtitle,#section-path')].filter(visible)
  const overflow=ownTexts.filter(el=>el.scrollWidth>el.clientWidth+2||el.scrollHeight>el.clientHeight+2).map(el=>({text:el.textContent,width:el.clientWidth,scroll:el.scrollWidth}))
  const box=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}}
  // A dip must never show the covering layer half-way while its own copy is already visible.
  const layer=(cover,copy)=>{const el=document.getElementById(cover),s=getComputedStyle(el);return s.display==='none'||s.visibility==='hidden'?null:[Number(s.opacity),Number(getComputedStyle(document.querySelector(copy)).opacity)]}
  const nativeFooter=getComputedStyle(n.document.querySelector('footer')).visibility!=='hidden'
  const stageCaption=frame>=first?Number(getComputedStyle(document.querySelector('footer span:not(.disclosure)')).opacity):0
  return {frame,shot:result.shot,disclosure:disclosure?.textContent,visible:visible(disclosure),overflow,fonts:document.fonts.check('20px "Microsoft YaHei"'),
    headline:document.getElementById('headline').textContent,nativeText:d.body.innerText,
    exactPrompt:d.querySelector('textarea')?.value===n.mediaData.prompt,
    report:(()=>{
     const card=d.querySelector('.cw-demo-report')
     if(!card)return null
     const markdown=el=>el?.querySelector('.cw-report-markdown')?.textContent??null
     const conclusion=card.querySelector('.cw-report-conclusion')
     return {head:!!card.querySelector('.cw-report-head'),fallback:!!d.querySelector('.cw-report-fallback'),
      title:card.querySelector('.cw-report-title h3')?.textContent??null,status:card.querySelector('.cw-report-status')?.textContent??null,
      sections:[...card.querySelectorAll('.cw-report-section')].map(s=>({number:s.querySelector('.cw-report-number')?.textContent,heading:s.querySelector('h4')?.textContent,body:markdown(s)})),
      conclusion:conclusion&&{heading:conclusion.querySelector('b')?.textContent,body:markdown(conclusion),summary:conclusion.dataset.summary??null},
      disclaimer:card.querySelector('.cw-report-foot p')?.textContent??null,collapsed:card.dataset.collapsed,
      rawMarkdown:card.innerText.split('\n').some(line=>/^\s*#/.test(line)),
      sourceUi:card.querySelectorAll('.cw-cite,.cw-report-sources,.cw-report-toggle').length}
    })(),
    reportFraming:result.nativeResult?.report??null,
    boardHeader:(()=>{const el=document.querySelector('.board-top');return {opacity:Number(getComputedStyle(el).opacity),bottom:el.getBoundingClientRect().bottom}})(),
    texts:ownTexts.map(el=>el.textContent),bridgeWindow:result.nativeWindow,
    chapterTitle:document.getElementById('section-heading').textContent,
    chapterSubtitle:document.getElementById('section-subtitle').textContent,
    shell:box(document.getElementById('native-shell')),methodCard:box(document.getElementById('shared-method')),
    dips:{chapter:layer('chapter-card','#section-copy'),brand:layer('end-card','#end-card .end-content'),footer:{nativeFooter,stageCaption,cover:layer('chapter-card','#section-copy')?.[0]??null}},
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
 // From the writing stage on, the conversation must hold the report card itself, never its raw-Markdown fallback.
 if(s.frame>=eventFrame('writing')){
  const r=s.report
  if(!r?.head||r.fallback||r.rawMarkdown)throw new Error('Report card missing or raw Markdown '+s.frame)
  if(r.sourceUi)throw new Error('Report shows citation or source UI without sources '+s.frame)
 }
 if(s.frame>=eventFrame('complete')){
  const r=s.report,same=(a,b)=>JSON.stringify(a)===JSON.stringify(b)
  if(r.title!==expected.title||r.status!==demoStatus||r.collapsed!=='false'||r.disclaimer!==disclaimer)throw new Error('Report card header/footer mismatch '+JSON.stringify(r))
  if(!same(r.sections,expected.sections.map((x,i)=>({number:String(i+1).padStart(2,'0'),...x}))))throw new Error('Report sections mismatch '+JSON.stringify(r.sections))
  if(!same(r.conclusion,{...expected.conclusion,summary:null}))throw new Error('Report conclusion mismatch '+JSON.stringify(r.conclusion))
 }
 if(s.frame>=reportHold.startFrame&&s.frame<reportHold.endFrameExclusive){
  const f=s.reportFraming
  if(!f?.inside||f.veil!==0||!f.foot||f.foot.bottom>f.card.bottom||f.composerTop<f.card.bottom)throw new Error('Report card not fully framed '+s.frame+' '+JSON.stringify(f))
 }
 // The shrinking report window must clear the board header before the header fades in behind it.
 if(s.frame>=eventFrame('bridge-start')&&s.boardHeader.opacity>0&&s.shell.y<s.boardHeader.bottom)throw new Error('Report window over the board header '+s.frame)
 const title=plan.shots.find(x=>x.id==='chapter-card')
 if(s.chapterTitle!==title.data.headline||s.chapterSubtitle!==title.data.description)throw new Error('Chapter card copy mismatch')
 for(const pair of [s.dips.chapter,s.dips.brand])if(pair&&pair[0]>.02&&pair[0]<.98&&pair[1]>.02)throw new Error('Copy visible during a cover dip '+s.frame)
 const f=s.dips.footer
 if(f.nativeFooter&&f.stageCaption>.02&&!(f.cover>=.98))throw new Error('Footer captions overlap '+s.frame)
}
try{
 const page=await open()
 expected=reportOutline(await page.evaluate(()=>document.getElementById('native').contentWindow.mediaData.demoReport))
 if(!process.argv.includes('--clips')&&!finalMode&&!auditMode){
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
  const frames=[...new Set([...plan.keyframes.map(k=>k.frame),...plan.events.flatMap(e=>[Math.max(0,e.frame-1),e.frame]),...plan.shots.flatMap(s=>[s.startFrame,Math.min(s.endFrameExclusive-1,s.startFrame+15),s.endFrameExclusive-1]),0,285,295,420,430,479,480,487,495,510,525,540,555,562,569,570,585,600,630,645,690,795,915])].sort((a,b)=>a-b)
  const manifest=[]
  await fs.mkdir(path.join(root,'cache/inspection'),{recursive:true})
  for(const frame of frames){
   const s=await inspect(page,frame);validate(s);layouts.push(s)
   const folder='cache/inspection'
   const file=`${folder}/frame-${String(frame).padStart(4,'0')}.png`
   const bytes=await page.screenshot({path:path.join(root,file)})
   manifest.push({frame,file,sha256:hash(bytes)})
  }
  const another=await open(),random=[]
  for(const frame of [795,150,525,435,645,285,585,915,45,1545]){
   const a=await inspect(page,frame),b=await inspect(another,frame)
   const keys=['shot','headline','nativeText','texts','nodes','wires','shell','methodCard','chapterTitle','chapterSubtitle','report']
   const equal=keys.every(k=>JSON.stringify(a[k])===JSON.stringify(b[k]))
   if(!equal)throw new Error('Non-deterministic semantic state '+frame)
   random.push({frame,semanticEqual:equal})
  }
  await another.close()
  await fs.writeFile(path.join(root,'cache/capture-audit.json'),JSON.stringify({planSha256:plan.planSha256,errors,blocked,clicks,layouts,random,manifest},null,2))
  console.log('Keyframes, native clicks, layout and random access passed.')
 }else{
  // --audit renders the whole film unencoded, only to compare it against the parent version before approval.
  const whole=id=>({id,startFrame:0,endFrameExclusive:plan.video.totalFrames,frameCount:plan.video.totalFrames,durationSeconds:plan.video.durationSeconds})
  const clips=finalMode?[whole('final/frames')]:auditMode?[whole('audit')]:plan.previewClips
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
