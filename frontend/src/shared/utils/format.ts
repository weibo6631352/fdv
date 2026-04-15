import type { JsonValue } from '../../core/api/types'

const numberFormatter = new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: 4,
})

const compactFormatter = new Intl.NumberFormat('zh-CN', {
  notation: 'compact',
  maximumFractionDigits: 2,
})

export const formatDecimal = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  const numericValue = Number(value)
  if (Number.isNaN(numericValue)) {
    return String(value)
  }
  return numberFormatter.format(numericValue)
}

export const formatCompact = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  const numericValue = Number(value)
  if (Number.isNaN(numericValue)) {
    return String(value)
  }
  return compactFormatter.format(numericValue)
}

export const formatDateTime = (value: string | null | undefined): string => {
  if (!value) {
    return '—'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

export const formatBool = (value: boolean | null | undefined): string => {
  if (value === null || value === undefined) {
    return '—'
  }
  return value ? '是' : '否'
}

export const formatJson = (value: JsonValue | unknown): string => {
  if (value === undefined) {
    return '—'
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export const formatList = (values: Array<string | null | undefined>): string => {
  const items = values.filter((value): value is string => Boolean(value))
  return items.length > 0 ? items.join(' / ') : '—'
}

export const getString = (value: unknown): string | null => {
  return typeof value === 'string' ? value : null
}
