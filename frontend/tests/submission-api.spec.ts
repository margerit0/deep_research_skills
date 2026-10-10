import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page, TestInfo } from '@playwright/test'
import { spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { join, resolve } from 'node:path'
import type { LiveThread, SubmissionReceipt } from '../src/data/liveSchema'

test.describe.configure({ mode: 'default' })
test.beforeEach(() => {
  test.skip(
    process.env.ATLAS_SUBMISSION_API !== '1',
    'Opt in to the isolated 1B native fault tests.',
  )
  test.setTimeout(180000)
})

async function fixture(request: APIRequestContext, info: TestInfo) {
  const root = resolve('..')
  const port = Number(process.env.ATLAS_SUBMISSION_PORT ?? 2027)
  const base = `http://127.0.0.1:${port}`
  const id = crypto.randomUUID()
  const parent = join(root, '.local', 'atlas-submission-api')
  await mkdir(parent, { recursive: true })
  const directory = await mkdtemp(join(parent, 'case-'))
  let child: ChildProcess | undefined
  let logs = ''
  let instance = ''
  const instances: string[] = []
  const observedRuns = new Map<string, { run_id: string; status: string }[]>()
  const free = () =>
    new Promise<boolean>((accept) => {
      const probe = createServer()
      probe.once('error', () => accept(false))
      probe.listen(port, '127.0.0.1', () => probe.close(() => accept(true)))
    })
  const identity = async () =>
    (await request.get(`${base}/atlas-fixture/identity`, { timeout: 2000 })).json()
  const start = async () => {
    expect(await free(), 'Never reuse another backend or fixture.').toBe(true)
    child = spawn(
      join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'),
      [
        join(root, 'tests/atlas_submission_server.py'),
        '--port',
        String(port),
        '--directory',
        directory,
        '--fixture-id',
        id,
      ],
      {
        cwd: root,
        windowsHide: true,
        env: { ...process.env, PYTHONUTF8: '1', NO_PROXY: '*' },
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
          if (child?.exitCode !== null) throw new Error(logs.slice(-6000))
          try {
            const body = await identity()
            instance = body.instance_id
            return body.fixture_id
          } catch {
            return ''
          }
        },
        { timeout: 45000 },
      )
      .toBe(id)
    const body = await identity()
    expect(body.substitutes).toBe(true)
    expect(body.submission_contract).toBe(true)
    expect(instances).not.toContain(instance)
    instances.push(instance)
  }
  const stop = async () => {
    const process = child
    child = undefined
    if (process && process.exitCode === null) {
      await new Promise<void>((accept, reject) => {
        const timeout = setTimeout(() => reject(new Error('Fixture did not exit')), 10000)
        process.once('exit', () => {
          clearTimeout(timeout)
          accept()
        })
        process.kill('SIGKILL')
      })
    }
    await expect.poll(free, { timeout: 10000 }).toBe(true)
  }
  const pause = (point: string) => writeFile(join(directory, `pause-${point}`), 'fixture')
  const release = (point: string) => writeFile(join(directory, `release-${point}`), 'fixture')
  const entered = async (point: string) => {
    await expect
      .poll(
        async () => {
          try {
            return await readFile(join(directory, `entered-${point}`), 'utf8')
          } catch {
            return ''
          }
        },
        { timeout: 20000 },
      )
      .toBe(instance)
  }
  const post = (path: string, data: unknown) =>
    request.post(`${base}${path}`, { data, timeout: 25000, maxRetries: 0 })
  const get = (path: string) => request.get(`${base}${path}`)
  const counts = async (): Promise<Record<string, number>> => (await identity()).calls
  const newSubmission = async () => {
    const thread = crypto.randomUUID(),
      turn = crypto.randomUUID()
    expect((await post('/threads', { thread_id: thread, if_exists: 'do_nothing' })).ok()).toBe(true)
    const path = `/atlas/threads/${thread}/submissions/${turn}`
    const body = {
      research_id: crypto.randomUUID(),
      text: '比较 Python 3.13 free-threaded 与默认构建。',
      expected_turn_id: null,
    }
    return { thread, turn, path, body }
  }
  const runs = async (thread: string): Promise<{ run_id: string; status: string }[]> => {
    const records: { run_id: string; status: string }[] = await (
      await get(`/threads/${thread}/runs?limit=100`)
    ).json()
    const summary = records.map(({ run_id, status }) => ({ run_id, status }))
    observedRuns.set(thread, summary)
    return summary
  }
  const completed = async (path: string) => {
    await expect
      .poll(async () => (await (await get(path)).json()).status, { timeout: 25000 })
      .toBe('completed')
    return (await (await get(path)).json()) as SubmissionReceipt
  }
  const finish = async () => {
    const finalCounts = child?.exitCode === null ? await counts().catch(() => ({})) : {}
    await stop()
    const evidence = info.outputPath('native-evidence.json')
    const log = info.outputPath('native-fixture.log')
    await writeFile(
      evidence,
      JSON.stringify(
        {
          directory,
          instances,
          calls: finalCounts,
          observedRuns: Object.fromEntries(observedRuns),
          modelAndSearchSubstitutes: true,
        },
        null,
        2,
      ),
    )
    await writeFile(log, logs)
    await info.attach('native-fixture-evidence', {
      contentType: 'application/json',
      path: evidence,
    })
    await info.attach('native-fixture-log', { contentType: 'text/plain', path: log })
  }
  try {
    await start()
  } catch (error) {
    await finish()
    throw error
  }
  return {
    base,
    id,
    start,
    stop,
    pause,
    release,
    entered,
    post,
    get,
    counts,
    newSubmission,
    runs,
    completed,
    finish,
  }
}

const cache = (page: Page): Promise<LiveThread> =>
  page.evaluate(() => {
    const workspace = JSON.parse(localStorage.getItem('atlas-workspace:v1')!)
    return workspace.threads.find((item: { id: string }) => item.id === workspace.activeThreadId)
      .live
  })
async function send(page: Page) {
  await page.goto('/')
  await page
    .getByRole('textbox', { name: '研究问题或补充要求' })
    .fill('比较 Python 3.13 free-threaded 与默认构建。')
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled({ timeout: 20000 })
  await page.getByRole('button', { name: '发送消息' }).click()
}

test('1B native: lost response, completed duplicates and competing tabs create no extra runs or tool calls', async ({
  page,
}, info) => {
  const f = await fixture(page.request, info)
  try {
    expect((await (await page.request.get('/api/atlas-fixture/identity')).json()).fixture_id).toBe(
      f.id,
    )
    await page.route(/\/api\/atlas\/threads\/[^/]+\/submissions\/[^/]+$/, async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      await route.fetch()
      await route.abort()
    })
    await send(page)
    await expect(page.getByTestId('live-status').last()).toHaveAttribute(
      'data-status',
      'succeeded',
      { timeout: 30000 },
    )
    const live = await cache(page)
    const research = live.researches.at(-1)!,
      turn = research.turns.at(-1)!
    const path = `/atlas/threads/${live.threadId}/submissions/${turn.id}`
    const body = {
      research_id: research.id,
      text: turn.text,
      expected_turn_id: turn.expectedTurnId,
    }
    const before = await f.counts()
    // Completed acknowledgement is durable without a background-flush delay.
    await f.stop()
    await f.start()
    const restored = (await (await f.get(path)).json()) as SubmissionReceipt
    expect(restored.status).toBe('completed')
    expect(restored.checkpoint_id).toBeTruthy()
    const duplicates = await Promise.all([f.post(path, body), f.post(path, body)])
    for (const duplicate of duplicates) expect((await duplicate.json()).run_id).toBe(turn.runId)
    expect((await f.post(path, { ...body, text: '改变过的内容' })).status()).toBe(409)
    expect(await f.runs(live.threadId)).toHaveLength(1)
    expect(await f.counts()).toEqual(before)
    expect(before.search).toBe(1)
    expect(before.writer).toBe(1)
    await page.reload()
    await expect(page.getByTestId('live-report')).toContainText('API 测试替身')
    const paths = [crypto.randomUUID(), crypto.randomUUID()].map(
      (id) => `/atlas/threads/${live.threadId}/submissions/${id}`,
    )
    const submissions = paths.map((path) =>
      f.post(path, { ...body, research_id: crypto.randomUUID(), expected_turn_id: turn.id }),
    )
    const responses = await Promise.all(submissions)
    expect(responses.map((response) => response.status()).sort()).toEqual([200, 409])
    const accepted = responses.findIndex((response) => response.ok())
    await f.completed(paths[accepted])
    // Even once the winner has finished, the stale predecessor remains a conflict.
    expect(
      (
        await f.post(`/atlas/threads/${live.threadId}/submissions/${crypto.randomUUID()}`, {
          ...body,
          research_id: crypto.randomUUID(),
          expected_turn_id: turn.id,
        })
      ).status(),
    ).toBe(409)
    expect(await f.runs(live.threadId)).toHaveLength(2)
    expect((await f.counts()).search).toBe(2)
    expect((await f.counts()).writer).toBe(2)
    const oldReceipt = (await (await f.get(path)).json()) as SubmissionReceipt
    expect(oldReceipt.status).toBe('completed')
    const oldState = await (
      await f.get(`/threads/${live.threadId}/state/${oldReceipt.checkpoint_id}`)
    ).json()
    expect(oldState.values.active_turn_id).toBe(turn.id)
    expect((await (await f.post(path, body)).json()).run_id).toBe(turn.runId)
    expect(await f.runs(live.threadId)).toHaveLength(2)
  } finally {
    await f.finish()
  }
})

