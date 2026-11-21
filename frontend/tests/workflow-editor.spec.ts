import { readFileSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test as base } from '@playwright/test'
import type { Page } from '@playwright/test'
import { catalog, workflowFixture } from './workflow-fixture'
import type { WorkflowFixture } from './workflow-fixture'
import { validateWorkflowStructure } from '../src/data/workflowSchema'
import type { WorkflowDocument } from '../src/data/workflowSchema'

const test = base.extend<{ workflow: WorkflowFixture }>({
  workflow: async ({ page }, use) => {
    const fixture = workflowFixture()
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('dialog', (dialog) => {
      void dialog.accept()
    })
    await fixture.attach(page)
    await use(fixture)
    expect(errors).toEqual([])
    expect(fixture.calls.runs).toEqual([])
  },
})
const node = (page: Page, id: string) => page.locator(`.react-flow__node[data-id="${id}"]`)
const save = async (page: Page) => {
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.wf-save-state')).toHaveText('已保存')
}
const open = async (page: Page, workflow: WorkflowFixture) => {
  const id = workflow.seed()
  await page.goto(`/#workflows/${id}`)
  await expect(page.getByLabel('流程名称', { exact: true })).toHaveValue('行业洞察 · 深度研究')
  await expect(node(page, 'start')).toBeVisible()
  await expect(node(page, 'end')).toBeInViewport({ ratio: 0.9 })
  return id
}
const add = async (page: Page, type = '研究计划优化') =>
  page.getByRole('button', { name: `添加${type}`, exact: true }).click()
const publish = async (page: Page) => {
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '发布新版本' })).toBeVisible()
  await page.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(page.locator('.wf-title-line .wf-tag')).toContainText('只读')
}

async function expectPortsMatchEdges(page: Page, document: WorkflowDocument) {
  await expect
    .poll(() =>
      page.evaluate(
        (edges) =>
          edges.every((edge) => {
            const path = window.document.querySelector<SVGPathElement>(
              `.react-flow__edge[data-id="${edge.id}"] .react-flow__edge-path`,
            )
            if (!path || !path.getScreenCTM()) return false
            return (
              [
                ['source', edge.source, 0],
                ['target', edge.target, path.getTotalLength()],
              ] as const
            ).every(([side, nodeId, length]) => {
              const port = window.document
                .querySelector(`.react-flow__node[data-id="${nodeId}"] .react-flow__handle.${side}`)
                ?.getBoundingClientRect()
              if (!port) return false
              const point = path.getPointAtLength(length)
              const screen = new DOMPoint(point.x, point.y).matrixTransform(path.getScreenCTM()!)
              return (
                Math.hypot(
                  screen.x - port.x - port.width / 2,
                  screen.y - port.y - port.height / 2,
                ) <=
                Math.max(port.width, port.height) / 2 + 2
              )
            })
          }),
        document.definition.edges,
      ),
    )
    .toBe(true)
}

test('workbench entry, template creation and saved content survive reload', async ({
  page,
  workflow,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: '流程管理', exact: true }).click()
  await expect(page.getByRole('heading', { name: '流程管理', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '使用标准模板', exact: true }).click()
  await page.getByRole('textbox', { name: '新流程名称' }).fill('产业研究方法')
  await page.getByRole('button', { name: '创建草稿' }).click()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '产业研究方法',
  )
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('产业研究方法 · 修订')
  await save(page)
  await page.reload()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '产业研究方法 · 修订',
  )
  expect(workflow.workflows.size).toBe(1)
})

