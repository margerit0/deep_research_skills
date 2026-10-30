import { test, expect } from '@playwright/test'
import { fakeLangGraph } from './langgraph-fixture'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import history from '../src/data/recordings.json' with { type: 'json' }
import latest from '../src/data/deepseek-p0-recording.json' with { type: 'json' }
import evidence from '../docs/provider-2026-10-17-deepseek-p0-evidence.json' with { type: 'json' }

const records = [latest, ...history]

test('DeepSeek recording matches accepted report, identity and source constraints', () => {
  expect(createHash('sha256').update(latest.research.report).digest('hex')).toBe(
    evidence.native_attempt.report_sha256,
  )
  expect(latest.research.report).toBe(
    readFileSync(
      new URL('../docs/provider-2026-10-17-deepseek-p0-report.md', import.meta.url),
      'utf8',
    ).replace(/\r\n/g, '\n'),
  )
  expect(latest.threadId).toBe(evidence.native_attempt.thread_id)
  expect(latest.research.reportIdentity.writingAttemptId).toBe(
    evidence.native_attempt.writing_attempt_id,
  )
  expect(latest.research.sources.map((source) => source.url).sort()).toEqual([
    'https://docs.python.org/3.13/howto/free-threading-extensions.html',
    'https://docs.python.org/3.13/howto/free-threading-python.html',
  ])
  expect(latest.research.events).toHaveLength(42)
  expect(latest.modelHttpAttempts).toHaveLength(32)
  expect(latest.modelHttpAttempts.filter((call) => call.httpStatus === 429)).toHaveLength(3)
  for (const task of latest.research.events.filter((event) => event.kind === 'delegated')) {
    const events = latest.research.events.filter((event) => event.task_id === task.task_id)
    const loaded = events.findIndex(
      (event) =>
        event.kind === 'tool_finished' &&
        event.tool === 'load_skill' &&
        event.query === 'product-comparison',
    )
    const work = events.findIndex(
      (event) => event.kind === 'model_started' || event.tool === 'tavily_search',
    )
    expect(loaded).toBeGreaterThanOrEqual(0)
    expect(loaded).toBeLessThan(work)
  }
})

test('default tour uses accepted DeepSeek data and resets after choosing a historical recording', async ({
  page,
}) => {
  await fakeLangGraph(page)
  await page.goto('/')
  await page.getByRole('textbox').fill('保留默认演示之前的草稿')
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
  await expect(page.getByLabel('演示数据来源')).toHaveValue(latest.id)
  await expect(page.locator('.cw-demo-report')).toHaveCount(0)
  await page.getByRole('button', { name: '跳转：记录结束状态', exact: true }).click()
  await page.getByText('实测配置与记录', { exact: true }).click()
  await expect(page.locator('.cw-config-history')).toContainText('成功加载 2 次')
  await expect(page.locator('.cw-config-history')).toContainText('128000 token')
  await page.getByLabel('演示数据来源').selectOption('kimi-full')
  await expect(page.locator('[data-recording="kimi-full"]')).toBeVisible()
  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page.getByRole('textbox')).toHaveValue('保留默认演示之前的草稿')
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
  await expect(page.getByLabel('演示数据来源')).toHaveValue(latest.id)
})

test('default recording load does not flash simulation or discard changes made while loading', async ({
  page,
}) => {
  await fakeLangGraph(page)
  let release!: () => void
  const ready = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/deepseek-p0-recording.json*', async (route) => {
    await ready
    await route.continue()
  })
  await page.goto('/')
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
  await expect(page.getByRole('button', { name: '全流程演示', exact: true })).toBeDisabled()
  await expect(page.locator('[data-demo]')).toHaveCount(0)
  await page.getByRole('textbox').fill('加载期间继续编辑的草稿')
  release()
  await expect(page.getByLabel('演示数据来源')).toHaveValue(latest.id)
  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page.getByRole('textbox')).toHaveValue('加载期间继续编辑的草稿')
})

