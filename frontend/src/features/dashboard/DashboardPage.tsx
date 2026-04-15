import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../../core/api/resources'
import { SectionCard } from '../../shared/ui/SectionCard'
import { StatusPill } from '../../shared/ui/StatusPill'
import { formatCompact, formatDateTime, formatDecimal, formatJson, getString } from '../../shared/utils/format'
import { resolveStrategyExtension } from '../../strategy/registry'

const boolTone = (value: boolean): 'success' | 'danger' => (value ? 'success' : 'danger')

export const DashboardPage = () => {
  const readyQuery = useQuery({
    queryKey: ['ready', 'dashboard'],
    queryFn: adminApi.getReady,
    refetchInterval: 10_000,
  })
  const runtimeQuery = useQuery({
    queryKey: ['runtime', 'dashboard'],
    queryFn: adminApi.getRuntime,
    refetchInterval: 15_000,
  })
  const workersQuery = useQuery({
    queryKey: ['workers'],
    queryFn: adminApi.getWorkers,
    refetchInterval: 15_000,
  })
  const metricsQuery = useQuery({
    queryKey: ['metrics'],
    queryFn: adminApi.getMetrics,
    refetchInterval: 15_000,
  })
  const portfolioQuery = useQuery({
    queryKey: ['portfolio'],
    queryFn: adminApi.getPortfolio,
    refetchInterval: 10_000,
  })
  const marketsQuery = useQuery({
    queryKey: ['markets', 'dashboard'],
    queryFn: () => adminApi.listMarkets({ limit: 100, offset: 0 }),
    refetchInterval: 20_000,
  })

  const strategyModule = getString(runtimeQuery.data?.settings?.strategy_module)
  const strategyExtension = useMemo(() => resolveStrategyExtension(strategyModule), [strategyModule])

  const blockingIssues = readyQuery.data?.blocking_issues ?? []
  const warnings = readyQuery.data?.warnings ?? []
  const recentAllocations = portfolioQuery.data?.recent_allocations ?? []
  const workers = workersQuery.data?.workers ?? []

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">总览</p>
          <h1>运行态与资金闸门</h1>
          <p>所有读操作都来自 Admin API，策略解释通过独立扩展模块挂接。</p>
        </div>
      </header>

      <section className="stats-grid">
        <div className="stat-card">
          <span>readiness</span>
          <strong>{readyQuery.data?.ready_to_trade ? 'ready' : 'blocked'}</strong>
          <StatusPill
            label={readyQuery.data?.phase ?? 'starting'}
            tone={readyQuery.data?.ready_to_trade ? 'success' : 'danger'}
          />
        </div>
        <div className="stat-card">
          <span>组合余额</span>
          <strong>{formatCompact(portfolioQuery.data?.balance_usdc)}</strong>
          <small>allowance {formatCompact(portfolioQuery.data?.allowance_usdc)}</small>
        </div>
        <div className="stat-card">
          <span>跟踪 market</span>
          <strong>{runtimeQuery.data?.registry.market_count ?? 0}</strong>
          <small>phase {runtimeQuery.data?.phase ?? 'starting'}</small>
        </div>
        <div className="stat-card">
          <span>持仓 / 挂单</span>
          <strong>
            {portfolioQuery.data?.position_count ?? 0} / {portfolioQuery.data?.open_order_count ?? 0}
          </strong>
          <small>fills {portfolioQuery.data?.fill_count ?? 0}</small>
        </div>
      </section>

      <div className="content-grid content-grid--two">
        <SectionCard title="交易闸门" subtitle="自动交易是否允许，先看这四项。">
          <div className="detail-list">
            <div>
              <dt>ready_to_trade</dt>
              <dd>
                <StatusPill
                  label={readyQuery.data?.ready_to_trade ? '允许' : '阻塞'}
                  tone={readyQuery.data?.ready_to_trade ? 'success' : 'danger'}
                />
              </dd>
            </div>
            <div>
              <dt>User WS</dt>
              <dd>
                <StatusPill
                  label={readyQuery.data?.runtime.user_ws_connected ? '已连接' : '未连接'}
                  tone={boolTone(readyQuery.data?.runtime.user_ws_connected ?? false)}
                />
              </dd>
            </div>
            <div>
              <dt>allow_new_buys</dt>
              <dd>
                <StatusPill
                  label={readyQuery.data?.runtime.allow_new_buys ? '打开' : '关闭'}
                  tone={boolTone(readyQuery.data?.runtime.allow_new_buys ?? false)}
                />
              </dd>
            </div>
            <div>
              <dt>last_reconcile_at</dt>
              <dd>{formatDateTime(readyQuery.data?.runtime.last_reconcile_at)}</dd>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="阻塞与告警" subtitle="这里优先显示真正阻止自动交易的原因。">
          {blockingIssues.length > 0 ? (
            <ul className="message-list">
              {blockingIssues.map((issue, index) => (
                <li key={`${issue.field}-${issue.code}-${index}`}>
                  <strong>{issue.field}</strong>
                  <span>{issue.message}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">当前没有阻塞项。</p>
          )}
          {warnings.length > 0 ? (
            <ul className="message-list is-warning">
              {warnings.map((issue, index) => (
                <li key={`${issue.field}-${issue.code}-${index}`}>
                  <strong>{issue.field}</strong>
                  <span>{issue.message}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </SectionCard>
      </div>

      <div className="content-grid content-grid--two">
        <SectionCard title="Worker 摘要" subtitle="运行态与调度信息从 `/workers` 聚合。">
          <div className="detail-list">
            <div>
              <dt>phase</dt>
              <dd>{workersQuery.data?.phase ?? '—'}</dd>
            </div>
            <div>
              <dt>automatic_trading_enabled</dt>
              <dd>{workersQuery.data?.automatic_trading_enabled ? '是' : '否'}</dd>
            </div>
            <div>
              <dt>worker 数量</dt>
              <dd>{workers.length}</dd>
            </div>
            <div>
              <dt>status_reason</dt>
              <dd>{workersQuery.data?.status_reason ?? '—'}</dd>
            </div>
          </div>
          {workers.length > 0 ? (
            <div className="inline-badge-list">
              {workers.map((worker, index) => (
                <StatusPill
                  key={`${worker.name ?? worker.worker_name ?? 'worker'}-${index}`}
                  label={`${worker.name ?? worker.worker_name ?? `worker-${index + 1}`}: ${worker.status ?? 'unknown'}`}
                  tone={worker.status === 'healthy' ? 'success' : 'warning'}
                />
              ))}
            </div>
          ) : null}
        </SectionCard>

        <SectionCard title="指标与队列" subtitle="先看快照，不在前端重写指标语义。">
          <pre className="json-block">{formatJson(metricsQuery.data?.metrics ?? metricsQuery.data?.queue_depths)}</pre>
        </SectionCard>
      </div>

      {strategyExtension.renderDashboard?.({
        ready: readyQuery.data,
        runtime: runtimeQuery.data,
        portfolio: portfolioQuery.data,
        markets: marketsQuery.data?.items ?? [],
      })}

      <div className="content-grid content-grid--two">
        <SectionCard title="近期分配" subtitle="组合与分配记录来自 `/portfolio`。">
          {recentAllocations.length > 0 ? (
            <div className="detail-list">
              {recentAllocations.slice(0, 6).map((allocation) => (
                <div key={allocation.idempotency_key ?? allocation.condition_id}>
                  <dt>{allocation.market_slug ?? allocation.condition_id}</dt>
                  <dd>
                    target {formatDecimal(allocation.target_budget_usdc)} / exposure{' '}
                    {formatDecimal(allocation.current_exposure_usdc)}
                  </dd>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">当前没有 recent allocations。</p>
          )}
        </SectionCard>

        <SectionCard title="配置摘要" subtitle="这里只显示已脱敏 settings。">
          <pre className="json-block">{formatJson(runtimeQuery.data?.settings ?? {})}</pre>
        </SectionCard>
      </div>
    </div>
  )
}
