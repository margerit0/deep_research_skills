const timeline = await (await fetch('../native-timeline.json')).json()
const finalEdition = new URLSearchParams(location.search).has('final')
const $ = id => document.getElementById(id)
const iframe = $('product'), stage = $('stage')
const clip = { width: 1270, height: 766 }
const openingStart = timeline.camera.opening_start, openingEnd = timeline.camera.opening_end
const byShot = id => timeline.shots.find(shot => shot.id === id)
const byEvent = id => timeline.events.find(event => event.id === id)
const graphStart = byShot('parallel').start, inspectStart = byShot('inspect').start, reportStart = byShot('report').start, brandStart = byShot('brand').start
const tabClick = byEvent('inspect-events').frame
const clicks = timeline.events.filter(event => event.kind === 'click')
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v))
const ease = t => { t = clamp(t); return t * t * (3 - 2 * t) }
const lerp = (a, b, t) => a + (b - a) * t
let app, cameras, playing = false, busy = false, current = 0
const clickAnchors = {}
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
// Between distant regions, pull back mid-move so the camera travels over the workspace
// instead of whip-panning across empty canvas; both ends match the framed cameras exactly.
function travel(a, b, p, depth) {
  const e = ease(p), centre = c => ({ x: (clip.width / 2 - c.x) / c.scale, y: (clip.height / 2 - c.y) / c.scale })
  const from = centre(a), to = centre(b)
  const scale = Math.exp(lerp(Math.log(a.scale), Math.log(b.scale), e)) * (1 - depth * Math.sin(Math.PI * e))
  return { scale, x: clip.width / 2 - lerp(from.x, to.x, e) * scale, y: clip.height / 2 - lerp(from.y, to.y, e) * scale }
}
function cameraAt(f) {
  if (f < openingStart) return cameras.workspace
  if (f <= openingEnd) return blend(cameras.workspace, cameras.input, (f - openingStart) / (openingEnd - openingStart))
  if (f < graphStart) return cameras.input
  if (f < graphStart + 30) return travel(cameras.input, cameras.graph, (f - graphStart) / 29, .34)
  if (f <= inspectStart) return cameras.graph
  if (f < tabClick) return blend(cameras.graph, cameras.inspectorInput, (f - inspectStart) / 14)
  if (f < tabClick + 11) return blend(cameras.inspectorInput, cameras.inspector, (f - tabClick) / 10)
  if (f < reportStart) return cameras.inspector
  if (f < reportStart + 15) return travel(cameras.inspector, cameras.report, (f - reportStart) / 14, .24)
  return cameras.report
}

function openingAt(frame) {
  const progress = ease((frame - openingStart) / (openingEnd - openingStart))
  const reveal = ease((frame - timeline.camera.copy_reveal_start) / (timeline.camera.copy_reveal_end - timeline.camera.copy_reveal_start))
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
  $('opening-disclosure').style.opacity = frame < timeline.camera.copy_reveal_end ? '1' : '0'
  document.querySelector('.window-status').style.opacity = frame > timeline.camera.copy_reveal_end ? '1' : '0'
  return { progress, reveal, windowBox }
}

// The report card in viewport coordinates, with the composer edge it must stay clear of.
function reportFraming(cam) {
  if (!app.document.querySelector('.cw-report-message')) return null
  const at = box => box && { x: box.x * cam.scale + cam.x, y: box.y * cam.scale + cam.y, right: box.right * cam.scale + cam.x, bottom: box.bottom * cam.scale + cam.y }
  const card = at(rect('.cw-report-message')), foot = at(app.document.querySelector('.cw-report-foot') && rect('.cw-report-foot'))
  return { scale: cam.scale, card, foot, composerTop: rect('.cw-composer-wrap').y * cam.scale + cam.y, veil: Number(veil.style.opacity), inside: card.x >= 0 && card.y >= 0 && card.right <= clip.width && card.bottom <= clip.height }
}

function pointerAt(frame, cam) {
  const pointer = $('pointer'), ring = $('click-ring')
  pointer.style.display = 'none'; ring.style.display = 'none'
  const event = clicks.find(event => frame >= event.frame - event.approach_frames && frame <= event.frame + event.linger_frames)
  if (!event) return
  const target = event.target, clickFrame = event.frame, approach = clickFrame - event.approach_frames
  const box = clickAnchors[event.id]
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
}

