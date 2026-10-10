import { useEffect, useRef, useState } from 'react'
import { models, modelName, skills, skillInfo } from '../data/mock'
import type { ModelId, SkillId } from '../data/schema'
import type { WorkspaceController } from '../state/useWorkspace'
import { Icon } from './Icon'
import { Picker } from './Picker'

export function Composer({ controller }: { controller: WorkspaceController }) {
  const { state, thread, dispatch } = controller
  const [open, setOpen] = useState<'model' | 'skill' | null>(null)
  const form = useRef<HTMLFormElement>(null)
  const composing = useRef(false)
  const skill = skillInfo(state.config.skill)
  useEffect(() => {
    if (!open) return
    const dismiss = (event: Event) => {
      if (!(event.target instanceof Element) || !event.target.closest('.cw-picker')) setOpen(null)
    }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('focusin', dismiss)
    return () => {
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('focusin', dismiss)
    }
  }, [open])
  function send() {
    if (composing.current) return
    setOpen(null)
    dispatch({ type: 'send' })
    form.current?.querySelector('textarea')?.focus()
  }
  return (
    <div className="cw-composer-wrap">
      <div className="cw-composer-context">
        <span className="cw-row">
          <Icon name="compass" />
          深度研究
        </span>
        <span>{thread.runs.length ? '可以继续补充研究要求' : '模型与 Skills 用于本次研究'}</span>
      </div>
      <form
        ref={form}
        className="cw-composer"
        aria-label="研究消息输入"
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
      >
        {state.config.skill !== 'auto' && (
          <div className="cw-skill-hint">
            <Icon name="layers" />
            <span className="cw-skill-hint-text">
              {skill.label} · {skill.description}
            </span>
            <button
              type="button"
              className="cw-skill-remove"
              aria-label="恢复自动选择 Skills"
              onClick={() => dispatch({ type: 'config', config: { skill: 'auto' } })}
            >
              <Icon name="x" />
            </button>
          </div>
        )}
        <label className="cw-sr-only" htmlFor="cw-message">
          研究问题或补充要求
        </label>
        <textarea
          id="cw-message"
          name="message"
          rows={3}
          maxLength={2000}
          value={thread.draft}
          placeholder={thread.runs.length ? '补充研究要求，或追问一个问题…' : '你想研究什么？'}
          aria-describedby="cw-composer-help"
          onChange={(e) => dispatch({ type: 'draft', text: e.target.value })}
          onCompositionStart={() => {
            composing.current = true
          }}
          onCompositionEnd={() => {
            composing.current = false
          }}
          onKeyDown={(e) => {
            if (
              e.key === 'Enter' &&
              !e.shiftKey &&
              !composing.current &&
              !e.nativeEvent.isComposing &&
              e.nativeEvent.keyCode !== 229
            ) {
              e.preventDefault()
              send()
            }
          }}
        />
        <div className="cw-composer-toolbar">
          <Picker
            name="model"
            label={modelName(state.config.model)}
            value={state.config.model}
            options={models}
            open={open === 'model'}
            onOpen={(yes) => setOpen(yes ? 'model' : null)}
            onChange={(id) => dispatch({ type: 'config', config: { model: id as ModelId } })}
          />
          <Picker
            name="skill"
            label={state.config.skill === 'auto' ? 'Skills' : `Skills · ${skill.label}`}
            value={state.config.skill}
            options={skills}
            open={open === 'skill'}
            onOpen={(yes) => setOpen(yes ? 'skill' : null)}
            onChange={(id) => dispatch({ type: 'config', config: { skill: id as SkillId } })}
          />
          <span className="cw-spacer" />
          <button
            type="submit"
            className="cw-send"
            aria-label="发送消息"
            disabled={!thread.draft.trim()}
          >
            <Icon name="up" />
          </button>
        </div>
      </form>
      <div className="cw-composer-hint" id="cw-composer-help">
        <span>Enter 发送 · Shift + Enter 换行</span>
        <span>本地模拟 · 未连接后端</span>
      </div>
    </div>
  )
}
