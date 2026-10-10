import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import type {
  GraphValues,
  LiveResearch,
  LiveThread,
  SubmissionReceipt,
} from '../src/data/liveSchema'
import { fakeLangGraph } from './langgraph-fixture'

async function managedBackend(page: Page) {
  const fake = await fakeLangGraph(page)
  fake.config.submission_recovery_version = 1
  const control = {
    loseSubmit: false,
    dropSubmit: false,
    conflict: false,
    loseRecovery: false,
    dropRecovery: false,
    interrupted: false,
    recoverable: true,
    wrongIdentity: false,
    unavailable: false,
    node: 'final_report_generation' as 'final_report_generation' | 'clarify_with_user',
  }
  type Entry = {
    thread: string
    turn: string
    research: string
    text: string
    expected: string | null
    attempts: SubmissionReceipt['attempts']
    eventRunId: string
    checkpoint?: string
    snapshot?: GraphValues
  }
  const entries = new Map<string, Entry>()
  const posts: { turn: string; body: unknown }[] = []
  const recoveries: { id: string; body: unknown }[] = []
  const checkpoint = crypto.randomUUID()
  function receipt(entry: Entry): SubmissionReceipt {
    const last = entry.attempts.at(-1)!
    const run = fake.runs.find((run) => run.run_id === last.run_id)!
    const missing = !fake.threads.has(entry.thread)
    if (run.status === 'success' && !entry.checkpoint) {
      entry.checkpoint = crypto.randomUUID()
      entry.snapshot = structuredClone(fake.states.get(entry.thread))
    }
    return {
      version: 1,
      thread_id: entry.thread,
      research_id: entry.research,
      turn_id: control.wrongIdentity ? 'another-turn' : entry.turn,
      attempt_id: last.attempt_id,
      run_id: run.run_id,
      event_run_id: entry.eventRunId,
      checkpoint_id: entry.checkpoint,
      status: missing
        ? 'blocked'
        : control.interrupted
          ? 'interrupted'
          : run.status === 'success'
            ? 'completed'
            : 'accepted',
      reason: missing
        ? 'thread_missing'
        : control.interrupted
          ? control.recoverable
            ? 'model_call_may_repeat'
            : 'research_node_not_resumable'
          : 'accepted',
      retry_allowed: false,
      attempts: entry.attempts,
      recovery:
        control.interrupted && control.recoverable && !missing
          ? {
              allowed: true,
              reason: 'model_call_may_repeat',
              node: control.node,
              checkpoint_id: checkpoint,
            }
          : { allowed: false, reason: 'unavailable' },
      run,
    }
  }
  await page.route(/\/api\/threads\/[^/]+\/state\/[^/]+$/, async (route) => {
    const path = new URL(route.request().url()).pathname
    const entry = [...entries.values()].find(
      (entry) => path === `/api/threads/${entry.thread}/state/${entry.checkpoint}`,
    )
    await route.fulfill(entry ? { json: { values: entry.snapshot, next: [] } } : { status: 404 })
  })
  await page.route(
    /\/api\/atlas\/threads\/([^/]+)\/submissions\/([^/]+)(?:\/recoveries\/([^/]+))?$/,
    async (route) => {
      const match = new URL(route.request().url()).pathname.match(
        /threads\/([^/]+)\/submissions\/([^/]+)(?:\/recoveries\/([^/]+))?$/,
      )!
      const [, thread, turn, recoveryId] = match
      const key = `${thread}/${turn}`
      const reply = (json: unknown, status = 200) => route.fulfill({ json, status })
      if (control.unavailable) return reply({}, 503)
      let entry = entries.get(key)
      if (route.request().method() === 'GET') {
        return entry
          ? reply(receipt(entry))
          : reply(
              { reason: fake.threads.has(thread) ? 'submission_unknown' : 'thread_missing' },
              404,
            )
      }
      const body = route.request().postDataJSON()
      if (recoveryId) {
        recoveries.push({ id: recoveryId, body })
        if (control.dropRecovery) return route.abort()
        if (!entry) return reply({}, 404)
        if (!entry.attempts.some((attempt) => attempt.attempt_id === recoveryId)) {
          if (!control.interrupted || !control.recoverable) return reply({}, 409)
          const runId = crypto.randomUUID()
          entry.attempts.push({ attempt_id: recoveryId, run_id: runId, kind: 'resume' })
          fake.runs.push({
            run_id: runId,
            thread_id: thread,
            status: 'running',
            metadata: { atlas_research_id: entry.research, atlas_turn_id: turn },
          })
          control.interrupted = false
        }
        if (control.loseRecovery) return route.abort()
      } else {
        posts.push({ turn, body })
        if (control.dropSubmit) return route.abort()
        if (control.conflict) return reply({}, 409)
        if (!entry) {
          const runId = crypto.randomUUID()
          entry = {
            thread,
            turn,
            research: body.research_id,
            text: body.text,
            expected: body.expected_turn_id,
            attempts: [{ attempt_id: turn, run_id: runId, kind: 'submit' }],
            eventRunId: runId,
          }
          entries.set(key, entry)
          fake.runs.push({
            run_id: runId,
            thread_id: thread,
            status: 'running',
            metadata: { atlas_research_id: body.research_id, atlas_turn_id: turn },
          })
          fake.states.set(thread, {
            active_research_id: body.research_id,
            active_turn_id: turn,
            research_status: 'running',
            research_phase: 'clarify',
            effective_config: structuredClone(fake.config),
            notes: [],
            sources: [],
            research_errors: [],
            final_report: '',
            report_research_id: '',
            messages: [{ id: turn, type: 'human', content: body.text }],
          })
        }
        if (control.loseSubmit) return route.abort()
      }
      return reply(receipt(entry!))
    },
  )
  function interrupt() {
    control.interrupted = true
    fake.change(
      {
        research_status: 'running',
        research_phase: 'writing',
        research_brief: '已确认的研究范围',
        notes: ['已确认的研究笔记'],
        sources: [{ title: '已确认来源', url: 'https://example.com/verified' }],
      },
      'running',
    )
  }
  return { ...fake, control, posts, recoveries, interrupt }
}

