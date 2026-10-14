import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import type { LiveResearch, ReportEvent } from '../src/data/liveSchema'
import type { ServerRun } from '../src/api/langgraph'
import { fakeLangGraph } from './langgraph-fixture'

const draft = (page: Page) => page.getByTestId('live-report-draft').last()
const refresh = (page: Page) => page.getByRole('button', { name: '刷新状态', exact: true }).click()
const saved = (page: Page): Promise<LiveResearch> =>
  page.evaluate(() => {
    const workspace = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
    return workspace.threads
      .find((item: { id: string }) => item.id === workspace.activeThreadId)
      .live.researches.at(-1)
  })

function event(
  run: ServerRun,
  writing: string,
  sequence: number,
  kind: ReportEvent['kind'],
  offset = 0,
  text?: string,
): ReportEvent {
  return {
    version: 1,
    id: crypto.randomUUID(),
    thread_id: run.thread_id,
    run_id: run.run_id,
    research_id: String(run.metadata.atlas_research_id),
    turn_id: String(run.metadata.atlas_turn_id),
    attempt_id: run.run_id,
    writing_attempt_id: writing,
    sequence,
    kind,
    offset,
    text,
    at: '2026-10-14T04:00:00+00:00',
    ...(kind === 'finished' ? { sha256: 'a'.repeat(64) } : {}),
  }
}

function start(run: ServerRun, text: string, sequence = 1) {
  const writing = crypto.randomUUID()
  return [
    event(run, writing, sequence, 'started'),
    event(run, writing, sequence + 1, 'delta', 0, text),
  ]
}

async function setup(page: Page) {
  const fake = await fakeLangGraph(page)
  Object.assign(fake.config, {
    research_events_version: 1,
    report_events_version: 1,
    report_event_replay_version: 1,
  })
  const control = {
    events: [] as ReportEvent[],
    sse: [] as ReportEvent[],
    journalId: crypto.randomUUID(),
    sealed: false,
    unavailable: false,
    missing: false,
    gap: false,
    unconfirmedBefore: 0,
  }
  const positions: number[] = []
  await page.route(/\/api\/atlas\/threads\/[^/]+\/runs\/[^/]+\/report-events\?/, async (route) => {
    if (control.unavailable) return route.fulfill({ status: 503 })
    const url = new URL(route.request().url())
    const run = fake.runs.find((item) => url.pathname.includes(item.run_id))!
    const after = Number(url.searchParams.get('after'))
    positions.push(after)
    const eventsForRun = control.events.filter((item) => item.run_id === run.run_id)
    const last = eventsForRun.at(-1)?.sequence ?? 0
    const reset =
      after > last ||
      (!!url.searchParams.get('journal_id') &&
        url.searchParams.get('journal_id') !== control.journalId)
    const remaining = control.missing
      ? []
      : eventsForRun.filter((item) => item.sequence > (reset ? 0 : after))
    const events = remaining.slice(0, 2)
    return route.fulfill({
      json: {
        version: 1,
        thread_id: run.thread_id,
        run_id: run.run_id,
        research_id: run.metadata.atlas_research_id,
        turn_id: run.metadata.atlas_turn_id,
        status: control.missing ? 'missing' : 'ready',
        journal_id: control.missing ? null : control.journalId,
        events,
        next_sequence: remaining.length > 2 ? events.at(-1)!.sequence : last,
        last_sequence: last,
        has_more: remaining.length > 2,
        sealed: control.sealed,
        gap: control.gap || control.missing,
        reset,
        unconfirmed_before_sequence: control.unconfirmedBefore,
      },
    })
  })
  await page.route(/\/api\/threads\/[^/]+\/runs\/[^/]+\/stream\?/, async (route) => {
    if (!control.sse.length) return route.fulfill({ status: 503 })
    return route.fulfill({
      contentType: 'text/event-stream',
      body: control.sse
        .map(
          (item, index) =>
            `id: ${index + 1}-0\nevent: custom\ndata: ${JSON.stringify({ type: 'atlas.report_event', event: item })}\n\n`,
        )
        .join(''),
    })
  })
  await page.goto('/')
  await page
    .getByRole('textbox', { name: '研究问题或补充要求' })
    .fill('验证真实正文事件协议（测试替身）')
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled()
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect.poll(() => fake.runs.length).toBe(1)
  const run = fake.runs[0]
  fake.change(
    {
      research_phase: 'writing',
      notes: ['保留的真实接口测试笔记'],
      sources: [{ title: '测试来源', url: 'https://example.com/a' }],
    },
    'running',
  )
  return { fake, run, control, positions }
}

