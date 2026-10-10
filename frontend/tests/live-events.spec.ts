import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { fakeLangGraph } from './langgraph-fixture'
import { readResearchEvents } from '../src/api/researchStream'
import type { ResearchEvent } from '../src/data/liveSchema'
import type { ServerRun } from '../src/api/langgraph'

const taskA = 'c09fdb03-e353-48cf-924d-4ef36aa09b61'
const taskB = 'b214aa6f-56e8-439b-8a56-fd94a25d14ae'
const taskC = '7ed6cde1-9e94-489e-85ae-0457e20c0f7f'
const node = (page: Page, id: string) => page.locator(`[data-flow-node="researcher-${id}"]`)
const status = (page: Page) => page.getByTestId('live-status').last()
const refresh = (page: Page) => page.getByRole('button', { name: '刷新状态', exact: true }).click()
const frame = (event: unknown, id = '1-0') =>
  `id: ${id}\nevent: custom\ndata: ${JSON.stringify({ type: 'atlas.research_event', event })}\n\n`

function event(
  run: ServerRun,
  sequence: number,
  kind: ResearchEvent['kind'],
  detail: Partial<ResearchEvent> = {},
): ResearchEvent {
  return {
    version: 1,
    id: crypto.randomUUID(),
    research_id: String(run.metadata.atlas_research_id),
    turn_id: String(run.metadata.atlas_turn_id),
    sequence,
    at: '2026-10-10T10:00:00+00:00',
    task_id: taskA,
    round: 1,
    kind,
    elapsed_ms: sequence * 100,
    ...detail,
  }
}

async function savedEvents(page: Page): Promise<ResearchEvent[]> {
  return page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
    return saved.threads
      .find((thread: { id: string }) => thread.id === saved.activeThreadId)
      .live.researches.at(-1).events
  })
}

async function setup(page: Page) {
  const fake = await fakeLangGraph(page)
  fake.config.research_events_version = 1
  const requests: { runId: string; cursor?: string }[] = []
  const pending: ((body: string | null) => void)[] = []
  let closed = false
  await page.route(/\/api\/threads\/[^/]+\/runs\/[^/]+\/stream\?/, async (route) => {
    requests.push({
      runId: route.request().url().split('/runs/')[1].split('/')[0],
      cursor: route.request().headers()['last-event-id'],
    })
    const body = closed ? '' : await new Promise<string | null>((resolve) => pending.push(resolve))
    if (body === null) await route.abort()
    else await route.fulfill({ contentType: 'text/event-stream', body })
  })
  async function publish(events: unknown[] | null) {
    await expect.poll(() => pending.length).toBeGreaterThan(0)
    pending.shift()!(
      events === null
        ? null
        : events.map((value, index) => frame(value, `${index + 1}-0`)).join(''),
    )
  }
  function close() {
    closed = true
    pending.splice(0).forEach((resolve) => resolve(''))
  }
  await page.goto('/')
  await page.getByRole('textbox', { name: '研究问题或补充要求' }).fill('研究事件测试')
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled()
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect.poll(() => fake.runs.length).toBe(1)
  fake.change({ research_phase: 'research', research_brief: '实际研究任务' }, 'running')
  return { ...fake, publish, requests, close }
}

