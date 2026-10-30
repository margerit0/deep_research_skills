import { getNodes, initialWorkspace } from './mock'
import type { InspectorTab, NodeStatus, Run, Workspace } from './schema'

// A deterministic, disposable playback view. Nothing here is persisted as a real run.
export const demoScenes = [
  {
    id: 'welcome',
    title: '从一个问题开始',
    detail: '银白玻璃、边缘反光与轻盈入场',
    duration: 3000,
    target: 'composer',
  },
  {
    id: 'model',
    title: '选择研究模型',
    detail: '展开紧凑模型菜单，保留本次配置',
    duration: 2500,
    target: 'composer',
  },
  {
    id: 'skill',
    title: '选择研究方法',
    detail: '展开 Skills 菜单，启用产品对比',
    duration: 2500,
    target: 'composer',
  },
  {
    id: 'prompt',
    title: '输入研究问题',
    detail: '模拟输入，然后发送到研究对话',
    duration: 4000,
    target: 'composer',
  },
  {
    id: 'reply',
    title: '研究助手回应',
    detail: '消息入场与逐字回复',
    duration: 4500,
    target: 'message',
  },
  {
    id: 'scope',
    title: '确认研究范围',
    detail: '明确技术、商业与隐私三个方向',
    duration: 3000,
    target: 'inspector',
  },
  {
    id: 'brief',
    title: '生成研究简报',
    detail: '范围确认，简报节点开始工作',
    duration: 3500,
    target: 'graph',
  },
  {
    id: 'dispatch',
    title: '分配并行任务',
    detail: '连线流动，三个研究员同时启动',
    duration: 3500,
    target: 'graph',
  },
  {
    id: 'search',
    title: '并行检索资料',
    detail: '研究员脉冲、进度推进与证据到达',
    duration: 5000,
    target: 'graph',
  },
  {
    id: 'evidence',
    title: '检查输入与输出',
    detail: '查看当前研究员的任务与模拟证据',
    duration: 3500,
    target: 'inspector',
  },
  {
    id: 'events',
    title: '跟随执行记录',
    detail: '检索、核验与压缩笔记依次出现',
    duration: 4000,
    target: 'inspector',
  },
  {
    id: 'converge',
    title: '汇总研究笔记',
    detail: '各方向完成，证据沿连线返回协调器',
    duration: 3500,
    target: 'graph',
  },
  {
    id: 'writing',
    title: '撰写研究报告',
    detail: '报告逐字生成，保留清晰的阅读节奏',
    duration: 7000,
    target: 'report',
  },
  {
    id: 'complete',
    title: '报告已就绪',
    detail: '完成状态与报告卡片呈现',
    duration: 3500,
    target: 'report',
  },
  {
    id: 'collapse',
    title: '专注阅读',
    detail: '收起图谱，对话平滑居中',
    duration: 3000,
    target: 'report',
  },
  {
    id: 'expand',
    title: '回到研究全貌',
    detail: '展开图谱，保留可独立收起的节点检查器',
    duration: 3000,
    target: 'graph',
  },
  {
    id: 'appearance',
    title: '另一种光线',
    detail: '体验另一种外观下的玻璃与反光',
    duration: 3500,
    target: 'inspector',
  },
  {
    id: 'finish',
    title: '全流程演示完成',
    detail: '可以重播，或退出回到原来的研究',
    duration: 2000,
    target: 'report',
  },
] as const

export interface DemoScene {
  id: string
  title: string
  detail: string
  duration: number
  target: 'composer' | 'message' | 'inspector' | 'graph' | 'report'
}
export const demoDuration = demoScenes.reduce((sum, scene) => sum + scene.duration, 0)
export const demoStart = (index: number, scenes: readonly DemoScene[] = demoScenes) =>
  scenes.slice(0, index).reduce((sum, scene) => sum + scene.duration, 0)
export function demoPosition(elapsed: number, scenes: readonly DemoScene[] = demoScenes) {
  let start = 0
  for (let index = 0; index < scenes.length; index++) {
    const scene = scenes[index]
    if (elapsed < start + scene.duration || index === scenes.length - 1)
      return { index, scene, progress: Math.min(1, (elapsed - start) / scene.duration) }
    start += scene.duration
  }
  throw new Error('Demo has no scenes')
}

export const demoReply =
  '我会从技术路线、商业模式和隐私风险三个方向并行研究。先确认比较范围，再核验资料、汇总证据，最后整理成一份便于阅读的对比报告。'
export const demoReport =
  '# 研究摘要（模拟）\n\n## 技术路线\n\n围绕检索、生成与引用追溯建立统一比较维度，记录各项能力需要核验的证据。\n\n## 商业模式\n\n按免费入口、订阅服务与企业场景整理分析框架，标记价格与服务条款的核验位置。\n\n## 隐私风险\n\n将数据收集、保留期限和用户控制列为审查项目，区分已确认信息与待验证问题。\n\n## 下一步\n\n接入真实检索后逐项补充来源，交叉核验，再形成结论。此处仅演示报告呈现，不含真实产品评价。'

