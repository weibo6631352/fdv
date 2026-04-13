# Current Strategy

这里是仓库里唯一保留的策略目录。

- [strategy.py](./strategy.py)：运行时固定装配入口，也是当前原始 FDV 策略实现。
- [config.py](./config.py)：策略参数定义和结构化配置加载入口。

如果要做二次开发，优先改这里，不要先去动 worker、执行链路和平台底座。
