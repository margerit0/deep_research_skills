// Negative controls: the report checks must reject the very states they exist to catch.
import fs from 'node:fs/promises'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createRequire} from 'node:module'
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'..'),repo=path.resolve(here,'../../..')
const require=createRequire(path.join(repo,'frontend/package.json'))
const {chromium}=require('playwright')
const plan=JSON.parse(await fs.readFile(path.join(root,'plan.json'),'utf8'))
const audit=JSON.parse(await fs.readFile(path.join(root,'cache/capture-audit.json'),'utf8'))
const capture=await fs.readFile(path.join(here,'capture.mjs'),'utf8')
// Exercise the real validate() from capture.mjs, not a copy of its rules.
const source=capture.slice(capture.indexOf('function validate(s){'),capture.indexOf('\ntry{'))
const at=frame=>structuredClone(audit.layouts.find(s=>s.frame===frame))
const good=at(435).report
const expected={title:good.title,sections:good.sections.map(({heading,body})=>({heading,body})),conclusion:{heading:good.conclusion.heading,body:good.conclusion.body}}
const validate=new Function('plan','eventFrame','reportHold','expected','disclaimer','demoStatus',source+';return validate')(plan,id=>plan.events.find(e=>e.id===id).frame,plan.holds.find(h=>h.shot==='report'),expected,good.disclaimer,good.status)
const fallback={head:false,fallback:true,title:null,status:null,sections:[],conclusion:null,disclaimer:null,rawMarkdown:true,sourceUi:0}
const cases=[
 ['写作阶段拍到 Suspense 回退态',375,s=>{s.report=fallback},/Report card missing/],
 ['报告镜头拍到 Suspense 回退态',435,s=>{s.report=fallback},/Report card missing/],
 ['卡片里残留原始 #',435,s=>{s.report.rawMarkdown=true},/raw Markdown/],
 ['出现引用或来源控件',435,s=>{s.report.sourceUi=1},/citation or source UI/],
 ['报告被折叠',435,s=>{s.report.collapsed='true'},/header\/footer/],
 ['标题不符',435,s=>{s.report.title='研究摘要'},/header\/footer/],
 ['状态标签不符',435,s=>{s.report.status='已完成'},/header\/footer/],
 ['免责声明缺失',435,s=>{s.report.disclaimer=null},/header\/footer/],
 ['章节标题不符',435,s=>{s.report.sections[1].heading='商业'},/sections mismatch/],
 ['章节编号不符',435,s=>{s.report.sections[2].number='04'},/sections mismatch/],
 ['少一个章节',435,s=>{s.report.sections.pop()},/sections mismatch/],
 ['下一步正文不符',435,s=>{s.report.conclusion.body='结论已确认。'},/conclusion mismatch/],
 ['卡片越出镜头',435,s=>{s.reportFraming.inside=false},/not fully framed/],
 ['底部说明越出卡片',435,s=>{s.reportFraming.foot.bottom=s.reportFraming.card.bottom+1},/not fully framed/],
 ['输入框压住卡片',435,s=>{s.reportFraming.composerTop=s.reportFraming.card.bottom-1},/not fully framed/],
 ['遮罩未退',435,s=>{s.reportFraming.veil=.5},/not fully framed/],
 ['报告窗口压住看板顶栏',585,s=>{s.boardHeader.opacity=.5;s.shell.y=s.boardHeader.bottom-1},/board header/],
]
for(const frame of [375,435,585])validate(at(frame))
const results=cases.map(([name,frame,mutate,pattern])=>{
 const state=at(frame);mutate(state)
 let message=null
 try{validate(state)}catch(error){message=error.message}
 if(!message||!pattern.test(message))throw new Error(`Guard did not reject: ${name} -> ${message}`)
 return {name,frame,rejectedBy:message.slice(0,80)}
})
// With the card chunk unavailable the render must fail loudly instead of filming the fallback.
const browser=await chromium.launch({headless:true,args:['--no-proxy-server','--disable-lcd-text'],executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'})
let chunk
try{
 const page=await browser.newPage({viewport:{width:1920,height:1080}}),errors=[]
 page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/*',route=>{
  const u=new URL(route.request().url())
  if(u.pathname.endsWith('/components/ReportCard.tsx')||u.origin!=='http://127.0.0.1:5192'||u.pathname.startsWith('/api/'))return route.abort()
  return route.continue()
 })
 await page.goto('http://127.0.0.1:5192/product-video/2026-10-31-v8/source/index.html?export',{waitUntil:'domcontentloaded'})
 for(let wait=0;wait<300&&!errors.some(m=>m.includes('did not load'));wait++)await page.waitForTimeout(200)
 chunk={message:errors.find(m=>m.includes('did not load'))??null,sceneLoaded:await page.evaluate(()=>!!window.sceneLoaded)}
 if(!chunk.message||chunk.sceneLoaded)throw new Error('Blocked chunk did not fail the render '+JSON.stringify({chunk,errors}))
}finally{await browser.close()}
await fs.mkdir(path.join(root,'preview'),{recursive:true})
await fs.writeFile(path.join(root,'preview/guard-verification.json'),JSON.stringify({planSha256:plan.planSha256,positiveFrames:[375,435,585],rejected:results,blockedChunk:chunk},null,2))
console.log(`${results.length} invalid states rejected; blocked chunk failed the render: ${chunk.message}`)
