import { test, expect } from '@playwright/test'
import { spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { mkdtemp, mkdir, stat, writeFile } from 'node:fs/promises'
import { resolve, join, delimiter } from 'node:path'
import { createServer } from 'node:net'
import type { EventPage, LiveResearch, LiveThread } from '../src/data/liveSchema'

test('native API: recover unseen events after stopping the backend inside a research tool', async ({
  page,
}, testInfo) => {
  test.skip(
    process.env.ATLAS_RECOVERY_API !== '1',
    'Opt in with ATLAS_RECOVERY_API=1 and a Vite proxy to the isolated backend port.',
  )
  test.setTimeout(180000)
  const root = resolve('..')
  const port = Number(process.env.ATLAS_RECOVERY_PORT ?? 2026)
  const base = `http://127.0.0.1:${port}`
  const nonce = crypto.randomUUID()
  // Refuse to reuse an existing service, including another fixture's service.
  await new Promise<void>((accept, reject) => {
    const probe = createServer()
    probe.once('error', reject)
    probe.listen(port, '127.0.0.1', () =>
      probe.close((error) => (error ? reject(error) : accept())),
    )
  })
  const parent = join(root, '.local', 'atlas-recovery-api')
  await mkdir(parent, { recursive: true })
  const dir = await mkdtemp(join(parent, 'case-'))
  const graph = join(root, 'tests', 'atlas_recovery_fixture.py').replaceAll('\\', '/')
  const configFile = join(dir, 'langgraph.json')
  await writeFile(
    configFile,
    JSON.stringify(
      {
        graphs: { research_agent_full: `${graph}:agent` },
        http: { app: `${graph}:app` },
        env: {
          LANGGRAPH_DISABLE_FILE_PERSISTENCE: 'false',
          LANGSMITH_TRACING: 'false',
          ATLAS_EVENT_DB: join(dir, 'events.sqlite3'),
          ATLAS_RECOVERY_FIXTURE_DIR: dir,
          ATLAS_RECOVERY_FIXTURE_ID: nonce,
        },
        dependencies: [root],
        python_version: '3.11',
      },
      null,
      2,
    ),
  )
  let child: ChildProcess | undefined
  let logs = ''
  const instances: string[] = []
  const start = async () => {
    let instanceId = ''
    const python =
      process.platform === 'win32'
        ? join(root, '.venv', 'Scripts', 'python.exe')
        : join(root, '.venv', 'bin', 'python')
    child = spawn(
      python,
      [
        '-c',
        'from langgraph_cli.cli import cli; cli()',
        'dev',
        '--config',
        configFile,
        '--no-browser',
        '--no-reload',
        '--allow-blocking',
        '--host',
        '127.0.0.1',
        '--port',
        String(port),
      ],
      {
        cwd: dir,
        windowsHide: true,
        env: {
          ...process.env,
          PYTHONUTF8: '1',
          NO_PROXY: '*',
          LANGGRAPH_DISABLE_FILE_PERSISTENCE: 'false',
          LANGSMITH_TRACING: 'false',
          ATLAS_EVENT_DB: join(dir, 'events.sqlite3'),
          PYTHONPATH: [root, join(root, 'src')].join(delimiter),
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    )
    child.stdout?.on('data', (bytes) => {
      logs += bytes.toString()
    })
    child.stderr?.on('data', (bytes) => {
      logs += bytes.toString()
    })
    await expect
      .poll(
        async () => {
          if (child?.exitCode !== null) throw new Error(`Fixture exited: ${logs.slice(-5000)}`)
          try {
            const response = await page.request.get(`${base}/atlas-fixture/identity`, {
              timeout: 1000,
            })
            const identity = await response.json()
            instanceId = identity.instance_id
            return identity.fixture_id
          } catch {
            return ''
          }
        },
        { timeout: 45000 },
      )
      .toBe(nonce)
    expect(instanceId).toBeTruthy()
    expect(instances).not.toContain(instanceId)
    instances.push(instanceId)
  }
  const stop = async () => {
    const process = child
    child = undefined
    if (!process || process.exitCode !== null) return
    await new Promise<void>((accept, reject) => {
      const timer = setTimeout(() => reject(new Error('Fixture process did not stop')), 10000)
      process.once('exit', () => {
        clearTimeout(timer)
        accept()
      })
      process.kill('SIGKILL')
    })
    // On Windows, the virtualenv launcher can exit just before its interpreter.
    // Wait for the old listener to disappear before checking the next instance.
    await expect
      .poll(
        () =>
          new Promise<boolean>((accept) => {
            const probe = createServer()
            probe.once('error', () => accept(false))
            probe.listen(port, '127.0.0.1', () => probe.close(() => accept(true)))
          }),
        { timeout: 10000 },
      )
      .toBe(true)
  }
  const streamRoute = /\/api\/threads\/[^/]+\/runs\/[^/]+\/stream\?/
  const replayRoute = /\/api\/atlas\/threads\/[^/]+\/runs\/[^/]+\/events\?/
  const cached = () =>
    page.evaluate(() => {
      const data = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
      return data.threads.find((thread: { id: string }) => thread.id === data.activeThreadId)
        .live as LiveThread
    })
  let posts = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/threads\/[^/]+\/runs$/.test(request.url())) posts++
  })
  try {
    await start()
    const proxy = await page.request.get('/api/atlas-fixture/identity')
    expect((await proxy.json()).fixture_id).toBe(nonce)
    await page.route(streamRoute, (route) => route.abort())
    await page.route(replayRoute, (route) => route.abort())
    await page.goto('/')
    const input = page.getByRole('textbox', { name: '研究问题或补充要求' })
    const send = page.getByRole('button', { name: '发送消息' })
    const status = page.getByTestId('live-status').last()
    await input.fill('请做一项对比研究。')
    await expect(send).toBeEnabled({ timeout: 15000 })
    await send.click()
    await expect(status).toHaveAttribute('data-status', 'awaiting_input', { timeout: 20000 })
    await input.fill('比较 Python 3.13 free-threaded 和默认构建。')
    await expect(send).toBeEnabled()
    await send.click()
    await expect.poll(() => posts).toBe(2)
    await expect
      .poll(async () => (await cached()).researches.at(-1)?.turns.at(-1)?.runId)
      .toBeTruthy()
    const live = await cached()
    const research = live.researches.at(-1)!
    const runId = research.turns.at(-1)!.runId!
    const query = new URLSearchParams({
      research_id: research.id,
      turn_id: research.turns.at(-1)!.id,
    })
    const replayUrl = `${base}/atlas/threads/${live.threadId}/runs/${runId}/events?${query}`
    let before!: EventPage
    await expect
      .poll(async () => {
        before = await (await page.request.get(replayUrl)).json()
        return before.events.some((event) => event.kind === 'tool_started')
      })
      .toBe(true)
    const checkpoint = await (
      await page.request.get(`${base}/threads/${live.threadId}/state`)
    ).json()
    expect(checkpoint.values.research_phase).toBe('research')
    expect(checkpoint.values.research_events).toEqual([])
    expect(before.sealed).toBe(false)
    expect((await cached()).researches.at(-1)!.events).toEqual([])
    // Dev run metadata has its own 10 s flush loop. Wait for that separate
    // boundary; the event journal above already committed without it.
    const now = Date.now()
    await expect
      .poll(
        async () => {
          try {
            return (await stat(join(dir, '.langgraph_api', '.langgraph_ops.pckl'))).mtimeMs > now
          } catch {
            return false
          }
        },
        { timeout: 25000, intervals: [500, 1000] },
      )
      .toBe(true)
    await stop()
    await start()
    await page.unroute(replayRoute)
    await page.reload()
    await expect
      .poll(
        async () => {
          const events = (await cached()).researches.at(-1)!.events
          return before.events.every((event) => events.some((saved) => saved.id === event.id))
        },
        { timeout: 15000 },
      )
      .toBe(true)
    await expect(page.locator('[data-flow-node^="researcher-"]').first()).toBeVisible()
    await expect(page.locator('[data-flow-node^="researcher-"]').first()).toHaveAttribute(
      'data-status',
      'partial',
    )
    await expect(page.getByTestId('event-recovery-note')).toContainText('部分进度记录无法确认')
    await expect(status).not.toHaveAttribute('data-status', 'succeeded')
    await expect(page.getByTestId('live-report')).toHaveCount(0)
    const runs = await (await page.request.get(`${base}/threads/${live.threadId}/runs`)).json()
    expect(runs).toHaveLength(2)
    expect(runs.map((run: { run_id: string }) => run.run_id).sort()).toEqual(
      research.turns.map((turn) => turn.runId).sort(),
    )
    expect(posts).toBe(2)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.screenshot({ path: testInfo.outputPath('recovery-api-desktop.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true)
    await page.getByTestId('event-recovery-note').scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('recovery-api-mobile.png') })
    await page
      .locator('.cw-graph-panel')
      .screenshot({ path: testInfo.outputPath('recovery-api-mobile-graph.png') })
    const restored: LiveResearch = (await cached()).researches.at(-1)!
    await testInfo.attach('recovery-result', {
      contentType: 'application/json',
      body: JSON.stringify(
        {
          modelAndSearchSubstitutes: true,
          threadId: live.threadId,
          runId,
          eventIdsBeforeCrash: before.events.map((event) => event.id),
          restoredEventCount: restored.events.length,
          recovery: restored.eventRecovery,
          researchStatus: restored.status,
          serverRunCount: runs.length,
          posts,
          processInstances: instances,
        },
        null,
        2,
      ),
    })
  } finally {
    await writeFile(join(dir, 'release-search'), 'release')
    await stop()
    await writeFile(testInfo.outputPath('native-fixture.log'), logs)
  }
})
