# cli 目录说明

该目录存放命令行入口。CLI 用于启动服务和执行受控运维命令，但不承载业务规则。

## 职责

- 解析命令行参数。
- 加载配置。
- 启动 FastAPI 服务，或通过 Admin API 调用受控运维动作。
- 作为 Admin API 之外的受控人工操作入口。

## 允许依赖

- `fdv_trader.api.app`。
- `fdv_trader.config`。
- Admin API HTTP client。
- 标准库参数解析工具。

## 禁止行为

- 不直接调用 Polymarket SDK。
- 不直接拼接订单 payload。
- 不绕过 Risk Manager 下单。
- 不把长期后台循环写在 CLI 函数里；长期任务应放入 workers / runtime。

## 输入与输出

- 输入：命令行参数、环境变量配置，以及必要的 Admin API 调用参数。
- 输出：进程退出码、控制台摘要，以及命令触发的受控操作结果。

## 当前命令

- 详细运维用法见 [docs/operations.md](../../../docs/operations.md)。

- `fdv-trader run`
- `fdv-trader init-db`
- `fdv-trader config-summary`
- `fdv-trader status`
- `fdv-trader reconcile`
- `fdv-trader replay`