for (const point of ['before-create', 'after-create']) {
  test(`1B native: process exit ${point} retains the submission key before any execution`, async ({
    request,
  }, info) => {
    const f = await fixture(request, info)
    try {
      const s = await f.newSubmission()
      await f.pause(point)
      const pending = f.post(s.path, s.body).catch(() => undefined)
      await f.entered(point)
      await f.stop()
      await pending
      await f.release(point)
      await f.start()
      const receipt = (await (await f.get(s.path)).json()) as SubmissionReceipt
      expect(receipt.status).toBe('retryable')
      expect(receipt.retry_allowed).toBe(true)
      expect((await f.counts()).search ?? 0).toBe(0)
      expect((await f.counts()).clarify ?? 0).toBe(0)
      const accepted = await f.post(s.path, s.body)
      expect(accepted.ok()).toBe(true)
      expect((await accepted.json()).run_id).toBe(receipt.run_id)
      await f.completed(s.path)
      expect((await (await f.post(s.path, s.body)).json()).run_id).toBe(receipt.run_id)
      expect((await f.runs(s.thread)).map((run) => run.run_id)).toEqual([receipt.run_id])
      expect((await f.counts()).search).toBe(1)
      expect((await f.counts()).writer).toBe(1)
    } finally {
      await f.finish()
    }
  })
}

