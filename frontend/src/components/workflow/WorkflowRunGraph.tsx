import { useId, useLayoutEffect, useRef, useState } from 'react'
import type { WorkspaceController } from '../../state/useWorkspace'
import type { NodeDetail } from '../../data/schema'
import { currentWorkflowNode } from '../../data/workflowRuntime'
import { liveStatusText } from '../../data/live'
import { Icon } from '../Icon'
import { Inspector } from '../Inspector'
import { StatusMark } from '../StatusMark'
import './workflow-run.css'

const RESEARCHERS_PER_GROUP = 20

export function WorkflowRunGraph({ controller }: { controller: WorkspaceController }) {
  const key = `${controller.thread.id}:${controller.liveRun?.turns.at(-1)?.id ?? ''}`
  return <WorkflowRunGraphForTurn key={key} controller={controller} />
}

function WorkflowRunGraphForTurn({ controller }: { controller: WorkspaceController }) {
  const { state, dispatch, liveRun, thread, nodes, inspectNode, live } = controller
  const revision = liveRun?.workflow ?? thread.live!.workflow!
  const selected = nodes.find((node) => node.id === state.selectedNode) ?? nodes[0]
  const researchers = nodes.filter((node) => node.researcher)
  const grouped = researchers.length > RESEARCHERS_PER_GROUP
  const [openGroup, setOpenGroup] = useState<number | null>(null)
  const groupId = useId()
  const panel = useRef<HTMLElement>(null)
  const pendingLocation = useRef<string | null>(null)
  const nodeButton = (id: string) =>
    panel.current?.querySelector<HTMLButtonElement>(`[data-flow-node="${CSS.escape(id)}"]`)
  const groupFor = (id: string) => {
    const index = grouped ? researchers.findIndex((node) => node.id === id) : -1
    return index < 0 ? null : Math.floor(index / RESEARCHERS_PER_GROUP)
  }
  useLayoutEffect(() => {
    if (pendingLocation.current === null) return
    // The active researcher may only have been mounted by this commit.
    const target = panel.current?.querySelector<HTMLButtonElement>(
      `[data-flow-node="${CSS.escape(pendingLocation.current)}"]`,
    )
    pendingLocation.current = null
    target?.scrollIntoView({ block: 'nearest' })
    target?.focus({ preventScroll: true })
  })
  if (!selected)
    return (
      <aside className="cw-graph-panel" role="alert">
        无法解析此研究的原发布流程，请重新读取版本。
      </aside>
    )
  const button = (node: NodeDetail) => (
    <button
      type="button"
      className="cw-node"
      key={node.id}
      data-flow-node={node.id}
      data-status={node.status}
      aria-pressed={selected.id === node.id}
      aria-expanded={selected.id === node.id && state.inspectorOpen}
      aria-controls="cw-inspector"
      aria-label={`${node.title}，${node.caption}，查看节点详情`}
      onClick={() => inspectNode(node.id)}
    >
      <span className="cw-row">
        <Icon name={node.icon} />
        <span className="cw-node-name">{node.title}</span>
        <span className="cw-spacer" />
        <StatusMark status={node.status} />
      </span>
      <span className="cw-node-state">{node.caption}</span>
    </button>
  )
  const researcherGroups = () =>
    Array.from({ length: Math.ceil(researchers.length / RESEARCHERS_PER_GROUP) }, (_, group) => {
      const first = group * RESEARCHERS_PER_GROUP
      const end = Math.min(first + RESEARCHERS_PER_GROUP, researchers.length)
      const expanded = openGroup === group
      const target = `${groupId}-${group}`
      return (
        <div className="cw-workflow-researcher-group" key={group}>
          <button
            type="button"
            className="cw-quiet"
            data-researcher-group={group}
            aria-expanded={expanded}
            aria-controls={target}
            onClick={() => setOpenGroup(expanded ? null : group)}
          >
            研究员 {first + 1}–{end}
            <span aria-hidden="true">{expanded ? '−' : '+'}</span>
          </button>
          <div id={target} hidden={!expanded}>
            {expanded && researchers.slice(first, end).map(button)}
          </div>
        </div>
      )
    })
  return (
    <aside id="cw-graph-panel" ref={panel} className="cw-graph-panel" aria-label="运行图谱">
      <div className="cw-graph-header">
        <Icon name="workflow" />
        <span>运行图谱</span>
        <span className="cw-spacer" />
        <span className="cw-label" role="status">
          {liveRun ? liveStatusText[liveRun.status] : '未开始'}
        </span>
        <button
          type="button"
          className="cw-icon-button"
          aria-label="收起流程图"
          onClick={() => dispatch({ type: 'graph', open: false })}
        >
          <Icon name="x" />
        </button>
      </div>
      <div className="cw-workflow-version">
        <span>
          {revision.document.name} · v{revision.revision_number}
        </span>
        <a
          href={`#workflows/${encodeURIComponent(revision.workflow_id)}/revisions/${encodeURIComponent(revision.revision_id)}`}
        >
          查看发布版本
        </a>
        <small>此会话固定使用该版本 · 运行观察</small>
      </div>
      {live.workflowReplayStates[thread.id]?.state === 'retrying' && (
        <p className="cw-workflow-observation" role="status">
          节点记录正在重新连接，已保留确认过的状态。
        </p>
      )}
      <div className="cw-workflow-chain" aria-label="已发布流程的运行节点">
        {nodes
          .filter((node) => !node.researcher)
          .map((node) => (
            <div className="cw-workflow-step" key={node.id}>
              {button(node)}
              {node.backendId === 'supervisor_subgraph' && (
                <div className="cw-workflow-researchers" aria-label="动态研究员">
                  <p>实际委派的研究员{grouped ? ` · ${researchers.length} 个任务` : ''}</p>
                  {grouped ? (
                    researcherGroups()
                  ) : researchers.length ? (
                    researchers.map(button)
                  ) : (
                    <small>收到委派事件后展示</small>
                  )}
                </div>
              )}
            </div>
          ))}
      </div>
      <div className="cw-graph-controls">
        <button
          type="button"
          className="cw-quiet"
          disabled={!liveRun}
          onClick={() => {
            const id =
              (liveRun?.phase === 'research' && liveRun.status === 'running'
                ? researchers.find((node) => node.status === 'running')?.id
                : undefined) ?? (liveRun ? currentWorkflowNode(liveRun) : 'prepare_research')
            const group = groupFor(id)
            if (group !== null) setOpenGroup(group)
            pendingLocation.current = id
            inspectNode(id)
          }}
        >
          <Icon name="locate" />
          定位当前
        </button>
        <button type="button" className="cw-quiet" onClick={() => void live.refresh(thread.id)}>
          <Icon name="reset" />
          刷新状态
        </button>
      </div>
      {state.inspectorOpen ? (
        <Inspector
          controller={controller}
          node={selected}
          onClose={() => {
            dispatch({ type: 'inspector', open: false })
            const group = groupFor(selected.id)
            const target =
              nodeButton(selected.id) ??
              panel.current?.querySelector<HTMLButtonElement>(`[data-researcher-group="${group}"]`)
            target?.focus({ preventScroll: true })
          }}
        />
      ) : (
        <button
          type="button"
          className="cw-inspector-reopen"
          onClick={() => dispatch({ type: 'inspector', open: true })}
        >
          <Icon name="inspector" />
          节点检查器
        </button>
      )}
    </aside>
  )
}