const status = (page: Page) => page.getByTestId('live-status').last()
const note = (page: Page) => page.getByTestId('execution-recovery-note').last()
const refresh = (page: Page) => page.getByRole('button', { name: '刷新状态', exact: true }).click()
const cached = (page: Page): Promise<LiveThread> =>
  page.evaluate(() => {
    const workspace = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
    return workspace.threads.find(
      (thread: { id: string }) => thread.id === workspace.activeThreadId,
    ).live
  })
const research = async (page: Page): Promise<LiveResearch> =>
  (await cached(page)).researches.at(-1)!
async function send(page: Page) {
  await page.goto('/')
  await page.getByRole('textbox', { name: '研究问题或补充要求' }).fill('需要提交确认的研究问题')
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled()
  await page.getByRole('button', { name: '发送消息' }).click()
}
async function prepared(page: Page) {
  const fake = await managedBackend(page)
  await send(page)
  await expect.poll(() => fake.runs.length).toBe(1)
  await expect
    .poll(async () => (await research(page)).turns.at(-1)?.runId)
    .toBe(fake.runs[0].run_id)
  fake.interrupt()
  await refresh(page)
  await expect(note(page)).toContainText('已完成的检索不会重跑')
  return fake
}

test('managed submission reconciles a lost response through its durable receipt', async ({
  page,
}) => {
  const fake = await managedBackend(page)
  fake.control.loseSubmit = true
  await send(page)
  await expect.poll(async () => (await research(page)).turns.at(-1)?.transport).toBe('accepted')
  expect(fake.posts).toHaveLength(1)
  fake.succeed()
  await refresh(page)
  await expect(status(page)).toHaveAttribute('data-status', 'succeeded')
  await page.reload()
  await expect(page.getByTestId('live-report')).toContainText('可核验的研究结论')
  expect(fake.runs).toHaveLength(1)
  expect(fake.posts).toHaveLength(1)
})

test('an unaccepted managed submission can retry the same saved envelope after reload', async ({
  page,
}) => {
  const fake = await managedBackend(page)
  fake.control.dropSubmit = true
  await send(page)
  await expect(page.getByRole('button', { name: '重试同一提交' })).toBeVisible()
  const before = (await research(page)).turns.at(-1)!
  await page.reload()
  await expect(page.getByRole('button', { name: '重试同一提交' })).toBeVisible()
  expect(fake.posts).toHaveLength(1)
  fake.control.dropSubmit = false
  await page.getByRole('button', { name: '重试同一提交' }).click()
  await expect.poll(() => fake.runs.length).toBe(1)
  expect(fake.posts[1]).toEqual(fake.posts[0])
  expect((await research(page)).turns.at(-1)?.id).toBe(before.id)
})

