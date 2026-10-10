import { useEffect, useRef } from 'react'
import type { WorkspaceController } from '../state/useWorkspace'
import { Icon } from './Icon'

export function Sidebar({
  controller,
  mobileOpen,
  onClose,
}: {
  controller: WorkspaceController
  mobileOpen: boolean
  onClose: () => void
}) {
  const { state, dispatch } = controller
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (mobileOpen) dialog.current?.showModal()
    else dialog.current?.close()
  }, [mobileOpen])
  const content = (mobile = false) => (
    <>
      <div className="cw-brand">
        <span className="cw-brand-icon">
          <Icon name="asterisk" />
        </span>
        <span className="cw-brand-name">Deep Research</span>
        {mobile && (
          <button
            type="button"
            className="cw-icon-button cw-drawer-close"
            aria-label="关闭最近对话"
            onClick={onClose}
          >
            <Icon name="x" />
          </button>
        )}
      </div>
      <button
        type="button"
        className="cw-new-chat"
        onClick={() => {
          dispatch({ type: 'new' })
          onClose()
        }}
      >
        <Icon name="edit" />
        新研究
      </button>
      <div className="cw-sidebar-label">最近对话</div>
      <div className="cw-thread-list">
        {state.threads.map((thread) => (
          <button
            type="button"
            key={thread.id}
            className="cw-thread"
            aria-current={thread.id === state.activeThreadId ? 'page' : undefined}
            title={thread.title}
            onClick={() => {
              dispatch({ type: 'switch', id: thread.id })
              onClose()
            }}
          >
            <span className="cw-thread-dot" />
            <span>{thread.title}</span>
          </button>
        ))}
      </div>
      <div className="cw-spacer" />
      <div className="cw-person">
        <span className="cw-avatar">ML</span>
        <span>个人研究空间</span>
      </div>
    </>
  )
  return (
    <>
      <nav className="cw-sidebar" aria-label="研究对话导航">
        {content()}
      </nav>
      <dialog
        ref={dialog}
        className="cw-drawer"
        aria-label="最近对话"
        onCancel={onClose}
        onClick={(e) => {
          if (e.target === dialog.current) onClose()
        }}
      >
        <nav className="cw-sidebar" aria-label="移动端研究对话导航">
          {content(true)}
        </nav>
      </dialog>
    </>
  )
}
