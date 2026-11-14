import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  Cloud,
  Copy,
  Download,
  History,
  LayoutGrid,
  Link2,
  LockKeyhole,
  Maximize,
  Minus,
  Plus,
  Redo2,
  Save,
  ShieldCheck,
  Trash2,
  Undo2,
} from 'lucide-react'
import type { WorkflowApi } from '../../api/workflows'
import { workflowErrorMessage } from '../../api/workflows'
import type {
  WorkflowDocument,
  WorkflowDraft,
  WorkflowNodeCatalog,
  WorkflowRevision,
  WorkflowRevisionSummary,
  WorkflowSummary,
} from '../../data/workflowSchema'
import {
  sameWorkflowDocument,
  validateWorkflowStructure,
  WORKFLOW_MAX_NODES,
} from '../../data/workflowSchema'
import {
  arrangeWorkflow,
  connectionProblem,
  downloadWorkflow,
  insertWorkflowNode,
  removableWorkflowNode,
  removeWorkflowNode,
  workflowEdge,
  workflowNodeLabel,
  workflowPositions,
} from '../../data/workflowEditing'
import { useWorkflowEditor } from '../../state/useWorkflowEditor'
import { WorkflowCanvas } from './WorkflowCanvas'
import type { WorkflowCanvasHandle } from './WorkflowCanvas'
import { WorkflowDialog, WorkflowGlyph, workflowDate } from './WorkflowUI'

type Props = {
  api: WorkflowApi
  catalog: WorkflowNodeCatalog
  draft: WorkflowDraft
  summary: WorkflowSummary
  revision?: WorkflowRevision
  onBack: () => void
  onReload: () => void
  onRevision: (revisionId: string) => void
  onDraft: () => void
  onCopy: (document: WorkflowDocument, revision?: WorkflowRevision) => void
  onUse?: (revision: WorkflowRevision) => void
  registerNavigation: (guard: ((action: () => void) => void) | null) => void
}
const roleLabels: Record<string, string> = {
  SCOPING: '范围规划',
  SUPERVISOR: '研究协调',
  RESEARCHER: '研究员',
  SUMMARIZATION: '网页摘要',
  COMPRESSION: '材料压缩',
  FINAL_REPORT: '报告写作',
}
const noIssueNodes = new Set<string>()

