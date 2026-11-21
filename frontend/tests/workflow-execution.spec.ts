import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import type {
  GraphValues,
  LiveResearch,
  LiveThread,
  ResearchEvent,
  SubmissionReceipt,
} from '../src/data/liveSchema'
import { workflowFixture, catalog } from './workflow-fixture'
import { fakeConfig } from './langgraph-fixture'
import { insertWorkflowNode } from '../src/data/workflowEditing'
import { workflowSemanticHash } from '../src/data/workflowSchema'
import type { WorkflowNodeEvent, WorkflowRevision } from '../src/data/workflowSchema'
import {
  confirmedWorkflowEvents,
  getWorkflowNodes,
  mergeWorkflowEvents,
  workflowPath,
} from '../src/data/workflowRuntime'
import { readResearchEvents } from '../src/api/researchStream'

const at = '2026-11-15T08:00:00Z'
const pageErrors = new WeakMap<Page, string[]>()
test.beforeEach(({ page }) => {
  const errors: string[] = []
  pageErrors.set(page, errors)
  page.on('pageerror', (error) => errors.push(error.message))
})
test.afterEach(({ page }) => expect(pageErrors.get(page)).toEqual([]))

async function published() {
  const management = workflowFixture()
  const id = management.seed('M3 流程')
  const entry = management.workflows.get(id)!
  const plan = insertWorkflowNode(entry.draft.document, catalog, 'optimize_plan')!
  const notes = insertWorkflowNode(entry.draft.document, catalog, 'organize_notes')!
  const revision: WorkflowRevision = {
    schema_version: 1,
    workflow_id: id,
    revision_id: 'revision_m3',
    revision_number: 1,
    source_edit_version: 1,
    semantic_hash: await workflowSemanticHash(entry.draft.document.definition),
    compatibility: {
      graph_id: 'research_workflow',
      compiler_version: 1,
      node_registry_version: 1,
      state_schema_version: 1,
    },
    document: structuredClone(entry.draft.document),
    note: '',
    published_at: at,
  }
  entry.revisions.push(revision)
  entry.draft.base_revision_id = revision.revision_id
  entry.draft.edit_version = 2
  return { management, revision, plan, notes }
}

function runData(
  revision: WorkflowRevision,
  threadId: string = crypto.randomUUID(),
  turnId: string = crypto.randomUUID(),
  researchId: string = crypto.randomUUID(),
) {
  const runId = crypto.randomUUID()
  const binding = {
    schema_version: 1 as const,
    thread_id: threadId,
    workflow_ref: { workflow_id: revision.workflow_id, revision_id: revision.revision_id },
    semantic_hash: revision.semantic_hash,
    compatibility: revision.compatibility,
    bound_at: at,
  }
  const config = {
    ...fakeConfig,
    submission_recovery_version: 1 as const,
    workflow_editor_version: 1 as const,
    workflow_execution_version: 1 as const,
    workflow_events_version: 1 as const,
  }
  const receipt: SubmissionReceipt = {
    version: 1,
    configuration: config,
    thread_id: threadId,
    research_id: researchId,
    turn_id: turnId,
    attempt_id: turnId,
    run_id: runId,
    event_run_id: runId,
    status: 'completed',
    reason: 'checkpoint_completed',
    retry_allowed: false,
    attempts: [{ run_id: runId, attempt_id: turnId, kind: 'submit' }],
    recovery: { allowed: false, reason: 'already_completed' },
    workflow_binding: binding,
    run: {
      run_id: runId,
      thread_id: threadId,
      status: 'success',
      metadata: { atlas_research_id: researchId, atlas_turn_id: turnId },
    },
  }
  const events = workflowPath(revision)
    .filter((node) => !['start', 'end'].includes(node.type))
    .flatMap((node) =>
      (['started', 'completed'] as const).map((kind): WorkflowNodeEvent => ({
        version: 1,
        id: crypto.randomUUID(),
        thread_id: threadId,
        research_id: researchId,
        turn_id: turnId,
        run_id: runId,
        attempt_id: turnId,
        workflow_ref: binding.workflow_ref,
        semantic_hash: revision.semantic_hash,
        node_id: node.id,
        node_type: node.type,
        sequence: 1,
        at,
        kind,
        elapsed_ms: kind === 'started' ? 0 : 100,
        summary: '',
      })),
    )
    .map((event, index) => ({ ...event, sequence: index + 1 }))
  const research: LiveResearch = {
    id: researchId,
    prompt: '测试问题',
    createdAt: at,
    config,
    workflow: revision,
    execution: receipt,
    turns: [
      {
        id: turnId,
        text: '测试问题',
        submittedAt: at,
        runId,
        transport: 'accepted',
        submissionVersion: 1,
        workflowRef: binding.workflow_ref,
        expectedTurnId: null,
      },
    ],
    status: 'succeeded',
    phase: 'complete',
    messages: [],
    brief: '优化后的简报',
    report: '# M3 浏览器测试报告',
    notes: ['原始笔记'],
    organizedNotes: '整理后的材料',
    sources: [],
    errors: [],
    events: [],
    observations: [],
  }
  const thread: LiveThread = {
    serverUrl: '/api',
    threadId,
    researches: [research],
    workflow: revision,
  }
  return { receipt, research, thread, events }
}

