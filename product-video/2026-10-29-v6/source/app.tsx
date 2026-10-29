import React from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { Sidebar } from '../../../frontend/src/components/Sidebar'
import { Conversation } from '../../../frontend/src/components/Conversation'
import { Graph } from '../../../frontend/src/components/Graph'
import { Icon } from '../../../frontend/src/components/Icon'
import { initialWorkspace, skills } from '../../../frontend/src/data/mock'
import { demoWorkspace, demoNodes, demoScenes, demoStart, demoReply, demoReport } from '../../../frontend/src/data/demo'
import type { WorkspaceController } from '../../../frontend/src/state/useWorkspace'
import '../../../frontend/src/apple.css'
import '../../../frontend/src/app.css'
import '../../../frontend/src/demo.css'
import timeline from '../native-timeline.json'

// Media adapter only: the application, schemas, components and fixtures stay untouched.
// No live hooks, API clients, model calls, recording loaders or persistence are invoked.
const base = initialWorkspace()
base.theme = 'light'
const noop = () => {}
const at = (index: number) => timeline.events.find(event => event.native_demo_index === index)!.frame
const firstClick = at(9), tabClick = at(10), reportReady = at(13)
const menuOpen = timeline.events.find(event => event.id === 'open-skills')!.frame
const skillChosen = timeline.events.find(event => event.id === 'choose-skill')!.frame
let callbackAudit: unknown[] = []
const recordDispatch = (action: unknown) => callbackAudit.push(action)
const root = createRoot(document.getElementById('root')!)
document.documentElement.style.colorScheme = 'light'
const style = document.createElement('style')
style.textContent = `html,body{width:1920px;height:1032px;overflow:hidden} *{scroll-behavior:auto!important} #atlas-conversation-workspace *{transition:none!important} #atlas-conversation-workspace .cw-header-caption{color:var(--cw-muted)} #atlas-conversation-workspace[data-terminal] .cw-wire-flash{visibility:hidden}`
document.head.append(style)

function stateAt(frame: number) {
  const index = [...timeline.events].reverse().find(event => event.frame <= frame && event.native_demo_index !== undefined)!.native_demo_index!
  // Keep event counts constant within a beat; continuous motion uses native timing below.
  const progress = index === 3 ? 1 : index === 12 ? Math.min(1, (frame - at(12)) / 12) : index === 10 ? .8 : .45
  const state = demoWorkspace(base, index, 'dark')
  // Open the existing graph toggle before filming, including the native empty state.
  state.graphOpen = true
  state.config.skill = frame < skillChosen ? 'auto' : 'product-comparison'
  state.inspectorOpen = frame >= firstClick
  // A user's inspected node stays selected while the remaining system stages finish.
  state.selectedNode = index === 3 ? 'clarify' : frame < firstClick ? 'a' : 'b'
  state.inspectorTab = frame >= tabClick ? 'events' : frame >= firstClick ? 'io' : 'overview'
  const thread = state.threads[0], run = thread.runs[0]
  const nodes = demoNodes(run, index, progress)
  const demo = {
    active: true, playing: true, reducedMotion: false, recording: undefined, manualMenu: false,
    index, progress, elapsed: demoStart(index) + (index === 12 ? progress : .45) * demoScenes[index].duration,
    scene: demoScenes[index], menu: frame >= menuOpen && frame < skillChosen ? 'skill' : null, currentNode: state.selectedNode,
    pause: noop, setMenu: (value: unknown) => callbackAudit.push({ type: 'menu', value }), replay: noop, seek: noop,
  }
  return { state, thread, run, nodes, demo, dispatch: recordDispatch, inspectNode: (id: string) => callbackAudit.push({ type: 'inspect', id }), isLive: false, live: {}, storageError: false } as unknown as WorkspaceController
}

function NativeScene({ frame }: { frame: number }) {
  const controller = stateAt(frame)
  return <div id="atlas-conversation-workspace" data-palette="apple" data-graph={controller.state.graphOpen ? 'open' : 'closed'} data-demo="playing" data-terminal={frame >= reportReady || undefined} aria-label="星图工作台 · Apple 银白">
    <Sidebar controller={controller} mobileOpen={false} onClose={noop}/>
    <main className="cw-main">
      <header className="cw-header"><div className="cw-header-title"><h1>{controller.thread.title}</h1><div className="cw-header-caption">星图工作台 · 演示数据</div></div><span className="cw-spacer"/><button className="cw-icon-button"><Icon name="light"/></button><button id="graph-toggle" className="cw-graph-toggle" aria-expanded={controller.state.graphOpen}><Icon name="panel"/>流程图</button></header>
      <div className="cw-workarea"><Conversation controller={controller}/><div className="cw-graph-slot">{controller.state.graphOpen && <Graph controller={controller}/>}</div></div>
    </main>
  </div>
}

