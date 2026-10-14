import type { GraphValues, LiveResearch } from './liveSchema'
import { sameSelection } from './liveSchema'
import type { NodeDetail, NodeStatus } from './schema'
import type { ServerRun } from '../api/langgraph'
import { eventTimeline, getResearcherNodes, mergeResearchEvents } from './researchEvents'

export const liveStatusText = {
  running: '运行中',
  awaiting_input: '等待补充',
  succeeded: '研究完成',
  failed: '研究失败',
  partial: '部分完成',
}
export const livePhaseText = {
  clarify: '确认研究范围',
  brief: '生成研究简报',
  research: '研究与资料检索',
  writing: '撰写最终报告',
  complete: '本轮研究已结束',
}
export const roleLabels: Record<string, string> = {
  SCOPING: '范围与简报',
  SUPERVISOR: '研究协调',
  RESEARCHER: '研究员',
  SUMMARIZATION: '网页摘要',
  COMPRESSION: '笔记压缩',
  FINAL_REPORT: '最终报告',
}
export const currentLiveNode = (run?: LiveResearch) =>
  !run
    ? 'clarify'
    : {
        clarify: 'clarify',
        brief: 'brief',
        research: 'supervisor',
        writing: 'report',
        complete: 'report',
      }[run.phase]

export function safeHttpUrl(url: string): string | undefined {
  try {
    const parsed = new URL(url)
    if (['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password)
      return parsed.href
  } catch {
    /* Not a navigable source. */
  }
  return undefined
}

function textContent(content: unknown): string {
  if (typeof content === 'string') return content
  if (Array.isArray(content))
    return content
      .map((block) => (typeof block?.text === 'string' ? block.text : ''))
      .filter(Boolean)
      .join('\n')
  return ''
}

export function applySnapshot(
  run: LiveResearch,
  server: ServerRun,
  values: GraphValues,
  expectedAttemptId?: string,
): LiveResearch {
  const turn = run.turns.at(-1)!
  const matches =
    values.active_research_id === run.id &&
    values.active_turn_id === turn.id &&
    (!turn.selection || sameSelection(turn.selection, values.effective_config?.selection))
  const apiFailed = ['error', 'timeout', 'interrupted'].includes(server.status)
  const apiRunning = ['pending', 'running'].includes(server.status)
  const next = {
    ...run,
    turns: run.turns.map((t) =>
      t.id === turn.id ? { ...t, runId: server.run_id, transport: 'accepted' as const } : t,
    ),
  }
  if (matches) {
    next.config = values.effective_config ?? run.config
    next.phase = values.research_phase ?? run.phase
    next.brief = values.research_brief ?? ''
    next.notes = (values.notes ?? []).filter(
      (note) => note.trim() && !note.trimStart().startsWith('## 研究未完成'),
    )
    next.sources = (values.sources ?? []).filter((source) => safeHttpUrl(source.url))
    next.errors = values.research_errors ?? []
    next.events = mergeResearchEvents(run, values.research_events ?? [])
    const hasReportIdentity = !!(
      values.report_run_id ||
      values.report_turn_id ||
      values.report_attempt_id ||
      values.report_writing_attempt_id
    )
    const reportOwned =
      !hasReportIdentity ||
      (values.report_run_id === server.run_id &&
        values.report_turn_id === turn.id &&
        values.report_attempt_id ===
          (expectedAttemptId ?? run.execution?.attempt_id ?? server.run_id) &&
        !!values.report_writing_attempt_id)
    next.report =
      values.report_research_id === run.id &&
      reportOwned &&
      !apiRunning &&
      ['succeeded', 'partial'].includes(values.research_status ?? '')
        ? (values.final_report ?? '')
        : ''
    next.reportIdentity =
      next.report && hasReportIdentity
        ? {
            runId: values.report_run_id!,
            turnId: values.report_turn_id!,
            attemptId: values.report_attempt_id!,
            writingAttemptId: values.report_writing_attempt_id!,
          }
        : undefined
    const messages = (values.messages ?? []).flatMap((message, i) =>
      ['human', 'ai'].includes(message.type) && message.name !== 'final_report'
        ? [
            {
              id: message.id || `${run.id}-${i}`,
              type: message.type as 'human' | 'ai',
              content: textContent(message.content),
              name: message.name ?? undefined,
            },
          ]
        : [],
    )
    // The server owns assistant messages. Retain only a locally submitted human
    // message that has not reached the visible checkpoint yet.
    next.messages = [
      ...messages,
      ...run.messages.filter(
        (m) => m.type === 'human' && !messages.some((serverMessage) => serverMessage.id === m.id),
      ),
    ]
    next.status = apiRunning ? 'running' : (values.research_status ?? 'failed')
    if (next.status === 'succeeded' && !next.report.trim()) {
      next.status = next.notes.length ? 'partial' : 'failed'
      next.errors = [
        ...next.errors,
        {
          code: 'missing_report',
          message: '运行结束但未返回本轮报告。',
          node: 'final_report_generation',
        },
      ]
    }
    if (!apiRunning && next.status === 'running') {
      next.status = next.notes.length ? 'partial' : 'failed'
      next.errors = [
        ...next.errors,
        {
          code: 'incomplete_run',
          message: '运行已结束，但研究流程未完成。',
          node: currentLiveNode(next),
        },
      ]
    }
  }
  if (apiFailed) {
    next.status = matches && next.notes.length ? 'partial' : 'failed'
    next.report = ''
    next.errors = [
      ...next.errors,
      {
        code: `run_${server.status}`,
        message:
          server.status === 'timeout'
            ? '服务端运行超时。'
            : server.status === 'interrupted'
              ? '服务端运行已中断。'
              : '服务端运行失败，请检查后端日志。',
        node: currentLiveNode(next),
      },
    ]
  }
  if (!matches && !apiRunning && !apiFailed) {
    next.status = 'failed'
    next.report = ''
    next.errors = [
      {
        code: 'state_mismatch',
        message: '未读到本次提交对应的状态；旧研究结果不会用于本轮。请重新读取状态。',
        node: 'clarify_with_user',
      },
    ]
  }
  next.errors = next.errors.filter(
    (error, index, errors) =>
      errors.findIndex(
        (other) =>
          other.code === error.code && other.node === error.node && other.message === error.message,
      ) === index,
  )
  const observation = { at: new Date().toISOString(), phase: next.phase, status: next.status }
  if (
    run.observations.at(-1)?.phase !== next.phase ||
    run.observations.at(-1)?.status !== next.status
  )
    next.observations = [...run.observations, observation]
  return next
}

export function getLiveNodes(run?: LiveResearch): NodeDetail[] {
  const ids = ['clarify', 'brief', 'supervisor', 'report']
  const active = ids.indexOf(currentLiveNode(run))
  const titles = ['澄清需求', '研究简报', '研究协调器', '最终报告']
  const backendIds = [
    'clarify_with_user',
    'write_research_brief',
    'supervisor_subgraph',
    'final_report_generation',
  ]
  const mainNodes: NodeDetail[] = ids.map((id, index) => {
    let status: NodeStatus =
      !run || index > active ? 'pending' : index < active ? 'completed' : 'running'
    if (run?.status === 'awaiting_input' && index === 0) status = 'waiting'
    if (run?.status === 'succeeded') status = 'completed'
    if (run && ['failed', 'partial'].includes(run.status)) {
      if (index === active) status = run.status === 'failed' ? 'failed' : 'partial'
      if (run.errors.some((error) => [id, backendIds[index]].includes(error.node)))
        status = run.status === 'failed' ? 'failed' : 'partial'
    }
    const output =
      !run || status === 'pending'
        ? '尚未执行，暂无输出。'
        : id === 'clarify'
          ? run.messages
              .filter((m) => m.type === 'ai')
              .map((m) => m.content)
              .join('\n\n')
          : id === 'brief'
            ? run.brief
            : id === 'supervisor'
              ? run.notes.join('\n\n')
              : run.report
    return {
      id,
      title: titles[index],
      shortTitle: titles[index],
      icon: ['messages-square', 'file-text', 'network', 'file-check-2'][index],
      path: `research_agent_full / ${backendIds[index]}`,
      backendId: backendIds[index],
      status,
      caption: {
        pending: '待执行',
        waiting: '等待补充',
        running: '执行中',
        completed: '已完成',
        failed: '失败',
        partial: '部分完成',
      }[status],
      description: [
        '根据本轮对话确认研究范围，必要时等待补充回答。',
        '后端根据确认后的要求生成的实际研究简报。',
        '由后端协调研究员、自动加载 Skills 并检索资料。',
        '根据有效研究笔记撰写报告；结果归属于本轮研究。',
      ][index],
      duration: '—',
      countLabel: id === 'supervisor' || id === 'report' ? '检索来源' : '对话消息',
      count:
        run && status !== 'pending'
          ? String(
              id === 'supervisor' || id === 'report' ? run.sources.length : run.messages.length,
            )
          : '—',
      tool: status === 'pending' ? '等待开始' : titles[index],
      query:
        run?.errors
          .filter((error) => [id, backendIds[index]].includes(error.node))
          .map((error) => error.message)
          .join('\n') || '阶段状态来自服务端检查点。',
      input:
        !run || status === 'pending'
          ? '等待输入。'
          : id === 'clarify'
            ? run.turns.map((t) => t.text).join('\n\n')
            : id === 'brief'
              ? run.messages.map((m) => m.content).join('\n\n')
              : run.brief,
      output:
        output ||
        (status === 'failed' || status === 'partial'
          ? '本阶段未返回完整结果。'
          : '等待节点返回结果。'),
      events:
        id === 'supervisor' && run?.events.length
          ? eventTimeline(
              run.events.filter((event) =>
                ['delegated', 'completed', 'failed'].includes(event.kind),
              ),
            )
          : (run?.observations ?? [])
              .filter((event) => currentLiveNode({ ...run!, phase: event.phase }) === id)
              .map((event) => [
                new Date(event.at).toLocaleTimeString('zh-CN', { hour12: false }),
                `回读：${liveStatusText[event.status]}`,
                livePhaseText[event.phase],
              ]),
      researcher: false,
    }
  })
  return [...mainNodes.slice(0, 3), ...getResearcherNodes(run), mainNodes[3]]
}
