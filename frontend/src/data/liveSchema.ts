import { z } from 'zod'

export const selectionSchema = z.object({
  version: z.literal(1),
  models: z.record(z.string(), z.string()),
  skills: z.object({ mode: z.enum(['auto', 'manual']), allowed: z.array(z.string()) }),
})
export type RunSelection = z.infer<typeof selectionSchema>
export function sameSelection(a: RunSelection, b?: RunSelection) {
  return (
    !!b &&
    a.version === b.version &&
    a.skills.mode === b.skills.mode &&
    JSON.stringify([...a.skills.allowed].sort()) === JSON.stringify([...b.skills.allowed].sort()) &&
    Object.keys(a.models).length === Object.keys(b.models).length &&
    Object.entries(a.models).every(([role, id]) => b.models[role] === id)
  )
}
const modelOptionSchema = z.object({
  id: z.string(),
  model: z.string(),
  provider: z.string(),
  max_tokens: z.number().nullable(),
})

export const backendConfigSchema = z.object({
  contract_version: z.literal(1),
  graph_id: z.literal('research_agent_full'),
  model_selection: z.literal('server'),
  skills_mode: z.literal('auto'),
  research_events_version: z.literal(1).optional(),
  research_event_replay_version: z.literal(1).optional(),
  report_events_version: z.literal(1).optional(),
  report_event_replay_version: z.literal(1).optional(),
  submission_recovery_version: z.literal(1).optional(),
  configuration_version: z.literal(1).optional(),
  selection: selectionSchema.optional(),
  skill_revisions: z.record(z.string(), z.string()).optional(),
  catalog: z
    .object({
      models: z.array(modelOptionSchema),
      defaults: z.record(z.string(), z.string()),
      skills: z.array(
        z.object({ name: z.string(), description: z.string(), when_to_use: z.string().optional() }),
      ),
    })
    .optional(),
  models: z
    .array(
      z.object({
        role: z.string(),
        model: z.string(),
        provider: z.string(),
        max_tokens: z.number().nullable(),
        config_id: z.string().optional(),
      }),
    )
    .min(1),
})
export const researchStatusSchema = z.enum([
  'running',
  'awaiting_input',
  'succeeded',
  'failed',
  'partial',
])
export const researchPhaseSchema = z.enum(['clarify', 'brief', 'research', 'writing', 'complete'])
export const sourceSchema = z.object({
  title: z.string(),
  url: z.string(),
  retrieval: z.literal('specified_url').optional(),
})
export const errorSchema = z.object({ code: z.string(), message: z.string(), node: z.string() })
export const researchEventSchema = z.object({
  version: z.literal(1),
  id: z.uuid(),
  research_id: z.string().min(1),
  turn_id: z.string().min(1),
  sequence: z.number().int().positive(),
  at: z.iso.datetime({ offset: true }),
  task_id: z.uuid(),
  round: z.number().int().positive(),
  kind: z.enum([
    'delegated',
    'model_started',
    'model_finished',
    'model_failed',
    'tool_started',
    'tool_finished',
    'tool_failed',
    'compression_started',
    'compression_finished',
    'compression_failed',
    'completed',
    'failed',
  ]),
  elapsed_ms: z.number().int().nonnegative(),
  topic: z.string().max(2050).optional(),
  tool: z.enum(['tavily_search', 'load_skill', 'think_tool', 'unknown']).optional(),
  query: z.string().max(1050).optional(),
  sources: z.array(sourceSchema).max(50).optional(),
  source_count: z.number().int().nonnegative().optional(),
  source_audit: z
    .array(
      z.object({
        url: z.string().max(2100),
        decision: z.enum([
          'accepted',
          'out_of_scope',
          'redirect_out_of_scope',
          'redirect_unverified',
          'redirect_limit',
          'source_http_error',
          'source_unverified',
        ]),
        http_status: z.number().int().nullable(),
        retrieval: z.enum(['search', 'specified_url']).optional(),
      }),
    )
    .max(50)
    .optional(),
  source_audit_count: z.number().int().nonnegative().optional(),
  output: z.string().max(8050).optional(),
})
export type ResearchEvent = z.infer<typeof researchEventSchema>
export const eventPageSchema = z.object({
  version: z.literal(1),
  thread_id: z.string(),
  run_id: z.string(),
  research_id: z.string(),
  turn_id: z.string(),
  status: z.enum(['ready', 'missing', 'expired']),
  journal_id: z.uuid().nullable(),
  events: z.array(researchEventSchema).max(100),
  next_sequence: z.number().int().nonnegative(),
  last_sequence: z.number().int().nonnegative(),
  has_more: z.boolean(),
  sealed: z.boolean(),
  gap: z.boolean(),
  reset: z.boolean(),
  unconfirmed_before_sequence: z.number().int().nonnegative().default(0),
})
export type EventPage = z.infer<typeof eventPageSchema>
export const reportEventSchema = z
  .object({
    version: z.literal(1),
    id: z.uuid(),
    thread_id: z.string().min(1),
    run_id: z.string().min(1),
    research_id: z.string().min(1),
    turn_id: z.string().min(1),
    attempt_id: z.string().min(1),
    writing_attempt_id: z.uuid(),
    sequence: z.number().int().positive(),
    at: z.iso.datetime({ offset: true }),
    kind: z.enum(['started', 'delta', 'failed', 'finished']),
    offset: z.number().int().nonnegative(),
    text: z.string().max(4096).optional(),
    sha256: z
      .string()
      .regex(/^[a-f0-9]{64}$/)
      .optional(),
  })
  .refine((event) => event.kind !== 'delta' || !!event.text)
  .refine((event) => event.kind !== 'started' || event.offset === 0)
  .refine((event) => event.kind !== 'finished' || !!event.sha256)
