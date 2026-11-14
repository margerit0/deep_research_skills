import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Archive,
  ArrowLeft,
  ArrowUpRight,
  Asterisk,
  FileUp,
  MessageSquare,
  Plus,
  RefreshCw,
  Workflow,
} from 'lucide-react'
import { Icon } from '../Icon'
import type { WorkspaceController } from '../../state/useWorkspace'
import { WorkflowApiError, workflowApi, workflowErrorMessage } from '../../api/workflows'
import {
  createWorkflowRequestSchema,
  workflowDocumentSchema,
  WORKFLOW_MAX_DOCUMENT_BYTES,
} from '../../data/workflowSchema'
import type {
  CreateWorkflowRequest,
  WorkflowDocument,
  WorkflowDraft,
  WorkflowNodeCatalog,
  WorkflowRevision,
  WorkflowSummary,
} from '../../data/workflowSchema'
import { workflowStorageKey } from '../../state/useWorkflowEditor'
import { WorkflowEditor } from './WorkflowEditor'
import { WorkflowDialog, workflowDate } from './WorkflowUI'
import './workflow.css'

function readRoute() {
  const parts = window.location.hash
    .slice(1)
    .split('/')
    .map((part) => {
      try {
        return decodeURIComponent(part)
      } catch {
        return ''
      }
    })
  return { id: parts[1], revisionId: parts[2] === 'revisions' ? parts[3] : undefined }
}
const openWorkflow = (id?: string, revision?: string) => {
  window.location.hash = id
    ? `workflows/${encodeURIComponent(id)}${revision ? `/revisions/${encodeURIComponent(revision)}` : ''}`
    : 'workflows'
}
type Loaded = {
  draft: WorkflowDraft
  summary: WorkflowSummary
  catalog: WorkflowNodeCatalog
  revision?: WorkflowRevision
}
type Creation = { source: CreateWorkflowRequest['source']; name: string }

