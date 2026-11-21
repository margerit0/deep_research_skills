import { z } from 'zod'

export const WORKFLOW_MAX_NODES = 30
export const WORKFLOW_MAX_EDGES = 60
export const WORKFLOW_MAX_DOCUMENT_BYTES = 262_144
export const workflowModelRoles = [
  'SCOPING',
  'SUPERVISOR',
  'RESEARCHER',
  'SUMMARIZATION',
  'COMPRESSION',
  'FINAL_REPORT',
] as const

// Python measures Unicode code points, not JavaScript UTF-16 code units.
const text = (maximum: number, minimum = 0) =>
  z.string().refine((value) => [...value].length >= minimum && [...value].length <= maximum)
const identifier = text(128, 1)
  .regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/)
  .refine((v) => !/\s/.test(v))
const nodeId = text(64, 1)
  .regex(/^[a-z][a-z0-9_-]*$/)
  .refine((v) => !/\s/.test(v))
const digest = z
  .string()
  .regex(/^[a-f0-9]{64}$/)
  .length(64)
const uuidText = z
  .string()
  .regex(/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/)
  .length(36)
const name = text(120, 1).regex(/\S/)
const positiveVersion = z.number().int().min(1).max(Number.MAX_SAFE_INTEGER)
const timestamp = z.iso
  .datetime({ offset: true })
  .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/)
const modelRole = z.enum(workflowModelRoles)
const jsonObject = z.record(z.string(), z.json())

export const workflowSkillsSchema = z
  .strictObject({
    mode: z.enum(['auto', 'manual']),
    allowed: z.array(name).max(100),
  })
  .refine(
    (value) =>
      new Set(value.allowed).size === value.allowed.length &&
      (value.mode !== 'auto' || value.allowed.length === 0),
  )

export const workflowSelectionSchema = z.strictObject({
  version: z.literal(1).default(1),
  models: z.record(modelRole, digest),
  skills: workflowSkillsSchema,
})
export const workflowDefaultsSchema = z.strictObject({
  selection: workflowSelectionSchema.nullable().default(null),
})
export const workflowNodeSchema = z.strictObject({
  id: nodeId,
  type: nodeId,
  type_version: positiveVersion.default(1),
  parameters: z.strictObject({ instructions: text(4000).optional() }).default({}),
})
export const workflowEdgeSchema = z.strictObject({
  id: identifier,
  source: nodeId,
  source_port: z.literal('out').default('out'),
  target: nodeId,
  target_port: z.literal('in').default('in'),
})
export const workflowDefinitionSchema = z.strictObject({
  schema_version: z.literal(1).default(1),
  nodes: z.array(workflowNodeSchema).max(WORKFLOW_MAX_NODES),
  edges: z.array(workflowEdgeSchema).max(WORKFLOW_MAX_EDGES),
  defaults: workflowDefaultsSchema.default({ selection: null }),
})
const positionSchema = z.strictObject({
  x: z.number().min(-1_000_000).max(1_000_000),
  y: z.number().min(-1_000_000).max(1_000_000),
})
export const workflowPresentationSchema = z.strictObject({
  schema_version: z.literal(1).default(1),
  nodes: z
    .array(
      z.strictObject({
        node_id: nodeId,
        label: name,
        position: positionSchema,
      }),
    )
    .max(WORKFLOW_MAX_NODES)
    .default([]),
  viewport: positionSchema
    .extend({ zoom: z.number().min(0.2).max(2) })
    .default({ x: 0, y: 0, zoom: 1 }),
})
export const workflowDocumentSchema = z.strictObject({
  name,
  definition: workflowDefinitionSchema,
  presentation: workflowPresentationSchema.default({
    schema_version: 1,
    nodes: [],
    viewport: { x: 0, y: 0, zoom: 1 },
  }),
})
export const workflowRefSchema = z.strictObject({
  workflow_id: identifier,
  revision_id: identifier,
})
export const workflowCompatibilitySchema = z.strictObject({
  graph_id: z.literal('research_workflow').default('research_workflow'),
  compiler_version: positiveVersion,
  node_registry_version: positiveVersion,
  state_schema_version: positiveVersion,
})
export const workflowDraftSchema = z.strictObject({
  schema_version: z.literal(1).default(1),
  workflow_id: identifier,
  edit_version: positiveVersion,
  base_revision_id: identifier.nullable().default(null),
  document: workflowDocumentSchema,
  updated_at: timestamp,
})
export const workflowRevisionSchema = z.strictObject({
  schema_version: z.literal(1).default(1),
  workflow_id: identifier,
  revision_id: identifier,
  revision_number: positiveVersion,
  source_edit_version: positiveVersion,
  semantic_hash: digest,
  compatibility: workflowCompatibilitySchema,
  document: workflowDocumentSchema,
  note: text(2000).default(''),
  published_at: timestamp,
})
export const workflowBindingSchema = z.strictObject({
  schema_version: z.literal(1).default(1),
  thread_id: identifier,
  workflow_ref: workflowRefSchema,
  semantic_hash: digest,
  compatibility: workflowCompatibilitySchema,
  bound_at: timestamp,
})
export const workflowIssueSchema = z.strictObject({
  code: identifier,
  severity: z.enum(['error', 'warning']).default('error'),
  message: text(500, 1),
  node_id: nodeId.nullable().default(null),
  edge_id: identifier.nullable().default(null),
  field: text(500).nullable().default(null),
})
export const workflowValidationSchema = z
  .strictObject({
    schema_version: z.literal(1).default(1),
    scope: z.enum(['structure', 'publication']).default('structure'),
    valid: z.boolean(),
    checked_edit_version: positiveVersion.nullable().default(null),
    issues: z.array(workflowIssueSchema).max(100),
    truncated: z.boolean().default(false),
  })
  .refine(
    (result) =>
      (result.scope !== 'publication' || result.checked_edit_version !== null) &&
      result.valid ===
        (!result.truncated && !result.issues.some((issue) => issue.severity === 'error')),
  )

