import { StrictMode, useCallback, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from '@xyflow/react'
import type { Connection, Edge, Node, NodeProps, OnBeforeDelete } from '@xyflow/react'
import dagre from '@dagrejs/dagre'
import '@xyflow/react/dist/style.css'
import './workflow-canvas.css'

type CanvasNode = Node<{ label: string; locked: boolean }, 'workflow'>
const labels = ['澄清需求', '研究简报', '研究协调', '最终报告']
const initialNodes: CanvasNode[] = labels.map((label, index) => ({
  id: `core-${index}`,
  type: 'workflow',
  position: { x: 0, y: 0 },
  data: { label, locked: true },
  deletable: false,
}))
const initialEdges: Edge[] = initialNodes.slice(1).map((node, index) => ({
  id: `edge-${index}`,
  source: initialNodes[index].id,
  target: node.id,
}))

function layout(nodes: CanvasNode[], edges: Edge[]): CanvasNode[] {
  const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
  graph.setGraph({ rankdir: 'LR', ranksep: 72, nodesep: 32, marginx: 30, marginy: 40 })
  for (const node of nodes) graph.setNode(node.id, { width: 156, height: 78 })
  for (const edge of edges) graph.setEdge(edge.source, edge.target)
  dagre.layout(graph)
  return nodes.map((node) => {
    const { x, y } = graph.node(node.id)
    return { ...node, position: { x: x - 78, y: y - 39 } }
  })
}

function WorkflowNode({ data, selected }: NodeProps<CanvasNode>) {
  return (
    <div className={`m0-node${selected ? ' is-selected' : ''}`}>
      <Handle type="target" position={Position.Left} aria-label={`${data.label}输入`} />
      <span>{data.locked ? '研究步骤' : '处理步骤'}</span>
      <strong>{data.label}</strong>
      <Handle type="source" position={Position.Right} aria-label={`${data.label}输出`} />
    </div>
  )
}

const nodeTypes = { workflow: WorkflowNode }

function Canvas() {
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>(
    layout(initialNodes, initialEdges),
  )
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const [notice, setNotice] = useState('可以添加、移动和连接处理步骤。')
  const nextNode = useRef(1)
  const { fitView, deleteElements } = useReactFlow<CanvasNode>()
  const connect = useCallback(
    (connection: Connection) => setEdges((current) => addEdge(connection, current)),
    [setEdges],
  )
  const beforeDelete: OnBeforeDelete<CanvasNode> = async ({
    nodes: removed,
    edges: removedEdges,
  }) => ({
    nodes: removed.filter((node) => !node.data.locked),
    edges: removedEdges,
  })

  return (
    <main className="m0-page" data-theme={theme}>
      <header>
        <div>
          <p className="m0-eyebrow">星图工作台 / 技术验证</p>
          <h1>流程画布</h1>
          <p className="m0-description">M0 交互原型 · 验证画布操作，尚未连接发布与研究执行。</p>
        </div>
        <button onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>
          {theme === 'light' ? '切换深色' : '切换浅色'}
        </button>
      </header>
      <div className="m0-toolbar" aria-label="画布操作">
        <button
          onClick={() => {
            const id = `extension-${nextNode.current++}`
            setNodes((current) => [
              ...current.map((node) => ({ ...node, selected: false })),
              {
                id,
                type: 'workflow',
                position: { x: 275, y: 200 },
                selected: true,
                data: { label: '研究计划优化', locked: false },
              },
            ])
            setNotice('已添加研究计划优化，拖动端口可建立连接。')
          }}
        >
          添加处理步骤
        </button>
        <button
          disabled={!nodes.some((node) => node.selected && !node.data.locked)}
          onClick={() =>
            void deleteElements({
              nodes: nodes.filter((node) => node.selected && !node.data.locked),
            })
          }
        >
          删除所选步骤
        </button>
        <button
          onClick={() => {
            setNodes((current) => layout(current, edges))
            setNotice('已自动排列。')
          }}
        >
          自动排列
        </button>
        <button onClick={() => void fitView({ padding: 0.25, duration: 0 })}>适应画布</button>
        <output data-testid="m0-counts">
          {nodes.length} 个节点 · {edges.length} 条连线
        </output>
      </div>
      <div className="m0-canvas" data-testid="m0-canvas">
        <ReactFlow<CanvasNode>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={connect}
          onBeforeDelete={beforeDelete}
          isValidConnection={(connection) => connection.source !== connection.target}
          colorMode={theme}
          deleteKeyCode={['Backspace', 'Delete']}
          fitView
          minZoom={0.3}
          maxZoom={2}
        >
          <Background gap={20} size={1} />
          <Controls />
        </ReactFlow>
      </div>
      <footer role="status">{notice}</footer>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ReactFlowProvider>
      <Canvas />
    </ReactFlowProvider>
  </StrictMode>,
)
