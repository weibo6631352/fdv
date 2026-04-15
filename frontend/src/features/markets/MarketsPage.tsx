import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { adminApi } from '../../core/api/resources'
import type { MarketView } from '../../core/api/types'
import { SectionCard } from '../../shared/ui/SectionCard'
import { DataTable, type DataColumn } from '../../shared/ui/DataTable'
import { StatusPill } from '../../shared/ui/StatusPill'
import { formatDateTime, formatDecimal, formatJson, formatList, getString } from '../../shared/utils/format'
import { resolveStrategyExtension } from '../../strategy/registry'

const tradingStatusTone = (status: string): 'neutral' | 'success' | 'warning' | 'danger' => {
  if (status === 'active') {
    return 'success'
  }
  if (status === 'paused') {
    return 'warning'
  }
  if (status === 'closed' || status === 'resolved' || status === 'rejected') {
    return 'danger'
  }
  return 'neutral'
}

export const MarketsPage = () => {
  const [search, setSearch] = useState('')
  const [tradingStatus, setTradingStatus] = useState('')
  const [feesEnabled, setFeesEnabled] = useState('all')
  const [sortBy, setSortBy] = useState('fee_rate_updated_at')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')
  const [offset, setOffset] = useState(0)
  const [selectedTokenId, setSelectedTokenId] = useState<string | null>(null)

  const runtimeQuery = useQuery({
    queryKey: ['runtime', 'markets'],
    queryFn: adminApi.getRuntime,
    refetchInterval: 20_000,
  })

  const marketsQuery = useQuery({
    queryKey: ['markets', { tradingStatus, feesEnabled, sortBy, sortDirection, offset }],
    queryFn: () =>
      adminApi.listMarkets({
        limit: 50,
        offset,
        trading_status: tradingStatus || undefined,
        fees_enabled: feesEnabled === 'all' ? undefined : feesEnabled === 'true',
        sort_by: sortBy || undefined,
        sort_direction: sortDirection,
      }),
    refetchInterval: 20_000,
  })

  const strategyExtension = useMemo(
    () => resolveStrategyExtension(getString(runtimeQuery.data?.settings?.strategy_module)),
    [runtimeQuery.data],
  )

  const filteredMarkets = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    if (!keyword) {
      return marketsQuery.data?.items ?? []
    }
    return (marketsQuery.data?.items ?? []).filter((item) => {
      const haystacks = [
        item.market.market_slug,
        item.market.event_title,
        item.market.event_slug,
        item.market.condition_id,
      ]
      return haystacks.some((value) => value?.toLowerCase().includes(keyword))
    })
  }, [marketsQuery.data, search])

  const activeTokenId =
    selectedTokenId && filteredMarkets.some((item) => item.market.no_token_id === selectedTokenId)
      ? selectedTokenId
      : filteredMarkets[0]?.market.no_token_id ?? null

  const selectedMarket = filteredMarkets.find((item) => item.market.no_token_id === activeTokenId) ?? null

  const detailQuery = useQuery({
    queryKey: ['market-detail', activeTokenId],
    queryFn: () => adminApi.getMarketDetail({ token_id: activeTokenId }),
    enabled: Boolean(activeTokenId),
  })
  const orderbookQuery = useQuery({
    queryKey: ['market-orderbook', activeTokenId],
    queryFn: () => adminApi.getMarketOrderbook({ token_id: activeTokenId }),
    enabled: Boolean(activeTokenId),
  })
  const midpointQuery = useQuery({
    queryKey: ['market-midpoint', activeTokenId],
    queryFn: () => adminApi.getMarketMidpoint({ token_id: activeTokenId }),
    enabled: Boolean(activeTokenId),
  })
  const historyQuery = useQuery({
    queryKey: ['market-history', activeTokenId],
    queryFn: () =>
      adminApi.getMarketPricesHistory({
        token_id: activeTokenId,
        interval: '1d',
        fidelity: 60,
      }),
    enabled: Boolean(activeTokenId),
  })

  const columns: Array<DataColumn<MarketView>> = [
    {
      key: 'market',
      header: '市场',
      cell: (row) => (
        <div className="table-primary">
          <strong>{row.market.event_title ?? row.market.market_slug}</strong>
          <span>{row.market.market_slug}</span>
        </div>
      ),
    },
    {
      key: 'status',
      header: '状态',
      cell: (row) => (
        <div className="badge-row">
          <StatusPill label={row.market.trading_status} tone={tradingStatusTone(row.market.trading_status)} />
          {row.tracked ? <StatusPill label="tracked" tone="success" /> : null}
        </div>
      ),
    },
    {
      key: 'strategy',
      header: '策略标签',
      cell: (row) => (
        <div className="badge-row">
          {strategyExtension.renderMarketBadges?.(row).map((badge) => (
            <StatusPill key={badge.label} label={badge.label} tone={badge.tone} />
          )) ?? '—'}
        </div>
      ),
    },
    {
      key: 'spread',
      header: 'spread',
      align: 'right',
      cell: (row) => formatDecimal(row.spread),
    },
    {
      key: 'fee',
      header: '费率 bps',
      align: 'right',
      cell: (row) => formatDecimal(row.market.fees.fee_rate_bps),
    },
    {
      key: 'position',
      header: '持仓 shares',
      align: 'right',
      cell: (row) => formatDecimal(row.position?.shares),
    },
    {
      key: 'orders',
      header: '挂单数',
      align: 'right',
      cell: (row) => row.open_order_count,
    },
  ]

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">市场</p>
          <h1>通用 market 视图 + 策略解释槽</h1>
          <p>列表、盘口、中间价和历史价格是通用能力，策略标签只通过扩展模块附加。</p>
        </div>
      </header>

      <SectionCard title="筛选" subtitle="服务端负责费率与状态过滤，文本检索在当前页内完成。">
        <div className="form-grid form-grid--filters">
          <label>
            <span>文本检索</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="slug / event / condition" />
          </label>
          <label>
            <span>trading_status</span>
            <select value={tradingStatus} onChange={(event) => setTradingStatus(event.target.value)}>
              <option value="">全部</option>
              <option value="active">active</option>
              <option value="paused">paused</option>
              <option value="closed">closed</option>
              <option value="resolved">resolved</option>
              <option value="rejected">rejected</option>
            </select>
          </label>
          <label>
            <span>fees_enabled</span>
            <select value={feesEnabled} onChange={(event) => setFeesEnabled(event.target.value)}>
              <option value="all">全部</option>
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          </label>
          <label>
            <span>sort_by</span>
            <select value={sortBy} onChange={(event) => setSortBy(event.target.value)}>
              <option value="fee_rate_updated_at">fee_rate_updated_at</option>
              <option value="market_slug">market_slug</option>
              <option value="fee_rate_bps">fee_rate_bps</option>
              <option value="maker_base_fee_bps">maker_base_fee_bps</option>
              <option value="taker_base_fee_bps">taker_base_fee_bps</option>
            </select>
          </label>
          <label>
            <span>sort_direction</span>
            <select value={sortDirection} onChange={(event) => setSortDirection(event.target.value as 'asc' | 'desc')}>
              <option value="desc">desc</option>
              <option value="asc">asc</option>
            </select>
          </label>
        </div>
      </SectionCard>

      <div className="content-grid content-grid--wide-aside">
        <SectionCard
          title="市场列表"
          subtitle={`当前页 ${filteredMarkets.length} 条，本轮服务端 total ${marketsQuery.data?.total ?? 0}。`}
          actions={
            <div className="inline-actions">
              <button type="button" onClick={() => setOffset((current) => Math.max(0, current - 50))} disabled={offset === 0}>
                上一页
              </button>
              <button
                type="button"
                onClick={() => setOffset((current) => current + 50)}
                disabled={(marketsQuery.data?.items.length ?? 0) < 50}
              >
                下一页
              </button>
            </div>
          }
        >
          <DataTable
            columns={columns}
            rows={filteredMarkets}
            rowKey={(row) => row.market.no_token_id}
            emptyTitle="没有 market"
            emptyDescription="调整筛选条件后重试。"
            onRowClick={(row) => setSelectedTokenId(row.market.no_token_id)}
            selectedRowKey={activeTokenId}
          />
        </SectionCard>

        <div className="detail-stack">
          <SectionCard title="市场详情" subtitle="详情、盘口和历史曲线都围绕当前选择的 market。">
            {selectedMarket ? (
              <div className="detail-list">
                <div>
                  <dt>event_title</dt>
                  <dd>{detailQuery.data?.market.event_title ?? selectedMarket.market.event_title ?? '—'}</dd>
                </div>
                <div>
                  <dt>market_slug</dt>
                  <dd>{selectedMarket.market.market_slug}</dd>
                </div>
                <div>
                  <dt>matched_keywords</dt>
                  <dd>{formatList(selectedMarket.market.matched_keywords)}</dd>
                </div>
                <div>
                  <dt>tags</dt>
                  <dd>{formatList(selectedMarket.market.tags)}</dd>
                </div>
              </div>
            ) : (
              <p className="muted">先从左侧选择一个 market。</p>
            )}
          </SectionCard>

          <SectionCard title="盘口与中间价" subtitle="优先展示 hot snapshot。">
            <div className="detail-list">
              <div>
                <dt>midpoint</dt>
                <dd>{formatDecimal(midpointQuery.data?.midpoint)}</dd>
              </div>
              <div>
                <dt>best bid / ask</dt>
                <dd>
                  {formatDecimal(midpointQuery.data?.best_bid)} / {formatDecimal(midpointQuery.data?.best_ask)}
                </dd>
              </div>
              <div>
                <dt>spread</dt>
                <dd>{formatDecimal(midpointQuery.data?.spread)}</dd>
              </div>
              <div>
                <dt>received_at</dt>
                <dd>{formatDateTime(midpointQuery.data?.received_at)}</dd>
              </div>
            </div>
            {orderbookQuery.data?.orderbook ? (
              <div className="depth-grid">
                <div>
                  <h3>bids</h3>
                  <ul className="depth-list">
                    {orderbookQuery.data.orderbook.bids.slice(0, 5).map((level, index) => (
                      <li key={`bid-${index}`}>
                        <span>{formatDecimal(level.price)}</span>
                        <span>{formatDecimal(level.size)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3>asks</h3>
                  <ul className="depth-list">
                    {orderbookQuery.data.orderbook.asks.slice(0, 5).map((level, index) => (
                      <li key={`ask-${index}`}>
                        <span>{formatDecimal(level.price)}</span>
                        <span>{formatDecimal(level.size)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : null}
          </SectionCard>

          <SectionCard title="价格历史" subtitle="`/markets/prices-history` 默认拉取 1d / fidelity 60。">
            {historyQuery.data && historyQuery.data.history.length > 0 ? (
              <div className="chart-wrap">
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={historyQuery.data.history}>
                    <XAxis
                      dataKey="timestamp"
                      tickFormatter={(value: string) => formatDateTime(value)}
                      minTickGap={24}
                    />
                    <YAxis />
                    <Tooltip
                      formatter={(value) =>
                        formatDecimal(Array.isArray(value) ? value[0] : value ?? undefined)
                      }
                      labelFormatter={(value) =>
                        typeof value === 'string' ? formatDateTime(value) : String(value ?? '—')
                      }
                    />
                    <Line type="monotone" dataKey="price" stroke="#0f766e" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <p className="muted">当前没有可展示的价格历史。</p>
            )}
          </SectionCard>

          {selectedMarket ? strategyExtension.renderMarketDetail?.(selectedMarket) : null}

          {selectedMarket ? (
            <SectionCard title="原始快照" subtitle="必要时直接看当前 market view。">
              <pre className="json-block">
                {formatJson(detailQuery.data ?? selectedMarket)}
              </pre>
            </SectionCard>
          ) : null}
        </div>
      </div>
    </div>
  )
}
