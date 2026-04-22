# 前端开发清单

本文档只描述当前仓库这次前端管理台建设的实施范围、模块边界和执行清单。

## 1. 目标

前端要做成一个可二次开发的管理台，而不是把某个策略的页面硬写进通用框架里。

本次前端建设解决四件事：

1. 给现有 Admin API 提供可直接使用的管理台入口。
2. 把通用运行态、市场、订单、持仓、审计、人工操作做成稳定模块。
3. 把策略相关展示收口到单独扩展位，不把策略规则揉进通用页面。
4. 目录、共享组件和 API 访问层已经按模块拆开；新增策略或新增页面时只需要改对应模块。

## 2. 边界

### 2.1 通用层负责

- 应用壳体、导航、路由、主题和布局。
- API 客户端、错误处理、轮询和缓存。
- 页面路由与后端接口路径隔离，浏览器统一通过 `/api/*` 访问后端。
- 通用数据资源：runtime、workers、metrics、markets、orders、fills、positions、portfolio、audit-events、outbox、operations。
- 通用展示组件：状态卡片、表格、筛选栏、详情面板、表单、分页、刷新控制。
- 人工操作入口：reconcile、cancel / replace sell。

### 2.2 策略层负责

- 解释某个策略如何看待 market 状态。
- 展示某个策略专有的摘要、标签、说明和扩展面板。
- 在通用 market 数据上做策略语义映射。

### 2.3 明确不做

- 不在浏览器直接接 Polymarket。
- 不在前端复写策略判断逻辑。
- 不让通用组件依赖 `strategies.current` 的命名或阈值常量。
- 不通过前端绕过后端应用服务直接执行交易动作。

## 3. 目录设计

前端工程放在仓库顶层 `frontend/`，采用独立构建，不塞进 Python 包内部。

```text
frontend/
  src/
    app/                 # 应用壳体、路由、provider
    core/
      api/               # HTTP client、query key、资源访问
      config/            # 运行配置和环境变量
    shared/
      ui/                # 通用组件
      layout/            # 页面框架、导航、分栏
      utils/             # 格式化、字段提取、通用工具
    features/
      dashboard/         # 运行态总览
      markets/           # 市场列表、详情、价格与盘口
      orders/            # 订单列表、人工卖出修复
      positions/         # 持仓与 fills
      audit/             # 审计事件与 outbox
      operations/        # 手工 reconcile 等操作
    strategy/
      registry.ts        # 策略扩展注册入口
      current/           # 当前策略的前端扩展实现
```

约束：

- `shared/` 不能依赖 `features/`。
- `features/` 只能依赖 `shared/`、`core/` 和策略扩展接口，不能直接依赖具体策略实现。
- `strategy/current/` 可以依赖通用接口，但不能反向影响通用模块。

## 4. 页面范围

首批页面直接围绕当前 API 做：

1. 总览页
   - readiness、phase、worker 健康、portfolio 摘要、关键指标。
2. 市场页
   - 市场列表、费率筛选、详情抽屉、盘口、中间价、价格历史。
3. 订单页
   - open / all 订单查询、定位目标 market、人工 cancel / replace sell。
4. 持仓页
   - positions 与 fills。
5. 审计页
   - audit events 与 outbox pending。
6. 操作页
   - reconcile 提交与结果反馈。

## 5. 策略扩展设计

策略扩展位采用显式注册，而不是在通用页面里写 `if extension_module == "strategies.current"`。

策略扩展接口至少提供：

- dashboard 扩展面板
- market 行附加标签
- market 详情扩展区块
- 策略模块标题与说明

通用页面只认识扩展接口，不认识具体策略实现目录。

## 6. 已实现范围

- 已明确前端目标、边界和模块拆分。
- 已建立 `frontend/` 工程与 TypeScript 构建链路。
- 已建立通用 API client、错误模型和查询缓存。
- 已建立应用壳体、导航、页面路由和统一布局。
- 已建立通用 UI 组件：状态卡、数据表、筛选栏、空状态、加载态、详情面板。
- 已接入总览页：`/ready`、`/runtime`、`/workers`、`/metrics`、`/portfolio`。
- 已接入市场页：`/markets`、`/markets/detail`、`/markets/orderbook`、`/markets/midpoint`、`/markets/prices-history`。
- 已接入订单页：`/orders`、`/orders/replace`。
- 已接入持仓页：`/positions`、`/fills`。
- 已接入审计页：`/audit-events`、`/outbox/pending`。
- 已接入操作页：`/operations/reconcile`。
- 已建立策略扩展注册表与 `strategies.current` 对应前端扩展模块。
- 已补充运行说明、构建验证和开发命令。

## 7. 当前结果

当前仓库已经落下：

- `frontend/` React + TypeScript + Vite 工程。
- 通用 API 访问层：`src/core/api/`。
- 通用壳体和共享组件：`src/app/`、`src/shared/`。
- 业务页面：`src/features/`。
- 策略扩展槽：`src/strategy/registry.ts` 与 `src/strategy/current/`。
- 构建验证：`npm --prefix frontend run typecheck`、`lint`、`build` 已通过。

## 8. 本次执行顺序

1. 先搭前端工程和通用基础设施。
2. 再把总览页和市场页做出来，先把读操作跑通。
3. 再补订单、持仓、审计和操作页。
4. 最后把策略扩展位接上，把当前策略的解释性展示单独放进去。
