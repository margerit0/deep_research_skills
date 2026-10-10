import { lazy, Suspense, useEffect, useRef } from 'react'
import type { WorkspaceController } from '../state/useWorkspace'
import { currentLiveNode, livePhaseText, liveStatusText, safeHttpUrl } from '../data/live'
import { Composer } from './Composer'
import { Icon } from './Icon'

const MarkdownReport = lazy(() => import('./ReportText'))

function ReportText({ children }: { children: string }) {
  return (
    <Suspense fallback={<p className="cw-muted">正在排版报告…</p>}>
      <MarkdownReport>{children}</MarkdownReport>
    </Suspense>
  )
}

export function LiveConversation({ controller }: { controller: WorkspaceController }) {
  const { thread, live, inspectNode } = controller
  const researches = thread.live?.researches ?? []
  const sync = live.sync[thread.id]
  const { connection } = live
  const end = useRef<HTMLDivElement>(null)
  const messageCount = researches.reduce((total, run) => total + run.messages.length, 0)
  const previousCount = useRef(messageCount)
  useEffect(() => {
    if (messageCount > previousCount.current) end.current?.scrollIntoView({ block: 'nearest' })
    previousCount.current = messageCount
  }, [messageCount])
  return (
    <section className="cw-conversation" aria-label="研究对话">
      <div className="cw-messages">
        <div className="cw-date">
          真实研究<span>·</span>
          <span>LangGraph</span>
        </div>
        {researches.length > 0 && (!sync || sync.state === 'loading') && (
          <p className="cw-sync-note" role="status">
            正在回读服务端状态…
          </p>
        )}
        {(connection.error || sync?.message) && (
          <div className="cw-connection-alert" role="status">
            <p>{sync?.message || connection.error}</p>
            <button
              type="button"
              className="cw-quiet"
              onClick={() => {
                void live.connect()
                void live.refresh(thread.id)
              }}
            >
              <Icon name="reset" />
              重新读取状态
            </button>
          </div>
        )}
        {!researches.length && (
          <div className="cw-empty">
            <span className="cw-empty-mark">
              <Icon name="sparkles" />
            </span>
            <h2>
              今天，想深入
              <br />
              了解什么？
            </h2>
            <p>输入问题，由研究助手确认范围、检索资料并生成报告。</p>
          </div>
        )}
        {researches.map((run) => (
          <article className="cw-message-pair" key={run.id} data-run-id={run.id} data-source="live">
            {run.messages.map((message) =>
              message.type === 'human' ? (
                <div className="cw-user-message" key={message.id}>
                  <div className="cw-user-bubble">{message.content}</div>
                  <div className="cw-message-meta">
                    {run.config.models.find((model) => model.role === 'RESEARCHER')?.model} · 自动
                    Skills
                  </div>
                </div>
              ) : (
                <div className="cw-agent-message" key={message.id}>
                  <span className="cw-agent-icon">
                    <Icon name="asterisk" />
                  </span>
                  <div className="cw-agent-content">
                    <div className="cw-agent-name">Deep Research</div>
                    <p className="cw-agent-text cw-live-text">{message.content}</p>
                  </div>
                </div>
              ),
            )}
            <div className="cw-agent-message">
              <span className="cw-agent-icon">
                <Icon name="asterisk" />
              </span>
              <div className="cw-agent-content">
                <div className="cw-activity" data-testid="live-status" data-status={run.status}>
                  <div className="cw-activity-title" role="status">
                    <Icon name="activity" />
                    <span>{liveStatusText[run.status]}</span>
                  </div>
                  <p className="cw-muted">
                    {run.status === 'awaiting_input'
                      ? '请在下方回答澄清问题，继续本轮研究。'
                      : run.turns.at(-1)?.transport === 'sending'
                        ? '正在提交研究问题…'
                        : livePhaseText[run.phase]}
                  </p>
                  <button
                    type="button"
                    className="cw-open-graph"
                    onClick={() => inspectNode(currentLiveNode(run), run.id)}
                  >
                    查看当前步骤
                    <Icon name="external" />
                  </button>
                </div>
                {run.brief && (
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
                      <span className="cw-brief-foot">研究范围已确认 · 查看实际简报</span>
                    </span>
                    <span className="cw-spacer" />
                    <Icon name="next" />
                  </button>
                )}
                {run.errors.length > 0 && (
                  <div className="cw-research-errors" role="status">
                    {run.errors.map((error, index) => (
                      <p key={`${error.code}-${index}`}>{error.message}</p>
                    ))}
                  </div>
                )}
                {run.report && (
                  <div className="cw-report-message" data-testid="live-report">
                    <div className="cw-row">
                      <Icon name="file-check-2" />
                      <span className="cw-strong">
                        {run.status === 'partial' ? '研究报告 · 部分完成' : '研究报告'}
                      </span>
                    </div>
                    <ReportText>{run.report}</ReportText>
                  </div>
                )}
                {run.status === 'partial' && !run.report && run.notes.length > 0 && (
                  <details className="cw-report-message" open>
                    <summary>已保留的研究笔记</summary>
                    <ReportText>{run.notes.join('\n\n---\n\n')}</ReportText>
                  </details>
                )}
                {run.sources.length > 0 && (
                  <section className="cw-sources" aria-label="检索来源">
                    <h3>检索来源 · {run.sources.length}</h3>
                    <p className="cw-muted">本轮搜索返回的来源；报告中的引用编号以报告正文为准。</p>
                    <ul>
                      {run.sources.map((source) => (
                        <li key={source.url}>
                          <a
                            href={safeHttpUrl(source.url)}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {source.title}
                          </a>
                          <span>{source.url}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
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
