import type { LiveResearch, LiveThread, WorkflowStream } from './liveSchema'
import type { NodeDetail, NodeStatus } from './schema'
import { getResearcherNodes } from './researchEvents'
import { workflowNodeEventSchema } from './workflowSchema'
import type {
  WorkflowBinding,
  WorkflowNodeEvent,
  WorkflowRef,
  WorkflowRevision,
} from './workflowSchema'

export const sameWorkflowRef = (a?: WorkflowRef, b?: WorkflowRef) =>
  !!a && !!b && a.workflow_id === b.workflow_id && a.revision_id === b.revision_id

export function matchesWorkflowBinding(
  revision: WorkflowRevision | undefined,
  binding: WorkflowBinding | undefined,
  threadId: string,
) {
  if (!revision) return !binding
  return (
    !!binding &&
    binding.thread_id === threadId &&
    sameWorkflowRef(revision, binding.workflow_ref) &&
    revision.semantic_hash === binding.semantic_hash &&
    revision.compatibility.compiler_version === binding.compatibility.compiler_version &&
    revision.compatibility.node_registry_version === binding.compatibility.node_registry_version &&
    revision.compatibility.state_schema_version === binding.compatibility.state_schema_version &&
    revision.compatibility.graph_id === binding.compatibility.graph_id
  )
}

export const workflowNodeId = (id: string) =>
  (
    ({
      clarify: 'clarify_with_user',
      brief: 'write_research_brief',
      supervisor: 'supervisor_subgraph',
      report: 'final_report_generation',
    }) as Record<string, string>
  )[id] ?? id

export function workflowPath(revision: WorkflowRevision) {
  const { nodes, edges } = revision.document.definition
  const path = []
  const visited = new Set<string>()
  let node = nodes.find((item) => item.id === 'start')
  while (node && !visited.has(node.id)) {
    path.push(node)
    visited.add(node.id)
    const successor = edges.find((edge) => edge.source === node!.id)?.target
    node = nodes.find((item) => item.id === successor)
  }
  return path
}

export type WorkflowReplay = {
  journalId?: string
  sequence: number
  gap: boolean
  sealed: boolean
  reset?: boolean
  unconfirmedBefore: number
}

export function ownsWorkflowEvent(
  thread: LiveThread,
  research: LiveResearch,
  runId: string,
  event: WorkflowNodeEvent,
) {
  const revision = research.workflow
  const attempt = research.execution?.attempts.find((item) => item.run_id === runId)
  const node = revision?.document.definition.nodes.find((item) => item.id === event.node_id)
  return (
    !!revision &&
    !!attempt &&
    !!node &&
    !['start', 'end'].includes(node.type) &&
    event.thread_id === thread.threadId &&
    event.research_id === research.id &&
    event.turn_id === research.turns.at(-1)?.id &&
    event.run_id === runId &&
    event.attempt_id === attempt.attempt_id &&
    node.type === event.node_type &&
    sameWorkflowRef(revision, event.workflow_ref) &&
    event.semantic_hash === revision.semantic_hash
  )
}

export function savedWorkflowStream(thread: LiveThread, research: LiveResearch, runId: string) {
  const turn = research.turns.at(-1)!
  const attempt = research.execution?.attempts.find((item) => item.run_id === runId)
  return research.workflowStreams?.find(
    (stream) =>
      stream.serverUrl === thread.serverUrl &&
      stream.threadId === thread.threadId &&
      stream.researchId === research.id &&
      stream.turnId === turn.id &&
      stream.runId === runId &&
      stream.attemptId === attempt?.attempt_id,
  )
}