for (const point of ['clarify', 'brief', 'writer']) {
  test(`1B native: recover ${point} from its verified checkpoint with measured call counts`, async ({
    page,
  }, info) => {
    const f = await fixture(page.request, info)
    try {
      await f.pause(point)
      let s: {
        thread: string
        turn: string
        path: string
        body: { research_id: string; text: string; expected_turn_id: null }
      }
      if (point === 'writer') {
        expect(
          (await (await page.request.get('/api/atlas-fixture/identity')).json()).fixture_id,
        ).toBe(f.id)
        await send(page)
        await expect
          .poll(async () => (await cache(page)).researches.at(-1)?.turns.at(-1)?.runId)
          .toBeTruthy()
        const live = await cache(page),
          research = live.researches.at(-1)!,
          turn = research.turns.at(-1)!
        s = {
          thread: live.threadId,
          turn: turn.id,
          path: `/atlas/threads/${live.threadId}/submissions/${turn.id}`,
          body: { research_id: research.id, text: turn.text, expected_turn_id: null },
        }
      } else {
        s = await f.newSubmission()
        expect((await f.post(s.path, s.body)).ok()).toBe(true)
      }
      await f.entered(point)
      const before = await f.counts()
      // No ten-second persistence grace period: the node entry is the barrier.
      await f.stop()
      await f.start()
      const receipt = (await (await f.get(s.path)).json()) as SubmissionReceipt
      expect(receipt.status).toBe('interrupted')
      expect(receipt.recovery.allowed).toBe(true)
      expect(await f.runs(s.thread)).toHaveLength(1)
      expect(await f.counts()).toEqual(before)
      await f.release(point)
      let recoveryPath = `${s.path}/recoveries/${crypto.randomUUID()}`
      let recoveryBody = {
        research_id: s.body.research_id,
        parent_run_id: receipt.run_id,
        checkpoint_id: receipt.recovery.checkpoint_id,
      }
      if (point === 'writer') {
        await page.reload()
        await expect(page.getByTestId('execution-recovery-note')).toContainText(
          '已完成的检索不会重跑',
        )
        await expect(page.getByText('已保留的研究笔记', { exact: true })).toBeVisible()
        for (const [width, theme] of [
          [1024, 'light'],
          [390, 'dark'],
          [320, 'light'],
        ] as const) {
          await page.setViewportSize({ width, height: 962 })
          await page.emulateMedia({ colorScheme: theme, reducedMotion: 'reduce' })
          expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
          ).toBe(true)
          await page.screenshot({
            path: info.outputPath(`execution-recovery-${theme}-${width}.png`),
            fullPage: true,
          })
        }
        await page.route(
          /\/api\/atlas\/threads\/[^/]+\/submissions\/[^/]+\/recoveries\/[^/]+$/,
          async (route) => {
            recoveryPath = new URL(route.request().url()).pathname.replace(/^\/api/, '')
            recoveryBody = route.request().postDataJSON()
            await route.fetch()
            await route.abort()
          },
        )
        await page.getByRole('button', { name: '继续生成报告', exact: true }).click()
        await expect(page.getByTestId('live-status').last()).toHaveAttribute(
          'data-status',
          'succeeded',
          { timeout: 30000 },
        )
        await expect(page.getByTestId('live-report')).toContainText('API 测试替身')
        await page.reload()
        await expect(page.getByTestId('live-report')).toContainText('API 测试替身')
        expect((await cache(page)).researches.at(-1)?.execution?.attempts).toHaveLength(2)
      } else expect((await f.post(recoveryPath, recoveryBody)).ok()).toBe(true)
      const final = await f.completed(s.path)
      expect(final.attempts).toHaveLength(2)
      expect(final.run_id).not.toBe(receipt.run_id)
      expect((await (await f.post(recoveryPath, recoveryBody)).json()).run_id).toBe(final.run_id)
      expect((await (await f.post(s.path, s.body)).json()).run_id).toBe(final.run_id)
      expect(
        (await f.post(`${s.path}/recoveries/${crypto.randomUUID()}`, recoveryBody)).status(),
      ).toBe(409)
      expect(await f.runs(s.thread)).toHaveLength(2)
      const calls = await f.counts()
      expect(calls.search).toBe(1)
      expect(calls.compression).toBe(1)
      expect(calls.clarify).toBe(point === 'clarify' ? 2 : 1)
      expect(calls.brief).toBe(point === 'brief' ? 2 : 1)
      expect(calls.writer).toBe(point === 'writer' ? 2 : 1)
      await info.attach('call-counts', {
        contentType: 'application/json',
        body: JSON.stringify(
          { before, after: calls, originalRun: receipt.run_id, recoveryRun: final.run_id },
          null,
          2,
        ),
      })
    } finally {
      await f.finish()
    }
  })
}

