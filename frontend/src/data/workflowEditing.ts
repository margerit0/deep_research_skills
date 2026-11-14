import type { WorkflowDocument, WorkflowEdge, WorkflowNodeCatalog } from './workflowSchema'
import { WORKFLOW_MAX_NODES } from './workflowSchema'

export function workflowNodeLabel(
  document: WorkflowDocument,
  catalog: WorkflowNodeCatalog,
  id: string,
) {
  const node = document.definition.nodes.find((node) => node.id === id)
  return (
    document.presentation.nodes.find((node) => node.node_id === id)?.label ??
    catalog.node_types.find((type) => type.type === node?.type)?.label ??
    id
  )
}

/** Lay out the normal chain in two columns, with compact system steps at the top. */
export function arrangeWorkflow(document: WorkflowDocument, catalog: WorkflowNodeCatalog) {
  const ordered: string[] = []
  let next: string | undefined = document.definition.nodes.find((node) => node.type === 'start')?.id
  while (
    next &&
    !ordered.includes(next) &&
    document.definition.nodes.some((node) => node.id === next)
  ) {
    ordered.push(next)
    next = document.definition.edges.find((edge) => edge.source === next)?.target
  }
  for (const node of document.definition.nodes)
    if (!ordered.includes(node.id)) ordered.push(node.id)
  let compact = 0
  let rowIndex = 0
  document.presentation.nodes = ordered.map((id) => {
    const early = ['start', 'prepare_research', 'clarify_with_user'].includes(id)
    let position: { x: number; y: number }
    if (early) {
      position = { x: 40, y: 28 + compact * 90 }
      compact++
    } else {
      const row = Math.floor(rowIndex / 2)
      const col = rowIndex % 2 === 0 ? row % 2 : 1 - (row % 2)
      position = { x: 40 + col * 286, y: 28 + compact * 90 + 36 + row * 145 }
      rowIndex++
    }
    return { node_id: id, label: workflowNodeLabel(document, catalog, id), position }
  })
}

export function workflowPositions(document: WorkflowDocument, catalog: WorkflowNodeCatalog) {
  const arranged = structuredClone(document)
  arrangeWorkflow(arranged, catalog)
  const positions = new Map(
    arranged.presentation.nodes.map((node) => [node.node_id, node.position]),
  )
  for (const node of document.presentation.nodes) positions.set(node.node_id, node.position)
  return positions
}

export function connectionProblem(
  document: WorkflowDocument,
  catalog: WorkflowNodeCatalog,
  source: string,
  target: string,
): string | null {
  if (source === target) return '节点不能连接到自身。'
  const before = document.definition.nodes.find((node) => node.id === source)
  const after = document.definition.nodes.find((node) => node.id === target)
  if (!before || !after) return '请先选择有效的起点和终点。'
  if (
    !catalog.node_types
      .find((type) => type.type === before.type)
      ?.successor_types.includes(after.type)
  )
    return '此连接不符合研究阶段顺序。'
  if (document.definition.edges.some((edge) => edge.source === source))
    return '起点已有正常出口，请先删除原连线。'
  if (document.definition.edges.some((edge) => edge.target === target))
    return '终点已有正常入口，请先删除原连线。'
  const pending = [target]
  const reached = new Set<string>()
  while (pending.length) {
    const id = pending.pop()!
    if (id === source) return '此连接会形成循环。'
    if (reached.has(id)) continue
    reached.add(id)
    pending.push(
      ...document.definition.edges.filter((edge) => edge.source === id).map((edge) => edge.target),
    )
  }
  return null
}

export const workflowEdge = (source: string, target: string): WorkflowEdge => ({
  id: `edge_${crypto.randomUUID()}`,
  source,
  target,
  source_port: 'out',
  target_port: 'in',
})

/** Prefer insertion into a compatible edge; disconnected drafts remain repairable. */
export function insertWorkflowNode(
  document: WorkflowDocument,
  catalog: WorkflowNodeCatalog,
  typeName: string,
  options: { after?: string; position?: { x: number; y: number }; copy?: string } = {},
): string | null {
  const type = catalog.node_types.find((type) => type.type === typeName)
  if (!type || document.definition.nodes.length >= WORKFLOW_MAX_NODES) return null
  const instances = document.definition.nodes.filter((node) => node.type === typeName)
  if (type.max_instances && instances.length >= type.max_instances) return null
  const id = type.fixed_id ?? `${typeName}_${crypto.randomUUID().slice(0, 8)}`
  if (document.definition.nodes.some((node) => node.id === id)) return null
  const candidates = document.definition.edges.filter((edge) => {
    const source = document.definition.nodes.find((node) => node.id === edge.source)
    const target = document.definition.nodes.find((node) => node.id === edge.target)
    return (
      catalog.node_types
        .find((item) => item.type === source?.type)
        ?.successor_types.includes(typeName) &&
      target &&
      type.successor_types.includes(target.type)
    )
  })
  const edge = candidates.find((edge) => edge.source === options.after) ?? candidates.at(-1)
  const copied = document.definition.nodes.find((node) => node.id === options.copy)
  const parameters = copied
    ? structuredClone(copied.parameters)
    : type.parameter_fields.includes('instructions')
      ? { instructions: String(type.default_parameters.instructions ?? '') }
      : {}
  document.definition.nodes.push({
    id,
    type: typeName,
    type_version: type.type_version,
    parameters,
  })
  if (edge) {
    document.definition.edges = document.definition.edges.filter((item) => item.id !== edge.id)
    document.definition.edges.push(workflowEdge(edge.source, id), workflowEdge(id, edge.target))
  }
  document.presentation.nodes.push({
    node_id: id,
    label: copied
      ? [...`${workflowNodeLabel(document, catalog, copied.id)} 副本`].slice(0, 120).join('')
      : `${type.label}${instances.length ? ` ${instances.length + 1}` : ''}`,
    position: options.position ?? { x: 326, y: 335 + instances.length * 100 },
  })
  if (!options.position) arrangeWorkflow(document, catalog)
  return id
}

export function removableWorkflowNode(
  document: WorkflowDocument,
  catalog: WorkflowNodeCatalog,
  id: string,
) {
  const node = document.definition.nodes.find((node) => node.id === id)
  return !!node && catalog.node_types.find((type) => type.type === node.type)?.min_instances !== 1
}

export function removeWorkflowNode(
  document: WorkflowDocument,
  catalog: WorkflowNodeCatalog,
  id: string,
  reconnect: boolean,
): boolean {
  if (!removableWorkflowNode(document, catalog, id)) return false
  const incoming = document.definition.edges.filter((edge) => edge.target === id)
  const outgoing = document.definition.edges.filter((edge) => edge.source === id)
  document.definition.nodes = document.definition.nodes.filter((node) => node.id !== id)
  document.definition.edges = document.definition.edges.filter(
    (edge) => edge.source !== id && edge.target !== id,
  )
  document.presentation.nodes = document.presentation.nodes.filter((node) => node.node_id !== id)
  if (
    reconnect &&
    incoming.length === 1 &&
    outgoing.length === 1 &&
    !connectionProblem(document, catalog, incoming[0].source, outgoing[0].target)
  )
    document.definition.edges.push(workflowEdge(incoming[0].source, outgoing[0].target))
  return true
}

/** Export document content only: never revision IDs, request receipts, or run data. */
export function downloadWorkflow(document: WorkflowDocument, suffix = '') {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(document, null, 2) + '\n'], { type: 'application/json' }),
  )
  const link = window.document.createElement('a')
  link.href = url
  link.download = `${document.name.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')}${suffix}.json`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
