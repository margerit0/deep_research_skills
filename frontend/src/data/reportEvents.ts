import type { LiveResearch, LiveThread, ReportEvent, ReportStream } from './liveSchema'

export function reportScope(thread: LiveThread, research: LiveResearch): ReportStream {
  const turn = research.turns.at(-1)!
  return {
    serverUrl: thread.serverUrl,
    threadId: thread.threadId,
    researchId: research.id,
    turnId: turn.id,
    runId: turn.runId!,
    attemptId:
      research.execution && research.execution.run_id === turn.runId
        ? research.execution.attempt_id
        : turn.runId!,
    events: [],
    sequence: 0,
    gap: false,
    sealed: false,
    unconfirmedBefore: 0,
    conflicts: [],
  }
}

export function sameReportScope(a: ReportStream, b: ReportStream) {
  return (
    a.serverUrl === b.serverUrl &&
    a.threadId === b.threadId &&
    a.researchId === b.researchId &&
    a.turnId === b.turnId &&
    a.runId === b.runId &&
    a.attemptId === b.attemptId
  )
}

export function savedReportStream(thread: LiveThread, research: LiveResearch) {
  const scope = reportScope(thread, research)
  return research.reportStreams
    ?.slice()
    .reverse()
    .find((stream) => !stream.archived && sameReportScope(stream, scope))
}

export function ownsReportEvent(scope: ReportStream, event: ReportEvent) {
  return (
    event.thread_id === scope.threadId &&
    event.run_id === scope.runId &&
    event.research_id === scope.researchId &&
    event.turn_id === scope.turnId &&
    event.attempt_id === scope.attemptId
  )
}

export type ReportReplay = {
  journalId?: string
  sequence: number
  gap: boolean
  sealed: boolean
  reset?: boolean
  unconfirmedBefore: number
}

export function mergeReportEvents(
  thread: LiveThread,
  research: LiveResearch,
  incoming: ReportEvent[],
  cursor?: string,
  replay?: ReportReplay,
): ReportStream[] {
  const scope = reportScope(thread, research)
  const saved = savedReportStream(thread, research)
  const replaced = !!saved && !!replay?.reset && saved.journalId !== replay.journalId
  const stream = { ...(replaced ? scope : (saved ?? scope)) }
  const events = new Map(stream.events.map((event) => [event.sequence, event]))
  const ids = new Map(stream.events.map((event) => [event.id, event]))
  const conflicts = new Set(stream.conflicts)
  for (const event of incoming) {
    if (!ownsReportEvent(scope, event)) continue
    const previous = events.get(event.sequence) ?? ids.get(event.id)
    if (previous && JSON.stringify(previous) !== JSON.stringify(event)) {
      conflicts.add(Math.min(previous.sequence, event.sequence))
    } else if (!previous && events.size < 10000) {
      events.set(event.sequence, event)
      ids.set(event.id, event)
    }
  }
  stream.events = [...events.values()].sort((a, b) => a.sequence - b.sequence)
  stream.conflicts = [...conflicts]
  if (cursor !== undefined) stream.cursor = cursor
  if (replay) {
    stream.sequence = replay.reset ? replay.sequence : Math.max(stream.sequence, replay.sequence)
    stream.journalId = replay.journalId
    stream.gap ||= replay.gap
    stream.sealed = replay.sealed
    stream.unconfirmedBefore = Math.max(stream.unconfirmedBefore, replay.unconfirmedBefore)
  }
  const history = research.reportStreams ?? []
  if (!saved) return [...history, stream]
  if (replaced)
    return [...history.map((item) => (item === saved ? { ...item, archived: true } : item)), stream]
  return history.map((item) => (item === saved ? stream : item))
}

export type WritingDraft = {
  id: string
  runId: string
  attemptId: string
  text: string
  offset: number
  state: 'writing' | 'finished' | 'failed' | 'unconfirmed'
  sequence: number
}

export function writingDrafts(stream: ReportStream): WritingDraft[] {
  const drafts: WritingDraft[] = []
  let expected = 1
  let current: WritingDraft | undefined
  for (const event of stream.events) {
    // Never concatenate past a missing/conflicting event, even if SSE arrived later.
    if (event.sequence !== expected || stream.conflicts.includes(event.sequence)) {
      if (current) current.state = 'unconfirmed'
      break
    }
    expected++
    if (event.kind === 'started') {
      if (current?.state === 'writing') current.state = 'unconfirmed'
      current = {
        id: event.writing_attempt_id,
        runId: event.run_id,
        attemptId: event.attempt_id,
        text: '',
        offset: 0,
        state: 'writing',
        sequence: event.sequence,
      }
      drafts.push(current)
    } else {
      if (
        !current ||
        current.id !== event.writing_attempt_id ||
        event.offset !== current.offset ||
        current.state !== 'writing'
      ) {
        if (current) current.state = 'unconfirmed'
        break
      }
      current.sequence = event.sequence
      if (event.kind === 'delta') {
        current.text += event.text!
        current.offset += new TextEncoder().encode(event.text!).length
      } else current.state = event.kind === 'failed' ? 'failed' : 'finished'
    }
  }
  if (
    current?.state === 'writing' &&
    (stream.gap || stream.archived || current.sequence <= stream.unconfirmedBefore || stream.sealed)
  )
    current.state = 'unconfirmed'
  return drafts
}

export function reportHasGap(stream: ReportStream) {
  return (
    stream.gap ||
    stream.conflicts.length > 0 ||
    stream.events.some((event, index) => event.sequence !== index + 1)
  )
}
