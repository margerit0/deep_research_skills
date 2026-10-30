// Original deterministic score, written for v7 and generated from oscillators and seeded noise.
// v8 keeps the same frame plan, so this renders the v7 score sample for sample (package-final.py checks it).
// No samples, external music, speech, models or third-party audio packages.
//
// Form follows the film: a quiet opening motif, a light groove while research runs in
// parallel, a breath on the "Agent 自动进化" chapter card, a sparse reading bed under the
// mechanism diagrams, a build through validation, the motif's return on release and a
// final cadence that rings out under the brand. Every section boundary, chord change and
// cue is derived from plan.json, so the score follows the same frame plan as the picture.
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const plan = JSON.parse(await fs.readFile(path.join(root, 'plan.json'), 'utf8'))
const approval = JSON.parse(await fs.readFile(path.join(root, 'approval.json'), 'utf8'))
if (approval.status !== 'approved' || approval.planSha256 !== plan.planSha256) throw new Error('Current plan approval is required.')
const fps = Number(plan.video.fps), rate = plan.audio.sampleRate, count = plan.audio.sampleCount
const duration = plan.video.durationSeconds, beat = 60 / plan.audio.bpm, beatFrames = fps * beat
const beatCount = duration / beat
if (!Number.isInteger(beatCount) || !Number.isInteger(beatFrames) || plan.video.totalFrames !== duration * fps) throw new Error('Inconsistent timeline')
if (count !== duration * rate) throw new Error('Sample count does not match the frame plan')

const LOUDNESS_TARGET = -16, CEILING_DBFS = -2
const tau = 2 * Math.PI, hz = note => 440 * 2 ** ((note - 69) / 12)
const soft = x => { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x) }
let seed = 0x41544c41
function noise() { seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5; return (seed >>> 0) / 2147483648 - 1 }

// ---------------------------------------------------------------- structure from the plan
const shotBeat = id => {
  const value = plan.shots.find(shot => shot.id === id).startFrame / beatFrames
  if (!Number.isInteger(value)) throw new Error(`${id} does not start on a beat`)
  return value
}
const S = {
  question: shotBeat('question'), skills: shotBeat('skills'), parallel: shotBeat('parallel'), inspect: shotBeat('inspect'),
  report: shotBeat('report'), chapter: shotBeat('chapter-card'), method: shotBeat('method'), feedback: shotBeat('feedback'),
  diagnose: shotBeat('diagnose'), candidate: shotBeat('candidate'), validate: shotBeat('validate'), release: shotBeat('release'),
  brand: shotBeat('brand'), end: beatCount,
}
// Downbeats land on every structural cut; a short bar absorbs odd spans before the next cut.
const anchors = [S.question, S.skills, S.parallel, S.chapter, S.method, S.diagnose, S.validate, S.release, S.brand, S.end]
const bars = []
for (let i = 0; i + 1 < anchors.length; i++) for (let b = anchors[i]; b < anchors[i + 1]; b += 4) bars.push({ start: b, length: Math.min(4, anchors[i + 1] - b) })
const sections = [
  ['intro', S.question], ['skills', S.skills], ['groove', S.parallel], ['chapter', S.chapter], ['explain', S.method],
  ['analyse', S.diagnose], ['validate', S.validate], ['release', S.release], ['brand', S.brand],
]
const sectionAt = b => sections.filter(([, start]) => start <= b).at(-1)[0]

// D major throughout; part two leans on the relative minor while the diagrams are read.
const chords = {
  'Dadd9': { pad: [62, 66, 69, 76], bass: 38 }, 'Gmaj7': { pad: [59, 62, 66, 71], bass: 43 },
  'Bm7': { pad: [62, 66, 69, 71], bass: 47 }, 'Aadd9': { pad: [61, 64, 69, 71], bass: 45 },
  'D': { pad: [62, 66, 69, 74], bass: 38 }, 'F#m7': { pad: [61, 64, 69, 73], bass: 42 },
  'D/F#': { pad: [62, 66, 69, 74], bass: 42 }, 'Em7': { pad: [62, 67, 71, 74], bass: 40 },
  'A7sus4': { pad: [62, 67, 69, 76], bass: 45 }, 'Gmaj13#11': { pad: [59, 61, 66, 69, 76], bass: 43 },
  'Bm9': { pad: [62, 66, 69, 73], bass: 47 }, 'Em9': { pad: [55, 59, 62, 66], bass: 40 },
  'Asus4': { pad: [62, 64, 69, 74], bass: 45 }, 'A': { pad: [61, 64, 69, 73], bass: 45 },
  'A/C#': { pad: [61, 64, 69, 76], bass: 49 },
}
const harmony = [
  [S.question, 'Dadd9'], [S.question + 4, 'Gmaj7'], [S.skills, 'Bm7'], [S.skills + 4, 'Aadd9'],
  [S.parallel, 'D'], [S.parallel + 4, 'F#m7'], [S.parallel + 8, 'Gmaj7'], [S.report, 'D/F#'], [S.report + 2, 'Em7'], [S.report + 4, 'A7sus4'],
  [S.chapter, 'Gmaj13#11'], [S.chapter + 4, 'A7sus4'],
  [S.method, 'Bm7'], [S.method + 4, 'Gmaj7'], [S.feedback, 'D/F#'], [S.feedback + 4, 'Em7'], [S.feedback + 6, 'A7sus4'],
  [S.diagnose, 'Bm9'], [S.diagnose + 4, 'F#m7'], [S.diagnose + 8, 'Gmaj7'], [S.candidate + 2, 'Em9'], [S.candidate + 6, 'Asus4'], [S.candidate + 8, 'A'],
  [S.validate, 'Em7'], [S.validate + 4, 'F#m7'], [S.validate + 8, 'Gmaj7'], [S.validate + 12, 'A7sus4'],
  [S.release, 'Dadd9'], [S.release + 4, 'A/C#'], [S.release + 8, 'Gmaj7'], [S.release + 10, 'A'], [S.brand, 'Dadd9'],
]
if (harmony.some(([b], i) => i && b <= harmony[i - 1][0]) || harmony[0][0] !== 0 || harmony.at(-1)[0] >= beatCount) throw new Error('Harmony must ascend inside the film')
const chordAt = b => chords[harmony.filter(([start]) => start <= b).at(-1)[1]]
const DIATONIC = new Set([2, 4, 6, 7, 9, 11, 1])

