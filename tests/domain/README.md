# domain 测试目录说明

该目录存放纯业务规则单元测试。这里的测试应该快速、确定、无网络、无数据库，能在任何开发机器上直接运行。

## 覆盖范围

- `allocation.py`：等权预算、剩余资金释放、单 market 上限。
- `classifier.py`：Crypto 分类、FDV 命中、500M 命中、排除其他阈值。
- `risk.py`：价格、notional、tick size、min order、集中度和 open BUY 异常。
- `strategy.py`：FAK BUY intent、GTC SELL intent、skip reason。
- `orderbook.py`：best bid / ask、spread、可成交深度。
- `state_machine.py`：market 生命周期和异常状态。

## 必须保持的边界

- 不连接数据库。
- 不调用 Polymarket SDK。
- 不依赖 FastAPI。
- 金额和价格断言使用 `Decimal`。
- 拒绝结果要断言 reason，避免只有布尔值。

## 新增测试交接清单

新增 domain 规则时，需要测试：
- 正常通过路径。
- 明确拒绝路径。
- 边界值，例如 `0.60`、`0.6001`、min order size。
- 与审计相关的 reason / event name。

