import { useRef } from 'react'
import type { InspectorTab, NodeDetail, Run } from '../data/schema'
import { modelName, statusText } from '../data/mock'
import type { WorkspaceController } from '../state/useWorkspace'
import { Icon } from './Icon'

const tabs: { id: InspectorTab; label: string }[] = [
  { id: 'overview', label: '概览' },
  { id: 'io', label: '输入 / 输出' },
  { id: 'events', label: '执行记录' },
]
export function Inspector({
  controller,
  node,
  run,
  onClose,
}: {
  controller: WorkspaceController
  node: NodeDetail
  run?: Run
  onClose: () => void
}) {
  const { state, dispatch, isLive, liveRun } = controller
  const role =
    node.modelRole ??
    (
      {
        clarify: 'SCOPING',
        brief: 'SCOPING',
        supervisor: 'SUPERVISOR',
        report: 'FINAL_REPORT',
      } as Record<string, string>
    )[node.id]
  const actualModel = liveRun?.config.models.find((model) => model.role === role)?.model ?? '待执行'
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])
  const pending = node.status === 'pending'
  return (
    <section
      id="cw-inspector"
      className="cw-inspector"
      data-status={node.status}
      data-live={isLive || undefined}
      aria-label="节点检查器"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault()
          onClose()
        }
      }}
    >
      <div className="cw-inspector-heading">
        <Icon name="inspector" />
        <span>节点检查器</span>
        <span className="cw-spacer" />
        <span className="cw-detail-status">{statusText[node.status]}</span>
        <button
          type="button"
          className="cw-icon-button"
          aria-label="收起节点检查器"
          onClick={onClose}
        >
          <Icon name="x" />
        </button>
      </div>
      <div className="cw-inspector-title">
        <span className="cw-inspector-symbol">
          <Icon name={node.icon} />
        </span>
        <div>
          <h2>{node.title}</h2>
          <div className="cw-detail-path">{node.path}</div>
        </div>
      </div>
      <div className="cw-inspector-tabs" role="tablist" aria-label="节点详情视图">
        {tabs.map((tab, i) => (
          <button
            key={tab.id}
            ref={(el) => {
              tabRefs.current[i] = el
            }}
            type="button"
            role="tab"
            id={`cw-tab-${tab.id}`}
            className="cw-inspector-tab"
            aria-selected={state.inspectorTab === tab.id}
            aria-controls={`cw-pane-${tab.id}`}
            tabIndex={state.inspectorTab === tab.id ? 0 : -1}
            onClick={() => dispatch({ type: 'tab', tab: tab.id })}
            onKeyDown={(e) => {
              if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return
              e.preventDefault()
              const next =
                e.key === 'Home'
                  ? 0
                  : e.key === 'End'
                    ? 2
                    : (i + (e.key === 'ArrowRight' ? 1 : -1) + 3) % 3
              dispatch({ type: 'tab', tab: tabs[next].id })
              tabRefs.current[next]?.focus()
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div
        key={`${node.id}-${state.inspectorTab}-overview`}
        role="tabpanel"
        id="cw-pane-overview"
        aria-labelledby="cw-tab-overview"
        className="cw-inspector-pane"
        hidden={state.inspectorTab !== 'overview'}
        tabIndex={0}
      >
        <p className="cw-detail-description">{node.description}</p>
        <dl className="cw-detail-stats">
          <div>
            <dt>执行模型</dt>
            <dd
              title={isLive ? actualModel : run ? modelName(run.config.model) : '待执行'}
              data-testid="run-model"
            >
              {isLive
                ? pending
                  ? '待执行'
                  : actualModel
                : pending || !run
                  ? '待执行'
                  : modelName(run.config.model)}
            </dd>
          </div>
          <div>
            <dt>已用时</dt>
            <dd>{node.duration}</dd>
          </div>
          <div>
            <dt>{node.countLabel}</dt>
            <dd>{node.count}</dd>
          </div>
        </dl>
        <div className="cw-current-step">
          <div className="cw-detail-tool">
            <Icon name="activity" />
            {node.tool}
          </div>
          <div className="cw-query">{node.query}</div>
        </div>
        {node.researcher && (
          <div className="cw-detail-loop">
            <span>模型</span>
            <Icon name="right" />
            <span>工具</span>
            <Icon name="undo" />
            <span>模型</span>
            <Icon name="right" />
            <span>压缩笔记</span>
          </div>
        )}
      </div>
      <div
        key={`${node.id}-${state.inspectorTab}-io`}
        role="tabpanel"
        id="cw-pane-io"
        aria-labelledby="cw-tab-io"
        className="cw-inspector-pane"
        hidden={state.inspectorTab !== 'io'}
        tabIndex={0}
      >
        <code className="cw-node-id">{node.backendId}</code>
        <div className="cw-payload-label">
          <Icon name="down" />
          输入
          <span className="cw-spacer" />
          <span>{pending ? '等待输入' : '本次任务'}</span>
        </div>
        <pre className="cw-payload">{node.input}</pre>
        <div className="cw-payload-label">
          <Icon name="output" />
          输出
          <span className="cw-spacer" />
          <span>{pending ? '待执行' : node.status === 'completed' ? '已返回' : '处理中'}</span>
        </div>
        <pre className="cw-payload" data-testid="node-output">
          {node.output}
        </pre>
      </div>
      <div
        key={`${node.id}-${state.inspectorTab}-events`}
        role="tabpanel"
        id="cw-pane-events"
        aria-labelledby="cw-tab-events"
        className="cw-inspector-pane"
        hidden={state.inspectorTab !== 'events'}
        tabIndex={0}
      >
        {node.events.length ? (
          <ol className="cw-event-list" aria-label="节点执行时间线">
            {node.events.map((event, i) => (
              <li
                key={i}
                className="cw-event"
                data-current={i === node.events.length - 1 && node.status !== 'completed'}
              >
                <span className="cw-event-time">{event[0]}</span>
                <span className="cw-event-dot" aria-hidden="true" />
                <div>
                  <div className="cw-event-name">{event[1]}</div>
                  <div className="cw-event-description">{event[2]}</div>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <div className="cw-inspector-empty">
            {isLive ? '暂无该节点的执行记录。' : '等待该节点开始执行。'}
          </div>
        )}
      </div>
    </section>
  )
}
