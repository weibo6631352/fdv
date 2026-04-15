import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../../core/api/resources'
import type { AuditEventRecord, OutboxEventRecord } from '../../core/api/types'
import { SectionCard } from '../../shared/ui/SectionCard'
import { DataTable, type DataColumn } from '../../shared/ui/DataTable'
import { formatDateTime } from '../../shared/utils/format'

export const AuditPage = () => {
  const [traceId, setTraceId] = useState('')
  const [eventTitle, setEventTitle] = useState('')
  const [outboxTraceId, setOutboxTraceId] = useState('')

  const auditQuery = useQuery({
    queryKey: ['audit-events', { traceId, eventTitle }],
    queryFn: () =>
      adminApi.listAuditEvents({
        limit: 100,
        offset: 0,
        trace_id: traceId || undefined,
        event_title: eventTitle || undefined,
      }),
  })

  const outboxQuery = useQuery({
    queryKey: ['outbox-pending', { outboxTraceId }],
    queryFn: () =>
      adminApi.listOutboxPending({
        limit: 100,
        offset: 0,
        trace_id: outboxTraceId || undefined,
      }),
  })

  const auditColumns: Array<DataColumn<AuditEventRecord>> = [
    {
      key: 'title',
      header: '事件',
      cell: (row) => (
        <div className="table-primary">
          <strong>{row.event_title}</strong>
          <span>{row.market_slug ?? row.condition_id ?? '—'}</span>
        </div>
      ),
    },
    { key: 'status', header: '状态', cell: (row) => row.status ?? '—' },
    { key: 'trace', header: 'trace_id', cell: (row) => row.trace_id ?? '—' },
    { key: 'reason', header: '原因', cell: (row) => row.reason ?? '—' },
    { key: 'updated', header: 'updated_at', cell: (row) => formatDateTime(row.updated_at ?? row.created_at) },
  ]

  const outboxColumns: Array<DataColumn<OutboxEventRecord>> = [
    {
      key: 'event',
      header: '事件',
      cell: (row) => (
        <div className="table-primary">
          <strong>{row.event_type}</strong>
          <span>{row.market_slug ?? row.condition_id ?? '—'}</span>
        </div>
      ),
    },
    { key: 'trace', header: 'trace_id', cell: (row) => row.trace_id ?? '—' },
    { key: 'priority', header: 'priority', cell: (row) => row.priority ?? '—' },
    { key: 'retry', header: 'retry_count', cell: (row) => row.retry_count ?? '—' },
    { key: 'created', header: 'created_at', cell: (row) => formatDateTime(row.created_at) },
  ]

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">审计</p>
          <h1>审计事件与 outbox</h1>
          <p>读审计和事件积压，不在前端解释底层 payload 的业务语义。</p>
        </div>
      </header>

      <SectionCard title="过滤条件" subtitle="audit-events 和 outbox 分别查询。">
        <div className="form-grid form-grid--filters">
          <label>
            <span>audit trace_id</span>
            <input value={traceId} onChange={(event) => setTraceId(event.target.value)} />
          </label>
          <label>
            <span>event_title</span>
            <input value={eventTitle} onChange={(event) => setEventTitle(event.target.value)} />
          </label>
          <label>
            <span>outbox trace_id</span>
            <input value={outboxTraceId} onChange={(event) => setOutboxTraceId(event.target.value)} />
          </label>
        </div>
      </SectionCard>

      <SectionCard title="audit-events" subtitle={`当前 ${auditQuery.data?.total ?? 0} 条。`}>
        <DataTable
          columns={auditColumns}
          rows={auditQuery.data?.items ?? []}
          rowKey={(row) => row.event_id ?? `${row.trace_id}-${row.updated_at ?? row.created_at ?? 'unknown'}`}
          emptyTitle="没有审计事件"
          emptyDescription="当前查询条件没有匹配数据。"
        />
      </SectionCard>

      <SectionCard title="outbox pending" subtitle={`当前 ${outboxQuery.data?.total ?? 0} 条。`}>
        <DataTable
          columns={outboxColumns}
          rows={outboxQuery.data?.items ?? []}
          rowKey={(row) => row.event_id ?? `${row.trace_id}-${row.created_at ?? 'unknown'}`}
          emptyTitle="没有 outbox pending"
          emptyDescription="当前没有待处理 outbox 事件。"
        />
      </SectionCard>
    </div>
  )
}