// ---------------------------------------------------------------- mixing buses
const music = { L: new Float64Array(count), R: new Float64Array(count) }
const bed = { L: new Float64Array(count), R: new Float64Array(count) }
const kicks = { L: new Float64Array(count), R: new Float64Array(count) }
const cues = { L: new Float64Array(count), R: new Float64Array(count) }
const wet = { L: new Float64Array(count), R: new Float64Array(count) }
const notes = []
// Gentle level automation shapes the arc: open softly, lift for the groove, breathe for
// the chapter card, stay out of the way while diagrams are read, build into the release.
const levels = { intro: .82, skills: .9, groove: 1, chapter: .88, explain: .86, analyse: .9, validate: .93, release: .94, brand: 1 }
const automation = new Float64Array(count)
for (let i = 0; i < count; i++) {
  const b = i / rate / beat, current = sectionAt(b), index = sections.findIndex(([name]) => name === current)
  const previous = index ? levels[sections[index - 1][0]] : levels[current]
  automation[i] = previous + (levels[current] - previous) * soft((b - sections[index][1]) / 1.5)
}
function add(bus, startSeconds, lengthSeconds, voice, gain = 1, pan = 0, send = 0) {
  const offset = Math.round(startSeconds * rate), total = Math.min(Math.round(lengthSeconds * rate), count - offset)
  if (offset < 0 || total <= 0) return
  const l = Math.cos((pan + 1) * Math.PI / 4), r = Math.sin((pan + 1) * Math.PI / 4), automated = bus !== cues
  for (let i = 0; i < total; i++) {
    const value = voice(i / rate) * gain * (automated ? automation[offset + i] : 1)
    bus.L[offset + i] += value * l; bus.R[offset + i] += value * r
    if (send) { wet.L[offset + i] += value * l * send; wet.R[offset + i] += value * r * send }
  }
}
const at = b => b * beat
function note(part, b, midi, length, velocity) {
  if (!DIATONIC.has(((midi % 12) + 12) % 12)) throw new Error(`${part} note ${midi} leaves D major`)
  notes.push({ part, beat: b, midi, beats: length, velocity: Number(velocity.toFixed(3)), chord: harmony.filter(([start]) => start <= b).at(-1)[1] })
}

