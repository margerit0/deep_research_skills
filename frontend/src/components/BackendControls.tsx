import type { BackendConfig, RunSelection } from '../data/liveSchema'
import { roleLabels } from '../data/live'
import { Icon } from './Icon'

export function BackendControls({
  config,
  open,
  onOpen,
  selection,
  locked = false,
  skillOpen = false,
  onSkillOpen,
  onChange,
}: {
  config?: BackendConfig
  open: boolean
  onOpen: (open: boolean) => void
  selection?: RunSelection
  locked?: boolean
  skillOpen?: boolean
  onSkillOpen?: (open: boolean) => void
  onChange?: (selection: RunSelection) => void
}) {
  const catalog = config?.catalog
  const selectable =
    !!catalog && config?.configuration_version === 1 && config?.submission_recovery_version === 1
  const chosen =
    selection ??
    (catalog
      ? {
          version: 1 as const,
          models: catalog.defaults,
          skills: { mode: 'auto' as const, allowed: [] },
        }
      : undefined)
  const selectedModel = catalog?.models.find((item) => item.id === chosen?.models.RESEARCHER)?.model
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
          <span className="cw-picker-trigger-label">{selectedModel || model || '后端模型'}</span>
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
            <div className="cw-menu-heading">
              {selectable ? (locked ? '本轮配置 · 已锁定' : '本次研究模型') : '当前服务配置'}
            </div>
            {selectable && chosen
              ? Object.entries(roleLabels).map(([role, label]) => (
                  <label key={role} className="cw-config-role">
                    <span>{label}</span>
                    <select
                      aria-label={`${label}模型`}
                      value={chosen.models[role]}
                      disabled={locked}
                      onChange={(event) =>
                        onChange?.({
                          ...chosen,
                          models: { ...chosen.models, [role]: event.target.value },
                        })
                      }
                    >
                      {!catalog.models.some((item) => item.id === chosen.models[role]) && (
                        <option value={chosen.models[role]}>
                          历史配置 · {config?.models.find((item) => item.role === role)?.model}
                        </option>
                      )}
                      {catalog.models.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.model}
                          {item.max_tokens ? ` · ${item.max_tokens} tokens` : ''} · {item.provider}
                        </option>
                      ))}
                    </select>
                  </label>
                ))
              : config?.models.map((item) => (
                  <div key={item.role} className="cw-backend-role">
                    <span>{roleLabels[item.role] ?? item.role}</span>
                    <strong>{item.model}</strong>
                  </div>
                ))}
            {selectable ? (
              <p>
                {locked
                  ? '澄清、重试与恢复沿用本轮配置。'
                  : '发送后固定本轮配置，下一轮可重新选择。'}
              </p>
            ) : (
              <>
                <p>模型由后端配置。Skills 根据研究任务自动加载。</p>
                <p>本轮暂不支持按次切换模型或手选 Skills。</p>
              </>
            )}
          </div>
        )}
      </div>
      {selectable && chosen ? (
        <div className="cw-picker">
          <button
            type="button"
            id="cw-live-skills"
            className="cw-picker-trigger"
            aria-label="配置 Skills 允许集合"
            aria-expanded={skillOpen}
            aria-controls="cw-live-skills-menu"
            onClick={() => onSkillOpen?.(!skillOpen)}
          >
            <Icon name="layers" />
            <span>
              Skills ·{' '}
              {chosen.skills.mode === 'auto' ? '自动' : `允许 ${chosen.skills.allowed.length} 项`}
            </span>
            <Icon name="chevron" />
          </button>
          {skillOpen && (
            <div
              id="cw-live-skills-menu"
              className="cw-picker-menu cw-backend-models"
              role="region"
              aria-label="Skills 允许集合"
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  event.preventDefault()
                  onSkillOpen?.(false)
                  document.getElementById('cw-live-skills')?.focus()
                }
              }}
            >
              <div className="cw-menu-heading">
                {locked ? '本轮 Skills · 已锁定' : '允许自动加载的 Skills'}
              </div>
              <label className="cw-config-check">
                <input
                  type="checkbox"
                  checked={chosen.skills.mode === 'auto'}
                  disabled={locked}
                  onChange={(event) =>
                    onChange?.({
                      ...chosen,
                      skills: { mode: event.target.checked ? 'auto' : 'manual', allowed: [] },
                    })
                  }
                />
                自动 · 全部可用
              </label>
              {catalog.skills.map((item) => (
                <label key={item.name} className="cw-config-check" title={item.description}>
                  <input
                    type="checkbox"
                    disabled={locked || chosen.skills.mode === 'auto'}
                    checked={
                      chosen.skills.mode === 'auto' || chosen.skills.allowed.includes(item.name)
                    }
                    onChange={(event) =>
                      onChange?.({
                        ...chosen,
                        skills: {
                          mode: 'manual',
                          allowed: (event.target.checked
                            ? [...chosen.skills.allowed, item.name]
                            : chosen.skills.allowed.filter((name) => name !== item.name)
                          ).sort(),
                        },
                      })
                    }
                  />
                  <span>{item.name}</span>
                </label>
              ))}
              <p>
                手选集合限定允许加载的方法论；实际加载情况见研究员执行记录。空集合表示不加载
                Skills。
              </p>
            </div>
          )}
        </div>
      ) : (
        <span className="cw-picker-trigger cw-fixed-skill" title="由后端研究员按需自动加载方法论">
          <Icon name="layers" />
          <span>Skills · 自动</span>
        </span>
      )}
    </>
  )
}