async function backend(page: Page) {
  const publishedVersion = await published()
  const { management, revision } = publishedVersion
  await management.attach(page)
  const control = {
    executable: true,
    loseResponse: false,
    awaiting: false,
    wrongSnapshot: false,
    wrongEvents: false,
    completed: true,
    researcherCount: 0,
  }
  const creations: string[] = []
  const submissions: { thread: string; turn: string; body: Record<string, unknown> }[] = []
  const reads: string[] = []
  const records = new Map<string, ReturnType<typeof runData>>()
  await page.route(/\/api\/atlas\/config$/, (route) =>
    route.fulfill({
      json: {
        ...fakeConfig,
        submission_recovery_version: 1,
        workflow_editor_version: 1,
        ...(control.executable
          ? { workflow_execution_version: 1, workflow_events_version: 1 }
          : {}),
      },
    }),
  )
  await page.route(/\/api\/(?:threads|atlas\/threads)(?:\/|$)/, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api', '')
    const reply = (json: unknown, status = 200) => route.fulfill({ json, status })
    reads.push(`${request.method()} ${path}`)
    if (path === '/threads' && request.method() === 'POST') {
      creations.push(request.postDataJSON().thread_id)
      return reply({ thread_id: creations.at(-1) })
    }
    const submission = path.match(/^\/atlas\/threads\/([^/]+)\/submissions\/([^/]+)$/)
    if (submission) {
      const [, thread, turn] = submission
      if (request.method() === 'POST') {
        const body = request.postDataJSON()
        submissions.push({ thread, turn, body })
        if (!records.has(turn)) {
          const record = runData(revision, thread, turn, body.research_id)
          if (control.researcherCount) {
            record.research.config.research_event_replay_version = 1
            const events: ResearchEvent[] = []
            for (let i = 1; i <= control.researcherCount; i++) {
              const task = {
                version: 1 as const,
                task_id: crypto.randomUUID(),
                at,
                round: 1,
                research_id: body.research_id,
                turn_id: turn,
                topic: `实际任务 ${i}`,
                elapsed_ms: 10,
              }
              events.push({
                ...task,
                id: crypto.randomUUID(),
                sequence: events.length + 1,
                kind: 'delegated',
              })
              if (i < control.researcherCount)
                events.push({
                  ...task,
                  id: crypto.randomUUID(),
                  sequence: events.length + 1,
                  kind: 'completed',
                })
            }
            record.research.events = events
          }
          records.set(turn, record)
        }
        if (control.loseResponse) {
          control.loseResponse = false
          return route.abort()
        }
      }
      const record = records.get(turn)
      if (!record) return reply({ reason: 'submission_unknown' }, 404)
      const receipt = structuredClone(record.receipt)
      if (!control.completed) {
        receipt.status = 'accepted'
        receipt.run!.status = 'running'
      }
      return reply(receipt)
    }
    const state = path.match(/^\/threads\/([^/]+)\/state(?:\/[^/]+)?$/)
    if (state) {
      const record = [...records.values()].filter((r) => r.thread.threadId === state[1]).at(-1)!
      const receipt = record.receipt
      const binding = structuredClone(receipt.workflow_binding!)
      if (control.wrongSnapshot) binding.semantic_hash = '0'.repeat(64)
      const values: GraphValues = {
        active_research_id: receipt.research_id,
        active_turn_id: receipt.turn_id,
        research_status: control.awaiting
          ? 'awaiting_input'
          : control.completed
            ? 'succeeded'
            : 'running',
        research_phase: control.awaiting ? 'clarify' : control.completed ? 'complete' : 'research',
        effective_config: record.research.config,
        workflow_binding: binding,
        organized_notes: '整理后的材料',
        research_brief: '优化后的简报',
        notes: ['原始笔记'],
        final_report: control.awaiting ? '' : '# M3 浏览器测试报告\n\n已确认归属的报告。',
        report_research_id: receipt.research_id,
        report_run_id: receipt.run_id,
        report_turn_id: receipt.turn_id,
        report_attempt_id: receipt.attempt_id,
        report_writing_attempt_id: crypto.randomUUID(),
        messages: [
          { id: receipt.turn_id, type: 'human', content: '测试问题' },
          ...(control.awaiting
            ? [{ id: crypto.randomUUID(), type: 'ai', content: '请补充研究范围。' }]
            : []),
        ],
        sources: [],
        research_errors: [],
      }
      return reply({ values, next: [] })
    }
    const replay = path.match(/^\/atlas\/threads\/([^/]+)\/runs\/([^/]+)\/workflow-events$/)
    if (replay) {
      const record = [...records.values()].find((r) => r.receipt.run_id === replay[2])!
      let events = structuredClone(record.events)
      if (control.awaiting) {
        events = events.slice(0, 4)
        events[3].kind = 'awaiting_input'
      }
      if (!control.completed) events = events.slice(0, 7)
      if (control.wrongEvents)
        events = events.map((event) => ({
          ...event,
          workflow_ref: { ...event.workflow_ref, revision_id: 'wrong' },
        }))
      const after = Number(url.searchParams.get('after') ?? 0)
      return reply({
        version: 1,
        thread_id: replay[1],
        run_id: replay[2],
        research_id: record.research.id,
        turn_id: record.receipt.turn_id,
        attempt_id: record.receipt.attempt_id,
        workflow_ref: record.receipt.workflow_binding!.workflow_ref,
        semantic_hash: revision.semantic_hash,
        status: 'ready',
        journal_id: record.receipt.run_id,
        events: events.filter((event) => event.sequence > after),
        last_sequence: events.length,
        next_sequence: events.length,
        has_more: false,
        sealed: control.completed,
        gap: false,
        reset: false,
        unconfirmed_before_sequence: 0,
      })
    }
    const tasks = path.match(/^\/atlas\/threads\/([^/]+)\/runs\/([^/]+)\/events$/)
    if (tasks) {
      const record = [...records.values()].find((r) => r.receipt.run_id === tasks[2])!
      const after = Number(url.searchParams.get('after') ?? 0)
      const all = record.research.events
      const events = all.slice(after, after + Number(url.searchParams.get('limit') ?? 50))
      const next = after + events.length
      return reply({
        version: 1,
        thread_id: tasks[1],
        run_id: tasks[2],
        research_id: record.research.id,
        turn_id: record.receipt.turn_id,
        status: 'ready',
        journal_id: tasks[2],
        events,
        last_sequence: all.length,
        next_sequence: next,
        has_more: next < all.length,
        sealed: control.completed,
        gap: false,
        reset: false,
      })
    }
    return reply({}, 404)
  })
  const open = async () => {
    await page.goto(`/#workflows/${revision.workflow_id}/revisions/${revision.revision_id}`)
    await expect(page.getByRole('button', { name: '使用此版本发起研究' })).toBeVisible()
    await page.getByRole('button', { name: '使用此版本发起研究' }).click()
    await expect(page.locator('.cw-workflow-choice')).toContainText('M3 流程 · v1')
  }
  const send = async (text = '测试工作流') => {
    await page.getByRole('textbox', { name: '研究问题或补充要求' }).fill(text)
    await page.getByRole('button', { name: '发送消息' }).click()
    await expect.poll(() => submissions.length).toBeGreaterThan(0)
  }
  return { ...publishedVersion, control, creations, submissions, records, reads, open, send }
}