export function mergeWorkflowEvents(
  thread: LiveThread,
  research: LiveResearch,
  runId: string,
  incoming: WorkflowNodeEvent[],
  replay?: WorkflowReplay,
): WorkflowStream[] | undefined {
  const attempt = research.execution?.attempts.find((item) => item.run_id === runId)
  if (!research.workflow || !attempt) return research.workflowStreams
  const previous = savedWorkflowStream(thread, research, runId)
  const stream: WorkflowStream = previous
    ? structuredClone(previous)
    : {
        serverUrl: thread.serverUrl,
        threadId: thread.threadId,
        researchId: research.id,
        turnId: research.turns.at(-1)!.id,
        runId,
        attemptId: attempt.attempt_id,
        events: [],
        sequence: 0,
        gap: false,
        sealed: false,
        unconfirmedBefore: 0,
        conflicts: [],
      }
  const events = new Map<number, WorkflowNodeEvent>()
  const ids = new Map<string, number>()
  const conflicts = new Set(stream.conflicts)
  for (const value of [...stream.events, ...incoming]) {
    const parsed = workflowNodeEventSchema.safeParse(value)
    if (!parsed.success || !ownsWorkflowEvent(thread, research, runId, parsed.data)) continue
    const event = parsed.data
    const prior = events.get(event.sequence)
    const sameId = ids.get(event.id)
    if (prior && JSON.stringify(prior) !== JSON.stringify(event)) conflicts.add(event.sequence)
    if (sameId !== undefined && sameId !== event.sequence) {
      conflicts.add(sameId)
      conflicts.add(event.sequence)
    }
    if (!prior) events.set(event.sequence, event)
    ids.set(event.id, event.sequence)
  }
  stream.events = [...events.values()].sort((a, b) => a.sequence - b.sequence).slice(0, 100)
  stream.conflicts = [...conflicts].sort((a, b) => a - b)
  if (replay) {
    stream.sequence =
      !replay.reset && replay.journalId === stream.journalId
        ? Math.max(stream.sequence, replay.sequence)
        : replay.sequence
    stream.journalId = replay.journalId
    stream.gap ||= replay.gap || !!stream.conflicts.length
    stream.sealed = replay.sealed
    stream.unconfirmedBefore = Math.max(stream.unconfirmedBefore, replay.unconfirmedBefore)
  }
  return [...(research.workflowStreams ?? []).filter((item) => item !== previous), stream]
}

export function confirmedWorkflowEvents(research: LiveResearch) {
  const result: WorkflowNodeEvent[] = []
  if (!research.workflow) return result
  const path = workflowPath(research.workflow).filter(
    (node) => !['start', 'end'].includes(node.type),
  )
  for (const attempt of research.execution?.attempts ?? []) {
    const stream = research.workflowStreams?.find(
      (item) =>
        item.runId === attempt.run_id &&
        item.attemptId === attempt.attempt_id &&
        item.turnId === research.turns.at(-1)?.id,
    )
    if (!stream) continue
    const binding = research.execution?.workflow_binding
    if (!binding || stream.threadId !== binding.thread_id) continue
    const owner: LiveThread = {
      serverUrl: stream.serverUrl,
      threadId: binding.thread_id,
      researches: [],
    }
    let sequence = 1,
      active: string | undefined,
      previous: string | undefined,
      ended = false
    for (const event of stream.events) {
      if (
        !ownsWorkflowEvent(owner, research, attempt.run_id, event) ||
        event.sequence !== sequence ||
        stream.conflicts.includes(sequence) ||
        ended
      )
        break
      if (event.kind === 'started') {
        const previousIndex = path.findIndex((node) => node.id === previous)
        if (active || (previous && path[previousIndex + 1]?.id !== event.node_id)) break
        if (
          !previous &&
          (attempt.kind === 'submit'
            ? event.node_id !== 'prepare_research'
            : !['clarify_with_user', 'write_research_brief', 'final_report_generation'].includes(
                event.node_id,
              ))
        )
          break
        active = event.node_id
      } else {
        if (active !== event.node_id) break
        previous = active
        active = undefined
        ended = event.kind !== 'completed'
      }
      result.push(event)
      sequence++
    }
  }
  return result
}

export function currentWorkflowNode(research: LiveResearch) {
  return confirmedWorkflowEvents(research).at(-1)?.node_id ?? 'prepare_research'
}

