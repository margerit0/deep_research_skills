import { safeHttpUrl } from './live'

export type ReportSource = { index: string; title: string; url: string }
export type ReportSection = { heading: string; body: string }
export type ReportOutline = {
  title: string
  lead: string
  sections: ReportSection[]
  conclusion?: ReportSection
  sources: ReportSource[]
}

const SOURCES_HEADING = /^(来源|参考来源|参考资料|参考文献|引用来源|信息来源|sources|references)$/i
const CONCLUSION_HEADING = /结论|总结|建议|下一步|conclusion|summary|recommendation/i
// Numbering the writer adds itself ("2.", "3.1 ", "一、") — the card numbers sections.
const HEADING_NUMBER = /^(\d+(\.\d+)*[.、)）]\s*|\d+(\.\d+)+\s+|[一二三四五六七八九十]+、\s*)/
const LABELLED_PARAGRAPH = /^([^。！？.!?：:\n]{2,24})[：:]\s*([\s\S]+)$/

type Line = { text: string; level: number }

function scan(markdown: string): Line[] {
  let fenced = false
  return markdown.split(/\r?\n/).map((text) => {
    if (/^\s*(```|~~~)/.test(text)) fenced = !fenced
    const heading = fenced ? null : text.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/)
    return heading ? { text: heading[2], level: heading[1].length } : { text, level: 0 }
  })
}

const join = (lines: Line[]) =>
  lines
    .map((line) => (line.level ? `${'#'.repeat(line.level)} ${line.text}` : line.text))
    .join('\n')
    .replace(/(^|\n)\s*(-{3,}|\*{3,})\s*(?=\n|$)/g, '$1')
    .trim()

function parseSources(lines: string[]): ReportSource[] {
  const sources: ReportSource[] = []
  for (const raw of lines) {
    const line = raw.replace(/^\s*[-*]\s+/, '').trim()
    const numbered = line.match(/^(?:\[(\d+)\]|(\d+)[.、)])\s*(.+)$/)
    if (!numbered) continue
    const index = numbered[1] ?? numbered[2]
    let rest = numbered[3]
    const link = rest.match(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/)
    const bare = rest.match(/<?(https?:\/\/[^\s>)]+)>?/)
    const url = link?.[2] ?? bare?.[1]
    if (!url || !safeHttpUrl(url)) continue
    rest = link ? rest.replace(link[0], link[1]) : rest.replace(bare![0], '')
    const title = rest.replace(/[\s:：，,|｜–—-]+$/, '').trim()
    sources.push({ index, title: title || url, url })
  }
  return sources
}

/** Splits a writer's Markdown report into the parts the report card lays out. */
export function outlineReport(markdown: string): ReportOutline {
  const lines = scan(markdown)
  let title = ''
  let start = 0
  const firstHeading = lines.findIndex((line) => line.level)
  if (
    firstHeading >= 0 &&
    lines[firstHeading].level === 1 &&
    !lines.slice(0, firstHeading).some((line) => line.text.trim())
  ) {
    title = lines[firstHeading].text
    start = firstHeading + 1
  }
  const body = lines.slice(start)

  // Pull out the trailing sources section, keeping it in the body when it does not parse.
  let sources: ReportSource[] = []
  const sourceAt = body.findIndex(
    (line) =>
      line.level &&
      SOURCES_HEADING.test(
        line.text
          .replace(HEADING_NUMBER, '')
          .replace(/[:：]$/, '')
          .trim(),
      ),
  )
  let content = body
  if (sourceAt >= 0) {
    const level = body[sourceAt].level
    const end = body.findIndex(
      (line, index) => index > sourceAt && line.level && line.level <= level,
    )
    const block = body.slice(sourceAt + 1, end < 0 ? undefined : end)
    sources = parseSources(block.map((line) => line.text))
    if (sources.length) content = [...body.slice(0, sourceAt), ...(end < 0 ? [] : body.slice(end))]
  }

  const levels = content.filter((line) => line.level).map((line) => line.level)
  const sectionLevel = levels.length ? Math.min(...levels) : 0
  const lead: Line[] = []
  let sections: ReportSection[] = []
  let current: { heading: string; lines: Line[] } | undefined
  const flush = () => {
    if (current) sections.push({ heading: current.heading, body: join(current.lines) })
  }
  if (sectionLevel) {
    for (const line of content) {
      if (line.level === sectionLevel) {
        flush()
        current = { heading: line.text.replace(HEADING_NUMBER, '').trim() || line.text, lines: [] }
      } else (current ? current.lines : lead).push(line)
    }
    flush()
  } else {
    // A report without headings: a short first line is the title, "label：text" paragraphs are sections.
    const paragraphs = join(content)
      .split(/\n\s*\n/)
      .map((part) => part.trim())
      .filter(Boolean)
    if (
      !title &&
      paragraphs[0] &&
      paragraphs[0].length <= 50 &&
      !paragraphs[0].includes('\n') &&
      !/[。.！!？?]$/.test(paragraphs[0])
    )
      title = paragraphs.shift()!
    const leadParts: string[] = []
    const found: { heading: string; parts: string[] }[] = []
    for (const paragraph of paragraphs) {
      const labelled = paragraph.match(LABELLED_PARAGRAPH)
      if (labelled && !/[*`[\]]/.test(labelled[1]))
        found.push({ heading: labelled[1].trim(), parts: [labelled[2]] })
      else (found.at(-1)?.parts ?? leadParts).push(paragraph)
    }
    if (found.length >= 2) {
      sections = found.map((item) => ({ heading: item.heading, body: item.parts.join('\n\n') }))
      lead.push({ text: leadParts.join('\n\n'), level: 0 })
    } else lead.push({ text: paragraphs.join('\n\n'), level: 0 })
  }

  let conclusion: ReportSection | undefined
  if (sections.length > 1 && CONCLUSION_HEADING.test(sections.at(-1)!.heading))
    conclusion = sections.pop()

  return { title, lead: join(lead), sections, conclusion, sources }
}