export const createWorkflowRequestSchema = z.strictObject({
  request_id: identifier,
  name,
  source: z.discriminatedUnion('kind', [
    z.strictObject({ kind: z.literal('template'), template_id: z.literal('standard_research') }),
    z.strictObject({ kind: z.literal('revision'), workflow_ref: workflowRefSchema }),
    z.strictObject({ kind: z.literal('import'), document: workflowDocumentSchema }),
  ]),
})
export const saveWorkflowDraftRequestSchema = z.strictObject({
  expected_edit_version: positiveVersion,
  document: workflowDocumentSchema,
})
export const validateWorkflowRequestSchema = z.strictObject({
  expected_edit_version: positiveVersion,
})
export const publishWorkflowRequestSchema = validateWorkflowRequestSchema.extend({
  request_id: identifier,
  note: text(2000).default(''),
})
export const archiveWorkflowRequestSchema = validateWorkflowRequestSchema
export const workflowRevisionSummarySchema = workflowRevisionSchema.pick({
  workflow_id: true,
  revision_id: true,
  revision_number: true,
  source_edit_version: true,
  semantic_hash: true,
  note: true,
  published_at: true,
})
export const workflowSummarySchema = z.strictObject({
  workflow_id: identifier,
  name,
  archived: z.boolean(),
  edit_version: positiveVersion,
  base_revision_id: identifier.nullable(),
  latest_revision: workflowRevisionSummarySchema.nullable(),
  created_at: timestamp,
  updated_at: timestamp,
})
export const workflowPageSchema = z.strictObject({
  schema_version: z.literal(1).default(1),
  items: z.array(workflowSummarySchema).max(100),
  next_cursor: positiveVersion.nullable(),
})
export const workflowRevisionPageSchema = z.strictObject({
  schema_version: z.literal(1).default(1),
  items: z.array(workflowRevisionSummarySchema).max(100),
  next_cursor: positiveVersion.nullable(),
})
export const workflowConflictSchema = z.strictObject({
  reason: z.enum([
    'workflow_edit_conflict',
    'workflow_request_conflict',
    'workflow_archived',
    'workflow_binding_conflict',
    'legacy_workflow_locked',
  ]),
  current_edit_version: positiveVersion.nullable().default(null),
})
export const workflowNodeEventSchema = z.strictObject({
  version: z.literal(1).default(1),
  id: uuidText,
  thread_id: identifier,
  research_id: identifier,
  turn_id: identifier,
  run_id: uuidText,
  attempt_id: identifier,
  workflow_ref: workflowRefSchema,
  semantic_hash: digest,
  node_id: nodeId,
  node_type: nodeId,
  sequence: positiveVersion,
  at: timestamp,
  kind: z.enum(['started', 'completed', 'awaiting_input', 'failed', 'partial']),
  elapsed_ms: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
  summary: text(2000).default(''),
})
export const workflowBusinessResultSchema = z.strictObject({
  outcome: z.enum(['continue', 'awaiting_input', 'failed', 'partial']),
})
export const workflowNodeTypeSchema = z.strictObject({
  type: nodeId,
  type_version: positiveVersion.default(1),
  label: z.string(),
  kind: z.enum(['system', 'core', 'extension']),
  min_instances: z.number().int().min(0).max(1),
  max_instances: z.number().int().min(1).max(30).nullable(),
  fixed_id: nodeId.nullable(),
  input_label: z.string().nullable(),
  output_label: z.string().nullable(),
  successor_types: z.array(nodeId),
  model_roles: z.array(modelRole),
  parameter_fields: z.array(z.literal('instructions')),
  parameters_schema: jsonObject,
  default_parameters: jsonObject,
  state_reads: z.array(identifier),
  state_writes: z.record(z.string(), z.enum(['replace', 'overwrite', 'merge_messages'])),
  outcomes: z.array(z.enum(['continue', 'awaiting_input', 'failed', 'partial'])),
  safe_recovery: z.boolean(),
})
export const workflowNodeCatalogSchema = z.strictObject({
  schema_version: z.literal(1).default(1),
  registry_version: positiveVersion.default(1),
  node_types: z.array(workflowNodeTypeSchema),
})