const descriptions: Record<string, [string, string, string | undefined]> = {
  start: ['开始', 'play', undefined],
  prepare_research: ['研究初始化', 'compass', undefined],
  clarify_with_user: ['澄清需求', 'messages-square', 'SCOPING'],
  write_research_brief: ['研究简报', 'file-text', 'SCOPING'],
  optimize_plan: ['研究计划优化', 'sparkles', 'SCOPING'],
  supervisor_subgraph: ['研究协调子流程', 'network', 'SUPERVISOR'],
  organize_notes: ['材料整理', 'layers', 'COMPRESSION'],
  final_report_generation: ['最终报告', 'file-check-2', 'FINAL_REPORT'],
  end: ['结束', 'check', undefined],
}
const captions: Record<NodeStatus, string> = {
  pending: '待执行',
  waiting: '等待补充',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  partial: '部分完成',
}

export function getWorkflowNodes(
  research?: LiveResearch,
  revision = research?.workflow,
): NodeDetail[] {
  if (!revision) return []
  const events = research ? confirmedWorkflowEvents(research) : []
  const nodes: NodeDetail[] = workflowPath(revision).map((node) => {
    const info = descriptions[node.type] ?? [node.type, 'workflow', undefined]
    const label =
      revision.document.presentation.nodes.find((item) => item.node_id === node.id)?.label ||
      info[0]
    const observations = events.filter((event) => event.node_id === node.id)
    const last = observations.at(-1)
    let status: NodeStatus = !last
      ? 'pending'
      : last.kind === 'started'
        ? 'running'
        : last.kind === 'awaiting_input'
          ? 'waiting'
          : last.kind
    let caption: string | undefined
    if (
      status === 'running' &&
      research &&
      (research.status !== 'running' ||
        research.execution?.run_id !== last?.run_id ||
        research.workflowStreams?.some(
          (stream) => stream.runId === last?.run_id && stream.unconfirmedBefore >= last.sequence,
        ))
    ) {
      status = 'partial'
      caption = '执行中断 · 结果未确认'
    }
    if (node.id === 'start' && events.length) status = 'completed'
    if (
      node.id === 'end' &&
      research?.execution?.status === 'completed' &&
      events.some(
        (event) => event.node_id === 'final_report_generation' && event.kind === 'completed',
      )
    )
      status = 'completed'
    const output =
      node.type === 'clarify_with_user'
        ? research?.messages
            .filter((m) => m.type === 'ai')
            .map((m) => m.content)
            .join('\n\n')
        : ['write_research_brief', 'optimize_plan'].includes(node.type)
          ? research?.brief
          : node.type === 'organize_notes'
            ? research?.organizedNotes
            : node.type === 'supervisor_subgraph'
              ? research?.notes.join('\n\n')
              : node.type === 'final_report_generation'
                ? research?.report
                : undefined
    return {
      id: node.id,
      title: label,
      shortTitle: label,
      icon: info[1],
      backendId: node.id,
      path: `${revision.document.name} / v${revision.revision_number} / ${node.id}`,
      status,
      caption: caption ?? captions[status],
      modelRole: info[2],
      researcher: false,
      description: node.parameters.instructions || `${info[0]}。按此研究固定的发布版本执行。`,
      duration: last && last.kind !== 'started' ? `${(last.elapsed_ms / 1000).toFixed(1)} 秒` : '—',
      countLabel: '节点事件',
      count: String(observations.length),
      tool: info[0],
      query:
        research?.errors
          .filter((error) => error.node === node.id)
          .map((error) => error.message)
          .join('\n') || '状态来自已核对归属的节点事件与检查点。',
      input: research?.brief || research?.turns.at(-1)?.text || '等待研究问题。',
      output:
        status === 'pending'
          ? '尚未执行，暂无输出。'
          : output || (status === 'completed' ? '节点执行已确认。' : '等待可确认的节点结果。'),
      events: observations.map((event) => [
        new Date(event.at).toLocaleTimeString('zh-CN', { hour12: false }),
        event.kind === 'started'
          ? '开始执行'
          : event.kind === 'awaiting_input'
            ? '等待补充回答'
            : captions[event.kind],
        `${event.elapsed_ms} ms`,
      ]),
    }
  })
  return [...nodes, ...getResearcherNodes(research)]
}