test('120 replayed researcher tasks expand on demand and locate the active group by keyboard', async ({
  page,
}, testInfo) => {
  const f = await backend(page)
  f.control.researcherCount = 120
  f.control.completed = false
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await f.open()
  await f.send()
  const researchers = page.getByLabel('动态研究员', { exact: true })
  await expect(researchers).toContainText('120 个任务', { timeout: 15000 })
  const group = researchers.getByRole('button', { name: '研究员 1–20', exact: true })
  const last = researchers.getByRole('button', { name: '研究员 101–120', exact: true })
  const taskButtons = researchers.locator('[data-flow-node]')
  await expect(taskButtons).toHaveCount(0)

  const durations: Record<string, number> = {}
  await group.focus()
  let start = performance.now()
  await page.keyboard.press('Enter')
  await expect(taskButtons).toHaveCount(20)
  durations.expandMs = performance.now() - start
  start = performance.now()
  await page.keyboard.press('Space')
  await expect(taskButtons).toHaveCount(0)
  durations.collapseMs = performance.now() - start

  const locate = page.getByRole('button', { name: '定位当前', exact: true })
  await locate.focus()
  start = performance.now()
  await page.keyboard.press('Enter')
  const active = researchers.getByRole('button', { name: /^研究员 120，/ })
  await expect(last).toHaveAttribute('aria-expanded', 'true')
  await expect(taskButtons).toHaveCount(20)
  await expect(active).toHaveAttribute('data-status', 'running')
  await expect(active).toBeFocused()
  await expect(active).toBeInViewport()
  durations.locateMs = performance.now() - start
  await expect(page.locator('#cw-inspector')).toContainText('研究员 120')

  await last.click()
  await expect(taskButtons).toHaveCount(0)
  await page.getByRole('button', { name: '收起节点检查器' }).click()
  await expect(last).toBeFocused()
  expect(f.submissions).toHaveLength(1)
  expect(f.reads.filter((path) => /^POST .*\/runs/.test(path))).toEqual([])
  await testInfo.attach('researcher-group-timings', {
    contentType: 'application/json',
    body: JSON.stringify({ researchers: 120, ...durations }, null, 2),
  })
})