export function demoWorkspace(
  base: Workspace,
  index: number,
  alternateTheme: 'light' | 'dark',
): Workspace {
  const example = initialWorkspace().threads[0].runs[0]
  const run: Run = {
    ...example,
    id: 'tour-run',
    config: { model: base.config.model, skill: 'product-comparison' },
    stage: index < 7 ? 'clarify' : index < 12 ? 'research' : index === 12 ? 'writing' : 'complete',
  }
  const nodes = [
    'clarify',
    'clarify',
    'clarify',
    'clarify',
    'clarify',
    'clarify',
    'brief',
    'supervisor',
    'a',
    'b',
    'b',
    'supervisor',
    'report',
    'report',
    'report',
    'report',
    'report',
    'report',
  ]
  const tab: InspectorTab = index === 9 ? 'io' : index === 10 ? 'events' : 'overview'
  return {
    ...base,
    activeThreadId: 'tour',
    threads: [
      {
        id: 'tour',
        title: 'AI 搜索 · 全流程演示',
        draft: '',
        runs: index < 4 ? [] : [run],
        selectedRunId: index < 4 ? null : run.id,
      },
      ...base.threads,
    ],
    config: { ...run.config, skill: index < 2 ? 'auto' : 'product-comparison' },
    theme: index === 16 ? alternateTheme : base.theme,
    graphOpen: index >= 5 && index !== 14,
    inspectorOpen: index >= 5 && index !== 15,
    inspectorTab: tab,
    selectedNode: nodes[index],
  }
}

export function demoNodes(run: Run | undefined, index: number, progress: number) {
  const statuses: Record<string, NodeStatus> = {
    clarify: index < 6 ? 'waiting' : 'completed',
    brief: index < 6 ? 'pending' : index === 6 ? 'running' : 'completed',
    supervisor: index < 7 ? 'pending' : index < 12 ? 'running' : 'completed',
    a: index < 7 ? 'pending' : index < 9 ? 'running' : 'completed',
    b:
      index < 7
        ? 'pending'
        : index < 10 || (index === 10 && progress < 0.75)
          ? 'running'
          : 'completed',
    c: index < 7 ? 'pending' : index < 11 ? 'running' : 'completed',
    report: index < 12 ? 'pending' : index === 12 ? 'running' : 'completed',
  }
  return getNodes(run, run ? statuses : undefined).map((node) => {
    if (node.status === 'pending' || !run) return node
    if (node.id === 'clarify')
      return {
        ...node,
        events: [
          ['00:00', '读取研究问题', run.prompt],
          ['00:03', index < 6 ? '确认比较范围' : '范围已确认', '技术路线、商业模式、隐私风险'],
        ] as [string, string, string][],
      }
    if (node.id === 'brief' && index === 6)
      return {
        ...node,
        caption: '生成中',
        tool: '整理研究简报',
        query: '正在将三个比较维度整理为研究任务。',
        output: '正在整理研究范围与比较维度…',
        events: [['00:06', '生成简报', '将研究要求整理为三个并行方向']] as [
          string,
          string,
          string,
        ][],
      }
    if (!node.researcher) return node
    const events: [string, string, string][] = [
      ['00:10', '接收研究任务', node.title],
      ['00:14', '检索示例资料', '模拟证据条目逐步返回'],
      ['00:20', '交叉核验', '记录一致信息与待验证问题'],
      ['00:25', 'compress_research', '模拟笔记返回协调器'],
    ]
    const count =
      node.status === 'completed'
        ? 4
        : index === 10
          ? 2 + Math.floor(progress * 2)
          : index >= 9
            ? 3
            : 2
    return {
      ...node,
      events: events.slice(0, count),
      backendId: `researcher_agent_skills / ${node.status === 'completed' ? 'compress_research' : 'tool_node'}`,
      tool:
        node.status === 'completed'
          ? 'compress_research · 已完成'
          : index >= 9
            ? '核验示例资料'
            : '检索示例资料',
      query:
        node.status === 'completed'
          ? '模拟笔记已返回协调器。'
          : `正在收集与「${node.title}」有关的示例资料。`,
      count: `${node.status === 'completed' ? 6 : Math.min(5, Math.max(1, Math.floor((index - 7 + progress) * 2)))} 条`,
      duration: `${Math.max(1, Math.floor((Math.min(demoStart(index) + progress * demoScenes[index].duration, demoStart(node.id === 'a' ? 9 : 11)) - demoStart(7)) / 1000))} s`,
      output:
        node.status === 'completed'
          ? 'compressed_research\n模拟笔记已返回协调器。'
          : '检索中 · 已收到模拟证据，正在核验，尚未生成压缩笔记。',
      caption: node.status === 'completed' ? '已完成' : index >= 9 ? '核验中' : '检索中',
    }
  })
}
