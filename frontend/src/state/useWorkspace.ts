import { useEffect, useReducer, useState } from 'react'
import { createRun, currentNode, getNodes, initialWorkspace } from '../data/mock'
import { useDemo } from './useDemo'
import { workspaceSchema } from '../data/schema'
import type { Config, InspectorTab, Thread, Workspace } from '../data/schema'

export const STORAGE_KEY = 'atlas-workspace:v1'
type Action =
  | { type: 'config'; config: Partial<Config> }
  | { type: 'theme'; theme: Workspace['theme'] }
  | { type: 'draft'; text: string }
  | { type: 'send' }
  | { type: 'new' }
  | { type: 'switch'; id: string }
  | { type: 'graph'; open: boolean }
  | { type: 'inspect'; node: string; runId?: string }
  | { type: 'inspector'; open: boolean }
  | { type: 'tab'; tab: InspectorTab }
  | { type: 'advance' }

function restore(): Workspace {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return initialWorkspace()
    const result = workspaceSchema.safeParse(JSON.parse(raw))
    if (result.success) {
      const saved = result.data
      if (!saved.threads.some((t) => t.id === saved.activeThreadId))
        saved.activeThreadId = saved.threads[0].id
      saved.threads.forEach((t) => {
        if (!t.runs.some((r) => r.id === t.selectedRunId))
          t.selectedRunId = t.runs.at(-1)?.id ?? null
      })
      return saved
    }
  } catch {
    /* Unavailable or stale storage must never prevent the app from opening. */
  }
  return initialWorkspace()
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
      const empty = state.threads.find((t) => t.runs.length === 0 && !t.draft)
      const next: Thread = empty ?? {
        id: crypto.randomUUID(),
        title: '新研究',
        draft: '',
        runs: [],
        selectedRunId: null,
      }
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
            selectedNode: currentNode(next.runs.find((r) => r.id === next.selectedRunId)),
          }
        : state
    }
    case 'send': {
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
  }
}

export function useWorkspace() {
  const [savedState, savedDispatch] = useReducer(reducer, undefined, restore)
  const demo = useDemo(savedState)
  const state = demo.state ?? savedState
  const dispatch = (action: Action) => {
    if (!demo.active) return savedDispatch(action)
    if (action.type === 'new' || (action.type === 'switch' && action.id !== 'tour')) {
      demo.exit()
      savedDispatch(action)
    } else if (action.type === 'advance') demo.seek(demo.index + 1)
    else demo.interact(reducer(state, action))
  }
  const [storageError, setStorageError] = useState(false)
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
  const nodes = demo.active ? demo.nodes : getNodes(run)
  return { state, dispatch, thread, run, nodes, storageError, inspectNode, demo }
}
export type WorkspaceController = ReturnType<typeof useWorkspace>
