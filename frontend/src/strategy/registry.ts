import type { ReactNode } from 'react'
import type {
  MarketView,
  PortfolioSnapshot,
  ReadyPayload,
  RuntimePayload,
} from '../core/api/types'
import type { Tone } from '../shared/ui/StatusPill'
import { currentStrategyExtension } from './current/extension'

export interface StrategyBadge {
  label: string
  tone?: Tone
}

export interface StrategyDashboardContext {
  ready?: ReadyPayload
  runtime?: RuntimePayload
  portfolio?: PortfolioSnapshot
  markets: MarketView[]
}

export interface StrategyExtension {
  id: string
  displayName: string
  description: string
  renderDashboard?: (context: StrategyDashboardContext) => ReactNode
  renderMarketBadges?: (market: MarketView) => StrategyBadge[]
  renderMarketDetail?: (market: MarketView) => ReactNode
}

const fallbackStrategyExtension: StrategyExtension = {
  id: 'unknown',
  displayName: '未知策略',
  description: '当前策略没有单独的前端扩展实现，页面只显示通用信息。',
}

const registry: Record<string, StrategyExtension> = {
  'strategies.current': currentStrategyExtension,
}

export const resolveStrategyExtension = (strategyModule: string | null | undefined): StrategyExtension => {
  if (!strategyModule) {
    return fallbackStrategyExtension
  }
  return registry[strategyModule] ?? fallbackStrategyExtension
}
