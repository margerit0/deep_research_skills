import { ApiError } from './errors'
import { reportPageSchema } from '../data/liveSchema'
import type { LiveResearch, LiveThread } from '../data/liveSchema'
import { ownsReportEvent, reportScope } from '../data/reportEvents'

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
  const response = await fetch(
    `${thread.serverUrl}/atlas/threads/${encodeURIComponent(scope.threadId)}/runs/${encodeURIComponent(scope.runId)}/report-events?${query}`,
    { cache: 'no-store', signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]) },
  )
  if (!response.ok) throw new ApiError(response.status)
  const page = reportPageSchema.parse(await response.json())
  if (
    page.thread_id !== scope.threadId ||
    page.run_id !== scope.runId ||
    page.research_id !== scope.researchId ||
    page.turn_id !== scope.turnId ||
    page.next_sequence > page.last_sequence
  )
    throw new Error('Report replay ownership mismatch')
  let previous = page.reset ? 0 : after
  for (const event of page.events) {
    if (
      !ownsReportEvent(scope, event) ||
      event.sequence <= previous ||
      event.sequence > page.next_sequence
    )
      throw new Error('Report replay sequence mismatch')
    if (event.sequence !== previous + 1) page.gap = true
    previous = event.sequence
  }
  if (page.status === 'ready') {
    if (page.next_sequence > previous) page.gap = true
    if (
      (!page.reset && page.next_sequence < after) ||
      (page.has_more && page.next_sequence <= (page.reset ? 0 : after))
    )
      throw new Error('Report replay did not advance')
  }
  return page
}
