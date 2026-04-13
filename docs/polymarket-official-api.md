# Polymarket 官方 API 调用清单

本文档把本仓库已经接入或已封装的 Polymarket 官方接口做一次本地落档，并额外标出费率信息获取方式。

- 核对日期：2026-04-13
- 适用仓库：`fdv`
- 依赖基线：`py-clob-client>=0.34.6`
- 本机核对到的官方 Python SDK 版本：`py-clob-client 0.34.6`

当前实现状态补充：

- 账户余额与 allowance 已切到 `GET /balance-allowance`。
- open orders / 用户 trades 已对齐到官方 SDK 当前 ledger 路径。
- Data API positions / trades 查询参数已对齐到官方当前 `user` / `market` / `eventId` 口径。
- market / user WebSocket 已按官方当前订阅 payload 接入主运行链路。
- 市场静态费率字段已经接入 `Market`、数据库落表和管理端 `/markets` 输出。
- `GET /fee-rate` 已由后台对账链路接入，用于按 `token_id` 刷新本地费率缓存。
- 管理端 `/markets` 已支持基于本地 fee 缓存字段做筛选和排序，不在 HTTP handler 内直接请求 Polymarket。
- 管理端已新增 `/profiles/detail`，通过 `GET /public-profile?address=...` 提供公开用户资料查询。
- 管理端已新增 `/profiles/value`，通过 `GET /value?user=...` 提供用户总持仓价值查询。
- 管理端已新增 `/profiles/activity`，通过 `GET /activity?user=...` 提供公开用户活动查询。
- 管理端已新增 `/profiles/trades`，通过 `GET /trades?user=...` 提供用户成交列表查询。
- 管理端已新增 `/profiles/positions`，通过 `GET /positions?user=...` 提供用户当前持仓分析查询。
- 管理端已新增 `/profiles/closed-positions`，通过 `GET /closed-positions?user=...` 提供用户已平仓持仓查询。
- 管理端已新增 `/markets/orderbook`，优先读本地热态快照，缺失时回退 `GET /book`。
- 管理端已新增 `/markets/midpoint`，优先用本地热态盘口计算 midpoint，缺失时回退 `GET /midpoint`。
- 管理端已新增 `/markets/positions`，通过 `GET /market-positions?market=...` 提供市场持仓分析查询。
- 管理端已新增 `/markets/holders`，通过 `GET /holders?market=...` 提供市场持有人列表查询。
- 管理端已新增 `/markets/prices-history`，通过 `GET /prices-history?market=...` 提供市场价格历史查询。
- 管理端已新增 `/profiles/search`，通过 `GET /public-search?q=...` 提供公开用户搜索。

## 1. 官方基础地址

| 类别 | 基础地址 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| Gamma API | `https://gamma-api.polymarket.com` | event / market 元数据发现 | 无 |
| Data API | `https://data-api.polymarket.com` | 用户持仓、成交、分析类数据 | 官方文档当前标注为公开 |
| CLOB API | `https://clob.polymarket.com` | orderbook、价格、下单、撤单、余额授权 | 公开读接口无鉴权；交易和用户账本接口需要 L1/L2 |
| Market WS | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | 实时 orderbook / price / market lifecycle | 无 |
| User WS | `wss://ws-subscriptions-clob.polymarket.com/ws/user` | 实时用户订单 / 成交更新 | 需要 API credentials |

## 2. 当前主运行链路实际在用的官方接口

这一节只记当前主运行链路已经会打到的官方接口，分为直接调用和通过官方 SDK 间接调用。

### 2.1 直接 REST 调用

