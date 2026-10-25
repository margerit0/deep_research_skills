const timeline = await (await fetch('../timeline.json')).json()
const finalEdition = new URLSearchParams(location.search).has('final')
const $ = id => document.getElementById(id)
const iframe = $('product'), stage = $('stage')
const clip = { width: 1270, height: 766 }
const openingStart = timeline.events.find(event => event.kind === 'camera').frame
const openingEnd = 59
const graphStart = timeline.shots[1].start, inspectStart = timeline.shots[2].start, reportStart = timeline.shots[3].start, brandStart = timeline.shots[4].start
const clicks = timeline.events.filter(event => event.kind === 'click')
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v))
const ease = t => { t = clamp(t); return t * t * (3 - 2 * t) }
const lerp = (a, b, t) => a + (b - a) * t
let app, cameras, playing = false, busy = false, current = 45
let clickAudit = []
const veil = document.createElement('div')
veil.id = 'focus-veil'
$('viewport').append(veil)

const rect = selector => {
  const el = app.document.querySelector(selector)
  if (!el) throw new Error(`Missing native target ${selector}`)
  const r = el.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }
}
function cameraFor(box, scale, align = 'center') {
  return { scale, x: align === 'right' ? clip.width - 34 - box.right * scale : clip.width / 2 - (box.x + box.width / 2) * scale, y: clip.height / 2 - (box.y + box.height / 2) * scale }
}
const blend = (a, b, p) => Object.fromEntries(['scale', 'x', 'y'].map(k => [k, lerp(a[k], b[k], ease(p))]))
function cameraAt(f) {
  if (f < openingStart) return cameras.workspace
  if (f <= openingEnd) return blend(cameras.workspace, cameras.input, (f - openingStart) / (openingEnd - openingStart))
  if (f < graphStart) return cameras.input
  if (f < graphStart + 30) return blend(cameras.input, cameras.graph, (f - graphStart) / 29)
  if (f <= inspectStart) return cameras.graph
  if (f < clicks[1].frame) return blend(cameras.graph, cameras.inspectorInput, (f - inspectStart) / 14)
  if (f < clicks[1].frame + 11) return blend(cameras.inspectorInput, cameras.inspector, (f - clicks[1].frame) / 10)
  if (f < reportStart) return cameras.inspector
  if (f < reportStart + 15) return blend(cameras.inspector, cameras.report, (f - reportStart) / 14)
  return cameras.report
}

function openingAt(frame) {
  const progress = ease((frame - openingStart) / (openingEnd - openingStart))
  const reveal = ease((frame - 60) / 14)
  const windowBox = { left: lerp(0, 570, progress), top: lerp(0, 164, progress), width: lerp(1920, 1272, progress), height: lerp(1080, 814, progress) }
  Object.assign($('window').style, Object.fromEntries(Object.entries(windowBox).map(([key, value]) => [key, `${value}px`])))
  $('window').style.borderWidth = `${progress}px`
  $('window').style.borderRadius = `${23 * progress}px`
  const bar = lerp(48, 46, progress)
  document.querySelector('.window-bar').style.height = `${bar}px`
  $('viewport').style.width = `${windowBox.width - progress * 2}px`
  $('viewport').style.height = `${windowBox.height - bar - progress * 2}px`
  document.querySelector('.identity').style.opacity = String(reveal)
  document.querySelector('footer').style.opacity = String(reveal)
  $('opening-disclosure').style.opacity = String(1 - reveal)
  document.querySelector('.window-status').style.opacity = frame >= 75 ? '1' : '0'
  return { progress, reveal, windowBox }
}

function pointerAt(frame, cam) {
  const pointer = $('pointer'), ring = $('click-ring')
  pointer.style.display = 'none'; ring.style.display = 'none'
  let target, clickFrame, approach
  if (frame >= clicks[0].frame - 15 && frame <= clicks[0].frame) { target = clicks[0].target; clickFrame = clicks[0].frame; approach = clickFrame - 15 }
  if (frame >= clicks[1].frame - 7 && frame <= clicks[1].frame + 15) { target = clicks[1].target; clickFrame = clicks[1].frame; approach = clickFrame - 7 }
  if (!target) return
  const box = rect(target)
  const p = ease((frame - approach) / Math.max(1, clickFrame - approach - 4))
  const x = (box.x + box.width * .55) * cam.scale + cam.x
  const y = (box.y + box.height * .5) * cam.scale + cam.y
  const px = x + (1 - p) * 100, py = y + (1 - p) * 90
  pointer.style.display = 'block'; pointer.style.left = `${px - 3}px`; pointer.style.top = `${py - 2}px`
  if (frame >= clickFrame && frame < clickFrame + 8) {
    const t = (frame - clickFrame) / 8, radius = 10 + 19 * t
    ring.style.display = 'block'; ring.style.width = ring.style.height = `${radius * 2}px`
    ring.style.left = `${x - radius}px`; ring.style.top = `${y - radius}px`; ring.style.opacity = String(1 - t)
  }
  if (frame === clickFrame) {
    const nativeX = (px - cam.x) / cam.scale, nativeY = (py - cam.y) / cam.scale
    const hit = app.document.elementFromPoint(nativeX, nativeY)
    clickAudit.push({ frame, target, tip: [px, py], nativeTip: [nativeX, nativeY], bounds: box, hit: !!hit?.closest(target), insideViewport: px >= 0 && py >= 0 && px < clip.width && py < clip.height, topElement: hit?.outerHTML.slice(0, 200) })
  }
}

