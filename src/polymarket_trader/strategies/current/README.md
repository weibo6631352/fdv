# Current Strategy

这里是运行中的策略目录。

## 改哪里

- 改阈值：[config.py](./config.py)
- 改 discovery 和市场筛选：[market_filter.py](./market_filter.py)
- 改分配、入场、退出、恢复：[trading_strategy.py](./trading_strategy.py)
- 改订阅保留与移除：[subscription.py](./subscription.py)
- 看装配入口：[strategy.py](./strategy.py)

## 规则

- `build_discovery_queries()` 不是 WebSocket 订阅参数入口。
- 当前 WebSocket 订阅由框架根据 registry 自动生成。
- 策略只通过 discovery、universe 选择和订阅保留规则间接影响订阅范围。

## 验证

- `pytest -q`
- `ruff check .`