test('a managed conflict is a definite rejection with no automatic resubmission', async ({
  page,
}) => {
  const fake = await managedBackend(page)
  fake.control.conflict = true
  await send(page)
  await expect(status(page)).toHaveAttribute('data-status', 'failed')
  await expect(page.getByRole('button', { name: '重试同一提交' })).toHaveCount(0)
  await page.reload()
  await expect(
    page.getByText('此次提交发生冲突或被拒绝。已保留输入和成果，可新建研究。'),
  ).toBeVisible()
  expect(fake.posts).toHaveLength(1)
  expect(fake.runs).toHaveLength(0)
})

test('verified writing recovery keeps the turn, notes and original event run', async ({ page }) => {
  const fake = await prepared(page)
  const before = (await research(page)).turns.at(-1)!
  await expect(page.getByText('已保留的研究笔记', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '发送消息' })).toBeDisabled()
  await page.getByRole('button', { name: '继续生成报告', exact: true }).click()
  await expect.poll(() => fake.runs.length).toBe(2)
  await expect(status(page)).toHaveAttribute('data-status', 'running')
  const after = (await research(page)).turns.at(-1)!
  expect(after.id).toBe(before.id)
  expect(after.runId).not.toBe(before.runId)
  expect(after.eventRunId).toBe(before.runId)
  fake.succeed()
  await refresh(page)
  await expect(status(page)).toHaveAttribute('data-status', 'succeeded')
  expect(fake.posts).toHaveLength(1)
  expect(fake.recoveries).toHaveLength(1)
})

test('lost recovery response reconciles its accepted attempt across refresh', async ({ page }) => {
  const fake = await prepared(page)
  fake.control.loseRecovery = true
  await page.getByRole('button', { name: '继续生成报告', exact: true }).click()
  await expect.poll(async () => (await research(page)).execution?.attempts.length).toBe(2)
  await page.reload()
  await expect
    .poll(async () => (await research(page)).turns.at(-1)?.runId)
    .toBe(fake.runs[1].run_id)
  expect((await research(page)).turns.at(-1)?.recoveryRequest).toBeUndefined()
  expect(fake.recoveries).toHaveLength(1)
  expect(fake.runs).toHaveLength(2)
})

test('a recovery request that never arrived retries its persisted attempt ID', async ({ page }) => {
  const fake = await prepared(page)
  fake.control.dropRecovery = true
  await page.getByRole('button', { name: '继续生成报告', exact: true }).click()
  await expect(page.getByRole('button', { name: '重试恢复请求', exact: true })).toBeEnabled()
  const pending = (await research(page)).turns.at(-1)?.recoveryRequest
  expect(pending?.id).toBeTruthy()
  await page.reload()
  await expect(page.getByRole('button', { name: '重试恢复请求', exact: true })).toBeEnabled()
  fake.control.dropRecovery = false
  await page.getByRole('button', { name: '重试恢复请求', exact: true }).click()
  await expect.poll(() => fake.runs.length).toBe(2)
  expect(fake.recoveries[0]).toEqual(fake.recoveries[1])
  expect(fake.recoveries[1].id).toBe(pending!.id)
})

test('recovery is blocked before POST when its new attempt cannot be persisted', async ({
  page,
}) => {
  const fake = await prepared(page)
  await page.evaluate(() => {
    Storage.prototype.setItem = () => {
      throw new DOMException('quota', 'QuotaExceededError')
    }
  })
  await page.getByRole('button', { name: '继续生成报告', exact: true }).click()
  await expect(page.getByRole('button', { name: '继续生成报告', exact: true })).toBeDisabled()
  expect(fake.recoveries).toHaveLength(0)
  expect(fake.runs).toHaveLength(1)
})

test('an unverified research interruption preserves results and offers a new conversation', async ({
  page,
}) => {
  const fake = await prepared(page)
  fake.control.recoverable = false
  fake.change({ research_phase: 'research' }, 'running')
  await refresh(page)
  await expect(note(page)).toContainText('当前研究子流程尚不能安全续跑')
  await expect(page.getByRole('button', { name: '继续生成报告' })).toHaveCount(0)
  await expect(page.getByText('已保留的研究笔记', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '新建研究并保留记录', exact: true }).click()
  await expect(page.getByTestId('live-status')).toHaveCount(0)
  expect(fake.posts).toHaveLength(1)
  expect(fake.runs).toHaveLength(1)
})

