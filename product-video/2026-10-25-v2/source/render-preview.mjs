import path from 'node:path'
import fs from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'

const here = path.dirname(fileURLToPath(import.meta.url))
const output = path.resolve(here, '..'), repo = path.resolve(here, '../../..')
const require = createRequire(path.join(repo, 'frontend/package.json'))
const { chromium } = require('playwright')
const timeline = JSON.parse(await fs.readFile(path.join(output, 'timeline.json'), 'utf8'))
if (timeline.events.some(event => event.frame % timeline.beat_frames !== 0)) throw new Error('Event starts must align with the beat grid.')
const finalMode = process.argv.includes('--final')
const cache = finalMode ? 'cache/final' : 'cache'
if (finalMode && timeline.approval.status !== 'approved') throw new Error('Approve the current preview before rendering the complete movie.')
const hash = data => createHash('sha256').update(data).digest('hex')
const saveJson = (name, value) => fs.writeFile(path.join(output, name.startsWith('cache/') ? name.replace('cache/', `${cache}/`) : name), JSON.stringify(value, null, 2) + '\n', 'utf8')
for (const folder of ['preview', `${cache}/frames`, `${cache}/random-access`]) await fs.mkdir(path.join(output, folder), { recursive: true })
if (finalMode) {
  const approved = JSON.parse(await fs.readFile(path.join(output, 'preview/approved-timeline.json'), 'utf8'))
  const current = { ...timeline }, original = { ...approved }
  delete current.approval; delete original.approval
  if (JSON.stringify(current) !== JSON.stringify(original)) throw new Error('Approved storyboard or timing changed.')
  const brief = JSON.parse(await fs.readFile(path.join(output, 'brief.json'), 'utf8'))
  for (const dependency of brief.sources) {
    if (hash(await fs.readFile(path.join(repo, dependency.path))) !== dependency.sha256) throw new Error(`Native dependency changed: ${dependency.path}`)
  }
}
const candidates = [process.env.CHROME_PATH, 'C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].filter(Boolean)
let executablePath
for (const candidate of candidates) { try { await fs.access(candidate); executablePath = candidate; break } catch {} }
const browser = await chromium.launch(executablePath ? { executablePath, headless: true } : { headless: true })
const context = await browser.newContext({ viewport: { width: timeline.width, height: timeline.height }, deviceScaleFactor: 1, colorScheme: 'light' })
const errors = [], blocked = [], requests = []
await context.route('**/*', route => {
  const url = new URL(route.request().url())
  if (url.protocol === 'data:') return route.continue()
  if (url.origin !== 'http://127.0.0.1:5187' || url.pathname.startsWith('/api/')) {
    blocked.push(url.href); return route.abort()
  }
  requests.push(url.pathname)
  return route.continue()
})
const url = `http://127.0.0.1:5187/product-video/${timeline.version}/source/index.html?export=1${finalMode ? '&final=1' : ''}`
async function openPage() {
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForFunction(() => window.sceneLoaded === true, null, { timeout: 30000 })
  return page
}
async function semanticState(page) {
  return page.evaluate(() => {
    const app = document.getElementById('product').contentWindow, doc = app.document
    const visibleText = el => el && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden'
    const disclosures = [...document.querySelectorAll('.disclosure')].map(el => {
      const box = el.getBoundingClientRect()
      let opacity = 1
      for (let ancestor = el; ancestor; ancestor = ancestor.parentElement) opacity *= Number(getComputedStyle(ancestor).opacity)
      return { text: el.textContent, visible: visibleText(el) && box.left >= 0 && box.bottom <= innerHeight && opacity >= .499 }
    })
    return {
      disclosure: { text: disclosures[0].text, visible: disclosures.some(item => item.visible), instances: disclosures },
      question: doc.querySelector('textarea')?.value,
      report: doc.querySelector('.cw-demo-report')?.textContent ?? null,
      events: [...doc.querySelectorAll('#cw-pane-events .cw-event')].map(e => e.innerText),
      selectedTab: doc.querySelector('.cw-inspector-tab[aria-selected="true"]')?.id,
      selectedNode: doc.querySelector('.cw-node[aria-pressed="true"]')?.dataset.flowNode,
      runningNodes: doc.querySelectorAll('.cw-node[data-status="running"]').length,
      flowing: [...doc.querySelectorAll('.cw-wire-flash.is-flowing')].map(e => ({ offset: app.getComputedStyle(e).strokeDashoffset, visible: app.getComputedStyle(e).visibility !== 'hidden' })),
      animations: doc.getAnimations().filter(a => a.animationName === 'cw-breathe').length,
      scroll: [doc.querySelector('.cw-messages')?.scrollTop, doc.querySelector('.cw-graph-panel')?.scrollTop ?? 0],
      fonts: { outer: document.fonts.check('16px "Microsoft YaHei"'), native: doc.fonts.check('13px "Microsoft YaHei"') },
    }
  })
}
const baseline = {}, semantic = {}, clicks = []
const evidence = new Set([0, 15, 29, 30, 35, 40, 45, 50, 55, 59, 60, 74, 75, 89, 90, 100, 105, 110, 119, 120, 125, 134, 135, 145, 149, 150, 151, 158, 164, 165, 176, 180, 194, 195, 209, 210, 224, 225, 239, 255, 299, 300, 314, 329, 330, 345, 359])
let page
try {
  page = await openPage()
  const data = await page.evaluate(() => window.mediaData)
  await saveJson('cache/source-texts.json', data)
  await page.evaluate(() => window.renderFrame(0))
  const openingLayout = await page.evaluate(() => {
    const app = document.getElementById('product').contentWindow, doc = app.document
    const selectors = ['.cw-sidebar','.cw-header','.cw-composer-wrap','.cw-graph-panel']
    return {
      nativeViewport: [app.innerWidth, app.innerHeight],
      videoWindow: document.getElementById('window').getBoundingClientRect().toJSON(),
      nativeElements: selectors.map(selector => {
        const el = doc.querySelector(selector), rect = el.getBoundingClientRect()
        return { selector, rect: rect.toJSON(), opacity: Number(app.getComputedStyle(el).opacity), insideViewport: rect.left >= 0 && rect.top >= 0 && rect.right <= app.innerWidth && rect.bottom <= app.innerHeight }
      }),
      pendingResearcherPlaceholder: doc.querySelector('.cw-graph-panel').innerText.includes('任务开始后展示研究员'),
    }
  })
  if (openingLayout.videoWindow.width !== 1920 || openingLayout.videoWindow.height !== 1080 || openingLayout.nativeElements.some(el => !el.insideViewport || el.opacity !== 1)) throw new Error('Opening must contain the complete visible native interface.')
  await saveJson('cache/native-layout.json', openingLayout)
  for (let frame = 0; frame < timeline.frame_count; frame++) {
    const state = await page.evaluate(f => window.renderFrame(f), frame)
    const snapshot = await semanticState(page)
    if (!snapshot.disclosure.visible || snapshot.disclosure.text !== '合成演示 · 流程已压缩') throw new Error(`Missing disclosure at ${frame}`)
    if (state.native.text.includes('\ufffd')) throw new Error(`Replacement character at ${frame}`)
    if (frame === 45 && snapshot.question !== data.prompt) throw new Error('Prompt differs from source')
    if (frame === 255 && snapshot.report !== data.demoReport) throw new Error('Report differs from source')
    if (frame >= 210 && (snapshot.runningNodes || snapshot.flowing.some(e => e.visible) || snapshot.animations)) throw new Error(`Running cue survived completion at ${frame}`)
    const core = { camera: state.camera, opening: state.opening, states: state.native.states, wires: state.native.wires, text: state.native.text, snapshot }
    baseline[frame] = hash(JSON.stringify(core))
    if (evidence.has(frame) || timeline.keyframes.includes(frame)) semantic[frame] = core
    if (timeline.events.some(e => e.frame === frame && e.kind === 'click')) {
      const hit = state.clickAudit.at(-1)
      if (!hit?.hit || !hit.insideViewport) throw new Error(`Click missed at ${frame}`)
      clicks.push(hit)
    }
    const inSample = frame >= timeline.motion_sample.first_frame && frame <= timeline.motion_sample.last_frame
    if (finalMode || inSample || evidence.has(frame) || timeline.keyframes.includes(frame)) {
      const file = path.join(output, cache, 'frames', `frame-${String(frame).padStart(3, '0')}.png`)
      await page.screenshot({ path: file, animations: 'allow' })
      if (!finalMode && timeline.keyframes.includes(frame)) await fs.copyFile(file, path.join(output, 'preview', path.basename(file)))
    }
    if (frame % 30 === 0) console.log(`Rendered ${frame}/359`)
  }
  const graph = await page.evaluate(async () => {
    await window.renderFrame(135)
    const doc = document.getElementById('product').contentDocument
    const flow = doc.querySelector('.cw-flow').getBoundingClientRect()
    const nodes = Object.fromEntries([...doc.querySelectorAll('[data-flow-node]')].map(el => {
      const r = el.getBoundingClientRect()
      return [el.dataset.flowNode, { x: r.x - flow.x, y: r.y - flow.y, w: r.width, h: r.height }]
    }))
    const pairs = [['clarify','brief'],['brief','supervisor'],['supervisor','a'],['a','join'],['supervisor','b'],['b','join'],['supervisor','c'],['c','join'],['join','report'],['join','supervisor']]
    return [...doc.querySelectorAll('.cw-wire')].map((p, i) => {
      const pair = pairs[i], a = nodes[pair[0]], b = nodes[pair[1]]
      const s = p.getPointAtLength(0), e = p.getPointAtLength(p.getTotalLength())
      const expectedStart = i === 0 ? [a.x+a.w+1,a.y+a.h/2] : i === 9 ? [a.x,a.y+a.h/2] : [a.x+a.w/2,a.y+a.h+1]
      const expectedEnd = i === 0 ? [b.x-4,b.y+b.h/2] : i === 9 ? [b.x-4,b.y+b.h/2] : [b.x+b.w/2,b.y-4]
      const maxError = Math.max(Math.abs(s.x-expectedStart[0]),Math.abs(s.y-expectedStart[1]),Math.abs(e.x-expectedEnd[0]),Math.abs(e.y-expectedEnd[1]))
      return { pair, maxError, arrow: p.getAttribute('marker-end'), loop: p.classList.contains('is-loop') }
    })
  })
  if (graph.length !== 10 || graph.some(edge => edge.maxError > 1 || !edge.arrow) || !graph[9].loop) throw new Error('Graph topology or endpoint mismatch')
  await page.close()
  page = await openPage()
  const randomAccess = []
  for (const frame of [255,15,75,45,195,105,345,0,30,59,125,145,135,150,165,239,225]) {
    const state = await page.evaluate(f => window.renderFrame(f), frame)
    const snapshot = await semanticState(page)
    const core = { camera: state.camera, opening: state.opening, states: state.native.states, wires: state.native.wires, text: state.native.text, snapshot }
    const equal = hash(JSON.stringify(core)) === baseline[frame]
    randomAccess.push({ frame, equal })
    await page.screenshot({ path: path.join(output, cache, 'random-access', `frame-${String(frame).padStart(3,'0')}.png`) })
    if (!equal) await saveJson(`cache/random-${frame}.json`, { baseline: semantic[frame], actual: core })
  }
  await saveJson('cache/capture-audit.json', { allFramesChecked: 360, resolution: [1920,1080], clicks, graph, randomAccess, semantic, errors, blocked, requestedPaths: [...new Set(requests)], cameras: await page.evaluate(() => window.sceneCameras) })
  if (!finalMode) {
  const trackedSources = ['frontend/src/data/demo.ts','frontend/src/data/mock.ts','frontend/src/data/example-nodes.json','frontend/src/components/Graph.tsx','frontend/src/components/Inspector.tsx','frontend/src/components/Composer.tsx','frontend/src/components/Conversation.tsx','frontend/src/components/Sidebar.tsx','frontend/src/components/Icon.tsx','frontend/src/apple.css','frontend/src/app.css','frontend/src/demo.css','frontend/package-lock.json']
  const sources = []
  for (const source of trackedSources) sources.push({ path: source, sha256: hash(await fs.readFile(path.join(repo, source))) })
  await saveJson('brief.json', {
    version: timeline.version, date: '2026-10-25', timezone: 'Europe/Amsterdam', stage: 'preview', approval: timeline.approval,
    git: { branch: execFileSync('git',['branch','--show-current'],{cwd:repo,encoding:'utf8'}).trim(), commit: execFileSync('git',['rev-parse','HEAD'],{cwd:repo,encoding:'utf8'}).trim(), existingWork: `本次仅新增 product-video/${timeline.version}，保留既有未提交修改和 v1 成片` },
    product: { name: '星图工作台', backend: 'Deep Research Agent', evidence: ['README.md 前端预览','frontend/README.md 保留的模拟会话与交互'], audience: { text: '需要拆解开放式问题、查看研究进展与阅读结构化报告的研究者和产品团队', status: 'carried_from_approved_v1' }, value: '在同一界面完成提问、查看并行研究进展、检查节点与阅读报告。', valueEvidence: 'README.md 配套星图工作台介绍', tagline: { text: '让研究的每一步，看得见。', status: 'carried_from_approved_v1' }, secondaryTagline: { text: '深度研究 · 一目了然', status: 'carried_from_approved_v1' } },
    scenario: { type: 'original_synthetic', source: 'frontend/src/data/demo.ts', supportingSource: 'frontend/src/data/mock.ts / initialWorkspace().threads[0].runs[0]', question: data.prompt, reply: data.demoReply, report: data.demoReport, reportKey: 'demoReport', citations: [], sourceTitles: [], sourceExcerpts: [], limitation: '原创合成报告没有真实来源原文或编号引用；不展示引用面板、实测结论、评估分数或产品响应速度。', nativeDataDurationMs: data.scenes.reduce((n,s)=>n+s.duration,0), displayedDurationSeconds: 12, nativeDemoIndexes: timeline.events.filter(e=>e.native_demo_index!==undefined).map(e=>e.native_demo_index) },
    displayCopy: timeline.shots.map(s=>({id:s.id,headline:s.headline,description:s.description,context:s.context})),
    copySupport: [{ copy: '三个方向，同时展开。', key: 'demoReply', evidence: '我会从技术路线、商业模式和隐私风险三个方向并行研究。' }, { copy: '已确认与待验证各有归属。', key: 'demoReport / 03 · 隐私风险', evidence: '区分已确认信息与待验证问题。', qualification: '这是模拟报告的分析框架，不是已经验证真实产品结论的声明。' }],
    layout: { nativeViewportCssPixels: [1920,1032], originalReferenceViewportCssPixels: [1440,962], videoPixels: [1920,1080], deviceScaleFactor: 1, originalGraphWidth: 350, originalInspectorWidth: 330, originalSidebarWidth: 146, fontSizesCssPixels: { header:15, question:13, graphNode:12, inspectorTitle:15, report:12 }, breakpoints: { narrowDesktop:920, hideSidebar:820, stackGraph:660 }, cameras: await page.evaluate(()=>window.sceneCameras), openingLayout, adaptation: '开场的 1920×1080 浏览器画面包含 48px 镜头容器栏与 1920×1032 原生工作台；初始显示原生待执行图谱，不提前添加研究员。完整视口保持 1 秒，连续聚焦 1 秒，输入框保持 1 秒。复用原组件、CSS、SVG 与合成数据，省略演示播放器控制栏。后续保留原生图谱与检查器。输入区为只读演示状态，不虚构发送点击。', nativeEvidence: 'cache/native-layout.json 为本版实际渲染并测量的组件布局；原应用参考证据保留在 v1/cache' },
    graph: { nodes: ['clarify','brief','supervisor','a','b','c','report'], join: '汇总连接点，不是新研究节点', edges: graph.map(e=>({from:e.pair[0],to:e.pair[1],loop:e.loop})), semantics: '图谱表示阶段和可返回的协作关系；检查器时间线展示所选商业研究员的任务、检索、核验与压缩记录，不展示内部推理。' },
    output: { directory: `product-video/${timeline.version}`, ...Object.fromEntries(['width','height','fps','duration_seconds','frame_count','bpm','beat_frames'].map(k=>[k,timeline[k]])), plannedFinal: 'H.264 yuv420p + AAC MP4；仅获批后制作', previewSample: timeline.motion_sample, music: '确认本版后，配乐事件依照新时间轴同步生成；本阶段未制作正式配乐' },
    sources, restrictions: { realModelCalls:0, realUserData:false, liveRecordingsUsed:false, publication:false, commitsCreated:false },
  })
  }
  if (errors.length || blocked.length || randomAccess.some(x=>!x.equal)) throw new Error('Capture completed with validation failures; inspect cache/capture-audit.json')
  console.log(`${finalMode ? 'Complete movie' : 'Preview'} capture and semantic checks passed.`)
} finally { await browser.close() }
