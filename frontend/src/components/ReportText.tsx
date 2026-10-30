import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { safeHttpUrl } from '../data/live'

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] }

const CITE_HREF = /^#cite-(\d+)$/

// Turns bare "[3]" markers in prose into links the card resolves against its source list.
function remarkCitations() {
  const visit = (node: MdNode) => {
    if (!node.children || node.type === 'link' || node.type === 'linkReference') return
    node.children = node.children.flatMap((child) => {
      if (child.type !== 'text' || !child.value?.includes('[')) {
        visit(child)
        return [child]
      }
      const parts: MdNode[] = []
      let last = 0
      for (const match of child.value.matchAll(/\[(\d{1,3})\]/g)) {
        if (match.index > last)
          parts.push({ type: 'text', value: child.value.slice(last, match.index) })
        parts.push({
          type: 'link',
          url: `#cite-${match[1]}`,
          children: [{ type: 'text', value: match[1] }],
        })
        last = match.index + match[0].length
      }
      if (!parts.length) return [child]
      if (last < child.value.length) parts.push({ type: 'text', value: child.value.slice(last) })
      return parts
    })
  }
  return (tree: MdNode) => visit(tree)
}

export default function ReportText({
  children,
  citations = false,
}: {
  children: string
  citations?: boolean
}) {
  return (
    <div className="cw-report-markdown">
      <Markdown
        remarkPlugins={citations ? [remarkGfm, remarkCitations] : [remarkGfm]}
        skipHtml
        urlTransform={(url) => (citations && CITE_HREF.test(url) ? url : (safeHttpUrl(url) ?? ''))}
        components={{
          a: ({ href, children: label }) => {
            const cite = href?.match(CITE_HREF)
            if (cite)
              return (
                <a
                  className="cw-cite"
                  href={href}
                  data-cite={cite[1]}
                  aria-label={`来源 ${cite[1]}`}
                >
                  {label}
                </a>
              )
            return href && safeHttpUrl(href) ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {label}
              </a>
            ) : (
              <span>{label}</span>
            )
          },
          img: ({ alt }) => <span>{alt}</span>,
          table: ({ children: rows }) => (
            <div className="cw-table-scroll">
              <table>{rows}</table>
            </div>
          ),
        }}
      >
        {children}
      </Markdown>
    </div>
  )
}
