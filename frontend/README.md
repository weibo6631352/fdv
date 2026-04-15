# 前端管理台

这个目录是 Polymarket Trader 的前端管理台工程。

## 目录边界

- `src/app/`：应用壳体、provider、路由。
- `src/core/api/`：HTTP client、DTO、资源访问函数。
- `src/shared/`：布局、通用组件、格式化工具。
- `src/features/`：总览、市场、订单、持仓、审计、操作。
- `src/strategy/`：策略扩展注册表和具体策略扩展实现。

约束：

- 通用页面不能直接依赖某个具体策略目录。
- 策略相关展示必须通过 `src/strategy/registry.ts` 挂接。
- 前端不直接连接 Polymarket，只访问后端 Admin API。

## 开发命令

在仓库根目录执行：

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

常用检查：

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

根目录也提供了打包脚本：

```bash
./build_dist.sh
./build_dist.sh --archive
```

- `./build_dist.sh`：产出 `frontend/dist`
- `./build_dist.sh --archive`：额外产出 `.dist-packages/frontend-dist.tar.gz`

## API 连接

- 前端统一通过 `/api/*` 访问后端 Admin API，这样页面路由和后端接口路径不会冲突。
- 开发模式默认通过 Vite proxy 把 `/api/*` 请求转发到 `http://127.0.0.1:8000`，并重写回后端原始接口路径。
- 如果后端不在这个地址，设置 `VITE_PROXY_TARGET`。
- 如果前端要直接访问另一个固定地址，设置 `VITE_API_BASE_URL`，例如 `http://127.0.0.1:8000` 或反向代理后的 `/api`。
- 示例文件见 `frontend/.env.example`。

## 二次开发入口

新增一个策略对应的前端展示时：

1. 在 `src/strategy/` 下新增该策略扩展模块。
2. 在 `src/strategy/registry.ts` 注册。
3. 通用页面通过扩展接口自动读取 badge、dashboard panel 和 market detail 扩展区块。