test('actual streamed tasks drive parallel and later-round nodes while demo stays separate', async ({
  page,
}) => {
  const fake = await setup(page)
  try {
    const run = fake.runs[0]
    const events = [
      event(run, 1, 'delegated', { topic: '核对官方构建与 GIL' }),
      event(run, 2, 'delegated', { task_id: taskB, topic: '核对扩展兼容性' }),
      event(run, 3, 'tool_started', {
        tool: 'tavily_search',
        query: 'Python 官方 free-threading 文档',
      }),
      event(run, 4, 'tool_finished', {
        tool: 'tavily_search',
        source_count: 1,
        sources: [{ title: 'Python 文档', url: 'https://docs.python.org/3.13/' }],
      }),
      event(run, 5, 'failed', { task_id: taskB }),
      event(run, 6, 'completed', { output: '有效的研究笔记 A' }),
      event(run, 7, 'delegated', { task_id: taskC, round: 2, topic: '补充核实实验性限制' }),
      event(run, 8, 'compression_started', { task_id: taskC, round: 2 }),
    ]
    await page.getByRole('button', { name: '全流程演示' }).click()
    await fake.publish(events)
    await expect(page.locator('[data-demo]')).toHaveCount(1)
    await expect(node(page, taskA)).toHaveCount(0)
    await page.getByRole('button', { name: '退出', exact: true }).click()
    await expect(node(page, taskA)).toHaveAttribute('data-status', 'completed')
    await expect(node(page, taskB)).toHaveAttribute('data-status', 'failed')
    await expect(node(page, taskC)).toHaveAttribute('data-status', 'running')
    await expect(node(page, taskC)).toContainText('第 2 轮')
    await node(page, taskC).click()
    await expect(page.getByTestId('run-model')).toHaveText('compression-server-model')
    await node(page, taskA).click()
    await page.getByRole('tab', { name: '输入 / 输出' }).click()
    await expect(page.getByTestId('node-output')).toHaveText('有效的研究笔记 A')
    await page.getByRole('tab', { name: '执行记录' }).click()
    await expect(page.getByRole('list', { name: '节点执行时间线' })).toContainText(
      'Python 官方 free-threading 文档',
    )
    await expect(page.getByTestId('live-report')).toHaveCount(0)
    const finished = [
      ...events,
      event(run, 9, 'completed', { task_id: taskC, round: 2, output: '补充笔记' }),
    ]
    fake.succeed()
    fake.change({
      research_status: 'partial',
      research_events: finished,
      research_errors: [
        { code: 'researcher_failed', message: '一个研究任务失败。', node: 'supervisor_subgraph' },
      ],
    })
    await refresh(page)
    await expect(status(page)).toHaveAttribute('data-status', 'partial')
    await expect(node(page, taskC)).toHaveAttribute('data-status', 'completed')
    expect(fake.submissions).toHaveLength(1)
    expect(fake.submissions[0].stream_mode).toEqual(['custom'])
    expect(fake.submissions[0].stream_resumable).toBe(true)
  } finally {
    fake.close()
  }
})

test('replayed and out-of-order events deduplicate across refresh; old research and turn are rejected', async ({
  page,
}) => {
  const fake = await setup(page)
  try {
    const run = fake.runs[0]
    const delegated = event(run, 1, 'delegated', { topic: '仅属于本轮的研究任务' })
    const searching = event(run, 2, 'tool_started', { tool: 'tavily_search', query: '真实查询' })
    await fake.publish([
      searching,
      delegated,
      searching,
      { ...delegated, version: 2 },
      { ...delegated, id: crypto.randomUUID(), research_id: 'foreign-research' },
      { ...delegated, id: crypto.randomUUID(), turn_id: 'foreign-turn' },
    ])
    await expect.poll(() => savedEvents(page)).toEqual([delegated, searching])
    await page.reload()
    await fake.publish([delegated, searching])
    await expect(node(page, taskA)).toHaveAttribute('data-status', 'running')
    await expect.poll(() => savedEvents(page)).toEqual([delegated, searching])
    expect(fake.requests.slice(0, 2).map((request) => request.cursor)).toEqual(['-1', '-1'])
    fake.succeed()
    fake.change({
      research_events: [delegated, searching, event(run, 3, 'completed', { output: '本轮笔记' })],
    })
    await refresh(page)
    await expect(status(page)).toHaveAttribute('data-status', 'succeeded')
    await page.getByRole('textbox', { name: '研究问题或补充要求' }).fill('另一轮全新研究')
    await page.getByRole('button', { name: '发送消息' }).click()
    await expect.poll(() => fake.runs.length).toBe(2)
    await fake.publish([delegated, searching])
    await expect(node(page, taskA)).toHaveCount(0)
    expect(await savedEvents(page)).toEqual([])
    expect(fake.submissions).toHaveLength(2)
  } finally {
    fake.close()
  }
})

