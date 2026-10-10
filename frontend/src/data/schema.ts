import { z } from 'zod'
import { liveThreadSchema } from './liveSchema'

export const modelSchema = z.enum(['qwen', 'deepseek', 'gpt4o'])
export const skillSchema = z.enum([
  'auto',
  'product-comparison',
  'academic-research',
  'news-timeline',
  'people-research',
])
export const stageSchema = z.enum(['clarify', 'research', 'writing', 'complete'])
const configSchema = z.object({ model: modelSchema, skill: skillSchema })
const researcherSchema = z.object({
  id: z.string(),
  title: z.string(),
  shortTitle: z.string(),
  task: z.string(),
  icon: z.string(),
})
const runSchema = z.object({
  id: z.string(),
  prompt: z.string(),
  config: configSchema,
  stage: stageSchema,
  kind: z.enum(['example', 'custom']),
  researchers: z.array(researcherSchema).min(1),
})
const threadSchema = z
  .object({
    id: z.string(),
    title: z.string(),
    draft: z.string(),
    runs: z.array(runSchema),
    selectedRunId: z.string().nullable(),
    source: z.enum(['mock', 'live']).optional(),
    live: liveThreadSchema.optional(),
  })
  .refine((thread) => thread.source !== 'live' || !!thread.live, {
    message: 'A live thread must include its server mapping.',
  })
export const workspaceSchema = z.object({
  version: z.literal(1),
  threads: z.array(threadSchema).min(1),
  activeThreadId: z.string(),
  config: configSchema,
  theme: z.enum(['system', 'light', 'dark']),
  graphOpen: z.boolean(),
  inspectorOpen: z.boolean(),
  inspectorTab: z.enum(['overview', 'io', 'events']),
  selectedNode: z.string(),
})
export type Config = z.infer<typeof configSchema>
export type ModelId = Config['model']
export type SkillId = Config['skill']
export type Run = z.infer<typeof runSchema>
export type Researcher = z.infer<typeof researcherSchema>
export type Thread = z.infer<typeof threadSchema>
export type Workspace = z.infer<typeof workspaceSchema>
export type InspectorTab = Workspace['inspectorTab']
export type NodeStatus = 'pending' | 'waiting' | 'running' | 'completed' | 'failed' | 'partial'
export interface NodeDetail {
  id: string
  title: string
  shortTitle: string
  icon: string
  path: string
  backendId: string
  status: NodeStatus
  caption: string
  description: string
  duration: string
  countLabel: string
  count: string
  tool: string
  query: string
  input: string
  output: string
  events: [string, string, string][]
  researcher: boolean
  modelRole?: string
}