test('repeatable extensions have separate parameters; delete reconnects and undo restores', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  await add(page)
  await page.getByRole('textbox', { name: '处理要求' }).fill('保留第一份要求')
  await page.getByRole('button', { name: '复制', exact: true }).click()
  await page.getByRole('textbox', { name: '处理要求' }).fill('第二份要求')
  await add(page, '材料整理')
  await save(page)
  const doc = workflow.workflows.get(id)!.draft.document
  const plans = doc.definition.nodes.filter((node) => node.type === 'optimize_plan')
  expect(plans).toHaveLength(2)
  expect(plans[0].id).not.toBe(plans[1].id)
  expect(plans.map((node) => node.parameters.instructions)).toEqual([
    '保留第一份要求',
    '第二份要求',
  ])
  expect(validateWorkflowStructure(doc, catalog).valid).toBe(true)
  await expectPortsMatchEdges(page, doc)
  await page.getByRole('button', { name: '删除节点', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '同时连接前后节点' })).toBeChecked()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.locator('.wf-canvas-toolbar .wf-tag')).toHaveText('9 节点')
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await expect(page.locator('.wf-canvas-toolbar .wf-tag')).toHaveText('10 节点')
  await page.getByRole('button', { name: '重做', exact: true }).click()
  await expect(page.locator('.wf-canvas-toolbar .wf-tag')).toHaveText('9 节点')
  await save(page)
  expect(validateWorkflowStructure(workflow.workflows.get(id)!.draft.document, catalog).valid).toBe(
    true,
  )
})

test('drag is one undo step and saves coordinates without per-frame requests', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  await page.getByRole('button', { name: '自动排列' }).click()
  await save(page)
  const before = structuredClone(
    workflow.workflows
      .get(id)!
      .draft.document.presentation.nodes.find((node) => node.node_id === 'write_research_brief')!
      .position,
  )
  const box = (await node(page, 'write_research_brief').boundingBox())!
  const previousSaves = workflow.calls.saves.length
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 55, box.y + box.height / 2 + 25, { steps: 12 })
  await page.mouse.up()
  await expect.poll(() => workflow.calls.saves.length).toBe(previousSaves + 1)
  expect(
    workflow.workflows
      .get(id)!
      .draft.document.presentation.nodes.find((node) => node.node_id === 'write_research_brief')!
      .position.x,
  ).toBeGreaterThan(before.x + 20)
  await page.getByRole('button', { name: '撤销', exact: true }).click()
  await save(page)
  expect(
    workflow.workflows
      .get(id)!
      .draft.document.presentation.nodes.find((node) => node.node_id === 'write_research_brief')!
      .position,
  ).toEqual(before)
  await page.reload()
  await expect(node(page, 'write_research_brief')).toBeVisible()
})

test('keyboard connection form rejects incompatible stages; ports restore a removed edge', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  await page.locator('.wf-connections summary').click()
  await page
    .getByRole('button', { name: '选择连线 研究简报 到 研究协调子流程', exact: true })
    .click()
  await page.getByRole('button', { name: '删除连线', exact: true }).click()
  await page.getByLabel('连接起点').selectOption('write_research_brief')
  await page.getByLabel('连接终点').selectOption('final_report_generation')
  await page.getByRole('button', { name: '建立连接' }).click()
  await expect(page.locator('.wf-editor-notice')).toHaveText('此连接不符合研究阶段顺序。')
  const source = node(page, 'write_research_brief').locator('.react-flow__handle.source')
  const target = node(page, 'supervisor_subgraph').locator('.react-flow__handle.target')
  await source.dragTo(target)
  await save(page)
  expect(validateWorkflowStructure(workflow.workflows.get(id)!.draft.document, catalog).valid).toBe(
    true,
  )
})

