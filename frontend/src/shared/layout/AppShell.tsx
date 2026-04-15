import type { ReactNode } from 'react'
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { NavLink } from 'react-router-dom'
import { adminApi } from '../../core/api/resources'
import { getString } from '../utils/format'
import { StatusPill } from '../ui/StatusPill'

interface AppShellProps {
  children: ReactNode
}

const navigation = [
  { to: '/', label: '总览' },
  { to: '/markets', label: '市场' },
  { to: '/orders', label: '订单' },
  { to: '/positions', label: '持仓' },
  { to: '/audit', label: '审计' },
  { to: '/operations', label: '操作' },
]

const statusTone = (ready: boolean, phase: string | undefined): 'success' | 'warning' | 'danger' | 'neutral' => {
  if (ready) {
    return 'success'
  }
  if (phase === 'degraded' || phase === 'recovering_snapshot') {
    return 'warning'
  }
  if (phase === 'paused' || phase === 'starting') {
    return 'danger'
  }
  return 'neutral'
}

export const AppShell = ({ children }: AppShellProps) => {
  const readyQuery = useQuery({
    queryKey: ['ready'],
    queryFn: adminApi.getReady,
    refetchInterval: 10_000,
  })
  const runtimeQuery = useQuery({
    queryKey: ['runtime', 'shell'],
    queryFn: adminApi.getRuntime,
    refetchInterval: 20_000,
  })

  const strategyModule = useMemo(
    () => getString(runtimeQuery.data?.settings?.strategy_module) ?? 'unknown',
    [runtimeQuery.data],
  )

  const ready = readyQuery.data?.ready_to_trade ?? false
  const phase = readyQuery.data?.phase ?? runtimeQuery.data?.phase ?? 'starting'

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="brand-block">
          <p className="eyebrow">Polymarket Trader</p>
          <h1>运行台</h1>
          <div className="brand-block__meta">
            <StatusPill label={ready ? '允许自动交易' : '自动交易未就绪'} tone={statusTone(ready, phase)} />
            <span>{strategyModule}</span>
          </div>
        </div>

        <nav className="nav-list" aria-label="主导航">
          {navigation.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => `nav-item${isActive ? ' is-active' : ''}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <p>所有动作先过后端应用服务。</p>
          <p>策略展示通过扩展注册表挂接。</p>
        </div>
      </aside>

      <div className="app-content">
        <header className="top-banner">
          <div className="top-banner__overlay" />
          <div className="top-banner__content">
            <p className="eyebrow">同一套通用壳体，分开承载策略扩展</p>
            <h2>运行态、市场、订单和修复操作统一收口</h2>
            <div className="top-banner__meta">
              <StatusPill label={`phase: ${phase}`} tone={statusTone(ready, phase)} />
              <span>readiness 每 10 秒刷新</span>
            </div>
          </div>
        </header>
        <main className="page-container">{children}</main>
      </div>
    </div>
  )
}
