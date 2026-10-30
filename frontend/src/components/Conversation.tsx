import { useEffect, useRef } from 'react'
import {
  activityText,
  currentNode,
  elapsed,
  getNodes,
  mockReport,
  modelName,
  skillInfo,
} from '../data/mock'
import type { WorkspaceController } from '../state/useWorkspace'
import { Icon } from './Icon'
import { StatusMark } from './StatusMark'
import { Composer } from './Composer'
import { demoReply, demoReport } from '../data/demo'
import { LazyReportCard } from './LazyReportCard'
import { LiveConversation } from './LiveConversation'
import { RecordedConversation } from './RecordedConversation'

export function Conversation({ controller }: { controller: WorkspaceController }) {
  return controller.demo.recording ? (
    <RecordedConversation controller={controller} />
  ) : controller.isLive ? (
    <LiveConversation controller={controller} />
  ) : (
    <MockConversation controller={controller} />
  )
}

function MockConversation({ controller }: { controller: WorkspaceController }) {
  const { thread, inspectNode, demo } = controller
  const end = useRef<HTMLDivElement>(null)
  const lastCount = useRef(thread.runs.length)
  useEffect(() => {
    if (thread.runs.length > lastCount.current) end.current?.scrollIntoView({ block: 'nearest' })
    lastCount.current = thread.runs.length
  }, [thread.runs.length])
  const streamProgress = demo.reducedMotion ? 1 : Math.min(1, demo.progress * 1.2)
  useEffect(() => {
    if (demo.active && demo.scene.id === 'writing') {
      const messages = end.current?.parentElement
      if (messages) messages.scrollTop = messages.scrollHeight
    }
  }, [demo.active, demo.scene.id, demo.progress])
  return (
    <section className="cw-conversation" aria-label="研究对话">
      <div className="cw-messages">
        <div className="cw-date">
          {demo.active ? '全流程演示' : thread.id === 'example' ? '示例对话' : '本地对话'}
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
                <p
                  className="cw-agent-text"
                  data-streaming={demo.active && demo.scene.id === 'reply' && streamProgress < 1}
                >
                  {demo.active
                    ? demoReply.slice(
                        0,
                        demo.scene.id === 'reply'
                          ? Math.ceil(streamProgress * demoReply.length)
                          : undefined,
                      )
                    : run.kind === 'example'
                      ? '我会从三个方向并行研究，再把证据整理成一份有来源的对比报告。'
                      : `已记录你的研究要求。本次使用${modelName(run.config.model)}与「${skillInfo(run.config.skill).label}」。请补充范围，或在图谱中推进本地演示。`}
                </p>
                {(!demo.active || demo.index >= 6) && (
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
                        {demo.active && demo.scene.id === 'brief'
                          ? '范围已确认 · 正在生成简报'
                          : run.stage === 'clarify'
                            ? '等待确认研究范围 · 查看预期输入'
                            : '研究范围已确认 · 查看简报'}
                      </span>
                    </span>
                    <span className="cw-spacer" />
                    <Icon name="next" />
                  </button>
                )}
                {(!demo.active || demo.index >= 7) && (
                  <div className="cw-activity">
                    <div className="cw-activity-title">
                      <Icon name="branch" />
                      <span>{activityText[run.stage]}</span>
                      <span className="cw-spacer" />
                      <span className="cw-tiny cw-muted cw-mono">
                        {demo.active ? `${Math.floor(demo.elapsed / 1000)} s` : elapsed[run.stage]}
                      </span>
                    </div>
                    <div className="cw-activity-rows">
                      {(demo.active ? controller.nodes : getNodes(run))
                        .filter((n) => n.researcher)
                        .map((node) => (
                          <div key={node.id} className="cw-activity-row" data-status={node.status}>
                            <StatusMark status={node.status} />
                            <span>{node.title}</span>
                            <span className="cw-activity-state">{node.caption}</span>
                            {demo.active && (
                              <span className="cw-worker-progress" aria-hidden="true">
                                <i
                                  style={{
                                    transform: `scaleX(${node.status === 'completed' ? 1 : Math.min(0.9, 0.1 + (demo.index - 7 + demo.progress) * 0.16)})`,
                                  }}
                                />
                              </span>
                            )}
                          </div>
                        ))}
                    </div>
                    <button
                      type="button"
                      className="cw-open-graph"
                      onClick={() =>
                        inspectNode(demo.active ? demo.currentNode : currentNode(run), run.id)
                      }
                    >
                      查看当前步骤
                      <Icon name="external" />
                    </button>
                  </div>
                )}
                {(run.stage === 'complete' || (demo.active && run.stage === 'writing')) && (
                  <LazyReportCard
                    markdown={
                      demo.active
                        ? demoReport.slice(
                            0,
                            run.stage === 'writing'
                              ? Math.ceil(streamProgress * demoReport.length)
                              : undefined,
                          )
                        : mockReport(run)
                    }
                    status={run.stage === 'writing' && streamProgress < 1 ? 'writing' : 'demo'}
                    topic={run.prompt}
                    lanes={run.researchers.length}
                    duration={
                      demo.active ? `${Math.floor(demo.elapsed / 1000)} 秒` : elapsed[run.stage]
                    }
                    model={modelName(run.config.model)}
                    disclaimer="这是本地报告占位内容。尚未检索真实来源，也未生成真实研究结论。"
                    className={demo.active ? 'cw-demo-report' : undefined}
                  />
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
