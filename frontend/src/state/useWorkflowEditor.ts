import { useEffect, useState, useSyncExternalStore } from 'react'
import { z } from 'zod'
import { WorkflowApiError, workflowErrorMessage } from '../api/workflows'
import type { WorkflowApi } from '../api/workflows'
import {
  publishWorkflowRequestSchema,
  sameWorkflowDocument,
  workflowDocumentSchema,
  workflowDraftSchema,
  workflowPresentationSchema,
  WORKFLOW_MAX_DOCUMENT_BYTES,
  WORKFLOW_MAX_NODES,
} from '../data/workflowSchema'
import type {
  PublishWorkflowRequest,
  WorkflowDocument,
  WorkflowDraft,
  WorkflowRevision,
  WorkflowValidation,
} from '../data/workflowSchema'

type SaveAttempt = { version: number; document: WorkflowDocument }
type PendingPublication = { request: PublishWorkflowRequest; document: WorkflowDocument }
type SaveStatus = 'saved' | 'dirty' | 'saving' | 'error' | 'conflict'
export type WorkflowEditorState = {
  baseline: WorkflowDraft
  document: WorkflowDocument
  status: SaveStatus
  message: string
  past: WorkflowDocument[]
  future: WorkflowDocument[]
  storageError: boolean
  uncertainSave: SaveAttempt | null
  pendingPublish: PendingPublication | null
  validation: WorkflowValidation | null
  busy: boolean
}

// A name may be temporarily empty while typing. Keep those local edits across
// reloads; the strict wire schema still blocks sending an invalid document.
const editingName = z.string().refine((value) => [...value].length <= 120)
const localDocumentSchema = workflowDocumentSchema.extend({
  name: editingName,
  presentation: workflowPresentationSchema.extend({
    nodes: z
      .array(workflowPresentationSchema.shape.nodes.unwrap().element.extend({ label: editingName }))
      .max(WORKFLOW_MAX_NODES),
  }),
})
const backupSchema = z.strictObject({
  version: z.literal(1),
  baseline: workflowDraftSchema,
  document: localDocumentSchema,
  uncertainSave: z
    .object({ version: z.number().int().positive(), document: workflowDocumentSchema })
    .nullable(),
  pendingPublish: z
    .object({ request: publishWorkflowRequestSchema, document: workflowDocumentSchema })
    .nullable(),
})

/** Keep each tab's recovery copy separate while surviving a page reload. */
export function workflowStorageKey(base: string, workflowId: string): string {
  let tab = sessionStorage.getItem('atlas.workflow.tab.v1')
  if (!tab) {
    tab = crypto.randomUUID()
    sessionStorage.setItem('atlas.workflow.tab.v1', tab)
  }
  return `atlas.workflow.editor.v1:${encodeURIComponent(base)}:${workflowId}:${tab}`
}

/** Serialize saves, reconcile unknown outcomes, and keep history independent of runs. */
export class WorkflowEditorSession {
  private api: WorkflowApi
  private storage: Storage | null
  private tabStorage: Storage | null
  private key: string
  private state: WorkflowEditorState
  private listeners = new Set<() => void>()
  private saving: Promise<boolean> | null = null
  private group: { key: string; at: number } | null = null