export type ReportEvent = z.infer<typeof reportEventSchema>
export const reportPageSchema = eventPageSchema.extend({
  events: z.array(reportEventSchema).max(100),
})
export type ReportPage = z.infer<typeof reportPageSchema>
export const reportStreamSchema = z.object({
  serverUrl: z.string(),
  threadId: z.string(),
  researchId: z.string(),
  turnId: z.string(),
  runId: z.string(),
  attemptId: z.string(),
  events: z.array(reportEventSchema).max(10000),
  sequence: z.number().int().nonnegative(),
  cursor: z
    .string()
    .max(256)
    .regex(/^(?:-1|\d+-\d+)$/)
    .optional(),
  journalId: z.uuid().optional(),
  gap: z.boolean(),
  sealed: z.boolean(),
  unconfirmedBefore: z.number().int().nonnegative(),
  conflicts: z.array(z.number().int().positive()),
  archived: z.boolean().optional(),
})
export type ReportStream = z.infer<typeof reportStreamSchema>
export const eventRecoverySchema = z.object({
  serverUrl: z.string(),
  threadId: z.string(),
  researchId: z.string(),
  turnId: z.string(),
  runId: z.string(),
  cursor: z
    .string()
    .max(256)
    .regex(/^(?:-1|\d+-\d+)$/)
    .optional(),
  journalId: z.uuid().optional(),
  sequence: z.number().int().nonnegative().default(0),
  gap: z.boolean().default(false),
  sealed: z.boolean().default(false),
  unconfirmedBefore: z.number().int().nonnegative().default(0),
})
export type EventRecovery = z.infer<typeof eventRecoverySchema>
export const messageSchema = z.object({
  id: z.string(),
  type: z.enum(['human', 'ai']),
  content: z.string(),
  name: z.string().optional(),
})
export const serverRunSchema = z.object({
  run_id: z.string(),
  thread_id: z.string(),
  status: z.enum(['pending', 'running', 'success', 'error', 'timeout', 'interrupted']),
  metadata: z.record(z.string(), z.unknown()).default({}),
})
export const submissionReceiptSchema = z.object({
  version: z.literal(1),
  configuration: backendConfigSchema.optional(),
  thread_id: z.string(),
  research_id: z.string(),
  turn_id: z.string(),
  attempt_id: z.string(),
  run_id: z.string(),
  event_run_id: z.string(),
  checkpoint_id: z.string().optional(),
  status: z.enum(['accepted', 'completed', 'retryable', 'interrupted', 'blocked', 'rejected']),
  reason: z.string(),
  retry_allowed: z.boolean(),
  attempts: z
    .array(
      z.object({ attempt_id: z.string(), run_id: z.string(), kind: z.enum(['submit', 'resume']) }),
    )
    .min(1),
  recovery: z.object({
    allowed: z.boolean(),
    reason: z.string(),
    checkpoint_id: z.string().optional(),
    node: z
      .enum(['clarify_with_user', 'write_research_brief', 'final_report_generation'])
      .optional(),
  }),
  run: serverRunSchema.nullable(),
})
export type SubmissionReceipt = z.infer<typeof submissionReceiptSchema>
export const turnSchema = z.object({
  id: z.string(),
  text: z.string(),
  submittedAt: z.string(),
  runId: z.string().optional(),
  eventRunId: z.string().optional(),
  submissionVersion: z.literal(1).optional(),
  selection: selectionSchema.optional(),
  expectedTurnId: z.string().nullable().optional(),
  recoveryRequest: z
    .object({
      id: z.uuid(),
      parentRunId: z.string(),
      checkpointId: z.string(),
      node: z.string(),
    })
    .optional(),
  transport: z.enum(['sending', 'accepted', 'uncertain', 'rejected']),
})
export const liveResearchSchema = z.object({
  id: z.string(),
  prompt: z.string(),
  createdAt: z.string(),
  config: backendConfigSchema,
  turns: z.array(turnSchema).min(1),
  status: researchStatusSchema,
  phase: researchPhaseSchema,
  messages: z.array(messageSchema),
  brief: z.string(),
  report: z.string(),
  notes: z.array(z.string()),
  sources: z.array(sourceSchema),
  errors: z.array(errorSchema),
  events: z.array(researchEventSchema).default([]),
  // A damaged recovery position must not discard the user's conversation.
  eventRecovery: eventRecoverySchema.optional().catch(undefined),
  reportStreams: z.array(reportStreamSchema).optional().catch(undefined),
  reportIdentity: z
    .object({
      runId: z.string(),
      turnId: z.string(),
      attemptId: z.string(),
      writingAttemptId: z.string(),
    })
    .optional()
    .catch(undefined),
  execution: submissionReceiptSchema.optional().catch(undefined),
  observations: z.array(
    z.object({ at: z.string(), phase: researchPhaseSchema, status: researchStatusSchema }),
  ),
})
export const liveThreadSchema = z.object({
  threadId: z.string(),
  serverUrl: z.string(),
  researches: z.array(liveResearchSchema),
  selection: selectionSchema.optional(),
})
export type BackendConfig = z.infer<typeof backendConfigSchema>
export type LiveResearch = z.infer<typeof liveResearchSchema>
export type LiveThread = z.infer<typeof liveThreadSchema>
export type LiveTurn = z.infer<typeof turnSchema>