test('core nodes are locked; typing, IME and field undo do not delete canvas nodes', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  await node(page, 'write_research_brief').focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('textbox', { name: '节点名称', exact: true })).toHaveValue('研究简报')
  await expect(page.getByRole('button', { name: '删除节点', exact: true })).toBeDisabled()
  await page.keyboard.press('Delete')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await add(page)
  const input = page.getByRole('textbox', { name: '处理要求' })
  await input.fill('中文输入要求')
  await input.dispatchEvent('keydown', {
    key: 'Delete',
    code: 'Delete',
    isComposing: true,
    bubbles: true,
  })
  await input.press('Control+z')
  await expect(page.locator('.wf-canvas-toolbar .wf-tag')).toHaveText('8 节点')
  await input.fill('保留来源并对照信息')
  await save(page)
  const plan = workflow.workflows
    .get(id)!
    .draft.document.definition.nodes.find((node) => node.type === 'optimize_plan')!
  await node(page, plan.id).click()
  await page.keyboard.press('Delete')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(node(page, plan.id)).toBeFocused()
})

test('validation locates the empty requirement; publishing snapshots and preserves later drafts', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  await add(page)
  await page.getByRole('textbox', { name: '处理要求' }).fill('')
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.locator('.wf-issue').first().click()
  await expect(page.getByRole('textbox', { name: '处理要求' })).toBeFocused()
  expect(workflow.calls.publishes).toHaveLength(0)
  await page.getByRole('textbox', { name: '处理要求' }).fill('核对来源并补充验证路径')
  await publish(page)
  const first = structuredClone(workflow.workflows.get(id)!.revisions[0])
  await expect(page.getByRole('button', { name: '保存', exact: true })).toHaveCount(0)
  await expect(page.locator('.wf-publication-note')).toContainText('执行功能开放后可用')
  await page.getByRole('button', { name: '编辑当前草稿', exact: true }).click()
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('后续草稿')
  await save(page)
  expect(workflow.workflows.get(id)!.revisions[0]).toEqual(first)
  await page.getByRole('button', { name: '版本历史', exact: true }).click()
  await page.locator('.wf-version').first().click()
  await expect(page.locator('.wf-title-line h1')).toHaveText(first.document.name)
  await page.getByRole('button', { name: '复制为新流程' }).click()
  await page.getByRole('textbox', { name: '新流程名称' }).fill('旧版本副本')
  await page.getByRole('button', { name: '创建草稿' }).click()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '旧版本副本',
  )
  expect(workflow.workflows.size).toBe(2)
  expect(workflow.workflows.get(id)!.draft.document.name).toBe('后续草稿')
})

test('new edits during an in-flight save are retained and saved serially', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  workflow.control.holdSave = true
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('第一份改动')
  await expect.poll(() => workflow.calls.saves.length).toBe(1)
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('保存期间的新改动')
  workflow.control.releaseSave()
  await expect(page.locator('.wf-save-state')).toHaveText('已保存')
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '保存期间的新改动',
  )
  expect(workflow.calls.saves.map((call) => call.version)).toEqual([1, 2])
  expect(workflow.workflows.get(id)!.draft.document.name).toBe('保存期间的新改动')
})

test('lost save response is confirmed by complete document readback without another PUT', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  workflow.control.loseSaveAfter = true
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('响应丢失后回读')
  await expect(page.locator('.wf-save-state')).toHaveText('已保存')
  await expect.poll(() => workflow.calls.saves.length).toBe(1)
  expect(workflow.calls.reads.length).toBeGreaterThan(1)
  expect(workflow.workflows.get(id)!.draft.document.name).toBe('响应丢失后回读')
  await page.reload()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '响应丢失后回读',
  )
})

test('lost save before commit preserves local content and exports it before readback', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  workflow.control.loseSaveBefore = true
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('需要保留的本地修改')
  await expect(page.getByRole('alert', { name: '草稿冲突' })).toBeVisible()
  expect(workflow.workflows.get(id)!.draft.document.name).toBe('行业洞察 · 深度研究')
  expect(workflow.calls.saves).toHaveLength(1)
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出本地备份并载入新版' }).click()
  const download = await downloadPromise
  const document = JSON.parse(readFileSync((await download.path())!, 'utf8'))
  expect(document.name).toBe('需要保留的本地修改')
  expect(Object.keys(document).sort()).toEqual(['definition', 'name', 'presentation'])
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '行业洞察 · 深度研究',
  )
})

