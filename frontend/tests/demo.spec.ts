import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { fakeLangGraph } from './langgraph-fixture'

test.beforeEach(async ({ page }) => {
  await fakeLangGraph(page)
})

const player = (page: Page) => page.getByRole('region', { name: '全流程演示控制' })
const saved = (page: Page) =>
  page.evaluate(() => JSON.parse(localStorage.getItem('atlas-workspace:v1')!))
async function start(page: Page) {
  await page.goto('/')
  await page.clock.install({ time: new Date('2026-10-10T00:00:00Z') })
  await page.clock.pauseAt(new Date('2026-10-10T00:00:01Z'))
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
}
async function seek(page: Page, name: string) {
  await page.getByRole('button', { name: `跳转：${name}`, exact: true }).click()
}

test('automatic tour covers menus, streaming, research, inspector, report and appearance without external calls', async ({
  page,
}, testInfo) => {
  test.setTimeout(60000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('request', (request) => {
    if (
      !request.url().startsWith(testInfo.project.use.baseURL!) &&
      !request.url().startsWith('data:')
    )
      errors.push(request.url())
  })
  await start(page)
  const before = await saved(page)
  await page.clock.runFor(3060)
  await expect(page.getByRole('menu', { name: '模型列表' })).toBeVisible()
  await expect(page.getByRole('button', { name: '暂停演示' })).toBeFocused()
  await page.clock.runFor(2520)
  await expect(page.getByRole('menu', { name: 'Skills列表' })).toBeVisible()
  await page.clock.runFor(3000)
  const prompt = page.getByRole('textbox')
  expect((await prompt.inputValue()).length).toBeGreaterThan(0)
  expect((await prompt.inputValue()).length).toBeLessThan(40)
  await page.clock.runFor(4500)
  await expect(page.locator('.cw-agent-text')).toHaveAttribute('data-streaming', 'true')
  await page.clock.runFor(13500)
  await expect(player(page)).toHaveAttribute('data-scene', 'search')
  await expect(page.locator('.cw-node[data-status="running"]')).toHaveCount(4)
  await expect(page.locator('.cw-wire-flash.is-flowing').first()).toHaveCSS(
    'animation-name',
    'cw-wire-travel',
  )
  await page.clock.runFor(5100)
  await expect(page.getByRole('tab', { name: '输入 / 输出' })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await page.clock.runFor(3500)
  await expect(page.getByRole('tab', { name: '执行记录' })).toHaveAttribute('aria-selected', 'true')
  await page.clock.runFor(7500)
  await expect(player(page)).toHaveAttribute('data-scene', 'writing')
  await expect(page.locator('.cw-demo-report')).toHaveAttribute('data-streaming', 'true')
  await page.clock.runFor(11000)
  await expect(player(page)).toHaveAttribute('data-scene', 'collapse')
  await expect(page.getByRole('complementary', { name: '运行图谱' })).toHaveCount(0)
  await page.clock.runFor(6000)
  await expect(player(page)).toHaveAttribute('data-scene', 'appearance')
  await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark')
  await page.clock.runFor(6000)
  await expect(page.getByRole('button', { name: '重播全流程演示' })).toBeVisible()
  await expect(page.locator('.cw-demo-report')).toContainText('不含真实产品评价')
  expect(await saved(page)).toEqual(before)
  expect(errors).toEqual([])
})

test('pause freezes text and time, speed, seeking, manual inspection, replay and hidden tab pause', async ({
  page,
}) => {
  await start(page)
  await seek(page, '研究助手回应')
  await page.clock.runFor(900)
  await page.getByRole('button', { name: '暂停演示' }).click()
  const reply = await page.locator('.cw-agent-text').textContent()
  const time = await page.locator('.cw-demo-footnote .cw-mono').textContent()
  await page.clock.runFor(5000)
  expect(await page.locator('.cw-agent-text').textContent()).toBe(reply)
  expect(await page.locator('.cw-demo-footnote .cw-mono').textContent()).toBe(time)
  await page.getByRole('button', { name: '播放速度 1 倍，点击切换' }).click()
  await page.getByRole('button', { name: '播放速度 1.5 倍，点击切换' }).click()
  await page.getByRole('button', { name: '继续演示' }).click()
  await page.clock.runFor(2000)
  await expect(player(page)).toHaveAttribute('data-scene', 'scope')
  await seek(page, '并行检索资料')
  await page.locator('[data-flow-node="report"]').click()
  await expect(page.getByRole('button', { name: '继续演示' })).toBeVisible()
  await page.getByRole('tab', { name: '输入 / 输出' }).click()
  await expect(page.getByTestId('node-output')).toHaveText('尚未执行，暂无输出。')
  await expect(page.getByRole('tabpanel').filter({ visible: true })).toHaveCSS('opacity', '1')
  await page.getByRole('button', { name: '从头重播演示' }).click()
  await expect(player(page)).toHaveAttribute('data-scene', 'welcome')
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await expect(page.getByRole('button', { name: '继续演示' })).toBeVisible()
  await page.clock.runFor(9000)
  await expect(player(page)).toHaveAttribute('data-scene', 'welcome')
})

test('exit, reload and navigation preserve original drafts, snapshots and preferences', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'AI 搜索的下一站', exact: true }).click()
  await page.getByRole('textbox').fill('保留这份未发送的草稿')
  await page.getByRole('button', { name: '外观：跟随系统' }).click()
  const before = await saved(page)
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
  await seek(page, '另一种光线')
  await page.getByRole('button', { name: '暂停演示' }).click()
  await page.getByRole('button', { name: '选择模型', exact: true }).click()
  await page.getByRole('menuitemradio', { name: 'GPT-4o' }).click()
  await expect(page.getByTestId('run-model')).toHaveText('Qwen3.5')
  expect(await saved(page)).toEqual(before)
  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page.getByRole('textbox')).toHaveValue('保留这份未发送的草稿')
  await expect(page.locator('html')).toHaveCSS('color-scheme', 'light')
  await expect(page.getByRole('button', { name: '全流程演示', exact: true })).toBeFocused()
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
  await seek(page, '撰写研究报告')
  await page.reload()
  await expect(player(page)).toHaveCount(0)
  expect(await saved(page)).toEqual(before)
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
  await page.getByRole('button', { name: 'AI 搜索的下一站', exact: true }).click()
  await expect(player(page)).toHaveCount(0)
  expect(await saved(page)).toEqual(before)
})

