import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from 'react'
import { safeHttpUrl, type ReportStatus } from '../data/live'
import { outlineReport } from '../data/reportOutline'
import { Icon } from './Icon'
import ReportText from './ReportText'

const COLLAPSE_CHARS = 3000
const COLLAPSE_SECTIONS = 6
const COLLAPSED_HEIGHT = 640
const SOURCES_SHOWN = 5

export type ReportCardProps = {
  markdown: string
  status: ReportStatus
  topic?: string
  lanes?: number
  retrievedCount?: number
  duration?: string
  model?: string
  disclaimer?: string
  className?: string
  testId?: string
  ariaLabel?: string
  children?: ReactNode
}

const statusLabels: Record<ReportStatus, [tone: string, label: string] | undefined> = {
  done: ['good', '已完成'],
  partial: ['warn', '部分完成'],
  demo: ['warn', '模拟内容'],
  writing: ['warn', '正在撰写'],
  unconfirmed: undefined,
}

const sectionNumber = (index: number) => String(index + 1).padStart(2, '0')
const hostOf = (url: string) => new URL(url).host.replace(/^www\./, '')
const scrollMotion = (): ScrollBehavior =>
  matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'
const fileName = (title: string) => `${title.replace(/[\\/:*?"<>|\s]+/g, '-').slice(0, 60)}.md`

