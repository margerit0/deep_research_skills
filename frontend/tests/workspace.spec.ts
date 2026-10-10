import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { fakeLangGraph } from './langgraph-fixture'

const input = (page: Page) => page.getByRole('textbox', { name: '研究问题或补充要求' })
const inspector = (page: Page) => page.getByRole('region', { name: '节点检查器', exact: true })
async function pick(page: Page, menu: '模型' | 'Skills', value: string) {
  await page.getByRole('button', { name: `选择${menu}`, exact: true }).click()
  await page.getByRole('menuitemradio', { name: value, exact: true }).click()
}
async function saved(page: Page) {
  return page.evaluate(() => JSON.parse(localStorage.getItem('atlas-workspace:v1')!))
}

test.beforeEach(async ({ page }) => {
  await fakeLangGraph(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'AI 搜索的下一站', exact: true }).click()
})

test('menus: icons, solid surface, keyboard selection, exclusivity, Escape and outside click', async ({
  page,
}) => {
  const model = page.getByRole('button', { name: '选择模型', exact: true })
  const skill = page.getByRole('button', { name: '选择Skills', exact: true })
  await expect(model.locator('svg')).toHaveCount(1)
  await expect(skill.locator('svg')).toHaveCount(2)
  await model.focus()
  await page.keyboard.press('ArrowDown')
  await expect(page.getByRole('menuitemradio', { name: 'Qwen3.5' })).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(model).toContainText('DeepSeek V3.2')
  await expect(model).toBeFocused()
  await model.click()
  await skill.click()
  await expect(page.getByRole('menu')).toHaveCount(1)
  await expect(page.getByRole('menu', { name: 'Skills列表' })).toHaveCSS('backdrop-filter', 'none')
  await page.keyboard.press('End')
  await page.keyboard.press('Enter')
  await expect(skill).toContainText('人物调研')
  await skill.click()
  await page.keyboard.press('Escape')
  await expect(skill).toBeFocused()
  await expect(page.getByRole('menu')).toHaveCount(0)
  await model.click()
  await page.locator('h1').click()
  await expect(page.getByRole('menu')).toHaveCount(0)
})

test('send, IME, immutable run snapshots, drafts and reload across multiple threads', async ({
  page,
}) => {
  await pick(page, '模型', 'DeepSeek V3.2')
  await pick(page, 'Skills', '学术研究')
  await expect(page.getByTestId('run-model')).toHaveText('Qwen3.5')
  await page.locator('nav[aria-label="研究对话导航"] .cw-new-chat').click()
  await input(page).fill('中文输入')
  await input(page).dispatchEvent('compositionstart')
  await input(page).press('Enter')
  await expect(page.locator('.cw-message-pair')).toHaveCount(0)
  await input(page).dispatchEvent('compositionend')
  await input(page).fill('量子计算的研究进展')
  await input(page).press('Shift+Enter')
  await input(page).press('KeyA')
  await expect(input(page)).toHaveValue('量子计算的研究进展\na')
  await input(page).press('Enter')
  await expect(page.locator('.cw-message-pair')).toHaveCount(1)
  await expect(page.getByTestId('run-model')).toHaveText('DeepSeek V3.2')
  await pick(page, '模型', 'GPT-4o')
  await pick(page, 'Skills', '人物调研')
  await expect(page.getByTestId('run-model')).toHaveText('DeepSeek V3.2')
  await input(page).fill('补充人物背景')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.locator('.cw-message-pair')).toHaveCount(2)
  await expect(page.getByTestId('run-model')).toHaveText('GPT-4o')
  await page.getByRole('button', { name: '查看当前步骤' }).first().click()
  await expect(page.getByTestId('run-model')).toHaveText('DeepSeek V3.2')
  await input(page).fill('尚未发送的草稿')
  await page.getByRole('button', { name: 'AI 搜索的下一站', exact: true }).click()
  await expect(input(page)).toHaveValue('')
  const state = await saved(page)
  const custom = state.threads.find((t: { id: string }) => t.id !== 'example')
  await page.getByRole('button', { name: custom.title, exact: true }).click()
  await expect(input(page)).toHaveValue('尚未发送的草稿')
  await page.reload()
  await expect(input(page)).toHaveValue('尚未发送的草稿')
  await expect(page.getByTestId('run-model')).toHaveText('DeepSeek V3.2')
  await expect(page.getByRole('button', { name: '选择模型', exact: true })).toContainText('GPT-4o')
  const restored = await saved(page)
  expect(
    restored.threads
      .find((t: { id: string }) => t.id === custom.id)
      .runs.map((r: { config: unknown }) => r.config),
  ).toEqual([
    { model: 'deepseek', skill: 'academic-research' },
    { model: 'gpt4o', skill: 'people-research' },
  ])
})

