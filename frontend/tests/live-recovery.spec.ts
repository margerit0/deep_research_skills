import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import type { EventRecovery, ResearchEvent } from '../src/data/liveSchema'
import type { ServerRun } from '../src/api/langgraph'
import { fakeLangGraph } from './langgraph-fixture'

const taskId = 'b9f7ef8b-1c6a-4c73-a0a4-0a4f2bb2d855'
const refresh = (page: Page) => page.getByRole('button', { name: '刷新状态', exact: true }).click()
const status = (page: Page) => page.getByTestId('live-status').last()
const note = (page: Page) => page.getByTestId('event-recovery-note').last()

function event(run: ServerRun, sequence: number, kind: ResearchEvent['kind']): ResearchEvent {
  return {
    version: 1,
    id: crypto.randomUUID(),
    research_id: String(run.metadata.atlas_research_id),
    turn_id: String(run.metadata.atlas_turn_id),
    sequence,
    at: '2026-10-11T01:00:00+00:00',
    task_id: taskId,
    round: 1,
    kind,
    elapsed_ms: sequence * 100,
    topic: '持久研究任务',
    ...(kind === 'completed' ? { output: '持久化研究笔记' } : {}),
  }
}

async function saved(
  page: Page,
): Promise<{ events: ResearchEvent[]; eventRecovery?: EventRecovery }> {
  return page.evaluate(() => {
    const workspace = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
    return workspace.threads
      .find((t: { id: string }) => t.id === workspace.activeThreadId)
      .live.researches.at(-1)
  })
}

async function setup(page: Page) {
  const fake = await fakeLangGraph(page)
  fake.config.research_events_version = 1
  fake.config.research_event_replay_version = 1
  const control = {
    events: [] as ResearchEvent[],
    journalId: crypto.randomUUID(),
    sealed: false,
    status: 'ready',
    wrongIdentity: false,
    gap: false,
    unavailable: false,
    sse: '',
    staleCursor: false,
    unconfirmedBefore: 0,
  }
  const pages: number[] = []
  const cursors: string[] = []
  await page.route(/\/api\/atlas\/threads\/[^/]+\/runs\/[^/]+\/events\?/, async (route) => {
    const url = new URL(route.request().url())
    const run = fake.runs.find((run) => url.pathname.includes(run.run_id))!
    const after = Number(url.searchParams.get('after') ?? 0)
    pages.push(after)
    if (control.unavailable || fake.controls.offline) return route.fulfill({ status: 503 })
    const last = control.events.at(-1)?.sequence ?? 0
    const reset =
      after > last ||
      (!!url.searchParams.get('journal_id') &&
        url.searchParams.get('journal_id') !== control.journalId)
    const remaining =
      control.status === 'ready'
        ? control.events.filter((event) => event.sequence > (reset ? 0 : after))
        : []
    const events = remaining.slice(0, 2)
    await route.fulfill({
      json: {
        version: 1,
        thread_id: run.thread_id,
        run_id: run.run_id,
        research_id: run.metadata.atlas_research_id,
        turn_id: control.wrongIdentity ? 'wrong-turn' : run.metadata.atlas_turn_id,
        status: control.status,
        journal_id: control.status === 'missing' ? null : control.journalId,
        events,
        last_sequence: last,
        next_sequence: remaining.length > 2 ? events.at(-1)!.sequence : last,
        has_more: remaining.length > 2,
        sealed: control.sealed,
        gap: control.gap || control.status !== 'ready',
        reset,
        unconfirmed_before_sequence: control.unconfirmedBefore,
      },
    })
  })
  await page.route(/\/api\/threads\/[^/]+\/runs\/[^/]+\/stream\?/, async (route) => {
    const cursor = route.request().headers()['last-event-id']
    cursors.push(cursor)
    if (control.staleCursor && cursor !== '-1') return route.fulfill({ status: 410 })
    if (!control.sse || fake.controls.offline) return route.fulfill({ status: 503 })
    await route.fulfill({ contentType: 'text/event-stream', body: control.sse })
  })
  await page.goto('/')
  await page.getByRole('textbox', { name: '研究问题或补充要求' }).fill('验证进度恢复')
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled()
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect.poll(() => fake.runs.length).toBe(1)
  fake.change({ research_phase: 'research' }, 'running')
  return { fake, control, pages, cursors, run: fake.runs[0] }
}

