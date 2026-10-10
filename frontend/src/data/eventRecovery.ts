import type { EventRecovery, LiveResearch, LiveThread } from './liveSchema'

export function recoveryScope(thread: LiveThread, research: LiveResearch): EventRecovery {
  const turn = research.turns.at(-1)!
  return {
    serverUrl: thread.serverUrl,
    threadId: thread.threadId,
    researchId: research.id,
    turnId: turn.id,
    runId: turn.eventRunId ?? turn.runId!,
    sequence: 0,
    gap: false,
    sealed: false,
    unconfirmedBefore: 0,
  }
}

export function savedRecovery(
  thread: LiveThread,
  research: LiveResearch,
): EventRecovery | undefined {
  const saved = research.eventRecovery
  const scope = recoveryScope(thread, research)
  return saved &&
    saved.serverUrl === scope.serverUrl &&
    saved.threadId === scope.threadId &&
    saved.researchId === scope.researchId &&
    saved.turnId === scope.turnId &&
    saved.runId === scope.runId
    ? saved
    : undefined
}

export function retryDelay(failures: number): number {
  return Math.min(30000, 1000 * 2 ** Math.min(failures - 1, 5) * (1 + Math.random() * 0.2))
}