// ---------------------------------------------------------------- filters and voices
function biquad(type, frequency, q = .707) {
  let b0, b1, b2, a1, a2, x1 = 0, x2 = 0, y1 = 0, y2 = 0
  const tune = f => {
    const w = tau * Math.min(f, rate * .45) / rate, cos = Math.cos(w), alpha = Math.sin(w) / (2 * q), a0 = 1 + alpha
    if (type === 'lowpass') { b0 = (1 - cos) / 2; b1 = 1 - cos; b2 = b0 } else if (type === 'highpass') { b0 = (1 + cos) / 2; b1 = -(1 + cos); b2 = b0 } else { b0 = alpha; b1 = 0; b2 = -alpha }
    b0 /= a0; b1 /= a0; b2 /= a0; a1 = -2 * cos / a0; a2 = (1 - alpha) / a0
  }
  tune(frequency)
  const run = x => { const y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2; x2 = x1; x1 = x; y2 = y1; y1 = y; return y }
  run.tune = tune
  return run
}
function shelf(type, frequency, db, q = .707) {
  const A = 10 ** (db / 40), w = tau * frequency / rate, cos = Math.cos(w), alpha = Math.sin(w) / (2 * q), root = 2 * Math.sqrt(A) * alpha
  const c = type === 'low'
    ? [A * ((A + 1) - (A - 1) * cos + root), 2 * A * ((A - 1) - (A + 1) * cos), A * ((A + 1) - (A - 1) * cos - root), (A + 1) + (A - 1) * cos + root, -2 * ((A - 1) + (A + 1) * cos), (A + 1) + (A - 1) * cos - root]
    : type === 'high'
      ? [A * ((A + 1) + (A - 1) * cos + root), -2 * A * ((A - 1) + (A + 1) * cos), A * ((A + 1) + (A - 1) * cos - root), (A + 1) - (A - 1) * cos + root, 2 * ((A - 1) - (A + 1) * cos), (A + 1) - (A - 1) * cos - root]
      : [1 + alpha * A, -2 * cos, 1 - alpha * A, 1 + alpha / A, -2 * cos, 1 - alpha / A]
  const [b0, b1, b2, a1, a2] = [c[0] / c[3], c[1] / c[3], c[2] / c[3], c[4] / c[3], c[5] / c[3]]
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0
  return x => { const y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2; x2 = x1; x1 = x; y2 = y1; y1 = y; return y }
}
function padVoice(midi, length, brightness) {
  const f = hz(midi), partials = Math.max(2, Math.round(2 + brightness * 8))
  const amplitude = Array.from({ length: partials }, (_, k) => (k + 1) ** -1.25 * Math.exp(-k * (1.15 - brightness)))
  const norm = 1 / amplitude.reduce((sum, value) => sum + value, 0), phase = midi * .37
  return t => {
    const envelope = soft(t / .42) * soft((length - t) / .85)
    let value = 0
    // A strong centre with two weaker, unequal detunes: a slow chorus that never beats down to a null.
    for (let k = 0; k < partials; k++) {
      const w = tau * f * (k + 1) * t
      value += amplitude[k] * (Math.sin(w + phase * k) + .3 * Math.sin(w * 1.0011 + phase * (k + 1.3)) + .26 * Math.sin(w * .9984 + phase * (k + 2.1)))
    }
    return value * norm * envelope * (.95 + .05 * Math.sin(tau * .21 * t + phase))
  }
}
function bassVoice(midi, length, ring = 0) {
  const f = hz(midi)
  // Second and third harmonics keep the line audible on laptop and phone speakers.
  return t => {
    const envelope = soft(t / .01) * (.58 + .42 * Math.exp(-t * 3)) * Math.exp(-t * ring) * soft((length - t) / .09)
    const value = Math.sin(tau * f * t) + .45 * Math.sin(tau * 2 * f * t) + .2 * Math.sin(tau * 3 * f * t) + .07 * Math.sin(tau * 4 * f * t)
    return Math.tanh(1.25 * value) * envelope
  }
}
function pluck(midi, length = .7, brightness = 1) {
  const f = hz(midi)
  return t => soft(t / .002) * Math.exp(-t * 6.5) * soft((length - t) / .08) *
    (Math.sin(tau * f * t + .85 * brightness * Math.exp(-t * 18) * Math.sin(tau * 2 * f * t)) + .28 * Math.exp(-t * 11) * Math.sin(tau * 2 * f * t))
}
function bell(midi, length = 1.6, brightness = 1) {
  const f = hz(midi)
  return t => soft(t / .003) * Math.exp(-t * 2.3) * soft((length - t) / .25) *
    (Math.sin(tau * f * t + 1.5 * brightness * Math.exp(-t * 5.5) * Math.sin(tau * 3.5 * f * t)) + .18 * Math.exp(-t * 3.5) * Math.sin(tau * 2 * f * t))
}
function kick() {
  return t => {
    const phase = tau * (52 * t + 95 / 38 * (1 - Math.exp(-t * 38)))
    const body = (Math.sin(phase) + .22 * Math.sin(2 * phase) * Math.exp(-t * 16)) * Math.exp(-t * 8.5) * soft(t / .0015)
    return (body + .2 * Math.exp(-t * 320) * Math.sin(tau * 1700 * t)) * soft((.34 - t) / .05)
  }
}
function clap() {
  const band = biquad('bandpass', 1350, .8), air = biquad('highpass', 2600)
  return t => {
    const n = noise(), bursts = [0, .011, .023].reduce((sum, start) => sum + (t >= start ? Math.exp(-(t - start) * 190) : 0), 0)
    return (band(n) * (bursts * .9 + .5 * Math.exp(-t * 20)) + .18 * air(n) * Math.exp(-t * 30)) * soft((.24 - t) / .05)
  }
}
function hat(open = false) {
  const high = biquad('highpass', 7200, .9), decay = open ? 13 : 55
  return t => high(noise()) * Math.exp(-t * decay) * soft(t / .0008) * soft(((open ? .3 : .08) - t) / .02)
}
function shaker() {
  const band = biquad('bandpass', 6200, .7)
  return t => band(noise()) * soft(t / .012) * Math.exp(-t * 38) * soft((.09 - t) / .02)
}
function crash(length = 2.4) {
  const high = biquad('highpass', 4300, .7), band = biquad('bandpass', 9000, .6)
  return t => (high(noise()) * .7 + band(noise()) * .5) * soft(t / .004) * Math.exp(-t * 1.7) * soft((length - t) / .4)
}
function riser(length, from = 320, to = 5600) {
  const band = biquad('bandpass', from, 1.4)
  let i = 0
  return t => {
    if (i++ % 32 === 0) band.tune(from * (to / from) ** (t / length))
    const rise = (t / length) ** 2
    return (band(noise()) * .9 + .12 * Math.sin(tau * (220 * t + 110 * t * t / length))) * rise * soft((length - t) / .03)
  }
}
function swell(length) {
  const low = biquad('lowpass', 500, .7)
  let i = 0
  return t => {
    if (i++ % 32 === 0) low.tune(500 + 7000 * (t / length) ** 2)
    return low(noise()) * Math.exp((t - length) * 5.5) * soft((length - t) / .015)
  }
}
function boom() {
  return t => {
    const phase = tau * (44 * t + 26 / 3 * (1 - Math.exp(-t * 3)))
    return (Math.sin(phase) + .35 * Math.sin(2 * phase)) * soft(t / .02) * Math.exp(-t * 2.6)
  }
}
function shimmer(midis, length) {
  return t => {
    let value = 0
    midis.forEach((midi, index) => { value += Math.sin(tau * hz(midi + 24) * t + index) * (.55 + .45 * Math.sin(tau * (.6 + .17 * index) * t + index)) })
    return value / midis.length * soft(t / 1.1) * soft((length - t) / .9)
  }
}
function click() {
  return t => ((Math.sin(tau * 1420 * t) + .24 * Math.sin(tau * 2810 * t)) * Math.exp(-t * 82) + .32 * Math.sin(tau * 480 * t) * Math.exp(-t * 58)) * soft(t / .0008) * soft((.11 - t) / .02)
}

