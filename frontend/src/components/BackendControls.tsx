import type { BackendConfig } from '../data/liveSchema'
import { roleLabels } from '../data/live'
import { Icon } from './Icon'

export function BackendControls({
  config,
  open,
  onOpen,
}: {
  config?: BackendConfig
  open: boolean
  onOpen: (open: boolean) => void
}) {
  const model = config?.models.find((item) => item.role === 'RESEARCHER')?.model
  return (
    <>
      <div className="cw-picker">
        <button
          type="button"
          id="cw-model"
          className="cw-picker-trigger"
          aria-label="查看后端模型"
          aria-expanded={open}
          aria-controls="cw-backend-models"
          onClick={() => onOpen(!open)}
        >
          <span className="cw-picker-trigger-label">{model || '后端模型'}</span>
          <Icon name="chevron" />
        </button>
        {open && (
          <div
            className="cw-picker-menu cw-backend-models"
            id="cw-backend-models"
            role="region"
            aria-label="后端实际配置"
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault()
                onOpen(false)
                document.getElementById('cw-model')?.focus()
              }
            }}
          >
            <div className="cw-menu-heading">当前服务配置</div>
            {config?.models.map((item) => (
              <div key={item.role} className="cw-backend-role">
                <span>{roleLabels[item.role] ?? item.role}</span>
                <strong>{item.model}</strong>
              </div>
            ))}
            <p>模型由后端配置。Skills 根据研究任务自动加载。</p>
            <p>本轮暂不支持按次切换模型或手选 Skills。</p>
          </div>
        )}
      </div>
      <span className="cw-picker-trigger cw-fixed-skill" title="由后端研究员按需自动加载方法论">
        <Icon name="layers" />
        <span>Skills · 自动</span>
      </span>
    </>
  )
}