test('published version opens a new question draft and only sends after input', async ({
  page,
}) => {
  const f = await backend(page)
  await f.open()
  expect(f.creations).toEqual([])
  expect(f.submissions).toEqual([])
  await expect(page.getByRole('textbox', { name: '研究问题或补充要求' })).toHaveValue('')
  await f.send()
  await expect(page.getByRole('heading', { name: 'M3 浏览器测试报告' })).toBeVisible()
  expect(f.submissions[0].body.workflow_ref).toEqual({
    workflow_id: f.revision.workflow_id,
    revision_id: f.revision.revision_id,
  })
  await expect(page.locator(`[data-flow-node="${f.plan}"]`)).toHaveAttribute(
    'data-status',
    'completed',
  )
  await expect(page.locator(`[data-flow-node="${f.notes}"]`)).toHaveAttribute(
    'data-status',
    'completed',
  )
  await page.locator(`[data-flow-node="${f.notes}"]`).click()
  await page.getByRole('tab', { name: '输入 / 输出' }).click()
  await expect(page.locator('#cw-inspector')).toContainText('整理后的材料')
  await page.reload()
  await expect(page.locator(`[data-flow-node="${f.plan}"]`)).toHaveAttribute(
    'data-status',
    'completed',
  )
  await page.getByRole('button', { name: '刷新状态', exact: true }).click()
  expect(f.submissions).toHaveLength(1)
  expect(f.creations).toHaveLength(1)
  expect(f.reads.filter((path) => /^POST .*\/runs/.test(path))).toEqual([])
})

test('each use of a published version creates a separate local session', async ({ page }) => {
  const f = await backend(page)
  await f.open()
  const id = await page.evaluate(
    () => JSON.parse(localStorage.getItem('atlas-workspace:v1')!).activeThreadId,
  )
  await page.getByRole('link', { name: '查看流程', exact: true }).click()
  await page.getByRole('button', { name: '使用此版本发起研究' }).click()
  const next = await page.evaluate(
    () => JSON.parse(localStorage.getItem('atlas-workspace:v1')!).activeThreadId,
  )
  expect(next).not.toBe(id)
  expect(f.submissions).toEqual([])
})

test('old backend capability cannot silently execute the default graph', async ({ page }) => {
  const f = await backend(page)
  await f.open()
  f.control.executable = false
  await page.getByRole('textbox', { name: '研究问题或补充要求' }).fill('保留这个问题')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.locator('.cw-workflow-choice')).toContainText('当前后端不支持此流程执行')
  await expect(page.getByRole('textbox', { name: '研究问题或补充要求' })).toHaveValue(
    '保留这个问题',
  )
  expect(f.submissions).toEqual([])
  expect(f.creations).toEqual([])
})