test('two tabs cannot overwrite each other; conflict can become an independent copy', async ({
  page,
  context,
  workflow,
}) => {
  const id = await open(page, workflow)
  const second = await context.newPage()
  await workflow.attach(second)
  second.on('dialog', (dialog) => {
    void dialog.accept()
  })
  await second.goto(`/#workflows/${id}`)
  await expect(second.getByRole('textbox', { name: '流程名称', exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('服务器上较新的草稿')
  await save(page)
  await second.getByRole('textbox', { name: '流程名称', exact: true }).fill('第二窗口的本地修改')
  await expect(second.getByRole('alert', { name: '草稿冲突' })).toBeVisible()
  await second.getByRole('button', { name: '另存本地副本', exact: true }).click()
  await second.getByRole('textbox', { name: '新流程名称' }).fill('保留冲突副本')
  await second.getByRole('button', { name: '创建草稿' }).click()
  await expect(second.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '保留冲突副本',
  )
  expect(workflow.workflows.get(id)!.draft.document.name).toBe('服务器上较新的草稿')
  expect(workflow.workflows.size).toBe(2)
  await second.close()
})

test('failed saves remain editable and retryable; reload recovers an uncertain save', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  workflow.control.rejectSave = true
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('保存失败时的内容')
  await expect(page.locator('.wf-save-state')).toHaveText('保存未完成')
  workflow.control.rejectSave = false
  workflow.control.loseSaveAfter = true
  workflow.control.readFailure = true
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.wf-editor-notice')).toContainText('保存结果尚未确认')
  workflow.control.readFailure = false
  await page.reload()
  await expect(page.locator('.wf-save-state')).toHaveText('已保存')
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '保存失败时的内容',
  )
  expect(workflow.workflows.get(id)!.draft.edit_version).toBe(2)
})

test('publication retry survives reload and uses the original identity after later edits', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  workflow.control.losePublishAfter = true
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await page.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(page.getByRole('button', { name: '重试发布', exact: true })).toBeVisible()
  const entry = workflow.workflows.get(id)!
  entry.draft = {
    ...entry.draft,
    edit_version: entry.draft.edit_version + 1,
    document: { ...entry.draft.document, name: '已存在更新的服务器草稿' },
  }
  await page.reload()
  await page.getByRole('button', { name: '重试发布', exact: true }).click()
  await expect(page.locator('.wf-title-line .wf-tag')).toHaveText('v1 · 只读')
  expect(workflow.calls.publishes).toHaveLength(2)
  expect(workflow.calls.publishes[0]).toEqual(workflow.calls.publishes[1])
  expect(entry.revisions).toHaveLength(1)
  expect(entry.draft.document.name).toBe('已存在更新的服务器草稿')
})

test('a changed draft after validation rejects publication and retains local content', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '发布新版本' })).toBeVisible()
  const entry = workflow.workflows.get(id)!
  entry.draft = {
    ...entry.draft,
    edit_version: 2,
    document: { ...entry.draft.document, name: '其他窗口的修改' },
  }
  await page.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(page.getByRole('alert', { name: '草稿冲突' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '行业洞察 · 深度研究',
  )
  expect(entry.revisions).toHaveLength(0)
})