async function renderFrame(frame) {
  if (!Number.isInteger(frame) || frame < 0 || frame >= timeline.frame_count) throw new Error('Frame must be an integer in 0–359')
  await window.ready
  current = frame
  const native = await app.renderNativeFrame(Math.min(frame, brandStart - 1))
  // At a node click preserve the pre-click scroll position for the exact hit frame.
  if (frame === inspectStart) {
    app.document.querySelector('.cw-graph-panel').scrollTop = 0
  }
  const shot = timeline.shots.find(s => frame >= s.start && frame <= s.end)
  // Keep the report under the closing fade; review-only candidate notes are not film copy.
  const copyShot = finalEdition && frame >= brandStart ? timeline.shots[3] : shot
  stage.dataset.focus = shot.id
  const shotIndex = timeline.shots.indexOf(shot)
  const opening = openingAt(frame)
  $('chapter-number').textContent = String(shotIndex + 1).padStart(2, '0')
  $('chapter-label').textContent = shot.label
  $('headline').textContent = copyShot.headline
  $('description').textContent = copyShot.description
  $('context').replaceChildren(Object.assign(document.createElement('strong'), { textContent: copyShot.context_title }), document.createTextNode(copyShot.context))
  $('window-label').textContent = frame < 60 ? '星图工作台 / 完整工作台' : `星图工作台 / ${shot.label}`
  const camera = cameraAt(frame)
  iframe.style.transform = `translate(${camera.x}px,${camera.y}px) scale(${camera.scale})`
  veil.style.opacity = String(frame >= graphStart && frame < reportStart ? ease((frame - graphStart) / 29) : frame >= reportStart && frame < reportStart + 15 ? 1 - ease((frame - reportStart) / 14) : 0)
  const panelLeft = rect(frame <= inspectStart ? '.cw-graph-panel' : '.cw-inspector').x
  veil.style.width = `${Math.max(0, panelLeft * camera.scale + camera.x - 12)}px`
  pointerAt(frame, camera)
  const end = ease((frame - brandStart) / 29)
  $('end-card').style.opacity = String(end)
  $('end-card').style.transform = `translateY(${(1 - end) * 18}px)`
  $('window').style.opacity = String(1 - end)
  $('window').style.transform = `translateY(${-end * 25}px) scale(${1 - end * .035})`
  $('copy').style.opacity = $('chapter').style.opacity = String(opening.reveal * (1 - end))
  $('footer-caption').textContent = frame >= brandStart ? '明确范围 · 并行研究 · 汇成报告' : '界面与数据来自项目内置合成演示'
  $('seek').value = String(frame)
  $('frame-label').textContent = `${frame} / 359`
  await new Promise(resolve => requestAnimationFrame(resolve))
  return { frame, shot: shot.id, camera, opening, native, clickAudit: [...clickAudit] }
}

window.ready = (async () => {
  if (!iframe.contentWindow?.renderNativeFrame) await new Promise(resolve => iframe.addEventListener('load', resolve, { once: true }))
  app = iframe.contentWindow
  await app.nativeReady
  await app.document.fonts.ready
  const nativeMark = app.document.querySelector('.cw-brand-icon').innerHTML
  document.querySelectorAll('.brand-mark,.end-mark').forEach(el => el.innerHTML = nativeMark)
  await app.renderNativeFrame(75)
  const input = cameraFor(rect('.cw-composer-wrap'), 1.62)
  await app.renderNativeFrame(135)
  const flow = rect('.cw-flow'), graph = rect('.cw-graph-panel')
  const graphBox = { ...flow, y: graph.y, height: flow.bottom - graph.y }
  const graphCamera = cameraFor(graphBox, Math.min(1.6, (clip.height - 30) / graphBox.height))
  await app.renderNativeFrame(clicks[1].frame - 1)
  const inputBox = rect('.cw-inspector')
  const inspectorInput = cameraFor(inputBox, Math.min(2.03, (clip.height - 50) / inputBox.height))
  await app.renderNativeFrame(190)
  const inspectorBox = rect('.cw-inspector')
  const inspector = cameraFor(inspectorBox, Math.min(2.03, (clip.height - 50) / inspectorBox.height))
  await app.renderNativeFrame(255)
  const reportBox = rect('.cw-report-message')
  const report = cameraFor(reportBox, Math.min(1.82, (clip.width - 70) / reportBox.width, (clip.height - 42) / reportBox.height))
  cameras = { workspace: { scale: 1, x: 0, y: 0 }, input, graph: graphCamera, inspectorInput, inspector, report }
  window.mediaData = app.mediaData
  window.sceneCameras = cameras
})()
Object.assign(window, { renderFrame, timeline })
function fit() {
  const scale = Math.min(innerWidth / 1920, innerHeight / 1080)
  stage.style.transform = `scale(${scale})`
}
fit(); addEventListener('resize', fit)
if (new URLSearchParams(location.search).has('export')) document.body.dataset.export = 'true'
if (finalEdition) document.querySelector('.edition').textContent = '产品演示 / v2'
$('seek').addEventListener('input', async e => { playing = false; if (!busy) { busy = true; await renderFrame(Number(e.target.value)); busy = false } })
$('play').addEventListener('click', async () => {
  playing = !playing
  if (!playing) return
  const start = performance.now()
  const tick = async () => {
    if (!playing) return
    const frame = Math.min(359, Math.floor((performance.now() - start) / 1000 * 30))
    if (!busy) { busy = true; await renderFrame(frame); busy = false }
    if (frame < 359) requestAnimationFrame(tick); else playing = false
  }
  requestAnimationFrame(tick)
})
await window.ready
if (!new URLSearchParams(location.search).has('export')) await renderFrame(Number(new URLSearchParams(location.search).get('frame') ?? 0))
window.sceneLoaded = true