test('lost acceptance response preserves the workflow reference without a second run', async ({
  page,
}) => {
  const f = await backend(page)
  await f.open()
  f.control.loseResponse = true
  await f.send()
  await expect(page.getByRole('heading', { name: 'M3 浏览器测试报告' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'M3 浏览器测试报告' })).toBeVisible()
  expect(f.submissions).toHaveLength(1)
  expect(f.records.size).toBe(1)
})

test('clarification replies keep the same thread and published revision', async ({ page }) => {
  const f = await backend(page)
  f.control.awaiting = true
  await f.open()
  await f.send('需要澄清')
  await expect(page.locator('[data-flow-node="clarify_with_user"]')).toHaveAttribute(
    'data-status',
    'waiting',
  )
  f.control.awaiting = false
  await f.send('补充研究范围')
  await expect.poll(() => f.submissions.length).toBe(2)
  await expect(page.getByRole('heading', { name: 'M3 浏览器测试报告' })).toBeVisible()
  expect(f.submissions[1].thread).toBe(f.submissions[0].thread)
  expect(f.submissions[1].body.workflow_ref).toEqual(f.submissions[0].body.workflow_ref)
  expect(f.submissions[1].body.research_id).toBe(f.submissions[0].body.research_id)
  expect(f.submissions[1].body.expected_turn_id).toBe(f.submissions[0].turn)
  expect(f.creations).toHaveLength(1)
})

test('wrong revision snapshots and events never confirm a report or node', async ({ page }) => {
  const f = await backend(page)
  f.control.wrongSnapshot = f.control.wrongEvents = true
  await f.open()
  await f.send()
  await expect(page.getByTestId('live-status').last()).toContainText('研究失败')
  await expect(page.getByRole('heading', { name: 'M3 浏览器测试报告' })).toHaveCount(0)
  await expect(page.locator(`[data-flow-node="${f.plan}"]`)).toHaveAttribute(
    'data-status',
    'pending',
  )
  expect(f.submissions).toHaveLength(1)
})

test('workflow stream rejects cross-attempt events, gaps and conflicting UUIDs', async () => {
  const { revision, plan } = await published()
  const { thread, research, events, receipt } = runData(revision)
  const merge = (incoming: WorkflowNodeEvent[]) => {
    research.workflowStreams = mergeWorkflowEvents(thread, research, receipt.run_id, incoming)
  }
  merge([{ ...events[0], attempt_id: crypto.randomUUID() }])
  expect(confirmedWorkflowEvents(research)).toEqual([])
  merge(events.slice(1))
  expect(confirmedWorkflowEvents(research)).toEqual([])
  merge([events[0]])
  expect(confirmedWorkflowEvents(research)).toEqual(events)
  expect(getWorkflowNodes(research).find((node) => node.id === plan)?.status).toBe('completed')
  merge([{ ...events[1], id: events[0].id }])
  expect(confirmedWorkflowEvents(research)).toEqual([])
})

test('read-only custom stream recognizes parent events separately from researchers', async () => {
  const { revision } = await published()
  const { events } = runData(revision)
  const observed: WorkflowNodeEvent[] = []
  const frame = `id: 1-0\nevent: custom\ndata: ${JSON.stringify({ type: 'atlas.workflow_event', event: events[0] })}\n\nevent: end\n\n`
  await readResearchEvents(
    new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(frame))
        controller.close()
      },
    }),
    {
      onCursor: () => {},
      onEvent: () => {
        throw new Error('Wrong event family')
      },
      onWorkflowEvent: (event) => observed.push(event),
    },
  )
  expect(observed).toEqual(events.slice(0, 1))
})

for (const [width, colorScheme] of [
  [1440, 'light'],
  [1024, 'dark'],
  [390, 'light'],
  [320, 'dark'],
] as const)
  test(`published execution graph remains readable at ${width}px in ${colorScheme}`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 962 })
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
    const f = await backend(page)
    await f.open()
    await f.send()
    await expect(page.getByRole('heading', { name: 'M3 浏览器测试报告' })).toBeVisible()
    await expect(page.locator(`[data-flow-node="${f.notes}"]`)).toHaveAttribute(
      'data-status',
      'completed',
    )
    await page.locator(`[data-flow-node="${f.notes}"]`).click()
    await expect(page.getByRole('heading', { name: '材料整理', exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    )
    await page.screenshot({ path: info.outputPath(`workflow-run-${width}.png`), fullPage: true })
  })
