import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const cache = path.join(root,'cache/final')
const source = JSON.parse(await fs.readFile(path.join(cache,'audio-source.json'),'utf8'))
const wav = await fs.readFile(path.join(cache,'music.wav'))
const raw = await fs.readFile(path.join(cache,'decoded-audio.f32'))
const sampleCount = raw.length / 8, expected = source.samplesPerChannel
if (sampleCount < expected || sampleCount > expected + 1024) throw new Error(`Unexpected decoded AAC duration: ${sampleCount}`)
const reference = new Float64Array(expected), decoded = new Float64Array(sampleCount)
let peak = 0, energy = 0, clipped = 0, paddingPeak = 0
for (let i=0;i<sampleCount;i++) {
  const l=raw.readFloatLE(i*8),r=raw.readFloatLE(i*8+4)
  if (!Number.isFinite(l)||!Number.isFinite(r)) throw new Error('Non-finite audio sample')
  decoded[i]=(l+r)/2; peak=Math.max(peak,Math.abs(l),Math.abs(r)); energy+=l*l+r*r
  if (Math.abs(l)>=.9999) clipped++; if (Math.abs(r)>=.9999) clipped++
  if (i>=expected) paddingPeak=Math.max(paddingPeak,Math.abs(l),Math.abs(r))
  if (i<expected) reference[i]=(wav.readInt16LE(44+i*4)+wav.readInt16LE(44+i*4+2))/65536
}
if (clipped || peak>=.98) throw new Error('Decoded audio has insufficient headroom')
const offsets=[]
for (const cue of source.cues) {
  const start=cue.sample-240,length=7200
  let best={lag:0,correlation:-1}
  function correlation(lag) {
    let ab=0,aa=0,bb=0
    for(let i=0;i<length;i+=2) {
      const a=reference[start+i],b=decoded[start+i+lag]
      ab+=a*b;aa+=a*a;bb+=b*b
    }
    return ab/Math.sqrt(aa*bb)
  }
  for(let lag=-512;lag<=512;lag+=4) { const c=correlation(lag); if(c>best.correlation)best={lag,correlation:c} }
  const coarse=best.lag
  for(let lag=coarse-4;lag<=coarse+4;lag++) { const c=correlation(lag); if(c>best.correlation)best={lag,correlation:c} }
  if(Math.abs(best.lag)>96 || best.correlation<.94) throw new Error(`AAC event alignment failed at frame ${cue.frame}`)
  offsets.push({frame:cue.frame,seconds:cue.seconds,sampleLag:best.lag,lagMilliseconds:best.lag/source.sampleRate*1000,correlation:best.correlation})
}
function rmsSegment(begin,end) {
  let sum=0,n=0
  for(let i=begin;i<end;i++){sum+=decoded[i]**2;n++}
  return Math.sqrt(sum/n)
}
const audit={sampleRate:source.sampleRate,decodedSamplesPerChannel:sampleCount,decodedSeconds:sampleCount/source.sampleRate,playableSamplesPerChannel:expected,playableSeconds:expected/source.sampleRate,aacTrailingPaddingSamples:sampleCount-expected,paddingPeak,peak,peakDbfs:20*Math.log10(peak),rmsDbfs:20*Math.log10(Math.sqrt(energy/(sampleCount*2))),clippedSamples:clipped,startRms:rmsSegment(0,480),endRms:rmsSegment(expected-480,expected),eventAlignment:offsets,scope:'Numerical decoding, peak, clipping and timing validation; this does not claim subjective listening.'}
await fs.writeFile(path.join(cache,'audio-decoded-audit.json'),JSON.stringify(audit,null,2)+'\n','utf8')
console.log(JSON.stringify(audit,null,2))
