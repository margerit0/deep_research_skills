import { useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { currentNode, phaseText, stageText } from '../data/mock'
import type { NodeDetail } from '../data/schema'
import type { WorkspaceController } from '../state/useWorkspace'
import { Icon } from './Icon'
import { Inspector } from './Inspector'
import { StatusMark } from './StatusMark'
import { currentLiveNode, livePhaseText, liveStatusText } from '../data/live'
import { currentResearcherNode } from '../data/researchEvents'

interface Wire {
  d: string
  active?: boolean
  loop?: boolean
  flowing?: boolean
}
export function Graph({ controller }: { controller: WorkspaceController }) {
  const { state, dispatch, run, inspectNode, nodes, demo, isLive, liveRun, live, thread } =
    controller
  const actualMode = isLive || Boolean(demo.recording)
  const recordedInterruption =
    Boolean(demo.recording?.observationEnded) && demo.scene.id === 'record-result'
  const flow = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLElement>(null)
  const [wires, setWires] = useState<Wire[]>([])
  const selected = nodes.find((n) => n.id === state.selectedNode) ?? nodes[0]
  const researchers = nodes.filter((n) => n.researcher)
  const researcherIds = researchers.map((n) => n.id).join(',')
  const runningIds = nodes
    .filter((n) => n.status === 'running')
    .map((n) => n.id)
    .join(',')
  const returning = demo.active && demo.scene.id === 'converge'
  useLayoutEffect(() => {
    const container = flow.current!
    function draw() {
      const box = container.getBoundingClientRect()
      const rect = (key: string) => {
        const r = container
          .querySelector<HTMLElement>(`[data-flow-node="${key}"]`)!
          .getBoundingClientRect()
        return { x: r.left - box.left, y: r.top - box.top, w: r.width, h: r.height }
      }
      const next: Wire[] = []
      const connect = (from: string, to: string, side = false) => {
        const a = rect(from),
          b = rect(to),
          x1 = a.x + a.w / 2,
          y1 = a.y + a.h + 1,
          x2 = b.x + b.w / 2,
          y2 = b.y - 4,
          middle = (y1 + y2) / 2
        next.push({
          d: side
            ? `M${a.x + a.w + 1} ${a.y + a.h / 2} H${b.x - 4}`
            : `M${x1} ${y1} C${x1} ${middle} ${x2} ${middle} ${x2} ${y2}`,
          active: to === selected.id,
          flowing: runningIds.split(',').includes(to) || (returning && to === 'join'),
        })
      }
      connect('clarify', 'brief', true)
      connect('brief', 'supervisor')
      if (researcherIds) {
        researcherIds.split(',').forEach((id) => {
          connect('supervisor', id)
          connect(id, 'join')
        })
        connect('join', 'report')
        const j = rect('join'),
          s = rect('supervisor'),
          first = rect(researcherIds.split(',')[0])
        next.push({
          d: `M${j.x} ${j.y + j.h / 2} H${first.x - 6} V${s.y + s.h / 2} H${s.x - 4}`,
          loop: true,
          flowing: returning,
        })
      } else connect('supervisor', 'report')
      setWires(next)
    }
    draw()
    const observer = new ResizeObserver(draw)
    observer.observe(container)
    return () => observer.disconnect()
  }, [researcherIds, selected.id, run?.stage, runningIds, returning])
  const closeInspector = () => {
    dispatch({ type: 'inspector', open: false })
    panel.current
      ?.querySelector<HTMLButtonElement>(`[data-flow-node="${selected.id}"]`)
      ?.focus({ preventScroll: true })
  }
  const nodeButton = (node: NodeDetail, variant = '') => (
    <button
      type="button"
      key={node.id}
      className={`cw-node ${variant}`}
      data-flow-node={node.id}
      data-status={node.status}
      aria-label={`${node.title}，${node.caption}，查看节点详情`}
      aria-pressed={node.id === selected.id}
      aria-expanded={node.id === selected.id && state.inspectorOpen}
      aria-controls="cw-inspector"
      title={actualMode && node.researcher ? node.input : undefined}
      onClick={() => inspectNode(node.id)}
    >
      {node.researcher ? (
        <>
          <span className="cw-row cw-between">
            <span className="cw-node-tag">
              研究员 {String(researchers.findIndex((n) => n.id === node.id) + 1).padStart(2, '0')}
            </span>
            <StatusMark key={node.status} status={node.status} />
          </span>
          <span className="cw-node-name">{node.shortTitle}</span>
        </>
      ) : (
        <span className="cw-row">
          {['supervisor', 'report'].includes(node.id) && <Icon name={node.icon} />}
          <span className="cw-node-name">{node.title}</span>
          <span className="cw-spacer" />
          <StatusMark key={node.status} status={node.status} />
        </span>
      )}
      <span className="cw-node-state">{node.caption}</span>
    </button>
  )
  return (
    <aside
      ref={panel}
      id="cw-graph-panel"
      className="cw-graph-panel"
      aria-label="运行图谱"
      data-recording-ended={recordedInterruption || undefined}
    >
      <div className="cw-graph-header">
        <Icon name="workflow" />
        <span>运行图谱</span>
        <span className="cw-spacer" />
        <span className="cw-label cw-status" role="status">
          {actualMode
            ? recordedInterruption
              ? '记录中断'
              : liveRun
                ? liveStatusText[liveRun.status]
                : '未开始'
            : demo.active && demo.scene.id === 'brief'
              ? '生成简报'
              : run
                ? stageText[run.stage]
                : '未开始'}
        </span>
        <button
          type="button"
          className="cw-icon-button"
          aria-label="收起流程图"
          onClick={() => {
            dispatch({ type: 'graph', open: false })
            document.getElementById('graph-toggle')?.focus()
          }}
        >
          <Icon name="x" />
        </button>
      </div>
      <div className="cw-graph-subheader">
        <span>
          {actualMode
            ? recordedInterruption
              ? '报告写作时中断 · 终态未确认'
              : liveRun
                ? livePhaseText[liveRun.phase]
                : '等待提交研究问题'
            : demo.active && run?.stage === 'research'
              ? '协作研究 · 并行演示'
              : run
                ? phaseText[run.stage]
                : '等待提交研究问题'}
        </span>
        <span
          title={
            isLive && live.eventConnections[thread.id] === 'retrying'
              ? '事件连接暂时中断，阶段状态仍会回读；不会重复提交研究。'
              : undefined
          }
        >
          {demo.recording
            ? '真实记录'
            : isLive
              ? liveRun?.status === 'running' && liveRun.config.research_events_version === 1
                ? {
                    connecting: '连接事件流',
                    live: '实时事件',
                    retrying: '事件重连中',
                    ended: '真实数据',
                  }[live.eventConnections[thread.id] ?? 'connecting']
                : '真实数据'
              : '演示数据'}
        </span>
      </div>
      <div ref={flow} className="cw-flow">
        <svg className="cw-wires" aria-hidden="true">
          <defs>
            {['base', 'active'].map((type) => (
              <marker
                key={type}
                id={`cw-arrow-${type}`}
                markerWidth="5"
                markerHeight="5"
                refX="4"
                refY="2.5"
                orient="auto"
              >
                <path
                  d="M0 0 L5 2.5 L0 5"
                  fill={`var(--cw-${type === 'active' ? 'accent' : 'edge'})`}
                />
              </marker>
            ))}
          </defs>
          {wires.map((wire, i) => (
            <path
              key={i}
              className={`cw-wire${wire.active ? ' is-active' : ''}${wire.loop ? ' is-loop' : ''}`}
              d={wire.d}
              markerEnd={`url(#cw-arrow-${wire.active ? 'active' : 'base'})`}
            />
          ))}
          {wires
            .filter((wire) => wire.flowing || wire.active)
            .map((wire, i) => (
              <path
                key={`${selected.id}-${run?.stage}-${i}`}
                className={`cw-wire-flash${wire.flowing ? ' is-flowing' : ''}`}
                d={wire.d}
                pathLength="100"
              />
            ))}
        </svg>
        <div className="cw-top-nodes">{nodes.slice(0, 2).map((n) => nodeButton(n))}</div>
        <div className="cw-cluster">
          <span className="cw-cluster-tag">
            {actualMode ? '协作研究 · 子流程' : '并行研究 · 子流程'}
          </span>
          {nodeButton(nodes[2], 'cw-supervisor')}
          {researchers.length ? (
            <>
              <div
                className="cw-forks"
                style={{ '--worker-columns': Math.min(researchers.length, 3) } as CSSProperties}
              >
                {researchers.map((n) => nodeButton(n, 'cw-fork'))}
              </div>
              <div className="cw-join" data-flow-node="join">
                返回协调器 · 按需继续研究
              </div>
            </>
          ) : (
            <div className="cw-await-workers">
              {demo.recording
                ? '当前章节没有实际委派记录'
                : isLive
                  ? '收到实际委派后展示研究员'
                  : '任务开始后展示研究员'}
            </div>
          )}
        </div>
        {nodeButton(nodes.at(-1)!, 'cw-report')}
      </div>
      <div className="cw-graph-controls">
        <button
          type="button"
          className="cw-quiet"
          onClick={() =>
            inspectNode(
              isLive
                ? (currentResearcherNode(liveRun) ?? currentLiveNode(liveRun))
                : demo.active
                  ? demo.currentNode
                  : currentNode(run),
            )
          }
        >
          <Icon name="locate" />
          定位当前
        </button>
        {isLive ? (
          <button
            type="button"
            className="cw-quiet"
            onClick={() => {
              void live.refresh(thread.id)
            }}
          >
            <Icon name="reset" />
            刷新状态
          </button>
        ) : demo.recording ? (
          <button
            type="button"
            className="cw-quiet"
            onClick={() =>
              demo.index === demo.scenes.length - 1 ? demo.replay() : demo.seek(demo.index + 1)
            }
          >
            <Icon name={demo.index === demo.scenes.length - 1 ? 'reset' : 'step'} />
            {demo.index === demo.scenes.length - 1 ? '从头回放' : '回放下一幕'}
          </button>
        ) : (
          <button
            type="button"
            className="cw-quiet"
            disabled={!run}
            onClick={() =>
              demo.active && run?.stage === 'complete'
                ? demo.replay()
                : dispatch({ type: 'advance' })
            }
          >
            <Icon name={run?.stage === 'complete' ? 'reset' : 'step'} />
            {run?.stage === 'complete' ? '重新演示' : '演示下一步'}
          </button>
        )}
      </div>
      {state.inspectorOpen ? (
        <Inspector controller={controller} node={selected} run={run} onClose={closeInspector} />
      ) : (
        <button
          type="button"
          className="cw-inspector-reopen"
          aria-expanded="false"
          aria-controls="cw-inspector"
          onClick={() => {
            dispatch({ type: 'inspector', open: true })
            requestAnimationFrame(() =>
              document.getElementById(`cw-tab-${state.inspectorTab}`)?.focus(),
            )
          }}
        >
          <span className="cw-row">
            <Icon name="inspector" />
            节点检查器
          </span>
          <span>点击节点查看详情</span>
        </button>
      )}
    </aside>
  )
}
