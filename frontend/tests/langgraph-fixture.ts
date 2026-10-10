import type { Page } from '@playwright/test'
import type { BackendConfig, GraphValues } from '../src/data/liveSchema'
import type { ServerRun } from '../src/api/langgraph'

export const fakeConfig: BackendConfig = {
  contract_version: 1,
  graph_id: 'research_agent_full',
  model_selection: 'server',
  skills_mode: 'auto',
  models: [
    'SCOPING',
    'SUPERVISOR',
    'RESEARCHER',
    'SUMMARIZATION',
    'COMPRESSION',
    'FINAL_REPORT',
  ].map((role) => ({
    role,
    model: `${role.toLowerCase()}-server-model`,
    provider: 'openai',
    max_tokens: 32000,
  })),
}
export interface Submission {
  input: {
    research_id: string
    turn_id: string
    messages: { id: string; type: string; content: string }[]
  }
  metadata: Record<string, string>
  multitask_strategy: string
  assistant_id: string
  stream_mode?: string[]
  stream_resumable?: boolean
}

export async function fakeLangGraph(page: Page) {
  const config = structuredClone(fakeConfig)
  const threads = new Set<string>()
  const states = new Map<string, GraphValues>()
  const runs: ServerRun[] = []
  const submissions: Submission[] = []
  const controls = {
    loseResponse: false,
    rejectBeforeRun: false,
    preservePreviousState: false,
    offline: false,
  }
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname.replace(/^\/api/, '')
      const reply = (body: unknown, status = 200) => route.fulfill({ status, json: body })
      if (controls.offline) return route.abort()
      if (path === '/atlas/config') return reply(config)
      if (path === '/threads' && request.method() === 'POST') {
        const body = request.postDataJSON()
        threads.add(body.thread_id)
        return reply({ thread_id: body.thread_id })
      }
      const match = path.match(/^\/threads\/([^/]+)\/(state|runs)(?:\/([^/]+))?$/)
      if (!match || !threads.has(match[1])) return reply({ detail: 'Not found' }, 404)
      const [, threadId, resource, runId] = match
      if (resource === 'state') return reply({ values: states.get(threadId) ?? {}, next: [] })
      if (request.method() === 'POST') {
        const body = request.postDataJSON() as Submission
        submissions.push(body)
        if (controls.rejectBeforeRun) return route.abort()
        const run: ServerRun = {
          run_id: crypto.randomUUID(),
          thread_id: threadId,
          status: 'running',
          metadata: body.metadata,
        }
        runs.push(run)
        if (!controls.preservePreviousState) {
          const old = states.get(threadId)
          states.set(threadId, {
            active_research_id: body.input.research_id,
            active_turn_id: body.input.turn_id,
            report_research_id: '',
            research_status: 'running',
            research_phase: 'clarify',
            effective_config: structuredClone(config),
            research_brief: '',
            final_report: '',
            notes: [],
            sources: [],
            research_errors: [],
            messages: [
              ...(old?.active_research_id === body.input.research_id ? (old.messages ?? []) : []),
              ...body.input.messages,
            ],
          })
        }
        if (controls.loseResponse) return route.abort()
        return reply(run)
      }
      if (runId) return reply(runs.find((run) => run.run_id === runId))
      return reply(runs.filter((run) => run.thread_id === threadId).reverse())
    },
  )

  function change(
    values: Partial<GraphValues>,
    status: ServerRun['status'] = 'success',
    run = runs.at(-1)!,
  ) {
    run.status = status
    states.set(run.thread_id, { ...states.get(run.thread_id), ...values })
  }
  function clarify(run = runs.at(-1)!) {
    change(
      {
        research_status: 'awaiting_input',
        research_phase: 'clarify',
        messages: [
          ...(states.get(run.thread_id)?.messages ?? []),
          { id: crypto.randomUUID(), type: 'ai', content: '请补充比较对象和时间范围。' },
        ],
      },
      'success',
      run,
    )
  }
  function succeed(run = runs.at(-1)!) {
    const state = states.get(run.thread_id)!
    change(
      {
        research_status: 'succeeded',
        research_phase: 'complete',
        report_research_id: state.active_research_id,
        research_brief: '后端生成的实际研究简报',
        final_report:
          '# 实际研究报告\n\n可核验的研究结论 [1]。\n\n| 对象 | 结论 |\n| --- | --- |\n| A | 有证据支持 |\n\n[来源 A](https://example.com/source)\n\n<script>alert(1)</script>\n\n![不要加载外部图像](https://example.com/tracker.png)',
        notes: ['研究笔记 A'],
        sources: [{ title: '来源 A', url: 'https://example.com/source' }],
      },
      'success',
      run,
    )
  }
  return { threads, states, runs, submissions, controls, config, change, clarify, succeed }
}
