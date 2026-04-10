# workers 目录说明

该目录存放常驻后台任务。

职责：
- Market discovery、Market WS、User WS、Strategy、Reconcile、Persistence 等 worker。
- 按优先级消费对应队列并调用应用服务。

约束：
- P0 worker 不得等待低优先级任务释放资源。
- P2 / P3 worker 只读取快照或提交异步请求，不反向阻塞交易链路。