test('creation retry after a lost response creates only one workflow', async ({
  page,
  workflow,
}) => {
  workflow.control.loseCreateAfter = true
  await page.goto('/#workflows')
  await page.getByRole('button', { name: '新建流程', exact: true }).click()
  await page.getByRole('button', { name: '创建草稿' }).click()
  await expect(page.getByRole('dialog')).toContainText('重试将沿用原创建请求')
  await page.reload()
  await page.getByRole('button', { name: '继续确认创建' }).click()
  await page.getByRole('button', { name: '重试创建', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '新的研究流程',
  )
  expect(workflow.workflows.size).toBe(1)
  expect(workflow.calls.creates[0]).toEqual(workflow.calls.creates[1])
})

test('import excludes execution and secret fields; incomplete imports remain editable drafts', async ({
  page,
  workflow,
}) => {
  const id = workflow.seed()
  const document = structuredClone(workflow.workflows.get(id)!.draft.document)
  await page.goto('/#workflows')
  const file = page.getByLabel('导入流程文件')
  await file.setInputFiles({
    name: 'bad.json',
    mimeType: 'application/json',
    buffer: Buffer.from(
      JSON.stringify({ ...document, workflow_binding: { secret: 'do-not-echo' } }),
    ),
  })
  await expect(page.getByRole('alert')).toContainText('无法导入')
  await expect(page.getByRole('alert')).not.toContainText('do-not-echo')
  document.definition.edges = []
  await file.setInputFiles({
    name: 'draft.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(document)),
  })
  await page.getByRole('textbox', { name: '新流程名称' }).fill('未连接的导入草稿')
  await page.getByRole('button', { name: '创建草稿' }).click()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '未连接的导入草稿',
  )
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.locator('.wf-issue').first()).toBeVisible()
  expect(workflow.workflows.size).toBe(2)
  expect(workflow.calls.publishes).toHaveLength(0)
})

test('archive preserves published views and allows a new copy', async ({ page, workflow }) => {
  const id = await open(page, workflow)
  await publish(page)
  await page.getByRole('button', { name: '流程管理', exact: true }).click()
  await page.getByRole('button', { name: '归档 行业洞察 · 深度研究', exact: true }).click()
  await page.getByRole('button', { name: '确认归档', exact: true }).click()
  await expect(page.locator('.wf-workflow-card')).toHaveCount(0)
  await page.getByLabel('流程筛选').selectOption('archived')
  await page.getByRole('button', { name: '查看 v1' }).click()
  await expect(page.locator('.wf-title-line .wf-tag')).toContainText('只读')
  await expect(page.getByRole('button', { name: '编辑当前草稿' })).toHaveCount(0)
  expect(workflow.workflows.get(id)!.revisions).toHaveLength(1)
  await page.getByRole('button', { name: '复制为新流程' }).click()
  await page.getByRole('button', { name: '创建草稿' }).click()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toBeVisible()
  expect(workflow.workflows.size).toBe(2)
})

test('capability gating and unavailable production runtime never launch another graph', async ({
  page,
  workflow,
}) => {
  workflow.control.capable = false
  await page.goto('/')
  await expect(page.getByRole('button', { name: '流程管理', exact: true })).toHaveCount(0)
  await page.goto('/#workflows')
  await expect(page.getByText('当前服务尚未开放正式流程编辑。')).toBeVisible()
  workflow.control.capable = true
  workflow.control.runtimeUnavailable = true
  const id = workflow.seed()
  await page.goto(`/#workflows/${id}`)
  await page.getByRole('button', { name: '重新连接', exact: true }).click()
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.locator('.wf-editor-notice')).toContainText('当前服务尚未开放流程发布')
  await expect(page.getByRole('button', { name: '保存', exact: true })).toBeEnabled()
  expect(workflow.calls.publishes).toHaveLength(0)
})