export function WorkflowWorkspace({
  controller,
  onExit,
}: {
  controller: WorkspaceController
  onExit: () => void
}) {
  const api = useMemo(() => workflowApi(), [])
  const [route, setRoute] = useState(readRoute)
  const [generation, setGeneration] = useState(0)
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [items, setItems] = useState<WorkflowSummary[]>([])
  const [filter, setFilter] = useState('active')
  const [cursor, setCursor] = useState<number | null>(null)
  const [creation, setCreation] = useState<Creation | null>(null)
  const [pendingCreate, setPendingCreate] = useState<CreateWorkflowRequest | null>(null)
  const [creationError, setCreationError] = useState('')
  const [creating, setCreating] = useState(false)
  const [archiveTarget, setArchiveTarget] = useState<WorkflowSummary | null>(null)
  const [archiveError, setArchiveError] = useState('')
  const [archiving, setArchiving] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const listRequest = useRef(0)
  const navigation = useRef<((action: () => void) => void) | null>(null)
  const registerNavigation = useCallback((guard: ((action: () => void) => void) | null) => {
    navigation.current = guard
  }, [])
  const navigate = (action: () => void) =>
    navigation.current ? navigation.current(action) : action()
  const ready = controller.live.connection.config?.workflow_editor_version === 1

  useEffect(() => {
    const change = () => {
      setRoute(readRoute())
      setError('')
    }
    window.addEventListener('hashchange', change)
    return () => window.removeEventListener('hashchange', change)
  }, [])
  useEffect(() => {
    try {
      const key = workflowStorageKey(api.base, 'create')
      const raw = sessionStorage.getItem(key) ?? localStorage.getItem(key) ?? 'null'
      sessionStorage.setItem(key, raw)
      const value: unknown = JSON.parse(raw)
      if (value !== null) setPendingCreate(createWorkflowRequestSchema.parse(value))
    } catch {
      setCreationError('浏览器无法读取上次的创建请求，请保留已有流程并恢复本地存储。')
    }
  }, [api])

  const loadList = async (more = false) => {
    const request = ++listRequest.current
    setLoading(true)
    setError('')
    try {
      const page = await api.list(filter, more ? (cursor ?? 0) : 0)
      if (listRequest.current !== request) return
      setItems((previous) =>
        more
          ? [
              ...previous,
              ...page.items.filter(
                (item) => !previous.some((old) => old.workflow_id === item.workflow_id),
              ),
            ]
          : page.items,
      )
      setCursor(page.next_cursor)
    } catch (error) {
      if (listRequest.current === request) setError(workflowErrorMessage(error))
    } finally {
      if (listRequest.current === request) setLoading(false)
    }
  }
  useEffect(() => {
    if (!ready) return
    if (!route.id) {
      setLoaded(null)
      void loadList()
      return () => {
        listRequest.current++
      }
    }
    let disposed = false
    setLoaded(null)
    setLoading(true)
    setError('')
    void Promise.all([
      api.get(route.id),
      api.summary(route.id),
      api.catalog(),
      route.revisionId ? api.revision(route.id, route.revisionId) : Promise.resolve(undefined),
    ])
      .then(([draft, summary, catalog, revision]) => {
        if (!disposed) setLoaded({ draft, summary, catalog, revision })
      })
      .catch((error) => {
        if (!disposed) setError(workflowErrorMessage(error))
      })
      .finally(() => {
        if (!disposed) setLoading(false)
      })
    return () => {
      disposed = true
    }
  }, [ready, route.id, route.revisionId, filter, generation, api])

  const openCreation = (value: Creation) => {
    setCreationError('')
    setCreation(pendingCreate ? { name: pendingCreate.name, source: pendingCreate.source } : value)
  }
  const copy = (document: WorkflowDocument, revision?: WorkflowRevision) =>
    openCreation({
      name: [...`${document.name} 副本`].slice(0, 120).join(''),
      source: revision
        ? {
            kind: 'revision',
            workflow_ref: { workflow_id: revision.workflow_id, revision_id: revision.revision_id },
          }
        : { kind: 'import', document },
    })
  const create = async () => {
    if (!creation || creating) return
    setCreating(true)
    setCreationError('')
    let request = pendingCreate
    if (!request) {
      const parsed = createWorkflowRequestSchema.safeParse({
        request_id: crypto.randomUUID(),
        ...creation,
      })
      if (!parsed.success) {
        setCreationError('请填写有效名称，并使用仅包含流程文档的 JSON 文件。')
        setCreating(false)
        return
      }
      request = parsed.data
    }
    try {
      // No request is sent until its stable identity and original body survive reload.
      const key = workflowStorageKey(api.base, 'create')
      sessionStorage.setItem(key, JSON.stringify(request))
      localStorage.setItem(key, JSON.stringify(request))
    } catch {
      setCreationError('浏览器无法保存创建请求标识，请恢复本地存储后再试。')
      setCreating(false)
      return
    }
    setPendingCreate(request)
    try {
      const draft = await api.create(request)
      try {
        const key = workflowStorageKey(api.base, 'create')
        sessionStorage.setItem(key, 'null')
        if (localStorage.getItem(key) === JSON.stringify(request)) localStorage.removeItem(key)
      } catch {
        /* Retrying the same receipt remains safe. */
      }
      setPendingCreate(null)
      setCreation(null)
      openWorkflow(draft.workflow_id)
    } catch (error) {
      if (error instanceof WorkflowApiError && error.status >= 400 && error.status < 500) {
        try {
          const key = workflowStorageKey(api.base, 'create')
          sessionStorage.setItem(key, 'null')
          if (localStorage.getItem(key) === JSON.stringify(request)) localStorage.removeItem(key)
        } catch {
          /* The unchanged request remains safe to retry. */
        }
        setPendingCreate(null)
        setCreationError(workflowErrorMessage(error))
      } else setCreationError(`${workflowErrorMessage(error)} 重试将沿用原创建请求。`)
    } finally {
      setCreating(false)
    }
  }
  const archive = async () => {
    if (!archiveTarget) return
    setArchiving(true)
    setArchiveError('')
    try {
      await api.archive(archiveTarget.workflow_id, archiveTarget.edit_version)
      setArchiveTarget(null)
      setGeneration((value) => value + 1)
    } catch (error) {
      setArchiveError(workflowErrorMessage(error))
    } finally {
      setArchiving(false)
    }
  }
  const themeLabels = { system: '跟随系统', light: '浅色', dark: '深色' }
  return (
    <div className="wf-workspace">
      <nav className="wf-rail" aria-label="工作区导航">
        <span className="wf-brand">
          <Asterisk />
        </span>
        <button
          className="wf-icon"
          aria-label="返回研究工作台"
          title="返回研究工作台"
          onClick={() => navigate(onExit)}
        >
          <MessageSquare />
        </button>
        <button
          className="wf-icon is-selected"
          aria-label="流程管理"
          title="流程管理"
          onClick={() => navigate(() => openWorkflow())}
        >
          <Workflow />
        </button>
        <span className="wf-rail-spacer" />
        <button
          className="wf-icon"
          aria-label={`外观：${themeLabels[controller.state.theme]}`}
          title="切换外观"
          onClick={() =>
            controller.dispatch({
              type: 'theme',
              theme:
                controller.state.theme === 'system'
                  ? 'light'
                  : controller.state.theme === 'light'
                    ? 'dark'
                    : 'system',
            })
          }
        >
          <Icon name={controller.state.theme} />
        </button>
        <span className="wf-avatar">ML</span>
      </nav>
      <main className="wf-main">
        {!ready ? (
          <div className="wf-unavailable">
            <Workflow />
            <h1>流程管理</h1>
            <p>
              {controller.live.connection.loading
                ? '正在连接流程服务…'
                : '当前服务尚未开放正式流程编辑。'}
            </p>
            <button className="wf-button" onClick={() => void controller.live.connect()}>
              <RefreshCw />
              重新连接
            </button>
            <button className="wf-button" onClick={onExit}>
              <ArrowLeft />
              返回工作台
            </button>
          </div>
        ) : route.id ? (
          <>
            {loading && (
              <p className="wf-loading" role="status">
                正在读取流程…
              </p>
            )}
            {error && (
              <div className="wf-unavailable" role="alert">
                <p>{error}</p>
                <button className="wf-button" onClick={() => setGeneration((value) => value + 1)}>
                  重新读取
                </button>
                <button className="wf-button" onClick={() => openWorkflow()}>
                  返回流程管理
                </button>
              </div>
            )}
            {loaded && (
              <WorkflowEditor
                key={`${route.id}:${route.revisionId ?? 'draft'}:${generation}`}
                api={api}
                {...loaded}
                onBack={() => openWorkflow()}
                onReload={() => setGeneration((value) => value + 1)}
                onDraft={() => openWorkflow(route.id)}
                onRevision={(revision) => openWorkflow(route.id, revision)}
                onCopy={copy}
                registerNavigation={registerNavigation}
              />
            )}
          </>
        ) : (
          <section className="wf-management" aria-label="流程管理页面">
            <header className="wf-management-header">
              <div>
                <p className="wf-eyebrow">星图工作台 / 研究方法</p>
                <h1>流程管理</h1>
                <p className="wf-description">把研究步骤保存为流程，按版本持续改进。</p>
              </div>
              <div className="wf-actions">
                <button className="wf-button" onClick={() => fileInput.current?.click()}>
                  <FileUp />
                  导入 JSON
                </button>
                <button
                  className="wf-button is-primary"
                  onClick={() =>
                    openCreation({
                      name: '新的研究流程',
                      source: { kind: 'template', template_id: 'standard_research' },
                    })
                  }
                >
                  <Plus />
                  新建流程
                </button>
              </div>
            </header>
            <input
              ref={fileInput}
              type="file"
              accept="application/json,.json"
              aria-label="导入流程文件"
              className="wf-file-input"
              onChange={async (event) => {
                const file = event.target.files?.[0]
                event.target.value = ''
                if (!file) return
                try {
                  if (file.size > WORKFLOW_MAX_DOCUMENT_BYTES + 16384) throw new Error('Too large')
                  const document = workflowDocumentSchema.parse(JSON.parse(await file.text()))
                  if (
                    new TextEncoder().encode(JSON.stringify(document)).length >
                    WORKFLOW_MAX_DOCUMENT_BYTES
                  )
                    throw new Error('Too large')
                  openCreation({ name: document.name, source: { kind: 'import', document } })
                } catch {
                  setError(
                    '无法导入：请使用 v1 流程文档 JSON，大小不超过 256 KiB；不要包含发布身份、运行记录或秘密配置。',
                  )
                }
              }}
            />
            {pendingCreate && (
              <p className="wf-banner">
                有一个创建请求等待确认。
                <button
                  className="wf-button"
                  onClick={() =>
                    openCreation({ name: pendingCreate.name, source: pendingCreate.source })
                  }
                >
                  继续确认创建
                </button>
              </p>
            )}
            <div className="wf-management-tools">
              <label>
                显示
                <select
                  aria-label="流程筛选"
                  value={filter}
                  onChange={(event) => setFilter(event.target.value)}
                >
                  <option value="active">使用中的流程</option>
                  <option value="archived">已归档流程</option>
                  <option value="all">全部流程</option>
                </select>
              </label>
              <button className="wf-button" disabled={loading} onClick={() => void loadList()}>
                <RefreshCw />
                刷新
              </button>
            </div>
            {error && (
              <p className="wf-banner" role="alert">
                {error}
              </p>
            )}
            {loading && (
              <p className="wf-loading" role="status">
                正在读取流程…
              </p>
            )}
            {!loading && !items.length && !error && (
              <div className="wf-empty">
                <span className="wf-empty-glyph">
                  <Workflow />
                </span>
                <h2>{filter === 'archived' ? '还没有归档流程' : '从一份研究方法开始'}</h2>
                <p>
                  {filter === 'archived'
                    ? '归档后仍可查看草稿与发布版本。'
                    : '标准模板包含澄清、简报、研究协调和最终报告。'}
                </p>
                {filter !== 'archived' && (
                  <button
                    className="wf-button"
                    onClick={() =>
                      openCreation({
                        name: '标准深度研究',
                        source: { kind: 'template', template_id: 'standard_research' },
                      })
                    }
                  >
                    使用标准模板
                  </button>
                )}
              </div>
            )}
            <div className="wf-workflow-list">
              {items.map((item) => (
                <article className="wf-workflow-card" key={item.workflow_id}>
                  <div className="wf-card-heading">
                    <span className="wf-card-glyph">
                      <Workflow />
                    </span>
                    <span className="wf-tag">
                      {item.archived
                        ? '已归档'
                        : item.latest_revision
                          ? `v${item.latest_revision.revision_number} 已发布`
                          : '尚未发布'}
                    </span>
                  </div>
                  <h2>{item.name}</h2>
                  <p className="wf-hint">最近更新 {workflowDate(item.updated_at)}</p>
                  <div className="wf-card-actions">
                    <button className="wf-button" onClick={() => openWorkflow(item.workflow_id)}>
                      {item.archived ? '查看草稿' : '继续编辑'}
                      <ArrowUpRight />
                    </button>
                    {item.latest_revision && (
                      <button
                        className="wf-button"
                        onClick={() =>
                          openWorkflow(item.workflow_id, item.latest_revision!.revision_id)
                        }
                      >
                        查看 v{item.latest_revision.revision_number}
                      </button>
                    )}
                    {!item.archived && (
                      <button
                        className="wf-icon"
                        aria-label={`归档 ${item.name}`}
                        title="归档流程"
                        onClick={() => {
                          setArchiveTarget(item)
                          setArchiveError('')
                        }}
                      >
                        <Archive />
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>
            {cursor !== null && (
              <button
                className="wf-button wf-load-more"
                disabled={loading}
                onClick={() => void loadList(true)}
              >
                加载更多流程
              </button>
            )}
          </section>
        )}
      </main>
      {creation && (
        <WorkflowDialog
          title={
            pendingCreate
              ? '确认创建结果'
              : creation.source.kind === 'revision'
                ? '复制发布版本'
                : creation.source.kind === 'import'
                  ? '导入为新流程'
                  : '新建研究流程'
          }
          busy={creating}
          onClose={() => setCreation(null)}
        >
          <p>
            {creation.source.kind === 'template'
              ? '从标准模板创建可编辑草稿，后续可添加研究计划优化和材料整理节点。'
              : '将创建独立的流程身份，保留来源中的内容与布局。'}
          </p>
          <label className="wf-field">
            流程名称
            <input
              autoFocus
              aria-label="新流程名称"
              value={creation.name}
              readOnly={!!pendingCreate || creating}
              onChange={(event) =>
                setCreation({ ...creation, name: [...event.target.value].slice(0, 120).join('') })
              }
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.nativeEvent.isComposing) void create()
              }}
            />
          </label>
          {creation.source.kind === 'import' && (
            <p className="wf-hint">
              {creation.source.document.definition.nodes.length} 个节点 ·{' '}
              {creation.source.document.definition.edges.length} 条连线
            </p>
          )}
          {pendingCreate && <p className="wf-hint">沿用已保存的请求标识和内容，避免重复创建。</p>}
          {creationError && (
            <p className="wf-banner" role="alert">
              {creationError}
            </p>
          )}
          <div className="wf-dialog-actions">
            <button className="wf-button" disabled={creating} onClick={() => setCreation(null)}>
              返回
            </button>
            <button
              className="wf-button is-primary"
              disabled={creating || !creation.name.trim()}
              onClick={() => void create()}
            >
              {creating ? '正在创建…' : pendingCreate ? '重试创建' : '创建草稿'}
            </button>
          </div>
        </WorkflowDialog>
      )}
      {archiveTarget && (
        <WorkflowDialog title="归档流程" busy={archiving} onClose={() => setArchiveTarget(null)}>
          <p>
            归档“{archiveTarget.name}
            ”后，将保留草稿、发布版本和已有研究引用。此流程不再接受编辑或新研究选择。
          </p>
          {archiveError && (
            <p className="wf-banner" role="alert">
              {archiveError}
            </p>
          )}
          <div className="wf-dialog-actions">
            <button
              className="wf-button"
              disabled={archiving}
              onClick={() => setArchiveTarget(null)}
            >
              取消
            </button>
            <button
              className="wf-button is-primary"
              disabled={archiving}
              onClick={() => void archive()}
            >
              {archiving ? '正在归档…' : '确认归档'}
            </button>
          </div>
        </WorkflowDialog>
      )}
    </div>
  )
}