test('report: paragraph is visible before completion; only owned checkpoint confirms report', async ({
  page,
}) => {
  const { fake, run, control } = await setup(page)
  control.events = start(run, '# 草稿\n\n首段 🌌')
  await refresh(page)
  await expect(draft(page)).toContainText('首段 🌌')
  await expect(page.getByTestId('live-report')).toHaveCount(0)
  const writing = control.events[0].writing_attempt_id
  control.events.push(
    event(run, writing, 3, 'finished', new TextEncoder().encode('# 草稿\n\n首段 🌌').length),
  )
  control.sealed = true
  await refresh(page)
  await expect(draft(page)).toContainText('等待确认')
  await expect(page.getByTestId('live-status')).toHaveAttribute('data-status', 'running')
  const final = '# 最终确认\n\n逐字采用检查点正文 [1]。'
  fake.change({
    research_status: 'partial',
    research_phase: 'complete',
    final_report: final,
    report_research_id: String(run.metadata.atlas_research_id),
    report_run_id: 'wrong-run',
    report_turn_id: String(run.metadata.atlas_turn_id),
    report_attempt_id: run.run_id,
    report_writing_attempt_id: writing,
  })
  await refresh(page)
  await expect(page.getByTestId('live-report')).toHaveCount(0)
  fake.change({ report_run_id: run.run_id })
  await refresh(page)
  await expect(page.getByTestId('live-report')).toContainText('逐字采用检查点正文')
  expect((await saved(page)).report).toBe(final)
  await expect(draft(page)).toHaveCount(0)
  await page.reload()
  expect((await saved(page)).report).toBe(final)
  expect(fake.submissions).toHaveLength(1)
})

test('report: same-run retry replaces active draft and retains failed attempt', async ({
  page,
}) => {
  const { run, control, fake } = await setup(page)
  control.events = start(run, '失败尝试的正文')
  await refresh(page)
  await expect(draft(page)).toContainText('失败尝试的正文')
  control.events.push(
    event(
      run,
      control.events[0].writing_attempt_id,
      3,
      'failed',
      new TextEncoder().encode('失败尝试的正文').length,
    ),
    ...start(run, '新写作正文', 4),
  )
  await refresh(page)
  await expect(draft(page)).toContainText('新写作正文')
  await expect(draft(page)).not.toContainText('失败尝试的正文')
  await page.getByTestId('report-attempt-history').locator('summary').first().click()
  await page.getByText('第 1 次写作 · 写作失败', { exact: true }).click()
  await expect(page.getByTestId('report-attempt-history')).toContainText('失败尝试的正文')
  expect(fake.runs).toHaveLength(1)
})

test('report: duplicate and out-of-order SSE waits for missing text and filters other owners', async ({
  page,
}) => {
  const { run, control } = await setup(page)
  control.unavailable = true
  const events = start(run, '甲')
  const next = event(run, events[0].writing_attempt_id, 3, 'delta', 3, '乙')
  control.sse = [events[0], next, next, { ...events[1], id: crypto.randomUUID(), run_id: 'wrong' }]
  await refresh(page)
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(draft(page)).toBeVisible()
  await expect(draft(page)).not.toContainText('乙')
  control.sse = [next, events[0], events[1], events[1], next]
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(draft(page)).toContainText('甲乙')
  expect((await saved(page)).reportStreams?.[0].events).toHaveLength(3)
})

test('report: reload paginates durable draft and interrupted journal does not look active', async ({
  page,
}) => {
  const { run, control, fake, positions } = await setup(page)
  control.events = start(run, '刷新前正文')
  await refresh(page)
  await expect(draft(page)).toContainText('刷新前正文')
  await page.reload()
  await expect(draft(page)).toContainText('刷新前正文')
  control.unconfirmedBefore = 2
  control.gap = true
  await refresh(page)
  await expect(draft(page)).toContainText('写作已中断')
  await expect(page.getByTestId('report-recovery-note')).toBeVisible()
  expect(positions).toContain(2)
  expect(fake.runs).toHaveLength(1)
  expect(fake.submissions).toHaveLength(1)
})

test('report: journal replacement keeps old attempt separate from the new draft', async ({
  page,
}) => {
  const { run, control } = await setup(page)
  control.events = start(run, '旧日志中的正文')
  await refresh(page)
  await expect(draft(page)).toContainText('旧日志中的正文')
  control.journalId = crypto.randomUUID()
  control.events = start(run, '替换日志中的新正文')
  await refresh(page)
  await expect(draft(page)).toContainText('替换日志中的新正文')
  await expect(draft(page)).not.toContainText('旧日志中的正文')
  const records = (await saved(page)).reportStreams!
  expect(records).toHaveLength(2)
  expect(records[0].archived).toBe(true)
  await page.reload()
  await expect(draft(page)).toContainText('替换日志中的新正文')
})