test('all nodes and tabs, pending outputs, focus, progression, graph collapse and restoration', async ({
  page,
}) => {
  await expect(page.locator('.cw-node')).toHaveCount(7)
  for (const node of await page.locator('.cw-node').all()) {
    await node.click()
    for (const label of ['概览', '输入 / 输出', '执行记录']) {
      await page.getByRole('tab', { name: label, exact: true }).click()
      await expect(inspector(page).getByRole('tabpanel')).toBeVisible()
    }
  }
  const report = page.getByRole('button', { name: /最终报告，等待研究汇总/ })
  await report.click()
  await page.getByRole('tab', { name: '输入 / 输出' }).click()
  await expect(page.getByTestId('node-output')).toHaveText('尚未执行，暂无输出。')
  await page.getByRole('tab', { name: '执行记录' }).click()
  await expect(inspector(page)).toContainText('等待该节点开始执行。')
  await page.keyboard.press('Home')
  await expect(page.getByRole('tab', { name: '概览', exact: true })).toBeFocused()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('tab', { name: '输入 / 输出' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(inspector(page)).toHaveCount(0)
  await expect(report).toBeFocused()
  await page.getByRole('button', { name: /节点检查器.*点击节点/ }).click()
  await expect(page.getByRole('tab', { name: '输入 / 输出' })).toBeFocused()
  await page.getByRole('button', { name: '演示下一步' }).click()
  await expect(page.getByTestId('node-output')).toContainText('尚未返回 final_report')
  await page.getByRole('button', { name: /商业与增长，已完成/ }).click()
  await expect(page.getByTestId('node-output')).toContainText('5 条来源，已返回协调器')
  await page.getByRole('button', { name: '演示下一步' }).click()
  await expect(page.locator('.cw-report-message')).toContainText('尚未检索真实来源')
  await page.getByRole('tab', { name: '概览', exact: true }).click()
  await expect(inspector(page)).toContainText('演示报告已生成')
  await expect(inspector(page)).not.toContainText('等待协调器确认研究完成')
  await page.getByRole('tab', { name: '输入 / 输出' }).click()
  await page.getByRole('button', { name: '流程图', exact: true }).click()
  await expect(page.getByRole('complementary', { name: '运行图谱' })).toHaveCount(0)
  expect(
    await page.locator('.cw-messages').evaluate((el) => el.getBoundingClientRect().width),
  ).toBeLessThanOrEqual(720)
  await page.reload()
  await expect(page.getByRole('button', { name: '流程图', exact: true })).toHaveAttribute(
    'aria-expanded',
    'false',
  )
  await page.getByRole('button', { name: '流程图', exact: true }).click()
  await page.getByRole('button', { name: '重新演示' }).click()
  await page.getByRole('button', { name: /研究简报，待执行/ }).click()
  await expect(page.getByTestId('node-output')).toHaveText('尚未执行，暂无输出。')
})

test('custom research uses dynamic workers and its own question; text is rendered safely', async ({
  page,
}) => {
  await page.locator('nav[aria-label="研究对话导航"] .cw-new-chat').click()
  await input(page).fill('<img src=x onerror=alert(1)> 太阳能电池')
  await input(page).press('Enter')
  await expect(page.locator('.cw-fork')).toHaveCount(2)
  await expect(page.locator('.cw-user-bubble')).toContainText('<img src=x onerror=alert(1)>')
  await expect(page.locator('.cw-user-bubble img')).toHaveCount(0)
  await page.getByRole('button', { name: '演示下一步' }).click()
  await page.getByRole('tab', { name: '输入 / 输出' }).click()
  await expect(inspector(page)).toContainText('太阳能电池')
  await expect(inspector(page)).not.toContainText('AI 搜索产品')
})

test('invalid saved data recovers, inaccessible storage remains usable, theme persists', async ({
  page,
}) => {
  await page.evaluate(() =>
    localStorage.setItem('atlas-workspace:v1', '{"version":1,"threads":[]}'),
  )
  await page.reload()
  await expect(page.locator('h1')).toHaveText('新研究')
  await page.getByRole('button', { name: 'AI 搜索的下一站', exact: true }).click()
  await page.getByRole('button', { name: '外观：跟随系统' }).click()
  await page.getByRole('button', { name: '外观：浅色' }).click()
  await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark')
  await page.reload()
  await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark')
  await page.addInitScript(() => {
    Storage.prototype.setItem = () => {
      throw new DOMException('Storage blocked', 'QuotaExceededError')
    }
  })
  await page.reload()
  await expect(page.getByRole('status').filter({ hasText: '浏览器暂时无法保存' })).toBeVisible()
  await input(page).fill('仍能发送')
  await input(page).press('Enter')
  await expect(page.locator('.cw-user-bubble').last()).toHaveText('仍能发送')
})

test('mobile history drawer and touch targets', async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 320, height: 900 },
    isMobile: true,
    hasTouch: true,
    reducedMotion: 'reduce',
  })
  const page = await context.newPage()
  await fakeLangGraph(page)
  await page.goto('/')
  await page.getByRole('button', { name: '打开最近对话' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'AI 搜索的下一站', exact: true })
    .click()
  await page.getByRole('button', { name: '打开最近对话' }).click()
  await page.getByRole('dialog').locator('.cw-new-chat').click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await input(page).fill('手机研究')
  await page.getByRole('button', { name: '发送消息' }).click()
  await page.getByRole('button', { name: '打开最近对话' }).click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'AI 搜索的下一站', exact: true })
    .click()
  await expect(page.locator('h1')).toHaveText('AI 搜索的下一站')
  for (const name of ['选择模型', '选择Skills', '发送消息']) {
    const box = await page.getByRole('button', { name, exact: true }).boundingBox()
    expect(box!.height).toBeGreaterThanOrEqual(44)
  }
  await pick(page, '模型', 'DeepSeek V3.2')
  await pick(page, 'Skills', '事件时间线')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: '选择Skills', exact: true }).click()
  const popup = await page.getByRole('menu').boundingBox()
  expect(popup!.x).toBeGreaterThanOrEqual(0)
  expect(popup!.x + popup!.width).toBeLessThanOrEqual(320)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '查看当前步骤' }).click()
  await expect(inspector(page)).toBeInViewport()
  await context.close()
})

