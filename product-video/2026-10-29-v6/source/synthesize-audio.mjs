// Original deterministic score, generated from oscillators and seeded noise.
// No samples, external music, speech, models or third-party audio packages.
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const plan = JSON.parse(await fs.readFile(path.join(root, 'plan.json'), 'utf8'))
const approval = JSON.parse(await fs.readFile(path.join(root, 'approval.json'), 'utf8'))
if (approval.status !== 'approved' || approval.planSha256 !== plan.planSha256) throw new Error('Current preview approval is required.')
const timeline = {duration_seconds:plan.video.durationSeconds,fps:Number(plan.video.fps),frame_count:plan.video.totalFrames,bpm:plan.audio.bpm,beat_frames:Number(plan.video.fps)*60/plan.audio.bpm,events:plan.events.map(e=>({...e,kind:e.id==='closing'?'brand':e.kind,target:e.target??e.action}))}
const rate = plan.audio.sampleRate, duration = timeline.duration_seconds, count = plan.audio.sampleCount
const beat = 60 / timeline.bpm, beatCount = duration / beat
if (!Number.isInteger(beatCount) || timeline.frame_count !== duration * timeline.fps) throw new Error('Inconsistent timeline')
const musicL = new Float64Array(count), musicR = new Float64Array(count)
const fxL = new Float64Array(count), fxR = new Float64Array(count)
const tau = 2 * Math.PI, hz = note => 440 * 2 ** ((note - 69) / 12)
const soft = x => { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x) }
let seed = 0x41544c41
function noise() { seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5; return (seed >>> 0) / 2147483648 - 1 }
function mix(start, length, voice, gain, pan = 0, bus = 'music') {
  const offset = Math.round(start * rate), total = Math.min(Math.round(length * rate), count - offset)
  const left = bus === 'music' ? musicL : fxL, right = bus === 'music' ? musicR : fxR
  const l = Math.cos((pan + 1) * Math.PI / 4), r = Math.sin((pan + 1) * Math.PI / 4)
  for (let i = 0; i < total; i++) {
    const t = i / rate, amplitude = voice(t, i, total) * gain
    left[offset + i] += amplitude * l; right[offset + i] += amplitude * r
  }
}
function bell(note, length = .9) {
  const f = hz(note)
  return t => {
    const attack = soft(t / .004), release = soft((length - t) / .10)
    const fundamental = Math.sin(tau * f * t + .30 * Math.sin(tau * f * 2 * t) * Math.exp(-t * 10))
    return attack * release * (fundamental * Math.exp(-t * 5.8) + .10 * Math.sin(tau * f * 3 * t) * Math.exp(-t * 13))
  }
}

// Extend the original warm motif over the approved beat grid; resolve at closing.
const chordMotif = [
  [62,66,69,73,76], [61,64,69,71,76], [59,62,66,69,74],
  [59,62,66,69,74], [59,62,64,67,71], [61,64,69,71,76],
  [59,62,66,69,74], [59,62,66,69,74], [62,66,69,73,76],
]
const bassMotif = [38,33,35,31,40,33,35,31,38]
const melodyMotif = [74,78,81,78, 76,73,69,73, 71,74,78,76, 67,71,74,78, 76,74,71,69, 73,76,81,76, 74,78,81,78, 71,74,78,81]
const closingBeat=plan.events.find(e=>e.id==='closing').beatIndex
const explanationBeat=plan.events.find(e=>e.id==='chapter-enter').beatIndex
const bars=Math.ceil(beatCount/4)
const chords=Array.from({length:bars},(_,bar)=>bar*4>=closingBeat-2?chordMotif[0]:chordMotif[bar%chordMotif.length])
const bass=Array.from({length:bars},(_,bar)=>bar*4>=closingBeat-2?38:bassMotif[bar%bassMotif.length])
const melody=Array.from({length:beatCount},(_,n)=>n>=closingBeat?[78,76,74,74][Math.min(3,n-closingBeat)]:melodyMotif[n%melodyMotif.length])
// The approved ending is six beats long; its last bar has only two beats.
if ((chords.length-1)*4 >= beatCount || chords.length*4 < beatCount || bass.length !== chords.length || melody.length !== beatCount) throw new Error('Score must cover every approved beat')
for (let bar = 0; bar < chords.length; bar++) {
  const start = bar * beat * 4, length = Math.min(2.45, duration - start)
  chords[bar].forEach((note, index) => {
    const frequency = hz(note)
    mix(start, length, t => {
      const env = soft(t / .19) * soft((length - t) / .48)
      const gentle = .83 * Math.sin(tau * frequency * t) + .12 * Math.sin(tau * frequency * 2 * t) + .05 * Math.sin(tau * frequency * 3 * t)
      return gentle * env * (.93 + .07 * Math.sin(tau * .38 * t))
    }, .027, (index - 2) * .22)
  })
  mix(start, 1.80, t => (Math.sin(tau * hz(bass[bar]) * t) + .16 * Math.sin(tau * hz(bass[bar]) * 2 * t)) * soft(t / .012) * Math.exp(-t * 1.65) * soft((1.80 - t) / .25), .10)
}
for (let n = 0; n < beatCount; n++) {
  const start = n * beat
  const focusGain=n >= explanationBeat ? .78 : 1
  mix(start, .90, bell(melody[n]), (n % 4 === 0 ? .105 : .072)*focusGain, n % 2 ? .25 : -.25)
  // Soft kick on the half-bar; light brushed ticks mark the pulse.
  if (n % 2 === 0) mix(start, .22, t => Math.sin(tau * (48 * t + 1.35 * (1 - Math.exp(-t * 35)))) * soft(t / .002) * Math.exp(-t * 25) * soft((.22 - t) / .04), .095)
  let previous = 0
  mix(start + beat / 2, .055, t => { const next = noise(); const high = next - previous; previous = next; return high * Math.exp(-t * 85) * soft(t / .001) * soft((.055 - t) / .015) }, .008, n % 2 ? -.42 : .42)
  if (n % 4 === 1 || n % 4 === 3) mix(start, .13, t => noise() * soft(t / .002) * Math.exp(-t * 37) * soft((.13 - t) / .025), .011)
}