| 场景 | 仓库入口 | 当前代码路径 | 官方接口 | 鉴权 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 市场发现 | `GammaClient.discover_events()` | `src/fdv_trader/infra/polymarket/gamma_client.py` | `GET /events` | 无 | `main.py` 的 market discovery 周期扫描使用 |
| 市场元数据刷新 | `GammaClient.list_markets()` | `src/fdv_trader/infra/polymarket/gamma_client.py` | `GET /markets` | 无 | `reconcile_worker.py` 按 `slug` 拉权威 market |
| orderbook 快照 | `ClobClient.get_orderbook()` | `src/fdv_trader/infra/polymarket/clob_client.py` | `GET /book` | 无 | `main.py` 的 REST snapshot loader 和 `reconcile_worker.py` 都在用 |
| 用户 positions 刷新 | `DataClient.list_positions()` | `src/fdv_trader/infra/polymarket/data_client.py` | `GET /positions` | 官方文档当前标注为公开 | `reconcile_worker.py` 用官方当前 `user` / `market` / `eventId` 参数口径刷新 positions；管理端 `/profiles/positions` 复用同一接口输出分析字段 |
| 用户 open orders 刷新 | `ClobClient.list_open_orders()` | `src/fdv_trader/infra/polymarket/clob_client.py` | `GET /data/orders` | L2 | `reconcile_worker.py` 刷新账户 open orders，按 SDK 分页拉全量 |
| 用户 trades 刷新 | `ClobClient.list_fills()` | `src/fdv_trader/infra/polymarket/clob_client.py` | `GET /data/trades` | L2 | `reconcile_worker.py` 刷新 fills，按 SDK 分页拉全量 |
| 账户余额/授权刷新 | `ClobClient.get_balance_allowance()` | `src/fdv_trader/infra/polymarket/clob_client.py` | `GET /balance-allowance` | L2 | `reconcile_worker.py` 刷新 `balance_usdc` 与 `allowance_usdc` |
| 市场费率刷新 | `ClobClient.get_fee_rate()` | `src/fdv_trader/infra/polymarket/clob_client.py` | `GET /fee-rate?token_id=...` | 无 | `reconcile_worker.py` 按 `market.no_token_id` 刷新本地费率缓存 |

补充说明：

- 官方 Get trades 页面当前展示的是 `GET /trades`。
- 官方 Python SDK `py-clob-client 0.34.6` 当前实际使用的是 `GET /data/trades`。
- 官方 rate limits 页面同时列出 `/trades` 和 `/data/trades`。
- 当前仓库按 SDK 路径接入。

### 2.2 通过官方 SDK 间接调用

`PolymarketTradingClient` 并不自己拼交易 REST，而是调用官方 `py-clob-client 0.34.6`。因此下列接口虽然没有在仓库源码里手写 URL，但在运行时会被官方 SDK 实际调用。

| 场景 | 仓库入口 | SDK 实际接口 | 鉴权 | 备注 |
| --- | --- | --- | --- | --- |
| 创建或派生 API credentials | `PolymarketTradingClient.get_api_credentials()` / `_ensure_client()` | `POST /auth/api-key` 或 `GET /auth/derive-api-key` | L1 | 首次进入 L2 流程时触发 |
| 提交订单 | `PolymarketTradingClient.post_signed_order()` | `POST /order` | L2 | `submit` 和 `replace` 的新单提交都走这里 |
| 撤单 | `PolymarketTradingClient.cancel_order()` | `DELETE /order` | L2 | `cancel` 和 `replace` 的旧单撤销都走这里 |
| 下单前拉 tick size | `PolymarketTradingClient.create_signed_order()` -> 官方 `create_order` / `create_market_order` | `GET /tick-size` | 无 | 官方 SDK 自动做，不需要仓库额外处理 |
| 下单前拉 neg risk | 同上 | `GET /neg-risk` | 无 | 官方 SDK 自动做 |
| 下单前拉 fee rate | 同上 | `GET /fee-rate?token_id=...` | 无 | 官方 SDK 自动做，并把 `feeRateBps` 写入签名 payload |

### 2.3 当前主链路最关键的费率接口

当前真正影响下单签名正确性的费率接口只有一个：