for (const width of [1440, 1024, 390, 320]) {
  test(`tour layout ${width}, reduced motion and screenshots`, async ({ browser }, testInfo) => {
    const context = await browser.newContext({
      viewport: { width, height: 962 },
      hasTouch: width < 661,
      isMobile: width < 661,
      colorScheme: width === 1024 ? 'dark' : 'light',
      reducedMotion: 'reduce',
    })
    const page = await context.newPage()
    await start(page)
    await page.getByRole('button', { name: '暂停演示' }).click()
    for (const name of [
      '选择研究方法',
      '并行检索资料',
      '跟随执行记录',
      '撰写研究报告',
      '专注阅读',
    ]) {
      await seek(page, name)
      await page.clock.runFor(300)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await expect(player(page)).toBeInViewport()
      if (name === '并行检索资料') {
        if (width < 661) {
          const controls = await player(page).boundingBox()
          const graph = await page.locator('.cw-flow').boundingBox()
          expect(controls!.height).toBeLessThan(230)
          expect(graph!.y).toBeGreaterThanOrEqual(controls!.y + controls!.height)
          await expect(page.locator('.cw-flow')).toBeInViewport({ ratio: 0.95 })
        }
        await expect(page.locator('.cw-wire-flash').first()).toHaveCSS('animation-name', 'none')
        await page.screenshot({
          path: testInfo.outputPath(`demo-${width}-research.png`),
          fullPage: true,
        })
      }
      if (name === '撰写研究报告') {
        await expect(page.locator('.cw-demo-report')).toContainText('不含真实产品评价')
        await page.screenshot({
          path: testInfo.outputPath(`demo-${width}-report.png`),
          fullPage: true,
        })
      }
    }
    if (width < 661) {
      for (const button of await player(page).getByRole('button').all()) {
        const bounds = await button.boundingBox()
        expect(bounds!.width).toBeGreaterThanOrEqual(44)
        expect(bounds!.height).toBeGreaterThanOrEqual(44)
      }
    }
    await context.close()
  })
}
