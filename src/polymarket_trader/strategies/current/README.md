# Current Strategy

这里是仓库里唯一保留的策略目录，也是二次开发优先落点。

- [strategy.py](./strategy.py)：运行时固定装配入口，只做模块装配和委托。
- [config.py](./config.py)：当前策略的业务参数，直接写 Python，不再读取 `.env` / `.json` / `.toml`。
- [market_filter.py](./market_filter.py)：远端 discovery 查询和最终 universe 筛选。
- [trading_strategy.py](./trading_strategy.py)：分配、入场、退出、恢复。
- [subscription.py](./subscription.py)：已筛出 market 的订阅保留与移除条件。

注意：

- `build_discovery_queries()` 不是 WebSocket 订阅参数入口。
- 当前 WebSocket 订阅由框架根据 registry 自动生成。
- 策略只通过 discovery、universe 选择和订阅保留规则间接影响订阅范围。

如果要做二次开发，优先改这里，不要先去动 worker、执行链路和平台底座。
