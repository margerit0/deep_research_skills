import { useEffect, useMemo, useState } from 'react'
import { demoNodes, demoPosition, demoScenes, demoStart, demoWorkspace } from '../data/demo'
import {
  loadRecordings,
  type Recording,
  recordingScenes,
  recordingFrame,
  recordingWorkspace,
  recordingNodes,
} from '../data/recordings'
import type { Workspace } from '../data/schema'

interface Session {
  base: Workspace
  alternateTheme: 'light' | 'dark'
  elapsed: number
  playing: boolean
  speed: number
  override?: Workspace
  menu?: 'model' | 'skill' | null
  recordingId?: string
}

export function useDemo(base: Workspace) {
  const [session, setSession] = useState<Session | null>(null)
  const [recordings, setRecordings] = useState<Recording[]>([])
  const [recordingLoadError, setRecordingLoadError] = useState(false)
  useEffect(() => {
    if (session && !recordings.length && !recordingLoadError) {
      void loadRecordings()
        .then(setRecordings)
        .catch(() => setRecordingLoadError(true))
    }
  }, [Boolean(session), recordings.length, recordingLoadError])
  const recording = recordings.find((item) => item.id === session?.recordingId)
  const scenes = useMemo(() => (recording ? recordingScenes(recording) : demoScenes), [recording])
  const duration = scenes.reduce((sum, scene) => sum + scene.duration, 0)
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
        const elapsed = Math.min(duration, current.elapsed + delta * current.speed)
        const changed =
          demoPosition(elapsed, scenes).index !== demoPosition(current.elapsed, scenes).index
        return {
          ...current,
          elapsed,
          playing: elapsed < duration,
          override: changed ? undefined : current.override,
          menu: changed ? undefined : current.menu,
        }
      })
    }, 60)
    return () => clearInterval(timer)
  }, [playing, speed, duration, scenes])
  useEffect(() => {
    const pauseWhenHidden = () => {
      if (document.hidden)
        setSession((current) => (current ? { ...current, playing: false } : null))
    }
    document.addEventListener('visibilitychange', pauseWhenHidden)
    return () => document.removeEventListener('visibilitychange', pauseWhenHidden)
  }, [])
  const position = demoPosition(session?.elapsed ?? 0, scenes)
  const index = position.index
  const recordedRun = useMemo(
    () => (recording ? recordingFrame(recording, scenes[index].id) : undefined),
    [recording, scenes, index],
  )
  const scriptedState = useMemo(
    () =>
      session
        ? recording && recordedRun
          ? recordingWorkspace(session.base, recording, recordedRun, scenes[index].id)
          : demoWorkspace(session.base, index, session.alternateTheme)
        : null,
    [session?.base, session?.alternateTheme, recording, recordedRun, index, scenes],
  )
  const state = session?.override ?? scriptedState
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
    recording,
    recordedRun,
    recordings,
    recordingLoadError,
    scenes,
    duration,
    currentNode: scriptedState?.selectedNode ?? 'clarify',
    active: Boolean(session),
    playing,
    speed,
    reducedMotion,
    manualMenu: session?.menu !== undefined,
    elapsed: session?.elapsed ?? 0,
    done: session?.elapsed === duration,
    ...position,
    nodes:
      recording && recordedRun
        ? recordingNodes(recording, recordedRun, position.scene.id)
        : demoNodes(run, index, position.progress),
    menu: recording
      ? null
      : session?.menu !== undefined
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
        current ? { ...current, playing: !current.playing && current.elapsed < duration } : null,
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
              elapsed: demoStart(Math.max(0, Math.min(scenes.length - 1, value)), scenes),
              override: undefined,
              menu: undefined,
            }
          : null,
      ),
    interact: (next: Workspace) =>
      setSession((current) => (current ? { ...current, playing: false, override: next } : null)),
    setMenu: (menu: 'model' | 'skill' | null) =>
      setSession((current) => (current ? { ...current, playing: false, menu } : null)),
    chooseRecording: (id: string) =>
      setSession((current) =>
        current
          ? {
              ...current,
              recordingId: recordings.find((item) => item.id === id)?.id,
              elapsed: 0,
              playing: true,
              override: undefined,
              menu: undefined,
            }
          : null,
      ),
  }
}
