import { useEffect, useRef, useState } from 'react'
import { createRun, currentNode, getNodes, initialWorkspace } from '../data/mock'
import { useDemo } from './useDemo'
import { workspaceSchema } from '../data/schema'
import type { Config, InspectorTab, Thread, Workspace } from '../data/schema'
import { apiUrl } from '../api/langgraph'
import { currentLiveNode, getLiveNodes } from '../data/live'
import { useLiveResearch } from './useLiveResearch'
import type { LiveUpdate } from './useLiveResearch'
import { mergeResearchEvents } from '../data/researchEvents'
import { recoveryScope, savedRecovery } from '../data/eventRecovery'

export const STORAGE_KEY = 'atlas-workspace:v1'
type Action =
  | { type: 'config'; config: Partial<Config> }
  | { type: 'theme'; theme: Workspace['theme'] }
  | { type: 'draft'; text: string }
  | { type: 'send' }
  | { type: 'new'; source?: 'mock' | 'live' }
  | { type: 'switch'; id: string }
  | { type: 'graph'; open: boolean }
  | { type: 'inspect'; node: string; runId?: string }
  | { type: 'inspector'; open: boolean }
  | { type: 'tab'; tab: InspectorTab }
  | { type: 'advance' }
  | LiveUpdate

function emptyThread(source: 'mock' | 'live'): Thread {
  const id = crypto.randomUUID()
  return {
    id,
    source,
    title: '新研究',
    draft: '',
    runs: [],
    selectedRunId: null,
    ...(source === 'live' ? { live: { threadId: id, serverUrl: apiUrl, researches: [] } } : {}),
  }
}

function newWorkspace(): Workspace {
  const base = initialWorkspace()
  const thread = emptyThread('live')
  return {
    ...base,
    threads: [thread, ...base.threads],
    activeThreadId: thread.id,
    selectedNode: 'clarify',
  }
}

function restore(): Workspace {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return newWorkspace()
    const result = workspaceSchema.safeParse(JSON.parse(raw))
    if (result.success) {
      const saved = result.data
      if (!saved.threads.some((t) => t.id === saved.activeThreadId))
        saved.activeThreadId = saved.threads[0].id
      saved.threads.forEach((t) => {
        const runs = t.source === 'live' ? (t.live?.researches ?? []) : t.runs
        if (!runs.some((r) => r.id === t.selectedRunId)) t.selectedRunId = runs.at(-1)?.id ?? null
      })
      return saved
    }
  } catch {
    /* Unavailable or stale storage must never prevent the app from opening. */
  }
  return newWorkspace()
}

function reducer(state: Workspace, action: Action): Workspace {
  const thread = state.threads.find((t) => t.id === state.activeThreadId)!
  const update = (next: Thread, patch: Partial<Workspace> = {}): Workspace => ({
    ...state,
    ...patch,
    threads: state.threads.map((t) => (t.id === next.id ? next : t)),
  })
  switch (action.type) {
    case 'config':
      return { ...state, config: { ...state.config, ...action.config } }
    case 'theme':
      return { ...state, theme: action.theme }
    case 'draft':
      return update({ ...thread, draft: action.text })
    case 'graph':
      return { ...state, graphOpen: action.open }
    case 'inspector':
      return { ...state, inspectorOpen: action.open }
    case 'tab':
      return { ...state, inspectorTab: action.tab }
    case 'inspect':
      return update(
        { ...thread, selectedRunId: action.runId ?? thread.selectedRunId },
        { selectedNode: action.node, graphOpen: true, inspectorOpen: true },
      )
    case 'new': {
      const source = action.source ?? thread.source ?? 'mock'
      const empty = state.threads.find(
        (t) =>
          (t.source ?? 'mock') === source &&
          t.runs.length === 0 &&
          !t.live?.researches.length &&
          !t.draft,
      )
      const next = empty ?? emptyThread(source)
      return {
        ...state,
        activeThreadId: next.id,
        selectedNode: 'clarify',
        threads: empty ? state.threads : [next, ...state.threads],
      }
    }
    case 'switch': {
      const next = state.threads.find((t) => t.id === action.id)
      return next
        ? {
            ...state,
            activeThreadId: next.id,
            selectedNode:
              next.source === 'live'
                ? currentLiveNode(next.live?.researches.find((r) => r.id === next.selectedRunId))
                : currentNode(next.runs.find((r) => r.id === next.selectedRunId)),
          }
        : state
    }
    case 'send': {
      if (thread.source === 'live') return state
      const prompt = thread.draft.trim()
      if (!prompt) return state
      const run = createRun(prompt, state.config)
      return update(
        {
          ...thread,
          title: thread.runs.length ? thread.title : prompt.slice(0, 28),
          draft: '',
          runs: [...thread.runs, run],
          selectedRunId: run.id,
        },
        { selectedNode: 'clarify', inspectorOpen: true },
      )
    }
    case 'advance': {
      const run = thread.runs.find((r) => r.id === thread.selectedRunId)
      if (!run) return state
      const stages = ['clarify', 'research', 'writing', 'complete'] as const
      const next = { ...run, stage: stages[(stages.indexOf(run.stage) + 1) % stages.length] }
      return update(
        { ...thread, runs: thread.runs.map((r) => (r.id === run.id ? next : r)) },
        { selectedNode: currentNode(next) },
      )
    }
    case 'live-events': {
      const target = state.threads.find((t) => t.id === action.threadId)
      const existing = target?.live?.researches.at(-1)
      const turn = existing?.turns.at(-1)
      if (
        !target?.live ||
        !existing ||
        existing.id !== action.researchId ||
        turn?.id !== action.turnId ||
        turn.runId !== action.runId
      )
        return state
      const events = mergeResearchEvents(existing, action.events)
      let recovery = savedRecovery(target.live, existing)
      if (action.cursor !== undefined || action.replay) {
        recovery = { ...(recovery ?? recoveryScope(target.live, existing)) }
        if (action.cursor !== undefined) recovery.cursor = action.cursor
        if (action.replay) {
          recovery.sequence =
            !action.replay.reset && action.replay.journalId === recovery.journalId
              ? Math.max(recovery.sequence, action.replay.sequence)
              : action.replay.sequence
          recovery.journalId = action.replay.journalId
          recovery.gap ||= action.replay.gap
          recovery.sealed = action.replay.sealed
          recovery.unconfirmedBefore = Math.max(
            recovery.unconfirmedBefore,
            action.replay.unconfirmedBefore,
          )
        }
      }
      if (
        events.length === existing.events.length &&
        JSON.stringify(recovery) === JSON.stringify(existing.eventRecovery)
      )
        return state
      return update({
        ...target,
        live: {
          ...target.live,
          researches: target.live.researches.map((research) =>
            research.id === existing.id
              ? { ...research, events, eventRecovery: recovery }
              : research,
          ),
        },
      })
    }
    case 'live': {
      const target = state.threads.find((t) => t.id === action.threadId)
      if (!target?.live || target.source !== 'live') return state
      const existing = target.live.researches.find((r) => r.id === action.research.id)
      if (!action.submission && existing?.turns.at(-1)?.id !== action.research.turns.at(-1)?.id)
        return state
      return update(
        {
          ...target,
          title: !target.live.researches.length
            ? action.research.prompt.slice(0, 28)
            : target.title,
          draft: action.clearDraft === target.draft ? '' : target.draft,
          selectedRunId: action.submission ? action.research.id : target.selectedRunId,
          live: {
            ...target.live,
            researches: existing
              ? target.live.researches.map((r) =>
                  r.id === action.research.id
                    ? {
                        ...action.research,
                        events: action.submission
                          ? action.research.events
                          : mergeResearchEvents(action.research, r.events),
                        eventRecovery: action.submission ? undefined : r.eventRecovery,
                      }
                    : r,
                )
              : [...target.live.researches, action.research],
          },
        },
        action.submission && state.activeThreadId === target.id ? { selectedNode: 'clarify' } : {},
      )
    }
  }
}

