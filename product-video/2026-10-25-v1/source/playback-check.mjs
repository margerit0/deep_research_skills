// Full-rate browser playback with the audio track enabled. This verifies playback
// mechanics and audible signal delivery, not subjective listening by a person.
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { createHash } from 'node:crypto'
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const repo=path.resolve(root,'../..')
const require=createRequire(path.join(repo,'frontend/package.json'))
const {chromium}=require('playwright')
const nativePlayback=process.argv.includes('--native')
const memoryPlayback=process.argv.includes('--memory')
let executablePath
for(const candidate of [process.env.CHROME_PATH,'C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].filter(Boolean)){
  try{await fs.access(candidate);executablePath=candidate;break}catch{}
}
const digest=createHash('sha256').update(await fs.readFile(path.join(root,'final/product-demo.mp4'))).digest('hex')
const browser=await chromium.launch(executablePath?{executablePath,headless:true}:{headless:true})
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},colorScheme:'light'})
  await page.goto('http://127.0.0.1:5187/product-video/2026-10-25-v1/final/index.html',{waitUntil:'networkidle'})
  await page.evaluate(async({nativePlayback,memoryPlayback})=>{
    const v=document.getElementById('movie')
    if(memoryPlayback){const response=await fetch(v.currentSrc||v.querySelector('source').src);v.src=URL.createObjectURL(await response.blob())}
    v.preload='auto';v.load()
    await new Promise(resolve=>v.readyState>=4?resolve():v.addEventListener('canplaythrough',resolve,{once:true}))
    const button=document.createElement('button');button.id='verification-play';button.textContent='播放成片检查';document.body.prepend(button)
    window.playbackResult=new Promise((resolve,reject)=>{
      button.onclick=async()=>{
        try{
          const ac=nativePlayback?null:new AudioContext(),analyser=ac?.createAnalyser()
          if(ac){const source=ac.createMediaElementSource(v);analyser.fftSize=2048;source.connect(analyser);analyser.connect(ac.destination);await ac.resume()}
          v.muted=false;v.volume=1;v.playbackRate=1
          const samples=new Float32Array(analyser?.fftSize??0),times=[]
          let measured=0,active=0,maxRms=0
          const before=v.getVideoPlaybackQuality()
          function next(_time,meta){
            times.push(meta.mediaTime);analyser?.getFloatTimeDomainData(samples)
            let energy=0;for(const value of samples)energy+=value*value
            const rms=samples.length?Math.sqrt(energy/samples.length):0;maxRms=Math.max(maxRms,rms);measured++;if(rms>.001)active++
            if(!v.ended)v.requestVideoFrameCallback(next)
          }
          v.requestVideoFrameCallback(next)
          const timer=setTimeout(()=>reject(new Error('Playback exceeded twenty seconds')),20000)
          v.addEventListener('error',()=>reject(new Error('Media element error')),{once:true})
          v.addEventListener('ended',()=>{
            clearTimeout(timer);const q=v.getVideoPlaybackQuality()
            const gaps=times.slice(1).flatMap((time,i)=>time-times[i]>.04?[{from:times[i],to:time}]:[])
            const result={transport:v.currentSrc.startsWith('blob:')?'fully buffered local Blob':'local HTTP',duration:v.duration,currentTime:v.currentTime,ended:v.ended,playbackRate:v.playbackRate,muted:v.muted,volume:v.volume,audioContextState:ac?.state??'native media playback',audioDecodedBytes:v.webkitAudioDecodedByteCount,audioMeter:{enabled:!!analyser,measuredFrames:measured,activeFrames:active,maxRms},totalVideoFrames:q.totalVideoFrames,droppedDuringPlayback:q.droppedVideoFrames-before.droppedVideoFrames,presentedCallbacks:times.length,firstMediaTime:times[0],lastMediaTime:times.at(-1),presentationGaps:gaps,scope:'Automated full-rate audiovisual playback and decoded-frame visual inspection; subjective listening is not claimed.'}
            ac?.close();resolve(result)
          },{once:true})
          await v.play()
        }catch(error){reject(error)}
      }
    })
  },{nativePlayback,memoryPlayback})
  await page.locator('#verification-play').click()
  const result=await page.evaluate(()=>window.playbackResult)
  if(!result.ended||result.duration!==12||result.muted||(!nativePlayback&&result.audioMeter.activeFrames<300))throw new Error('Incomplete audiovisual playback')
  await fs.writeFile(path.join(root,`cache/final/playback${nativePlayback?'-native':''}${memoryPlayback?'-memory':''}-audit.json`),JSON.stringify({movieSha256:digest,...result},null,2)+'\n','utf8')
  console.log(JSON.stringify(result,null,2))
}finally{await browser.close()}