test('recovery: paginated journal restores a finished run without the SSE buffer', async ({
  page,
}) => {
  const { fake, control, run, pages } = await setup(page)
  control.events = [
    'delegated',
    'model_started',
    'model_finished',
    'compression_finished',
    'completed',
  ].map((kind, i) => event(run, i + 1, kind as ResearchEvent['kind']))
  control.sealed = true
  fake.succeed()
  await refresh(page)
  await expect.poll(async () => (await saved(page)).events.length).toBe(5)
  await expect(status(page)).toHaveAttribute('data-status', 'succeeded')
  await expect(page.locator(`[data-flow-node="researcher-${taskId}"]`)).toHaveAttribute(
    'data-status',
    'completed',
  )
  expect(pages).toEqual(expect.arrayContaining([0, 2, 4]))
  expect((await saved(page)).eventRecovery?.sequence).toBe(5)
  await page.reload()
  await expect.poll(() => pages.at(-1)).toBe(5)
  expect((await saved(page)).events).toEqual(control.events)
  await expect(note(page)).toHaveCount(0)
  expect(fake.runs).toHaveLength(1)
  expect(fake.submissions).toHaveLength(1)
})

test('recovery: browser reload keeps the stream cursor and an expired cursor falls back', async ({
  page,
}) => {
  const { fake, control, run, cursors } = await setup(page)
  const first = event(run, 1, 'delegated')
  control.events = [first]
  control.sse = `id: 100-0\nevent: custom\ndata: ${JSON.stringify({ type: 'atlas.research_event', event: first })}\n\n`
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect.poll(async () => (await saved(page)).eventRecovery?.cursor).toBe('100-0')
  control.staleCursor = true
  control.sse = 'id: 200-0\nevent: keepalive\ndata: {}\n\n'
  const index = cursors.length
  await page.reload()
  await expect.poll(() => cursors.slice(index)).toContain('100-0')
  await expect.poll(() => cursors.slice(index)).toContain('-1')
  await expect.poll(async () => (await saved(page)).eventRecovery?.cursor).toBe('200-0')
  expect((await saved(page)).events).toEqual([first])
  expect(fake.runs).toHaveLength(1)
})

test('recovery: a storage failure cannot advance the replay position', async ({ page }) => {
  const { fake, control, run } = await setup(page)
  await page.evaluate(() => {
    const original = Storage.prototype.setItem
    Object.assign(window, {
      restoreStorage: () => {
        Storage.prototype.setItem = original
      },
    })
    Storage.prototype.setItem = function (key, value) {
      if (key === 'atlas-workspace:v1') throw new DOMException('full', 'QuotaExceededError')
      return original.call(this, key, value)
    }
  })
  control.events = [event(run, 1, 'delegated'), event(run, 2, 'completed')]
  await refresh(page)
  await expect(page.locator(`[data-flow-node="researcher-${taskId}"]`)).toBeVisible()
  await expect(page.getByText('浏览器暂时无法保存本地会话', { exact: false })).toBeVisible()
  expect((await saved(page)).eventRecovery?.sequence ?? 0).toBe(0)
  await page.evaluate(() => (window as unknown as { restoreStorage: () => void }).restoreStorage())
  await refresh(page)
  await expect.poll(async () => (await saved(page)).eventRecovery?.sequence).toBe(2)
  expect(fake.runs).toHaveLength(1)
})

for (const situation of ['expired', 'missing', 'unsealed', 'unterminated']) {
  test(`recovery: ${situation} history is explicit without changing the report outcome`, async ({
    page,
  }) => {
    const { fake, control, run } = await setup(page)
    control.events = [event(run, 1, 'delegated')]
    control.status = ['unsealed', 'unterminated'].includes(situation) ? 'ready' : situation
    control.sealed = situation === 'unterminated'
    fake.succeed()
    await refresh(page)
    await expect(note(page)).toContainText('部分进度记录无法确认')
    await expect(status(page)).toHaveAttribute('data-status', 'succeeded')
    await expect(page.getByTestId('live-report')).toBeVisible()
    await page.reload()
    await expect(note(page)).toContainText('部分进度记录无法确认')
    expect(fake.runs).toHaveLength(1)
  })
}

test('recovery: a mismatched replay cannot contaminate this submission', async ({ page }) => {
  const { control, run, fake } = await setup(page)
  control.events = [event(run, 1, 'delegated')]
  control.wrongIdentity = true
  await refresh(page)
  await expect(note(page)).toContainText('进度记录暂时无法回读')
  expect((await saved(page)).events).toHaveLength(0)
  control.wrongIdentity = false
  await refresh(page)
  await expect.poll(async () => (await saved(page)).events.length).toBe(1)
  expect(fake.submissions).toHaveLength(1)
})

test('recovery: a missing journal during research becomes visible and can recover', async ({
  page,
}) => {
  const { control, fake, run, pages } = await setup(page)
  control.status = 'missing'
  await refresh(page)
  await expect.poll(() => pages.length).toBeGreaterThanOrEqual(2)
  await expect(note(page)).toContainText('进度记录暂时无法回读')
  await expect(status(page)).toHaveAttribute('data-status', 'running')
  control.status = 'ready'
  control.events = [event(run, 1, 'delegated')]
  await refresh(page)
  await expect.poll(async () => (await saved(page)).events.length).toBe(1)
  await expect(note(page)).toHaveCount(0)
  expect(fake.runs).toHaveLength(1)
})