async function renderFrame(frame) {
  if (!Number.isInteger(frame) || frame < 0 || frame >= timeline.frame_count) throw new Error(`Frame must be an integer in 0–${timeline.frame_count - 1}`)
  await window.ready
  current = frame
  const click = clicks.find(event => event.frame === frame)
  if (click) {
    await app.renderNativeFrame(frame - 1)
    const audit = app.invokeNativeClick(click.target)
    const camera = cameraAt(frame), [nativeX, nativeY] = audit.nativeTip
    const tip = [nativeX * camera.scale + camera.x, nativeY * camera.scale + camera.y]
    const expected = click.expected_callback
    const callbackMatches = !expected || audit.callbacks.some(callback => JSON.stringify(callback) === JSON.stringify(expected))
    clickAudit.push({ ...audit, frame, id: click.id, tip, callbackMatches, insideViewport: tip[0] >= 0 && tip[1] >= 0 && tip[0] < clip.width && tip[1] < clip.height })
  }
  const native = await app.renderNativeFrame(Math.min(frame, brandStart - 1))
  // At a node click preserve the pre-click scroll position for the exact hit frame.
  if (frame === inspectStart) {
    app.document.querySelector('.cw-graph-panel').scrollTop = 0
  }
  const shot = timeline.shots.find(s => frame >= s.start && frame <= s.end)
  // Keep the report under the closing fade; review-only candidate notes are not film copy.
  const copyShot = frame >= brandStart ? byShot('report') : shot
  stage.dataset.focus = shot.id
  const shotIndex = timeline.shots.indexOf(shot)
  const opening = openingAt(frame)
  $('chapter-number').textContent = String(shotIndex + 1).padStart(2, '0')
  $('chapter-label').textContent = shot.label
  $('headline').textContent = copyShot.headline
  $('description').textContent = copyShot.description
  $('context').replaceChildren(Object.assign(document.createElement('strong'), { textContent: copyShot.context_title }), document.createTextNode(copyShot.context))
  $('window-label').textContent = frame <= openingEnd ? '星图工作台 / 完整工作台' : `星图工作台 / ${shot.label}`
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
  $('frame-label').textContent = `${frame} / ${timeline.frame_count - 1}`
  await new Promise(resolve => requestAnimationFrame(resolve))
  return { frame, shot: shot.id, camera, opening, native, clickAudit: [...clickAudit], report: reportFraming(camera) }
}

window.ready = (async () => {
  if (!iframe.contentWindow?.renderNativeFrame) await new Promise(resolve => iframe.addEventListener('load', resolve, { once: true }))
  app = iframe.contentWindow
  await app.nativeReady
  await app.document.fonts.ready
  const nativeMark = app.document.querySelector('.cw-brand-icon').innerHTML
  document.querySelectorAll('.brand-mark,.end-mark').forEach(el => el.innerHTML = nativeMark)
  await app.renderNativeFrame(byEvent('choose-skill').frame + 15)
  const inputBoxSelected = rect('.cw-composer-wrap')
  await app.renderNativeFrame(byEvent('open-skills').frame + 15)
  const menuBox = rect('#cw-skill-menu')
  const input = cameraFor({ ...inputBoxSelected, y: Math.min(inputBoxSelected.y, menuBox.y), height: inputBoxSelected.bottom - Math.min(inputBoxSelected.y, menuBox.y) }, 1.62)
  await app.renderNativeFrame(graphStart + 45)
  const flow = rect('.cw-flow'), graph = rect('.cw-graph-panel')
  const graphBox = { ...flow, y: graph.y, height: flow.bottom - graph.y }
  const graphCamera = cameraFor(graphBox, Math.min(1.6, (clip.height - 30) / graphBox.height))
  await app.renderNativeFrame(tabClick - 1)
  const inputBox = rect('.cw-inspector')
  const inspectorInput = cameraFor(inputBox, Math.min(2.03, (clip.height - 50) / inputBox.height))
  await app.renderNativeFrame(reportStart - 20)
  const inspectorBox = rect('.cw-inspector')
  const inspector = cameraFor(inspectorBox, Math.min(2.03, (clip.height - 50) / inspectorBox.height))
  await app.renderNativeFrame(reportStart + 45)
  const reportBox = rect('.cw-report-message')
  const report = cameraFor(reportBox, Math.min(1.82, (clip.width - 70) / reportBox.width, (clip.height - 42) / reportBox.height))
  cameras = { workspace: { scale: 1, x: 0, y: 0 }, input, graph: graphCamera, inspectorInput, inspector, report }
  for (const click of clicks) {
    await app.renderNativeFrame(click.frame - 1)
    clickAnchors[click.id] = rect(click.target)
  }
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
if (finalEdition) document.querySelector('.edition').textContent = '产品演示 / v8'
$('seek').max = String(timeline.frame_count - 1)
$('play').textContent = `播放 ${timeline.duration_seconds} 秒分镜`
$('seek').addEventListener('input', async e => { playing = false; if (!busy) { busy = true; await renderFrame(Number(e.target.value)); busy = false } })
$('play').addEventListener('click', async () => {
  playing = !playing
  if (!playing) return
  const start = performance.now()
  const tick = async () => {
    if (!playing) return
    const frame = Math.min(timeline.frame_count - 1, Math.floor((performance.now() - start) / 1000 * timeline.fps))
    if (!busy) { busy = true; await renderFrame(frame); busy = false }
    if (frame < timeline.frame_count - 1) requestAnimationFrame(tick); else playing = false
  }
  requestAnimationFrame(tick)
})
await window.ready
if (!new URLSearchParams(location.search).has('export')) await renderFrame(Number(new URLSearchParams(location.search).get('frame') ?? 0))
window.sceneLoaded = true
