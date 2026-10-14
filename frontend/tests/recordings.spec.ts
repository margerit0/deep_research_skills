import { test, expect } from '@playwright/test'
import { fakeLangGraph } from './langgraph-fixture'
import records from '../src/data/recordings.json' with { type: 'json' }

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
      record.observationEnded ? '记录中断' : '研究失败',
    )
    if (record.id === 'kimi') {
      await expect(page.getByTestId('recorded-brief')).toContainText(record.research.brief)
      const sources = page.getByRole('region', { name: '实录检索来源' }).getByRole('link')
      expect(
        await sources.evaluateAll((links) => links.map((link) => link.getAttribute('href'))),
      ).toEqual(record.research.sources.map((source) => source.url))
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

for (const width of [1440, 320]) {
  test(`real playback fits ${width}px and reload restores the original workspace`, async ({
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
    await page.getByLabel('演示数据来源').selectOption(records.at(-1)!.id)
    await page.getByRole('button', { name: '跳转：记录结束状态', exact: true }).click()
    await page.getByRole('button', { name: '暂停演示' }).click()
    await expect(page.getByTestId('recorded-status')).toBeInViewport({ ratio: 0.9 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`recorded-${width}.png`) })
    await page.reload()
    await expect(page.getByRole('region', { name: '全流程演示控制' })).toHaveCount(0)
    expect(
      await page.evaluate(() => JSON.parse(localStorage.getItem('atlas-workspace:v1')!)),
    ).toEqual(before)
  })
}
