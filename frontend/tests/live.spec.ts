import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { fakeLangGraph, fakeConfig } from './langgraph-fixture'

const input = (page: Page) => page.getByRole('textbox', { name: '研究问题或补充要求' })
const status = (page: Page) => page.getByTestId('live-status').last()
const refresh = (page: Page) => page.getByRole('button', { name: '刷新状态', exact: true }).click()
async function send(page: Page, text = '研究测试主题') {
  await input(page).fill(text)
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled()
  await page.getByRole('button', { name: '发送消息' }).click()
}
async function saved(page: Page) {
  return page.evaluate(() => {
    const workspace = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
    return workspace.threads.find(
      (thread: { id: string }) => thread.id === workspace.activeThreadId,
    )
  })
}

test('real mode exposes actual roles and automatic Skills without fake selectors', async ({
  page,
}) => {
  const fake = await fakeLangGraph(page)
  await page.goto('/')
  await page.getByRole('button', { name: '查看后端模型' }).click()
  await expect(page.getByRole('region', { name: '后端实际配置' })).toContainText(
    'researcher-server-model',
  )
  await expect(page.locator('.cw-backend-role')).toHaveCount(6)
  await expect(page.getByRole('button', { name: '选择Skills' })).toHaveCount(0)
  await expect(page.getByRole('menuitemradio')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: '查看后端模型' })).toBeFocused()
  expect(fake.submissions).toHaveLength(0)
})

test('a restarted backend configuration is reread before submission; old snapshots stay intact', async ({
  page,
}) => {
  const fake = await fakeLangGraph(page)
  await page.goto('/')
  await send(page, '原配置研究')
  await expect.poll(() => fake.runs.length).toBe(1)
  fake.succeed()
  await refresh(page)
  await expect(status(page)).toHaveAttribute('data-status', 'succeeded')
  fake.config.models = fake.config.models.map((model) => ({
    ...model,
    model: 'updated-server-model',
  }))
  await send(page, '更新配置后的研究')
  await expect.poll(() => fake.runs.length).toBe(2)
  await expect(page.getByRole('button', { name: '查看后端模型' })).toContainText(
    'updated-server-model',
  )
  const thread = await saved(page)
  expect(thread.live.researches[0].config).toEqual(fakeConfig)
  expect(thread.live.researches[1].config).toEqual(fake.config)
})

test('clarification, same-thread answer, actual brief, report and source survive reload', async ({
  page,
}) => {
  const fake = await fakeLangGraph(page)
  await page.goto('/')
  await send(page)
  await expect.poll(() => fake.runs.length).toBe(1)
  fake.clarify()
  await refresh(page)
  await expect(status(page)).toHaveAttribute('data-status', 'awaiting_input')
  await expect(page.locator('.cw-agent-text')).toHaveText('请补充比较对象和时间范围。')
  await expect(page.getByTestId('live-report')).toHaveCount(0)
  const first = await saved(page)
  await page.reload()
  await expect(status(page)).toHaveAttribute('data-status', 'awaiting_input')
  await send(page, '比较 A 和 B，只看 2026 年。')
  await expect.poll(() => fake.runs.length).toBe(2)
  expect(fake.runs[0].thread_id).toBe(fake.runs[1].thread_id)
  expect(fake.submissions[0].input.research_id).toBe(fake.submissions[1].input.research_id)
  expect(fake.submissions[0].input.turn_id).not.toBe(fake.submissions[1].input.turn_id)
  expect(fake.submissions[1].input.messages).toHaveLength(1)
  expect(fake.submissions[1].multitask_strategy).toBe('reject')
  expect(fake.submissions[1].assistant_id).toBe('research_agent_full')
  expect(Object.keys(fake.submissions[1])).not.toContain('config')
  fake.change(
    { research_phase: 'research', research_status: 'running', research_brief: '确认后的真实简报' },
    'running',
  )
  await refresh(page)
  await page.getByRole('button', { name: /研究简报.*查看实际简报/ }).click()
  await page.getByRole('tab', { name: '输入 / 输出' }).click()
  await expect(page.getByTestId('node-output')).toHaveText('确认后的真实简报')
  fake.succeed()
  await refresh(page)
  await expect(status(page)).toHaveAttribute('data-status', 'succeeded')
  await expect(page.getByTestId('live-report')).toContainText('可核验的研究结论')
  await expect(page.getByTestId('live-report').locator('table')).toHaveCount(1)
  await expect(page.getByTestId('live-report').locator('img,script')).toHaveCount(0)
  await expect(page.getByRole('region', { name: '检索来源' }).getByRole('link')).toHaveAttribute(
    'href',
    'https://example.com/source',
  )
  await page.reload()
  await expect(page.getByTestId('live-report')).toContainText('可核验的研究结论')
  expect(fake.submissions).toHaveLength(2)
  const final = await saved(page)
  expect(final.live.threadId).toBe(first.live.threadId)
  expect(final.live.researches).toHaveLength(1)
  expect(final.live.researches[0].turns).toHaveLength(2)
  expect(final.live.researches[0].config).toEqual(fakeConfig)
})

