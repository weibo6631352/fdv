# api 目录说明

该目录存放 FastAPI Admin API。

职责：
- 暴露健康检查、运行状态、markets、orders 和 portfolio 查询。
- 提供受控人工操作入口，例如暂停 market、取消 open SELL、cancel + replace。

约束：
- 不写策略判断和下单核心逻辑。
- 不绕过 Risk Manager 直接提交 FAK BUY。
- 查询只读取快照或仓储层数据，避免阻塞 P0 交易热路径。

