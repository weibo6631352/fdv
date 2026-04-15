import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '../../core/api/resources'
import type { AllocationRecord } from '../../core/api/types'
import { SectionCard } from '../../shared/ui/SectionCard'
import { DataTable, type DataColumn } from '../../shared/ui/DataTable'
import { formatDecimal, formatJson } from '../../shared/utils/format'

export const OperationsPage = () => {
  const queryClient = useQueryClient()
  const [traceId, setTraceId] = useState('')
  const [conditionIdsInput, setConditionIdsInput] = useState('')

  const allocationsQuery = useQuery({
    queryKey: ['allocations'],
    queryFn: () =>
      adminApi.listAllocations({
        limit: 100,
        offset: 0,
      }),
  })

  const reconcileMutation = useMutation({
    mutationFn: () =>
      adminApi.reconcile({
        trace_id: traceId || undefined,
        condition_ids: conditionIdsInput
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean),
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['portfolio'] }),
        queryClient.invalidateQueries({ queryKey: ['orders'] }),
        queryClient.invalidateQueries({ queryKey: ['positions'] }),
      ])
    },
  })

  const allocationColumns: Array<DataColumn<AllocationRecord>> = [
    {
      key: 'market',
      header: '市场',
      cell: (row) => (
        <div className="table-primary">
          <strong>{row.market_slug ?? row.condition_id}</strong>
          <span>{row.token_id ?? '—'}</span>
        </div>
      ),
    },
    { key: 'target', header: 'target_budget', align: 'right', cell: (row) => formatDecimal(row.target_budget_usdc) },
    { key: 'buy', header: 'buy_budget', align: 'right', cell: (row) => formatDecimal(row.buy_budget_usdc) },
    {
      key: 'exposure',
      header: 'current_exposure',
      align: 'right',
      cell: (row) => formatDecimal(row.current_exposure_usdc),
    },
    { key: 'reason', header: 'reason', cell: (row) => row.reason ?? '—' },
  ]

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">操作</p>
          <h1>人工 reconcile 与分配观察</h1>
          <p>前端只提交受控操作，不直接执行交易动作。</p>
        </div>
      </header>

      <div className="content-grid content-grid--two">
        <SectionCard title="手工 reconcile" subtitle="支持可选 trace_id 和 condition_ids 过滤。">
          <form
            className="form-grid"
            onSubmit={(event) => {
              event.preventDefault()
              void reconcileMutation.mutateAsync()
            }}
          >
            <label>
              <span>trace_id</span>
              <input value={traceId} onChange={(event) => setTraceId(event.target.value)} />
            </label>
            <label>
              <span>condition_ids</span>
              <textarea
                value={conditionIdsInput}
                onChange={(event) => setConditionIdsInput(event.target.value)}
                rows={4}
                placeholder="用逗号分隔多个 condition_id"
              />
            </label>
            <button type="submit" disabled={reconcileMutation.isPending}>
              {reconcileMutation.isPending ? '执行中...' : '执行 reconcile'}
            </button>
          </form>
        </SectionCard>

        <SectionCard title="reconcile 结果" subtitle="保留原始返回，方便人工复核。">
          <pre className="json-block">{formatJson(reconcileMutation.data ?? {})}</pre>
        </SectionCard>
      </div>

      <SectionCard title="allocations" subtitle={`当前 ${allocationsQuery.data?.total ?? 0} 条。`}>
        <DataTable
          columns={allocationColumns}
          rows={allocationsQuery.data?.items ?? []}
          rowKey={(row) => row.idempotency_key ?? `${row.condition_id}-${row.token_id ?? 'unknown'}`}
          emptyTitle="没有 allocations"
          emptyDescription="当前没有可展示的分配记录。"
        />
      </SectionCard>
    </div>
  )
}
