import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import type { ZodType } from 'zod'
import * as workflow from '../src/data/workflowSchema'

const fixture = JSON.parse(
  readFileSync(
    new URL('../../tests/fixtures/workflows/v1-wire-examples.json', import.meta.url),
    'utf8',
  ),
) as {
  examples: Record<string, unknown>
  hash_examples: Record<string, { definition: unknown; semantic_hash: string }>
}
const cases = JSON.parse(
  readFileSync(new URL('../../tests/fixtures/workflows/v1-cases.json', import.meta.url), 'utf8'),
).cases as {
  id: string
  base: string | null
  changes: { op: 'set' | 'remove' | 'append'; path: string; value?: unknown }[]
  schema_valid: boolean
  codes: string[]
}[]
const examples = fixture.examples
const catalog = workflow.workflowNodeCatalogSchema.parse(examples.WorkflowNodeCatalog)
const documents = new Map<string, unknown>()
const get = (value: unknown, key: string): unknown =>
  Array.isArray(value) ? value[Number(key)] : (value as Record<string, unknown>)[key]
for (const sample of cases) {
  const value = structuredClone(
    sample.base ? documents.get(sample.base) : examples.WorkflowDocument,
  )
  for (const change of sample.changes) {
    const parts = change.path.slice(1).split('/')
    let current: unknown = value
    for (const part of parts.slice(0, -1)) current = get(current, part)
    const key = parts[parts.length - 1]
    if (change.op === 'append') (get(current, key) as unknown[]).push(structuredClone(change.value))
    else if (change.op === 'remove') {
      if (Array.isArray(current)) current.splice(Number(key), 1)
      else delete (current as Record<string, unknown>)[key]
    } else if (Array.isArray(current)) current[Number(key)] = structuredClone(change.value)
    else (current as Record<string, unknown>)[key] = structuredClone(change.value)
  }
  documents.set(sample.id, value)
}

for (const sample of cases)
  test(`workflow v1 structure: ${sample.id}`, () => {
    const value = documents.get(sample.id)
    expect(workflow.workflowDocumentSchema.safeParse(value).success).toBe(sample.schema_valid)
    const result = workflow.validateWorkflowStructure(value, catalog)
    expect([...new Set(result.issues.map((issue) => issue.code))].sort()).toEqual(sample.codes)
    expect(result.valid).toBe(sample.codes.length === 0)
    expect(result.scope).toBe('structure')
    expect(JSON.stringify(result)).not.toContain('synthetic-sensitive-value')
    expect(workflow.workflowValidationSchema.safeParse(result).success).toBe(true)
  })

const schemas: Record<string, ZodType> = {
  WorkflowDocument: workflow.workflowDocumentSchema,
  WorkflowDraft: workflow.workflowDraftSchema,
  WorkflowRevision: workflow.workflowRevisionSchema,
  WorkflowRef: workflow.workflowRefSchema,
  WorkflowBinding: workflow.workflowBindingSchema,
  WorkflowValidation: workflow.workflowValidationSchema,
  CreateWorkflowRequest: workflow.createWorkflowRequestSchema,
  SaveDraftRequest: workflow.saveWorkflowDraftRequestSchema,
  ValidateWorkflowRequest: workflow.validateWorkflowRequestSchema,
  PublishWorkflowRequest: workflow.publishWorkflowRequestSchema,
  WorkflowConflict: workflow.workflowConflictSchema,
  WorkflowNodeEvent: workflow.workflowNodeEventSchema,
  WorkflowBusinessResult: workflow.workflowBusinessResultSchema,
  WorkflowNodeCatalog: workflow.workflowNodeCatalogSchema,
}
for (const [name, schema] of Object.entries(schemas))
  test(`workflow v1 wire: ${name}`, () => {
    expect(schema.parse(examples[name])).toEqual(examples[name])
  })

for (const [name, sample] of Object.entries(fixture.hash_examples))
  test(`workflow v1 cross-language hash: ${name}`, async () => {
    const definition = workflow.workflowDefinitionSchema.parse(sample.definition)
    expect(await workflow.workflowSemanticHash(definition)).toBe(sample.semantic_hash)
    definition.nodes.reverse()
    definition.edges.reverse()
    definition.edges.forEach((edge, index) => {
      edge.id = `another_edge_${index}`
    })
    definition.defaults.selection?.skills.allowed.reverse()
    expect(await workflow.workflowSemanticHash(definition)).toBe(sample.semantic_hash)
  })

test('workflow hash changes when processing instructions change', async () => {
  const definition = workflow.workflowDefinitionSchema.parse(
    fixture.hash_examples.processing.definition,
  )
  const before = await workflow.workflowSemanticHash(definition)
  definition.nodes.find((node) => node.type === 'optimize_plan')!.parameters.instructions =
    '改变研究要求'
  expect(await workflow.workflowSemanticHash(definition)).not.toBe(before)
})

