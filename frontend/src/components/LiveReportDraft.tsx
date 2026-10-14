import { lazy, Suspense } from 'react'
import type { LiveResearch, LiveThread } from '../data/liveSchema'
import { reportHasGap, savedReportStream, writingDrafts } from '../data/reportEvents'

const MarkdownReport = lazy(() => import('./ReportText'))
const labels = {
  writing: '正在生成',
  finished: '正文已收到，等待确认',
  failed: '写作失败',
  unconfirmed: '写作已中断，完成状态未确认',
}

export function LiveReportDraft({
  thread,
  research,
  replayState,
}: {
  thread: LiveThread
  research: LiveResearch
  replayState?: 'ready' | 'pending' | 'retrying' | 'incomplete'
}) {
  const stream = savedReportStream(thread, research)
  const active = stream ? writingDrafts(stream).at(-1) : undefined
  const history = (research.reportStreams ?? [])
    .flatMap(writingDrafts)
    .filter(
      (draft) => draft.id !== active?.id && draft.id !== research.reportIdentity?.writingAttemptId,
    )
  const state =
    active?.state === 'writing' && research.status !== 'running' ? 'unconfirmed' : active?.state
  return (
    <>
      {active && !research.report && (
        <div
          className="cw-report-message"
          data-testid="live-report-draft"
          data-writing-attempt={active.id}
        >
          <div className="cw-row">
            <span className="cw-strong" role="status">
              报告草稿 · {labels[state!]}
            </span>
          </div>
          <p className="cw-muted">内容以最终确认的报告为准。</p>
          {active.text && (
            <Suspense fallback={<p className="cw-muted">正在排版草稿…</p>}>
              <MarkdownReport>{active.text}</MarkdownReport>
            </Suspense>
          )}
        </div>
      )}
      {!research.report &&
        (['pending', 'retrying', 'incomplete'].includes(replayState ?? '') ||
          (stream && reportHasGap(stream))) && (
          <p className="cw-sync-note" role="status" data-testid="report-recovery-note">
            {replayState === 'incomplete' || (stream && reportHasGap(stream))
              ? '部分写作记录无法确认，已保留连续正文，等待回读或最终报告。'
              : replayState === 'pending'
                ? '写作记录尚未就绪，正在等待；已收到的草稿会保留。'
                : '写作记录暂时无法回读，正在重试；已收到的草稿会保留。'}
          </p>
        )}
      {history.length > 0 && (
        <details className="cw-report-message" data-testid="report-attempt-history">
          <summary>先前写作尝试 · {history.length}</summary>
          {history.map((draft, index) => (
            <details key={`${draft.runId}-${draft.id}`} data-writing-attempt={draft.id}>
              <summary>
                第 {index + 1} 次写作 ·{' '}
                {labels[draft.state === 'writing' ? 'unconfirmed' : draft.state]}
              </summary>
              <p className="cw-muted">此尝试的草稿未作为最终报告交付。</p>
              <Suspense fallback={<p className="cw-muted">正在排版草稿…</p>}>
                <MarkdownReport>{draft.text}</MarkdownReport>
              </Suspense>
            </details>
          ))}
        </details>
      )}
    </>
  )
}