export default function ReportCard({
  markdown,
  status,
  topic,
  lanes,
  retrievedCount = 0,
  duration,
  model,
  disclaimer,
  className = '',
  testId,
  ariaLabel,
  children,
}: ReportCardProps) {
  const outline = useMemo(() => outlineReport(markdown), [markdown])
  const { lead, sections, conclusion, sources } = outline
  const title = outline.title || '研究报告'
  const collapsible =
    status !== 'writing' &&
    (markdown.length > COLLAPSE_CHARS || sections.length > COLLAPSE_SECTIONS)
  const [expanded, setExpanded] = useState(false)
  const [allSources, setAllSources] = useState(false)
  const [copied, setCopied] = useState<'done' | 'failed'>()
  const [flash, setFlash] = useState<{ index: string; at: number }>()
  const [hiddenSections, setHiddenSections] = useState(0)
  const card = useRef<HTMLElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const open = expanded || !collapsible
  const sourceCount = sources.length || retrievedCount
  const shownSources = allSources ? sources : sources.slice(0, SOURCES_SHOWN)

  useLayoutEffect(() => {
    if (open || !body.current) return
    const clipped = [...body.current.querySelectorAll<HTMLElement>('.cw-report-section')].filter(
      (section) => section.offsetTop + 60 > COLLAPSED_HEIGHT,
    )
    setHiddenSections(clipped.length + (conclusion ? 1 : 0))
  }, [open, markdown, conclusion])

  // The target row only exists once the longer source list has rendered.
  useEffect(() => {
    if (!flash) return
    card.current
      ?.querySelector(`[data-source-index="${flash.index}"]`)
      ?.scrollIntoView({ block: 'center', behavior: scrollMotion() })
    const timer = setTimeout(() => setFlash(undefined), 1800)
    return () => clearTimeout(timer)
  }, [flash])

  useEffect(() => {
    if (!copied) return
    const timer = setTimeout(() => setCopied(undefined), 1600)
    return () => clearTimeout(timer)
  }, [copied])

  const followCitation = (event: MouseEvent) => {
    const cite = (event.target as HTMLElement).closest<HTMLElement>('[data-cite]')
    if (!cite) return
    event.preventDefault()
    const index = cite.dataset.cite!
    if (!sources.some((source) => source.index === index)) return
    setAllSources(true)
    setFlash({ index, at: Date.now() })
  }
  const copy = () =>
    navigator.clipboard.writeText(markdown).then(
      () => setCopied('done'),
      () => setCopied('failed'),
    )
  const download = () => {
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = fileName(title)
    link.click()
    URL.revokeObjectURL(url)
  }
  const toggle = () => {
    setExpanded(!open)
    if (open) card.current?.scrollIntoView({ block: 'start', behavior: scrollMotion() })
  }

  const citations = sources.length > 0
  const pill = statusLabels[status]
  return (
    <section
      ref={card}
      className={`cw-report-message cw-report-card ${className}`}
      data-testid={testId}
      data-streaming={status === 'writing'}
      data-collapsed={!open}
      aria-label={ariaLabel ?? title}
      onClick={followCitation}
    >
      <header className="cw-report-head">
        <span className="cw-report-tile">
          <Icon name="file-check-2" />
        </span>
        <div className="cw-report-heading">
          <div className="cw-report-title">
            <h3>{title}</h3>
            {pill && (
              <span className="cw-report-status" data-tone={pill[0]}>
                {pill[1]}
              </span>
            )}
          </div>
          {topic && <p className="cw-report-topic">{topic}</p>}
          <ul className="cw-report-meta">
            {!!lanes && (
              <li>
                <Icon name="branch" />
                {lanes} 个研究方向
              </li>
            )}
            <li>
              <Icon name="link" />
              {sourceCount ? `${sourceCount} 条来源` : '暂无来源'}
            </li>
            {duration && (
              <li>
                <Icon name="clock" />
                {duration}
              </li>
            )}
            {model && (
              <li>
                <Icon name="bot" />
                {model}
              </li>
            )}
          </ul>
        </div>
        {status !== 'writing' && (
          <div className="cw-report-actions">
            <button
              type="button"
              className="cw-icon-button"
              aria-label={copied === 'failed' ? '复制失败' : copied ? '已复制' : '复制 Markdown'}
              title={copied === 'failed' ? '复制失败' : copied ? '已复制' : '复制 Markdown'}
              onClick={copy}
            >
              <Icon name={copied === 'done' ? 'check' : copied ? 'x' : 'copy'} />
            </button>
            <button
              type="button"
              className="cw-icon-button"
              aria-label="下载 Markdown"
              title="下载 Markdown"
              onClick={download}
            >
              <Icon name="down" />
            </button>
          </div>
        )}
      </header>
      {children}
      {!open && conclusion && (
        <aside className="cw-report-conclusion" data-summary="true" aria-label={conclusion.heading}>
          <Icon name="target" />
          <div>
            <b>{conclusion.heading}</b>
            <ReportText citations={citations}>{conclusion.body}</ReportText>
          </div>
        </aside>
      )}
      <div
        ref={body}
        className="cw-report-body"
        onFocusCapture={(event) => {
          if (!open && (event.target as HTMLElement).matches(':focus-visible')) setExpanded(true)
        }}
      >
        {lead && (
          <div className="cw-report-lead">
            <ReportText citations={citations}>{lead}</ReportText>
          </div>
        )}
        {sections.map((section, index) => (
          <section key={`${index}-${section.heading}`} className="cw-report-section">
            <span className="cw-report-number">{sectionNumber(index)}</span>
            <div>
              <h4>{section.heading}</h4>
              <ReportText citations={citations}>{section.body}</ReportText>
            </div>
          </section>
        ))}
        {open && conclusion && (
          <div className="cw-report-conclusion">
            <Icon name="target" />
            <div>
              <b>{conclusion.heading}</b>
              <ReportText citations={citations}>{conclusion.body}</ReportText>
            </div>
          </div>
        )}
      </div>
      {collapsible && (
        <div className="cw-report-toggle">
          <button type="button" aria-expanded={open} onClick={toggle}>
            <Icon name="chevron" />
            {open ? '收起全文' : '展开全文'}
            {!open && !!hiddenSections && <em>还有 {hiddenSections} 节</em>}
          </button>
        </div>
      )}
      {citations && (
        <section className="cw-report-sources" aria-label="报告引用来源">
          <h4>引用来源 · {sources.length}</h4>
          <ol>
            {shownSources.map((source) => (
              <li
                key={`${source.index}-${source.url}`}
                data-source-index={source.index}
                data-flash={flash?.index === source.index}
              >
                <span className="cw-cite">{source.index}</span>
                <a href={safeHttpUrl(source.url)} target="_blank" rel="noopener noreferrer">
                  <span>{source.title}</span>
                  <small>{hostOf(source.url)}</small>
                </a>
              </li>
            ))}
          </ol>
          {sources.length > SOURCES_SHOWN && (
            <button type="button" onClick={() => setAllSources(!allSources)}>
              {allSources ? '收起来源' : `显示全部 ${sources.length} 条来源`}
            </button>
          )}
        </section>
      )}
      {disclaimer && (
        <footer className="cw-report-foot">
          <Icon name="info" />
          <p>{disclaimer}</p>
        </footer>
      )}
    </section>
  )
}
