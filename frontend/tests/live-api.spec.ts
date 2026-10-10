import { test, expect } from '@playwright/test'

// Explicit opt-in: this test calls the real configured models and search service.
test('native LangGraph API: clarification, answer, report, sources and reload', async ({
  page,
}, testInfo) => {
  test.skip(
    process.env.ATLAS_LIVE !== '1' && process.env.ATLAS_API_FIXTURE !== '1',
    'Opt in with ATLAS_LIVE=1 (real models) or ATLAS_API_FIXTURE=1 (fixture server).',
  )
  test.setTimeout(900000)
  let posts = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/threads\/[^/]+\/runs$/.test(request.url())) posts++
  })
  await page.goto('/')
  const capabilities = await page.request.get('/api/atlas/config')
  expect(capabilities.ok()).toBe(true)
  const configured = await capabilities.json()
  const fixtureModels = configured.models.every(
    (model: { model: string }) => model.model === 'fixture/model',
  )
  expect(fixtureModels, 'The selected test mode must match the server before creating a run.').toBe(
    process.env.ATLAS_API_FIXTURE === '1',
  )
  const input = page.getByRole('textbox', { name: '研究问题或补充要求' })
  const status = page.getByTestId('live-status').last()
  await input.fill('请帮我做一项对比研究。')
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled({ timeout: 20000 })
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(status).toHaveAttribute('data-status', /^(awaiting_input|failed)$/, {
    timeout: 180000,
  })
  await expect(status).toHaveAttribute('data-status', 'awaiting_input')
  await page.screenshot({ path: testInfo.outputPath('live-clarification.png'), fullPage: true })
  await page.reload()
  await expect(status).toHaveAttribute('data-status', 'awaiting_input')
  await input.fill(
    '比较 Python 3.13 实验性的 free-threaded CPython 与默认 GIL 构建，用于开发者判断是否试用。只比较 GIL 状态、C 扩展兼容性和适用限制三个维度。仅使用 Python 官方文档或 PEP 中的 2–3 个来源，中文报告控制在 500 字左右。范围已明确，无需继续澄清；不确定之处请明示。',
  )
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled({ timeout: 20000 })
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect.poll(() => posts).toBe(2)
  await page.reload()
  await expect(status).toHaveAttribute('data-status', /^(succeeded|partial|failed)$/, {
    timeout: 660000,
  })
  const saved = await page.evaluate(() => {
    const workspace = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
    return workspace.threads.find(
      (thread: { id: string }) => thread.id === workspace.activeThreadId,
    ).live
  })
  const research = saved.researches[0]
  await testInfo.attach('api-result', {
    contentType: 'application/json',
    body: JSON.stringify(
      {
        modelAndSearchSubstitutes: process.env.ATLAS_API_FIXTURE === '1',
        threadId: saved.threadId,
        researchId: research.id,
        turns: research.turns.map((turn: { id: string; runId: string }) => ({
          id: turn.id,
          runId: turn.runId,
        })),
        status: research.status,
        reportLength: research.report.length,
        sourceCount: research.sources.length,
        errors: research.errors,
        config: research.config,
      },
      null,
      2,
    ),
  })
  expect(research.status, JSON.stringify(research.errors)).toBe('succeeded')
  expect(research.turns).toHaveLength(2)
  expect(research.report.length).toBeGreaterThan(100)
  expect(research.sources.length).toBeGreaterThan(0)
  await expect(page.getByTestId('live-report')).toBeVisible()
  await expect(page.getByRole('region', { name: '检索来源' })).toBeVisible()
  await expect(page.getByTestId('live-report')).toContainText('Python')
  await page.screenshot({ path: testInfo.outputPath('live-result.png'), fullPage: true })
  await page.reload()
  await expect(status).toHaveAttribute('data-status', 'succeeded')
  await expect(page.getByTestId('live-report')).toContainText('Python')
  expect(posts).toBe(2)
})