export function WorkflowEditor(props: Props) {
  const { api, catalog, summary, revision } = props
  const permanentlyReadOnly = !!revision || summary.archived
  const shownDraft = useMemo(
    () =>
      revision
        ? {
            ...props.draft,
            document: revision.document,
            edit_version: revision.source_edit_version,
            base_revision_id: revision.revision_id,
            updated_at: revision.published_at,
          }
        : props.draft,
    [props.draft, revision],
  )
  const { session, state } = useWorkflowEditor(api, shownDraft, permanentlyReadOnly)
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width:760px)').matches)
  const [panel, setPanel] = useState<'canvas' | 'library' | 'inspector'>('canvas')
  const [selected, setSelected] = useState<string | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [showIssues, setShowIssues] = useState(false)
  const [dialog, setDialog] = useState<'delete' | 'publish' | 'leave' | null>(null)
  const [reconnect, setReconnect] = useState(true)
  const [publishNote, setPublishNote] = useState('')
  const [connectSource, setConnectSource] = useState('')
  const [connectTarget, setConnectTarget] = useState('')
  const [connectionsOpen, setConnectionsOpen] = useState(false)
  const [showVersions, setShowVersions] = useState(false)
  const [versions, setVersions] = useState<WorkflowRevisionSummary[]>([])
  const [versionCursor, setVersionCursor] = useState<number | null>(null)
  const [versionError, setVersionError] = useState('')
  const [versionsLoading, setVersionsLoading] = useState(false)
  const nextNavigation = useRef<(() => void) | null>(null)
  const canvas = useRef<WorkflowCanvasHandle>(null)
  const instructions = useRef<HTMLTextAreaElement>(null)
  const nodeName = useRef<HTMLInputElement>(null)
  const workflowName = useRef<HTMLInputElement>(null)
  const document = state.document
  const readOnly = permanentlyReadOnly || narrow
  const locked = readOnly || state.busy || !!state.pendingPublish
  const preflight = useMemo(() => validateWorkflowStructure(document, catalog), [document, catalog])
  const validation = state.validation ?? preflight
  const issues = validation.issues
  const issueNodes = useMemo(
    () => new Set(issues.flatMap((issue) => (issue.node_id ? [issue.node_id] : []))),
    [issues],
  )
  const node = document.definition.nodes.find((node) => node.id === selected)
  const type = catalog.node_types.find((type) => type.type === node?.type)
  const edge = document.definition.edges.find((edge) => edge.id === selectedEdge)
  const positions = useMemo(() => workflowPositions(document, catalog), [document, catalog])
  const orderedNodes = useMemo(() => {
    const arranged = structuredClone(document)
    arrangeWorkflow(arranged, catalog)
    return arranged.presentation.nodes.flatMap((item) =>
      document.definition.nodes.filter((node) => node.id === item.node_id),
    )
  }, [document, catalog])
  const label = (id: string) => workflowNodeLabel(document, catalog, id)
  const statusLabels = {
    saved: '已保存',
    dirty: '待保存',
    saving: '保存中…',
    error: '保存未完成',
    conflict: '存在冲突',
  }

  useEffect(() => {
    const media = window.matchMedia('(max-width:760px)')
    const update = () => setNarrow(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    if (selected && !document.definition.nodes.some((node) => node.id === selected))
      setSelected(null)
    if (selectedEdge && !document.definition.edges.some((edge) => edge.id === selectedEdge))
      setSelectedEdge(null)
  }, [document, selected, selectedEdge])

  const select = (nodeId: string | null, edgeId: string | null = null) => {
    setSelected(nodeId)
    setSelectedEdge(edgeId)
    if (edgeId) setConnectionsOpen(true)
    setNotice('')
    session.endGroup()
    if (narrow && nodeId) setPanel('inspector')
  }
  const insert = (typeName: string, position?: { x: number; y: number }, copy?: string) => {
    if (locked) return
    let id: string | null = null
    session.change((document) => {
      id = insertWorkflowNode(document, catalog, typeName, {
        after: selected ?? undefined,
        position,
        copy,
      })
    })
    if (id) {
      select(id)
      setNotice('已添加节点。可在右侧修改要求，连线需保持研究阶段顺序。')
      if (!position) requestAnimationFrame(() => canvas.current?.fit())
    }
  }
  const connect = (source: string, target: string) => {
    if (locked) return
    const problem = connectionProblem(document, catalog, source, target)
    if (problem) {
      setNotice(problem)
      return
    }
    session.change((document) => {
      document.definition.edges.push(workflowEdge(source, target))
    })
    setNotice('已连接节点。')
  }
  const canReconnect = useMemo(() => {
    if (!selected) return false
    const copy = structuredClone(document)
    const count = copy.definition.edges.filter(
      (edge) => edge.source !== selected && edge.target !== selected,
    ).length
    removeWorkflowNode(copy, catalog, selected, true)
    return copy.definition.edges.length === count + 1
  }, [document, selected, catalog])
  const requestDelete = () => {
    if (locked) return
    if (edge) {
      session.change((document) => {
        document.definition.edges = document.definition.edges.filter((item) => item.id !== edge.id)
      })
      setSelectedEdge(null)
      setNotice('已删除连线，可撤销或重新连接。')
      return
    }
    if (!node) return
    if (!removableWorkflowNode(document, catalog, node.id)) {
      setNotice('此节点是必需步骤，不能删除。')
      return
    }
    setReconnect(canReconnect)
    setDialog('delete')
  }
  const navigate = async (action: () => void) => {
    if (
      permanentlyReadOnly ||
      (!state.pendingPublish &&
        !state.uncertainSave &&
        sameWorkflowDocument(state.document, state.baseline.document))
    ) {
      action()
      return
    }
    if (!state.busy && (await session.flush())) {
      action()
      return
    }
    nextNavigation.current = action
    setDialog('leave')
  }
  useEffect(() => {
    props.registerNavigation((action) => {
      void navigate(action)
    })
    return () => props.registerNavigation(null)
  }, [state, permanentlyReadOnly, session, props.registerNavigation])
  const loadVersions = async (more = false) => {
    setShowVersions(true)
    setVersionsLoading(true)
    setVersionError('')
    try {
      const page = await api.revisions(summary.workflow_id, more ? (versionCursor ?? 0) : 0)
      setVersions((previous) => (more ? [...previous, ...page.items] : page.items))
      setVersionCursor(page.next_cursor)
    } catch (error) {
      setVersionError(workflowErrorMessage(error))
    } finally {
      setVersionsLoading(false)
    }
  }
  const publish = async () => {
    const result = await session.publish(publishNote)
    setDialog(null)
    if (result) props.onRevision(result.revision_id)
    else setShowIssues(true)
  }

  return (
    <section
      className="wf-editor"
      aria-label="流程编辑器"
      onKeyDown={(event) => {
        if (locked || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
          event.preventDefault()
          void session.flush()
          return
        }
        if (
          (event.target as HTMLElement).closest(
            'input,textarea,select,[contenteditable="true"],dialog',
          )
        )
          return
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
          event.preventDefault()
          if (event.shiftKey) session.redo()
          else session.undo()
        } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
          event.preventDefault()
          session.redo()
        } else if (event.key === 'Delete' || event.key === 'Backspace') {
          event.preventDefault()
          requestDelete()
        }
      }}
    >
      <header className="wf-editor-header">
        <div className="wf-editor-heading">
          <button className="wf-breadcrumb" onClick={() => void navigate(props.onBack)}>
            <ArrowLeft />
            流程管理<span> / {revision ? '发布版本' : '编辑流程'}</span>
          </button>
          <div className="wf-title-line">
            {permanentlyReadOnly ? (
              <h1>{document.name}</h1>
            ) : (
              <input
                ref={workflowName}
                className="wf-name"
                aria-label="流程名称"
                value={document.name}
                readOnly={locked}
                onChange={(event) =>
                  session.change((document) => {
                    document.name = [...event.target.value].slice(0, 120).join('')
                  }, 'workflow-name')
                }
                onBlur={session.endGroup}
              />
            )}
            <span className="wf-tag">
              {revision
                ? `v${revision.revision_number} · 只读`
                : summary.archived
                  ? '已归档'
                  : '草稿'}
            </span>
          </div>
        </div>
        <div className="wf-header-actions">
          {!permanentlyReadOnly && (
            <span className="wf-save-state" data-state={state.status} role="status">
              <Cloud />
              {statusLabels[state.status]}
            </span>
          )}
          <button
            className="wf-icon"
            aria-label="导出流程 JSON"
            title="导出流程 JSON"
            onClick={() => downloadWorkflow(document)}
          >
            <Download />
          </button>
          <button
            className="wf-icon"
            aria-label="版本历史"
            title="版本历史"
            onClick={() => void loadVersions()}
          >
            <History />
          </button>
          {!readOnly && (
            <>
              <button
                className="wf-button"
                disabled={state.busy || !!state.pendingPublish}
                onClick={() => void session.flush()}
              >
                <Save />
                <span>保存</span>
              </button>
              <button
                className="wf-button"
                disabled={state.busy || !!state.pendingPublish}
                onClick={async () => {
                  setShowIssues(true)
                  await session.validate()
                }}
              >
                <ShieldCheck />
                <span>校验</span>
              </button>
              <button
                className="wf-button is-primary"
                disabled={state.busy}
                onClick={async () => {
                  if (state.pendingPublish) {
                    await publish()
                    return
                  }
                  setShowIssues(true)
                  const result = await session.validate()
                  if (result?.valid) {
                    setPublishNote('')
                    setDialog('publish')
                  }
                }}
              >
                <ArrowUpRight />
                <span>{state.pendingPublish ? '重试发布' : '发布'}</span>
              </button>
            </>
          )}
          {revision && !narrow && (
            <button className="wf-button" onClick={() => props.onCopy(document, revision)}>
              <Copy />
              复制为新流程
            </button>
          )}
          {revision && !summary.archived && !narrow && (
            <button className="wf-button is-primary" onClick={props.onDraft}>
              编辑当前草稿
            </button>
          )}
        </div>
      </header>
      {narrow && <p className="wf-view-note">窄屏查看 · 请在桌面上编辑流程</p>}
      {revision && (
        <div className="wf-publication-note">
          <Check />
          <p>
            v{revision.revision_number} · {workflowDate(revision.published_at)} · 已固定版本内容
            {revision.note && <span> · {revision.note}</span>}
            <br />
            {props.onUse
              ? '新研究将固定使用此版本；请先填写研究问题。'
              : '当前可查看与复制流程；发起研究将在执行功能开放后可用。'}
          </p>
          {props.onUse && !summary.archived && (
            <button className="wf-button is-primary" onClick={() => props.onUse?.(revision)}>
              使用此版本发起研究
            </button>
          )}
        </div>
      )}
      {summary.archived && (
        <p className="wf-banner">
          此流程已归档，草稿和历史版本均已保留。
          <button className="wf-button" onClick={() => props.onCopy(document, revision)}>
            另存副本
          </button>
        </p>
      )}
      {!permanentlyReadOnly && state.storageError && (
        <p className="wf-banner" role="alert">
          浏览器无法保存本地恢复副本。请导出重要修改；发布需先恢复本地存储。
        </p>
      )}
      {!permanentlyReadOnly && state.status === 'conflict' && (
        <div className="wf-conflict" role="alert" aria-label="草稿冲突">
          <p>{state.message}</p>
          <div className="wf-actions">
            <button
              className="wf-button"
              disabled={state.busy}
              onClick={() => props.onCopy(document)}
            >
              另存本地副本
            </button>
            <button
              className="wf-button"
              disabled={state.busy || !!state.pendingPublish}
              onClick={async () => {
                downloadWorkflow(document, '-本地备份')
                if (await session.reload()) props.onReload()
              }}
            >
              导出本地备份并载入新版
            </button>
          </div>
        </div>
      )}
      <div className="wf-mobile-tabs" aria-label="编辑器区域">
        {(['canvas', 'library', 'inspector'] as const).map((item, index) => (
          <button key={item} aria-pressed={panel === item} onClick={() => setPanel(item)}>
            {['画布', '节点库', '属性'][index]}
          </button>
        ))}
      </div>
      <div className="wf-three-pane" data-mobile-panel={panel}>
        <aside className="wf-library" aria-label="节点库">
          <div className="wf-pane-heading">
            <h2>节点库</h2>
            <span className="wf-tag">首版</span>
          </div>
          <p className="wf-hint">{readOnly ? '查看可用步骤与连接顺序' : '点击或拖入画布'}</p>
          {(['core', 'extension', 'system'] as const).map((kind) => (
            <div className="wf-library-group" key={kind}>
              <h3>
                {kind === 'core' ? '基础流程' : kind === 'extension' ? '研究处理' : '系统节点'}
              </h3>
              {catalog.node_types
                .filter((type) => type.kind === kind)
                .map((type) => {
                  const existing = document.definition.nodes.filter(
                    (node) => node.type === type.type,
                  )
                  const full = !!type.max_instances && existing.length >= type.max_instances
                  const canAdd =
                    !locked && !full && document.definition.nodes.length < WORKFLOW_MAX_NODES
                  return (
                    <button
                      key={type.type}
                      className={`wf-library-node${kind === 'extension' ? ' is-extension' : ''}`}
                      aria-label={`${full ? '查看' : '添加'}${type.label}`}
                      title={
                        type.min_instances
                          ? '必需步骤，随流程保留'
                          : full
                            ? '已在流程中'
                            : '插入相容的研究阶段'
                      }
                      draggable={canAdd}
                      onDragStart={(event) => {
                        if (canAdd)
                          event.dataTransfer.setData('application/atlas-workflow-node', type.type)
                      }}
                      disabled={!full && !canAdd}
                      onClick={() => {
                        if (full) {
                          select(existing[0].id)
                          canvas.current?.focus(existing[0].id)
                        } else insert(type.type)
                      }}
                    >
                      <WorkflowGlyph type={type.type} />
                      <span>{type.label}</span>
                      {full ? type.min_instances ? <LockKeyhole /> : <Check /> : <Plus />}
                    </button>
                  )
                })}
            </div>
          ))}
          <p className="wf-library-foot">
            扩展节点会插入相容的阶段，并连接前后节点。
            <br />
            <br />
            最多 30 个主流程节点。研究员任务属于运行实例。
          </p>
        </aside>
        <section className="wf-canvas-panel" aria-label="主流程">
          <div className="wf-canvas-toolbar">
            <div className="wf-actions">
              <Link2 />
              <strong>主流程</strong>
              <span className="wf-tag">{document.definition.nodes.length} 节点</span>
            </div>
            <div className="wf-actions">
              <button
                className="wf-icon"
                aria-label="撤销"
                title="撤销 · Ctrl Z"
                disabled={locked || !state.past.length}
                onClick={session.undo}
              >
                <Undo2 />
              </button>
              <button
                className="wf-icon"
                aria-label="重做"
                title="重做 · Ctrl Shift Z"
                disabled={locked || !state.future.length}
                onClick={session.redo}
              >
                <Redo2 />
              </button>
              <button
                className="wf-icon"
                aria-label="自动排列"
                title="自动排列"
                disabled={locked}
                onClick={() => {
                  session.change((document) => arrangeWorkflow(document, catalog))
                  requestAnimationFrame(() => canvas.current?.fit())
                }}
              >
                <LayoutGrid />
              </button>
            </div>
          </div>
          {!narrow ? (
            <WorkflowCanvas
              ref={canvas}
              document={document}
              catalog={catalog}
              readOnly={locked}
              selectedNode={selected}
              selectedEdge={selectedEdge}
              issueNodes={showIssues ? issueNodes : noIssueNodes}
              onSelect={select}
              onConnect={connect}
              onInsert={insert}
              onNotice={setNotice}
              onPositions={(moved, keyboard) => {
                if (locked) return
                session.change(
                  (document) => {
                    for (const [id, position] of moved) {
                      if (!document.definition.nodes.some((node) => node.id === id)) continue
                      const bounded = {
                        x: Math.max(-1e6, Math.min(1e6, position.x)),
                        y: Math.max(-1e6, Math.min(1e6, position.y)),
                      }
                      const presentation = document.presentation.nodes.find(
                        (node) => node.node_id === id,
                      )
                      if (presentation) presentation.position = bounded
                      else
                        document.presentation.nodes.push({
                          node_id: id,
                          label: label(id),
                          position: bounded,
                        })
                    }
                  },
                  keyboard ? 'keyboard-position' : undefined,
                )
              }}
              onViewport={(viewport) => {
                if (!locked) session.setViewport(viewport)
              }}
            />
          ) : (
            <div className="wf-mobile-chain">
              {orderedNodes.map((node) => (
                <button
                  key={node.id}
                  className="wf-mobile-node"
                  aria-pressed={selected === node.id}
                  onClick={() => select(node.id)}
                >
                  <WorkflowGlyph type={node.type} />
                  <span>
                    {label(node.id)}
                    <small>
                      {document.definition.edges
                        .filter((edge) => edge.source === node.id)
                        .map((edge) => `→ ${label(edge.target)}`)
                        .join(' / ') || (node.type === 'end' ? '流程结束' : '尚未连接后继节点')}
                    </small>
                  </span>
                  {catalog.node_types.find((type) => type.type === node.type)?.min_instances ===
                    1 && <LockKeyhole />}
                </button>
              ))}
            </div>
          )}
          <div className="wf-canvas-footer">
            <div className="wf-actions">
              <button
                className="wf-icon"
                aria-label="缩小画布"
                onClick={() => canvas.current?.zoom(-0.1)}
                disabled={narrow}
              >
                <Minus />
              </button>
              <span className="wf-hint">画布缩放</span>
              <button
                className="wf-icon"
                aria-label="放大画布"
                onClick={() => canvas.current?.zoom(0.1)}
                disabled={narrow}
              >
                <Plus />
              </button>
              <button
                className="wf-icon"
                aria-label="适应画布"
                onClick={() => canvas.current?.fit()}
                disabled={narrow}
              >
                <Maximize />
              </button>
            </div>
            <button
              className="wf-issues-toggle"
              aria-expanded={showIssues}
              onClick={() => setShowIssues(!showIssues)}
            >
              {issues.length ? `${issues.length} 项待检查` : '结构完整'}
              <ShieldCheck />
            </button>
          </div>
          {showIssues && (
            <div className="wf-validation" aria-label="校验结果">
              <div className="wf-pane-heading">
                <h3>{validation.scope === 'publication' ? '服务端发布校验' : '本地结构检查'}</h3>
                <span className="wf-tag">{issues.length} 项问题</span>
              </div>
              {!issues.length && (
                <p>
                  {validation.scope === 'publication'
                    ? '当前保存版本已通过发布校验。'
                    : '本地结构检查通过，发布时仍需服务端完整校验。'}
                </p>
              )}
              {issues.map((issue, index) => (
                <button
                  key={`${issue.code}-${index}`}
                  className="wf-issue"
                  onClick={() => {
                    if (issue.node_id) {
                      select(issue.node_id)
                      canvas.current?.focus(issue.node_id)
                      if (narrow) setPanel('inspector')
                    } else if (issue.edge_id) select(null, issue.edge_id)
                    requestAnimationFrame(() => {
                      if (issue.field?.includes('/parameters')) instructions.current?.focus()
                      else if (issue.field === '/name') workflowName.current?.focus()
                      else if (issue.field?.includes('/presentation')) nodeName.current?.focus()
                    })
                  }}
                >
                  <span>{index + 1}</span>
                  <p>
                    {issue.node_id ? `${label(issue.node_id)}：` : ''}
                    {issue.message}
                  </p>
                </button>
              ))}
              {validation.truncated && <p>问题较多，请修复后再次校验。</p>}
            </div>
          )}
        </section>
        <aside className="wf-inspector" aria-label="节点属性">
          <div className="wf-pane-heading">
            <h2>{edge ? '连线属性' : node ? '节点属性' : '流程信息'}</h2>
            <span className="wf-tag">
              {readOnly ? '只读' : type?.min_instances ? '必需节点' : node ? '可选节点' : '草稿'}
            </span>
          </div>
          {node ? (
            <>
              <div className="wf-inspector-title">
                <span className="wf-node-glyph">
                  <WorkflowGlyph type={node.type} />
                </span>
                <h3>{label(node.id)}</h3>
              </div>
              <p className="wf-description">{captionsFor(node.type)}</p>
              <label className="wf-field">
                节点名称
                <input
                  ref={nodeName}
                  aria-label="节点名称"
                  readOnly={locked}
                  value={label(node.id)}
                  onBlur={session.endGroup}
                  onChange={(event) =>
                    session.change((document) => {
                      let presentation = document.presentation.nodes.find(
                        (item) => item.node_id === node.id,
                      )
                      if (!presentation) {
                        presentation = {
                          node_id: node.id,
                          label: label(node.id),
                          position: positions.get(node.id)!,
                        }
                        document.presentation.nodes.push(presentation)
                      }
                      presentation.label = [...event.target.value].slice(0, 120).join('')
                    }, `label-${node.id}`)
                  }
                />
              </label>
              {type?.parameter_fields.includes('instructions') && (
                <label className="wf-field">
                  处理要求 <span className="wf-required">必填</span>
                  <textarea
                    ref={instructions}
                    aria-label="处理要求"
                    rows={6}
                    readOnly={locked}
                    value={node.parameters.instructions ?? ''}
                    onBlur={session.endGroup}
                    onChange={(event) =>
                      session.change((document) => {
                        document.definition.nodes.find(
                          (item) => item.id === node.id,
                        )!.parameters.instructions = [...event.target.value].slice(0, 4000).join('')
                      }, `instructions-${node.id}`)
                    }
                  />
                  <span className="wf-hint">
                    {[...(node.parameters.instructions ?? '')].length} / 4000 字符
                  </span>
                </label>
              )}
              {!type && <p className="wf-banner">此节点类型当前不受支持，可以移除或导出后修复。</p>}
              <div className="wf-role-box">
                <p>使用的模型角色</p>
                <strong>
                  {type?.model_roles.map((role) => roleLabels[role]).join('、') || '无需模型'}
                </strong>
                <p>
                  {document.definition.defaults.selection
                    ? '使用流程默认配置，发布时核对可用性'
                    : '沿用本次研究的模型与 Skills 配置'}
                </p>
              </div>
              <dl className="wf-node-contract">
                <dt>输入</dt>
                <dd>{type?.input_label ?? '无'}</dd>
                <dt>输出</dt>
                <dd>{type?.output_label ?? '无'}</dd>
                <dt>后继</dt>
                <dd>
                  {type?.successor_types
                    .map(
                      (value) =>
                        catalog.node_types.find((type) => type.type === value)?.label ?? value,
                    )
                    .join(' / ') || '流程结束'}
                </dd>
              </dl>
              {node.type === 'clarify_with_user' && (
                <p className="wf-hint">
                  需要补充时进入系统等待路径，回答继续使用同一研究。此出口不参与主流程连线。
                </p>
              )}
              {node.type === 'supervisor_subgraph' && (
                <p className="wf-hint">
                  研究员由运行时动态创建。请在研究会话中查看任务，不能通过删除卡片取消研究。
                </p>
              )}
              <div className="wf-node-actions">
                {type?.kind === 'extension' && (
                  <button
                    className="wf-button"
                    disabled={locked || document.definition.nodes.length >= WORKFLOW_MAX_NODES}
                    onClick={() => insert(node.type, undefined, node.id)}
                  >
                    <Copy />
                    复制
                  </button>
                )}
                <button
                  className="wf-button is-danger"
                  disabled={locked || !removableWorkflowNode(document, catalog, node.id)}
                  onClick={requestDelete}
                >
                  <Trash2 />
                  删除节点
                </button>
              </div>
              {type?.min_instances === 1 && (
                <p className="wf-hint">
                  <LockKeyhole /> 必需步骤，随流程保留。
                </p>
              )}
            </>
          ) : edge ? (
            <>
              <div className="wf-inspector-title">
                <Link2 />
                <h3>正常控制连接</h3>
              </div>
              <p className="wf-description">
                {label(edge.source)} → {label(edge.target)}
              </p>
              <p className="wf-hint">删除连线后，需重新连接才能通过发布校验。</p>
              <button className="wf-button is-danger" disabled={locked} onClick={requestDelete}>
                <Trash2 />
                删除连线
              </button>
            </>
          ) : (
            <>
              <div className="wf-inspector-title">
                <ShieldCheck />
                <h3>研究流程</h3>
              </div>
              <p className="wf-description">选择节点查看参数，或连接相容的研究阶段。</p>
              <dl className="wf-node-contract">
                <dt>节点</dt>
                <dd>{document.definition.nodes.length} / 30</dd>
                <dt>连线</dt>
                <dd>{document.definition.edges.length}</dd>
                <dt>基础版本</dt>
                <dd>{state.baseline.base_revision_id ? '保留当前发布内容的草稿' : '尚未发布'}</dd>
              </dl>
              <div className="wf-role-box">
                <p>模型与 Skills</p>
                <strong>
                  {document.definition.defaults.selection
                    ? '已保存流程默认配置'
                    : '沿用发起研究时的配置'}
                </strong>
                {document.definition.defaults.selection && (
                  <button
                    className="wf-button"
                    disabled={locked}
                    onClick={() =>
                      session.change((document) => {
                        document.definition.defaults.selection = null
                      })
                    }
                  >
                    改为沿用研究配置
                  </button>
                )}
              </div>
            </>
          )}
          <details
            className="wf-connections"
            open={connectionsOpen}
            onToggle={(event) => setConnectionsOpen(event.currentTarget.open)}
          >
            <summary>
              <Link2 />
              连接节点
            </summary>
            <p className="wf-hint">也可在画布上拖动端口连线。</p>
            <label className="wf-field">
              起点
              <select
                aria-label="连接起点"
                value={connectSource}
                disabled={locked}
                onChange={(event) => setConnectSource(event.target.value)}
              >
                <option value="">选择输出节点</option>
                {document.definition.nodes
                  .filter((node) => node.type !== 'end')
                  .map((node) => (
                    <option key={node.id} value={node.id}>
                      {label(node.id)}
                    </option>
                  ))}
              </select>
            </label>
            <label className="wf-field">
              终点
              <select
                aria-label="连接终点"
                value={connectTarget}
                disabled={locked}
                onChange={(event) => setConnectTarget(event.target.value)}
              >
                <option value="">选择输入节点</option>
                {document.definition.nodes
                  .filter((node) => node.type !== 'start')
                  .map((node) => (
                    <option key={node.id} value={node.id}>
                      {label(node.id)}
                    </option>
                  ))}
              </select>
            </label>
            <button
              className="wf-button"
              disabled={locked || !connectSource || !connectTarget}
              onClick={() => connect(connectSource, connectTarget)}
            >
              建立连接
            </button>
            <div className="wf-edge-list">
              {document.definition.edges.map((edge) => (
                <button
                  key={edge.id}
                  aria-label={`选择连线 ${label(edge.source)} 到 ${label(edge.target)}`}
                  onClick={() => select(null, edge.id)}
                >
                  {label(edge.source)} → {label(edge.target)}
                </button>
              ))}
            </div>
          </details>
        </aside>
      </div>
      <p className="wf-editor-notice" role="status" aria-live="polite">
        {notice ||
          (state.status !== 'conflict' ? state.message : '') ||
          (readOnly ? '此视图只读，可选择节点查看参数。' : '拖动节点 · 连接端口 · 修改后自动保存')}
      </p>
      {dialog === 'delete' && node && (
        <WorkflowDialog title={`删除“${label(node.id)}”`} onClose={() => setDialog(null)}>
          <p>将移除此节点及关联连线，操作可以撤销。</p>
          <label className="wf-check">
            <input
              type="checkbox"
              checked={reconnect && canReconnect}
              disabled={!canReconnect}
              onChange={(event) => setReconnect(event.target.checked)}
            />
            同时连接前后节点
          </label>
          {!canReconnect && <p className="wf-hint">当前前后连接不相容，移除后请手动连接。</p>}
          <div className="wf-dialog-actions">
            <button className="wf-button" onClick={() => setDialog(null)}>
              取消
            </button>
            <button
              className="wf-button is-danger"
              onClick={() => {
                session.change((document) => {
                  removeWorkflowNode(document, catalog, node.id, reconnect && canReconnect)
                })
                setDialog(null)
                select(null)
                setNotice('节点已移除，可使用撤销恢复。')
              }}
            >
              确认删除
            </button>
          </div>
        </WorkflowDialog>
      )}
      {dialog === 'publish' && (
        <WorkflowDialog title="发布新版本" busy={state.busy} onClose={() => setDialog(null)}>
          <p>当前草稿已保存并通过服务端校验。发布后将固定完整内容和布局，后续编辑保留在草稿中。</p>
          <div className="wf-role-box">
            <strong>{document.name}</strong>
            <p>{document.definition.nodes.length} 个节点 · 当前草稿</p>
          </div>
          <label className="wf-field">
            版本说明（可选）
            <textarea
              aria-label="版本说明"
              value={publishNote}
              readOnly={state.busy}
              rows={3}
              onChange={(event) => setPublishNote([...event.target.value].slice(0, 2000).join(''))}
            />
          </label>
          <div className="wf-dialog-actions">
            <button className="wf-button" disabled={state.busy} onClick={() => setDialog(null)}>
              返回编辑
            </button>
            <button
              className="wf-button is-primary"
              disabled={state.busy}
              onClick={() => void publish()}
            >
              {state.busy ? '正在发布…' : '确认发布'}
            </button>
          </div>
        </WorkflowDialog>
      )}
      {dialog === 'leave' && (
        <WorkflowDialog title="保留当前修改" busy={state.busy} onClose={() => setDialog(null)}>
          <p>
            {state.pendingPublish
              ? '发布结果尚未确认，原请求标识已保留。返回此草稿后可继续重试。'
              : '服务器尚未确认当前修改。可以留在此页处理，或导出备份后离开。'}
          </p>
          <div className="wf-dialog-actions">
            <button className="wf-button" onClick={() => setDialog(null)}>
              留在此页
            </button>
            <button
              className="wf-button"
              onClick={() => {
                downloadWorkflow(document, '-本地备份')
                setDialog(null)
                nextNavigation.current?.()
              }}
            >
              导出备份并离开
            </button>
          </div>
        </WorkflowDialog>
      )}
      {showVersions && (
        <WorkflowDialog title="版本历史" onClose={() => setShowVersions(false)}>
          <p>发布版本只读。复制旧版本会创建一个新的流程，不覆盖当前草稿。</p>
          {versionError && (
            <p className="wf-banner" role="alert">
              {versionError}
              <button className="wf-button" onClick={() => void loadVersions()}>
                重试加载
              </button>
            </p>
          )}
          {!versions.length && !versionsLoading && !versionError && (
            <p className="wf-empty">此流程尚未发布。</p>
          )}
          <div className="wf-version-list">
            {versions.map((item) => (
              <button
                className="wf-version"
                key={item.revision_id}
                onClick={() => {
                  setShowVersions(false)
                  void navigate(() => props.onRevision(item.revision_id))
                }}
              >
                <span className="wf-tag">v{item.revision_number}</span>
                <span>
                  <strong>{item.note || '已发布版本'}</strong>
                  <small>{workflowDate(item.published_at)}</small>
                </span>
                <ArrowUpRight />
              </button>
            ))}
          </div>
          {versionsLoading && <p role="status">正在读取版本…</p>}
          {versionCursor !== null && (
            <button
              className="wf-button"
              disabled={versionsLoading}
              onClick={() => void loadVersions(true)}
            >
              加载更早版本
            </button>
          )}
        </WorkflowDialog>
      )}
    </section>
  )
}

function captionsFor(type: string) {
  return (
    (
      {
        start: '接收本轮研究问题，进入主流程。',
        prepare_research: '初始化本轮研究上下文并保留正确的研究归属。',
        clarify_with_user: '必要时询问用户，确认目标与范围；信息充分时继续生成简报。',
        write_research_brief: '将研究要求转化为清晰的目标、范围和研究简报。',
        optimize_plan: '补充研究维度与验证路径，让协调器接收更完整的简报开展研究。',
        supervisor_subgraph: '根据简报委派研究员任务，汇总有效研究笔记和来源。',
        organize_notes: '整理已有材料并保留来源定位，原始笔记与证据不被覆盖。',
        final_report_generation: '根据有效材料完成报告写作、核验与引用。',
        end: '结束本轮执行，保留已确认的研究成果。',
      } as Record<string, string>
    )[type] ?? '此类型需要当前服务提供相应支持。'
  )
}