function animationOrigin(animation: Animation, frame: number): number {
  const target = animation.effect instanceof KeyframeEffect ? animation.effect.target as Element : null
  const name = (animation as CSSAnimation).animationName
  if (!target) return 0
  if (target.classList.contains('cw-graph-panel')) return -30
  if (name === 'cw-menu-open') return menuOpen
  const node = target.closest('[data-flow-node]')?.getAttribute('data-flow-node')
  if (name === 'cw-wire-travel') {
    if (frame >= at(12)) return at(12)
    if (frame >= at(11)) return at(11)
    if (frame >= firstClick && !target.classList.contains('is-flowing')) return firstClick
    return frame < at(7) ? at(6) : at(7)
  }
  if (name === 'cw-breathe') return node === 'report' ? at(12) : node === 'brief' ? at(6) : at(7)
  if (name === 'cw-check-in') return node === 'clarify' ? at(6) : node === 'brief' ? at(7) : node === 'a' ? firstClick : node === 'b' ? tabClick : node === 'c' ? at(11) : node === 'supervisor' ? at(12) : reportReady
  if (target.closest('.cw-inspector-pane') || target.closest('.cw-event')) return frame >= tabClick ? tabClick : firstClick
  if (target.closest('.cw-inspector')) return firstClick
  if (target.closest('.cw-report-message')) return at(12)
  if (target.closest('.cw-activity')) return at(7)
  if (target.closest('.cw-brief')) return at(6)
  if (name === 'cw-panel-enter') return at(6)
  if (target.closest('.cw-user-message') || target.closest('.cw-agent-message')) return at(6)
  return 0
}

const nextPaint = () => new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
async function renderNativeFrame(frame: number) {
  flushSync(() => root.render(<NativeScene frame={frame}/>))
  await nextPaint()
  await document.fonts.ready
  document.querySelectorAll<HTMLElement>('#cw-skill-menu [role="menuitemradio"]').forEach((el, index) => { el.dataset.skillOption = skills[index].id })
  // Native components calculate SVG endpoints in their own unscaled iframe coordinates.
  const graph = document.querySelector<HTMLElement>('.cw-graph-panel')
  const messages = document.querySelector<HTMLElement>('.cw-messages')!
  messages.scrollTop = frame >= at(12) ? messages.scrollHeight : 0
  if (graph) graph.scrollTop = 0
  for (const animation of document.getAnimations()) {
    animation.pause()
    animation.currentTime = Math.max(0, (frame - animationOrigin(animation, frame)) / 30 * 1000)
  }
  await nextPaint()
  return {
    frame,
    states: stateAt(frame).nodes.map(n => ({ id: n.id, status: n.status })),
    text: document.body.innerText,
    wires: [...document.querySelectorAll('.cw-wire')].map(e => ({ d: e.getAttribute('d'), marker: e.getAttribute('marker-end'), loop: e.classList.contains('is-loop') })),
  }
}
function invokeNativeClick(selector: string) {
  const target = document.querySelector<HTMLElement>(selector)!
  if (!target) throw new Error(`Missing click target: ${selector}`)
  const box = target.getBoundingClientRect()
  const x = box.x + box.width * .55, y = box.y + box.height * .5
  const top = document.elementFromPoint(x, y)
  let opacity = 1
  for (let el: HTMLElement | null = target; el; el = el.parentElement) opacity *= Number(getComputedStyle(el).opacity)
  callbackAudit = []
  const result = { target: selector, bounds: box.toJSON(), nativeTip: [x,y], hit: !!top?.closest(selector), visible: opacity > .99, text: target.innerText }
  // Invoke the original component handler before deterministic frame state advances.
  // For a menu option, the visible target is measured before its native close action.
  target.click()
  if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
  return { ...result, callbacks: [...callbackAudit], phase: 'before-native-handler' }
}
Object.assign(window, { renderNativeFrame, invokeNativeClick, mediaData: { prompt: base.threads[0].runs[0].prompt, demoReply, demoReport, skills, scenes: demoScenes } })
;(window as any).nativeReady = renderNativeFrame(0)
