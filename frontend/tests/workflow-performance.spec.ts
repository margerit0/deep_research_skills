import { writeFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'
import type { TestInfo } from '@playwright/test'
import { workflowEdge } from '../src/data/workflowEditing'
import { workflowDocumentSchema } from '../src/data/workflowSchema'
import { catalog, workflowFixture } from './workflow-fixture'

// Trace snapshots on every mouse move would measure the recorder too.
test.use({ viewport: { width: 1440, height: 960 }, trace: 'off' })

async function record(info: TestInfo, name: string, values: object) {
  const path = info.outputPath(`${name}.json`)
  await writeFile(path, JSON.stringify(values, null, 2) + '\n')
  await info.attach(name, { path, contentType: 'application/json' })
}

test('M4: drag 50 display nodes / 100 edges on the production canvas', async ({
  page,
  browser,
}, info) => {
  test.skip(process.env.ATLAS_WORKFLOW_M4_PERF !== '1', 'opt in to desktop timing thresholds')
  const document = workflowDocumentSchema.parse({
    name: 'M4 仅展示',
    definition: { nodes: [], edges: [] },
  })
  const n = 50
  for (let i = 0; i < n; i++) {
    const id = `display_${i}`
    document.definition.nodes.push({ id, type: 'optimize_plan', type_version: 1, parameters: {} })
    document.presentation.nodes.push({
      node_id: id,
      label: `展示节点 ${i + 1}`,
      position: { x: (i % 10) * 240, y: Math.floor(i / 10) * 180 },
    })
    for (const offset of [1, 10])
      document.definition.edges.push(workflowEdge(id, `display_${(i + offset) % n}`))
  }
  document.presentation.viewport = { x: 36, y: 100, zoom: 0.55 }
  expect(workflowDocumentSchema.safeParse(document).success).toBe(false)
  await page.addInitScript((encoded: string) => {
    window.m4Canvas = JSON.parse(encoded)
  }, JSON.stringify({ document, catalog }))
  await page.goto('/tests/fixtures/workflow-m4.html')
  await expect(page.locator('.react-flow__node')).toHaveCount(50)
  await expect(page.locator('.react-flow__edge-path')).toHaveCount(100)
  const node = page.locator('.react-flow__node[data-id="display_21"]')
  const box = (await node.boundingBox())!
  const x = Math.round(box.x + box.width / 2),
    y = Math.round(box.y + box.height / 2)
  const initialTransform = await node.evaluate((el) => el.style.transform)
  await page.mouse.move(x, y)
  await page.mouse.down()
  // React Flow sets its grab offset at the drag threshold, not at pointerdown.
  // Establish a rendered reference point before timing the continuous drag.
  await page.mouse.move(x + 8, y)
  await page.mouse.move(x + 16, y)
  await expect.poll(() => node.evaluate((el) => el.style.transform)).not.toBe(initialTransform)
  // Timestamp *actual* input in the browser. Retire queued moves only when
  // the drawn node reaches their position (including moves coalesced in a frame).
  const readMetrics = await node.evaluateHandle(
    (element, origin) => {
      const pending: { at: number; dx: number; dy: number }[] = []
      const latencies: number[] = []
      let total = 0,
        frames = 0,
        commits = 0,
        last = 0
      const first = performance.now()
      const { x: startX, y: startY } = element.getBoundingClientRect()
      let active = true
      let lastTransform = element.style.transform
      const tick = () => {
        if (!active) return
        const time = performance.now()
        frames++
        const transform = element.style.transform
        if (pending.length && transform !== lastTransform) {
          const rect = element.getBoundingClientRect()
          const dx = rect.x - startX,
            dy = rect.y - startY
          let applied = pending.length - 1
          while (
            applied >= 0 &&
            Math.hypot(pending[applied].dx - dx, pending[applied].dy - dy) > 1.5
          )
            applied--
          if (applied >= 0) {
            commits++
            for (const event of pending.splice(0, applied + 1)) latencies.push(time - event.at)
            last = time
          }
        }
        lastTransform = transform
        requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
      window.addEventListener(
        'pointermove',
        (event) => {
          if (active && event.buttons === 1) {
            total++
            pending.push({
              at: event.timeStamp,
              dx: event.clientX - origin.x,
              dy: event.clientY - origin.y,
            })
          }
        },
        true,
      )
      return () => {
        active = false
        const seconds = (last - first) / 1000
        const sorted = [...latencies].sort((a, b) => a - b)
        return {
          seconds,
          pointerMoves: total,
          observedMoves: latencies.length,
          positionFrames: commits,
          positionFps: commits / seconds,
          rafFrames: frames,
          inputToVisibleP95Ms: sorted[Math.ceil(sorted.length * 0.95) - 1],
          inputToVisibleMs: latencies,
        }
      }
    },
    { x: x + 16, y },
  )
  for (let i = 1; i <= 140; i++) {
    const stepStart = performance.now()
    await page.mouse.move(x + 16 + 2 * i, y + Math.round(24 * Math.sin(i / 16)))
    const remaining = 16.7 - (performance.now() - stepStart)
    if (remaining > 0) await new Promise((resolve) => setTimeout(resolve, remaining))
  }
  // Give the last dispatched event its display frame without including idle
  // time after the last visible transform in the effective FPS denominator.
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  )
  const metrics = await readMetrics.evaluate((read) => read())
  await page.mouse.up()
  await record(info, 'canvas-drag', {
    browser: browser.version(),
    viewport: page.viewportSize(),
    nodes: n,
    edges: n * 2,
    ...metrics,
  })
  expect(metrics.seconds).toBeGreaterThan(1)
  expect(metrics.pointerMoves).toBeGreaterThanOrEqual(100)
  expect(metrics.observedMoves).toBe(metrics.pointerMoves)
  expect(metrics.positionFps).toBeGreaterThanOrEqual(30)
  expect(metrics.inputToVisibleP95Ms).toBeLessThanOrEqual(100)
})

test('one sustained drag creates one undo step and one debounced draft request', async ({
  page,
}, info) => {
  const fixture = workflowFixture()
  const id = fixture.seed()
  const original = structuredClone(fixture.workflows.get(id)!.draft.document)
  await fixture.attach(page)
  await page.goto(`/#workflows/${id}`)
  const undo = page.getByRole('button', { name: '撤销', exact: true })
  await expect(undo).toBeDisabled()
  const node = page.locator('.react-flow__node[data-id="write_research_brief"]')
  await expect(node).toBeInViewport()
  const box = (await node.boundingBox())!
  const x = box.x + box.width / 2,
    y = box.y + box.height / 2
  await page.evaluate(() => {
    window.addEventListener('pointerup', () => performance.mark('m4-drag-end'), {
      capture: true,
      once: true,
    })
  })
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + 38, y + 16, { steps: 10 })
  // Hold past the debounce interval: an erroneous per-move save now fires.
  await page.waitForTimeout(1000)
  expect(fixture.calls.saves).toHaveLength(0)
  await page.mouse.move(x + 52, y + 20, { steps: 5 })
  await page.mouse.up()
  await expect.poll(() => fixture.calls.saves.length).toBe(1)
  await expect(page.locator('.wf-save-state')).toHaveText('已保存')
  const delayMs = await page.evaluate(() => {
    const end = performance.getEntriesByName('m4-drag-end')[0].startTime
    const save = performance
      .getEntriesByType('resource')
      .find((entry) => new URL(entry.name).pathname.endsWith('/draft'))!
    return save.startTime - end
  })
  await record(info, 'drag-autosave', {
    delayMs,
    beforeRelease: 0,
    afterRelease: fixture.calls.saves.length,
  })
  expect(delayMs).toBeGreaterThanOrEqual(750)
  expect(delayMs).toBeLessThan(1300)
  expect(fixture.calls.saves[0].document.presentation.nodes).not.toEqual(
    original.presentation.nodes,
  )
  await undo.click()
  await expect(undo).toBeDisabled()
  await expect.poll(() => fixture.calls.saves.length).toBe(2)
  expect(fixture.calls.saves[1].document).toEqual(original)
  expect(fixture.calls.runs).toEqual([])
})