test('1B native: an interrupted research tool and a missing server thread cannot be restarted by retries', async ({
  request,
}, info) => {
  const f = await fixture(request, info)
  try {
    const s = await f.newSubmission()
    await f.pause('search')
    expect((await f.post(s.path, s.body)).ok()).toBe(true)
    await f.entered('search')
    await f.stop()
    await f.start()
    const receipt = (await (await f.get(s.path)).json()) as SubmissionReceipt
    expect(receipt.status).toBe('interrupted')
    expect(receipt.recovery).toEqual({ allowed: false, reason: 'research_node_not_resumable' })
    const before = await f.counts()
    expect(
      (
        await f.post(`${s.path}/recoveries/${crypto.randomUUID()}`, {
          research_id: s.body.research_id,
          parent_run_id: receipt.run_id,
          checkpoint_id: crypto.randomUUID(),
        })
      ).status(),
    ).toBe(409)
    expect((await (await f.post(s.path, s.body)).json()).status).toBe('interrupted')
    expect(await f.runs(s.thread)).toHaveLength(1)
    expect((await f.counts()).search).toBe(1)
    expect((await f.counts()).writer ?? 0).toBe(0)
    expect((await request.delete(`${f.base}/threads/${s.thread}`)).ok()).toBe(true)
    const missing = await (await f.get(s.path)).json()
    expect(missing.status).toBe('blocked')
    expect(missing.reason).toBe('thread_missing')
    expect((await f.post(s.path, s.body)).status()).toBe(200)
    expect((await f.get(`/threads/${s.thread}`)).status()).toBe(404)
    expect(await f.counts()).toEqual(before)
  } finally {
    await f.finish()
  }
})

test('1B native: recovery acceptance survives a second process exit with the same attempt ID', async ({
  request,
}, info) => {
  const f = await fixture(request, info)
  try {
    const s = await f.newSubmission()
    await f.pause('writer')
    expect((await f.post(s.path, s.body)).ok()).toBe(true)
    await f.entered('writer')
    await f.stop()
    await f.start()
    const receipt = (await (await f.get(s.path)).json()) as SubmissionReceipt
    expect(receipt.recovery.allowed).toBe(true)
    const path = `${s.path}/recoveries/${crypto.randomUUID()}`
    const body = {
      research_id: s.body.research_id,
      parent_run_id: receipt.run_id,
      checkpoint_id: receipt.recovery.checkpoint_id,
    }
    await f.pause('after-create')
    const pending = f.post(path, body).catch(() => undefined)
    await f.entered('after-create')
    await f.stop()
    await pending
    await f.release('after-create')
    await f.release('writer')
    await f.start()
    const reserved = (await (await f.get(s.path)).json()) as SubmissionReceipt
    expect(reserved.status).toBe('retryable')
    expect((await (await f.post(path, body)).json()).run_id).toBe(reserved.run_id)
    await f.completed(s.path)
    expect((await f.runs(s.thread)).map((run) => run.run_id).sort()).toEqual(
      [receipt.run_id, reserved.run_id].sort(),
    )
    expect((await f.counts()).search).toBe(1)
    expect((await f.counts()).writer).toBe(2)
  } finally {
    await f.finish()
  }
})