| 接口 | 返回字段 | 当前仓库是否在用 | 用法 |
| --- | --- | --- | --- |
| `GET /fee-rate?token_id={token_id}` 或 `GET /fee-rate/{token_id}` | `base_fee` | 是，直接和间接都在用 | 官方 SDK 在签名前自动拉取；本仓库后台也会显式拉取后写入本地市场记录 |

## 3. 已封装但当前不在主运行链路的接口

当前已封装但不在交易主运行链路里的读接口如下。

| 场景 | 仓库入口 | 当前代码路径 | 官方接口 | 鉴权 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 用户公开资料 | `GammaClient.get_public_profile()` | `src/fdv_trader/infra/polymarket/gamma_client.py` | `GET /public-profile?address=...` | 无 | 管理端 `/profiles/detail` 读取并序列化 `name`、`profileImage`、`xUsername`、`verifiedBadge` 等稳定字段 |
| 用户总持仓价值 | `DataClient.get_user_value()` | `src/fdv_trader/infra/polymarket/data_client.py` | `GET /value?user=...` | 官方文档当前标注为公开 | 管理端 `/profiles/value` 读取并序列化总价值，支持按单个 condition id 过滤 |
| 用户公开活动 | `DataClient.list_activity()` | `src/fdv_trader/infra/polymarket/data_client.py` | `GET /activity?user=...` | 官方文档当前标注为公开 | 管理端 `/profiles/activity` 读取并序列化 `type`、`size`、`usdcSize`、`transactionHash`、`profileImage` 等稳定字段 |
| 用户成交列表 | `DataClient.list_trades()` | `src/fdv_trader/infra/polymarket/data_client.py` | `GET /trades?user=...` | 官方文档当前标注为公开 | 管理端 `/profiles/trades` 读取并序列化 `side`、`size`、`price`、`timestamp`、`transactionHash` 与用户公开资料字段 |
| 用户当前持仓分析 | `DataClient.list_positions()` | `src/fdv_trader/infra/polymarket/data_client.py` | `GET /positions?user=...` | 官方文档当前标注为公开 | 管理端 `/profiles/positions` 读取并序列化官方当前 `currentValue`、`cashPnl`、`realizedPnl`、`negativeRisk` 等字段 |
| 用户已平仓持仓 | `DataClient.list_closed_positions()` | `src/fdv_trader/infra/polymarket/data_client.py` | `GET /closed-positions?user=...` | 官方文档当前标注为公开 | 管理端 `/profiles/closed-positions` 读取并序列化 `realizedPnl`、`curPrice`、`timestamp`、`outcome` 等字段 |
| 市场盘口快照 | `ClobClient.get_orderbook()` | `src/fdv_trader/infra/polymarket/clob_client.py` | `GET /book` | 无 | 管理端 `/markets/orderbook` 优先读本地 `market_ws_worker` 热态快照，缺失时回退 REST |
| 市场中间价 | `ClobClient.get_midpoint()` | `src/fdv_trader/infra/polymarket/clob_client.py` | `GET /midpoint` | 无 | 管理端 `/markets/midpoint` 优先用本地 `best_bid` / `best_ask` 计算 midpoint，缺失时回退 REST |
| 市场持仓分析 | `DataClient.list_market_positions()` | `src/fdv_trader/infra/polymarket/data_client.py` | `GET /market-positions?market=...` | 官方文档当前标注为公开 | 管理端 `/markets/positions` 读取并序列化按 outcome token 分组的持仓、当前价值和 pnl 字段 |
| 市场持有人列表 | `DataClient.list_holders()` | `src/fdv_trader/infra/polymarket/data_client.py` | `GET /holders?market=...` | 官方文档当前标注为公开 | 管理端 `/markets/holders` 读取并序列化 `token`、`amount`、`name`、`profileImage` 等稳定字段 |
| 市场价格历史 | `ClobClient.get_prices_history()` | `src/fdv_trader/infra/polymarket/clob_client.py` | `GET /prices-history?market=...` | 无 | 管理端 `/markets/prices-history` 读取并序列化 `history[].t` / `history[].p` |
| 用户公开搜索 | `GammaClient.search_public_profiles()` | `src/fdv_trader/infra/polymarket/gamma_client.py` | `GET /public-search?q=...` | 无 | 管理端 `/profiles/search` 只提取 `profiles` 与 `pagination`，不透传 events / tags |