export type WorkflowNode = z.infer<typeof workflowNodeSchema>
export type WorkflowEdge = z.infer<typeof workflowEdgeSchema>
export type WorkflowDefinition = z.infer<typeof workflowDefinitionSchema>
export type WorkflowDocument = z.infer<typeof workflowDocumentSchema>
export type WorkflowDraft = z.infer<typeof workflowDraftSchema>
export type WorkflowRevision = z.infer<typeof workflowRevisionSchema>
export type WorkflowSummary = z.infer<typeof workflowSummarySchema>
export type WorkflowRevisionSummary = z.infer<typeof workflowRevisionSummarySchema>
export type CreateWorkflowRequest = z.infer<typeof createWorkflowRequestSchema>
export type PublishWorkflowRequest = z.infer<typeof publishWorkflowRequestSchema>
export type WorkflowRef = z.infer<typeof workflowRefSchema>
export type WorkflowBinding = z.infer<typeof workflowBindingSchema>
export type WorkflowIssue = z.infer<typeof workflowIssueSchema>
export type WorkflowValidation = z.infer<typeof workflowValidationSchema>
export type WorkflowNodeCatalog = z.infer<typeof workflowNodeCatalogSchema>
export type WorkflowNodeType = z.infer<typeof workflowNodeTypeSchema>
export type WorkflowNodeEvent = z.infer<typeof workflowNodeEventSchema>

/** Compare the complete saved content; a semantic hash excludes names and layout. */
export function sameWorkflowDocument(a: WorkflowDocument, b: WorkflowDocument): boolean {
  const stable = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(stable)
    if (value && typeof value === 'object')
      return Object.fromEntries(
        Object.entries(value)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([key, item]) => [key, stable(item)]),
      )
    return value
  }
  return JSON.stringify(stable(a)) === JSON.stringify(stable(b))
}

