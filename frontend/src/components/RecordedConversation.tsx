import { lazy, Suspense } from 'react'
import type { WorkspaceController } from '../state/useWorkspace'
import { liveStatusText, roleLabels, safeHttpUrl } from '../data/live'
import { Icon } from './Icon'

const ReportText = lazy(() => import('./ReportText'))

export function RecordedConversation({ controller }: { controller: WorkspaceController }) {
  const { demo, inspectNode } = controller
  const record = demo.recording!
  const run = demo.recordedRun!
  const ended = demo.scene.id === 'record-result'
  return (
    <section className="cw-conversation" aria-label="研究对话" data-recording={record.id}>
      <div className="cw-messages">
        <div className="cw-date">
          真实记录回放<span>·</span>
          <span>{record.date}</span>
        </div>
        <p className="cw-sync-note">来自真实调用的离线回放，播放时间已压缩。</p>
        <details className="cw-config-history">
          <summary>实测配置与记录</summary>
          {run.config.models.map((model) => (
            <p key={model.role}>
              {roleLabels[model.role] ?? model.role}：{model.model}
            </p>
          ))}
          <p>
            Skills：自动允许集合；成功加载{' '}
            {
              run.events.filter(
                (event) => event.kind === 'tool_finished' && event.tool === 'load_skill',
              ).length
            }{' '}
            次。
          </p>
          <p>
            整段记录：{record.runCount} 个 run · {record.modelHttpAttempts.length} 次模型 HTTP
            尝试。
          </p>
        </details>
        {run.messages.map((message, index) => (
          <article key={message.id ?? index} className="cw-message-pair">
            {message.type === 'human' ? (
              <div className="cw-user-message">
                <div className="cw-user-bubble">{message.content}</div>
              </div>
            ) : (
              <div className="cw-agent-message">
                <span className="cw-agent-icon">
                  <Icon name="asterisk" />
                </span>
                <div className="cw-agent-content">
                  <div className="cw-agent-name">Deep Research · 实录</div>
                  <Suspense fallback={<p data-recording-loading>{message.content}</p>}>
                    <ReportText>{message.content}</ReportText>
                  </Suspense>
                </div>
              </div>
            )}
          </article>
        ))}
        {run.brief && (
          <section className="cw-report-message" data-testid="recorded-brief">
            <h3>真实研究简报</h3>
            <p>{run.brief}</p>
          </section>
        )}
        {run.report && (
          <section className="cw-report-message" data-testid="recorded-report">
            <h3>真实检查点报告</h3>
            {record.acceptanceNotes && (
              <aside className="cw-sync-note" aria-label="实录验收说明">
                {record.acceptanceNotes.map((note) => (
                  <p key={note}>{note}</p>
                ))}
              </aside>
            )}
            <Suspense fallback={<p data-recording-loading>{run.report}</p>}>
              <ReportText>{run.report}</ReportText>
            </Suspense>
          </section>
        )}
        {!!run.sources.length && (
          <section className="cw-report-message" aria-label="实录检索来源">
            <h3>真实检索来源</h3>
            <ul>
              {run.sources.map((source) => (
                <li key={source.url}>
                  {safeHttpUrl(source.url) ? (
                    <a href={source.url} target="_blank" rel="noopener noreferrer">
                      {source.title || source.url}
                    </a>
                  ) : (
                    source.title
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
        {ended && (
          <div
            className="cw-connection-alert"
            role="status"
            data-testid="recorded-status"
            data-status={run.status}
          >
            <p>
              记录结束状态：
              {record.observationEnded ? '写作中断，尚未确认业务终态' : liveStatusText[run.status]}
            </p>
            {run.errors.map((error, index) => (
              <p key={index}>{error.message}</p>
            ))}
            {!run.report && (
              <p>本次未生成报告，检索来源 {run.sources.length} 条。未执行阶段不补充模拟结果。</p>
            )}
          </div>
        )}
        <button
          type="button"
          className="cw-open-graph"
          onClick={() => inspectNode(demo.currentNode)}
        >
          查看实际节点与记录 <Icon name="external" />
        </button>
      </div>
      <div className="cw-composer-wrap">
        <p className="cw-sync-note">只读回放 · 不重新调用模型或创建研究 · 退出后恢复原会话</p>
      </div>
    </section>
  )
}
