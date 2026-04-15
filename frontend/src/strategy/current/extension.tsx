import { SectionCard } from '../../shared/ui/SectionCard'
import { StatusPill } from '../../shared/ui/StatusPill'
import { formatDecimal, formatList } from '../../shared/utils/format'
import type { MarketView } from '../../core/api/types'
import type { StrategyExtension } from '../registry'

const marketsWithPosition = (markets: MarketView[]) => markets.filter((market) => Number(market.position?.shares ?? 0) > 0)
const marketsWithSellOrders = (markets: MarketView[]) =>
  markets.filter((market) => market.open_orders.some((order) => order.side === 'sell'))

export const currentStrategyExtension: StrategyExtension = {
  id: 'strategies.current',
  displayName: '当前策略',
  description: '围绕市场发现、入场触发、恢复和跟踪语义提供解释性展示。',
  renderDashboard: ({ markets }) => {
    const tracked = markets.filter((market) => market.tracked).length
    const touched = markets.filter((market) => market.entry_price_touched).length
    const positioned = marketsWithPosition(markets)
    const liveSellMarkets = marketsWithSellOrders(markets)

    return (
      <div className="content-grid content-grid--two">
        <SectionCard title="策略态势" subtitle="只解释当前策略如何看待这些市场。">
          <div className="stats-grid stats-grid--compact">
            <div className="stat-card">
              <span>策略跟踪</span>
              <strong>{tracked}</strong>
            </div>
            <div className="stat-card">
              <span>入场触发</span>
              <strong>{touched}</strong>
            </div>
            <div className="stat-card">
              <span>持仓市场</span>
              <strong>{positioned.length}</strong>
            </div>
            <div className="stat-card">
              <span>挂卖单市场</span>
              <strong>{liveSellMarkets.length}</strong>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="策略说明" subtitle="策略层负责解释，不直接操作交易客户端。">
          <div className="detail-list">
            <div>
              <dt>发现与筛选</dt>
              <dd>通用市场列表照常展示，当前策略只额外标注匹配关键词、拒绝原因和入场触发状态。</dd>
            </div>
            <div>
              <dt>入场语义</dt>
              <dd>当 `entry_price_touched=true` 时，表示该市场已进入当前策略关心的触发带。</dd>
            </div>
            <div>
              <dt>恢复与跟踪</dt>
              <dd>持仓和未完成卖单会在策略扩展里单独高亮，避免它们淹没在通用市场表格里。</dd>
            </div>
          </div>
        </SectionCard>
      </div>
    )
  },
  renderMarketBadges: (market) => {
    const badges = []
    if (market.entry_price_touched) {
      badges.push({ label: '触发带内', tone: 'success' as const })
    }
    if (Number(market.position?.shares ?? 0) > 0) {
      badges.push({ label: '有持仓', tone: 'warning' as const })
    }
    if (market.open_orders.some((order) => order.side === 'sell')) {
      badges.push({ label: '有卖单', tone: 'neutral' as const })
    }
    return badges
  },
  renderMarketDetail: (market) => {
    return (
      <SectionCard title="当前策略视角" subtitle="策略解释只依赖通用市场数据。">
        <div className="detail-list">
          <div>
            <dt>策略标签</dt>
            <dd className="badge-row">
              {currentStrategyExtension.renderMarketBadges?.(market).map((badge) => (
                <StatusPill key={badge.label} label={badge.label} tone={badge.tone} />
              ))}
            </dd>
          </div>
          <div>
            <dt>匹配关键词</dt>
            <dd>{formatList(market.market.matched_keywords)}</dd>
          </div>
          <div>
            <dt>分类</dt>
            <dd>{market.market.category ?? '—'}</dd>
          </div>
          <div>
            <dt>当前价差</dt>
            <dd>{formatDecimal(market.spread)}</dd>
          </div>
          <div>
            <dt>拒绝原因</dt>
            <dd>{market.market.reject_reason ?? '—'}</dd>
          </div>
        </div>
      </SectionCard>
    )
  },
}
