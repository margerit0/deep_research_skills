import { workflowEventPageSchema } from '../data/liveSchema'
import type { LiveResearch, LiveThread } from '../data/liveSchema'
import { ownsWorkflowEvent, sameWorkflowRef } from '../data/workflowRuntime'
import { ApiError } from './errors'

export async function readWorkflowEventPage(
  thread: LiveThread,
  research: LiveResearch,
  runId: string,
  after: number,
  journalId: string | undefined,
  signal: AbortSignal,
) {
  const attempt = research.execution?.attempts.find((item) => item.run_id === runId)
  if (!attempt || !research.workflow) throw new Error('Workflow attempt missing')
  const query = new URLSearchParams({
    research_id: research.id,
    turn_id: research.turns.at(-1)!.id,
    attempt_id: attempt.attempt_id,
    after: String(after),
    limit: '100',
    ...(journalId ? { journal_id: journalId } : {}),
  })
  const response = await fetch(
    `${thread.serverUrl}/atlas/threads/${thread.threadId}/runs/${runId}/workflow-events?${query}`,
    {
      cache: 'no-store',
      signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]),
    },
  )
  if (!response.ok) throw new ApiError(response.status)
  const page = workflowEventPageSchema.parse(await response.json())
  let expected = page.reset ? 1 : after + 1
  if (
    page.thread_id !== thread.threadId ||
    page.run_id !== runId ||
    page.research_id !== research.id ||
    page.turn_id !== research.turns.at(-1)?.id ||
    page.attempt_id !== attempt.attempt_id ||
    !sameWorkflowRef(research.workflow, page.workflow_ref) ||
    page.semantic_hash !== research.workflow.semantic_hash ||
    page.events.some(
      (event) =>
        !ownsWorkflowEvent(thread, research, runId, event) || event.sequence !== expected++,
    ) ||
    page.next_sequence > page.last_sequence ||
    (page.has_more && !page.events.length) ||
    (page.status === 'ready' &&
      page.next_sequence !== (page.events.at(-1)?.sequence ?? (page.reset ? 0 : after))) ||
    (page.status === 'ready' && !page.has_more && page.next_sequence !== page.last_sequence)
  )
    throw new Error('Workflow event page identity or sequence mismatch')
  return page
}