test('desktop and narrow viewing layouts fit in silver, graphite and reduced motion', async ({
  page,
  workflow,
}) => {
  await open(page, workflow)
  await add(page)
  await add(page, '材料整理')
  await save(page)
  const directory = resolve('..', '.local', 'graph-canvas-m2', 'screenshots')
  mkdirSync(directory, { recursive: true })
  for (const { width, theme } of [
    { width: 1440, theme: 'light' },
    { width: 1024, theme: 'light' },
    { width: 1024, theme: 'dark' },
    { width: 390, theme: 'light' },
    { width: 320, theme: 'light' },
  ] as const) {
    await page.setViewportSize({ width, height: 960 })
    await page.emulateMedia({ colorScheme: theme, reducedMotion: 'reduce' })
    if (width > 760) await page.getByRole('button', { name: '适应画布', exact: true }).click()
    else {
      await expect(page.getByText('窄屏查看 · 请在桌面上编辑流程')).toBeVisible()
      await page.getByRole('button', { name: '属性', exact: true }).click()
      await expect(page.getByRole('textbox', { name: '处理要求' })).toHaveAttribute('readonly', '')
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const overflow = await page
      .locator(
        '.wf-workspace button:visible, .wf-workspace input:visible, .wf-workspace textarea:visible, .wf-workspace select:visible',
      )
      .evaluateAll((elements) =>
        elements
          .filter((element) => !element.closest('.react-flow'))
          .map((element) => ({
            text: element.getAttribute('aria-label') ?? element.textContent,
            rect: element.getBoundingClientRect(),
          }))
          .filter(({ rect }) => rect.width && (rect.left < -1 || rect.right > innerWidth + 1))
          .map(({ text }) => text),
      )
    expect(overflow).toEqual([])
    await page.screenshot({
      path: resolve(directory, `editor-${width}-${theme}.png`),
      fullPage: true,
    })
  }
})

test('clarification can be removed and reinserted; node limits include system nodes', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  await node(page, 'clarify_with_user').click()
  await page.getByRole('button', { name: '删除节点', exact: true }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(node(page, 'clarify_with_user')).toHaveCount(0)
  await page.getByRole('button', { name: '添加澄清需求', exact: true }).click()
  await expect(node(page, 'clarify_with_user')).toBeVisible()
  for (let index = 0; index < 23; index++) await add(page)
  await expect(page.locator('.wf-canvas-toolbar .wf-tag')).toHaveText('30 节点')
  await expect(page.getByRole('button', { name: '添加研究计划优化', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '添加材料整理', exact: true })).toBeDisabled()
  await save(page)
  expect(validateWorkflowStructure(workflow.workflows.get(id)!.draft.document, catalog).valid).toBe(
    true,
  )
})

test('temporarily empty names preserve unsaved nodes across reload', async ({ page, workflow }) => {
  const id = await open(page, workflow)
  await add(page)
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('')
  await expect(page.locator('.wf-save-state')).toHaveText('保存未完成')
  await page.reload()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue('')
  await expect(page.locator('.wf-canvas-toolbar .wf-tag')).toHaveText('8 节点')
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('恢复后的有效名称')
  await save(page)
  expect(workflow.workflows.get(id)!.draft.document.definition.nodes).toHaveLength(8)
})

test('reload reconciles a lost earlier save and keeps edits made while it was in flight', async ({
  page,
  workflow,
}) => {
  const id = await open(page, workflow)
  workflow.control.holdSave = true
  workflow.control.loseSaveAfter = true
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('已提交的第一版')
  await expect.poll(() => workflow.calls.saves.length).toBe(1)
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('仍需保留的后续修改')
  workflow.control.readFailure = true
  workflow.control.releaseSave()
  await expect(page.locator('.wf-editor-notice')).toContainText('保存结果尚未确认')
  workflow.control.readFailure = false
  await page.reload()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '仍需保留的后续修改',
  )
  await expect(page.locator('.wf-save-state')).toHaveText('已保存')
  expect(workflow.workflows.get(id)!.draft.document.name).toBe('仍需保留的后续修改')
  expect(workflow.calls.saves.map((call) => call.version)).toEqual([1, 2])
})

test('publication cannot be sent when its request identity cannot be stored', async ({
  page,
  workflow,
}) => {
  await open(page, workflow)
  await page.evaluate(() => {
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith('atlas.workflow.'))
        throw new DOMException('fixture quota', 'QuotaExceededError')
      return original.call(this, key, value)
    }
  })
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await page.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(page.locator('.wf-editor-notice')).toContainText('无法保存发布请求标识')
  expect(workflow.calls.publishes).toHaveLength(0)
  await expect(page.getByRole('button', { name: '保存', exact: true })).toBeEnabled()
})