补充说明：

- `DataClient.list_positions()` / `DataClient.list_trades()` 已收敛到官方当前 `user` / `market` / `eventId` 参数口径。
- 新增 Polymarket 接口时，仍以官方文档和 `py-clob-client` 当前实现为准，不再引入旧参数别名。

## 4. 费率信息能从哪里拿

如果需求是“知道某个 token / market 当前费率是多少”，优先级建议如下。

### 4.1 最权威，且适合下单前使用

| 接口 | 返回内容 | 适用场景 |
| --- | --- | --- |
| `GET /fee-rate?token_id={token_id}` | `base_fee`，单位是 bps | 签名前获取真实费率；这是最应该依赖的接口 |
| `GET /fee-rate/{token_id}` | 同上 | 和 query 版本等价，适合 path 风格的调用方 |

说明：

- 费率是按 token / market 动态取的，不要硬编码。
- 官方 Fees 页面明确要求自建 REST 签名时必须先拉 `fee-rate`，再把 `feeRateBps` 写进签名 payload。

### 4.2 适合做市场扫描或展示，但不应替代签名前查询

| 来源 | 可拿到的费率字段 | 备注 |
| --- | --- | --- |
| Gamma `GET /events` / `GET /markets` 响应 | `makerBaseFee`、`takerBaseFee`、`feesEnabled`、`feeSchedule` | 已用于市场发现和权威刷新，并已写入本地 `Market` / 数据库 / `/markets` 输出 |
| Market WS `new_market` 事件 | `fees_enabled`、`taker_base_fee`、`fee_schedule.rate`、`fee_schedule.rebate_rate` | 已回写本地 `Market` fee 快照；管理端可直接用本地缓存做筛选和展示 |
| Market WS `last_trade_price` 事件 | `fee_rate_bps` | 已回写本地 `fee_rate_bps` / `fee_rate_updated_at`，优先更新运行态 registry 缓存 |

### 4.3 当前仓库的费率展示口径

当前市场视图统一输出 `fees` 对象，结构如下：

```json
{
  "fees": {
    "enabled": true,
    "maker_base_fee_bps": 0,
    "taker_base_fee_bps": 100,
    "fee_rate_bps": 125,
    "fee_rate_updated_at": "2026-04-13T10:00:00+00:00"
  }
}
```

- `enabled` / `maker_base_fee_bps` / `taker_base_fee_bps`：来自 Gamma 市场元数据。
- `fee_rate_bps` / `fee_rate_updated_at`：来自 CLOB `GET /fee-rate` 与 Market WS `last_trade_price.fee_rate_bps`，都会写入本地。
- 当前后台使用 `market.no_token_id` 作为 `token_id` 去刷新 `fee_rate_bps`。
- 管理端 `/markets` 只返回本地快照，不在请求过程中实时调用外部费率接口；运行中优先读 registry 热态市场缓存，registry 为空时再回退数据库快照。
- market 相关事件现在会从 `EventBus` 镜像到 `LocalOutbox`，再由 `PersistenceWorker` 异步写入数据库市场快照。
- user WS 的 `order_state_updated` / `fill_recorded` / `position_updated` 也会镜像进 outbox，但会裁掉 `snapshot` / `open_orders` 这类大块上下文字段，只保留落库需要的数据。
- `account_snapshots` 现已落库，但进程启动时只恢复 `balance_usdc` / `allowance_usdc` 这类可持久化事实；`user_ws_connected`、`allow_new_buys`、`paused_markets`、`last_reconcile_at` 仍按当前进程的 live WS / reconcile 状态重新建立。
- 管理端 `/markets` 当前支持 `fees_enabled`、`fee_rate_bps_min/max`、`maker_base_fee_bps_min/max`、`taker_base_fee_bps_min/max` 筛选，以及 `fee_rate_bps` / `fee_rate_updated_at` / `maker_base_fee_bps` / `taker_base_fee_bps` / `market_slug` 排序。

