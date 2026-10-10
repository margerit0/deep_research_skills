import { z } from 'zod'
import { backendConfigSchema, graphValuesSchema, serverRunSchema } from '../data/liveSchema'
import type { LiveResearch, LiveThread, LiveTurn } from '../data/liveSchema'
import { ApiError } from './errors'
export { ApiError } from './errors'

export const apiUrl = (import.meta.env.VITE_LANGGRAPH_API_URL || '/api').replace(/\/$/, '')

async function request(base: string, path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    signal: AbortSignal.timeout(15000),
    cache: 'no-store',
  })
  // Do not forward provider messages, keys, stack traces or proxy HTML into the UI.
  if (!response.ok) throw new ApiError(response.status)
  return response.json()
}

const runSchema = serverRunSchema
const snapshotSchema = z.object({
  values: graphValuesSchema,
  next: z.array(z.string()).default([]),
})
export type ServerRun = z.infer<typeof runSchema>

export async function getConfig(base = apiUrl) {
  return backendConfigSchema.parse(await request(base, '/atlas/config'))
}

export async function createThread(thread: LiveThread) {
  await request(thread.serverUrl, '/threads', {
    method: 'POST',
    body: JSON.stringify({
      thread_id: thread.threadId,
      if_exists: 'do_nothing',
      metadata: { atlas_workspace: 1 },
    }),
  })
}

export async function createRun(thread: LiveThread, research: LiveResearch, turn: LiveTurn) {
  return runSchema.parse(
    await request(thread.serverUrl, `/threads/${thread.threadId}/runs`, {
      method: 'POST',
      body: JSON.stringify({
        assistant_id: 'research_agent_full',
        input: {
          research_id: research.id,
          turn_id: turn.id,
          messages: [{ type: 'human', id: turn.id, content: turn.text }],
        },
        metadata: { atlas_research_id: research.id, atlas_turn_id: turn.id },
        multitask_strategy: 'reject',
        if_not_exists: 'reject',
        durability: 'sync',
        ...(research.config.research_events_version === 1
          ? { stream_mode: ['custom'], stream_resumable: true }
          : {}),
      }),
    }),
  )
}

export async function findRun(
  thread: LiveThread,
  research: LiveResearch,
): Promise<ServerRun | undefined> {
  const turn = research.turns.at(-1)!
  if (turn.runId) {
    const run = runSchema.parse(
      await request(thread.serverUrl, `/threads/${thread.threadId}/runs/${turn.runId}`),
    )
    if (
      run.thread_id !== thread.threadId ||
      run.metadata.atlas_turn_id !== turn.id ||
      run.metadata.atlas_research_id !== research.id
    )
      throw new Error('Run identity mismatch')
    return run
  }
  // A lost POST response is reconciled by its persisted turn ID, never by "latest run".
  for (let offset = 0; ; offset += 100) {
    const runs = z
      .array(runSchema)
      .parse(
        await request(
          thread.serverUrl,
          `/threads/${thread.threadId}/runs?limit=100&offset=${offset}`,
        ),
      )
    const found = runs.find(
      (run) =>
        run.metadata.atlas_turn_id === turn.id &&
        run.metadata.atlas_research_id === research.id &&
        run.thread_id === thread.threadId,
    )
    if (found) return found
    if (runs.length < 100) return undefined
  }
}

export async function getState(thread: LiveThread, checkpointId?: string) {
  return snapshotSchema.parse(
    await request(
      thread.serverUrl,
      `/threads/${thread.threadId}/state${checkpointId ? `/${encodeURIComponent(checkpointId)}` : ''}`,
    ),
  )
}