for (const [extra, valid] of [
  [23, true],
  [24, false],
] as const)
  test(`main-node limit includes system nodes: ${extra + 7}`, () => {
    const document = workflow.workflowDocumentSchema.parse(examples.WorkflowDocument)
    document.definition.nodes.splice(
      4,
      0,
      ...Array.from({ length: extra }, (_, index) => ({
        id: `plan_${index}`,
        type: 'optimize_plan',
        type_version: 1,
        parameters: { instructions: '核对证据' },
      })),
    )
    document.definition.edges = document.definition.nodes.slice(0, -1).map((node, index) => ({
      id: `edge_${index}`,
      source: node.id,
      source_port: 'out',
      target: document.definition.nodes[index + 1].id,
      target_port: 'in',
    }))
    expect(workflow.validateWorkflowStructure(document, catalog).valid).toBe(valid)
  })

for (const [count, valid] of [
  [4000, true],
  [4001, false],
] as const)
  test(`Unicode instruction length: ${count}`, () => {
    const value = workflow.workflowDocumentSchema.parse(documents.get('extensions'))
    value.definition.nodes[7].parameters.instructions = '😀'.repeat(count)
    expect(workflow.validateWorkflowStructure(value, catalog).valid).toBe(valid)
  })

test('workflow size is bounded by UTF-8 bytes', () => {
  const value = workflow.workflowDocumentSchema.parse(documents.get('extensions'))
  value.definition.nodes[7].parameters.instructions = '密'.repeat(90_000)
  expect(
    workflow.validateWorkflowStructure(value, catalog).issues.map((issue) => issue.code),
  ).toEqual(['document_too_large'])
})

for (const version of [0, -1, true, '7', 1.5, Number.MAX_SAFE_INTEGER + 1])
  test(`exact edit version rejects ${JSON.stringify(version)}`, () => {
    for (const name of ['SaveDraftRequest', 'PublishWorkflowRequest']) {
      const value = {
        ...(examples[name] as Record<string, unknown>),
        expected_edit_version: version,
      }
      expect(schemas[name].safeParse(value).success).toBe(false)
    }
  })

test('publish commands cannot choose revision IDs or omit retry identity', () => {
  const value = { ...(examples.PublishWorkflowRequest as Record<string, unknown>) }
  delete value.request_id
  expect(workflow.publishWorkflowRequestSchema.safeParse(value).success).toBe(false)
  expect(
    workflow.publishWorkflowRequestSchema.safeParse({
      ...value,
      request_id: 'retry',
      revision_id: 'client',
    }).success,
  ).toBe(false)
})

test('validation results cannot claim success with errors or truncation', () => {
  expect(
    workflow.workflowValidationSchema.safeParse({
      scope: 'publication',
      valid: true,
      issues: [],
    }).success,
  ).toBe(false)
  expect(
    workflow.workflowValidationSchema.safeParse({
      valid: true,
      issues: [{ code: 'cycle', message: '循环' }],
    }).success,
  ).toBe(false)
  expect(
    workflow.workflowValidationSchema.safeParse({ valid: true, issues: [], truncated: true })
      .success,
  ).toBe(false)
})

test('model selection retains six roles and Skills restrictions', () => {
  const selection = workflow.workflowSelectionSchema.parse(
    workflow.workflowDefinitionSchema.parse(fixture.hash_examples.configured.definition).defaults
      .selection,
  )
  const models = { ...selection.models } as Record<string, string>
  delete models.SCOPING
  expect(workflow.workflowSelectionSchema.safeParse({ ...selection, models }).success).toBe(false)
  expect(
    workflow.workflowSelectionSchema.safeParse({
      ...selection,
      skills: { mode: 'auto', allowed: ['alpha'] },
    }).success,
  ).toBe(false)
  expect(
    workflow.workflowSelectionSchema.safeParse({
      ...selection,
      skills: { mode: 'manual', allowed: ['alpha', 'alpha'] },
    }).success,
  ).toBe(false)
})

test('nonfinite coordinates and unsupported registry versions never validate', () => {
  for (const x of [NaN, Infinity, -Infinity]) {
    const value = workflow.workflowDocumentSchema.parse(examples.WorkflowDocument)
    value.presentation.viewport.x = x
    expect(workflow.validateWorkflowStructure(value, catalog).valid).toBe(false)
  }
  expect(
    workflow.validateWorkflowStructure(examples.WorkflowDocument, {
      ...catalog,
      registry_version: 2,
    }).valid,
  ).toBe(false)
})