test('report: two ongoing studies and subsequent completion keep their own drafts', async ({
  page,
}) => {
  const { run, control, fake } = await setup(page)
  control.events = start(run, '第一项研究草稿')
  await refresh(page)
  await expect(draft(page)).toContainText('第一项研究草稿')
  await page.getByRole('button', { name: '新研究', exact: true }).click()
  await page.getByRole('textbox', { name: '研究问题或补充要求' }).fill('第二项并行研究')
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled()
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect.poll(() => fake.runs.length).toBe(2)
  const second = fake.runs[1]
  fake.change({ research_phase: 'writing' }, 'running', second)
  control.events.push(...start(second, '第二项研究草稿'))
  await refresh(page)
  await expect(draft(page)).toContainText('第二项研究草稿')
  await expect(draft(page)).not.toContainText('第一项研究草稿')
  fake.succeed(run)
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(draft(page)).toContainText('第二项研究草稿')
  await expect(page.getByTestId('live-report')).toHaveCount(0)
  const studies = await page.evaluate(() =>
    JSON.parse(localStorage.getItem('atlas-workspace:v1')!).threads.flatMap(
      (item: { live?: { researches: LiveResearch[] } }) => item.live?.researches ?? [],
    ),
  )
  expect(studies.filter((item: LiveResearch) => item.reportStreams?.length)).toHaveLength(2)
  expect(fake.submissions).toHaveLength(2)
})

test('report: permanent gap never appends later text; empty failure preserves notes and sources', async ({
  page,
}) => {
  const { run, fake, control } = await setup(page)
  const events = start(run, '连续片段')
  control.events = [
    ...events,
    event(run, events[0].writing_attempt_id, 4, 'delta', 99, '禁止跨缺口拼接'),
  ]
  control.gap = true
  await refresh(page)
  await expect(draft(page)).toContainText('连续片段')
  await expect(draft(page)).not.toContainText('禁止跨缺口拼接')
  fake.change({
    research_status: 'partial',
    final_report: '',
    research_errors: [
      { code: 'report_failed', message: '写作失败；笔记仍保留。', node: 'final_report_generation' },
    ],
  })
  await refresh(page)
  await expect(page.getByTestId('live-report')).toHaveCount(0)
  await expect(page.getByText('已保留的研究笔记')).toBeVisible()
  await expect(page.getByRole('heading', { name: '检索来源 · 1' })).toBeVisible()
})

test('report: durable save failure keeps draft in memory without advancing replay position', async ({
  page,
}) => {
  const { run, control, positions } = await setup(page)
  await page.evaluate(() => {
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = function (key, value) {
      if (
        key === 'atlas-workspace:v1' &&
        JSON.parse(value).threads.some((item: { live?: { researches: LiveResearch[] } }) =>
          item.live?.researches.some((research) =>
            research.reportStreams?.some((stream) => stream.events.length > 0),
          ),
        )
      )
        throw new DOMException('Full', 'QuotaExceededError')
      return original.call(this, key, value)
    }
  })
  control.events = start(run, '内存中仍能看到')
  await refresh(page)
  await expect(draft(page)).toContainText('内存中仍能看到')
  await refresh(page)
  await expect.poll(() => positions.filter((position) => position === 0).length).toBeGreaterThan(1)
  expect((await saved(page)).reportStreams?.some((stream) => stream.sequence > 0) ?? false).toBe(
    false,
  )
})

for (const width of [1440, 320]) {
  test(`report: safe incomplete Markdown, demo isolation and layout ${width}`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 960 })
    const { run, control, fake } = await setup(page)
    control.events = start(
      run,
      '# 实际草稿\n\n| 项目 | 内容 |\n| --- | --- |\n| A | 尚未结束\n\n[未闭合链接](https://example.com\n\n<script>alert(1)</script>\n\n![外部图片](https://example.com/image.png)',
    )
    await refresh(page)
    await expect(draft(page)).toContainText('实际草稿')
    await expect(draft(page).locator('img, script')).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    )
    if (width === 1440) {
      await page.getByRole('button', { name: '全流程演示', exact: true }).click()
      await expect(page.getByTestId('live-report-draft')).toHaveCount(0)
      await page.getByRole('button', { name: '退出', exact: true }).click()
      await expect(draft(page)).toContainText('实际草稿')
    }
    await page.screenshot({ path: info.outputPath(`report-draft-${width}.png`), fullPage: true })
    expect(fake.runs).toHaveLength(1)
  })
}
