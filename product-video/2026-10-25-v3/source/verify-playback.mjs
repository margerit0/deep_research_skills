import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { createHash } from 'node:crypto'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(path.resolve(root, '../../frontend/package.json'))
const { chromium } = require('playwright')
const timeline = JSON.parse(await fs.readFile(path.join(root, 'timeline.json'), 'utf8'))
const digest = createHash('sha256').update(await fs.readFile(path.join(root,'preview/motion-sample.mp4'))).digest('hex')
const browser = await chromium.launch({executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true})
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1})
  await page.goto(`http://127.0.0.1:5187/product-video/${timeline.version}/preview/index.html`,{waitUntil:'networkidle'})
  await page.waitForFunction(()=>document.getElementById('motion').controls)
  const audit = await page.evaluate(async()=>{
    const video=document.getElementById('motion'), stamps=[]
    const buffer=await (await fetch(video.src)).arrayBuffer()
    const sample_sha256=[...new Uint8Array(await crypto.subtle.digest('SHA-256',buffer))].map(x=>x.toString(16).padStart(2,'0')).join('')
    let handle
    const record=(now,meta)=>{stamps.push({mediaTime:meta.mediaTime,presentedFrames:meta.presentedFrames});handle=video.requestVideoFrameCallback(record)}
    handle=video.requestVideoFrameCallback(record)
    video.playbackRate=1
    const before=video.getVideoPlaybackQuality(), start=performance.now()
    const ended=new Promise((resolve,reject)=>{video.addEventListener('ended',resolve,{once:true});video.addEventListener('error',reject,{once:true})})
    await video.play(); await ended; video.cancelVideoFrameCallback(handle)
    const quality=video.getVideoPlaybackQuality()
    return {sample_sha256,ended:video.ended,duration:video.duration,resolution:[video.videoWidth,video.videoHeight],playbackRate:video.playbackRate,wallTimeMs:performance.now()-start,fullyBuffered:video.src.startsWith('blob:'),totalVideoFrames:quality.totalVideoFrames,droppedDuringPlayback:quality.droppedVideoFrames-before.droppedVideoFrames,presentedCallbacks:stamps.length,frameCallbackGaps:stamps.slice(1).filter((s,i)=>s.presentedFrames-stamps[i].presentedFrames>1).length,firstCallback:stamps[0],lastCallback:stamps.at(-1),error:video.error?.message??null}
  })
  await fs.writeFile(path.join(root,'cache/playback-audit.json'),JSON.stringify(audit,null,2)+'\n','utf8')
  const count=timeline.motion_sample.last_frame-timeline.motion_sample.first_frame+1
  if(audit.sample_sha256!==digest || !audit.ended || audit.totalVideoFrames!==count || audit.duration!==count/timeline.fps || audit.droppedDuringPlayback || audit.frameCallbackGaps) throw Error('Playback verification failed; inspect cache/playback-audit.json')
  console.log(JSON.stringify(audit,null,2))
} finally { await browser.close() }
