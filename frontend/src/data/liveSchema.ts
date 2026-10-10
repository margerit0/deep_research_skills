import { z } from 'zod'

export const backendConfigSchema = z.object({
  contract_version: z.literal(1),
  graph_id: z.literal('research_agent_full'),
  model_selection: z.literal('server'),
  skills_mode: z.literal('auto'),
  research_events_version: z.literal(1).optional(),
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
export const messageSchema = z.object({
  id: z.string(),
  type: z.enum(['human', 'ai']),
  content: z.string(),
  name: z.string().optional(),
})
export const turnSchema = z.object({
  id: z.string(),
  text: z.string(),
  submittedAt: z.string(),
  runId: z.string().optional(),
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
