import { researchEventSchema, reportEventSchema } from '../data/liveSchema'
import type { LiveThread, ResearchEvent, ReportEvent } from '../data/liveSchema'
import { ApiError } from './errors'

interface StreamOptions {
  signal: AbortSignal
  after: string
  onOpen: () => void
  onCursor: (id: string) => void
  onEvent: (event: ResearchEvent) => void
  onReportEvent?: (event: ReportEvent) => void
}

// Joining is read-only. Disconnecting this observer never cancels the research.
export async function streamResearchEvents(
  thread: LiveThread,
  runId: string,
  options: StreamOptions,
) {
  const handshake = new AbortController()
  const timeout = window.setTimeout(() => handshake.abort(), 15000)
  let response: Response
  try {
    response = await fetch(
      `${thread.serverUrl}/threads/${thread.threadId}/runs/${runId}/stream?stream_mode=custom&cancel_on_disconnect=false`,
      {
        headers: { Accept: 'text/event-stream', 'Last-Event-ID': options.after },
        signal: AbortSignal.any([options.signal, handshake.signal]),
        cache: 'no-store',
      },
    )
  } finally {
    clearTimeout(timeout)
  }
  if (!response.ok || !response.body) throw new ApiError(response.status)
  options.onOpen()
  await readResearchEvents(response.body, options)
}

export async function readResearchEvents(
  body: ReadableStream<Uint8Array>,
  options: Pick<StreamOptions, 'onCursor' | 'onEvent' | 'onReportEvent'>,
) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = '',
    eventName = '',
    eventId = '',
    data: string[] = []
  try {
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) return
      buffer += decoder.decode(chunk.value, { stream: true })
      if (buffer.length + data.join('\n').length > 256000)
        throw new Error('Research event frame too large')
      let newline: number
      while ((newline = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, newline).replace(/\r$/, '')
        buffer = buffer.slice(newline + 1)
        if (line === '') {
          if (eventName === 'error') throw new Error('Research event stream ended with an error')
          if (eventName === 'end') return
          if (eventName === 'custom' && data.length) {
            let payload: unknown
            try {
              payload = JSON.parse(data.join('\n'))
            } catch {
              /* Ignore malformed custom events. */
            }
            if (
              payload &&
              typeof payload === 'object' &&
              'type' in payload &&
              payload.type === 'atlas.research_event' &&
              'event' in payload
            ) {
              const parsed = researchEventSchema.safeParse(payload.event)
              if (parsed.success) options.onEvent(parsed.data)
            }
            if (
              payload &&
              typeof payload === 'object' &&
              'type' in payload &&
              payload.type === 'atlas.report_event' &&
              'event' in payload
            ) {
              const parsed = reportEventSchema.safeParse(payload.event)
              if (parsed.success) options.onReportEvent?.(parsed.data)
            }
          }
          if (eventId && !eventId.includes('\0')) options.onCursor(eventId)
          eventName = ''
          eventId = ''
          data = []
        } else if (!line.startsWith(':')) {
          const colon = line.indexOf(':')
          const field = colon === -1 ? line : line.slice(0, colon)
          const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '')
          if (field === 'event') eventName = value
          else if (field === 'id') eventId = value
          else if (field === 'data') data.push(value)
        }
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