test('native failure wins over old state; a new research cannot inherit a previous report', async ({
  page,
}) => {
  const fake = await fakeLangGraph(page)
  await page.goto('/')
  await send(page, '第一轮研究')
  await expect.poll(() => fake.runs.length).toBe(1)
  fake.succeed()
  await refresh(page)
  await expect(status(page)).toHaveAttribute('data-status', 'succeeded')
  fake.controls.preservePreviousState = true
  await send(page, '完全不同的新研究')
  await expect.poll(() => fake.runs.length).toBe(2)
  expect(fake.runs[0].thread_id).toBe(fake.runs[1].thread_id)
  expect(fake.submissions[0].input.research_id).not.toBe(fake.submissions[1].input.research_id)
  await refresh(page)
  await expect(page.locator('[data-source="live"]').last().getByTestId('live-report')).toHaveCount(
    0,
  )
  fake.change({}, 'error')
  await refresh(page)
  await expect(status(page)).toHaveAttribute('data-status', 'failed')
  await expect(page.locator('[data-source="live"]').last()).toContainText('服务端运行失败')
  await page.reload()
  await expect(page.getByTestId('live-report')).toHaveCount(1)
  await expect(status(page)).toHaveAttribute('data-status', 'failed')
  expect(fake.submissions).toHaveLength(2)
})

for (const withReport of [false, true]) {
  test(`partial research preserves ${withReport ? 'report' : 'notes'} without success label`, async ({
    page,
  }) => {
    const fake = await fakeLangGraph(page)
    await page.goto('/')
    await send(page)
    await expect.poll(() => fake.runs.length).toBe(1)
    if (withReport) fake.succeed()
    fake.change({
      research_status: 'partial',
      research_phase: withReport ? 'complete' : 'writing',
      notes: ['保留下来的有效研究笔记'],
      research_errors: [
        {
          code: 'report_failed',
          message: '部分任务失败，已保留有效结果。',
          node: 'final_report_generation',
        },
      ],
    })
    await refresh(page)
    await expect(status(page)).toHaveAttribute('data-status', 'partial')
    await expect(page.locator('.cw-research-errors')).toContainText('部分任务失败')
    if (withReport) await expect(page.getByTestId('live-report')).toContainText('部分完成')
    else await expect(page.locator('details')).toContainText('保留下来的有效研究笔记')
    await expect(
      page.getByRole('complementary', { name: '运行图谱' }).getByRole('status'),
    ).toHaveText('部分完成')
  })
}

test('lost POST response is found by turn metadata; reload and retry-read never POST again', async ({
  page,
}) => {
  const fake = await fakeLangGraph(page)
  fake.controls.loseResponse = true
  await page.goto('/')
  await send(page)
  await expect.poll(() => fake.runs.length).toBe(1)
  await page.reload()
  fake.clarify()
  await refresh(page)
  await expect(status(page)).toHaveAttribute('data-status', 'awaiting_input')
  expect(fake.submissions).toHaveLength(1)
  expect((await saved(page)).live.researches[0].turns[0].runId).toBe(fake.runs[0].run_id)
})

