# Current Strategy

这里是仓库里唯一保留的策略目录。

- [strategy.py](./strategy.py)：运行时固定装配入口，也是当前实际运行的策略实现。
- [config.py](./config.py)：策略参数定义和结构化配置加载入口。
- `build_discovery_queries()`：声明远端扫描时要透传给 Gamma 的官方查询参数。
- `select_market()`：对扫描回来的 market 做最终准入判断。

注意：

- `build_discovery_queries()` 不是 WebSocket 订阅参数入口。
- 当前 WebSocket 订阅由框架根据 registry 自动生成。
- 策略只通过 discovery + universe 选择间接影响订阅范围。

如果要做二次开发，优先改这里，不要先去动 worker、执行链路和平台底座。