const cues = []
for (const event of timeline.events) {
  if (event.kind === 'show') continue
  if (event.frame % timeline.beat_frames !== 0) throw new Error('Off-beat action')
  const time = event.frame / timeline.fps
  cues.push({ frame: event.frame, seconds: time, sample: Math.round(time * rate), kind: event.kind, target: event.target })
  if (event.kind === 'click') {
    mix(time, .085, t => (Math.sin(tau * 1420 * t) + .24 * Math.sin(tau * 2810 * t)) * soft(t / .0008) * Math.exp(-t * 82) * soft((.085 - t) / .014), .14, .08, 'fx')
    mix(time, .11, t => Math.sin(tau * 480 * t) * soft(t / .001) * Math.exp(-t * 58) * soft((.11 - t) / .03), .045, -.08, 'fx')
  } else if (event.kind === 'brand') {
    mix(time, 1.75, bell(74, 1.75), .115, -.18, 'fx')
    mix(time, 1.75, bell(81, 1.75), .055, .18, 'fx')
  } else {
    const note = event.target === '报告完成' ? 81 : event.target === '汇总笔记' ? 78 : 74
    mix(time, .24, t => Math.sin(tau * hz(note) * t) * soft(t / .003) * Math.exp(-t * 18) * soft((.24 - t) / .06), .055, 0, 'fx')
  }
}

// Small, fixed early reflections on the music bus only; interaction cues stay dry.
const dryL = musicL.slice(), dryR = musicR.slice()
for (const [seconds, gain] of [[.071,.10],[.119,.075],[.193,.04]]) {
  const delay = Math.round(seconds * rate)
  for (let i = delay; i < count; i++) { musicL[i] += dryR[i-delay] * gain; musicR[i] += dryL[i-delay] * gain }
}
const left = new Float64Array(count), right = new Float64Array(count)
let peak = 0, energy = 0
for (let i = 0; i < count; i++) {
  const t = i / rate, fade = soft(t / .025) * soft((duration - t) / .52)
  left[i] = (musicL[i] + fxL[i]) * fade; right[i] = (musicR[i] + fxR[i]) * fade
  if (!Number.isFinite(left[i]) || !Number.isFinite(right[i])) throw new Error('Non-finite score sample')
  peak = Math.max(peak, Math.abs(left[i]), Math.abs(right[i])); energy += left[i] ** 2 + right[i] ** 2
}
const rawRms = Math.sqrt(energy / (count * 2)), gain = Math.min(.67 / peak, .11 / rawRms)
const pcm = Buffer.alloc(count * 4)
let normalizedPeak = 0, normalizedEnergy = 0
for (let i = 0; i < count; i++) {
  const l = left[i] * gain, r = right[i] * gain
  normalizedPeak = Math.max(normalizedPeak, Math.abs(l), Math.abs(r)); normalizedEnergy += l*l+r*r
  pcm.writeInt16LE(Math.round(l * 32767), i * 4); pcm.writeInt16LE(Math.round(r * 32767), i * 4 + 2)
}
const header = Buffer.alloc(44)
header.write('RIFF', 0); header.writeUInt32LE(36 + pcm.length, 4); header.write('WAVEfmt ', 8)
header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(2, 22)
header.writeUInt32LE(rate, 24); header.writeUInt32LE(rate * 4, 28); header.writeUInt16LE(4, 32); header.writeUInt16LE(16, 34)
header.write('data', 36); header.writeUInt32LE(pcm.length, 40)
const cache = path.join(root, 'cache/final'); await fs.mkdir(cache, { recursive: true })
const wav = Buffer.concat([header, pcm]); await fs.writeFile(path.join(cache, 'music.wav'), wav)
const audit = {
  description: 'Original 120 BPM score: warm pads, sine/FM plucks, bass, restrained percussion and event-derived UI cues; no voices or external samples.',
  sampleRate: rate, channels: 2, samplesPerChannel: count, seconds: duration, bpm: timeline.bpm, beats: beatCount,
  peak: normalizedPeak, peakDbfs: 20 * Math.log10(normalizedPeak), rmsDbfs: 20 * Math.log10(Math.sqrt(normalizedEnergy/(count*2))),
  clippingSamples: 0, seed: '0x41544c41', fadeInSeconds: .025, fadeOutSeconds: .52, cues,
  sourceSha256: createHash('sha256').update(wav).digest('hex'), planSha256:plan.planSha256, timelineSha256: createHash('sha256').update(await fs.readFile(path.join(root,'timeline.json'))).digest('hex'),
}
await fs.writeFile(path.join(cache, 'audio-source.json'), JSON.stringify(audit, null, 2) + '\n', 'utf8')
console.log(JSON.stringify(audit, null, 2))