test('failed recording load keeps the workspace and does not substitute simulation', async ({
  page,
}) => {
  await fakeLangGraph(page)
  await page.route('**/deepseek-p0-recording.json*', (route) => route.abort())
  await page.goto('/')
  await page.getByRole('textbox').fill('实录加载失败时保留')
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('实录暂时无法加载')
  await expect(page.locator('[data-demo]')).toHaveCount(0)
  await expect(page.getByRole('textbox')).toHaveValue('实录加载失败时保留')
})

test('navigating away during recording load cancels delayed playback', async ({ page }) => {
  await fakeLangGraph(page)
  let release!: () => void
  const ready = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/deepseek-p0-recording.json*', async (route) => {
    await ready
    await route.continue()
  })
  await page.goto('/')
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
  await expect(page.getByRole('button', { name: '全流程演示', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'AI 搜索的下一站', exact: true }).click()
  release()
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
  await expect(page.getByLabel('演示数据来源')).toHaveValue(latest.id)
  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page.locator('.cw-header-title h1')).toHaveText('AI 搜索的下一站')
})

for (const record of records) {
  test(`${record.id}: real playback preserves recorded outcome without execution or storage changes`, async ({
    page,
  }) => {
    await fakeLangGraph(page)
    let posts = 0
    page.on('request', (request) => {
      if (
        request.method() === 'POST' &&
        /\/(threads|runs|submissions|recoveries)(\/|$)/.test(new URL(request.url()).pathname)
      )
        posts++
    })
    await page.goto('/')
    await page.clock.install({ time: new Date('2026-10-13T00:00:00Z') })
    await page.clock.pauseAt(new Date('2026-10-13T00:00:01Z'))
    const before = await page.evaluate(() =>
      JSON.parse(localStorage.getItem('atlas-workspace:v1')!),
    )
    await page.getByRole('button', { name: '全流程演示', exact: true }).click()
    await page.getByLabel('演示数据来源').selectOption(record.id)
    await expect(page.locator(`[data-recording="${record.id}"]`)).toContainText('真实记录回放')
    await page.getByRole('button', { name: '跳转：实际澄清', exact: true }).click()
    await expect(page.locator(`[data-recording="${record.id}"]`)).toContainText(
      record.research.messages[1].content.slice(0, 16),
    )
    await expect(page.getByTestId('run-model')).toHaveText(
      record.research.config.models.find((item) => item.role === 'SCOPING')!.model,
    )
    await page.getByRole('button', { name: '跳转：记录结束状态', exact: true }).click()
    await expect(page.getByTestId('recorded-status')).toHaveAttribute(
      'data-status',
      record.research.status,
    )
    if (!record.research.report) await expect(page.getByTestId('recorded-report')).toHaveCount(0)
    await expect(page.locator('.cw-demo-report')).toHaveCount(0)
    await expect(page.locator('.cw-graph-subheader')).toContainText('真实记录')
    await expect(page.locator('.cw-graph-header [role="status"]')).toHaveText(
      record.observationEnded
        ? '记录中断'
        : record.research.status === 'succeeded'
          ? '研究完成'
          : '研究失败',
    )
    if (record.research.sources.length) {
      await expect(page.getByTestId('recorded-brief')).toContainText(record.research.brief)
      const sources = page.getByRole('region', { name: '实录检索来源' }).getByRole('link')
      expect(
        await sources.evaluateAll((links) => links.map((link) => link.getAttribute('href'))),
      ).toEqual(record.research.sources.map((source) => source.url))
    }
    if (record.research.report) {
      await expect(page.getByTestId('recorded-report')).toContainText(
        record.research.report.split('\n')[0].replace(/^#+\s*/, ''),
      )
      for (const note of record.acceptanceNotes ?? [])
        await expect(page.getByRole('complementary', { name: '实录验收说明' })).toContainText(note)
      await expect(page.locator('.cw-fork[data-status="failed"]')).toHaveCount(0)
      await expect(page.locator('.cw-fork[data-status="completed"]')).toHaveCount(
        record.research.events.filter((event) => event.kind === 'completed').length,
      )
      await expect(page.locator('[data-flow-node="report"]')).toHaveAttribute(
        'data-status',
        'completed',
      )
      await page.getByRole('tab', { name: '输入 / 输出', exact: true }).click()
      await expect(page.getByTestId('node-output')).toHaveText(record.research.report)
      await page.getByRole('tab', { name: '执行记录', exact: true }).click()
      await expect(page.getByRole('tabpanel').filter({ visible: true })).toContainText('响应头')
      await page.getByRole('button', { name: '跳转：实际研究事件', exact: true }).click()
      await expect(page.getByTestId('recorded-report')).toHaveCount(0)
      await page.getByRole('button', { name: '跳转：实际报告与来源', exact: true }).click()
      await expect(page.getByTestId('recorded-report')).toBeVisible()
      await expect(page.getByTestId('recorded-status')).toHaveCount(0)
      await page.getByRole('button', { name: '跳转：记录结束状态', exact: true }).click()
    } else {
      await expect(
        page.getByRole('button', { name: '跳转：实际报告与来源', exact: true }),
      ).toHaveCount(0)
    }
    if (record.id === 'kimi') {
      await expect(page.locator('.cw-fork[data-status="failed"]')).toHaveCount(1)
      await expect(page.locator('.cw-fork[data-status="completed"]')).toHaveCount(1)
      await expect(page.locator('.cw-detail-stats')).toContainText('HTTP 尝试2')
      await page.getByRole('tab', { name: '执行记录', exact: true }).click()
      await expect(
        page.getByRole('list', { name: '节点执行时间线' }).getByRole('listitem'),
      ).toHaveCount(2)
      await expect(page.getByRole('tabpanel').filter({ visible: true })).toContainText('响应未记录')
      await page.locator('[data-flow-node="supervisor"]').click()
      await page.getByRole('tab', { name: '输入 / 输出', exact: true }).click()
      await expect(page.getByTestId('node-output')).toHaveText(record.research.notes.join('\n\n'))
    }
    await page.clock.runFor(6000)
    expect(posts).toBe(0)
    expect(
      await page.evaluate(() => JSON.parse(localStorage.getItem('atlas-workspace:v1')!)),
    ).toEqual(before)
    await page.getByLabel('演示数据来源').selectOption('simulated')
    await page.getByRole('button', { name: '跳转：报告已就绪', exact: true }).click()
    await expect(page.locator('.cw-demo-report')).toContainText('研究摘要（模拟）')
    await page.getByRole('button', { name: '退出', exact: true }).click()
    expect(
      await page.evaluate(() => JSON.parse(localStorage.getItem('atlas-workspace:v1')!)),
    ).toEqual(before)
    expect(posts).toBe(0)
  })
}

for (const record of records.filter((item) => item.id !== 'backoff')) {
  for (const width of [1440, 320]) {
    test(`${record.id}: real playback fits ${width}px and reload restores the original workspace`, async ({
      page,
    }, testInfo) => {
      await fakeLangGraph(page)
      await page.setViewportSize({ width, height: 962 })
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await page.goto('/')
      const before = await page.evaluate(() =>
        JSON.parse(localStorage.getItem('atlas-workspace:v1')!),
      )
      await page.getByRole('button', { name: '全流程演示', exact: true }).click()
      await page.getByLabel('演示数据来源').selectOption(record.id)
      // Freeze the timeline before checking a chapter's scroll position.
      await page.getByRole('button', { name: '暂停演示' }).click()
      await page.getByRole('button', { name: '跳转：记录结束状态', exact: true }).click()
      await expect(page.getByTestId('recorded-status')).toBeInViewport({ ratio: 0.9 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await page.screenshot({ path: testInfo.outputPath(`recorded-${record.id}-${width}.png`) })
      if (record.research.report) {
        await page.getByRole('button', { name: '跳转：实际报告与来源', exact: true }).click()
        await page.getByTestId('recorded-report').scrollIntoViewIfNeeded()
        await expect(page.getByTestId('recorded-report')).toBeVisible()
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        )
        await page.screenshot({ path: testInfo.outputPath(`recorded-report-${width}.png`) })
      }
      await page.reload()
      await expect(page.getByRole('region', { name: '全流程演示控制' })).toHaveCount(0)
      expect(
        await page.evaluate(() => JSON.parse(localStorage.getItem('atlas-workspace:v1')!)),
      ).toEqual(before)
    })
  }
}
