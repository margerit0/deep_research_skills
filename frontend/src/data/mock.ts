import example from './example-nodes.json'
import type { Config, NodeDetail, NodeStatus, Researcher, Run, SkillId, Workspace } from './schema'

export const models = [
  { id: 'qwen', label: 'Qwen3.5' },
  { id: 'deepseek', label: 'DeepSeek V3.2' },
  { id: 'gpt4o', label: 'GPT-4o' },
] as const
export const skills = [
  { id: 'auto', label: '自动选择', icon: 'sparkles', description: '按研究问题选择合适的方法论' },
  {
    id: 'product-comparison',
    label: '产品对比',
    icon: 'columns',
    description: '对齐候选产品的能力、差异与适用场景',
  },
  {
    id: 'academic-research',
    label: '学术研究',
    icon: 'book',
    description: '优先查找论文、综述与可追溯的学术证据',
  },
  {
    id: 'news-timeline',
    label: '事件时间线',
    icon: 'history',
    description: '按时间组织事件、关键进展与来源',
  },
  {
    id: 'people-research',
    label: '人物调研',
    icon: 'user',
    description: '整理人物履历、代表作与可核验的动态',
  },
] as const
export const modelName = (id: Config['model']) => models.find((m) => m.id === id)!.label
export const skillInfo = (id: SkillId) => skills.find((s) => s.id === id)!
export const statusText: Record<NodeStatus, string> = {
  pending: '待执行',
  waiting: '待补充',
  running: '执行中',
  completed: '已完成',
}
export const stageText = {
  clarify: '确认范围',
  research: '研究中',
  writing: '写作中',
  complete: '已完成',
}
export const phaseText = {
  clarify: '范围界定',
  research: '协作研究 · 第 2 轮',
  writing: '最终报告生成',
  complete: '本次研究已结束',
}
export const activityText = {
  clarify: '正在确认研究范围',
  research: '正在并行研究',
  writing: '正在撰写最终报告',
  complete: '研究已完成',
}
export const elapsed = { clarify: '00:03', research: '01:42', writing: '02:18', complete: '02:56' }
const exampleResearchers: Researcher[] = ['a', 'b', 'c'].map((id, i) => {
  const key = id as 'a' | 'b' | 'c'
  return {
    id,
    title: example.nodes[key].title,
    shortTitle: ['技术', '商业', '隐私'][i],
    task: example.nodes[key].description,
    icon: example.inspection[key].icon,
  }
})

export function createRun(prompt: string, config: Config): Run {
  const method = skillInfo(config.skill)
  // A local scenario with two workers also exercises data-driven graph layout.
  const researchers = [
    {
      id: 'evidence',
      title: '资料与证据',
      shortTitle: '证据',
      task: `围绕「${prompt}」收集资料。${method.description}。`,
      icon: 'book',
    },
    {
      id: 'review',
      title: '核验与分析',
      shortTitle: '核验',
      task: `围绕「${prompt}」交叉核验结论，记录差异与待确认问题。`,
      icon: 'shield-check',
    },
  ]
  return {
    id: crypto.randomUUID(),
    prompt,
    config: { ...config },
    stage: 'clarify',
    kind: 'custom',
    researchers,
  }
}

export function initialWorkspace(): Workspace {
  const run: Run = {
    id: 'example-run',
    kind: 'example',
    stage: 'research',
    config: { model: 'qwen', skill: 'auto' },
    prompt: '比较 AI 搜索产品的技术路线、商业模式和隐私风险，附可核验的来源。',
    researchers: exampleResearchers,
  }
  return {
    version: 1,
    config: { ...run.config },
    activeThreadId: 'example',
    theme: 'system',
    graphOpen: true,
    inspectorOpen: true,
    inspectorTab: 'overview',
    selectedNode: 'b',
    threads: [
      { id: 'example', title: 'AI 搜索的下一站', draft: '', runs: [run], selectedRunId: run.id },
    ],
  }
}

export function currentNode(run?: Run): string {
  if (!run || run.stage === 'clarify') return 'clarify'
  if (run.stage === 'research') return run.researchers[1]?.id ?? run.researchers[0].id
  return 'report'
}

export function nodeStatus(id: string, run?: Run): NodeStatus {
  if (!run) return 'pending'
  if (run.stage === 'clarify') return id === 'clarify' ? 'waiting' : 'pending'
  if (run.stage === 'complete') return 'completed'
  if (run.stage === 'writing') return id === 'report' ? 'running' : 'completed'
  if (['clarify', 'brief', run.researchers[0].id].includes(id)) return 'completed'
  return id === 'report' ? 'pending' : 'running'
}

interface FixtureDetail {
  id: string
  path: string
  icon: string
  duration: string
  doneDuration?: string
  countLabel: string
  count: string
  doneCount?: string
  input: string
  output: string
  doneOutput?: string
  events: string[][]
}

