import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import type { Page } from '@playwright/test'
import { outlineReport } from '../src/data/reportOutline'
import latest from '../src/data/deepseek-p0-recording.json' with { type: 'json' }
import { fakeLangGraph } from './langgraph-fixture'

const example = (slug: string) =>
  readFileSync(new URL(`../../examples/${slug}.md`, import.meta.url), 'utf8')
    .split('## 📄 最终报告')[1]
    .split('## 🧭 决策与执行轨迹')[0]

const longReport = [
  '# 长篇研究报告',
  ...Array.from(
    { length: 8 },
    (_, index) =>
      `## ${index + 1}. 第 ${index + 1} 节\n\n${'这一节的正文引用了来源 [1]，篇幅足够长以触发折叠。'.repeat(14)}`,
  ),
  '## 结论\n\n长报告的结论摘要 [2]。',
  '### 来源\n\n' +
    Array.from(
      { length: 7 },
      (_, index) => `[${index + 1}] 来源标题 ${index + 1}: https://example.com/${index + 1}`,
    ).join('\n'),
].join('\n\n')

async function finishWith(page: Page, report: string) {
  const fake = await fakeLangGraph(page)
  await page.goto('/')
  await page.getByRole('textbox', { name: '研究问题或补充要求' }).fill('研究测试主题')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect.poll(() => fake.runs.length).toBe(1)
  fake.succeed()
  fake.change({ final_report: report }, 'success')
  await page.getByRole('button', { name: '刷新状态', exact: true }).click()
  return page.getByTestId('live-report')
}

test('outline: headings give title, sections, conclusion and numbered sources', () => {
  const outline = outlineReport(
    [
      '# 报告标题',
      '开场导语。',
      '## 一、GIL 状态',
      '正文 [1]。',
      '## 2. C 扩展',
      '正文 [2]。',
      '## 结论',
      '结论正文。',
      '### 来源',
      '[1] 文档一: https://docs.python.org/a',
      '[2] 文档二，https://docs.python.org/b',
    ].join('\n\n'),
  )
  expect(outline.title).toBe('报告标题')
  expect(outline.lead).toBe('开场导语。')
  expect(outline.sections.map((section) => section.heading)).toEqual(['GIL 状态', 'C 扩展'])
  expect(outline.conclusion?.heading).toBe('结论')
  expect(outline.sources).toEqual([
    { index: '1', title: '文档一', url: 'https://docs.python.org/a' },
    { index: '2', title: '文档二', url: 'https://docs.python.org/b' },
  ])
})

test('outline: a report without headings splits on labelled paragraphs', () => {
  const outline = outlineReport(latest.research.report)
  expect(outline.title).toBe('Python 3.13 free-threaded 与默认 GIL 构建对比')
  expect(outline.sections.map((section) => section.heading)).toEqual([
    'GIL 状态',
    'C 扩展兼容性',
    '适用限制',
  ])
  expect(outline.conclusion?.heading).toContain('试用建议')
  expect(outline.sources).toHaveLength(2)
})

test('outline: published examples keep their structure and every source', () => {
  const deepseek = outlineReport(example('deepseek-360'))
  expect(deepseek.title).toBe('DeepSeek 系统性研究报告')
  expect(deepseek.sections).toHaveLength(6)
  expect(deepseek.conclusion?.heading).toBe('结论')
  expect(deepseek.sources.map((source) => source.index)).toEqual(
    Array.from({ length: 11 }, (_, index) => String(index + 1)),
  )
  const iceland = outlineReport(example('iceland-self-drive'))
  expect(iceland.title).toBe('')
  expect(iceland.sections[1].heading).toBe('8 天可执行环岛方案（首次自驾版）')
  expect(iceland.conclusion?.heading).toBe('最终建议')
})

test('outline: headings in code stay in the body and unparsed sources are not dropped', () => {
  const fenced = outlineReport('## 一节\n\n```\n## 不是标题\n```\n\n## 二节\n\n正文')
  expect(fenced.sections.map((section) => section.heading)).toEqual(['一节', '二节'])
  const unparsed = outlineReport('## 分析\n\n正文\n\n## 来源\n\n官方文档与公开报道')
  expect(unparsed.sources).toEqual([])
  expect(unparsed.sections.at(-1)?.body).toContain('官方文档与公开报道')
})

