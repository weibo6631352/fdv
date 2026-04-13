# 对外 API 清单

本文档只记录当前仓库已经实际暴露的 HTTP API。

- 核对日期：2026-04-13
- 适用仓库：`fdv`
- 服务入口：`src/fdv_trader/api/app.py`
- 默认无应用层鉴权，建议仅暴露在本机或受控内网

## 1. 当前实际暴露的路由

由 `create_app()` 当前注册的路由如下。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/openapi.json` | OpenAPI 描述 |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/docs/oauth2-redirect` | Swagger UI OAuth redirect helper |
| `GET` | `/redoc` | ReDoc |
| `GET` | `/health` | 存活检查 |
| `GET` | `/ready` | readiness 与阻塞原因 |
| `GET` | `/runtime` | 运行态总览 |
| `GET` | `/workers` | worker 健康与调度状态 |
| `GET` | `/metrics` | 当前指标快照 |
| `GET` | `/audit-events` | 审计事件分页查询 |
| `GET` | `/allocations` | 资金分配分页查询 |
| `GET` | `/markets` | 市场分页查询 |
| `GET` | `/markets/detail` | 单 market 详情 |
| `GET` | `/markets/holders` | 市场持有人列表 |
| `GET` | `/orders` | 订单分页查询 |
| `POST` | `/orders/cancel-replace-sell` | 人工取消并重挂 SELL |
| `GET` | `/fills` | fills 分页查询 |
| `GET` | `/positions` | 持仓分页查询 |
| `GET` | `/portfolio` | 组合与账户摘要 |
| `GET` | `/profiles/detail` | 用户公开资料详情 |
| `GET` | `/profiles/activity` | 用户公开活动列表 |
| `GET` | `/profiles/search` | 用户公开资料搜索 |
| `GET` | `/outbox/pending` | outbox 待处理事件 |
| `POST` | `/operations/reconcile` | 手动触发 reconcile |

当前没有对外暴露的路由：

- 直接下 BUY 单
- 直接撤任意单
- 直接暂停/恢复 market

## 2. 通用返回约定

### 2.1 分页接口

`/markets`、`/orders`、`/fills`、`/positions` 统一返回：

```json
{
  "items": [],
  "total": 0,
  "limit": 100,
  "offset": 0
}
```

`/profiles/activity` 返回：

```json
{
  "items": [],
  "limit": 100,
  "offset": 0
}
```

说明：

- 不返回 `total`，因为上游官方 `GET /activity` 当前不提供总数。

`/markets/holders` 返回：

```json
{
  "items": [],
  "condition_id": "0x...",
  "limit": 20,
  "min_balance": 1
}
```

说明：

- 不返回 `total`，因为上游官方 `GET /holders` 当前不提供总数。

`/profiles/search` 返回：

```json
{
  "items": [],
  "limit": 20,
  "page": 1,
  "has_more": false,
  "total_results": 0
}
```

### 2.2 金额和价格序列化

- `Decimal` 字段统一序列化成字符串。
- 时间统一输出 ISO 8601 UTC 字符串。
- 枚举统一输出小写或约定字符串值。

### 2.3 热态优先级

- `/markets` 运行中优先读内存 `MarketRegistry` 热态快照。
- `/orders` 的 `open_only=true` 读运行态 `AccountStateStore`。
- `/positions` 读运行态 `AccountStateStore`。
- `/fills` 在有 DB session factory 时优先查仓储；否则回退运行态 fills。

## 3. 只读接口

### 3.1 `GET /health`

用途：

- 只看进程是否活着。

典型返回：

```json
{
  "status": "ok",
  "timestamp": "2026-04-13T10:00:00+00:00"
}
```

### 3.2 `GET /ready`

用途：

- 返回当前是否允许自动交易。
- 返回阻塞原因、warning、运行态摘要。

关键字段：

- `ready_to_trade`
- `phase`
- `blocking_issues`
- `warnings`
- `runtime.user_ws_connected`
- `runtime.allow_new_buys`
- `runtime.last_reconcile_at`
- `runtime.blocking_reasons`

说明：

- 该接口是运维判断“现在能不能自动下单”的首选入口。
- `allow_new_buys=false` 会明确表现为阻塞项。

### 3.3 `GET /runtime`

用途：

- 输出完整运行态总览，方便本地排障。

主要顶层字段：

- `phase`
- `ready_to_trade`
- `readiness`
- `settings`
- `runtime`
- `bootstrap_summary`
- `registry`
- `account`
- `event_bus`
- `persistence`
- `markets`
- `portfolio`

说明：

- `settings` 已脱敏，测试里已覆盖 `wallet_private_key -> "***"`。
- `markets[].market.fees` 当前会输出：
  - `enabled`
  - `maker_base_fee_bps`
  - `taker_base_fee_bps`
  - `fee_rate_bps`
  - `fee_rate_updated_at`