export function getNodes(run?: Run, statuses?: Record<string, NodeStatus>): NodeDetail[] {
  const workers = run?.researchers ?? []
  const titles = workers.map((w) => w.title).join(' / ')
  return ['clarify', 'brief', 'supervisor', ...workers.map((w) => w.id), 'report'].map((id) => {
    const worker = workers.find((w) => w.id === id)
    const index = workers.findIndex((w) => w.id === id)
    const key = id in example.nodes ? (id as keyof typeof example.nodes) : 'b'
    const base = example.nodes[key]
    const info: FixtureDetail = example.inspection[key]
    const status = statuses?.[id] ?? nodeStatus(id, run)
    const done = status === 'completed'
    const pending = status === 'pending'
    const isExample = run?.kind === 'example'
    const title = worker?.title ?? base.title
    const description = worker?.task ?? base.description
    const count = isExample
      ? done
        ? (info.doneCount ?? info.count)
        : info.count
      : worker
        ? `${index + 3} 条`
        : `${workers.length} ${{ supervisor: '位', report: '份', brief: '个', clarify: '项' }[id] ?? '项'}`
    const caption =
      status !== 'completed' && status !== 'running'
        ? statusText[status]
        : id === 'clarify'
          ? '已确认'
          : id === 'brief'
            ? '已生成'
            : id === 'supervisor'
              ? done
                ? '研究已汇总'
                : `已委派 ${workers.length} 个方向`
              : id === 'report'
                ? done
                  ? '报告已生成'
                  : '正在撰写'
                : done
                  ? '已完成'
                  : index === workers.length - 1 && isExample
                    ? '整理中'
                    : '检索中'
    let input = isExample
      ? info.input
      : worker
        ? `research_topic\n${worker.task}`
        : `${run?.prompt ?? '尚未提交研究问题。'}\n研究方向：${titles || '等待生成'}`
    if (id === 'clarify') input = `messages\n${run?.prompt ?? '尚未提交研究问题。'}`
    if (worker && !pending)
      input += `\nskill: ${run?.config.skill === 'auto' ? (isExample ? 'product-comparison（模拟自动选择）' : 'auto（模拟自动选择）') : run?.config.skill}`
    let output = isExample
      ? done
        ? (info.doneOutput ?? info.output)
        : info.output
      : worker
        ? `围绕「${run?.prompt}」的${title}\n${done ? 'compressed_research · 模拟笔记已返回协调器' : '正在收集示例资料，压缩笔记尚未生成'}`
        : id === 'report'
          ? done
            ? `final_report\n「${run?.prompt}」的演示报告已生成。`
            : '正在生成演示报告，尚未返回 final_report。'
          : id === 'supervisor'
            ? `${done ? '已汇总' : '已分配'} ${workers.length} 个研究方向\n${titles}`
            : `研究需求：${run?.prompt}\n研究方向：${titles}`
    let events: [string, string, string][] = isExample
      ? info.events.map((e) => [e[0], e[1], e[2]])
      : [
          ['00:03', '接收研究任务', run?.prompt ?? ''],
          ['00:12', worker ? 'load_skill → tavily_search' : base.tool, worker?.task ?? description],
        ]
    if (done && (!isExample || info.doneOutput)) {
      if (isExample && id === 'b')
        events[events.length - 1] = ['01:42', '检索已完成', '5 条来源已交叉核验']
      const time =
        id === 'report' ? '02:56' : id === 'clarify' ? '00:03' : id === 'brief' ? '00:09' : '02:18'
      events = [
        ...events,
        [
          time,
          worker ? 'compress_research' : '节点已完成',
          worker ? '模拟笔记已返回协调器' : '模拟输出已就绪',
        ],
      ]
    }
    if (pending) {
      output = '尚未执行，暂无输出。'
      events = []
      input = `预期输入\n${input}`
    }
    if (status === 'waiting') {
      output = '等待确认研究范围，尚未进入研究简报节点。'
      events = [
        ['00:00', '读取研究问题', run?.prompt ?? ''],
        ['00:03', '等待确认范围', '补充要求，或点击“演示下一步”确认范围'],
      ]
    }
    let tool = pending
      ? '尚未执行'
      : status === 'waiting'
        ? '等待补充研究范围'
        : worker && done
          ? 'compress_research · 已完成'
          : base.tool
    let query = pending
      ? '等待上游节点完成后开始。'
      : isExample
        ? done && worker
          ? `${count}来源 · 压缩笔记已返回协调器`
          : base.query
        : (worker?.task ?? titles)
    if (!pending && id === 'supervisor' && done) {
      tool = '研究汇总完成'
      query = `${workers.length} 份研究笔记已交给最终报告节点。`
    }
    if (!pending && id === 'report')
      query = done
        ? '演示报告已生成，包含模拟笔记汇总。'
        : `正在综合 ${workers.length} 份研究笔记，生成报告内容…`
    return {
      id,
      title,
      shortTitle: worker?.shortTitle ?? title,
      icon: worker?.icon ?? info.icon,
      path: worker ? `并行研究 / 研究员 ${String(index + 1).padStart(2, '0')}` : info.path,
      backendId: worker
        ? done
          ? 'researcher_agent_skills / compress_research'
          : isExample
            ? info.id
            : 'researcher_agent_skills / tool_node'
        : info.id,
      status,
      caption: id === 'report' && pending ? '等待研究汇总' : caption,
      description,
      duration: pending ? '—' : done ? (info.doneDuration ?? info.duration) : info.duration,
      countLabel: worker ? '来源' : info.countLabel,
      count: pending ? '—' : count,
      tool,
      query,
      input,
      output,
      events,
      researcher: Boolean(worker),
    }
  })
}
