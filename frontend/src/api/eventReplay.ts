import { ApiError } from './errors'
import { eventPageSchema } from '../data/liveSchema'
import type { LiveResearch, LiveThread } from '../data/liveSchema'

export async function readEventPage(
  thread: LiveThread,
  research: LiveResearch,
  after: number,
  journalId: string | undefined,
  signal: AbortSignal,
) {
  const turn = research.turns.at(-1)!
  const query = new URLSearchParams({
    research_id: research.id,
    turn_id: turn.id,
    after: String(after),
    limit: '50',
  })
  if (journalId) query.set('journal_id', journalId)
  const response = await fetch(
    `${thread.serverUrl}/atlas/threads/${encodeURIComponent(thread.threadId)}/runs/${encodeURIComponent(turn.runId!)}/events?${query}`,
    { cache: 'no-store', signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]) },
  )
  if (!response.ok) throw new ApiError(response.status)
  const page = eventPageSchema.parse(await response.json())
  if (
    page.thread_id !== thread.threadId ||
    page.run_id !== turn.runId ||
    page.research_id !== research.id ||
    page.turn_id !== turn.id ||
    page.next_sequence > page.last_sequence
  )
    throw new Error('Event replay identity or position mismatch')
  let previous = page.reset ? 0 : after
  for (const event of page.events) {
    if (
      event.research_id !== research.id ||
      event.turn_id !== turn.id ||
      event.sequence <= previous ||
      event.sequence > page.next_sequence
    )
      throw new Error('Invalid event replay sequence')
    if (event.sequence !== previous + 1) page.gap = true
    previous = event.sequence
  }
  if (page.status === 'ready' && page.next_sequence > previous) page.gap = true
  if (
    page.status === 'ready' &&
    ((!page.reset && page.next_sequence < after) ||
      (page.has_more && page.next_sequence <= (page.reset ? 0 : after)))
  )
    throw new Error('Event replay did not advance')
  return page
}
