import { useEffect, useRef, useState } from 'react'
import * as api from '../api/langgraph'
import * as submissions from '../api/submissions'
import type { BackendConfig, LiveResearch, ResearchEvent } from '../data/liveSchema'
import type { Thread, Workspace } from '../data/schema'
import { applySnapshot } from '../data/live'
import { applyReceipt } from '../data/executionRecovery'
import { streamResearchEvents } from '../api/researchStream'
import { readEventPage } from '../api/eventReplay'
import { retryDelay, savedRecovery } from '../data/eventRecovery'
import { getResearcherNodes, mergeResearchEvents } from '../data/researchEvents'

export type LiveUpdate =
  | {
      type: 'live'
      threadId: string
      research: LiveResearch
      submission?: boolean
      clearDraft?: string
    }
  | {
      type: 'live-events'
      threadId: string
      researchId: string
      turnId: string
      runId: string
      events: ResearchEvent[]
      cursor?: string
      replay?: {
        journalId?: string
        sequence: number
        gap: boolean
        sealed: boolean
        reset?: boolean
        unconfirmedBefore: number
      }
    }
type Sync = { state: 'loading' | 'ready' | 'error'; message?: string; retrySubmission?: boolean }
type Connection = { config?: BackendConfig; loading: boolean; error?: string }
type EventConnection = 'connecting' | 'live' | 'retrying' | 'ended'
type EventStream = {
  runId: string
  cursor: string
  retryAt: number
  failures: number
  controller?: AbortController
}
type ReplayState = { runId: string; state: 'ready' | 'retrying' | 'incomplete' }
type Retry = { failures: number; at: number }

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
  const streams = useRef(new Map<string, EventStream>())
  const [eventConnections, setEventConnections] = useState<Record<string, EventConnection>>({})
  const [replayStates, setReplayStates] = useState<Record<string, ReplayState>>({})
  const replays = useRef(new Map<string, AbortController>())
  const replayRetries = useRef(new Map<string, Retry>())
  const syncRetries = useRef(new Map<string, Retry>())

  function updateReplayState(id: string, value: ReplayState) {
    if (mounted.current)
      setReplayStates((previous) =>
        previous[id]?.runId === value.runId && previous[id]?.state === value.state
          ? previous
          : { ...previous, [id]: value },
      )
  }

  async function recoverEvents(thread: Thread, research: LiveResearch, force: boolean) {
    const live = thread.live!
    const turn = research.turns.at(-1)!
    if (
      !mounted.current ||
      !turn.runId ||
      research.config.research_event_replay_version !== 1 ||
      (!research.events.length && !['research', 'writing', 'complete'].includes(research.phase))
    )
      return
    if (replays.current.has(thread.id)) return
    const retry = replayRetries.current.get(turn.runId)
    if (!force && retry && retry.at > Date.now()) return
    const controller = new AbortController()
    replays.current.set(thread.id, controller)
    const saved = savedRecovery(live, research)
    let after = saved?.sequence ?? 0
    let journalId = saved?.journalId
    try {
      // Bound work per tick; later pages continue from the durably saved position.
      for (let index = 0; index < 4; index++) {
        const page = await readEventPage(live, research, after, journalId, controller.signal)
        if (!mounted.current || controller.signal.aborted) return
        const latest = current.current.threads
          .find((t) => t.id === thread.id)
          ?.live?.researches.at(-1)
        if (latest?.id !== research.id || latest.turns.at(-1)?.runId !== turn.runId) return
        const terminal = research.status !== 'running' || latest.status !== 'running'
        if (page.status === 'missing' && !terminal && !saved?.journalId) {
          // The research checkpoint can arrive just before the recorder starts.
          // Allow the first miss, but never hide a persistently missing journal.
          const failures = (retry?.failures ?? 0) + 1
          replayRetries.current.set(turn.runId, { failures, at: Date.now() + retryDelay(failures) })
          if (failures > 1) updateReplayState(thread.id, { runId: turn.runId, state: 'retrying' })
          return
        }
        const unfinished =
          terminal &&
          !page.has_more &&
          getResearcherNodes({
            ...research,
            events: mergeResearchEvents(latest, page.events),
          }).some((node) => node.status === 'partial')
        const gap = page.gap || page.reset || (terminal && !page.sealed) || unfinished
        const action: LiveUpdate = {
          type: 'live-events',
          threadId: thread.id,
          researchId: research.id,
          turnId: turn.id,
          runId: turn.eventRunId ?? turn.runId,
          events: page.events,
          replay: {
            journalId: page.journal_id ?? journalId,
            sequence: page.status === 'ready' ? page.next_sequence : after,
            gap,
            sealed: page.sealed,
            reset: page.reset,
            unconfirmedBefore: page.unconfirmed_before_sequence,
          },
        }
        if (!commitRef.current(action, true)) {
          // Keep usable progress in memory without advancing a durable cursor.
          commitRef.current({
            ...action,
            replay: { ...action.replay!, sequence: after, journalId, reset: false },
          })
          throw new Error('Event recovery could not be saved')
        }
        after = page.next_sequence
        journalId = page.journal_id ?? undefined
        updateReplayState(thread.id, { runId: turn.runId, state: gap ? 'incomplete' : 'ready' })
        if (!page.has_more) {
          replayRetries.current.delete(turn.runId)
          return
        }
      }
      replayRetries.current.set(turn.runId, { failures: 0, at: Date.now() + 2000 })
    } catch {
      if (controller.signal.aborted || !mounted.current) return
      const failures = (retry?.failures ?? 0) + 1
      replayRetries.current.set(turn.runId, { failures, at: Date.now() + retryDelay(failures) })
      updateReplayState(thread.id, { runId: turn.runId, state: 'retrying' })
    } finally {
      if (replays.current.get(thread.id) === controller) replays.current.delete(thread.id)
    }
  }

  function updateEventConnection(id: string, value: EventConnection) {
    if (mounted.current)
      setEventConnections((previous) =>
        previous[id] === value ? previous : { ...previous, [id]: value },
      )
  }

  function syncStreams() {
    if (!mounted.current) return
    const candidates = current.current.threads.filter((thread) => {
      const research = thread.live?.researches.at(-1)
      return (
        research?.status === 'running' &&
        research.config.research_events_version === 1 &&
        research.turns.at(-1)?.runId &&
        (!research.turns.at(-1)?.eventRunId ||
          research.turns.at(-1)?.eventRunId === research.turns.at(-1)?.runId)
      )
    })
    for (const [id, stream] of streams.current) {
      const candidate = candidates.find((thread) => thread.id === id)
      if (candidate?.live?.researches.at(-1)?.turns.at(-1)?.runId !== stream.runId) {
        stream.controller?.abort()
        streams.current.delete(id)
        updateEventConnection(id, 'ended')
      }
    }
    for (const thread of candidates) {
      const research = thread.live!.researches.at(-1)!
      const turn = research.turns.at(-1)!
      const stream = streams.current.get(thread.id) ?? {
        runId: turn.runId!,
        cursor: savedRecovery(thread.live!, research)?.cursor ?? '-1',
        retryAt: 0,
        failures: 0,
      }
      streams.current.set(thread.id, stream)
      if (stream.controller || stream.retryAt > Date.now()) continue
      const controller = new AbortController()
      stream.controller = controller
      updateEventConnection(thread.id, 'connecting')
      void streamResearchEvents(thread.live!, turn.runId!, {
        signal: controller.signal,
        after: stream.cursor,
        onOpen: () => updateEventConnection(thread.id, 'live'),
        onCursor: (id) => {
          if (!mounted.current || controller.signal.aborted) return
          if (
            commitRef.current(
              {
                type: 'live-events',
                threadId: thread.id,
                researchId: research.id,
                turnId: turn.id,
                runId: turn.runId!,
                events: [],
                cursor: id,
              },
              true,
            )
          )
            stream.cursor = id
        },
        onEvent: (event) => {
          if (!mounted.current || controller.signal.aborted) return
          stream.failures = 0
          commitRef.current({
            type: 'live-events',
            threadId: thread.id,
            researchId: research.id,
            turnId: turn.id,
            runId: turn.runId!,
            events: [event],
          })
        },
      })
        .then(() => {
          if (!controller.signal.aborted) updateEventConnection(thread.id, 'ended')
        })
        .catch((error) => {
          if (error instanceof api.ApiError && [400, 404, 410, 422].includes(error.status)) {
            // A stale native buffer cursor is independent of journal sequence.
            stream.cursor = '-1'
            if (!controller.signal.aborted)
              commitRef.current(
                {
                  type: 'live-events',
                  threadId: thread.id,
                  researchId: research.id,
                  turnId: turn.id,
                  runId: turn.runId!,
                  events: [],
                  cursor: '-1',
                },
                true,
              )
          }
          if (!controller.signal.aborted) updateEventConnection(thread.id, 'retrying')
        })
        .finally(() => {
          if (streams.current.get(thread.id) !== stream || controller.signal.aborted) return
          stream.controller = undefined
          stream.failures++
          stream.retryAt = Date.now() + retryDelay(stream.failures)
          // A stream's end is not a business result. Always reread run + checkpoint.
          void refresh(thread.id, false)
        })
    }
  }

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

  async function refresh(threadId: string, force = true) {
    if (!mounted.current) return
    if (syncing.current.has(threadId) || sending.current.has(threadId)) return
    const retry = syncRetries.current.get(threadId)
    if (!force && retry && retry.at > Date.now()) return
    const thread = current.current.threads.find((t) => t.id === threadId)
    const research = thread?.live?.researches.at(-1)
    if (!thread?.live || !research) {
      updateSync(threadId, { state: 'ready' })
      return
    }
    const turnId = research.turns.at(-1)!.id
    syncing.current.add(threadId)
    try {
      if (research.turns.at(-1)!.submissionVersion === 1) {
        const receipt = await submissions.getReceipt(thread.live, research)
        const snapshot =
          receipt.run && !['blocked', 'rejected'].includes(receipt.status)
            ? await api.getState(thread.live, receipt.checkpoint_id)
            : undefined
        if (!mounted.current) return
        const latest = current.current.threads
          .find((t) => t.id === threadId)
          ?.live?.researches.at(-1)
        if (!latest || latest.id !== research.id || latest.turns.at(-1)?.id !== turnId) return
        submissions.validateReceipt(thread.live, latest, receipt)
        const next = applyReceipt(latest, receipt, snapshot?.values)
        commitRef.current({ type: 'live', threadId, research: next })
        updateSync(threadId, { state: 'ready' })
        syncRetries.current.delete(threadId)
        await recoverEvents(thread, next, force)
        return
      }
      const serverRun = await api.findRun(thread.live, research)
      if (!serverRun) {
        const failures = (retry?.failures ?? 0) + 1
        syncRetries.current.set(threadId, { failures, at: Date.now() + retryDelay(failures) })
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
      syncRetries.current.delete(threadId)
      await recoverEvents(thread, next, force)
    } catch (error) {
      const latest = current.current.threads
        .find((item) => item.id === threadId)
        ?.live?.researches.at(-1)
      if (latest?.id !== research.id || latest.turns.at(-1)?.id !== turnId) return
      const rejected = latest.turns.at(-1)?.transport === 'rejected'
      const failures = (retry?.failures ?? 0) + 1
      syncRetries.current.set(threadId, { failures, at: Date.now() + retryDelay(failures) })
      updateSync(threadId, {
        state: 'error',
        retrySubmission:
          error instanceof submissions.SubmissionError &&
          error.status === 404 &&
          error.reason === 'submission_unknown' &&
          !rejected,
        message:
          error instanceof submissions.SubmissionError &&
          error.status === 404 &&
          error.reason === 'submission_unknown'
            ? rejected
              ? '此次提交发生冲突或被拒绝。已保留输入和成果，可新建研究。'
              : '服务端尚无此提交记录。可使用原提交标识安全重试。'
            : error instanceof api.ApiError && error.status === 404
              ? '服务端找不到此会话或运行。保留本地记录；不会自动重建或重发。'
              : '暂时无法回读研究状态。已保留本地内容，将继续尝试连接；不会重复提交。',
      })
      // Progress can survive even when native dev run metadata was not flushed.
      await recoverEvents(thread, research, force)
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
    if (last?.execution && last.execution.status !== 'completed') return
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
      ...(config.submission_recovery_version === 1
        ? { submissionVersion: 1 as const, expectedTurnId: last?.turns.at(-1)?.id ?? null }
        : {}),
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
      events: [],
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
      if (turn.submissionVersion === 1) {
        const receipt = await submissions.submitResearch(live, research)
        if (mounted.current)
          commitRef.current({
            type: 'live',
            threadId: thread.id,
            research: applyReceipt(research, receipt),
          })
        return
      }
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
        error instanceof api.ApiError &&
        ([400, 401, 403, 404, 422].includes(error.status) ||
          (turn.submissionVersion === 1 && error.status === 409))
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

  async function retrySubmission(threadId: string) {
    const thread = current.current.threads.find((item) => item.id === threadId)
    const research = thread?.live?.researches.at(-1)
    if (
      !thread?.live ||
      !research ||
      research.turns.at(-1)?.submissionVersion !== 1 ||
      sending.current.has(threadId) ||
      syncing.current.has(threadId)
    )
      return
    if (research.turns.at(-1)?.transport === 'rejected') return
    if (!research.execution?.retry_allowed && !sync[threadId]?.retrySubmission) return
    sending.current.add(threadId)
    updateSync(threadId, { state: 'loading' })
    try {
      // Re-persist the original immutable envelope before every authorized retry.
      if (!commitRef.current({ type: 'live', threadId, research }, true))
        throw new Error('Storage unavailable')
      const receipt = await submissions.submitResearch(thread.live, research)
      if (mounted.current)
        commitRef.current({ type: 'live', threadId, research: applyReceipt(research, receipt) })
    } catch {
      updateSync(threadId, {
        state: 'error',
        message: '提交确认暂时未完成，原提交标识已保留。正在重新读取状态。',
      })
    } finally {
      sending.current.delete(threadId)
      void refresh(threadId)
    }
  }

  async function recoverExecution(threadId: string) {
    const thread = current.current.threads.find((item) => item.id === threadId)
    const research = thread?.live?.researches.at(-1)
    if (
      !thread?.live ||
      !research ||
      research.turns.at(-1)?.submissionVersion !== 1 ||
      sending.current.has(threadId) ||
      syncing.current.has(threadId)
    )
      return
    sending.current.add(threadId)
    updateSync(threadId, { state: 'loading' })
    try {
      // A displayed button is not proof that a checkpoint is still current.
      const receipt = await submissions.getReceipt(thread.live, research)
      let next = applyReceipt(research, receipt)
      const boundary = receipt.recovery
      const existing = next.turns.at(-1)!.recoveryRequest
      if (!existing && (!boundary.allowed || !boundary.checkpoint_id || !boundary.node)) {
        commitRef.current({ type: 'live', threadId, research: next })
        return
      }
      const recoveryRequest = existing ?? {
        id: crypto.randomUUID(),
        parentRunId: receipt.run_id,
        checkpointId: boundary.checkpoint_id!,
        node: boundary.node!,
      }
      next = {
        ...next,
        turns: next.turns.map((turn, index) =>
          index === next.turns.length - 1 ? { ...turn, recoveryRequest } : turn,
        ),
      }
      if (!commitRef.current({ type: 'live', threadId, research: next }, true)) {
        updateSync(threadId, {
          state: 'error',
          message: '浏览器无法保存恢复标识，请恢复本地存储后再继续。',
        })
        return
      }
      const accepted = await submissions.resumeResearch(thread.live, next)
      if (mounted.current)
        commitRef.current({ type: 'live', threadId, research: applyReceipt(next, accepted) })
    } catch {
      updateSync(threadId, {
        state: 'error',
        message: '恢复请求结果待确认，已保留恢复标识。正在重新读取状态。',
      })
    } finally {
      sending.current.delete(threadId)
      void refresh(threadId)
    }
  }

  useEffect(() => {
    mounted.current = true
    void connect()
    return () => {
      mounted.current = false
      for (const stream of streams.current.values()) stream.controller?.abort()
      streams.current.clear()
      for (const controller of replays.current.values()) controller.abort()
      replays.current.clear()
    }
  }, [])
  useEffect(() => {
    void refresh(workspace.activeThreadId)
  }, [workspace.activeThreadId])
  useEffect(() => {
    syncStreams()
  }, [workspace])
  useEffect(() => {
    const tick = () => {
      for (const thread of current.current.threads) {
        const last = thread.live?.researches.at(-1)
        const runId = last?.turns.at(-1)?.runId
        if (last?.status === 'running' || (runId && replayRetries.current.has(runId)))
          void refresh(thread.id, false)
      }
      syncStreams()
    }
    const focus = () => {
      for (const stream of streams.current.values()) stream.retryAt = 0
      for (const retry of syncRetries.current.values()) retry.at = 0
      for (const retry of replayRetries.current.values()) retry.at = 0
      syncStreams()
      for (const thread of current.current.threads) {
        if (
          thread.id === current.current.activeThreadId ||
          thread.live?.researches.at(-1)?.status === 'running'
        )
          void refresh(thread.id)
      }
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

  return {
    connection,
    sync,
    send,
    refresh,
    connect,
    eventConnections,
    replayStates,
    retrySubmission,
    recoverExecution,
  }
}
