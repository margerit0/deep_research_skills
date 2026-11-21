import { z } from 'zod'
import { apiUrl } from './langgraph'
import {
  createWorkflowRequestSchema,
  publishWorkflowRequestSchema,
  saveWorkflowDraftRequestSchema,
  sameWorkflowDocument,
  workflowDraftSchema,
  workflowNodeCatalogSchema,
  workflowPageSchema,
  workflowRevisionPageSchema,
  workflowRevisionSchema,
  workflowSemanticHash,
  workflowSummarySchema,
  workflowValidationSchema,
} from '../data/workflowSchema'
import type {
  CreateWorkflowRequest,
  PublishWorkflowRequest,
  WorkflowDocument,
  WorkflowValidation,
} from '../data/workflowSchema'

const failureSchema = z.object({
  reason: z.string(),
  current_edit_version: z.number().int().positive().optional(),
  validation: workflowValidationSchema.optional(),
})

export class WorkflowApiError extends Error {
  status: number
  reason: string
  currentEditVersion?: number
  validation?: WorkflowValidation
  constructor(
    status: number,
    reason: string,
    currentEditVersion?: number,
    validation?: WorkflowValidation,
  ) {
    super(reason)
    this.status = status
    this.reason = reason
    this.currentEditVersion = currentEditVersion
    this.validation = validation
  }
}

export function workflowErrorMessage(error: unknown): string {
  const reason = error instanceof WorkflowApiError ? error.reason : ''
  const messages: Record<string, string> = {
    workflow_edit_conflict: '服务器上已有较新的草稿。本地修改已保留，请另存副本或备份后载入。',
    workflow_request_conflict: '此请求标识已用于不同内容，请先核对服务器记录。',
    workflow_archived: '此流程已归档。可以查看或另存副本。',
    workflow_not_found: '没有找到此流程。',
    workflow_revision_not_found: '没有找到此发布版本。',
    workflow_runtime_unavailable: '当前服务尚未开放流程发布，草稿仍可保存和编辑。',
    workflow_editor_unavailable: '当前服务尚未开放流程编辑。',
    workflow_validation_failed: '校验未通过，请先修复下方问题。',
    workflow_request_invalid: '内容不符合流程格式，请检查名称、参数和导入文件。',
    workflow_document_too_large: '流程内容超过 256 KiB 上限。',
    workflow_archive_invalid: '此版本的数据未通过完整性检查，暂时无法打开。',
    workflow_storage_incompatible: '当前服务无法读取此流程存储版本。',
    workflow_response_invalid: '服务器返回的流程信息不完整，请回读后重试。',
  }
  return messages[reason] ?? '暂时无法连接流程服务。当前内容已保留，可稍后重试。'
}

/** All identities and publication decisions come from the management service. */
export function workflowApi(base = apiUrl) {
  const path = (id: string) => `/atlas/workflows/${encodeURIComponent(id)}`
  const request = async <T>(
    url: string,
    schema: z.ZodType<T>,
    method = 'GET',
    body?: unknown,
  ): Promise<T> => {
    let response: Response
    try {
      response = await fetch(`${base}${url}`, {
        method,
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      })
    } catch {
      throw new WorkflowApiError(0, 'workflow_network_unknown')
    }
    const value: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      const failure = failureSchema.safeParse(value)
      throw new WorkflowApiError(
        response.status,
        failure.success ? failure.data.reason : 'workflow_service_unavailable',
        failure.success ? failure.data.current_edit_version : undefined,
        failure.success ? failure.data.validation : undefined,
      )
    }
    const parsed = schema.safeParse(value)
    if (!parsed.success) throw new WorkflowApiError(0, 'workflow_response_invalid')
    return parsed.data
  }
  const assert = (condition: boolean) => {
    if (!condition) throw new WorkflowApiError(0, 'workflow_response_invalid')
  }
  const get = async (id: string) => {
    const draft = await request(path(id), workflowDraftSchema)
    assert(draft.workflow_id === id)
    return draft
  }
  const checkedRevision = async (id: string, url: string, method = 'GET', body?: unknown) => {
    const result = await request(url, workflowRevisionSchema, method, body)
    assert(
      result.workflow_id === id &&
        result.semantic_hash === (await workflowSemanticHash(result.document.definition)),
    )
    return result
  }
  return {
    base,
    get,
    catalog: () => request('/atlas/workflow-node-types', workflowNodeCatalogSchema),
    list: (archived = 'active', after = 0) =>
      request(`/atlas/workflows?archived=${archived}&after=${after}&limit=30`, workflowPageSchema),
    summary: async (id: string) => {
      const result = await request(`${path(id)}/summary`, workflowSummarySchema)
      assert(
        result.workflow_id === id &&
          (!result.latest_revision || result.latest_revision.workflow_id === id),
      )
      return result
    },
    create: (body: CreateWorkflowRequest) =>
      request(
        '/atlas/workflows',
        workflowDraftSchema,
        'POST',
        createWorkflowRequestSchema.parse(body),
      ),
    save: async (id: string, version: number, document: WorkflowDocument) => {
      const result = await request(
        `${path(id)}/draft`,
        workflowDraftSchema,
        'PUT',
        saveWorkflowDraftRequestSchema.parse({ expected_edit_version: version, document }),
      )
      assert(
        result.workflow_id === id &&
          result.edit_version === version + 1 &&
          sameWorkflowDocument(result.document, document),
      )
      return result
    },
    validate: async (id: string, version: number) => {
      const result = await request(`${path(id)}/validate`, workflowValidationSchema, 'POST', {
        expected_edit_version: version,
      })
      assert(result.scope === 'publication' && result.checked_edit_version === version)
      return result
    },
    publish: async (id: string, body: PublishWorkflowRequest) => {
      const result = await checkedRevision(
        id,
        `${path(id)}/publish`,
        'POST',
        publishWorkflowRequestSchema.parse(body),
      )
      assert(result.source_edit_version === body.expected_edit_version && result.note === body.note)
      return result
    },
    revisions: async (id: string, after = 0) => {
      const result = await request(
        `${path(id)}/revisions?after=${after}&limit=30`,
        workflowRevisionPageSchema,
      )
      assert(result.items.every((item) => item.workflow_id === id))
      return result
    },
    revision: async (id: string, revisionId: string) => {
      const result = await checkedRevision(
        id,
        `${path(id)}/revisions/${encodeURIComponent(revisionId)}`,
      )
      assert(result.revision_id === revisionId)
      return result
    },
    archive: async (id: string, version: number) => {
      const result = await request(`${path(id)}/archive`, workflowSummarySchema, 'POST', {
        expected_edit_version: version,
      })
      assert(result.workflow_id === id && result.archived)
      return result
    },
  }
}
export type WorkflowApi = ReturnType<typeof workflowApi>
