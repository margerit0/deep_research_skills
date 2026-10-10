import type { LiveResearch, ResearchEvent } from './liveSchema'
import type { NodeDetail, NodeStatus } from './schema'

const labels: Record<ResearchEvent['kind'], string> = {
  delegated: '收到研究任务',
  model_started: '研究模型调用中',
  model_finished: '研究模型已返回',
  model_failed: '研究模型调用失败',
  tool_started: '工具执行中',
  tool_finished: '工具已返回',
  tool_failed: '工具执行失败',
  compression_started: '正在压缩笔记',
  compression_finished: '笔记压缩已返回',
  compression_failed: '笔记压缩失败',
  completed: '研究任务完成',
  failed: '研究任务失败',
}
const tools: Record<string, string> = {
  tavily_search: 'Tavily 检索与摘要',
  load_skill: '加载 Skills',
  think_tool: '检查研究进度',
  unknown: '研究工具',
}

export function mergeResearchEvents(run: LiveResearch, incoming: ResearchEvent[]): ResearchEvent[] {
  const turnId = run.turns.at(-1)!.id
  const events = new Map<string, ResearchEvent>()
  for (const event of [...run.events, ...incoming]) {
    if (event.research_id === run.id && event.turn_id === turnId && !events.has(event.id))
      events.set(event.id, event)
  }
  return [...events.values()].sort((a, b) => a.sequence - b.sequence)
}

export function eventTimeline(events: ResearchEvent[]): [string, string, string][] {
  return events.map((event) => [
    new Date(event.at).toLocaleTimeString('zh-CN', { hour12: false }),
    labels[event.kind],
    [
      `第 ${event.round} 轮`,
      event.tool ? tools[event.tool] : '',
      event.query ?? event.topic ?? '',
      event.source_count === undefined ? '' : `${event.source_count} 个检索来源`,
    ]
      .filter(Boolean)
      .join(' · '),
  ])
}

export function getResearcherNodes(run?: LiveResearch): NodeDetail[] {
  if (!run) return []
  const tasks = new Map<string, ResearchEvent[]>()
  for (const event of mergeResearchEvents(run, [])) {
    const task = tasks.get(event.task_id) ?? []
    task.push(event)
    tasks.set(event.task_id, task)
  }
  return [...tasks.entries()].map(([id, events], index) => {
    const last = events.at(-1)!
    const topic = events.find((event) => event.topic)?.topic ?? '等待回读任务说明'
    const failed = last.kind === 'failed' || last.kind.endsWith('_failed')
    const completed = last.kind === 'completed'
    const stillResearching =
      run.status === 'running' && !['writing', 'complete'].includes(run.phase)
    const status: NodeStatus = completed
      ? 'completed'
      : failed
        ? 'failed'
        : stillResearching
          ? 'running'
          : 'partial'
    const caption = status === 'partial' ? '完成状态未确认' : labels[last.kind]
    const sourceEvents = events.filter((event) => event.sources?.length)
    const sources = new Map(
      sourceEvents.flatMap((event) =>
        event.sources!.map((source) => [source.url, source] as const),
      ),
    )
    const recent = [...events].reverse()
    const output = recent.find((event) => event.output)?.output
    const query = recent.find((event) => event.query)?.query
    const modelEvent = recent.find(
      (event) => event.kind.startsWith('model_') || event.kind.startsWith('compression_'),
    )
    return {
      id: `researcher-${id}`,
      title: `研究员 ${String(index + 1).padStart(2, '0')}`,
      shortTitle: topic.length > 18 ? `${topic.slice(0, 18)}…` : topic,
      icon: 'user',
      path: `research_agent_full / supervisor / 第 ${last.round} 轮`,
      backendId: `research_agent_skills / ${id}`,
      modelRole: modelEvent?.kind.startsWith('compression_') ? 'COMPRESSION' : 'RESEARCHER',
      status,
      caption: `第 ${last.round} 轮 · ${caption}`,
      description: `第 ${last.round} 轮实际委派的研究任务。进度与时间来自后端执行事件。`,
      duration: `${(last.elapsed_ms / 1000).toFixed(1)} s`,
      countLabel: '检索次数',
      count: String(
        events.filter((event) => event.kind === 'tool_finished' && event.tool === 'tavily_search')
          .length,
      ),
      tool: last.tool ? `${tools[last.tool]} · ${labels[last.kind]}` : labels[last.kind],
      query: failed ? '本任务未完成；其他任务的有效结果仍会保留。' : (query ?? topic),
      input: topic,
      output:
        output ??
        (sources.size
          ? `已返回的检索来源：\n${[...sources.values()].map((source) => `${source.title}\n${source.url}`).join('\n\n')}`
          : failed
            ? '任务未返回有效笔记。'
            : '等待研究任务返回笔记。'),
      events: eventTimeline(events),
      researcher: true,
    }
  })
}

export function currentResearcherNode(run?: LiveResearch): string | undefined {
  if (run?.phase !== 'research' || run.status !== 'running') return undefined
  return getResearcherNodes(run).find((node) => node.status === 'running')?.id
}