// Deliberately ignore raw tool traces and provider errors from native API payloads.
export const graphValuesSchema = z.object({
  active_research_id: z.string().optional(),
  active_turn_id: z.string().optional(),
  report_research_id: z.string().optional(),
  report_run_id: z.string().optional(),
  report_turn_id: z.string().optional(),
  report_attempt_id: z.string().optional(),
  report_writing_attempt_id: z.string().optional(),
  research_status: researchStatusSchema.optional(),
  research_phase: researchPhaseSchema.optional(),
  effective_config: backendConfigSchema.optional(),
  research_brief: z.string().nullish(),
  final_report: z.string().optional(),
  notes: z.array(z.string()).optional(),
  sources: z.array(sourceSchema).optional(),
  research_errors: z.array(errorSchema).optional(),
  // Unknown event versions must not prevent report/status recovery.
  research_events: z
    .array(z.unknown())
    .transform((events) =>
      events.flatMap((event) => {
        const parsed = researchEventSchema.safeParse(event)
        return parsed.success ? [parsed.data] : []
      }),
    )
    .optional(),
  messages: z
    .array(
      z.object({
        id: z.string().nullish(),
        type: z.string(),
        content: z.unknown(),
        name: z.string().nullish(),
      }),
    )
    .optional(),
})
export type GraphValues = z.infer<typeof graphValuesSchema>