// ---------------------------------------------------------------- harmony: pads, bass, shimmer
const brightness = { intro: .5, skills: .56, groove: .68, chapter: .82, explain: .46, analyse: .52, validate: .64, release: .84, brand: .8 }
harmony.forEach(([start, name], index) => {
  const end = index + 1 < harmony.length ? harmony[index + 1][0] : beatCount, chord = chords[name], part = sectionAt(start)
  const length = at(end - start) + (end < beatCount ? .7 : 0)
  chord.pad.forEach((midi, voice) => {
    add(bed, at(start), Math.min(length, duration - at(start)), padVoice(midi, Math.min(length, duration - at(start)), brightness[part]), .036, (voice - (chord.pad.length - 1) / 2) * .26, .3)
    note('pad', start, midi, end - start, .5)
  })
  if (part === 'chapter' || part === 'brand') add(bed, at(start), at(end - start) + .4, shimmer(chord.pad, at(end - start) + .4), .018, 0, .55)
})
const bassPatterns = {
  hold: length => [[0, length, .85]],
  half: length => length > 2 ? [[0, 2, .9], [2, length - 2, .72]] : [[0, length, .9]],
  groove: length => [[0, 1.5, 1], [1.5, .5, .55], [2, 1, .85], [3, .5, .5], [3.5, .5, .68]].filter(([offset]) => offset < length),
  drive: length => Array.from({ length: length * 2 }, (_, i) => [i / 2, .5, i % 2 ? .58 : (i % 4 ? .78 : 1)]),
}
const bassStyle = { intro: 'hold', skills: 'half', groove: 'groove', chapter: 'hold', explain: 'hold', analyse: 'half', validate: 'half', release: 'groove', brand: 'hold' }
for (const bar of bars) {
  const part = sectionAt(bar.start)
  if (part === 'brand' && bar.start > S.brand) continue
  let style = bassStyle[part]
  if (part === 'validate' && bar.start >= S.validate + 4) style = 'drive'
  const gain = { intro: .085, skills: .1, groove: .125, chapter: .085, explain: .09, analyse: .1, validate: .115, release: .125, brand: .1 }[part]
  for (const [offset, length, velocity] of bassPatterns[style](bar.length)) {
    const b = bar.start + offset, midi = chordAt(b).bass
    const tail = part === 'brand' ? duration - at(b) : at(length) * .96
    add(bed, at(b), tail, bassVoice(midi, tail, part === 'brand' ? .8 : 0), gain * velocity, 0, 0)
    note('bass', b, midi, length, velocity)
  }
}

// ---------------------------------------------------------------- melody: stated, answered, recalled
const phrases = [
  // Opening motif over the full workspace.
  [S.question, .078, [[1, 69, .5], [1.5, 74, .5], [2, 78, 1], [3, 76, 1], [4, 74, 1], [5, 71, .5], [5.5, 74, .5], [6, 69, 2]]],
  // Answer phrase while a method is chosen; it leaves the two native clicks in the clear.
  [S.skills, .068, [[.5, 74, .5], [1, 78, 1], [2, 76, .5], [2.5, 74, 1.5], [4.5, 73, .5], [5, 76, .5], [5.5, 81, 1], [6.5, 76, 1.5]]],
  // The motif returns, brighter, when a validated method is put to use.
  [S.release, .08, [[0, 78, 1], [1, 76, .5], [1.5, 78, .5], [2, 81, 1.5], [3.5, 78, .5], [4, 76, 1], [5, 73, .5], [5.5, 76, .5], [6, 81, 2], [8, 83, 1], [9, 81, .5], [9.5, 79, .5], [10, 81, 1], [11, 85, 1]]],
]
for (const [start, gain, line] of phrases) line.forEach(([offset, midi, length], index) => {
  const b = start + offset
  add(music, at(b), Math.min(at(length) + 1.2, duration - at(b)), bell(midi, Math.min(at(length) + 1.2, duration - at(b)), .9), gain * (offset % 2 === 0 ? 1 : .82), index % 2 ? .22 : -.22, .38)
  note('bell', b, midi, length, gain)
  if (start === S.release) add(music, at(b), Math.min(at(length) + .6, duration - at(b)), pluck(midi + 12, Math.min(at(length) + .6, duration - at(b)), .5), gain * .22, index % 2 ? -.3 : .3, .4)
})

// ---------------------------------------------------------------- arpeggio: research activity
const arpWindows = [
  // Three directions at once: the figure walks left, centre and right while research runs.
  { from: S.parallel + 2, to: S.report, octave: 12, gain: .05, pans: [-.62, 0, .62] },
  { from: S.diagnose, to: S.validate, octave: 0, gain: .032, pans: [-.25, .25] },
  { from: S.validate, to: S.release, octave: 12, gain: .04, pans: [-.45, .45], build: true },
  { from: S.release, to: S.brand, octave: 12, gain: .036, pans: [-.62, 0, .62] },
]
const figure = [0, 2, 1, 3, 2, 1, 3, 2]
for (const window of arpWindows) for (let step = window.from * 2; step < window.to * 2; step++) {
  const b = step / 2, tones = [...chordAt(b).pad].sort((x, y) => x - y).slice(0, 4).map(midi => midi + window.octave)
  const midi = tones[figure[step % figure.length] % tones.length]
  const build = window.build ? .55 + .45 * (b - window.from) / (window.to - window.from) : 1
  const velocity = (step % 2 ? .72 : 1) * build
  add(music, at(b), .62, pluck(midi, .62, .8), window.gain * velocity, window.pans[step % window.pans.length], .32)
  note('arp', b, midi, .5, velocity)
  // In the last bar before release the figure doubles to sixteenths.
  if (window.build && b >= S.release - 2) {
    add(music, at(b + .25), .4, pluck(tones[(figure[(step + 3) % 8]) % tones.length], .4, .8), window.gain * velocity * .8, -window.pans[step % window.pans.length], .32)
    note('arp', b + .25, tones[(figure[(step + 3) % 8]) % tones.length], .25, velocity * .8)
  }
}