test('recovery: terminal replay failure retries after the connection returns', async ({ page }) => {
  const { control, fake, run } = await setup(page)
  control.events = [event(run, 1, 'delegated'), event(run, 2, 'completed')]
  control.sealed = true
  control.unavailable = true
  fake.succeed()
  await refresh(page)
  await expect(note(page)).toContainText('进度记录暂时无法回读')
  control.unavailable = false
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect.poll(async () => (await saved(page)).events.length).toBe(2)
  await expect(note(page)).toHaveCount(0)
  expect(fake.runs).toHaveLength(1)
})

test('recovery: server journal replacement resets the position and marks the gap', async ({
  page,
}) => {
  const { control, run } = await setup(page)
  control.events = [event(run, 1, 'delegated'), event(run, 2, 'model_started')]
  await refresh(page)
  await expect.poll(async () => (await saved(page)).eventRecovery?.sequence).toBe(2)
  control.journalId = crypto.randomUUID()
  control.events = [event(run, 1, 'delegated')]
  await refresh(page)
  await expect.poll(async () => (await saved(page)).eventRecovery?.sequence).toBe(1)
  await expect(note(page)).toContainText('部分进度记录无法确认')
  expect((await saved(page)).events).toHaveLength(3)
})

test('recovery: an ahead-of-server position resets even within the same journal', async ({
  page,
}) => {
  const { control, run, pages, fake } = await setup(page)
  control.events = [event(run, 1, 'delegated'), event(run, 2, 'model_started')]
  await refresh(page)
  await expect.poll(async () => (await saved(page)).eventRecovery?.sequence).toBe(2)
  await page.evaluate(() => {
    const data = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
    const thread = data.threads.find((thread: { id: string }) => thread.id === data.activeThreadId)
    thread.live.researches.at(-1).eventRecovery.sequence = 99
    localStorage.setItem('atlas-workspace:v1', JSON.stringify(data))
  })
  await page.reload()
  await expect.poll(() => pages).toContain(99)
  await expect.poll(async () => (await saved(page)).eventRecovery?.sequence).toBe(2)
  await expect(note(page)).toContainText('部分进度记录无法确认')
  expect(fake.runs).toHaveLength(1)
})

test('recovery: a position for a different run is not reused', async ({ page }) => {
  const { control, run, pages, fake } = await setup(page)
  control.events = [event(run, 1, 'delegated'), event(run, 2, 'model_started')]
  await refresh(page)
  await expect.poll(async () => (await saved(page)).eventRecovery?.sequence).toBe(2)
  await page.evaluate(() => {
    const data = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
    const thread = data.threads.find((thread: { id: string }) => thread.id === data.activeThreadId)
    thread.live.researches.at(-1).eventRecovery.runId = 'another-run'
    thread.live.researches.at(-1).eventRecovery.sequence = 99
    localStorage.setItem('atlas-workspace:v1', JSON.stringify(data))
  })
  const offset = pages.length
  await page.reload()
  await expect.poll(() => pages.slice(offset)).toContain(0)
  await expect.poll(async () => (await saved(page)).eventRecovery?.runId).toBe(run.run_id)
  expect(pages.slice(offset)).not.toContain(99)
  expect(fake.runs).toHaveLength(1)
})

for (const width of [1440, 390, 320]) {
  test(`recovery: uncertain task and notice fit ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 962 })
    await page.emulateMedia({
      reducedMotion: 'reduce',
      colorScheme: width === 390 ? 'dark' : 'light',
    })
    const { control, run, fake } = await setup(page)
    control.events = [event(run, 1, 'delegated'), event(run, 2, 'tool_started')]
    control.unconfirmedBefore = 2
    control.gap = true
    await refresh(page)
    const task = page.locator(`[data-flow-node="researcher-${taskId}"]`)
    await expect(task).toHaveAttribute('data-status', 'partial')
    await expect(task).toContainText('完成状态未确认')
    await expect(note(page)).toContainText('此前任务是否继续尚未确认')
    await expect(status(page)).toHaveAttribute('data-status', 'running')
    for (const element of [note(page), task]) {
      const box = await element.boundingBox()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await note(page).scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath(`recovery-${width}-notice.png`) })
    await page
      .locator('.cw-graph-panel')
      .screenshot({ path: testInfo.outputPath(`recovery-${width}-graph.png`) })
    expect(fake.runs).toHaveLength(1)
  })
}
