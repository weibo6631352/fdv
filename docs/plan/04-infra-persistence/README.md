# 基础设施与持久化组

## 目标

负责 Polymarket 外部协议适配、内部 DTO 转换、数据库模型、仓储、outbox、本地可靠队列、Persistence Worker、配置和密钥约束。

## 可并行任务

| 任务 | Worker 入口 | 主要模块 |
| --- | --- | --- |
| Polymarket clients 与 schemas | [01-polymarket-clients-schemas](./01-polymarket-clients-schemas/README.md) | `src/fdv_trader/infra/polymarket` |
| DB 模型与 repository | [02-db-models-repositories](./02-db-models-repositories/README.md) | `src/fdv_trader/infra/db` |
| Outbox / Local Queue | [03-outbox-local-queue](./03-outbox-local-queue/README.md) | `src/fdv_trader/infra/outbox` |
| Persistence Worker | [04-persistence-worker](./04-persistence-worker/README.md) | `src/fdv_trader/workers/persistence_worker.py` |
| 配置与密钥 | [05-config-secrets](./05-config-secrets/README.md) | `src/fdv_trader/config.py`、`.env.example` |

## 并行边界

- 外部响应必须先转换为内部 DTO，再提供给 app/domain/runtime。
- 数据库用于审计、复盘、调试和恢复参考，不作为交易状态唯一真相来源。
- Persistence Worker 属于 P3，数据库失败不得阻塞交易主流程。
- 密钥、签名 payload、未脱敏 raw response 和账户敏感信息不得进入仓库、日志或注释。