  constructor(
    api: WorkflowApi,
    draft: WorkflowDraft,
    storage: Storage | null,
    key: string,
    tabStorage: Storage | null = null,
  ) {
    this.api = api
    this.storage = storage
    this.tabStorage = tabStorage
    this.key = key
    this.state = {
      baseline: draft,
      document: draft.document,
      status: 'saved',
      message: '',
      past: [],
      future: [],
      storageError: !storage,
      uncertainSave: null,
      pendingPublish: null,
      validation: null,
      busy: false,
    }
    try {
      // Duplicating a browser tab also duplicates sessionStorage's tab ID.
      // Its private copy takes precedence over the shared durable backup.
      const raw = tabStorage?.getItem(key) ?? storage?.getItem(key)
      if (raw) {
        const saved = backupSchema.parse(JSON.parse(raw))
        if (saved.baseline.workflow_id !== draft.workflow_id) throw new Error('Wrong workflow')
        this.state.pendingPublish = saved.pendingPublish
        this.state.uncertainSave = saved.uncertainSave
        if (
          saved.uncertainSave &&
          sameWorkflowDocument(saved.uncertainSave.document, draft.document)
        ) {
          // The server confirmed the in-flight snapshot. Keep edits made after
          // it was sent and use the confirmed version as their baseline.
          this.state.document = saved.document
          this.state.uncertainSave = null
          this.state.status = sameWorkflowDocument(saved.document, draft.document)
            ? 'saved'
            : 'dirty'
        } else if (sameWorkflowDocument(saved.document, draft.document)) {
          // Includes a saved response that was lost, or publication after reload.
          this.state.uncertainSave = null
        } else if (!sameWorkflowDocument(saved.document, saved.baseline.document)) {
          this.state.document = saved.document
          this.state.baseline = saved.baseline
          const conflict =
            saved.baseline.edit_version !== draft.edit_version ||
            !sameWorkflowDocument(saved.baseline.document, draft.document)
          this.state.status = conflict ? 'conflict' : 'dirty'
          this.state.message = conflict
            ? '已恢复本地修改，但服务器草稿已有更新。请另存副本或备份后载入。'
            : '已恢复上次未保存的本地修改。'
        }
      }
      tabStorage?.setItem(key, this.backup(this.state))
    } catch {
      this.state.storageError = true
      this.state.message = '本地恢复副本暂时无法读取，请保留当前页面并导出重要修改。'
    }
  }