### 3.4 `GET /markets`

用途：

- 分页查询当前跟踪市场。
- 支持费率筛选和排序。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | `int` | `100` | `1..500` |
| `offset` | `int` | `0` | `>=0` |
| `trading_status` | `str` | `null` | 按交易状态过滤 |
| `fees_enabled` | `bool` | `null` | 按是否启用费率过滤 |
| `fee_rate_bps_min` | `int` | `null` | `>=0` |
| `fee_rate_bps_max` | `int` | `null` | `>=0` |
| `maker_base_fee_bps_min` | `int` | `null` | `>=0` |
| `maker_base_fee_bps_max` | `int` | `null` | `>=0` |
| `taker_base_fee_bps_min` | `int` | `null` | `>=0` |
| `taker_base_fee_bps_max` | `int` | `null` | `>=0` |
| `sort_by` | `str` | `null` | `market_slug` / `fee_rate_bps` / `fee_rate_updated_at` / `maker_base_fee_bps` / `taker_base_fee_bps` |
| `sort_direction` | `str` | `desc` | `asc` / `desc` |

单项结构重点：

- `market`
- `tracked`
- `orderbook`
- `position`
- `open_orders`
- `open_order_count`
- `best_ask`
- `best_bid`
- `spread`
- `entry_price_touched`

说明：

- 当前不会在 handler 内现场请求外部费率接口。
- 费率查询只使用本地缓存字段。

### 3.5 `GET /markets/detail`

用途：

- 按 `market_slug`、`condition_id` 或 `token_id` 精确查询单个 market。

查询参数：

- `market_slug`
- `condition_id`
- `token_id`

约束：

- 三者至少给一个。
- 找不到时返回 `404 market not found`。

返回结构：

- 与 `/markets.items[]` 单项结构一致。

### 3.6 `GET /markets/holders`

用途：

- 查询单个市场当前 top holders，并带出可展示的公开资料字段。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `condition_id` | `str` | 必填 | `0x` 开头的 64 位 condition id |
| `limit` | `int` | `20` | `1..20`，每个 token 最多返回多少 holder |
| `min_balance` | `int` | `1` | `0..999999`，过滤过小余额 |

返回结构：

- `items[].token_id`
- `items[].holders[].proxy_wallet`
- `items[].holders[].pseudonym`
- `items[].holders[].name`
- `items[].holders[].amount`
- `items[].holders[].profile_image`
- `items[].holders[].profile_image_optimized`

说明：

- 该接口直连 `DataClient.list_holders()`。
- 返回按 token 分组，不同 outcome 会拆成不同 `items[]`。
- 上游 Polymarket 暂时不可用时返回 `502 market_holders_upstream_unavailable`。

### 3.7 `GET /profiles/detail`

用途：

- 按钱包地址查询 Polymarket 公开资料。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `address` | `str` | 必填 | `0x` 开头的 40 位钱包地址 |

关键返回字段：

- `created_at`
- `proxy_wallet`
- `profile_image`
- `display_username_public`
- `bio`
- `pseudonym`
- `name`
- `users`
- `x_username`
- `verified_badge`

说明：

- 该接口直连 `GammaClient.get_public_profile()`，不写数据库，不修改运行态账户快照。
- 找不到 profile 时返回 `404 profile not found`。
- 上游 Polymarket 暂时不可用时返回 `502 profile_upstream_unavailable`。

### 3.8 `GET /profiles/activity`

用途：

- 按钱包地址查询 Polymarket 用户公开活动。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `address` | `str` | 必填 | `0x` 开头的 40 位钱包地址 |
| `limit` | `int` | `100` | `1..500` |
| `offset` | `int` | `0` | `0..10000` |
| `condition_id` | `str` | `null` | 可选，单个 condition id |
| `event_id` | `int` | `null` | 可选，单个 event id |
| `type` | `str` | `null` | `TRADE` / `SPLIT` / `MERGE` / `REDEEM` / `REWARD` / `CONVERSION` / `MAKER_REBATE` / `REFERRAL_REWARD` |
| `start` | `int` | `null` | Unix 时间戳下界 |
| `end` | `int` | `null` | Unix 时间戳上界 |
| `sort_by` | `str` | `null` | `TIMESTAMP` / `TOKENS` / `CASH` |
| `sort_direction` | `str` | `null` | `ASC` / `DESC` |
| `side` | `str` | `null` | `BUY` / `SELL` |

约束：

- `condition_id` 和 `event_id` 互斥。
- `start`、`end` 同时存在时必须满足 `start <= end`。

单项结构重点：

