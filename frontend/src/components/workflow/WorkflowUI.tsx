import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import {
  CircleCheck,
  CirclePlay,
  FileText,
  Files,
  Fingerprint,
  ListChecks,
  MessageSquare,
  Network,
  X,
} from 'lucide-react'

export function WorkflowGlyph({ type }: { type: string }) {
  const Glyph =
    (
      {
        start: CirclePlay,
        prepare_research: Fingerprint,
        clarify_with_user: MessageSquare,
        write_research_brief: FileText,
        optimize_plan: ListChecks,
        supervisor_subgraph: Network,
        organize_notes: Files,
        final_report_generation: FileText,
        end: CircleCheck,
      } as Record<string, typeof FileText>
    )[type] ?? Network
  return <Glyph aria-hidden="true" />
}

export function WorkflowDialog({
  title,
  children,
  onClose,
  busy = false,
}: {
  title: string
  children: ReactNode
  onClose: () => void
  busy?: boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const heading = useId()
  useEffect(() => {
    const active = document.activeElement as HTMLElement | null
    const dialog = ref.current!
    dialog.showModal()
    return () => {
      dialog.close()
      active?.focus()
    }
  }, [])
  return (
    <dialog
      ref={ref}
      className="wf-dialog"
      aria-labelledby={heading}
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onClose()
      }}
      onClick={(event) => {
        if (event.target === ref.current && !busy) onClose()
      }}
    >
      <div className="wf-dialog-heading">
        <h2 id={heading}>{title}</h2>
        <button className="wf-icon" aria-label="关闭对话框" onClick={onClose} disabled={busy}>
          <X />
        </button>
      </div>
      {children}
    </dialog>
  )
}

export const workflowDate = (at: string) =>
  new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(at))
