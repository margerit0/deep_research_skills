import { z } from 'zod'

export const backendConfigSchema = z.object({
  contract_version: z.literal(1),
  graph_id: z.literal('research_agent_full'),
  model_selection: z.literal('server'),
  skills_mode: z.literal('auto'),
  research_events_version: z.literal(1).optional(),
  research_event_replay_version: z.literal(1).optional(),
  submission_recovery_version: z.literal(1).optional(),
  models: z
    .array(
      z.object({
        role: z.string(),
        model: z.string(),
        provider: z.string(),
        max_tokens: z.number().nullable(),
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
export const sourceSchema = z.object({ title: z.string(), url: z.string() })
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
  execution: submissionReceiptSchema.optional().catch(undefined),
  observations: z.array(
    z.object({ at: z.string(), phase: researchPhaseSchema, status: researchStatusSchema }),
  ),
})
export const liveThreadSchema = z.object({
  threadId: z.string(),
  serverUrl: z.string(),
  researches: z.array(liveResearchSchema),
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