- `proxy_wallet`
- `timestamp`
- `condition_id`
- `type`
- `size`
- `usdc_size`
- `transaction_hash`
- `price`
- `asset`
- `side`
- `outcome_index`
- `title`
- `market_slug`
- `event_slug`
- `name`
- `pseudonym`
- `profile_image`

说明：

- 该接口直连 `DataClient.list_activity()`。
- 时间统一输出 ISO 8601 UTC 字符串；上游原始 `timestamp` 是 Unix 时间戳。
- 上游 Polymarket 暂时不可用时返回 `502 profile_activity_upstream_unavailable`。

### 3.9 `GET /profiles/search`

用途：

- 按关键字搜索 Polymarket 公开用户资料。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `q` | `str` | 必填 | 搜索关键字 |
| `limit` | `int` | `20` | `1..100` |
| `page` | `int` | `1` | `>=1` |

关键返回字段：

- `items[].profile_id`
- `items[].name`
- `items[].pseudonym`
- `items[].display_username_public`
- `items[].profile_image`
- `items[].profile_image_optimized`
- `items[].bio`
- `items[].proxy_wallet`
- `has_more`
- `total_results`

说明：

- 该接口直连 `GammaClient.search_public_profiles()`，只取 `profiles` 和 `pagination`，不透出 events / tags 结果。
- 上游 Polymarket 暂时不可用时返回 `502 profile_search_upstream_unavailable`。

### 3.10 `GET /orders`

用途：

- 分页查询订单。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | `int` | `100` | `1..500` |
| `offset` | `int` | `0` | `>=0` |
| `open_only` | `bool` | `true` | `true` 时只看当前 open orders |
| `condition_id` | `str` | `null` | 可选过滤 |
| `token_id` | `str` | `null` | 可选过滤 |
| `trace_id` | `str` | `null` | 可选过滤 |
| `order_id` | `str` | `null` | 可选过滤 |
| `trade_id` | `str` | `null` | 可选过滤 |

单项结构重点：

- `trace_id`
- `condition_id`
- `token_id`
- `market_slug`
- `side`
- `order_type`
- `price`
- `amount_usdc`
- `size_shares`
- `filled_shares`
- `remaining_shares`
- `notional_usdc`
- `order_id`
- `trade_id`
- `status`
- `idempotency_key`
- `reason`
- `post_only`

说明：

- `open_only=true` 时只返回运行态 open orders。
- `open_only=false` 且存在 DB session factory 时，走仓储快照查询。

### 3.11 `GET /fills`

用途：

- 分页查询 fills。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | `int` | `100` | `1..500` |
| `offset` | `int` | `0` | `>=0` |
| `trace_id` | `str` | `null` | 可选过滤 |
| `order_id` | `str` | `null` | 可选过滤 |
| `trade_id` | `str` | `null` | 可选过滤 |

单项结构重点：

- `trace_id`
- `event_type`
- `event_id`
- `market_slug`
- `condition_id`
- `token_id`
- `order_id`
- `trade_id`
- `side`
- `price`
- `size`
- `notional_usdc`
- `status`
- `confirmed_at`

### 3.12 `GET /positions`

用途：

- 分页查询当前持仓。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | `int` | `100` | `1..500` |
| `offset` | `int` | `0` | `>=0` |
| `condition_id` | `str` | `null` | 可选过滤 |
| `token_id` | `str` | `null` | 可选过滤 |

单项结构重点：

- `condition_id`
- `token_id`
- `market_slug`
- `shares`
- `cost_usdc`
- `open_buy_shares`
- `open_sell_shares`
- `pending_buy_shares`
- `confirmed_shares`
- `last_order_id`
- `last_trade_id`
- `confirmation_status`
- `updated_at`

### 3.13 `GET /portfolio`

用途：

- 给出账户和组合摘要。

当前返回重点：

- `balance_usdc`
- `allowance_usdc`
- `available_usdc`
- `position_count`
- `open_order_count`
- `fill_count`
- `pause_count`
- `last_reconcile_at`
- `user_ws_connected`
- `allow_new_buys`
- `markets_tracked`
- `recent_allocations`

说明：

- 当前 `available_usdc` 直接等于 `balance_usdc`。
- 若仓储可用，会补 `recent_allocations`；否则返回空数组。

### 3.14 `GET /audit-events`

用途：

- 分页查询审计事件。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | `int` | `100` | `1..500` |
| `offset` | `int` | `0` | `>=0` |
| `trace_id` | `str` | `null` | 可选过滤 |
| `event_type` | `str` | `null` | 对应 `event_title` |

单项结构重点：

- `trace_id`
- `event_id`
- `event_title`
- `market_slug`
- `condition_id`
- `token_id`
- `outcome`
- `side`
- `order_type`
- `price`
- `size`
- `notional_usdc`
- `order_id`
- `trade_id`
- `tx_hash`
- `status`
- `reason`
- `created_at`

