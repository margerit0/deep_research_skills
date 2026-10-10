import { useEffect, useRef, useState } from 'react'
import * as api from '../api/langgraph'
import type { BackendConfig, LiveResearch } from '../data/liveSchema'
import type { Thread, Workspace } from '../data/schema'
import { applySnapshot } from '../data/live'

export interface LiveUpdate {
  type: 'live'
  threadId: string
  research: LiveResearch
  submission?: boolean
  clearDraft?: string
}
type Sync = { state: 'loading' | 'ready' | 'error'; message?: string }
type Connection = { config?: BackendConfig; loading: boolean; error?: string }

export function useLiveResearch(
  workspace: Workspace,
  commit: (action: LiveUpdate, durable?: boolean) => boolean,
) {
  const current = useRef(workspace)
  current.current = workspace
  const commitRef = useRef(commit)
  commitRef.current = commit
  const [connection, setConnection] = useState<Connection>({ loading: true })
  const [sync, setSync] = useState<Record<string, Sync>>({})
  const syncing = useRef(new Set<string>())
  const sending = useRef(new Set<string>())
  const mounted = useRef(true)

  async function connect() {
    setConnection({ loading: true })
    try {
      const config = await api.getConfig()
      if (mounted.current) setConnection({ loading: false, config })
    } catch {
      if (mounted.current)
        setConnection({
          loading: false,
          error: '无法读取后端配置。请启动 LangGraph 服务并检查接口地址。',
        })
    }
  }

  function updateSync(id: string, value: Sync) {
    if (mounted.current) setSync((previous) => ({ ...previous, [id]: value }))
  }

  async function refresh(threadId: string) {
    if (!mounted.current) return
    if (syncing.current.has(threadId) || sending.current.has(threadId)) return
    const thread = current.current.threads.find((t) => t.id === threadId)
    const research = thread?.live?.researches.at(-1)
    if (!thread?.live || !research) {
      updateSync(threadId, { state: 'ready' })
      return
    }
    const turnId = research.turns.at(-1)!.id
    syncing.current.add(threadId)
    try {
      const serverRun = await api.findRun(thread.live, research)
      if (!serverRun) {
        updateSync(threadId, {
          state: 'error',
          message: '提交结果尚未确认。未找到对应运行，不会自动重复提交；可重新读取状态或新建研究。',
        })
        return
      }
      // Read the checkpoint after the run status, so a terminal run is not paired
      // with an earlier state read that raced with its final checkpoint write.
      const snapshot = await api.getState(thread.live)
      if (!mounted.current) return
      const latest = current.current.threads.find((t) => t.id === threadId)?.live?.researches.at(-1)
      if (!latest || latest.id !== research.id || latest.turns.at(-1)?.id !== turnId) return
      const next = applySnapshot(latest, serverRun, snapshot.values)
      commitRef.current({ type: 'live', threadId, research: next })
      updateSync(threadId, { state: 'ready' })
    } catch (error) {
      updateSync(threadId, {
        state: 'error',
        message:
          error instanceof api.ApiError && error.status === 404
            ? '服务端找不到此会话或运行。保留本地记录；不会自动重建或重发。'
            : '暂时无法回读研究状态。已保留本地内容，将继续尝试连接；不会重复提交。',
      })
    } finally {
      syncing.current.delete(threadId)
    }
  }

  async function send(thread: Thread) {
    let config = connection.config
    const live = thread.live
    const prompt = thread.draft.trim()
    const last = live?.researches.at(-1)
    if (!config || !live || !prompt || sending.current.has(thread.id) || last?.status === 'running')
      return
    if (last && sync[thread.id]?.state !== 'ready') return
    sending.current.add(thread.id)
    try {
      // A restarted backend may have new process-level configuration. Refresh
      // its public snapshot before recording this submission's actual models.
      config = await api.getConfig(live.serverUrl)
      if (!mounted.current) {
        sending.current.delete(thread.id)
        return
      }
      setConnection({ loading: false, config })
    } catch {
      sending.current.delete(thread.id)
      if (mounted.current)
        setConnection({
          loading: false,
          error: '无法确认后端实际配置，问题仍保存在草稿中。请重新连接后发送。',
        })
      return
    }
    const turn = {
      id: crypto.randomUUID(),
      text: prompt,
      submittedAt: new Date().toISOString(),
      transport: 'sending' as const,
    }
    const continuing = last?.status === 'awaiting_input'
    const research: LiveResearch = {
      id: continuing ? last.id : crypto.randomUUID(),
      prompt: continuing ? last.prompt : prompt,
      createdAt: continuing ? last.createdAt : turn.submittedAt,
      config,
      status: 'running',
      phase: 'clarify',
      turns: [...(continuing ? last.turns : []), turn],
      messages: [
        ...(continuing ? last.messages : []),
        { id: turn.id, type: 'human', content: prompt },
      ],
      brief: '',
      report: '',
      notes: [],
      sources: [],
      errors: [],
      observations: continuing ? last.observations : [],
    }
    // Durable outbox BEFORE either POST. If storage fails, there is no network write.
    if (
      !commitRef.current(
        { type: 'live', threadId: thread.id, research, submission: true, clearDraft: thread.draft },
        true,
      )
    ) {
      sending.current.delete(thread.id)
      updateSync(thread.id, {
        state: 'error',
        message: '浏览器无法保存提交记录，请恢复本地存储后再发送。',
      })
      return
    }
    updateSync(thread.id, { state: 'loading' })
    try {
      if (!last) await api.createThread(live)
      const serverRun = await api.createRun(live, research, turn)
      if (!mounted.current) return
      commitRef.current({
        type: 'live',
        threadId: thread.id,
        research: {
          ...research,
          turns: research.turns.map((t) =>
            t.id === turn.id ? { ...t, runId: serverRun.run_id, transport: 'accepted' } : t,
          ),
        },
      })
    } catch (error) {
      if (!mounted.current) return
      // 4xx (except a conflict) is a definite rejection. Timeouts, 5xx and lost
      // responses are ambiguous: preserve the ID and reconcile without reposting.
      const rejected =
        error instanceof api.ApiError && [400, 401, 403, 404, 422].includes(error.status)
      commitRef.current({
        type: 'live',
        threadId: thread.id,
        research: {
          ...research,
          status: rejected ? 'failed' : 'running',
          turns: research.turns.map((t) =>
            t.id === turn.id ? { ...t, transport: rejected ? 'rejected' : 'uncertain' } : t,
          ),
          errors: rejected
            ? [
                {
                  code: 'submission_rejected',
                  message: '后端拒绝此次提交，请检查服务配置后新建研究。',
                  node: 'clarify_with_user',
                },
              ]
            : [],
        },
      })
      updateSync(thread.id, {
        state: 'error',
        message: rejected
          ? '提交被拒绝。可保留当前记录并新建研究。'
          : '提交结果待确认，正在回读服务端；不会重复发送。',
      })
    } finally {
      sending.current.delete(thread.id)
      void refresh(thread.id)
    }
  }

  useEffect(() => {
    mounted.current = true
    void connect()
    return () => {
      mounted.current = false
    }
  }, [])
  useEffect(() => {
    void refresh(workspace.activeThreadId)
  }, [workspace.activeThreadId])
  useEffect(() => {
    const tick = () => {
      for (const thread of current.current.threads) {
        const last = thread.live?.researches.at(-1)
        if (last?.status === 'running') void refresh(thread.id)
      }
    }
    const focus = () => {
      void refresh(current.current.activeThreadId)
    }
    const interval = window.setInterval(tick, 2000)
    window.addEventListener('focus', focus)
    window.addEventListener('online', focus)
    return () => {
      clearInterval(interval)
      window.removeEventListener('focus', focus)
      window.removeEventListener('online', focus)
    }
  }, [])

  return { connection, sync, send, refresh, connect }
}
