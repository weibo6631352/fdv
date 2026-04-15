import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '../../core/api/resources'
import type { OrderRecord } from '../../core/api/types'
import { SectionCard } from '../../shared/ui/SectionCard'
import { DataTable, type DataColumn } from '../../shared/ui/DataTable'
import { StatusPill } from '../../shared/ui/StatusPill'
import { formatDateTime, formatDecimal, formatJson } from '../../shared/utils/format'

const orderTone = (status: string): 'neutral' | 'success' | 'warning' | 'danger' => {
  if (status === 'matched' || status === 'partially_filled') {
    return 'success'
  }
  if (status === 'live' || status === 'placed') {
    return 'warning'
  }
  if (status === 'failed' || status === 'rejected' || status === 'cancelled') {
    return 'danger'
  }
  return 'neutral'
}

export const OrdersPage = () => {
  const queryClient = useQueryClient()
  const [openOnly, setOpenOnly] = useState(true)
  const [conditionId, setConditionId] = useState('')
  const [tokenId, setTokenId] = useState('')
  const [traceId, setTraceId] = useState('')
  const [offset, setOffset] = useState(0)
  const [selectedOrder, setSelectedOrder] = useState<OrderRecord | null>(null)
  const [marketSlug, setMarketSlug] = useState('')
  const [manualTokenId, setManualTokenId] = useState('')
  const [newPrice, setNewPrice] = useState('0.62')
  const [operator, setOperator] = useState('manual')

  const ordersQuery = useQuery({
    queryKey: ['orders', { openOnly, conditionId, tokenId, traceId, offset }],
    queryFn: () =>
      adminApi.listOrders({
        limit: 50,
        offset,
        open_only: openOnly,
        condition_id: conditionId || undefined,
        token_id: tokenId || undefined,
        trace_id: traceId || undefined,
      }),
    refetchInterval: openOnly ? 10_000 : 20_000,
  })

  const cancelReplaceMutation = useMutation({
    mutationFn: () =>
      adminApi.cancelReplaceSell({
        market_slug: marketSlug || undefined,
        token_id: manualTokenId || undefined,
        new_price: newPrice,
        operator,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['orders'] }),
        queryClient.invalidateQueries({ queryKey: ['markets'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio'] }),
      ])
    },
  })

  const columns: Array<DataColumn<OrderRecord>> = useMemo(
    () => [
      {
        key: 'market',
        header: '市场',
        cell: (row) => (
          <div className="table-primary">
            <strong>{row.market_slug ?? row.condition_id}</strong>
            <span>{row.token_id}</span>
          </div>
        ),
      },
      {
        key: 'side',
        header: '方向',
        cell: (row) => (
          <div className="badge-row">
            <StatusPill label={row.side} tone={row.side === 'sell' ? 'warning' : 'neutral'} />
            <StatusPill label={row.status} tone={orderTone(row.status)} />
          </div>
        ),
      },
      {
        key: 'price',
        header: '价格 / 数量',
        cell: (row) => (
          <div className="table-primary">
            <strong>{formatDecimal(row.price)}</strong>
            <span>{formatDecimal(row.size_shares)} shares</span>
          </div>
        ),
      },
      {
        key: 'filled',
        header: 'filled',
        align: 'right',
        cell: (row) => formatDecimal(row.filled_shares),
      },
      {
        key: 'trace',
        header: 'trace',
        cell: (row) => row.trace_id ?? '—',
      },
      {
        key: 'updated',
        header: 'updated_at',
        cell: (row) => formatDateTime(row.updated_at),
      },
    ],
    [],
  )

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">订单</p>
          <h1>通用订单查询与人工卖出修复</h1>
          <p>浏览订单和触发 cancel / replace sell 都通过统一应用服务，不让前端直接改交易状态。</p>
        </div>
      </header>

      <SectionCard title="查询" subtitle="open_only 默认开启，便于先看当前在场风险。">
        <div className="form-grid form-grid--filters">
          <label>
            <span>open_only</span>
            <select value={openOnly ? 'true' : 'false'} onChange={(event) => setOpenOnly(event.target.value === 'true')}>
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          </label>
          <label>
            <span>condition_id</span>
            <input value={conditionId} onChange={(event) => setConditionId(event.target.value)} />
          </label>
          <label>
            <span>token_id</span>
            <input value={tokenId} onChange={(event) => setTokenId(event.target.value)} />
          </label>
          <label>
            <span>trace_id</span>
            <input value={traceId} onChange={(event) => setTraceId(event.target.value)} />
          </label>
        </div>
      </SectionCard>

      <div className="content-grid content-grid--wide-aside">
        <SectionCard
          title="订单列表"
          subtitle={`服务端 total ${ordersQuery.data?.total ?? 0}`}
          actions={
            <div className="inline-actions">
              <button type="button" onClick={() => setOffset((current) => Math.max(0, current - 50))} disabled={offset === 0}>
                上一页
              </button>
              <button
                type="button"
                onClick={() => setOffset((current) => current + 50)}
                disabled={(ordersQuery.data?.items.length ?? 0) < 50}
              >
                下一页
              </button>
            </div>
          }
        >
          <DataTable
            columns={columns}
            rows={ordersQuery.data?.items ?? []}
            rowKey={(row) => row.order_id ?? `${row.condition_id}-${row.token_id}-${row.created_at ?? 'unknown'}`}
            emptyTitle="没有订单"
            emptyDescription="当前筛选下没有匹配结果。"
            onRowClick={(row) => {
              setSelectedOrder(row)
              setMarketSlug(row.market_slug ?? '')
              setManualTokenId(row.token_id)
            }}
            selectedRowKey={selectedOrder?.order_id ?? null}
          />
        </SectionCard>

        <div className="detail-stack">
          <SectionCard title="人工 cancel / replace sell" subtitle="适合已经有持仓且需要重挂 SELL 的场景。">
            <form
              className="form-grid"
              onSubmit={(event) => {
                event.preventDefault()
                void cancelReplaceMutation.mutateAsync()
              }}
            >
              <label>
                <span>market_slug</span>
                <input value={marketSlug} onChange={(event) => setMarketSlug(event.target.value)} />
              </label>
              <label>
                <span>token_id</span>
                <input value={manualTokenId} onChange={(event) => setManualTokenId(event.target.value)} />
              </label>
              <label>
                <span>new_price</span>
                <input value={newPrice} onChange={(event) => setNewPrice(event.target.value)} />
              </label>
              <label>
                <span>operator</span>
                <input value={operator} onChange={(event) => setOperator(event.target.value)} />
              </label>
              <button type="submit" disabled={cancelReplaceMutation.isPending}>
                {cancelReplaceMutation.isPending ? '提交中...' : '提交 SELL 修复'}
              </button>
            </form>
          </SectionCard>

          <SectionCard title="当前选中订单" subtitle="点击左侧订单可快速带入 market_slug 和 token_id。">
            <pre className="json-block">{formatJson(selectedOrder ?? {})}</pre>
          </SectionCard>

          <SectionCard title="操作结果" subtitle="服务端返回 review、取消结果和重挂结果。">
            <pre className="json-block">{formatJson(cancelReplaceMutation.data ?? {})}</pre>
          </SectionCard>
        </div>
      </div>
    </div>
  )
}
