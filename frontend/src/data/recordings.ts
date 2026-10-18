import { liveResearchSchema, type LiveResearch } from './liveSchema'
import { getLiveNodes } from './live'
import type { Workspace } from './schema'

export interface PlaybackScene {
  id: string
  title: string
  detail: string
  duration: number
  target: 'composer' | 'message' | 'inspector' | 'graph' | 'report'
}

export const DEFAULT_RECORDING_ID = 'deepseek-p0'
type RawRecording =
  (typeof import('./recordings.json'))[number] | typeof import('./deepseek-p0-recording.json')
export type Recording = Omit<RawRecording, 'research'> & {
  research: LiveResearch
  runtimeNotes?: string[]
}
export async function loadRecordings(): Promise<Recording[]> {
  const [{ default: latest }, { default: history }] = await Promise.all([
    import('./deepseek-p0-recording.json'),
    import('./recordings.json'),
  ])
  return [latest, ...history].map((item) => ({
    ...item,
    research: liveResearchSchema.parse(item.research),
  }))
}

export function recordingScenes(record: Recording): PlaybackScene[] {
  const scenes: PlaybackScene[] = [
    {
      id: 'record-question',
      title: '实际提问',
      detail: '真实输入与当次模型配置',
      duration: 3500,
      target: 'message',
    },
    {
      id: 'record-clarification',
      title: '实际澄清',
      detail: '模型返回的澄清问题',
      duration: 5500,
      target: 'message',
    },
  ]
  if (record.research.turns.length > 1)
    scenes.push({
      id: 'record-answer',
      title: '实际补充范围',
      detail: '同一研究沿用受理配置',
      duration: 5500,
      target: 'message',
    })
  if (record.research.brief)
    scenes.push({
      id: 'record-brief',
      title: '实际研究简报',
      detail: '来自服务端检查点的简报正文',
      duration: 5500,
      target: 'inspector',
    })
  if (record.research.events.length)
    scenes.push({
      id: 'record-research',
      title: '实际研究事件',
      detail: '真实委派与工具事件，保留失败和缺失',
      duration: 6000,
      target: 'graph',
    })
  if (record.research.report)
    scenes.push({
      id: 'record-report',
      title: '实际报告与来源',
      detail: '保留模型报告原文与引用核验限制',
      duration: 8000,
      target: 'report',
    })
  scenes.push({
    id: 'record-result',
    title: '记录结束状态',
    detail:
      record.research.status === 'succeeded'
        ? '报告与来源来自实际检查点'
        : '保留实际失败或未完成状态；未执行阶段不补写',
    duration: 5000,
    target: record.research.report ? 'report' : 'inspector',
  })
  return scenes
}

export function recordingFrame(record: Recording, scene: string): LiveResearch {
  const original = record.research
  if (scene === 'record-result' || scene === 'record-report') return original
  const beforeAnswer = ['record-question', 'record-clarification'].includes(scene)
  const firstAnswer = original.messages.findIndex(
    (message, index) => index > 0 && message.type === 'human',
  )
  return {
    ...original,
    turns: beforeAnswer ? original.turns.slice(0, 1) : original.turns,
    messages:
      scene === 'record-question'
        ? original.messages.slice(0, 1)
        : beforeAnswer
          ? original.messages.slice(0, firstAnswer > 0 ? firstAnswer : undefined)
          : original.messages,
    status: scene === 'record-clarification' ? 'awaiting_input' : 'running',
    phase: beforeAnswer
      ? 'clarify'
      : ['record-brief', 'record-research'].includes(scene)
        ? 'research'
        : 'brief',
    brief: ['record-brief', 'record-research'].includes(scene) ? original.brief : '',
    report: '',
    notes: [],
    sources: [],
    errors: [],
    events: scene === 'record-research' ? original.events : [],
    execution: undefined,
    eventRecovery: undefined,
    observations: [],
  }
}

export function recordingWorkspace(
  base: Workspace,
  record: Recording,
  frame: LiveResearch,
  scene: string,
): Workspace {
  return {
    ...base,
    activeThreadId: 'tour',
    graphOpen: true,
    inspectorOpen: true,
    selectedNode:
      scene === 'record-brief'
        ? 'brief'
        : frame.phase === 'clarify'
          ? 'clarify'
          : frame.phase === 'brief'
            ? 'brief'
            : frame.phase === 'research'
              ? 'supervisor'
              : 'report',
    inspectorTab: 'overview',
    threads: [
      { id: 'tour', title: record.label, draft: '', runs: [], selectedRunId: null },
      ...base.threads,
    ],
  }
}

export function recordingNodes(record: Recording, frame: LiveResearch, scene: string) {
  const ended = scene === 'record-result'
  return getLiveNodes(frame).map((node) => {
    if (ended && record.observationEnded && node.status === 'running') {
      node = {
        ...node,
        caption: '记录结束时执行中',
        query: '专用后端已按保护期限退出；这是中断前的检查点状态。',
        output: frame.report || '中断前未保存报告正文。',
      }
    }
    const calls = record.modelHttpAttempts.filter((call) => call.node === node.backendId)
    if (!ended || !calls.length || node.status === 'pending') return node
    return {
      ...node,
      countLabel: 'HTTP 尝试',
      count: String(calls.length),
      events: calls.map((call): [string, string, string] => [
        new Date(call.startedAt).toLocaleTimeString('zh-CN', { hour12: false }),
        `模型请求 · ${call.responseFormat ?? '文本 / 工具'}`,
        `SDK 重试序号 ${call.sdkRetryCount ?? 0} · ${'headersSeconds' in call && call.headersSeconds != null ? `响应头 ${call.headersSeconds} s` : `${call.seconds ?? '—'} s`} · ${call.httpStatus ? `HTTP ${call.httpStatus}` : call.outcome === 'in_flight' ? '响应未记录' : '连接失败'}`,
      ]),
    }
  })
}
