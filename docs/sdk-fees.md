# 手续费工具说明

这页只说明当前新增的手续费能力，给二开扩展或脚本直接复用。

适用代码：

- 计算实现：`src/polymarket_trader/domain/fees.py`

## 能力边界

当前提供两类能力：

1. 纯计算：
   - `calculate_trade_fee(...)`
2. 基于当前 market + orderbook 的预估：
   - `build_taker_fee_preview(...)`

当前示例扩展**没有**接入这套能力。
也就是说，这次改动只补通用能力和展示，不改变现有策略决策。

## 导入方式

```python
from decimal import Decimal

from polymarket_trader.domain.fees import calculate_trade_fee, build_taker_fee_preview
```

## 公式

当前实现遵循 Polymarket 文档公式：

`fee = C × feeRate × p × (1 - p)`

在本仓库里的对应关系是：

- `C = size_shares`
- `p = price`
- `feeRate = fee_rate_bps / 1000`

说明：

- 这里的 `fee_rate_bps` 按 Polymarket API 返回值解释，例如 `30 -> 0.03`
- 买单会额外给出 `fee_shares`
- 卖单手续费保持在 `USDC`
- maker 当前直接返回 `0`

## 直接计算示例

```python
from decimal import Decimal

from polymarket_trader.domain.fees import calculate_trade_fee

quote = calculate_trade_fee(
    price=Decimal("0.52"),
    size_shares=Decimal("100"),
    side="buy",
    fee_rate_bps=30,
)

print(quote.fee_usdc)    # 0.74880
print(quote.fee_shares)  # 1.44000
print(quote.charged_in)  # shares
```

## 预估示例

```python
from polymarket_trader.domain.fees import build_taker_fee_preview

preview = build_taker_fee_preview(
    market=context.market,
    orderbook=context.orderbook,
)

if preview is not None and preview.buy is not None:
    print(preview.buy.fee_usdc)
```

默认预估口径：

- `basis_size_shares = 100`
- 买单取 `best_ask`
- 卖单取 `best_bid`

如果没有盘口，返回 `None`。

## Admin API 展示

市场列表和单 market 详情现在会返回 `fee_preview`。

结构是：

```json
{
  "fee_preview": {
    "basis_size_shares": "100",
    "fee_rate_bps": 30,
    "buy": {
      "price": "0.52",
      "price_source": "best_ask",
      "fee_usdc": "0.74880",
      "fee_shares": "1.44000",
      "charged_in": "shares"
    },
    "sell": {
      "price": "0.48",
      "price_source": "best_bid",
      "fee_usdc": "0.74880",
      "fee_shares": null,
      "charged_in": "usdc"
    }
  }
}
```

注意：

- `fee_preview` 是热态派生视图
- 它依赖当前盘口和固定展示口径
- 它不是 `Market` 的静态字段，也不会落库

## 该怎么用

推荐：

- 二开策略里，直接拿 `context.market` 和 `context.orderbook` 调纯函数
- 管理台和脚本，直接消费 `fee_preview`

不推荐：

- 把 `fee_preview` 当成持久化市场事实
- 把它写回策略配置或数据库
- 默认把手续费直接并入当前扩展的 entry/exit/risk 逻辑
