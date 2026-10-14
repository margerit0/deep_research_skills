import { useEffect, useRef } from 'react'
import type { WorkspaceController } from '../state/useWorkspace'
import { Icon } from './Icon'

const time = (ms: number) =>
  `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`

export function DemoPlayer({ controller }: { controller: WorkspaceController }) {
  const { demo } = controller
  const play = useRef<HTMLButtonElement>(null)
  const timeline = useRef<HTMLDivElement>(null)
  useEffect(() => {
    play.current?.focus({ preventScroll: true })
  }, [])
  // Follow scene changes, never move keyboard focus away from the player.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const selector = {
        composer: '.cw-composer-wrap',
        message: '.cw-message-pair',
        inspector: '#cw-inspector',
        graph: '.cw-flow',
        report: '.cw-report-message',
      }[demo.scene.target]
      const recordedSelectors: Record<string, string> = {
        'record-question': '[data-recording] .cw-user-message',
        'record-clarification': '[data-recording] .cw-agent-message',
        'record-answer': '[data-recording] .cw-user-message',
        'record-brief': '[data-testid="recorded-brief"]',
        'record-research': '.cw-flow',
        'record-result': '[data-testid="recorded-status"]',
      }
      const element = demo.recording
        ? Array.from(document.querySelectorAll(recordedSelectors[demo.scene.id] ?? selector)).at(-1)
        : document.querySelector(selector)
      const behavior = demo.reducedMotion ? 'instant' : 'smooth'
      if (element && matchMedia('(max-width:660px)').matches && demo.scene.target !== 'composer') {
        const playerHeight = document
          .querySelector('.cw-demo-player')!
          .getBoundingClientRect().height
        window.scrollTo({
          top: window.scrollY + element.getBoundingClientRect().top - playerHeight - 24,
          behavior,
        })
      } else {
        element?.scrollIntoView({
          block: demo.scene.target === 'composer' ? 'end' : 'nearest',
          behavior,
        })
      }
      const chapters = timeline.current
      const active = chapters?.children[demo.index] as HTMLElement | undefined
      if (active && chapters)
        chapters.scrollTo({
          left: active.offsetLeft - chapters.clientWidth / 2 + active.clientWidth / 2,
          behavior,
        })
    }, 180)
    return () => clearTimeout(timer)
  }, [demo.index, demo.scene.id, demo.scene.target, demo.reducedMotion, demo.recording?.id])
  return (
    <section className="cw-demo-player" aria-label="全流程演示控制" data-scene={demo.scene.id}>
      <label className="cw-demo-source">
        数据来源
        <select
          aria-label="演示数据来源"
          value={demo.recording?.id ?? 'simulated'}
          onChange={(event) => demo.chooseRecording(event.target.value)}
        >
          <option value="simulated">完整模拟流程</option>
          {demo.recordings.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <div className="cw-demo-caption" aria-live="polite" aria-atomic="true">
        <span className="cw-demo-kicker">
          {demo.recording ? '真实记录回放' : '全流程演示'} ·{' '}
          {demo.done ? '已结束' : demo.playing ? '播放中' : '已暂停'}
        </span>
        <strong>
          {String(demo.index + 1).padStart(2, '0')} / {demo.scenes.length} · {demo.scene.title}
        </strong>
        <span>{demo.scene.detail}</span>
      </div>
      <div className="cw-demo-actions">
        <button
          type="button"
          className="cw-quiet"
          aria-label="上一幕"
          disabled={demo.index === 0}
          onClick={() => demo.seek(demo.index - 1)}
        >
          <Icon name="previous" />
        </button>
        <button
          ref={play}
          type="button"
          className="cw-demo-play"
          onClick={demo.done ? demo.replay : demo.toggle}
          aria-label={demo.done ? '重播全流程演示' : demo.playing ? '暂停演示' : '继续演示'}
        >
          <Icon name={demo.done ? 'reset' : demo.playing ? 'pause' : 'play'} />
          {demo.done ? '重播' : demo.playing ? '暂停' : '继续'}
        </button>
        <button
          type="button"
          className="cw-quiet"
          aria-label="下一幕"
          disabled={demo.index === demo.scenes.length - 1}
          onClick={() => demo.seek(demo.index + 1)}
        >
          <Icon name="step" />
        </button>
        <button
          type="button"
          className="cw-quiet cw-demo-speed"
          aria-label={`播放速度 ${demo.speed} 倍，点击切换`}
          onClick={() => demo.setSpeed(demo.speed === 1 ? 1.5 : demo.speed === 1.5 ? 2 : 1)}
        >
          {demo.speed}×
        </button>
        {!demo.done && (
          <button
            type="button"
            className="cw-quiet"
            aria-label="从头重播演示"
            onClick={demo.replay}
          >
            <Icon name="reset" />
          </button>
        )}
        <button
          type="button"
          className="cw-quiet"
          onClick={() => {
            demo.exit()
            requestAnimationFrame(() => document.getElementById('demo-start')?.focus())
          }}
        >
          退出
        </button>
      </div>
      <div
        ref={timeline}
        className="cw-demo-timeline"
        aria-label="演示章节"
        style={{ gridTemplateColumns: `repeat(${demo.scenes.length}, minmax(0, 1fr))` }}
      >
        {demo.scenes.map((scene, index) => (
          <button
            type="button"
            key={scene.id}
            aria-label={`跳转：${scene.title}`}
            aria-current={index === demo.index ? 'step' : undefined}
            title={scene.title}
            onClick={() => demo.seek(index)}
          >
            <span>
              <i
                style={{
                  transform: `scaleX(${index < demo.index ? 1 : index === demo.index ? demo.progress : 0})`,
                }}
              />
            </span>
          </button>
        ))}
      </div>
      <div className="cw-demo-footnote">
        <span>
          {demo.recordingLoadError ? '真实记录暂时不可用 · ' : ''}
          {demo.reducedMotion ? '已遵循减少动态效果偏好 · ' : ''}
          {demo.recording
            ? '真实记录 · 时间已压缩 · 不重新执行'
            : '独立模拟 · 点击节点或菜单会暂停'}{' '}
          · 退出恢复原会话
        </span>
        <span className="cw-mono">
          {time(demo.elapsed)} / {time(demo.duration)}
        </span>
      </div>
    </section>
  )
}