// ---------------------------------------------------------------- percussion by section
const kickTimes = []
function hit(kind, b, velocity) {
  if (b >= beatCount) return
  const voices = { kick: [kick(), .31, 0, .35, 0], clap: [clap(), .17, .06, .24, .16], hat: [hat(), .055, .28, .09, .04], open: [hat(true), .045, .28, .3, .06], shaker: [shaker(), .055, -.3, .09, .03] }
  const [voice, gain, pan, length, send] = voices[kind]
  if (kind === 'kick') kickTimes.push({ seconds: at(b), velocity })
  add(kind === 'kick' ? kicks : music, at(b), length, voice, gain * velocity, pan, send)
}
for (const bar of bars) {
  const part = sectionAt(bar.start), b0 = bar.start, beats = bar.length
  const eighths = (velocity, kind = 'shaker', offbeatOnly = false) => {
    for (let e = 0; e < beats * 2; e++) if (!offbeatOnly || e % 2) hit(kind, b0 + e / 2, velocity * (e % 2 ? 1 : .7))
  }
  if (part === 'intro' && b0 >= S.question + 4) eighths(.32)
  if (part === 'skills') { hit('kick', b0, .5); eighths(.42) }
  if (part === 'groove') {
    // The last two beats before the chapter card thin out to make room for the swell.
    const lastBar = b0 + beats >= S.chapter
    hit('kick', b0, 1); hit('kick', b0 + 2, lastBar ? .7 : .9)
    if (!lastBar) { hit('kick', b0 + 3.5, .38); hit('clap', b0 + 3, .7) }
    hit('clap', b0 + 1, .7)
    for (let e = 0; e < beats * 2; e++) if (!(lastBar && e >= 4)) hit(e % 2 ? 'hat' : 'shaker', b0 + e / 2, e % 2 ? .8 : .45)
    if (b0 === S.parallel) add(music, at(b0), 2.4, crash(2.4), .03, .2, .3)
  }
  if (part === 'explain') { hit('kick', b0, .5); eighths(.5) }
  if (part === 'analyse') { hit('kick', b0, .55); if (beats > 2) hit('kick', b0 + 2, .36); eighths(.45) }
  if (part === 'validate') {
    const step = (b0 - S.validate) / 4
    hit('kick', b0, .72); if (beats > 2) hit('kick', b0 + 2, .66)
    eighths(.34)
    if (step >= 1) eighths(.5, 'hat', true)
    if (step >= 2 && beats > 2) { hit('clap', b0 + 1, .5); hit('clap', b0 + 3, .55) }
    if (beats === 2) for (let s = 0; s < 8; s++) hit('hat', b0 + s / 4, .35 + .5 * s / 7)
  }
  if (part === 'release') {
    hit('kick', b0, 1); hit('kick', b0 + 2, .9); hit('kick', b0 + 3.5, .4)
    hit('clap', b0 + 1, .75); hit('clap', b0 + 3, .8)
    for (let e = 0; e < 8; e++) hit(e % 2 ? 'hat' : 'shaker', b0 + e / 2, e % 2 ? .85 : .5)
    if (b0 + 4 === S.brand) hit('open', b0 + 3.5, .8)
  }
}
// Transitions: swell into the chapter card, rise into part two and into the release.
add(music, at(S.chapter - 1.5), at(1.5), swell(at(1.5)), .1, 0, .3)
add(music, at(S.method - 2), at(2), riser(at(2)), .075, 0, .3)
add(music, at(S.release - 2), at(2), riser(at(2), 400, 7200), .085, 0, .3)
add(music, at(S.release), 2.6, crash(2.6), .042, -.15, .35)
add(music, at(S.brand - 1), at(1), swell(at(1)), .06, 0, .3)

