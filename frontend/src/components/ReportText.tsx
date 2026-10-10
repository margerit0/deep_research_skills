import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { safeHttpUrl } from '../data/live'

export default function ReportText({ children }: { children: string }) {
  return (
    <div className="cw-report-markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={(url) => safeHttpUrl(url) ?? ''}
        components={{
          a: ({ href, children: label }) =>
            href && safeHttpUrl(href) ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {label}
              </a>
            ) : (
              <span>{label}</span>
            ),
          img: ({ alt }) => <span>{alt}</span>,
        }}
      >
        {children}
      </Markdown>
    </div>
  )
}