export function useWorkspace() {
  const [savedState, setSavedState] = useState(restore)
  const savedRef = useRef(savedState)
  const [storageError, setStorageError] = useState(false)
  const savedDispatch = (action: Action, durable = false): boolean => {
    const next = reducer(savedRef.current, action)
    if (next === savedRef.current) return true
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      setStorageError(false)
    } catch {
      setStorageError(true)
      if (durable) return false
    }
    savedRef.current = next
    setSavedState(next)
    return true
  }
  const live = useLiveResearch(savedState, savedDispatch)
  const demo = useDemo(savedState)
  const state = demo.state ?? savedState
  const dispatch = (action: Action) => {
    if (!demo.active && action.type === 'send') {
      const active = savedRef.current.threads.find((t) => t.id === savedRef.current.activeThreadId)!
      if (active.source === 'live') {
        void live.send(active)
        return
      }
    }
    if (!demo.active) return savedDispatch(action)
    if (action.type === 'new' || (action.type === 'switch' && action.id !== 'tour')) {
      demo.exit()
      savedDispatch(action)
    } else if (action.type === 'advance') demo.seek(demo.index + 1)
    else demo.interact(reducer(state, action))
  }
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(savedState))
      setStorageError(false)
    } catch {
      setStorageError(true)
    }
  }, [savedState])
  useEffect(() => {
    document.documentElement.style.colorScheme =
      state.theme === 'system' ? 'light dark' : state.theme
  }, [state.theme])
  const thread = state.threads.find((t) => t.id === state.activeThreadId)!
  const run = thread.runs.find((r) => r.id === thread.selectedRunId)
  const isLive = !demo.active && thread.source === 'live'
  const liveRun = isLive
    ? thread.live?.researches.find((r) => r.id === thread.selectedRunId)
    : undefined
  const inspectNode = (node: string, runId?: string) => {
    dispatch({ type: 'inspect', node, runId })
    // On narrow screens the graph follows the conversation; bring the requested
    // detail into view instead of silently changing a panel below the fold.
    if (window.matchMedia('(max-width:660px)').matches) {
      requestAnimationFrame(() => {
        document.getElementById('cw-inspector')?.scrollIntoView({
          block: 'nearest',
          behavior: window.matchMedia('(prefers-reduced-motion:reduce)').matches
            ? 'instant'
            : 'smooth',
        })
      })
    }
  }
  const nodes = demo.active ? demo.nodes : isLive ? getLiveNodes(liveRun) : getNodes(run)
  return {
    state,
    dispatch,
    thread,
    run,
    nodes,
    storageError,
    inspectNode,
    demo,
    live,
    liveRun,
    isLive,
  }
}
export type WorkspaceController = ReturnType<typeof useWorkspace>