test('a missing server thread keeps a previously confirmed report without recreating execution', async ({
  page,
}) => {
  const fake = await managedBackend(page)
  await send(page)
  await expect.poll(() => fake.runs.length).toBe(1)
  fake.succeed()
  await refresh(page)
  await expect(page.getByTestId('live-report')).toContainText('可核验的研究结论')
  fake.threads.clear()
  await page.reload()
  await expect(note(page)).toContainText('服务端会话已不存在')
  await expect(page.getByTestId('live-report')).toContainText('可核验的研究结论')
  await expect(page.getByRole('button', { name: '发送消息' })).toBeDisabled()
  expect(fake.posts).toHaveLength(1)
})

test('wrong receipt ownership cannot replace the confirmed run or unlock recovery', async ({
  page,
}) => {
  const fake = await prepared(page)
  const before = (await research(page)).turns.at(-1)?.runId
  fake.control.wrongIdentity = true
  await refresh(page)
  await expect(page.getByText(/暂时无法回读研究状态/)).toBeVisible()
  expect((await research(page)).turns.at(-1)?.runId).toBe(before)
  await page.getByRole('button', { name: '继续生成报告', exact: true }).click()
  await expect.poll(() => fake.recoveries.length).toBe(0)
  expect(fake.runs).toHaveLength(1)
})

test('recovery rereads eligibility before creating an attempt', async ({ page }) => {
  const fake = await prepared(page)
  fake.control.recoverable = false
  await page.getByRole('button', { name: '继续生成报告', exact: true }).click()
  await expect(note(page)).toContainText('当前研究子流程尚不能安全续跑')
  expect(fake.recoveries).toHaveLength(0)
  expect(fake.runs).toHaveLength(1)
})

test('a completed receipt reads its own checkpoint after another tab advances the server thread', async ({
  page,
}) => {
  const fake = await managedBackend(page)
  await send(page)
  await expect.poll(() => fake.runs.length).toBe(1)
  fake.succeed()
  await refresh(page)
  await expect(status(page)).toHaveAttribute('data-status', 'succeeded')
  const before = await research(page)
  fake.states.set((await cached(page)).threadId, {
    active_research_id: 'another-study',
    active_turn_id: 'another-turn',
    research_status: 'running',
    research_phase: 'clarify',
    messages: [],
  })
  await page.reload()
  await expect(status(page)).toHaveAttribute('data-status', 'succeeded')
  await expect(page.getByTestId('live-report')).toContainText('可核验的研究结论')
  expect((await research(page)).report).toBe(before.report)
  expect(fake.posts).toHaveLength(1)
})

test('late journal replay immediately preserves confirmed findings after an unsafe interruption', async ({
  page,
}) => {
  const fake = await managedBackend(page)
  fake.config.research_events_version = 1
  fake.config.research_event_replay_version = 1
  const journal = crypto.randomUUID(),
    event = crypto.randomUUID(),
    task = crypto.randomUUID()
  await page.route(/\/api\/atlas\/threads\/[^/]+\/runs\/[^/]+\/events\?/, async (route) => {
    const run = fake.runs[0]
    const after = Number(new URL(route.request().url()).searchParams.get('after'))
    await route.fulfill({
      json: {
        version: 1,
        thread_id: run.thread_id,
        run_id: run.run_id,
        research_id: run.metadata.atlas_research_id,
        turn_id: run.metadata.atlas_turn_id,
        status: 'ready',
        journal_id: journal,
        next_sequence: 1,
        last_sequence: 1,
        has_more: false,
        sealed: false,
        gap: false,
        reset: false,
        unconfirmed_before_sequence: 1,
        events: after
          ? []
          : [
              {
                version: 1,
                id: event,
                task_id: task,
                research_id: run.metadata.atlas_research_id,
                turn_id: run.metadata.atlas_turn_id,
                sequence: 1,
                at: '2026-10-11T00:00:00Z',
                round: 1,
                kind: 'completed',
                elapsed_ms: 10,
                output: '从日志补回的确认笔记',
                sources: [{ title: '从日志补回的来源', url: 'https://example.com/journal-source' }],
              },
            ],
      },
    })
  })
  await send(page)
  await expect.poll(() => fake.runs.length).toBe(1)
  fake.control.interrupted = true
  fake.control.recoverable = false
  fake.change({ research_phase: 'research', notes: [], sources: [] }, 'running')
  await refresh(page)
  await expect(note(page)).toContainText('当前研究子流程尚不能安全续跑')
  await expect(page.getByText('已保留的研究笔记', { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: '检索来源' }).getByRole('link')).toHaveText(
    '从日志补回的来源',
  )
  expect((await research(page)).notes).toContain('从日志补回的确认笔记')
  expect(fake.runs).toHaveLength(1)
})