test('reduced motion / transparency disable glass animation and pointer sheen', async ({
  page,
}) => {
  const session = await page.context().newCDPSession(page)
  await session.send('Emulation.setEmulatedMedia', {
    features: [
      { name: 'prefers-reduced-motion', value: 'reduce' },
      { name: 'prefers-reduced-transparency', value: 'reduce' },
    ],
  })
  await expect(page.locator('.cw-composer')).toHaveCSS('backdrop-filter', 'none')
  await expect(page.locator('.cw-composer')).toHaveCSS('--cw-reflection-strength', '0')
  await page.getByRole('button', { name: '选择模型', exact: true }).click()
  await expect(page.getByRole('menu')).toHaveCSS('animation-name', 'none')
  await page.mouse.move(300, 850)
  expect(
    await page
      .locator('.cw-composer')
      .evaluate((el) => (el as HTMLElement).style.getPropertyValue('--cw-light-x')),
  ).toBe('')
})

for (const theme of ['light', 'dark'] as const) {
  for (const width of [1440, 1024, 900, 736, 390, 320]) {
    test(`layout ${theme} ${width}: boundaries, menus and screenshot`, async ({
      page,
    }, testInfo) => {
      const errors: string[] = []
      page.on('pageerror', (error) => errors.push(error.message))
      page.on('console', (message) => {
        if (message.type() === 'error') errors.push(`${message.text()} (${message.location().url})`)
      })
      page.on('request', (request) => {
        if (
          !request.url().startsWith(testInfo.project.use.baseURL!) &&
          !request.url().startsWith('data:')
        )
          errors.push(`Unexpected request: ${request.url()}`)
      })
      await page.setViewportSize({ width, height: 962 })
      await page.emulateMedia({ colorScheme: theme })
      await page.reload()
      const overflow = () =>
        page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
      expect(await overflow()).toBe(false)
      await page.screenshot({
        path: testInfo.outputPath(`apple-${theme}-${width}.png`),
        fullPage: true,
      })
      for (const name of ['选择模型', '选择Skills']) {
        await page.getByRole('button', { name, exact: true }).click()
        // Wait for the opening animation before capturing the opaque menu.
        await expect(page.getByRole('menu')).toHaveCSS('opacity', '1')
        await expect(page.getByRole('menu')).toHaveCSS(
          'background-color',
          theme === 'light' ? 'rgb(255, 255, 255)' : 'rgb(44, 44, 48)',
        )
        const bounds = await page.getByRole('menu').boundingBox()
        expect(bounds!.x).toBeGreaterThanOrEqual(0)
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width)
        expect(bounds!.y).toBeGreaterThanOrEqual(0)
        await expect(page.getByRole('menu')).toHaveCSS('backdrop-filter', 'none')
        if (width === 1024 || width === 320)
          await page.screenshot({
            path: testInfo.outputPath(`apple-${theme}-${width}-${name}.png`),
            fullPage: true,
          })
        await page.keyboard.press('Escape')
      }
      await page.getByRole('button', { name: '流程图', exact: true }).click()
      expect(await overflow()).toBe(false)
      expect(errors).toEqual([])
    })
  }
}
