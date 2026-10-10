import { useEffect, useRef, useState } from 'react'
import { useWorkspace } from './state/useWorkspace'
import { Sidebar } from './components/Sidebar'
import { Conversation } from './components/Conversation'
import { Graph } from './components/Graph'
import { Icon } from './components/Icon'
import './apple.css'
import './app.css'

export default function App() {
  const controller = useWorkspace()
  const { state, thread, dispatch, storageError } = controller
  const [mobileOpen, setMobileOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = root.current!
    const media = window.matchMedia(
      '(hover:hover) and (pointer:fine) and (prefers-reduced-motion:no-preference) and (prefers-reduced-transparency:no-preference)',
    )
    let frame = 0,
      lastSurface: HTMLElement | null = null
    const clear = () => {
      cancelAnimationFrame(frame)
      lastSurface?.style.removeProperty('--cw-light-x')
      lastSurface?.style.removeProperty('--cw-light-y')
      lastSurface = null
    }
    const move = (event: PointerEvent) => {
      if (!media.matches) {
        clear()
        return
      }
      const surface = (event.target as HTMLElement).closest<HTMLElement>(
        '.cw-sidebar, .cw-composer, .cw-inspector',
      )
      if (surface !== lastSurface) clear()
      if (!surface) return
      lastSurface = surface
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const box = surface.getBoundingClientRect()
        surface.style.setProperty('--cw-light-x', `${event.clientX - box.left}px`)
        surface.style.setProperty('--cw-light-y', `${event.clientY - box.top}px`)
      })
    }
    element.addEventListener('pointermove', move)
    element.addEventListener('pointerleave', clear)
    media.addEventListener('change', clear)
    return () => {
      clear()
      element.removeEventListener('pointermove', move)
      element.removeEventListener('pointerleave', clear)
      media.removeEventListener('change', clear)
    }
  }, [])
  const themeLabel = { system: '跟随系统', light: '浅色', dark: '深色' }
  return (
    <div
      ref={root}
      id="atlas-conversation-workspace"
      data-palette="apple"
      data-graph={state.graphOpen ? 'open' : 'closed'}
      aria-label="星图工作台 · Apple 银白"
    >
      <Sidebar
        controller={controller}
        mobileOpen={mobileOpen}
        onClose={() => setMobileOpen(false)}
      />
      <main className="cw-main">
        <header className="cw-header">
          <button
            type="button"
            className="cw-brand-icon cw-mobile-brand"
            aria-label="打开最近对话"
            aria-haspopup="dialog"
            onClick={() => setMobileOpen(true)}
          >
            <Icon name="asterisk" />
          </button>
          <div className="cw-header-title">
            <h1>{thread.title}</h1>
            <div className="cw-header-caption">星图工作台</div>
          </div>
          <span className="cw-spacer" />
          <span className="cw-label">本地演示</span>
          <button
            type="button"
            className="cw-icon-button cw-theme"
            aria-label={`外观：${themeLabel[state.theme]}`}
            title={`外观：${themeLabel[state.theme]} · 点击切换`}
            onClick={() =>
              dispatch({
                type: 'theme',
                theme:
                  state.theme === 'system' ? 'light' : state.theme === 'light' ? 'dark' : 'system',
              })
            }
          >
            <Icon name={state.theme} />
          </button>
          <button
            id="graph-toggle"
            type="button"
            className="cw-graph-toggle"
            aria-expanded={state.graphOpen}
            aria-controls="cw-graph-panel"
            onClick={() => dispatch({ type: 'graph', open: !state.graphOpen })}
          >
            <Icon name="panel" />
            流程图
          </button>
          <button
            type="button"
            className="cw-icon-button cw-new-mobile"
            aria-label="开始新研究"
            onClick={() => dispatch({ type: 'new' })}
          >
            <Icon name="edit" />
          </button>
        </header>
        {storageError && (
          <p className="cw-storage-alert" role="status">
            浏览器暂时无法保存本地会话；当前内容可继续使用，但刷新后可能丢失。
          </p>
        )}
        <div className="cw-workarea">
          <Conversation key={thread.id} controller={controller} />
          {state.graphOpen && <Graph controller={controller} />}
        </div>
      </main>
    </div>
  )
}
