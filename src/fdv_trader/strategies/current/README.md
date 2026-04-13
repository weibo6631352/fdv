# Current Strategy

这里就是唯一保留的策略目录。

它同时承担三件事：

- `src/fdv_trader/strategies/current/strategy.py`

- runtime 固定装配入口
- 原 FDV 策略当前实现
- 后续二次开发的直接修改位置

如果你要做二次开发，直接改这里，不要去改平台 worker 和执行链路。