test('a failed event connection keeps polling; interrupted tasks never become completed', async ({
  page,
}) => {
  const fake = await setup(page)
  try {
    await fake.publish(null)
    await expect(page.getByText('事件重连中', { exact: true })).toBeVisible()
    const events = [
      event(fake.runs[0], 1, 'delegated', { topic: '从检查点恢复的任务' }),
      event(fake.runs[0], 2, 'model_started'),
    ]
    fake.change({ research_events: events }, 'running')
    await refresh(page)
    await expect(node(page, taskA)).toHaveAttribute('data-status', 'running')
    fake.change({}, 'error')
    await refresh(page)
    await expect(status(page)).toHaveAttribute('data-status', 'failed')
    await expect(node(page, taskA)).toHaveAttribute('data-status', 'partial')
    await expect(node(page, taskA)).toContainText('完成状态未确认')
    await page.reload()
    await expect(node(page, taskA)).toHaveAttribute('data-status', 'partial')
    await expect(page.getByTestId('live-report')).toHaveCount(0)
    expect(fake.submissions).toHaveLength(1)
  } finally {
    fake.close()
  }
})

for (const width of [1440, 390, 320]) {
  test(`researcher graph and event inspector fit ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 962 })
    await page.emulateMedia({
      reducedMotion: 'reduce',
      colorScheme: width === 390 ? 'dark' : 'light',
    })
    const fake = await setup(page)
    try {
      await fake.publish([
        event(fake.runs[0], 1, 'delegated', {
          topic: '较长的实际研究任务：比较构建、兼容性和具体适用限制',
        }),
        event(fake.runs[0], 2, 'tool_started', {
          tool: 'tavily_search',
          query: '一个较长的实际查询 https://docs.python.org/3.13/howto/free-threading-python.html',
        }),
        event(fake.runs[0], 3, 'delegated', { task_id: taskB, topic: '官方文档交叉核实' }),
        event(fake.runs[0], 4, 'failed', { task_id: taskB }),
        event(fake.runs[0], 5, 'delegated', { task_id: taskC, round: 2, topic: '第二轮补充资料' }),
      ])
      await node(page, taskA).click()
      await page.getByRole('tab', { name: '执行记录' }).click()
      await expect(page.getByRole('list', { name: '节点执行时间线' })).toBeVisible()
      expect(
        await page.locator('.cw-event').evaluateAll((events) =>
          events.every((event) => {
            const range = document.createRange()
            range.selectNodeContents(event.querySelector('.cw-event-time')!)
            return (
              range.getBoundingClientRect().right + 4 <=
              event.querySelector('.cw-event-dot')!.getBoundingClientRect().left
            )
          }),
        ),
      ).toBe(true)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      for (const id of [taskA, taskB, taskC]) {
        const box = await node(page, id).boundingBox()
        expect(box!.x).toBeGreaterThanOrEqual(0)
        expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1)
      }
      await page.screenshot({
        path: testInfo.outputPath(`research-events-${width}.png`),
        fullPage: true,
      })
    } finally {
      fake.close()
    }
  })
}

test('SSE parsing survives UTF-8 fragments, CRLF, multiline data and unrelated payloads', async () => {
  const run: ServerRun = {
    run_id: 'run',
    thread_id: 'thread',
    status: 'running',
    metadata: { atlas_research_id: 'research', atlas_turn_id: 'turn' },
  }
  const progress = event(run, 1, 'delegated', { topic: '中文跨字节事件' })
  const payload = JSON.stringify({ type: 'atlas.research_event', event: progress }, null, 2)
    .split('\n')
    .map((line) => `data: ${line}`)
    .join('\r\n')
  const encoded = new TextEncoder().encode(
    `: heartbeat\r\n\r\nevent: metadata\r\ndata: {"ignore":true}\r\n\r\nevent: custom\r\ndata: not-json\r\n\r\nid: 100-0\r\nevent: custom\r\n${payload}\r\n\r\nevent: end\r\n\r\n`,
  )
  const received: ResearchEvent[] = [],
    cursors: string[] = []
  await readResearchEvents(
    new ReadableStream({
      start(controller) {
        for (let i = 0; i < encoded.length; i += 7) controller.enqueue(encoded.slice(i, i + 7))
        controller.close()
      },
    }),
    { onEvent: (value) => received.push(value), onCursor: (value) => cursors.push(value) },
  )
  expect(received).toEqual([progress])
  expect(cursors).toEqual(['100-0'])
})
