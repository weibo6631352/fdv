# routes 目录说明

该目录存放 Admin API 的路由模块。路由模块负责 HTTP 边界，不负责业务决策。

## 文件职责

- `health.py`：当前暴露 `/health`，只做进程健康检查；`/ready` 作为 M4 readiness 路由后续补齐。
- `markets.py`：market 相关查询和后续暂停 / 恢复入口。
- `orders.py`：订单查询和后续 SELL cancel / replace 入口。
- `portfolio.py`：组合预算、exposure 和分配状态查询。

## 路由层只能做

- 解析 path / query / body。
- 调用 FastAPI dependency 获取应用服务。
- 做轻量请求校验。
- 返回统一 response schema。

## 路由层不能做

- 策略判断。
- 风控判断。
- 订单 payload 拼接。
- 签名、下单、撤单。
- 持有交易状态锁。
- 直接查询 Polymarket API。

## 交接清单

新增路由文件时，需要同步：
- 更新 [api README](../README.md)。
- 更新 [docs/api.md](../../../../docs/api.md) 中的接口类别说明。
- 增加 app service 或测试，不把逻辑写进 route。
