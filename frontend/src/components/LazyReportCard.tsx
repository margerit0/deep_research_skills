import { lazy, Suspense } from 'react'
import type { ReportCardProps } from './ReportCard'

const ReportCard = lazy(() => import('./ReportCard'))

// The Markdown renderer stays in its own chunk; until it loads the text is already readable.
export function LazyReportCard(props: ReportCardProps) {
  return (
    <Suspense
      fallback={
        <section
          className={`cw-report-message ${props.className ?? ''}`}
          data-testid={props.testId}
          data-streaming={props.status === 'writing'}
          aria-label={props.ariaLabel}
        >
          {props.children}
          <p className="cw-report-fallback">{props.markdown}</p>
        </section>
      }
    >
      <ReportCard {...props} />
    </Suspense>
  )
}
