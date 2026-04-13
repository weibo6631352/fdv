# Template Strategy

这个目录是二次开发模板，不会被 runtime 自动装配。

它不是玩具示例，而是原 FDV 策略在新框架下的完整模板实现。

固定策略入口是：

- `src/fdv_trader/strategies/current/strategy.py`

推荐做法：

1. 直接以 `template/strategy.py` 和 `template/config.py` 为起点修改
2. 按你的市场筛选、资金分配、入场、退出、恢复规则改代码
3. 用 `tests/strategies/contract/` 跑契约测试
4. 调 `fdv_trader.strategy_api.replay.run_entry_replay(...)` 做本地回放

模板已经带着原策略的完整五段职责：

- `select_market`
- `size_entry`
- `decide_entry`
- `decide_exit`
- `decide_recovery`