### 3.15 `GET /allocations`

用途：

- 分页查询已落库的资金分配快照。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | `int` | `100` | `1..500` |
| `offset` | `int` | `0` | `>=0` |
| `trace_id` | `str` | `null` | 可选过滤 |
| `condition_id` | `str` | `null` | 可选过滤 |
| `token_id` | `str` | `null` | 可选过滤 |
| `market_slug` | `str` | `null` | 可选过滤 |

单项结构重点：

- `condition_id`
- `market_slug`
- `token_id`
- `target_budget_usdc`
- `buy_budget_usdc`
- `current_exposure_usdc`
- `released_budget_usdc`
- `reason`
- `release_reason`
- `idempotency_key`

### 3.16 `GET /workers`

用途：

- 输出 worker 健康状态、调度器快照和队列深度。

当前返回重点：

- `phase`
- `automatic_trading_enabled`
- `status_reason`
- `queue_depths`
- `scheduler`
- `workers`

### 3.17 `GET /metrics`

用途：

- 输出 runtime 当前指标快照。

当前返回重点：

- `phase`
- `automatic_trading_enabled`
- `status_reason`
- `queue_depths`
- `metrics`

### 3.18 `GET /outbox/pending`

用途：

- 分页查询当前待处理 outbox 事件。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | `int` | `100` | `1..500` |
| `offset` | `int` | `0` | `>=0` |
| `trace_id` | `str` | `null` | 可选过滤 |

单项结构重点：

- `trace_id`
- `event_type`
- `idempotency_key`
- `event_id`
- `market_slug`
- `condition_id`
- `token_id`
- `reason`
- `created_at`
- `priority`
- `retry_count`
- `last_error`
- `raw_response_summary`
- `payload`

## 4. 受控操作接口

### 4.1 `POST /operations/reconcile`

用途：

- 人工触发一次 reconcile。
- 可只针对部分 `condition_id` 执行。

请求体：

```json
{
  "trace_id": "trace-manual-reconcile",
  "condition_ids": ["condition-500m"]
}
```

返回重点：

- `status`
- `trace_id`
- `plan`
- `applied_actions`
- `failed_actions`

`plan.market_plans[].actions[].action_type` 当前可能出现：

- `cancel_open_buy`
- `cancel_excess_sell`
- `submit_missing_sell`
- `pause_trading`

失败口径：

- 若 `reconcile_worker` 不可用，返回 `{"status":"failed","reason":"reconcile_worker_unavailable"}`。

### 4.2 `POST /orders/cancel-replace-sell`

用途：

- 对某个 market 的现有 SELL 单执行 cancel + replace。

请求体：

```json
{
  "market_slug": "token-500m-fdv",
  "new_price": "0.70",
  "operator": "manual",
  "reason": "admin_reprice",
  "trace_id": "trace-reprice"
}
```

字段约束：

| 字段 | 说明 |
| --- | --- |
| `market_slug` / `condition_id` / `token_id` | 三者至少给一个 |
| `new_price` | `0 < new_price < 1` |
| `operator` | 默认 `manual` |
| `reason` | 默认 `admin_cancel_replace_sell` |
| `trace_id` | 可选，不传则自动生成 |

成功返回重点：

- `status`
- `trace_id`
- `operator`
- `market`
- `cancelled_orders`
- `replace_review`
- `replace_order_submitted`

当前明确失败原因：

- `market_not_found`
- `market_not_operable`
- `invalid_price`
- `invalid_tick_size`
- `price_not_aligned_to_tick_size`
- `no_position_to_sell`
- `cancel_failed`
- `replace_sell_failed`

## 5. 当前接口边界

Admin API 是人工查询和受控操作入口，不是交易策略入口。

允许：

- 健康检查
- readiness 查询
- runtime 查询
- market / profile / order / fill / position / portfolio 查询
- 手动 reconcile
- 手动 cancel + replace sell

禁止：

- 直接创建 FAK BUY 的 HTTP endpoint
- 绕过 Risk Manager 的订单提交
- 在 handler 里直接调用 Polymarket SDK
- 在 handler 里直接改写 `MarketRegistry`
- 在 handler 里直接改写 `Orderbook Cache`
- 无分页的大查询

## 6. 使用建议

- 自动化探活用 `/health`
- 判断能否自动交易用 `/ready`
- 本地排障先看 `/runtime`
- 市场扫描和费率筛选用 `/markets`
- 用户资料查询用 `/profiles/detail`
- 用户活动回放用 `/profiles/activity`
- 用户搜索入口用 `/profiles/search`
- 市场持有人展示用 `/markets/holders`
- 人工修复只用 `/operations/reconcile` 和 `/orders/cancel-replace-sell`
