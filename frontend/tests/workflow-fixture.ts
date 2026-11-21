/** Stateful management substitute. Publication capability exists ONLY in these tests. */
import { readFileSync } from 'node:fs'
import type { Page } from '@playwright/test'
import { fakeConfig } from './langgraph-fixture'
import {
  createWorkflowRequestSchema,
  publishWorkflowRequestSchema,
  saveWorkflowDraftRequestSchema,
  validateWorkflowStructure,
  workflowDocumentSchema,
  workflowNodeCatalogSchema,
  workflowSemanticHash,
} from '../src/data/workflowSchema'
import type {
  WorkflowDocument,
  WorkflowDraft,
  WorkflowRevision,
  WorkflowSummary,
} from '../src/data/workflowSchema'

const examples = JSON.parse(
  readFileSync(
    new URL('../../tests/fixtures/workflows/v1-wire-examples.json', import.meta.url),
    'utf8',
  ),
).examples
export const catalog = workflowNodeCatalogSchema.parse(examples.WorkflowNodeCatalog)
const template = workflowDocumentSchema.parse(examples.WorkflowDocument)
const at = '2026-11-15T08:00:00Z'
type Entry = {
  draft: WorkflowDraft
  archived: boolean
  revisions: WorkflowRevision[]
  sequence: number
}

