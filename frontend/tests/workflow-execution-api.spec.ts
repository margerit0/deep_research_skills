import { expect, test } from '@playwright/test'
import { spawn } from 'node:child_process'
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { join, resolve } from 'node:path'
import type { LiveThread } from '../src/data/liveSchema'
import type { WorkflowRevision } from '../src/data/workflowSchema'

test('native workflow: editor publication changes execution and keeps old history', async ({
  page,
  request,
}, info) => {
  test.skip(
    process.env.ATLAS_WORKFLOW_M3_API !== '1',
    'Opt in to the isolated M3 native browser test.',
  )
  test.setTimeout(150000)
  const root = resolve('..')
  const port = Number(process.env.ATLAS_WORKFLOW_M3_PORT ?? 2858)
  const base = `http://127.0.0.1:${port}`
  const fixtureId = crypto.randomUUID()
  const parent = join(root, '.local/graph-canvas-m3')
  await mkdir(parent, { recursive: true })
  const directory = await mkdtemp(join(parent, 'browser-'))
  const free = () =>
    new Promise<boolean>((resolve) => {
      const server = createServer()
      server.once('error', () => resolve(false))
      server.listen(port, '127.0.0.1', () => server.close(() => resolve(true)))
    })
  expect(await free()).toBe(true)
  let logs = ''
  const child = spawn(
    join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'),
    [
      join(root, 'tests/atlas_workflow_execution_server.py'),
      '--port',
      String(port),
      '--directory',
      directory,
      '--fixture-id',
      fixtureId,
    ],
    {
      cwd: root,
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: '1', NO_PROXY: '*' },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  )
  child.stdout.on('data', (data) => {
    logs += data.toString()
  })
  child.stderr.on('data', (data) => {
    logs += data.toString()
  })
  let serverPid: number | undefined
  const errors: string[] = []
  const submissions: string[] = []
  const histories: unknown[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('request', (request) => {
    if (
      request.method() === 'POST' &&
      /\/atlas\/threads\/[^/]+\/submissions\/[^/]+$/.test(new URL(request.url()).pathname)
    )
      submissions.push(request.postData()!)
  })
  const get = async (path: string) => {
    const response = await request.get(`${base}${path}`, { timeout: 3000 })
    expect(response.ok()).toBe(true)
    return response.json()
  }
  const saved = (): Promise<LiveThread> =>
    page.evaluate(() => {
      const workspace = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
      return workspace.threads.find(
        (thread: { id: string }) => thread.id === workspace.activeThreadId,
      ).live
    })
  const publish = async () => {
    await page.getByRole('button', { name: '保存', exact: true }).click()
    await expect(page.locator('.wf-save-state')).toHaveText('已保存')
    await page.getByRole('button', { name: '发布', exact: true }).click()
    await page.getByRole('button', { name: '确认发布', exact: true }).click()
    await expect(page.getByRole('button', { name: '使用此版本发起研究' })).toBeVisible()
  }
  const run = async () => {
    await page.getByRole('button', { name: '使用此版本发起研究' }).click()
    await expect(page.getByRole('textbox', { name: '研究问题或补充要求' })).toHaveValue('')
    await page
      .getByRole('textbox', { name: '研究问题或补充要求' })
      .fill('比较 Python 3.13 free-threaded 与默认构建。')
    await page.getByRole('button', { name: '发送消息' }).click()
    await expect(page.getByTestId('live-status').last()).toHaveAttribute(
      'data-status',
      'succeeded',
      { timeout: 30000 },
    )
    await expect(
      page.getByRole('heading', { name: 'Python 对比报告（API 测试替身）' }),
    ).toBeVisible()
    return saved()
  }
  try {
    await expect
      .poll(
        async () => {
          if (child.exitCode !== null) throw new Error(logs.slice(-4000))
          try {
            const identity = await get('/m3/identity')
            serverPid = identity.pid
            return identity.fixture_id
          } catch {
            return ''
          }
        },
        { timeout: 45000 },
      )
      .toBe(fixtureId)
    const config = await get('/atlas/config')
    expect([
      config.workflow_editor_version,
      config.workflow_execution_version,
      config.workflow_events_version,
    ]).toEqual([1, 1, 1])
    await page.goto('/')
    await page.getByRole('button', { name: '流程管理', exact: true }).click()
    await page.getByRole('button', { name: '使用标准模板', exact: true }).click()
    await page.getByRole('textbox', { name: '新流程名称' }).fill('原生 M3 执行流程')
    await page.getByRole('button', { name: '创建草稿' }).click()
    await page.getByRole('button', { name: '添加研究计划优化', exact: true }).click()
    await page.getByRole('button', { name: '添加材料整理', exact: true }).click()
    await publish()
    expect(submissions).toEqual([])
    const first = await run()
    const firstRevision = first.workflow!
    const organizeId = firstRevision.document.definition.nodes.find(
      (node) => node.type === 'organize_notes',
    )!.id
    await expect(page.locator(`[data-flow-node="${organizeId}"]`)).toHaveAttribute(
      'data-status',
      'completed',
    )
    await page.locator(`[data-flow-node="${organizeId}"]`).click()
    await page.getByRole('tab', { name: '输入 / 输出' }).click()
    await expect(page.locator('#cw-inspector')).toContainText('[M3 organized]')
    await page.screenshot({ path: info.outputPath('native-workflow-v1.png'), fullPage: true })
    await page.getByRole('link', { name: '查看发布版本' }).click()
    await page.getByRole('button', { name: '编辑当前草稿', exact: true }).click()
    await page.locator(`.react-flow__node[data-id="${organizeId}"]`).click()
    await page.getByRole('button', { name: '删除节点', exact: true }).click()
    await page.getByRole('button', { name: '确认删除', exact: true }).click()
    await publish()
    const second = await run()
    expect(second.threadId).not.toBe(first.threadId)
    expect(second.workflow!.revision_number).toBe(2)
    await expect(page.locator(`[data-flow-node="${organizeId}"]`)).toHaveCount(0)
    for (const live of [first, second]) {
      const state = await get(`/threads/${live.threadId}/state`)
      const runs = await get(`/threads/${live.threadId}/runs?limit=100`)
      const revision: WorkflowRevision = live.workflow!
      expect(state.values.workflow_binding.workflow_ref.revision_id).toBe(revision.revision_id)
      expect(state.values.research_status).toBe('succeeded')
      expect(runs).toHaveLength(1)
      histories.push({ thread_id: live.threadId, revision: revision.revision_id, runs, state })
    }
    await page.reload()
    await expect(page.getByTestId('live-status').last()).toHaveAttribute('data-status', 'succeeded')
    await page.getByRole('button', { name: '刷新状态', exact: true }).click()
    const identity = await get('/m3/identity')
    for (const [live, expected] of [
      [first, 1],
      [second, 0],
    ] as const) {
      const calls = identity.audit.filter(
        (item: { thread_id: string; kind: string; name: string }) =>
          item.thread_id === live.threadId && item.kind === 'call',
      )
      expect(calls.filter((item: { name: string }) => item.name === 'organize_notes')).toHaveLength(
        expected,
      )
      expect(calls.filter((item: { name: string }) => item.name === 'optimize_plan')).toHaveLength(
        1,
      )
      expect(calls.filter((item: { name: string }) => item.name === 'writer')).toHaveLength(1)
    }
    expect(submissions).toHaveLength(2)
    expect(errors).toEqual([])
    await page.screenshot({ path: info.outputPath('native-workflow-v2.png'), fullPage: true })
  } finally {
    await writeFile(
      info.outputPath('native-workflow-evidence.json'),
      JSON.stringify({ directory, fixtureId, submissions, histories }, null, 2),
    )
    await writeFile(info.outputPath('native-workflow.log'), logs)
    if (serverPid && serverPid !== child.pid) {
      const identity = await get('/m3/identity').catch(() => null)
      if (identity?.fixture_id === fixtureId) process.kill(serverPid, 'SIGKILL')
    }
    if (child.exitCode === null) child.kill('SIGKILL')
    await expect.poll(free, { timeout: 10000 }).toBe(true)
  }
})