  getSnapshot = () => this.state
  private backup(state: WorkflowEditorState) {
    return JSON.stringify({
      version: 1,
      baseline: state.baseline,
      document: state.document,
      uncertainSave: state.uncertainSave,
      pendingPublish: state.pendingPublish,
    })
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  private emit(patch: Partial<WorkflowEditorState>, persist = true): boolean {
    const next = { ...this.state, ...patch }
    let stored = !next.storageError
    if (persist) {
      try {
        if (!this.storage) throw new Error('No durable storage')
        const backup = this.backup(next)
        this.tabStorage?.setItem(this.key, backup)
        this.storage.setItem(this.key, backup)
        next.storageError = false
        stored = true
      } catch {
        next.storageError = true
        stored = false
      }
    }
    this.state = next
    this.listeners.forEach((listener) => listener())
    return stored
  }

  endGroup = () => {
    this.group = null
  }

  setViewport = (viewport: WorkflowDocument['presentation']['viewport']) => {
    if (this.state.busy || this.state.pendingPublish) return
    const document = {
      ...this.state.document,
      presentation: { ...this.state.document.presentation, viewport },
    }
    if (sameWorkflowDocument(document, this.state.document)) return
    // Zoom and pan are saved but do not consume a topology undo step.
    this.emit({
      document,
      validation: null,
      status: this.state.status === 'conflict' ? 'conflict' : 'dirty',
    })
  }

  change = (edit: (document: WorkflowDocument) => void, group?: string) => {
    if (this.state.busy || this.state.pendingPublish) return
    const next = structuredClone(this.state.document)
    edit(next)
    if (sameWorkflowDocument(next, this.state.document)) return
    const grouped = group && this.group?.key === group && Date.now() - this.group.at < 1000
    const past = grouped ? this.state.past : [...this.state.past.slice(-79), this.state.document]
    this.group = group ? { key: group, at: Date.now() } : null
    this.emit({
      document: next,
      past,
      future: [],
      validation: null,
      status: this.state.status === 'conflict' ? 'conflict' : 'dirty',
      message: this.state.status === 'conflict' ? this.state.message : '',
    })
  }

  undo = () => {
    if (!this.state.past.length || this.state.busy || this.state.pendingPublish) return
    this.group = null
    this.emit({
      document: this.state.past.at(-1)!,
      past: this.state.past.slice(0, -1),
      future: [this.state.document, ...this.state.future],
      validation: null,
      status: this.state.status === 'conflict' ? 'conflict' : 'dirty',
    })
  }

  redo = () => {
    if (!this.state.future.length || this.state.busy || this.state.pendingPublish) return
    this.group = null
    this.emit({
      document: this.state.future[0],
      future: this.state.future.slice(1),
      past: [...this.state.past, this.state.document],
      validation: null,
      status: this.state.status === 'conflict' ? 'conflict' : 'dirty',
    })
  }

  private accepted(draft: WorkflowDraft) {
    this.emit({
      baseline: draft,
      uncertainSave: null,
      status: sameWorkflowDocument(draft.document, this.state.document) ? 'saved' : 'dirty',
      message: '',
    })
  }

  private async reconcile(attempt: SaveAttempt): Promise<boolean> {
    try {
      const remote = await this.api.get(this.state.baseline.workflow_id)
      if (sameWorkflowDocument(remote.document, attempt.document)) {
        this.accepted(remote)
        return true
      }
      this.emit({
        status: 'conflict',
        uncertainSave: null,
        message:
          '保存响应未确认，服务器内容与本次提交不同。本地修改已保留，请另存副本或备份后载入。',
      })
    } catch {
      this.emit({
        status: 'error',
        uncertainSave: attempt,
        message: '保存结果尚未确认。重试会先回读服务器，本地修改已保留。',
      })
    }
    return false
  }

  private async saveLoop(): Promise<boolean> {
    if (this.state.status === 'conflict' || this.state.pendingPublish) return false
    if (this.state.uncertainSave && !(await this.reconcile(this.state.uncertainSave))) return false
    while (!sameWorkflowDocument(this.state.document, this.state.baseline.document)) {
      const document = workflowDocumentSchema.safeParse(this.state.document)
      if (
        !document.success ||
        new TextEncoder().encode(JSON.stringify(document.data)).length > WORKFLOW_MAX_DOCUMENT_BYTES
      ) {
        this.emit({
          status: 'error',
          message: '请填写有效的流程名称和节点参数，内容不能超过 256 KiB。',
        })
        return false
      }
      const attempt = { document: document.data, version: this.state.baseline.edit_version }
      // Preserve the exact in-flight document before sending, including layout.
      this.emit({ status: 'saving', uncertainSave: attempt, message: '' })
      try {
        const saved = await this.api.save(
          this.state.baseline.workflow_id,
          attempt.version,
          attempt.document,
        )
        this.accepted(saved)
      } catch (error) {
        if (!(error instanceof WorkflowApiError) || error.status === 0 || error.status >= 500) {
          if (!(await this.reconcile(attempt))) return false
        } else {
          this.emit({
            status: error.status === 409 ? 'conflict' : 'error',
            uncertainSave: null,
            message: workflowErrorMessage(error),
          })
          return false
        }
      }
    }
    this.emit({ status: 'saved' })
    return true
  }

  flush = async (): Promise<boolean> => {
    if (this.saving) return this.saving
    this.saving = this.saveLoop()
    try {
      return await this.saving
    } finally {
      this.saving = null
    }
  }

  validate = async (): Promise<WorkflowValidation | null> => {
    if (this.state.busy || this.state.pendingPublish) return null
    this.emit({ busy: true, validation: null })
    try {
      if (!(await this.flush())) return null
      const result = await this.api.validate(
        this.state.baseline.workflow_id,
        this.state.baseline.edit_version,
      )
      this.emit({
        validation: result,
        message: result.valid ? '已通过服务端发布校验。' : '校验未通过，请定位并修复问题。',
      })
      return result
    } catch (error) {
      this.emit({
        message: workflowErrorMessage(error),
        status:
          error instanceof WorkflowApiError && error.status === 409
            ? 'conflict'
            : this.state.status,
      })
      return null
    } finally {
      this.emit({ busy: false })
    }
  }

  publish = async (note = ''): Promise<WorkflowRevision | null> => {
    if (this.state.busy) return null
    if (!this.state.pendingPublish) {
      const validation = this.state.validation
      if (
        !validation?.valid ||
        validation.scope !== 'publication' ||
        validation.checked_edit_version !== this.state.baseline.edit_version ||
        !sameWorkflowDocument(this.state.document, this.state.baseline.document)
      )
        return null
      const pendingPublish = {
        request: {
          request_id: crypto.randomUUID(),
          expected_edit_version: this.state.baseline.edit_version,
          note,
        },
        document: this.state.document,
      }
      if (!this.emit({ pendingPublish })) {
        this.emit(
          { pendingPublish: null, message: '浏览器无法保存发布请求标识，请恢复本地存储后再发布。' },
          false,
        )
        return null
      }
    }
    const pending = this.state.pendingPublish!
    this.emit({ busy: true, message: '' })
    try {
      const result = await this.api.publish(this.state.baseline.workflow_id, pending.request)
      if (!sameWorkflowDocument(result.document, pending.document))
        throw new WorkflowApiError(0, 'workflow_response_invalid')
      this.emit({ pendingPublish: null, validation: null, message: '已发布，版本内容已固定。' })
      return result
    } catch (error) {
      const definite =
        error instanceof WorkflowApiError &&
        ((error.status >= 400 && error.status < 500) ||
          error.reason === 'workflow_runtime_unavailable')
      this.emit({
        pendingPublish: definite ? null : pending,
        validation: error instanceof WorkflowApiError ? (error.validation ?? null) : null,
        status:
          error instanceof WorkflowApiError && error.status === 409
            ? 'conflict'
            : this.state.status,
        message: definite
          ? workflowErrorMessage(error)
          : '发布结果尚未确认。请使用“重试发布”，将沿用原请求标识。',
      })
      return null
    } finally {
      this.emit({ busy: false })
    }
  }

  reload = async (): Promise<boolean> => {
    if (this.state.busy || this.saving || this.state.pendingPublish) return false
    this.emit({ busy: true })
    try {
      const draft = await this.api.get(this.state.baseline.workflow_id)
      this.emit({
        baseline: draft,
        document: draft.document,
        status: 'saved',
        past: [],
        future: [],
        uncertainSave: null,
        validation: null,
        message: '已载入服务器上的草稿。',
      })
      return true
    } catch (error) {
      this.emit({ message: workflowErrorMessage(error) })
      return false
    } finally {
      this.emit({ busy: false })
    }
  }
}

export function useWorkflowEditor(api: WorkflowApi, draft: WorkflowDraft, readOnly = false) {
  const [session] = useState(() => {
    if (readOnly) return new WorkflowEditorSession(api, draft, null, '')
    try {
      return new WorkflowEditorSession(
        api,
        draft,
        localStorage,
        workflowStorageKey(api.base, draft.workflow_id),
        sessionStorage,
      )
    } catch {
      return new WorkflowEditorSession(api, draft, null, '')
    }
  })
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot)
  useEffect(() => {
    if (readOnly || state.status !== 'dirty' || state.busy || state.pendingPublish) return
    const timer = window.setTimeout(() => {
      void session.flush()
    }, 800)
    return () => clearTimeout(timer)
  }, [session, state.document, state.status, state.busy, state.pendingPublish, readOnly])
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      const current = session.getSnapshot()
      if (
        !readOnly &&
        (current.pendingPublish ||
          current.uncertainSave ||
          !sameWorkflowDocument(current.document, current.baseline.document))
      ) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [session, readOnly])
  return { session, state }
}
