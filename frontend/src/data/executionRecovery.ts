import type { GraphValues, LiveResearch, SubmissionReceipt } from './liveSchema'
import { applySnapshot, safeHttpUrl } from './live'

export function applyReceipt(
  research: LiveResearch,
  receipt: SubmissionReceipt,
  values?: GraphValues,
): LiveResearch {
  const interrupted = ['interrupted', 'blocked'].includes(receipt.status)
  const server = receipt.run && {
    ...receipt.run,
    status:
      receipt.status === 'completed'
        ? ('success' as const)
        : interrupted
          ? ('interrupted' as const)
          : receipt.run.status,
  }
  let next = server && values ? applySnapshot(research, server, values) : { ...research }
  if (interrupted) {
    // Native checkpoints may be older than evidence already confirmed locally.
    // Preserve that evidence without claiming that execution or a report finished.
    next.notes = [
      ...new Set([
        ...research.notes,
        ...next.notes,
        ...research.events.flatMap((event) =>
          event.kind === 'completed' && event.output ? [event.output] : [],
        ),
      ]),
    ]
    next.sources = [
      ...new Map(
        [
          ...research.sources,
          ...next.sources,
          ...research.events.flatMap((event) => event.sources ?? []),
        ]
          .filter((source) => safeHttpUrl(source.url))
          .map((source) => [source.url, source]),
      ).values(),
    ]
    next.report ||= research.report
    next.brief ||= research.brief
    next.status = next.notes.length || next.report || next.sources.length ? 'partial' : 'failed'
    next.errors = next.errors.filter(
      (error) => !['run_interrupted', 'incomplete_run', 'state_mismatch'].includes(error.code),
    )
  } else if (receipt.status === 'accepted' || receipt.status === 'retryable') {
    next.status = 'running'
    next.errors = next.errors.filter(
      (error) => !['run_interrupted', 'incomplete_run'].includes(error.code),
    )
  } else if (receipt.status === 'rejected') next.status = 'failed'
  next.execution = receipt
  next.turns = next.turns.map((turn, index) =>
    index !== next.turns.length - 1
      ? turn
      : {
          ...turn,
          runId: receipt.run_id,
          eventRunId: receipt.event_run_id,
          transport: receipt.status === 'rejected' ? 'rejected' : 'accepted',
          recoveryRequest:
            turn.recoveryRequest &&
            receipt.attempts.some((attempt) => attempt.attempt_id === turn.recoveryRequest!.id)
              ? undefined
              : turn.recoveryRequest,
        },
  )
  return next
}

export function executionMessage(receipt: SubmissionReceipt): string {
  if (receipt.status === 'retryable') return '提交已记录，执行尚未开始。可以安全重试同一提交。'
  if (receipt.reason === 'thread_missing') return '服务端会话已不存在。已保留本地成果，请新建研究。'
  if (receipt.status === 'blocked')
    return '服务端缺少可验证的运行或检查点，暂时无法继续。已保留确认过的成果。'
  if (receipt.status === 'rejected')
    return '此会话的提交发生冲突。请读取最新状态，或新建研究并保留当前记录。'
  if (receipt.status !== 'interrupted') return ''
  if (receipt.recovery.allowed) {
    return receipt.recovery.node === 'final_report_generation'
      ? '执行已中断，研究笔记和来源已保存。可继续生成报告；写作模型可能再次调用，已完成的检索不会重跑。'
      : '执行已中断，可从已验证的检查点继续。当前澄清或简报模型可能再次调用。'
  }
  return receipt.reason === 'research_node_not_resumable'
    ? '研究执行已中断，当前研究子流程尚不能安全续跑。已保留确认过的笔记与来源，可新建研究。'
    : '执行已中断，当前检查点尚不能安全续跑。已保留确认过的成果，可重新读取状态或新建研究。'
}