test('rail navigation offers a backup instead of dropping a failed local edit', async ({
  page,
  workflow,
}) => {
  await open(page, workflow)
  workflow.control.rejectSave = true
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('无法保存的本地内容')
  await expect(page.locator('.wf-save-state')).toHaveText('保存未完成')
  await page.getByRole('button', { name: '返回研究工作台', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '保留当前修改' })).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出备份并离开' }).click()
  const download = await downloadPromise
  expect(JSON.parse(readFileSync((await download.path())!, 'utf8')).name).toBe('无法保存的本地内容')
  await expect(page.locator('#atlas-conversation-workspace')).toHaveAttribute(
    'data-view',
    'research',
  )
})

test('duplicated tab storage does not replace either windows unsaved recovery copy', async ({
  page,
  context,
  workflow,
}) => {
  const id = await open(page, workflow)
  workflow.control.rejectSave = true
  await page.getByRole('textbox', { name: '流程名称', exact: true }).fill('窗口 A 的本地内容')
  await expect(page.locator('.wf-save-state')).toHaveText('保存未完成')
  const copiedSession = await page.evaluate(() =>
    Object.fromEntries(
      Object.keys(sessionStorage).map((key) => [key, sessionStorage.getItem(key)!]),
    ),
  )
  const second = await context.newPage()
  await workflow.attach(second)
  second.on('dialog', (dialog) => {
    void dialog.accept()
  })
  await second.addInitScript((values) => {
    for (const [key, value] of Object.entries(values)) sessionStorage.setItem(key, value)
  }, copiedSession)
  await second.goto(`/#workflows/${id}`)
  await second.getByRole('textbox', { name: '流程名称', exact: true }).fill('窗口 B 的本地内容')
  await expect(second.locator('.wf-save-state')).toHaveText('保存未完成')
  await page.reload()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '窗口 A 的本地内容',
  )
  await expect(second.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '窗口 B 的本地内容',
  )
  await second.close()
})

test('duplicated tabs retain independent creation receipts when one response is lost', async ({
  page,
  context,
  workflow,
}) => {
  await page.goto('/#workflows')
  await expect(page.getByRole('heading', { name: '流程管理', exact: true })).toBeVisible()
  const copiedSession = await page.evaluate(() =>
    Object.fromEntries(
      Object.keys(sessionStorage).map((key) => [key, sessionStorage.getItem(key)!]),
    ),
  )
  const second = await context.newPage()
  await workflow.attach(second)
  await second.addInitScript((values) => {
    for (const [key, value] of Object.entries(values)) sessionStorage.setItem(key, value)
  }, copiedSession)
  await second.goto('/#workflows')
  await expect(second.getByRole('heading', { name: '流程管理', exact: true })).toBeVisible()
  workflow.control.loseCreateAfter = true
  await page.getByRole('button', { name: '新建流程', exact: true }).click()
  await page.getByRole('textbox', { name: '新流程名称' }).fill('窗口 A 的新流程')
  await page.getByRole('button', { name: '创建草稿' }).click()
  await expect(page.getByRole('dialog')).toContainText('重试将沿用原创建请求')
  await second.getByRole('button', { name: '新建流程', exact: true }).click()
  await second.getByRole('textbox', { name: '新流程名称' }).fill('窗口 B 的新流程')
  await second.getByRole('button', { name: '创建草稿' }).click()
  await expect(second.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '窗口 B 的新流程',
  )
  await page.reload()
  await page.getByRole('button', { name: '继续确认创建' }).click()
  await page.getByRole('button', { name: '重试创建', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '流程名称', exact: true })).toHaveValue(
    '窗口 A 的新流程',
  )
  expect(workflow.workflows.size).toBe(2)
  await second.close()
})
