// Dev-server test entry, not a production route or publishable v1 definition.
import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { WorkflowCanvas } from '../../src/components/workflow/WorkflowCanvas'
import type { WorkflowDocument, WorkflowNodeCatalog } from '../../src/data/workflowSchema'
import '../../src/apple.css'
import '../../src/components/workflow/workflow.css'

declare global {
  interface Window {
    m4Canvas: { document: WorkflowDocument; catalog: WorkflowNodeCatalog }
  }
}

const noop = () => {}
const issues = new Set<string>()
function DisplaySample() {
  const [doc, setDoc] = useState(window.m4Canvas.document)
  const [selected, select] = useState<string | null>(null)
  return (
    <WorkflowCanvas
      document={doc}
      catalog={window.m4Canvas.catalog}
      readOnly={false}
      selectedNode={selected}
      selectedEdge={null}
      issueNodes={issues}
      onSelect={select}
      onPositions={(moved) =>
        setDoc((previous) => ({
          ...previous,
          presentation: {
            ...previous.presentation,
            nodes: previous.presentation.nodes.map((node) => ({
              ...node,
              position: moved.get(node.node_id) ?? node.position,
            })),
          },
        }))
      }
      onConnect={noop}
      onViewport={noop}
      onNotice={noop}
      onInsert={noop}
    />
  )
}

createRoot(document.getElementById('atlas-conversation-workspace')!).render(<DisplaySample />)