export function workflowFixture() {
  const workflows = new Map<string, Entry>()
  const creates = new Map<string, { body: string; draft: WorkflowDraft }>()
  const publications = new Map<string, { body: string; id: string; revision: WorkflowRevision }>()
  const calls = {
    saves: [] as { id: string; version: number; document: WorkflowDocument }[],
    publishes: [] as {
      id: string
      request_id: string
      expected_edit_version: number
      note: string
    }[],
    creates: [] as { request_id: string }[],
    reads: [] as string[],
    runs: [] as string[],
  }
  const control = {
    capable: true,
    runtimeUnavailable: false,
    loseSaveAfter: false,
    loseSaveBefore: false,
    readFailure: false,
    losePublishAfter: false,
    loseCreateAfter: false,
    holdSave: false,
    releaseSave: (() => {}) as () => void,
    rejectSave: false,
  }
  const seed = (name = '行业洞察 · 深度研究', document = structuredClone(template)) => {
    const sequence = workflows.size + 1
    const id = `workflow_${sequence}`
    document.name = name
    const draft: WorkflowDraft = {
      schema_version: 1,
      workflow_id: id,
      edit_version: 1,
      base_revision_id: null,
      document,
      updated_at: at,
    }
    workflows.set(id, { draft, archived: false, revisions: [], sequence })
    return id
  }
  const revisionSummary = (revision: WorkflowRevision) => ({
    workflow_id: revision.workflow_id,
    revision_id: revision.revision_id,
    revision_number: revision.revision_number,
    source_edit_version: revision.source_edit_version,
    semantic_hash: revision.semantic_hash,
    note: revision.note,
    published_at: revision.published_at,
  })
  const summary = (entry: Entry): WorkflowSummary => ({
    workflow_id: entry.draft.workflow_id,
    name: entry.draft.document.name,
    archived: entry.archived,
    edit_version: entry.draft.edit_version,
    base_revision_id: entry.draft.base_revision_id,
    latest_revision: entry.revisions.length ? revisionSummary(entry.revisions.at(-1)!) : null,
    created_at: at,
    updated_at: at,
  })
  const attach = async (page: Page) => {
    await page.route(
      (url) => url.pathname.startsWith('/api/'),
      async (route) => {
        const req = route.request()
        const url = new URL(req.url())
        const path = url.pathname.slice(4)
        const reply = (json: unknown, status = 200) => route.fulfill({ json, status })
        const fail = (reason: string, status = 409, extra = {}) =>
          reply({ reason, ...extra }, status)
        if (path === '/atlas/config')
          return reply({
            ...fakeConfig,
            ...(control.capable ? { workflow_editor_version: 1 } : {}),
          })
        if (!path.startsWith('/atlas/workflow')) {
          calls.runs.push(path)
          return reply({}, 404)
        }
        if (path === '/atlas/workflow-node-types') return reply(catalog)
        if (path === '/atlas/workflows' && req.method() === 'POST') {
          const parsed = createWorkflowRequestSchema.safeParse(req.postDataJSON())
          if (!parsed.success) return fail('workflow_request_invalid', 400)
          const body = parsed.data
          calls.creates.push(body)
          const prior = creates.get(body.request_id)
          if (prior)
            return prior.body === JSON.stringify(body)
              ? reply(prior.draft)
              : fail('workflow_request_conflict')
          let doc: WorkflowDocument
          if (body.source.kind === 'template') doc = structuredClone(template)
          else if (body.source.kind === 'import') doc = structuredClone(body.source.document)
          else {
            const reference = body.source.workflow_ref
            const original = workflows
              .get(reference.workflow_id)
              ?.revisions.find((item) => item.revision_id === reference.revision_id)
            if (!original) return fail('workflow_revision_not_found', 404)
            doc = structuredClone(original.document)
          }
          const id = seed(body.name, doc)
          const draft = workflows.get(id)!.draft
          creates.set(body.request_id, {
            body: JSON.stringify(body),
            draft: structuredClone(draft),
          })
          if (control.loseCreateAfter) {
            control.loseCreateAfter = false
            return route.abort('failed')
          }
          return reply(draft)
        }
        if (path === '/atlas/workflows') {
          const filter = url.searchParams.get('archived') ?? 'active'
          const after = Number(url.searchParams.get('after') ?? 0)
          const entries = [...workflows.values()]
            .reverse()
            .filter(
              (entry) =>
                (!after || entry.sequence < after) &&
                (filter === 'all' || entry.archived === (filter === 'archived')),
            )
          return reply({
            schema_version: 1,
            items: entries.slice(0, 30).map(summary),
            next_cursor: entries.length > 30 ? entries[29].sequence : null,
          })
        }
        const match = path.match(/^\/atlas\/workflows\/([^/]+)(?:\/(.*))?$/)
        if (!match) return reply({}, 404)
        const id = decodeURIComponent(match[1])
        const action = match[2] ?? ''
        const entry = workflows.get(id)
        if (!entry) return fail('workflow_not_found', 404)
        if (!action) {
          calls.reads.push(id)
          return control.readFailure
            ? fail('workflow_storage_unavailable', 503)
            : reply(entry.draft)
        }
        if (action === 'summary') return reply(summary(entry))
        if (action === 'revisions') {
          const after = Number(url.searchParams.get('after') ?? 0)
          const items = [...entry.revisions]
            .reverse()
            .filter((item) => !after || item.revision_number < after)
          return reply({
            schema_version: 1,
            items: items.slice(0, 30).map(revisionSummary),
            next_cursor: items.length > 30 ? items[29].revision_number : null,
          })
        }
        if (action.startsWith('revisions/')) {
          const revision = entry.revisions.find((item) => item.revision_id === action.slice(10))
          return revision ? reply(revision) : fail('workflow_revision_not_found', 404)
        }
        const body = req.postDataJSON()
        if (action === 'publish') {
          calls.publishes.push({ id, ...body })
          const prior = publications.get(body.request_id)
          if (prior)
            return prior.id === id && prior.body === JSON.stringify(body)
              ? reply(prior.revision)
              : fail('workflow_request_conflict')
        }
        if (entry.archived) return fail('workflow_archived')
        if (action === 'draft') {
          calls.saves.push({
            id,
            version: body.expected_edit_version,
            document: structuredClone(body.document),
          })
          if (control.holdSave) {
            control.holdSave = false
            await new Promise<void>((resolve) => {
              control.releaseSave = resolve
            })
          }
          if (control.loseSaveBefore) {
            control.loseSaveBefore = false
            return route.abort('failed')
          }
          if (control.rejectSave) return fail('workflow_request_invalid', 400)
        }
        if (body.expected_edit_version !== entry.draft.edit_version)
          return fail('workflow_edit_conflict', 409, {
            current_edit_version: entry.draft.edit_version,
          })
        if (action === 'draft') {
          const parsed = saveWorkflowDraftRequestSchema.safeParse(body)
          if (!parsed.success) return fail('workflow_request_invalid', 400)
          entry.draft = {
            ...entry.draft,
            document: structuredClone(parsed.data.document),
            edit_version: entry.draft.edit_version + 1,
          }
          if (control.loseSaveAfter) {
            control.loseSaveAfter = false
            return route.abort('failed')
          }
          return reply(entry.draft)
        }
        if (action === 'archive') {
          entry.archived = true
          return reply(summary(entry))
        }
        if (action === 'validate' || action === 'publish') {
          if (control.runtimeUnavailable) return fail('workflow_runtime_unavailable', 503)
          const validation = {
            ...validateWorkflowStructure(entry.draft.document, catalog),
            scope: 'publication',
            checked_edit_version: entry.draft.edit_version,
          }
          if (action === 'validate') return reply(validation)
          if (!validation.valid) return fail('workflow_validation_failed', 422, { validation })
          const parsed = publishWorkflowRequestSchema.safeParse(body)
          if (!parsed.success) return fail('workflow_request_invalid', 400)
          const revision: WorkflowRevision = {
            schema_version: 1,
            workflow_id: id,
            revision_id: `revision_${id}_${entry.revisions.length + 1}`,
            revision_number: entry.revisions.length + 1,
            source_edit_version: entry.draft.edit_version,
            semantic_hash: await workflowSemanticHash(entry.draft.document.definition),
            compatibility: {
              graph_id: 'research_workflow',
              compiler_version: 1,
              node_registry_version: 1,
              state_schema_version: 1,
            },
            document: structuredClone(entry.draft.document),
            note: body.note,
            published_at: at,
          }
          entry.revisions.push(revision)
          publications.set(body.request_id, {
            body: JSON.stringify(body),
            id,
            revision: structuredClone(revision),
          })
          entry.draft = {
            ...entry.draft,
            edit_version: entry.draft.edit_version + 1,
            base_revision_id: revision.revision_id,
          }
          if (control.losePublishAfter) {
            control.losePublishAfter = false
            return route.abort('failed')
          }
          return reply(revision)
        }
        return reply({}, 404)
      },
    )
  }
  return { attach, seed, workflows, control, calls }
}
export type WorkflowFixture = ReturnType<typeof workflowFixture>