// ---------------------------------------------------------------- event cues
const cueList = []
const fanNotes = [81, 86, 90]
const automaticNotes = { brief: [81], search: [88], converge: [79, 83], writing: [86] }
const revealOrder = {}
for (const event of plan.events) {
  if (event.kind === 'show') continue
  if (event.frame % beatFrames !== 0) throw new Error(`Off-beat action ${event.id}`)
  const time = event.frame / fps, b = event.frame / beatFrames
  cueList.push({ frame: event.frame, seconds: time, sample: Math.round(time * rate), kind: event.kind, target: event.target ?? event.action, id: event.id })
  if (event.kind === 'click') {
    add(cues, time, .11, click(), .15, .08, .05)
  } else if (event.kind === 'camera') {
    add(cues, time, .5, swell(.5), .05, -.1, .25)
    add(cues, time, .45, pluck(74, .45, .5), .025, 0, .3)
  } else if (event.id === 'dispatch') {
    fanNotes.forEach((midi, i) => { add(cues, time + i * beat / 4, .7, pluck(midi, .7), .06, [-.62, 0, .62][i], .3); note('cue', b + i / 4, midi, .25, .06) })
  } else if (event.id === 'complete') {
    for (const midi of [86, 93]) { add(cues, time, 1.6, bell(midi, 1.6, 1.1), .06, midi === 86 ? -.15 : .15, .4); note('cue', b, midi, 2, .06) }
  } else if (automaticNotes[event.id]) {
    for (const midi of automaticNotes[event.id]) { add(cues, time, .7, pluck(midi, .7), .055, 0, .3); note('cue', b, midi, .5, .055) }
  } else if (event.id === 'chapter-enter') {
    add(cues, time, 3, boom(), .12, 0, .2)
    ;[81, 85, 90].forEach((midi, i) => { add(cues, time + i * .045, 2.4, bell(midi, 2.4, .7), .04, [-.3, 0, .3][i], .55); note('cue', b, midi, 4, .04) })
  } else if (event.id === 'chapter-exit') {
    add(cues, time, .5, swell(.5), .04, 0, .3)
  } else if (event.id === 'closing') {
    // Final cadence: a slow strum of the tonic that rings out under the brand.
    ;[74, 81, 86, 90].forEach((midi, i) => { add(cues, time + i * .03, duration - time - i * .03, bell(midi, duration - time - i * .03, .85), .07 - i * .008, [-.25, -.08, .08, .25][i], .5); note('cue', b, midi, beatCount - b, .07) })
    kickTimes.push({ seconds: time, velocity: 1 })
    add(kicks, time, .35, kick(), .3, 0, 0)
    add(music, time, duration - time, crash(duration - time), .03, .1, .4)
  } else {
    // Diagram reveals: soft plucks climb the current chord as each step of a shot appears.
    const order = revealOrder[event.shot] = (revealOrder[event.shot] ?? -1) + 1
    const tones = [...chordAt(b).pad].sort((x, y) => x - y).map(midi => midi + 12)
    const midi = tones[order % tones.length]
    const level = sectionAt(b) === 'release' ? .075 : .045
    add(cues, time, .8, pluck(midi, .8, .65), level, order % 2 ? .18 : -.18, .35)
    note('cue', b, midi, .5, level)
  }
}

// ---------------------------------------------------------------- reverb, master and loudness
function freeverb(input, room = .86, damp = .3) {
  const scale = n => Math.round(n * rate / 44100)
  const combs = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617], allpasses = [556, 441, 341, 225]
  const output = { L: new Float64Array(count), R: new Float64Array(count) }
  for (const [channel, spread] of [['L', 0], ['R', 23]]) {
    const comb = combs.map(n => ({ buffer: new Float64Array(scale(n + spread)), index: 0, store: 0 }))
    const pass = allpasses.map(n => ({ buffer: new Float64Array(scale(n + spread)), index: 0 }))
    const out = output[channel]
    for (let i = 0; i < count; i++) {
      const x = (wet.L[i] + wet.R[i]) * .015
      let sum = 0
      for (const c of comb) {
        const y = c.buffer[c.index]
        c.store = y * (1 - damp) + c.store * damp
        c.buffer[c.index] = x + c.store * room
        if (++c.index === c.buffer.length) c.index = 0
        sum += y
      }
      for (const a of pass) {
        const delayed = a.buffer[a.index], y = delayed - sum
        a.buffer[a.index] = sum + delayed * .5
        if (++a.index === a.buffer.length) a.index = 0
        sum = y
      }
      out[i] = sum
    }
  }
  return output
}
const reverb = freeverb(), wetGain = 1.9
const master = { L: new Float64Array(count), R: new Float64Array(count) }
const duck = new Float64Array(count).fill(1)
for (const { seconds, velocity } of kickTimes) {
  const start = Math.round(seconds * rate), attack = Math.round(.004 * rate)
  for (let i = Math.max(0, start - attack); i < Math.min(count, start + Math.round(.32 * rate)); i++) {
    const depth = .26 * velocity * (i < start ? (i - start + attack) / attack : Math.exp(-(i - start) / rate / .09))
    duck[i] = Math.min(duck[i], 1 - depth)
  }
}
// Fixed tilt: less sub and boxy midrange, a little more presence for small speakers.
const tilt = () => { const stages = [biquad('highpass', 32, .707), shelf('low', 95, -2), shelf('peak', 400, -2.5, .9), shelf('high', 2400, 2.5)]; return x => stages.reduce((value, stage) => stage(value), x) }
const tiltL = tilt(), tiltR = tilt()
for (let i = 0; i < count; i++) {
  master.L[i] = tiltL(music.L[i] + bed.L[i] * duck[i] + kicks.L[i] + cues.L[i] + reverb.L[i] * wetGain)
  master.R[i] = tiltR(music.R[i] + bed.R[i] * duck[i] + kicks.R[i] + cues.R[i] + reverb.R[i] * wetGain)
  if (!Number.isFinite(master.L[i]) || !Number.isFinite(master.R[i])) throw new Error('Non-finite score sample')
}

