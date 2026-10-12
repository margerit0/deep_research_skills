import { submissionReceiptSchema, sameSelection } from '../data/liveSchema'
import type { LiveResearch, LiveThread, SubmissionReceipt } from '../data/liveSchema'
import { ApiError } from './errors'

export class SubmissionError extends ApiError {
  readonly reason: string
  constructor(status: number, reason: string) {
    super(status)
    this.reason = reason
  }
}

async function request(thread: LiveThread, research: LiveResearch, suffix = '', body?: unknown) {
  const turn = research.turns.at(-1)!
  const response = await fetch(
    `${thread.serverUrl}/atlas/threads/${thread.threadId}/submissions/${turn.id}${suffix}`,
    {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
      cache: 'no-store',
    },
  )
  if (!response.ok) {
    // Only two machine-readable 404 reasons affect retry eligibility. Never
    // retain or display arbitrary backend, gateway, or provider response bodies.
    const error = await response.json().catch(() => ({}))
    const reason = ['submission_unknown', 'thread_missing'].includes(error.reason)
      ? error.reason
      : 'request_failed'
    throw new SubmissionError(response.status, reason)
  }
  const receipt = submissionReceiptSchema.parse(await response.json())
  validateReceipt(thread, research, receipt)
  return receipt
}

export function validateReceipt(
  thread: LiveThread,
  research: LiveResearch,
  receipt: SubmissionReceipt,
) {
  const turn = research.turns.at(-1)!
  if (
    receipt.thread_id !== thread.threadId ||
    (turn.selection && !sameSelection(turn.selection, receipt.configuration?.selection)) ||
    receipt.research_id !== research.id ||
    receipt.turn_id !== turn.id ||
    receipt.attempts.at(-1)?.run_id !== receipt.run_id ||
    receipt.attempts.at(-1)?.attempt_id !== receipt.attempt_id ||
    !receipt.attempts.some((attempt) => attempt.run_id === receipt.event_run_id) ||
    (turn.runId && !receipt.attempts.some((attempt) => attempt.run_id === turn.runId)) ||
    (receipt.run &&
      (receipt.run.run_id !== receipt.run_id ||
        receipt.run.thread_id !== thread.threadId ||
        receipt.run.metadata.atlas_turn_id !== turn.id ||
        receipt.run.metadata.atlas_research_id !== research.id))
  )
    throw new Error('Submission receipt identity mismatch')
}

export const getReceipt = (thread: LiveThread, research: LiveResearch) => request(thread, research)
export const submitResearch = (thread: LiveThread, research: LiveResearch) => {
  const turn = research.turns.at(-1)!
  return request(thread, research, '', {
    research_id: research.id,
    text: turn.text,
    expected_turn_id: turn.expectedTurnId ?? null,
    ...(turn.selection ? { selection: turn.selection } : {}),
  })
}
export const resumeResearch = (thread: LiveThread, research: LiveResearch) => {
  const recovery = research.turns.at(-1)!.recoveryRequest!
  return request(thread, research, `/recoveries/${recovery.id}`, {
    research_id: research.id,
    parent_run_id: recovery.parentRunId,
    checkpoint_id: recovery.checkpointId,
  })
}
