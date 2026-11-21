import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const browserErrors = new WeakMap<Page, string[]>()

test.beforeEach(async ({ page }) => {
  const errors: string[] = []
  browserErrors.set(page, errors)
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'warning' || message.type() === 'error') errors.push(message.text())
  })
  await page.goto('/m0/workflow.html')
  await expect(page.getByTestId('m0-counts')).toHaveText('4 个节点 · 3 条连线')
})

test.afterEach(async ({ page }) => {
  expect(browserErrors.get(page)).toEqual([])
})

test('M0 canvas: add, drag, connect and delete a node with its edge', async ({ page }) => {
  await page.getByRole('button', { name: '添加处理步骤' }).click()
  await expect(page.getByTestId('m0-counts')).toHaveText('5 个节点 · 3 条连线')
  const added = page.locator('.react-flow__node[data-id="extension-1"]')
  const initial = await added.boundingBox()
  expect(initial).not.toBeNull()
  await page.mouse.move(initial!.x + 60, initial!.y + 40)
  await page.mouse.down()
  await page.mouse.move(initial!.x + 140, initial!.y + 70, { steps: 10 })
  await page.mouse.up()
  const moved = await added.boundingBox()
  expect(moved!.x - initial!.x).toBeGreaterThan(50)
  const source = page.locator('.react-flow__node[data-id="core-1"] .react-flow__handle.source')
  const target = added.locator('.react-flow__handle.target')
  await source.dragTo(target)
  await expect(page.getByTestId('m0-counts')).toHaveText('5 个节点 · 4 条连线')
  await added.click()
  await page.getByRole('button', { name: '删除所选步骤' }).click()
  await expect(page.getByTestId('m0-counts')).toHaveText('4 个节点 · 3 条连线')
  await expect(added).toHaveCount(0)
})

test('M0 canvas: Dagre layout, keyboard deletion and locked nodes', async ({ page }) => {
  const zoomIcon = await page.locator('.react-flow__controls-zoomin svg').boundingBox()
  expect(zoomIcon!.width).toBeGreaterThan(10)
  const viewport = page.locator('.react-flow__viewport')
  const originalTransform = await viewport.getAttribute('style')
  await page.locator('.react-flow__controls-zoomin').click()
  await expect(viewport).not.toHaveAttribute('style', originalTransform!)
  await page.getByRole('button', { name: '添加处理步骤' }).click()
  await page.getByRole('button', { name: '自动排列' }).click()
  await page.getByRole('button', { name: '适应画布' }).click()
  const added = page.locator('.react-flow__node[data-id="extension-1"]')
  await added.click()
  await page.keyboard.press('Delete')
  await expect(page.getByTestId('m0-counts')).toHaveText('4 个节点 · 3 条连线')
  await page.locator('.react-flow__node[data-id="core-1"]').click()
  await page.keyboard.press('Delete')
  await expect(page.getByTestId('m0-counts')).toHaveText('4 个节点 · 3 条连线')
})

test('M0 canvas: desktop and narrow layouts with dark theme', async ({ page }, info) => {
  await info.attach('browser-environment', {
    contentType: 'application/json',
    body: JSON.stringify({
      browser: page.context().browser()?.version(),
      widths: [1440, 1024, 390, 320],
    }),
  })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  for (const width of [1440, 1024, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await page.getByRole('button', { name: '适应画布' }).click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await expect(page.getByRole('heading', { name: '流程画布' })).toBeVisible()
    await page.screenshot({ path: info.outputPath(`canvas-light-${width}.png`), fullPage: true })
  }
  await page.getByRole('button', { name: '切换深色' }).click()
  await expect(page.locator('.react-flow')).toHaveClass(/dark/)
  await page.screenshot({ path: info.outputPath('canvas-dark-320.png'), fullPage: true })
})