### 4.4 静态规则说明页面

官方 Fees 页面给出了：

- 哪些分类收费、哪些分类免手续费
- taker fee 公式
- maker rebate 比例
- `feesEnabled` / `feeRateBps` 的解释

但这个页面更适合做人读说明，不适合在程序里替代 `GET /fee-rate`。

## 5. WebSocket 在当前仓库里的状态

截至 2026-04-13，主运行链路已经真正调用 `PolymarketWebSocketClient.stream_market_messages()` 和 `stream_user_messages()`。

当前接入方式：

- market：按官方当前 payload 订阅 `{"assets_ids":[...],"type":"market","custom_feature_enabled":true}`，订阅集来自当前 registry 中跟踪市场的 NO token ids。
- user：按官方当前 payload 订阅 `{"auth": {...}, "markets": [...], "type":"user"}`，订阅集来自当前 registry 中跟踪市场的 condition ids。

当前仓库已经把以下官方消息形态纳入处理：

- market WS 的 `price_change.price_changes[]`、`market_resolved.assets_ids[]`
- market WS 的 `new_market` fee 字段回写、`last_trade_price.fee_rate_bps` 回写
- user WS 的 `event_type=order|trade`、`market`、`asset_id`、`original_size`、`size_matched`、`matchtime`

当前还没有做的部分：

- 若订阅市场集合频繁变化，当前实现会重建 stream task 以更新订阅集。

## 6. 官方参考链接

- API 总览：<https://docs.polymarket.com/api-reference>
- Authentication：<https://docs.polymarket.com/api-reference/authentication>
- List events：<https://docs.polymarket.com/api-reference/events/list-events>
- List markets：<https://docs.polymarket.com/api-reference/markets/list-markets>
- Get order book：<https://docs.polymarket.com/api-reference/market-data/get-order-book>
- Get midpoint：<https://docs.polymarket.com/api-reference/market-data/get-midpoint>
- Get prices history：<https://docs.polymarket.com/api-reference/markets/get-prices-history>
- Get positions for a market：<https://docs.polymarket.com/api-reference/core/get-positions-for-a-market>
- Get current positions for a user：<https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user>
- Get closed positions for a user：<https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user>
- Get total value of a user's positions：<https://docs.polymarket.com/api-reference/core/get-total-value-of-a-users-positions>
- Get top holders for markets：<https://docs.polymarket.com/api-reference/core/get-top-holders-for-markets>
- Get user activity：<https://docs.polymarket.com/api-reference/core/get-user-activity>
- Get trades for a user or markets：<https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets>
- Get public profile by wallet address：<https://docs.polymarket.com/api-reference/profiles/get-public-profile-by-wallet-address>
- Search markets, events, and profiles：<https://docs.polymarket.com/api-reference/search/search-markets-events-and-profiles>
- Post a new order：<https://docs.polymarket.com/api-reference/trade/post-a-new-order>
- Get trades：<https://docs.polymarket.com/api-reference/trade/get-trades>
- Get fee rate：<https://docs.polymarket.com/api-reference/market-data/get-fee-rate>
- Get fee rate by path parameter：<https://docs.polymarket.com/api-reference/market-data/get-fee-rate-by-path-parameter>
- Fees：<https://docs.polymarket.com/trading/fees>
- Market Channel：<https://docs.polymarket.com/market-data/websocket/market-channel>
- User Channel：<https://docs.polymarket.com/market-data/websocket/user-channel>
- Rate Limits：<https://docs.polymarket.com/quickstart/introduction/rate-limits>
