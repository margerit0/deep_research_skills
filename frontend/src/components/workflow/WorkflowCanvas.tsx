import { useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import type { Ref } from 'react'
import {
  Background,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
  useUpdateNodeInternals,
} from '@xyflow/react'
import type { Connection, Edge, Node, NodeChange, NodeProps } from '@xyflow/react'
import { LockKeyhole, SlidersHorizontal } from 'lucide-react'
import '@xyflow/react/dist/style.css'
import type { WorkflowDocument, WorkflowNodeCatalog } from '../../data/workflowSchema'
import { connectionProblem, workflowNodeLabel, workflowPositions } from '../../data/workflowEditing'
import { WorkflowGlyph } from './WorkflowUI'

type CanvasNode = Node<
  {
    label: string
    type: string
    caption: string
    locked: boolean
    system: boolean
    input: Position | null
    output: Position | null
    issue: boolean
    waiting?: boolean
  },
  'workflow'
>

function NodeCard({ id, data, selected }: NodeProps<CanvasNode>) {
  const updateNodeInternals = useUpdateNodeInternals()
  const ports = useRef({ input: data.input, output: data.output })
  useEffect(() => {
    // Layout can move a port to another side without changing node dimensions.
    // Let the initial ResizeObserver batch measure every node before fitView;
    // forcing an update on mount can fit only the first measured node.
    if (ports.current.input !== data.input || ports.current.output !== data.output) {
      ports.current = { input: data.input, output: data.output }
      updateNodeInternals(id)
    }
  }, [id, data.input, data.output, updateNodeInternals])
  return (
    <div
      className={`wf-node${selected ? ' is-selected' : ''}${data.system ? ' is-system' : ''}${data.issue ? ' has-issue' : ''}${data.waiting ? ' is-waiting' : ''}`}
    >
      {data.input && (
        <Handle type="target" id="in" position={data.input} aria-label={`${data.label}输入`} />
      )}
      <div className="wf-node-title">
        <span className="wf-node-glyph">
          <WorkflowGlyph type={data.type} />
        </span>
        <strong>{data.label}</strong>
      </div>
      {!data.system && (
        <div className="wf-node-caption">
          <span>{data.caption}</span>
          {data.locked ? (
            <LockKeyhole aria-label="必需节点" />
          ) : (
            <SlidersHorizontal aria-hidden="true" />
          )}
        </div>
      )}
      {data.output && (
        <Handle type="source" id="out" position={data.output} aria-label={`${data.label}输出`} />
      )}
    </div>
  )
}

const nodeTypes = { workflow: NodeCard }
const captions: Record<string, string> = {
  clarify_with_user: '可选 · 必要时询问',
  write_research_brief: '定义目标与范围',
  optimize_plan: '细化维度与验证路径',
  supervisor_subgraph: '动态委派研究任务',
  organize_notes: '去重归类 · 保留来源',
  final_report_generation: '写作、核验与引用',
}

type Point = { x: number; y: number }
export type WorkflowCanvasHandle = {
  fit: () => void
  zoom: (amount: number) => void
  focus: (id: string) => void
}
type Props = {
  ref?: Ref<WorkflowCanvasHandle>
  document: WorkflowDocument
  catalog: WorkflowNodeCatalog
  readOnly: boolean
  selectedNode: string | null
  selectedEdge: string | null
  issueNodes: Set<string>
  onSelect: (node: string | null, edge?: string | null) => void
  onConnect: (source: string, target: string) => void
  onPositions: (positions: Map<string, Point>, keyboard?: boolean) => void
  onViewport: (viewport: { x: number; y: number; zoom: number }) => void
  onInsert: (type: string, position: Point) => void
  onNotice: (message: string) => void
}

const side = (here: Point, other: Point, outgoing: boolean) => {
  if (Math.abs(here.y - other.y) < 80) return other.x > here.x ? Position.Right : Position.Left
  if (Math.abs(here.x - other.x) < 80) return other.y > here.y ? Position.Bottom : Position.Top
  return outgoing ? Position.Bottom : Position.Top
}

function Canvas(props: Props) {
  const { document, catalog, readOnly, selectedNode, selectedEdge, issueNodes } = props
  const flow = useReactFlow<CanvasNode>()
  const dragging = useRef(false)
  const positions = useMemo(() => workflowPositions(document, catalog), [document, catalog])
  const definition = document.definition
  const generated = useMemo<CanvasNode[]>(() => {
    const result: CanvasNode[] = definition.nodes.map((node) => {
      const type = catalog.node_types.find((type) => type.type === node.type)
      const position = positions.get(node.id) ?? { x: 40, y: 40 }
      const before = definition.edges.find((edge) => edge.target === node.id)?.source
      const after = definition.edges.find((edge) => edge.source === node.id)?.target
      return {
        id: node.id,
        type: 'workflow',
        position,
        initialWidth: 208,
        initialHeight: type?.kind === 'system' ? 46 : 88,
        selected: node.id === selectedNode,
        ariaLabel: `${workflowNodeLabel(document, catalog, node.id)}${type?.min_instances ? '，必需节点' : ''}`,
        data: {
          type: node.type,
          label: workflowNodeLabel(document, catalog, node.id),
          caption: captions[node.type] ?? '当前服务不支持此节点',
          locked: type?.min_instances === 1,
          system: type?.kind === 'system',
          input:
            node.type === 'start'
              ? null
              : before && positions.get(before)
                ? side(position, positions.get(before)!, false)
                : Position.Top,
          output:
            node.type === 'end'
              ? null
              : after && positions.get(after)
                ? side(position, positions.get(after)!, true)
                : Position.Bottom,
          issue: issueNodes.has(node.id),
        },
      }
    })
    const clarify = positions.get('clarify_with_user')
    if (definition.nodes.some((node) => node.id === 'clarify_with_user') && clarify)
      result.push({
        id: '__waiting',
        type: 'workflow',
        position: { x: clarify.x + 286, y: clarify.y },
        draggable: false,
        selectable: false,
        focusable: false,
        connectable: false,
        data: {
          type: 'clarify_with_user',
          label: '等待用户回答',
          caption: '',
          locked: true,
          system: true,
          input: null,
          output: null,
          issue: false,
          waiting: true,
        },
      })
    return result
  }, [document, definition, catalog, positions, selectedNode, issueNodes])
  const [nodes, setNodes] = useState(generated)
  useEffect(() => {
    if (!dragging.current)
      setNodes((current) =>
        generated.map((node) => ({
          ...node,
          measured: current.find((item) => item.id === node.id)?.measured,
        })),
      )
  }, [generated])
  // Node positions change on every drag frame; the edge definitions do not.
  // Stable identities let React Flow update just the incident paths.
  const edges = useMemo<Edge[]>(
    () =>
      definition.edges
        .filter((edge) => positions.has(edge.source) && positions.has(edge.target))
        .map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          sourceHandle: 'out',
          targetHandle: 'in',
          type: 'smoothstep',
          selected: selectedEdge === edge.id,
          markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15 },
          ariaLabel: `${workflowNodeLabel(document, catalog, edge.source)} → ${workflowNodeLabel(document, catalog, edge.target)}`,
          interactionWidth: 24,
        })),
    [definition.edges, positions, document, catalog, selectedEdge],
  )

  const persistViewport = () => props.onViewport(flow.getViewport())
  useImperativeHandle(props.ref, () => ({
    fit: () => {
      void flow.fitView({ padding: 0.14, maxZoom: 1, duration: 0 }).then(() => {
        if (!readOnly) persistViewport()
      })
    },
    zoom: (amount) => {
      void flow
        .zoomTo(Math.max(0.2, Math.min(2, flow.getZoom() + amount)), { duration: 0 })
        .then(() => {
          if (!readOnly) persistViewport()
        })
    },
    focus: (id) => {
      const position = positions.get(id)
      if (position)
        void flow.setCenter(position.x + 104, position.y + 40, {
          zoom: Math.max(flow.getZoom(), 0.8),
          duration: 0,
        })
    },
  }))

  const onNodesChange = (changes: NodeChange<CanvasNode>[]) => {
    setNodes((current) => applyNodeChanges(changes, current))
    const selection = changes.find((change) => change.type === 'select' && change.selected)
    if (
      selection?.type === 'select' &&
      selection.id !== '__waiting' &&
      selection.id !== selectedNode
    )
      props.onSelect(selection.id)
    if (!dragging.current && !readOnly) {
      const moved = changes.filter(
        (change) => change.type === 'position' && change.position && !change.dragging,
      )
      if (moved.length)
        props.onPositions(
          new Map(
            moved.flatMap((change) =>
              change.type === 'position' && change.position
                ? [[change.id, change.position] as const]
                : [],
            ),
          ),
          true,
        )
    }
  }
  const connect = (connection: Connection) => {
    if (readOnly) return
    const problem = connectionProblem(document, catalog, connection.source, connection.target)
    if (problem) props.onNotice(problem)
    else props.onConnect(connection.source, connection.target)
  }
  return (
    <div
      className="wf-canvas"
      data-testid="workflow-canvas"
      onDragOver={(event) => {
        if (!readOnly) {
          event.preventDefault()
          event.dataTransfer.dropEffect = 'copy'
        }
      }}
      onDrop={(event) => {
        if (readOnly) return
        event.preventDefault()
        const type = event.dataTransfer.getData('application/atlas-workflow-node')
        if (catalog.node_types.some((node) => node.type === type))
          props.onInsert(type, flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }))
      }}
    >
      <ReactFlow<CanvasNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStart={() => {
          dragging.current = true
        }}
        onNodeDragStop={(_event, _node, moved) => {
          dragging.current = false
          props.onPositions(
            new Map(
              moved
                .filter((node) => node.id !== '__waiting')
                .map((node) => [node.id, node.position]),
            ),
          )
        }}
        onNodeClick={(_event, node) => {
          if (node.id !== '__waiting') props.onSelect(node.id)
        }}
        onEdgeClick={(_event, edge) => props.onSelect(null, edge.id)}
        onEdgesChange={(changes) => {
          const selection = changes.find((change) => change.type === 'select' && change.selected)
          if (selection?.type === 'select' && selection.id !== selectedEdge)
            props.onSelect(null, selection.id)
        }}
        onPaneClick={() => props.onSelect(null)}
        onConnect={connect}
        isValidConnection={(connection) =>
          !readOnly && !connectionProblem(document, catalog, connection.source, connection.target)
        }
        onConnectEnd={(_event, connection) => {
          if (!connection.isValid && connection.fromNode && connection.toNode) {
            const source =
              connection.fromHandle?.type === 'source'
                ? connection.fromNode.id
                : connection.toNode.id
            const target =
              connection.fromHandle?.type === 'source'
                ? connection.toNode.id
                : connection.fromNode.id
            props.onNotice(
              connectionProblem(document, catalog, source, target) ?? '请选择输入和输出端口。',
            )
          }
        }}
        onMoveEnd={(event, viewport) => {
          if (event && !readOnly) props.onViewport(viewport)
        }}
        defaultViewport={document.presentation.viewport}
        fitView={!document.presentation.nodes.length}
        fitViewOptions={{ padding: 0.14, maxZoom: 1 }}
        minZoom={0.2}
        maxZoom={2}
        deleteKeyCode={null}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        nodesFocusable
        edgesFocusable
        selectionKeyCode={null}
        multiSelectionKeyCode={null}
        zoomOnDoubleClick={false}
        ariaLabelConfig={{
          'node.a11yDescription.default': '按 Enter 选择节点，方向键移动节点。',
          'edge.a11yDescription.default': '按 Enter 选择连线。',
        }}
      >
        <Background gap={20} size={1} />
      </ReactFlow>
    </div>
  )
}

export function WorkflowCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  )
}
