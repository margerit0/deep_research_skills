import { useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Icon } from './Icon'

interface Option {
  id: string
  label: string
  icon?: string
}
interface Props {
  name: 'model' | 'skill'
  label: string
  value: string
  options: readonly Option[]
  open: boolean
  autoFocus?: boolean
  onOpen: (open: boolean) => void
  onChange: (id: string) => void
}

export function Picker({
  name,
  label,
  value,
  options,
  open,
  autoFocus = true,
  onOpen,
  onChange,
}: Props) {
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const edge = useRef<'first' | 'last' | 'selected'>('selected')
  const [left, setLeft] = useState(8)
  const [bottom, setBottom] = useState(44)
  const title = name === 'model' ? '模型' : 'Skills'
  useLayoutEffect(() => {
    if (!open) return
    const position = () => {
      const button = trigger.current!,
        popup = menu.current!,
        form = button.closest('.cw-composer')!
      const rect = form.getBoundingClientRect(),
        anchor = button.getBoundingClientRect()
      setLeft(Math.max(8, Math.min(anchor.left - rect.left, rect.width - popup.offsetWidth - 8)))
      setBottom(rect.bottom - anchor.top + 6)
    }
    position()
    const items = menu.current!.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')
    const selected = options.findIndex((o) => o.id === value)
    if (autoFocus)
      items[
        edge.current === 'first' ? 0 : edge.current === 'last' ? items.length - 1 : selected
      ]?.focus({ preventScroll: true })
    const observer = new ResizeObserver(position)
    observer.observe(trigger.current!.closest('.cw-composer')!)
    return () => observer.disconnect()
  }, [open, options, value, autoFocus])
  const close = () => {
    onOpen(false)
    trigger.current?.focus({ preventScroll: true })
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const items = Array.from(
      menu.current!.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]'),
    )
    const index = items.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      close()
    }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      const next =
        event.key === 'Home'
          ? 0
          : event.key === 'End'
            ? items.length - 1
            : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
      items[next].focus()
    }
    if (event.key === 'Tab') {
      event.preventDefault()
      close()
    }
  }
  return (
    <div className="cw-picker">
      <button
        ref={trigger}
        type="button"
        id={`cw-${name}`}
        className="cw-picker-trigger"
        aria-label={`选择${title}`}
        title={`${title}：${label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={`cw-${name}-menu`}
        onClick={() => {
          edge.current = 'selected'
          onOpen(!open)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault()
            edge.current = e.key === 'ArrowDown' ? 'first' : 'last'
            onOpen(true)
          }
        }}
      >
        {name === 'skill' && <Icon name="layers" />}
        <span className="cw-picker-trigger-label">{label}</span>
        <span className="cw-picker-chevron">
          <Icon name="chevron" />
        </span>
      </button>
      {open && (
        <div
          ref={menu}
          id={`cw-${name}-menu`}
          className="cw-picker-menu"
          role="menu"
          aria-label={`${title}列表`}
          style={{ left, bottom }}
          onKeyDown={onKeyDown}
        >
          <div className="cw-menu-heading">{title}</div>
          {options.map((option, index) => (
            <div key={option.id} role="none">
              {name === 'skill' && index === 1 && (
                <div className="cw-menu-divider" role="separator" />
              )}
              <button
                type="button"
                role="menuitemradio"
                aria-checked={value === option.id}
                className="cw-menu-option"
                tabIndex={-1}
                onClick={() => {
                  onChange(option.id)
                  close()
                }}
              >
                {option.icon && (
                  <span className="cw-menu-icon">
                    <Icon name={option.icon} />
                  </span>
                )}
                <span>{option.label}</span>
                <span className="cw-menu-check">
                  <Icon name="check" />
                </span>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
