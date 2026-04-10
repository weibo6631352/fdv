# observability 目录说明

该目录存放审计、指标和 trace 能力。

职责：
- 生成并传播 `trace_id`。
- 记录 market discovery 到订单动作的完整审计事件。
- 维护交易延迟、队列深度、锁等待和执行器等待等指标。

约束：
- 交易热路径不得同步等待 PostgreSQL 或阻塞文件日志。
- raw response 必须限长和脱敏。

