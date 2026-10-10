import { test, expect } from '@playwright/test'
import { readResearchEvents } from '../src/api/researchStream'
import type { ResearchEvent } from '../src/data/liveSchema'

// Explicit opt-in: this test calls the real configured models and search service.
test('native LangGraph API: clarification, answer, report, sources and reload', async ({
  page,
}, testInfo) => {
  test.skip(
    process.env.ATLAS_LIVE !== '1' && process.env.ATLAS_API_FIXTURE !== '1',
    'Opt in with ATLAS_LIVE=1 (real models) or ATLAS_API_FIXTURE=1 (fixture server).',
  )
  test.setTimeout(900000)
  let posts = 0
  let streamConnections = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/threads\/[^/]+\/runs$/.test(request.url())) posts++
    if (request.method() === 'GET' && /\/runs\/[^/]+\/stream\?/.test(request.url()))
      streamConnections++
  })
  await page.goto('/')
  const capabilities = await page.request.get('/api/atlas/config')
  expect(capabilities.ok()).toBe(true)
  const configured = await capabilities.json()
  const fixtureModels = configured.models.every(
    (model: { model: string }) => model.model === 'fixture/model',
  )
  expect(fixtureModels, 'The selected test mode must match the server before creating a run.').toBe(
    process.env.ATLAS_API_FIXTURE === '1',
  )
  if (process.env.ATLAS_API_FIXTURE === '1') {
    const fixture = await page.request.get('/api/atlas-fixture/identity')
    expect(fixture.ok(), 'Start the isolated tests/atlas_fixture_server.py launcher.').toBe(true)
    const identity = await fixture.json()
    expect(identity.file_persistence_disabled).toBe(true)
    expect(identity.event_journal_enabled).toBe(false)
    expect(configured.research_event_replay_version).toBeUndefined()
  }
  const input = page.getByRole('textbox', { name: '研究问题或补充要求' })
  const status = page.getByTestId('live-status').last()
  await input.fill('请帮我做一项对比研究。')
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled({ timeout: 20000 })
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(status).toHaveAttribute('data-status', /^(awaiting_input|failed)$/, {
    timeout: 180000,
  })
  await expect(status).toHaveAttribute('data-status', 'awaiting_input')
  await page.screenshot({ path: testInfo.outputPath('live-clarification.png'), fullPage: true })
  await page.reload()
  await expect(status).toHaveAttribute('data-status', 'awaiting_input')
  await input.fill(
    '比较 Python 3.13 实验性的 free-threaded CPython 与默认 GIL 构建，用于开发者判断是否试用。只比较 GIL 状态、C 扩展兼容性和适用限制三个维度。仅使用 Python 官方文档或 PEP 中的 2–3 个来源，中文报告控制在 500 字左右。范围已明确，无需继续澄清；不确定之处请明示。',
  )
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled({ timeout: 20000 })
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect.poll(() => posts).toBe(2)
  await page.reload()
  await expect(status).toHaveAttribute('data-status', /^(succeeded|partial|failed)$/, {
    timeout: 660000,
  })
  const saved = await page.evaluate(() => {
    const workspace = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
    return workspace.threads.find(
      (thread: { id: string }) => thread.id === workspace.activeThreadId,
    ).live
  })
  const research = saved.researches[0]
  const runsResponse = await page.request.get(`/api/threads/${saved.threadId}/runs?limit=100`)
  expect(runsResponse.ok()).toBe(true)
  const serverRuns = await runsResponse.json()
  const stateResponse = await page.request.get(`/api/threads/${saved.threadId}/state`)
  expect(stateResponse.ok()).toBe(true)
  const checkpoint = (await stateResponse.json()).values
  const replayed: ResearchEvent[] = []
  if (configured.research_events_version === 1) {
    const replay = await page.request.get(
      `/api/threads/${saved.threadId}/runs/${research.turns.at(-1).runId}/stream?stream_mode=custom&cancel_on_disconnect=false`,
      { headers: { 'Last-Event-ID': '-1' } },
    )
    expect(replay.ok()).toBe(true)
    const bytes = new Uint8Array(await replay.body())
    await readResearchEvents(
      new ReadableStream({
        start(controller) {
          controller.enqueue(bytes)
          controller.close()
        },
      }),
      {
        onEvent: (event) => replayed.push(event),
        onCursor: () => undefined,
      },
    )
    expect(replayed).toEqual(checkpoint.research_events)
  }
  await testInfo.attach('api-result', {
    contentType: 'application/json',
    body: JSON.stringify(
      {
        modelAndSearchSubstitutes: process.env.ATLAS_API_FIXTURE === '1',
        threadId: saved.threadId,
        researchId: research.id,
        turns: research.turns.map((turn: { id: string; runId: string }) => ({
          id: turn.id,
          runId: turn.runId,
        })),
        status: research.status,
        reportLength: research.report.length,
        sourceCount: research.sources.length,
        errors: research.errors,
        config: research.config,
        streamConnections,
        eventCount: research.events.length,
        nativeStreamEventCount: replayed.length,
        researcherCount: new Set(research.events.map((event: { task_id: string }) => event.task_id))
          .size,
        serverRunCount: serverRuns.length,
      },
      null,
      2,
    ),
  })
  expect(research.status, JSON.stringify(research.errors)).toBe('succeeded')
  expect(research.turns).toHaveLength(2)
  expect(research.report.length).toBeGreaterThan(100)
  expect(research.sources.length).toBeGreaterThan(0)
  expect(serverRuns).toHaveLength(2)
  expect(serverRuns.map((run: { run_id: string }) => run.run_id).sort()).toEqual(
    research.turns.map((turn: { runId: string }) => turn.runId).sort(),
  )
  for (const run of serverRuns) {
    expect(run.thread_id).toBe(saved.threadId)
    expect(run.metadata.atlas_research_id).toBe(research.id)
    expect(research.turns.map((turn: { id: string }) => turn.id)).toContain(
      run.metadata.atlas_turn_id,
    )
    expect(run.status).toBe('success')
  }
  expect(checkpoint.research_status).toBe('succeeded')
  expect(checkpoint.active_research_id).toBe(research.id)
  expect(checkpoint.active_turn_id).toBe(research.turns.at(-1).id)
  expect(checkpoint.report_research_id).toBe(research.id)
  expect(checkpoint.final_report).toBe(research.report)
  expect(checkpoint.sources).toEqual(research.sources)
  if (configured.research_events_version === 1) {
    expect(streamConnections).toBeGreaterThan(0)
    expect(research.events).toEqual(checkpoint.research_events)
    expect(
      research.events.some(
        (event: { kind: string; tool?: string; source_count?: number }) =>
          event.kind === 'tool_finished' &&
          event.tool === 'tavily_search' &&
          (event.source_count ?? 0) > 0,
      ),
    ).toBe(true)
    expect(research.events.some((event: { kind: string }) => event.kind === 'completed')).toBe(true)
    await expect(page.locator('[data-flow-node^="researcher-"]').first()).toHaveAttribute(
      'data-status',
      'completed',
    )
  }
  await expect(page.getByTestId('live-report')).toBeVisible()
  await expect(page.getByRole('region', { name: '检索来源' })).toBeVisible()
  await expect(page.getByTestId('live-report')).toContainText('Python')
  await page.screenshot({ path: testInfo.outputPath('live-result.png'), fullPage: true })
  await page.reload()
  await expect(status).toHaveAttribute('data-status', 'succeeded')
  await expect(page.getByTestId('live-report')).toContainText('Python')
  expect(posts).toBe(2)
  const restoredEvents = await page.evaluate(() => {
    const workspace = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
    return workspace.threads.find(
      (thread: { id: string }) => thread.id === workspace.activeThreadId,
    ).live.researches[0].events
  })
  expect(restoredEvents).toEqual(research.events)
  const restoredRuns = await page.request.get(`/api/threads/${saved.threadId}/runs?limit=100`)
  expect(await restoredRuns.json()).toHaveLength(2)
})