// ITU-R BS.1770-4 loudness at 48 kHz (K-weighting, 400 ms blocks, absolute and relative gates).
function kWeighted(signal) {
  const out = new Float64Array(signal.length)
  const stages = [[[1.53512485958697, -2.69169618940638, 1.19839281085285], [-1.69065929318241, .73248077421585]], [[1, -2, 1], [-1.99004745483398, .99007225036621]]]
  out.set(signal)
  for (const [[b0, b1, b2], [a1, a2]] of stages) {
    let x1 = 0, x2 = 0, y1 = 0, y2 = 0
    for (let i = 0; i < out.length; i++) { const x = out[i], y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2; x2 = x1; x1 = x; y2 = y1; y1 = y; out[i] = y }
  }
  return out
}
function loudness(L, R) {
  if (rate !== 48000) throw new Error('K-weighting coefficients are for 48 kHz')
  const kl = kWeighted(L), kr = kWeighted(R), energy = new Float64Array(L.length + 1)
  for (let i = 0; i < L.length; i++) energy[i + 1] = energy[i] + kl[i] * kl[i] + kr[i] * kr[i]
  const mean = (from, to) => (energy[Math.min(to, L.length)] - energy[Math.max(0, from)]) / (Math.min(to, L.length) - Math.max(0, from))
  const lufs = z => -.691 + 10 * Math.log10(z)
  const blocks = []
  for (let start = 0; start + .4 * rate <= L.length; start += .1 * rate) blocks.push(mean(start, start + .4 * rate))
  const gated = blocks.filter(z => lufs(z) > -70), relative = lufs(gated.reduce((s, z) => s + z, 0) / gated.length) - 10
  const kept = gated.filter(z => lufs(z) > relative)
  const integrated = lufs(kept.reduce((s, z) => s + z, 0) / kept.length)
  const shortTerm = []
  for (let start = 0; start + 3 * rate <= L.length; start += .1 * rate) shortTerm.push(lufs(mean(start, start + 3 * rate)))
  const shortGated = shortTerm.filter(l => l > -70), shortMean = lufs(shortGated.map(l => 10 ** ((l + .691) / 10)).reduce((s, z) => s + z, 0) / shortGated.length)
  const range = shortGated.filter(l => l > shortMean - 20).sort((a, b) => a - b), pick = p => range[Math.min(range.length - 1, Math.floor(p * (range.length - 1)))]
  const sectionLoudness = sections.map(([name, start], i) => {
    const end = i + 1 < sections.length ? sections[i + 1][1] : beatCount
    return { section: name, startSeconds: at(start), endSeconds: at(end), lufs: Number(lufs(mean(Math.round(at(start) * rate), Math.round(at(end) * rate))).toFixed(2)) }
  })
  return { integrated, range: pick(.95) - pick(.1), sectionLoudness }
}
// True peak via 4x windowed-sinc interpolation between samples.
function truePeak(L, R) {
  const taps = 16, phases = [.25, .5, .75].map(p => Array.from({ length: 2 * taps }, (_, j) => {
    const x = p - (j - taps + 1), sinc = Math.sin(Math.PI * x) / (Math.PI * x), w = .5 + .5 * Math.cos(Math.PI * x / taps)
    return sinc * w
  }))
  let peak = 0
  for (const signal of [L, R]) for (let i = 0; i < signal.length; i++) {
    peak = Math.max(peak, Math.abs(signal[i]))
    for (const h of phases) {
      let value = 0
      for (let j = 0; j < h.length; j++) { const k = i + j - taps + 1; if (k >= 0 && k < signal.length) value += signal[k] * h[j] }
      peak = Math.max(peak, Math.abs(value))
    }
  }
  return peak
}
// Lookahead peak limiter: the gain is already down when a transient arrives.
function limit(L, R, ceiling) {
  const look = Math.round(.003 * rate), release = Math.exp(-1 / (.12 * rate)), n = L.length
  const need = new Float64Array(n)
  for (let i = 0; i < n; i++) { const p = Math.max(Math.abs(L[i]), Math.abs(R[i])); need[i] = p > ceiling ? ceiling / p : 1 }
  const minimum = new Float64Array(n), queue = []
  for (let i = n - 1; i >= 0; i--) {
    while (queue.length && need[queue.at(-1)] >= need[i]) queue.pop()
    queue.push(i)
    while (queue[0] > i + look) queue.shift()
    minimum[i] = need[queue[0]]
  }
  let envelope = 1, sum = 0, reduced = 0, deepest = 1, deepestAt = 0
  const history = new Float64Array(look + 1)
  for (let i = 0; i < n; i++) {
    envelope = minimum[i] < envelope ? minimum[i] : minimum[i] - (minimum[i] - envelope) * release
    sum += envelope - history[i % (look + 1)]; history[i % (look + 1)] = envelope
    const gain = sum / Math.min(i + 1, look + 1)
    if (gain < .999) reduced++
    if (gain < deepest) { deepest = gain; deepestAt = i / rate }
    L[i] *= gain; R[i] *= gain
  }
  return { reduced, deepest, deepestAt }
}
const dbfs = value => 20 * Math.log10(value)
let gain = 1, report
const left = new Float64Array(count), right = new Float64Array(count)
for (let pass = 0; pass < 4; pass++) {
  for (let i = 0; i < count; i++) { left[i] = master.L[i] * gain; right[i] = master.R[i] * gain }
  const limited = limit(left, right, 10 ** (CEILING_DBFS / 20))
  for (let i = 0; i < count; i++) {
    const t = i / rate, fade = soft(t / .15) * (t > duration - 1 ? .5 + .5 * Math.cos(Math.PI * (t - duration + 1)) : 1)
    left[i] *= fade; right[i] *= fade
  }
  report = { ...loudness(left, right), limitedSamples: limited.reduced, deepestLimitDb: 20 * Math.log10(limited.deepest), deepestLimitSeconds: limited.deepestAt }
  if (Math.abs(report.integrated - LOUDNESS_TARGET) < .15) break
  gain *= 10 ** ((LOUDNESS_TARGET - report.integrated) / 20)
}
const peakTrue = truePeak(left, right)
if (dbfs(peakTrue) > -1.5) throw new Error(`True peak too high: ${dbfs(peakTrue).toFixed(2)} dBTP`)