test('card: long reports collapse behind a conclusion summary and expand in place', async ({
  page,
}) => {
  const card = await finishWith(page, longReport)
  await expect(card).toHaveAttribute('data-collapsed', 'true')
  await expect(card.getByRole('heading', { name: '长篇研究报告' })).toBeVisible()
  await expect(card.getByRole('complementary', { name: '结论' })).toContainText('长报告的结论摘要')
  await expect(card.locator('.cw-report-body')).not.toContainText('长报告的结论摘要')
  const toggle = card.getByRole('button', { name: /展开全文/ })
  await expect(toggle).toContainText(/还有 \d+ 节/)
  await toggle.click()
  await expect(card).toHaveAttribute('data-collapsed', 'false')
  await expect(card.getByRole('complementary', { name: '结论' })).toHaveCount(0)
  await expect(card.locator('.cw-report-body')).toContainText('长报告的结论摘要')
  await expect(card.getByRole('button', { name: '收起全文' })).toHaveAttribute(
    'aria-expanded',
    'true',
  )
})

test('card: citations jump to their source, revealing the full list', async ({ page }) => {
  const card = await finishWith(page, longReport)
  const sources = card.getByRole('region', { name: '报告引用来源' })
  await expect(sources.getByRole('link')).toHaveCount(5)
  await card.getByRole('button', { name: /展开全文/ }).click()
  await card.locator('.cw-report-conclusion [data-cite="2"]').click()
  await expect(sources.locator('[data-source-index="2"]')).toHaveAttribute('data-flash', 'true')
  await expect(sources.getByRole('link')).toHaveCount(7)
  await expect(page).not.toHaveURL(/#/)
  await expect(sources.getByRole('link').first()).toHaveAttribute('href', 'https://example.com/1')
})

test('card: citations stay plain text when the report lists no sources', async ({ page }) => {
  const card = await finishWith(page, '# 无来源报告\n\n结论 [1]。')
  await expect(card).toContainText('[1]')
  await expect(card.locator('[data-cite]')).toHaveCount(0)
  await expect(card.getByRole('region', { name: '报告引用来源' })).toHaveCount(0)
})

test('card: copy and download hand over the original Markdown', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const card = await finishWith(page, longReport)
  await card.getByRole('button', { name: '复制 Markdown' }).click()
  await expect(card.getByRole('button', { name: '已复制' })).toBeVisible()
  // The Windows clipboard reads text back with CRLF line endings.
  const copied = await page.evaluate(() => navigator.clipboard.readText())
  expect(copied.replace(/\r\n/g, '\n')).toBe(longReport)
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    card.getByRole('button', { name: '下载 Markdown' }).click(),
  ])
  expect(download.suggestedFilename()).toBe('长篇研究报告.md')
  expect(readFileSync(await download.path(), 'utf8')).toBe(longReport)
})

test('card: recorded playback shows the whole card, not a shrunken flex item', async ({ page }) => {
  await fakeLangGraph(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await page.getByRole('button', { name: '全流程演示', exact: true }).click()
  await page.getByLabel('演示数据来源').selectOption(latest.id)
  await page.getByRole('button', { name: '暂停演示' }).click()
  await page.getByRole('button', { name: '跳转：实际报告与来源', exact: true }).click()
  const card = page.getByTestId('recorded-report')
  await expect(card.locator('.cw-report-section')).toHaveCount(3)
  const height = await card.evaluate((element) => element.getBoundingClientRect().height)
  expect(height).toBeGreaterThan(400)
})

test('card: narrow screens keep the collapsed card inside the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 })
  const card = await finishWith(page, `${longReport}\n\n| 列一 | 列二 |\n| --- | --- |\n| A | B |`)
  await expect(card).toHaveAttribute('data-collapsed', 'true')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
