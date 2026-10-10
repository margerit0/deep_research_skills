import type { NodeStatus } from '../data/schema'
export function StatusMark({ status }: { status: NodeStatus }) {
  return (
    <span className="cw-mini-state" aria-hidden="true">
      {{ pending: '○', waiting: '?', running: '●', completed: '✓' }[status]}
    </span>
  )
}