// 16-bit PCM with triangular dither.
const pcm = Buffer.alloc(count * 4)
let samplePeak = 0, energy = 0, clipped = 0
for (let i = 0; i < count; i++) {
  const l = left[i], r = right[i]
  samplePeak = Math.max(samplePeak, Math.abs(l), Math.abs(r)); energy += l * l + r * r
  if (Math.abs(l) >= 1) clipped++
  if (Math.abs(r) >= 1) clipped++
  pcm.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(l * 32767 + (noise() + noise()) * .5))), i * 4)
  pcm.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(r * 32767 + (noise() + noise()) * .5))), i * 4 + 2)
}
const header = Buffer.alloc(44)
header.write('RIFF', 0); header.writeUInt32LE(36 + pcm.length, 4); header.write('WAVEfmt ', 8)
header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(2, 22)
header.writeUInt32LE(rate, 24); header.writeUInt32LE(rate * 4, 28); header.writeUInt16LE(4, 32); header.writeUInt16LE(16, 34)
header.write('data', 36); header.writeUInt32LE(pcm.length, 40)
const cache = path.join(root, 'cache/final'); await fs.mkdir(cache, { recursive: true })
const wav = Buffer.concat([header, pcm]); await fs.writeFile(path.join(cache, 'music.wav'), wav)
// Cue legibility: cue bus against everything else above 500 Hz, where small speakers still work.
const cueBand = new Float64Array(count), restBand = new Float64Array(count)
{
  const a = biquad('highpass', 500), b = biquad('highpass', 500)
  for (let i = 0; i < count; i++) {
    cueBand[i] = a(cues.L[i] + cues.R[i])
    restBand[i] = b(music.L[i] + music.R[i] + bed.L[i] * duck[i] + bed.R[i] * duck[i] + (reverb.L[i] + reverb.R[i]) * wetGain)
  }
}
const windowRms = (signal, from, to) => { let sum = 0; for (let i = from; i < to; i++) sum += signal[i] * signal[i]; return Math.sqrt(sum / (to - from)) }
const legibility = cueList.map(cue => {
  const delayed = cue.kind === 'camera' || cue.id === 'chapter-exit' ? Math.round(.32 * rate) : 0
  const from = cue.sample + delayed, to = Math.min(count, from + Math.round(.18 * rate))
  return { id: cue.id, frame: cue.frame, cueToMusicDb: Number(dbfs(windowRms(cueBand, from, to) / windowRms(restBand, from, to)).toFixed(1)) }
})
const offChord = notes.filter(n => n.part !== 'pad' && n.part !== 'bass' && Number.isInteger(n.beat) && !chords[n.chord].pad.concat(chords[n.chord].bass).some(m => (m - n.midi) % 12 === 0))
// Sustained melody, cue or arpeggio notes a semitone (or octaves of one) from the pad underneath.
const pads = notes.filter(n => n.part === 'pad')
const rubs = notes.filter(n => ['bell', 'cue', 'arp'].includes(n.part) && n.beats >= 1).filter(n => pads.some(pad =>
  n.beat < pad.beat + pad.beats && pad.beat < n.beat + n.beats && [1, 13, 25].includes(Math.abs(n.midi - pad.midi))))
const audit = {
  description: 'Original 120 BPM score in D major: additive pads, harmonic bass, FM bells and plucks, synthesized percussion, risers and event-derived cues; no voices or external samples.',
  form: sections.map(([name, start], i) => ({ section: name, startBeat: start, endBeat: i + 1 < sections.length ? sections[i + 1][1] : beatCount })),
  bars, harmony: harmony.map(([b, name]) => ({ beat: b, seconds: at(b), chord: name })),
  sampleRate: rate, channels: 2, samplesPerChannel: count, seconds: duration, bpm: plan.audio.bpm, beats: beatCount,
  loudness: { targetLufs: LOUDNESS_TARGET, integratedLufs: Number(report.integrated.toFixed(2)), loudnessRangeLu: Number(report.range.toFixed(2)), sections: report.sectionLoudness, limitedSamples: report.limitedSamples, deepestLimitDb: Number(report.deepestLimitDb.toFixed(2)), deepestLimitSeconds: Number(report.deepestLimitSeconds.toFixed(3)), masterGainDb: Number(dbfs(gain).toFixed(2)) },
  peak: samplePeak, peakDbfs: dbfs(samplePeak), truePeakDbtp: dbfs(peakTrue), rmsDbfs: dbfs(Math.sqrt(energy / (count * 2))),
  clippingSamples: clipped, seed: '0x41544c41', fadeInSeconds: .15, fadeOutSeconds: 1,
  harmonicCheck: { notes: notes.length, outsideKey: 0, strongBeatNonChordTones: offChord.length, sustainedSemitoneRubs: rubs.length },
  cueLegibility: legibility, cues: cueList, notes,
  sourceSha256: createHash('sha256').update(wav).digest('hex'), planSha256: plan.planSha256,
  timelineSha256: createHash('sha256').update(await fs.readFile(path.join(root, 'timeline.json'))).digest('hex'),
}
await fs.writeFile(path.join(cache, 'audio-source.json'), JSON.stringify(audit, null, 2) + '\n', 'utf8')
const { notes: _, cues: __, bars: ___, ...summary } = audit
console.log(JSON.stringify(summary, null, 2))
