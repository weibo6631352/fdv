import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '../../core/api/resources'
import type { OrderRecord } from '../../core/api/types'
import { formatApiError } from '../../core/api/client'
import { SectionCard } from '../../shared/ui/SectionCard'
import { DataTable, type DataColumn } from '../../shared/ui/DataTable'
import { JsonPanel } from '../../shared/ui/JsonPanel'
import { StatusPill } from '../../shared/ui/StatusPill'
import { formatDateTime, formatDecimal } from '../../shared/utils/format'

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
  const [formError, setFormError] = useState<string | null>(null)

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
    mutationFn: (payload: { market_slug?: string; token_id?: string; new_price: string; operator: string }) =>
      adminApi.cancelReplaceSell(payload),
    onSuccess: async () => {
      setFormError(null)
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

  const requestError = cancelReplaceMutation.error ? formatApiError(cancelReplaceMutation.error) : null

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    cancelReplaceMutation.reset()

    const normalizedMarketSlug = marketSlug.trim()
    const normalizedTokenId = manualTokenId.trim()
    const normalizedOperator = operator.trim()
    const numericPrice = Number(newPrice)

    if (!normalizedMarketSlug && !normalizedTokenId) {
      setFormError('market_slug 和 token_id 至少要提供一个，才能定位要修复的卖单。')
      return
    }
    if (!Number.isFinite(numericPrice) || numericPrice <= 0 || numericPrice >= 1) {
      setFormError('new_price 必须是 0 到 1 之间的数字。')
      return
    }
    if (!normalizedOperator) {
      setFormError('operator 不能为空。')
      return
    }

    setFormError(null)
    cancelReplaceMutation.mutate({
      market_slug: normalizedMarketSlug || undefined,
      token_id: normalizedTokenId || undefined,
      new_price: newPrice.trim(),
      operator: normalizedOperator,
    })
  }

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
            <form className="form-grid" onSubmit={handleSubmit}>
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
            {formError ? (
              <ul className="message-list form-feedback">
                <li>
                  <strong>表单校验</strong>
                  <span>{formError}</span>
                </li>
              </ul>
            ) : null}
            {requestError ? (
              <ul className="message-list form-feedback">
                <li>
                  <strong>请求失败</strong>
                  <span>{requestError}</span>
                </li>
              </ul>
            ) : null}
          </SectionCard>

          <SectionCard title="当前选中订单" subtitle="点击左侧订单可快速带入 market_slug 和 token_id。">
            <JsonPanel
              value={selectedOrder}
              emptyLabel="尚未选择订单。"
              detailsLabel="查看订单原始 JSON"
              defaultOpen={Boolean(selectedOrder)}
            />
          </SectionCard>

          <SectionCard title="操作结果" subtitle="服务端返回 review、取消结果和重挂结果。">
            <JsonPanel
              value={cancelReplaceMutation.data}
              emptyLabel="尚未执行 SELL 修复。"
              detailsLabel="查看操作结果原始 JSON"
              summary={
                cancelReplaceMutation.data ? (
                  <div className="detail-list">
                    <div>
                      <dt>status</dt>
                      <dd>{cancelReplaceMutation.data.status}</dd>
                    </div>
                    <div>
                      <dt>trace_id</dt>
                      <dd>{cancelReplaceMutation.data.trace_id}</dd>
                    </div>
                    <div>
                      <dt>operator</dt>
                      <dd>{cancelReplaceMutation.data.operator ?? '—'}</dd>
                    </div>
                    <div>
                      <dt>reason</dt>
                      <dd>{cancelReplaceMutation.data.reason ?? '—'}</dd>
                    </div>
                  </div>
                ) : null
              }
            />
          </SectionCard>
        </div>
      </div>
    </div>
  )
}
