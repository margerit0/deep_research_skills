import { reportPageSchema } from '../data/liveSchema'
import type { LiveResearch, LiveThread } from '../data/liveSchema'
import { ownsReportEvent, reportScope } from '../data/reportEvents'

export type ReportReplayFailureKind =
  | 'http'
  | 'timeout'
  | 'network'
  | 'json'
  | 'schema'
  | 'ownership'
  | 'sequence'
  | 'cursor'
  | 'storage'
  | 'unknown'

export class ReportReplayError extends Error {
  readonly category: ReportReplayFailureKind
  readonly httpStatus?: number

  constructor(category: ReportReplayFailureKind, httpStatus?: number) {
    super(`Report replay: ${category}`)
    this.category = category
    this.httpStatus = httpStatus
  }
}

// Observers can persist this safe metadata. Never include URLs, response bodies,
// draft text, error messages, credentials or model reasoning in diagnostics.
export function reportReplayDiagnostic(
  thread: LiveThread,
  research: LiveResearch,
  details: {
    requestId: string
    outcome: 'ready' | 'pending' | 'incomplete' | 'failed'
    after: number
    elapsedMs: number
    category?: ReportReplayFailureKind
    httpStatus?: number
    pageStatus?: string
    nextSequence?: number
    lastSequence?: number
    journalId?: string | null
    writingAttemptId?: string
    eventCount?: number
    gap?: boolean
    sealed?: boolean
  },
) {
  const scope = reportScope(thread, research)
  window.dispatchEvent(
    new CustomEvent('atlas:report-replay', {
      detail: {
        at: new Date().toISOString(),
        threadId: scope.threadId,
        runId: scope.runId,
        researchId: scope.researchId,
        turnId: scope.turnId,
        attemptId: scope.attemptId,
        researchPhase: research.phase,
        businessStatus: research.status,
        ...details,
      },
    }),
  )
}

export async function readReportPage(
  thread: LiveThread,
  research: LiveResearch,
  after: number,
  journalId: string | undefined,
  signal: AbortSignal,
) {
  const scope = reportScope(thread, research)
  const query = new URLSearchParams({
    research_id: scope.researchId,
    turn_id: scope.turnId,
    after: String(after),
    limit: '50',
  })
  if (journalId) query.set('journal_id', journalId)
  const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(15000)])
  let response: Response
  try {
    response = await fetch(
      `${thread.serverUrl}/atlas/threads/${encodeURIComponent(scope.threadId)}/runs/${encodeURIComponent(scope.runId)}/report-events?${query}`,
      { cache: 'no-store', signal: requestSignal },
    )
  } catch (error) {
    if (signal.aborted) throw error
    throw new ReportReplayError(
      requestSignal.reason?.name === 'TimeoutError' ? 'timeout' : 'network',
    )
  }
  if (!response.ok) throw new ReportReplayError('http', response.status)
  let body: unknown
  try {
    body = await response.json()
  } catch (error) {
    throw new ReportReplayError(
      requestSignal.reason?.name === 'TimeoutError'
        ? 'timeout'
        : error instanceof SyntaxError
          ? 'json'
          : 'network',
      response.status,
    )
  }
  const parsed = reportPageSchema.safeParse(body)
  if (!parsed.success) throw new ReportReplayError('schema', response.status)
  const page = parsed.data
  if (
    page.thread_id !== scope.threadId ||
    page.run_id !== scope.runId ||
    page.research_id !== scope.researchId ||
    page.turn_id !== scope.turnId
  )
    throw new ReportReplayError('ownership', response.status)
  if (page.next_sequence > page.last_sequence)
    throw new ReportReplayError('cursor', response.status)
  let previous = page.reset ? 0 : after
  for (const event of page.events) {
    if (!ownsReportEvent(scope, event)) throw new ReportReplayError('ownership', response.status)
    if (event.sequence <= previous || event.sequence > page.next_sequence)
      throw new ReportReplayError('sequence', response.status)
    if (event.sequence !== previous + 1) page.gap = true
    previous = event.sequence
  }
  if (page.status === 'ready') {
    if (page.next_sequence > previous) page.gap = true
    if (
      (!page.reset && page.next_sequence < after) ||
      (page.has_more && page.next_sequence <= (page.reset ? 0 : after))
    )
      throw new ReportReplayError('cursor', response.status)
  }
  return page
}
