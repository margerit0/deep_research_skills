// Full-speed playback with enabled audio and an audio signal meter.
// Numerical measurements do not substitute for subjective listening.
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { createHash } from 'node:crypto'
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const require=createRequire(path.resolve(root,'../../frontend/package.json'))
const {chromium}=require('playwright')
const plan=JSON.parse(await fs.readFile(path.join(root,'plan.json'),'utf8'))
const timeline={version:path.basename(root),duration_seconds:plan.video.durationSeconds,fps:Number(plan.video.fps),frame_count:plan.video.totalFrames}
const bytes=await fs.readFile(path.join(root,'final/product-demo.mp4'))
const digest=createHash('sha256').update(bytes).digest('hex')
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--no-proxy-server']})
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},colorScheme:'light'})
  const errors=[];page.on('pageerror',error=>errors.push(error.message))
  await page.goto(`http://127.0.0.1:5191/product-video/${timeline.version}/final/index.html`,{waitUntil:'networkidle'})
  await page.waitForFunction(()=>document.getElementById('movie').dataset.ready==='true',null,{timeout:30000})
  const servedHash=await page.evaluate(async()=>{
    const buffer=await (await fetch(document.getElementById('movie').currentSrc)).arrayBuffer()
    return [...new Uint8Array(await crypto.subtle.digest('SHA-256',buffer))].map(byte=>byte.toString(16).padStart(2,'0')).join('')
  })
  if(servedHash!==digest)throw Error('The player loaded a different movie')
  await page.evaluate(({duration,fps})=>{
    const video=document.getElementById('movie')
    const button=document.createElement('button');button.id='verify-play';button.textContent='播放成片检查';document.body.prepend(button)
    window.playbackResult=new Promise((resolve,reject)=>{
      button.onclick=async()=>{
        let audioContext,timer,frameHandle
        try{
          audioContext=new AudioContext()
          const analyser=audioContext.createAnalyser();analyser.fftSize=2048
          const source=audioContext.createMediaElementSource(video);source.connect(analyser);analyser.connect(audioContext.destination)
          await audioContext.resume()
          video.muted=false;video.volume=1;video.playbackRate=1
          const samples=new Float32Array(analyser.fftSize),stamps=[]
          let active=0,maxRms=0
          const before=video.getVideoPlaybackQuality(),start=performance.now()
          const preloadedFirstFrame=video.readyState>=2&&video.currentTime===0
          const bufferedAtStart=video.buffered.length>0&&video.buffered.start(0)<.001&&video.buffered.end(video.buffered.length-1)>=duration-.001
          function record(_now,meta){
            analyser.getFloatTimeDomainData(samples)
            let energy=0;for(const sample of samples)energy+=sample*sample
            const rms=Math.sqrt(energy/samples.length);maxRms=Math.max(maxRms,rms);if(rms>.001)active++
            stamps.push({mediaTime:meta.mediaTime,presentedFrames:meta.presentedFrames})
            frameHandle=video.requestVideoFrameCallback(record)
          }
          frameHandle=video.requestVideoFrameCallback(record)
          timer=setTimeout(()=>reject(Error('Playback timeout')),(duration+10)*1000)
          video.addEventListener('error',()=>reject(Error('Media element error')),{once:true})
          video.addEventListener('ended',()=>{
            clearTimeout(timer);video.cancelVideoFrameCallback(frameHandle)
            const quality=video.getVideoPlaybackQuality()
            const gaps=stamps.slice(1).filter((stamp,index)=>stamp.mediaTime-stamps[index].mediaTime>1/fps+.002||stamp.presentedFrames-stamps[index].presentedFrames>1)
            // Browser cumulative counters can include repeat decoding during preload.
            // Prove every media-frame timestamp instead of equating that counter to file frames.
            const mediaFrames=[...new Set([...(preloadedFirstFrame?[0]:[]),...stamps.map(stamp=>Math.round(stamp.mediaTime*fps))])].sort((a,b)=>a-b)
            const presentationCoverage={complete:mediaFrames.length===duration*fps&&mediaFrames.every((frame,index)=>frame===index),uniqueFrames:mediaFrames.length,firstFrame:mediaFrames[0],lastFrame:mediaFrames.at(-1),preloadedFirstFrame}
            const result={transport:video.currentSrc.startsWith('blob:')?'local Blob':'local HTTP',bufferedAtStart,fallbackReason:video.dataset.fallbackReason??null,duration:video.duration,ended:video.ended,playbackRate:video.playbackRate,wallTimeMs:performance.now()-start,muted:video.muted,volume:video.volume,audioContextState:audioContext.state,audioDecodedBytes:video.webkitAudioDecodedByteCount,audioMeter:{measuredFrames:stamps.length,activeFrames:active,maxRms},cumulativeVideoFramesBefore:before.totalVideoFrames,totalVideoFrames:quality.totalVideoFrames,presentationCoverage,droppedDuringPlayback:quality.droppedVideoFrames-before.droppedVideoFrames,presentedCallbacks:stamps.length,frameCallbackGaps:gaps.length,firstCallback:stamps[0],lastCallback:stamps.at(-1),scope:'Full-speed program playback with audio enabled, signal metering and decoded-frame visual inspection; subjective listening is not claimed.'}
            audioContext.close();resolve(result)
          },{once:true})
          await video.play()
        }catch(error){clearTimeout(timer);audioContext?.close();reject(error)}
      }
    })
  },{duration:timeline.duration_seconds,fps:timeline.fps})
  await page.locator('#verify-play').click()
  const result={movieSha256:digest,servedSha256:servedHash,...await page.evaluate(()=>window.playbackResult),pageErrors:errors}
  await fs.writeFile(path.join(root,'cache/final/playback-audit.json'),JSON.stringify(result,null,2)+'\n','utf8')
  console.log(JSON.stringify(result,null,2))
  if(!result.ended||result.duration!==timeline.duration_seconds||!result.presentationCoverage.complete||result.presentationCoverage.uniqueFrames!==timeline.frame_count||result.muted||result.volume!==1||result.audioMeter.activeFrames<timeline.frame_count*.8||result.droppedDuringPlayback||result.frameCallbackGaps||errors.length)throw Error('Playback verification failed; inspect cache/final/playback-audit.json')
}finally{await browser.close()}
