import fs from 'node:fs/promises'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createRequire} from 'node:module'
import {createHash} from 'node:crypto'
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'..'),repo=path.resolve(here,'../../..')
const require=createRequire(path.join(repo,'frontend/package.json'))
const {chromium}=require('playwright')
const plan=JSON.parse(await fs.readFile(path.join(root,'plan.json'),'utf8'))
const browser=await chromium.launch({headless:true,args:['--no-proxy-server'],executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'})
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],blocked=[],results=[]
page.on('pageerror',e=>errors.push(e.message))
await page.route('**/*',route=>{
 const url=new URL(route.request().url())
 if(url.origin==='http://127.0.0.1:5190')return route.continue()
 blocked.push(url.origin+url.pathname);return route.abort()
})
try{
 await page.goto('http://127.0.0.1:5190/product-video/2026-10-29-v6/preview/index.html')
 await page.waitForSelector('video')
 for(const clip of plan.previewClips){
  const selector=`video[src="${clip.id}.mp4"]`
  await page.locator(selector).scrollIntoViewIfNeeded()
  await page.locator(selector).evaluate(v=>{v.muted=true;v.playbackRate=1;v.currentTime=0;window.framesSeen=[];const cb=(_,m)=>{window.framesSeen.push({time:m.mediaTime,presented:m.presentedFrames});if(!v.ended)v.requestVideoFrameCallback(cb)};v.requestVideoFrameCallback(cb);window.baseQuality=v.getVideoPlaybackQuality().totalVideoFrames})
  await page.locator(selector).click({position:{x:50,y:50}})
  await page.locator(selector).evaluate(v=>v.play())
  await page.waitForFunction(sel=>document.querySelector(sel).ended,selector,{timeout:45000})
  const result=await page.locator(selector).evaluate(v=>({duration:v.duration,ended:v.ended,rate:v.playbackRate,width:v.videoWidth,height:v.videoHeight,error:v.error?.message??null,framesSeen:window.framesSeen,quality:{total:v.getVideoPlaybackQuality().totalVideoFrames,dropped:v.getVideoPlaybackQuality().droppedVideoFrames,baseline:window.baseQuality}}))
  if(!result.ended||result.error||Math.abs(result.duration-clip.durationSeconds)>.01||result.framesSeen.length<clip.frameCount*.7)throw new Error('Playback failed '+clip.id)
  result.clip=clip.id
  result.sha256=createHash('sha256').update(await fs.readFile(path.join(root,'preview',`${clip.id}.mp4`))).digest('hex')
  results.push(result)
  console.log(`${clip.id}: ended, ${result.duration}s, ${result.framesSeen.length} frame callbacks`)
 }
 await fs.writeFile(path.join(root,'preview/playback-verification.json'),JSON.stringify({planSha256:plan.planSha256,results,errors,blocked,subjectiveListening:'not_applicable_silent_preview',visualPlaybackReview:'not_claimed_by_automated_playback'},null,2))
 if(errors.length||blocked.length)throw new Error(JSON.stringify({errors,blocked}))
}finally{await browser.close()}
