import { useEffect, useMemo, useState } from 'react'
import {
  demoDuration,
  demoNodes,
  demoPosition,
  demoScenes,
  demoStart,
  demoWorkspace,
} from '../data/demo'
import type { Workspace } from '../data/schema'

interface Session {
  base: Workspace
  alternateTheme: 'light' | 'dark'
  elapsed: number
  playing: boolean
  speed: number
  override?: Workspace
  menu?: 'model' | 'skill' | null
}

export function useDemo(base: Workspace) {
  const [session, setSession] = useState<Session | null>(null)
  const [reducedMotion, setReducedMotion] = useState(
    () => matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReducedMotion(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  const playing = session?.playing ?? false
  const speed = session?.speed ?? 1
  useEffect(() => {
    if (!playing) return
    let previous = performance.now()
    const timer = window.setInterval(() => {
      const now = performance.now()
      const delta = now - previous
      previous = now
      setSession((current) => {
        if (!current?.playing) return current
        const elapsed = Math.min(demoDuration, current.elapsed + delta * current.speed)
        const changed = demoPosition(elapsed).index !== demoPosition(current.elapsed).index
        return {
          ...current,
          elapsed,
          playing: elapsed < demoDuration,
          override: changed ? undefined : current.override,
          menu: changed ? undefined : current.menu,
        }
      })
    }, 60)
    return () => clearInterval(timer)
  }, [playing, speed])
  useEffect(() => {
    const pauseWhenHidden = () => {
      if (document.hidden)
        setSession((current) => (current ? { ...current, playing: false } : null))
    }
    document.addEventListener('visibilitychange', pauseWhenHidden)
    return () => document.removeEventListener('visibilitychange', pauseWhenHidden)
  }, [])
  const index = session ? demoPosition(session.elapsed).index : 0
  const scriptedState = useMemo(
    () => (session ? demoWorkspace(session.base, index, session.alternateTheme) : null),
    [session?.base, session?.alternateTheme, index],
  )
  const state = session?.override ?? scriptedState
  const position = demoPosition(session?.elapsed ?? 0)
  const run = state?.threads[0].runs[0]
  const start = () => {
    const dark =
      base.theme === 'dark' ||
      (base.theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
    setSession({
      base,
      alternateTheme: dark ? 'light' : 'dark',
      elapsed: 0,
      playing: true,
      speed: 1,
    })
  }
  return {
    state,
    currentNode: scriptedState?.selectedNode ?? 'clarify',
    active: Boolean(session),
    playing,
    speed,
    reducedMotion,
    manualMenu: session?.menu !== undefined,
    elapsed: session?.elapsed ?? 0,
    done: session?.elapsed === demoDuration,
    ...position,
    nodes: demoNodes(run, index, position.progress),
    menu:
      session?.menu !== undefined
        ? session.menu
        : index === 1
          ? ('model' as const)
          : index === 2
            ? ('skill' as const)
            : null,
    start,
    exit: () => setSession(null),
    pause: () => setSession((current) => (current ? { ...current, playing: false } : null)),
    toggle: () =>
      setSession((current) =>
        current
          ? { ...current, playing: !current.playing && current.elapsed < demoDuration }
          : null,
      ),
    replay: () =>
      setSession((current) =>
        current
          ? { ...current, elapsed: 0, playing: true, override: undefined, menu: undefined }
          : null,
      ),
    setSpeed: (value: number) =>
      setSession((current) => (current ? { ...current, speed: value } : null)),
    seek: (value: number) =>
      setSession((current) =>
        current
          ? {
              ...current,
              elapsed: demoStart(Math.max(0, Math.min(demoScenes.length - 1, value))),
              override: undefined,
              menu: undefined,
            }
          : null,
      ),
    interact: (next: Workspace) =>
      setSession((current) => (current ? { ...current, playing: false, override: next } : null)),
    setMenu: (menu: 'model' | 'skill' | null) =>
      setSession((current) => (current ? { ...current, playing: false, menu } : null)),
  }
}
