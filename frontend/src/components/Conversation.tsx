import { useEffect, useRef } from 'react'
import { activityText, currentNode, elapsed, getNodes, modelName, skillInfo } from '../data/mock'
import type { WorkspaceController } from '../state/useWorkspace'
import { Icon } from './Icon'
import { StatusMark } from './StatusMark'
import { Composer } from './Composer'

export function Conversation({ controller }: { controller: WorkspaceController }) {
  const { thread, inspectNode } = controller
  const end = useRef<HTMLDivElement>(null)
  const lastCount = useRef(thread.runs.length)
  useEffect(() => {
    if (thread.runs.length > lastCount.current) end.current?.scrollIntoView({ block: 'nearest' })
    lastCount.current = thread.runs.length
  }, [thread.runs.length])
  return (
    <section className="cw-conversation" aria-label="研究对话">
      <div className="cw-messages">
        <div className="cw-date">
          {thread.id === 'example' ? '示例对话' : '本地对话'}
          <span>·</span>
          <span>模拟数据</span>
        </div>
        {!thread.runs.length && (
          <div className="cw-empty">
            <span className="cw-empty-mark">
              <Icon name="sparkles" />
            </span>
            <h2>
              今天，想深入
              <br />
              了解什么？
            </h2>
            <p>选好模型与 Skills，开始一项研究。</p>
          </div>
        )}
        {thread.runs.map((run) => (
          <article key={run.id} className="cw-message-pair" data-run-id={run.id}>
            <div className="cw-user-message">
              <div className="cw-user-bubble">
                {run.kind === 'example' ? (
                  <>
                    比较 AI 搜索产品的技术路线、商业模式和隐私风险，
                    <span className="cw-keep-phrase">附可核验的来源。</span>
                  </>
                ) : (
                  run.prompt
                )}
              </div>
              <div className="cw-message-meta">
                {modelName(run.config.model)} · {skillInfo(run.config.skill).label}
                {run.config.skill === 'auto' && ' Skills'}
              </div>
            </div>
            <div className="cw-agent-message">
              <span className="cw-agent-icon">
                <Icon name="asterisk" />
              </span>
              <div className="cw-agent-content">
                <div className="cw-agent-name">Deep Research</div>
                <p className="cw-agent-text">
                  {run.kind === 'example'
                    ? '我会从三个方向并行研究，再把证据整理成一份有来源的对比报告。'
                    : `已记录你的研究要求。本次使用${modelName(run.config.model)}与「${skillInfo(run.config.skill).label}」。请补充范围，或在图谱中推进本地演示。`}
                </p>
                <button
                  type="button"
                  className="cw-brief cw-row"
                  onClick={() => inspectNode('brief', run.id)}
                >
                  <span className="cw-brief-icon">
                    <Icon name="file-text" />
                  </span>
                  <span>
                    <span className="cw-small cw-strong">研究简报</span>
                    <span className="cw-brief-foot">
                      {run.stage === 'clarify'
                        ? '等待确认研究范围 · 查看预期输入'
                        : '研究范围已确认 · 查看简报'}
                    </span>
                  </span>
                  <span className="cw-spacer" />
                  <Icon name="next" />
                </button>
                <div className="cw-activity">
                  <div className="cw-activity-title">
                    <Icon name="branch" />
                    <span>{activityText[run.stage]}</span>
                    <span className="cw-spacer" />
                    <span className="cw-tiny cw-muted cw-mono">{elapsed[run.stage]}</span>
                  </div>
                  <div className="cw-activity-rows">
                    {getNodes(run)
                      .filter((n) => n.researcher)
                      .map((node) => (
                        <div key={node.id} className="cw-activity-row" data-status={node.status}>
                          <StatusMark status={node.status} />
                          <span>{node.title}</span>
                          <span className="cw-activity-state">{node.caption}</span>
                        </div>
                      ))}
                  </div>
                  <button
                    type="button"
                    className="cw-open-graph"
                    onClick={() => inspectNode(currentNode(run), run.id)}
                  >
                    查看当前步骤
                    <Icon name="external" />
                  </button>
                </div>
                {run.stage === 'complete' && (
                  <div className="cw-report-message">
                    <div className="cw-row">
                      <Icon name="file-check-2" />
                      <span className="cw-strong">演示报告已生成</span>
                    </div>
                    <p className="cw-muted">研究主题：{run.prompt}</p>
                    <ul>
                      {run.researchers.map((w) => (
                        <li key={w.id}>{w.title}：模拟笔记已汇总。</li>
                      ))}
                    </ul>
                    <p className="cw-muted">
                      这是本地报告占位内容。尚未检索真实来源，也未生成真实研究结论。
                    </p>
                  </div>
                )}
              </div>
            </div>
          </article>
        ))}
        <div ref={end} />
      </div>
      <Composer controller={controller} />
    </section>
  )
}