test('ambiguous unaccepted submission stays blocked across reload without automatic recreation', async ({
  page,
}) => {
  const fake = await fakeLangGraph(page)
  fake.controls.rejectBeforeRun = true
  await page.goto('/')
  await send(page)
  await expect.poll(() => fake.submissions.length).toBe(1)
  await expect(page.locator('.cw-connection-alert')).toContainText('未找到对应运行')
  await page.reload()
  await input(page).fill('不应重复启动')
  await expect(page.getByRole('button', { name: '发送消息' })).toBeDisabled()
  await page.getByRole('button', { name: '重新读取状态' }).click()
  await expect(page.locator('.cw-connection-alert')).toContainText('不会自动重复提交')
  expect(fake.submissions).toHaveLength(1)
  expect(fake.runs).toHaveLength(0)
})

test('refresh restores active running state and backend completion while another thread is selected', async ({
  page,
}) => {
  const fake = await fakeLangGraph(page)
  await page.goto('/')
  await send(page, '第一条后台研究')
  await expect.poll(() => fake.runs.length).toBe(1)
  const first = fake.runs[0]
  await page.reload()
  await expect(status(page)).toHaveAttribute('data-status', 'running')
  await page.getByRole('button', { name: '新研究', exact: true }).click()
  await send(page, '第二条后台研究')
  await expect.poll(() => fake.runs.length).toBe(2)
  fake.succeed(first)
  await expect(page.getByTestId('live-report')).toHaveCount(0)
  await page.getByRole('button', { name: '第一条后台研究', exact: true }).click()
  await expect(status(page)).toHaveAttribute('data-status', 'succeeded', { timeout: 10000 })
  await expect(page.getByTestId('live-report')).toContainText('实际研究报告')
  expect(fake.submissions).toHaveLength(2)
})

test('unavailable local storage prevents real submission before network writes', async ({
  page,
}) => {
  const fake = await fakeLangGraph(page)
  await page.addInitScript(() => {
    Storage.prototype.setItem = () => {
      throw new DOMException('Full', 'QuotaExceededError')
    }
  })
  await page.goto('/')
  await input(page).fill('不能丢失的研究请求')
  await input(page).press('Enter')
  await expect(page.getByRole('button', { name: '发送消息' })).toBeDisabled()
  expect(fake.submissions).toHaveLength(0)
  expect(fake.threads.size).toBe(0)
})

test('demo remains separate while a real research finishes in the background', async ({ page }) => {
  const fake = await fakeLangGraph(page)
  await page.goto('/')
  await send(page)
  await expect.poll(() => fake.runs.length).toBe(1)
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
  await page.getByRole('button', { name: '跳转：实际报告与来源', exact: true }).click()
  await expect(page.getByTestId('recorded-report')).toBeVisible()
  fake.succeed()
  await expect
    .poll(async () => {
      const workspace = await page.evaluate(() =>
        JSON.parse(localStorage.getItem('atlas-workspace:v1')!),
      )
      return workspace.threads.find((thread: { source?: string }) => thread.source === 'live').live
        .researches[0].status
    })
    .toBe('succeeded')
  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page.getByTestId('live-report')).toContainText('实际研究报告')
  await expect(page.getByTestId('recorded-report')).toHaveCount(0)
  expect(fake.submissions).toHaveLength(1)
})

for (const width of [1440, 390, 320]) {
  test(`live layout ${width}: report, sources and fixed config`, async ({ page }, testInfo) => {
    const fake = await fakeLangGraph(page)
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.setViewportSize({ width, height: 962 })
    await page.emulateMedia({
      colorScheme: width === 390 ? 'dark' : 'light',
      reducedMotion: 'reduce',
    })
    await page.goto('/')
    await send(page)
    await expect.poll(() => fake.runs.length).toBe(1)
    fake.succeed()
    await refresh(page)
    await expect(status(page)).toHaveAttribute('data-status', 'succeeded')
    await expect(page.getByTestId('live-report')).toContainText('可核验的研究结论')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.getByRole('button', { name: '查看后端模型' }).click()
    const menu = page.getByRole('region', { name: '后端实际配置' })
    const box = await menu.boundingBox()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    await expect(menu).toHaveCSS('backdrop-filter', 'none')
    await page.screenshot({ path: testInfo.outputPath(`live-${width}.png`), fullPage: true })
    expect(errors).toEqual([])
  })
}
