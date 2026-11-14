import { useRef } from 'react'
import type { WorkspaceController } from '../../state/useWorkspace'
import type { NodeDetail } from '../../data/schema'
import { currentWorkflowNode } from '../../data/workflowRuntime'
import { currentResearcherNode } from '../../data/researchEvents'
import { liveStatusText } from '../../data/live'
import { Icon } from '../Icon'
import { Inspector } from '../Inspector'
import { StatusMark } from '../StatusMark'
import './workflow-run.css'

export function WorkflowRunGraph({ controller }: { controller: WorkspaceController }) {
  const { state, dispatch, liveRun, thread, nodes, inspectNode, live } = controller
  const revision = liveRun?.workflow ?? thread.live!.workflow!
  const selected = nodes.find((node) => node.id === state.selectedNode) ?? nodes[0]
  const researchers = nodes.filter((node) => node.researcher)
  const panel = useRef<HTMLElement>(null)
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
                  <p>实际委派的研究员</p>
                  {researchers.length ? researchers.map(button) : <small>收到委派事件后展示</small>}
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
              (liveRun?.phase === 'research' ? currentResearcherNode(liveRun) : undefined) ??
              (liveRun ? currentWorkflowNode(liveRun) : 'prepare_research')
            inspectNode(id)
            panel.current
              ?.querySelector<HTMLElement>(`[data-flow-node="${CSS.escape(id)}"]`)
              ?.scrollIntoView({ block: 'nearest' })
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
            panel.current
              ?.querySelector<HTMLButtonElement>(`[data-flow-node="${CSS.escape(selected.id)}"]`)
              ?.focus({ preventScroll: true })
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