const processingParametersSchema = z.strictObject({ instructions: text(4000, 1).regex(/\S/) })
const emptyParametersSchema = z.strictObject({})
const pointer = (parts: PropertyKey[]) =>
  (
    '/' + parts.map((part) => String(part).replace(/~/g, '~0').replace(/\//g, '~1')).join('/')
  ).slice(0, 500)

/** Preflight only. Availability and authoritative publication checks stay on the server. */
export function validateWorkflowStructure(
  value: unknown,
  catalog: WorkflowNodeCatalog,
): WorkflowValidation {
  const issues: WorkflowIssue[] = []
  const issue = (
    code: string,
    message: string,
    node: string | null = null,
    edge: string | null = null,
    field: string | null = null,
  ) => issues.push({ code, message, node_id: node, edge_id: edge, field, severity: 'error' })
  const finish = (): WorkflowValidation => ({
    schema_version: 1,
    scope: 'structure',
    valid: issues.length === 0,
    checked_edit_version: null,
    issues: issues.slice(0, 100),
    truncated: issues.length > 100,
  })
  const schemaIssues = (
    errors: z.core.$ZodIssue[],
    prefix: PropertyKey[] = [],
    node: string | null = null,
  ) => {
    for (const error of errors) {
      const paths =
        error.code === 'unrecognized_keys'
          ? error.keys.map((key) => [...error.path, key])
          : [error.path]
      for (const path of paths)
        issue(
          node ? 'node_parameters_invalid' : 'schema_invalid',
          node
            ? '请按节点要求填写参数，不能添加未开放的参数。'
            : '字段类型、取值或大小不符合流程协议。',
          node,
          null,
          pointer([...prefix, ...path]),
        )
    }
  }
  try {
    const serialized = JSON.stringify(value)
    if (serialized === undefined) throw new Error('Missing JSON value')
    if (new TextEncoder().encode(serialized).length > WORKFLOW_MAX_DOCUMENT_BYTES) {
      issue('document_too_large', '流程内容超过 256 KiB 上限。', null, null, '/')
      return finish()
    }
  } catch {
    issue('schema_invalid', '流程必须使用有限的 JSON 数据。', null, null, '/')
    return finish()
  }
  const parsed = workflowDocumentSchema.safeParse(value)
  if (!parsed.success) {
    schemaIssues(parsed.error.issues)
    return finish()
  }
  if (catalog.registry_version !== 1) {
    issue('workflow_runtime_incompatible', '当前节点目录版本不兼容。', null, null, '/definition')
    return finish()
  }
  const document = parsed.data
  const { nodes, edges } = document.definition
  const registry = new Map(catalog.node_types.map((item) => [item.type, item]))
  const byId = new Map<string, WorkflowNode>()
  let duplicateNodes = false
  nodes.forEach((node, index) => {
    const prefix = `/definition/nodes/${index}`
    if (byId.has(node.id)) {
      duplicateNodes = true
      issue('node_id_duplicate', '节点标识重复。', node.id, null, `${prefix}/id`)
    }
    byId.set(node.id, node)
    const description = registry.get(node.type)
    if (!description) {
      issue('node_type_unknown', '当前服务不支持此节点类型。', node.id, null, `${prefix}/type`)
      return
    }
    if (node.type_version !== description.type_version)
      issue(
        'node_type_version_unsupported',
        '节点实现版本不受支持。',
        node.id,
        null,
        `${prefix}/type_version`,
      )
    if (
      (description.fixed_id && node.id !== description.fixed_id) ||
      (description.kind === 'extension' && registry.has(node.id))
    )
      issue(
        'core_node_id',
        '基础节点或类型的保留标识不能更改或占用。',
        node.id,
        null,
        `${prefix}/id`,
      )
    const schema = description.parameter_fields.includes('instructions')
      ? processingParametersSchema
      : emptyParametersSchema
    const parameters = schema.safeParse(node.parameters)
    if (!parameters.success)
      schemaIssues(parameters.error.issues, ['definition', 'nodes', index, 'parameters'], node.id)
  })
  for (const description of registry.values()) {
    const count = nodes.filter((node) => node.type === description.type).length
    if (
      count < description.min_instances ||
      (description.max_instances !== null && count > description.max_instances)
    )
      issue(
        'node_count',
        `「${description.label}」的数量不符合要求。`,
        description.fixed_id,
        null,
        '/definition/nodes',
      )
  }
  const incoming = new Map([...byId.keys()].map((id) => [id, [] as string[]]))
  const outgoing = new Map([...byId.keys()].map((id) => [id, [] as string[]]))
  const edgeIds = new Set<string>(),
    pairs = new Set<string>()
  edges.forEach((edge, index) => {
    const prefix = `/definition/edges/${index}`
    if (edgeIds.has(edge.id))
      issue('edge_id_duplicate', '连接标识重复。', null, edge.id, `${prefix}/id`)
    edgeIds.add(edge.id)
    const pair = `${edge.source}|${edge.target}`
    if (pairs.has(pair)) issue('edge_duplicate', '同一对端口不能重复连接。', null, edge.id, prefix)
    pairs.add(pair)
    const sourceNode = byId.get(edge.source),
      targetNode = byId.get(edge.target)
    if (!sourceNode || !targetNode) {
      issue('edge_node_missing', '连接引用了不存在的节点。', null, edge.id, prefix)
      return
    }
    outgoing.get(edge.source)!.push(edge.target)
    incoming.get(edge.target)!.push(edge.source)
    const source = registry.get(sourceNode.type),
      target = registry.get(targetNode.type)
    if (source && target) {
      if (source.output_label === null || target.input_label === null)
        issue('edge_port_invalid', '开始没有输入端口，结束没有输出端口。', null, edge.id, prefix)
      if (!source.successor_types.includes(target.type))
        issue('stage_order_invalid', '连接不符合研究阶段顺序。', null, edge.id, prefix)
    }
  })
  if (!duplicateNodes) {
    nodes.forEach((node, index) => {
      if (incoming.get(node.id)!.length !== (node.type === 'start' ? 0 : 1))
        issue(
          'input_count',
          '除开始节点外，每个节点须有且仅有一个正常入口。',
          node.id,
          null,
          `/definition/nodes/${index}`,
        )
      if (outgoing.get(node.id)!.length !== (node.type === 'end' ? 0 : 1))
        issue(
          'output_count',
          '除结束节点外，每个节点须有且仅有一个正常出口。',
          node.id,
          null,
          `/definition/nodes/${index}`,
        )
    })
    const remaining = new Map([...incoming].map(([id, parents]) => [id, parents.length]))
    const queue = [...remaining].filter(([, degree]) => !degree).map(([id]) => id)
    for (let index = 0; index < queue.length; index++)
      for (const successor of outgoing.get(queue[index])!) {
        const next = remaining.get(successor)! - 1
        remaining.set(successor, next)
        if (!next) queue.push(successor)
      }
    if ([...remaining.values()].some(Boolean))
      issue('cycle', '首版主流程不能包含自环或循环。', null, null, '/definition/edges')
    const starts = nodes.filter((node) => node.type === 'start')
    if (starts.length === 1) {
      const reached = new Set<string>(),
        pending = [starts[0].id]
      while (pending.length) {
        const id = pending.pop()!
        if (reached.has(id)) continue
        reached.add(id)
        pending.push(...outgoing.get(id)!)
      }
      nodes.forEach((node, index) => {
        if (!reached.has(node.id))
          issue(
            'node_unreachable',
            '节点无法从开始节点到达。',
            node.id,
            null,
            `/definition/nodes/${index}`,
          )
      })
    }
  }
  const presentationIds = new Set<string>()
  document.presentation.nodes.forEach((item, index) => {
    if (presentationIds.has(item.node_id))
      issue(
        'presentation_duplicate',
        '同一节点不能保存两份展示信息。',
        item.node_id,
        null,
        `/presentation/nodes/${index}/node_id`,
      )
    presentationIds.add(item.node_id)
    if (!byId.has(item.node_id))
      issue(
        'presentation_node_missing',
        '展示信息引用了不存在的节点。',
        item.node_id,
        null,
        `/presentation/nodes/${index}/node_id`,
      )
  })
  return finish()
}

function canonicalJSON(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonicalJSON).join(',') + ']'
  if (value !== null && typeof value === 'object')
    return (
      '{' +
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, entry]) => JSON.stringify(key) + ':' + canonicalJSON(entry))
        .join(',') +
      '}'
    )
  return JSON.stringify(value)
}

/** Match the server's hash for validated v1 nodes (only empty or text parameters). */
export async function workflowSemanticHash(definition: WorkflowDefinition): Promise<string> {
  const value = structuredClone(workflowDefinitionSchema.parse(definition))
  value.nodes.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
  const edges = value.edges.map(({ source, source_port, target, target_port }) => ({
    source,
    source_port,
    target,
    target_port,
  }))
  const keys = ['source', 'source_port', 'target', 'target_port'] as const
  edges.sort((a, b) => {
    for (const key of keys) {
      if (a[key] < b[key]) return -1
      if (a[key] > b[key]) return 1
    }
    return 0
  })
  value.defaults.selection?.skills.allowed.sort()
  const payload = canonicalJSON({ ...value, edges })
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(payload))
  return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}
